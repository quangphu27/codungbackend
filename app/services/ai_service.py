"""
AI Service – Gemini Pro/4 (paid) + image models + OpenAI fallback + Local KB
Priority: Local DB/KB → Gemini API → OpenAI API → Fallback message
"""
import os
from flask import current_app


# ──────────────────────────────────────────────
# Client helpers – REST-based (không phụ thuộc SDK version)
# ──────────────────────────────────────────────

# Bản trả phí: Pro/Argon trước, Flash làm dự phòng nếu model chưa mở trên project
GEMINI_MODELS = [
    "gemini-4-argon",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro",
    "gemini-2.5-pro",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

GEMINI_IMAGE_MODELS = [
    "gemini-3-pro-image",
    "gemini-nano-banana-2.1",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
]

GEMINI_REST_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _text_models() -> list[str]:
    preferred = ""
    try:
        preferred = (current_app.config.get("GEMINI_TEXT_MODEL") or os.getenv("GEMINI_TEXT_MODEL") or "").strip()
    except Exception:
        preferred = (os.getenv("GEMINI_TEXT_MODEL") or "").strip()
    models = list(GEMINI_MODELS)
    if preferred and preferred not in models:
        models.insert(0, preferred)
    elif preferred:
        models = [preferred] + [m for m in models if m != preferred]
    return models


def _image_models() -> list[str]:
    preferred = ""
    try:
        preferred = (current_app.config.get("GEMINI_IMAGE_MODEL") or os.getenv("GEMINI_IMAGE_MODEL") or "").strip()
    except Exception:
        preferred = (os.getenv("GEMINI_IMAGE_MODEL") or "").strip()
    models = list(GEMINI_IMAGE_MODELS)
    if preferred and preferred not in models:
        models.insert(0, preferred)
    elif preferred:
        models = [preferred] + [m for m in models if m != preferred]
    return models


def _call_gemini(
    prompt: str,
    system: str = "",
    *,
    json_mode: bool = False,
    timeout: int = 30,
    max_output_tokens: int = 2048,
) -> str:
    """Gọi Gemini qua REST HTTP – không dùng SDK để tránh lỗi thư viện."""
    import json
    from app.services.secret_store import get_gemini_api_key
    api_key = get_gemini_api_key()
    if not api_key:
        return None

    contents = []
    if system:
        contents.append({"role": "user",  "parts": [{"text": system}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I will follow the instructions."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    generation_config = {
        "temperature": 0.25 if json_mode else 0.7,
        "maxOutputTokens": max(256, int(max_output_tokens or 2048)),
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    body = {"contents": contents, "generationConfig": generation_config}
    payload = json.dumps(body).encode()

    for model_name in _text_models():
        url = GEMINI_REST_URL.format(model=model_name, key=api_key)
        try:
            import urllib.request
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = json.loads(res.read())
                candidates = data.get("candidates") or []
                if not candidates:
                    current_app.logger.warning(f"Gemini empty candidates: {model_name}")
                    continue
                parts = (candidates[0].get("content") or {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))
                if not text:
                    text = "".join(p.get("text", "") for p in parts if p.get("text"))
                if not text:
                    finish = candidates[0].get("finishReason") or candidates[0].get("finish_reason")
                    current_app.logger.warning(f"Gemini empty text: {model_name} finish={finish}")
                    continue
                current_app.logger.info(f"Gemini OK: {model_name}")
                return text
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                current_app.logger.warning(f"Gemini quota: {model_name}, next...")
                continue
            elif "404" in err_str or "not found" in err_str.lower():
                current_app.logger.warning(f"Gemini model not found: {model_name}")
                continue
            elif "400" in err_str or "INVALID_ARGUMENT" in err_str:
                # Một số model không hỗ trợ responseMimeType → thử lại không JSON mode 1 lần
                if json_mode and "responseMimeType" in err_str.lower():
                    current_app.logger.warning(f"Gemini JSON mime unsupported on {model_name}, retry plain")
                    try:
                        plain_body = {
                            "contents": contents,
                            "generationConfig": {
                                "temperature": 0.4,
                                "maxOutputTokens": generation_config["maxOutputTokens"],
                            },
                        }
                        plain_payload = json.dumps(plain_body).encode()
                        req2 = urllib.request.Request(
                            url, data=plain_payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req2, timeout=timeout) as res2:
                            data2 = json.loads(res2.read())
                            parts2 = (data2["candidates"][0].get("content") or {}).get("parts") or []
                            text2 = "".join(p.get("text", "") for p in parts2 if p.get("text"))
                            if text2:
                                current_app.logger.info(f"Gemini OK (plain): {model_name}")
                                return text2
                    except Exception as e2:
                        current_app.logger.warning(f"Gemini plain retry fail ({model_name}): {str(e2)[:120]}")
                        continue
                current_app.logger.warning(f"Gemini 400 ({model_name}): {err_str[:120]}")
                continue
            else:
                current_app.logger.warning(f"Gemini error ({model_name}): {err_str[:120]}")
                continue

    current_app.logger.warning("All Gemini models failed")
    return None


def generate_slide_image(
    prompt: str,
    *,
    aspect_ratio: str = "4:3",
    timeout: int = 55,
) -> bytes | None:
    """Tạo ảnh minh họa bằng Gemini Image (Nano Banana Pro / 2.1). Trả về PNG/JPEG bytes."""
    import base64
    import json
    import urllib.request

    from app.services.secret_store import get_gemini_api_key

    api_key = get_gemini_api_key()
    if not api_key or not (prompt or "").strip():
        return None

    configs = [
        {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
        {"responseModalities": ["IMAGE"]},
        {"responseModalities": ["TEXT", "IMAGE"]},
    ]

    import urllib.error

    for model_name in _image_models():
        url = GEMINI_REST_URL.format(model=model_name, key=api_key)
        skip_model = False
        for cfg in configs:
            body = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": cfg,
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as res:
                    data = json.loads(res.read())
                parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                for part in parts:
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                    raw = inline.get("data")
                    mime = (inline.get("mimeType") or inline.get("mime_type") or "image/png").lower()
                    if raw and "image" in mime:
                        current_app.logger.info(f"Gemini image OK: {model_name}")
                        return base64.b64decode(raw)
            except urllib.error.HTTPError as e:
                body_txt = ""
                try:
                    body_txt = e.read().decode("utf-8", "ignore")[:180]
                except Exception:
                    pass
                if e.code == 404:
                    current_app.logger.warning(f"Gemini image model missing: {model_name}")
                    skip_model = True
                    break
                current_app.logger.warning(f"Gemini image ({model_name} {e.code}): {body_txt or str(e)[:140]}")
            except Exception as e:
                err = str(e)
                if "404" in err or "not found" in err.lower():
                    current_app.logger.warning(f"Gemini image model missing: {model_name}")
                    skip_model = True
                    break
                current_app.logger.warning(f"Gemini image ({model_name}): {err[:140]}")
        if skip_model:
            continue
    return None


def _call_openai(messages: list, max_tokens: int = 800) -> str:
    """Gọi OpenAI qua REST HTTP – không phụ thuộc SDK version."""
    import json, urllib.request
    from app.services.secret_store import get_openai_api_key
    api_key = get_openai_api_key()
    if not api_key:
        return None
    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.loads(res.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        current_app.logger.warning(f"OpenAI error: {str(e)[:120]}")
        return None


def _get_provider():
    """Xác định AI provider ưu tiên."""
    provider = current_app.config.get("AI_PROVIDER") or os.getenv("AI_PROVIDER", "gemini")
    return provider.lower()


def _call_ai(
    prompt: str,
    system: str = "",
    max_tokens: int = 800,
    *,
    json_mode: bool = False,
    timeout: int | None = None,
) -> tuple[str, str]:
    """
    Gọi AI theo thứ tự ưu tiên.
    Returns: (response_text, source_label)
    """
    provider = _get_provider()
    gemini_timeout = timeout or (120 if json_mode or max_tokens >= 1500 else 45)
    gemini_kwargs = {
        "json_mode": json_mode,
        "timeout": gemini_timeout,
        "max_output_tokens": max(max_tokens, 8192 if json_mode else 1024),
    }

    def _openai_messages():
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    if provider == "gemini":
        text = _call_gemini(prompt, system, **gemini_kwargs)
        if text:
            return text, "gemini"
        text = _call_openai(_openai_messages(), max_tokens)
        if text:
            return text, "openai"
    else:
        text = _call_openai(_openai_messages(), max_tokens)
        if text:
            return text, "openai"
        text = _call_gemini(prompt, system, **gemini_kwargs)
        if text:
            return text, "gemini"

    return None, None


# ──────────────────────────────────────────────
# PUBLIC FUNCTIONS
# ──────────────────────────────────────────────

def ask_question(question: str, context: str = "") -> dict:
    """Trả lời câu hỏi tiếng Anh."""
    # 1. Thử local KB trước
    try:
        from app.services.local_ai_service import ask_question_local
        local = ask_question_local(question)
        if local:
            return local
    except Exception:
        pass

    # 2. Gọi AI
    system = (
        "Bạn là trợ lý học tiếng Anh thông minh cho học sinh Việt Nam (lớp 9-12). "
        "Trả lời bằng tiếng Việt, rõ ràng, có cấu trúc (dùng markdown: **bold**, bullet points, code block). "
        "Nếu là ngữ pháp: nêu cấu trúc, cách dùng, ví dụ cụ thể. "
        "Nếu là từ vựng: giải thích nghĩa, IPA, ví dụ. "
        "Giữ câu trả lời súc tích, không quá 400 từ."
    )
    user_content = f"Ngữ cảnh: {context}\n\nCâu hỏi: {question}" if context else question
    
    text, source = _call_ai(user_content, system, 800)
    if text:
        return {"answer": text, "source": source}
    
    return {
        "answer": (
            "Xin lỗi, tôi chưa tìm thấy câu trả lời trong cơ sở dữ liệu.\n\n"
            "Hãy thử hỏi về:\n"
            "- Ngữ pháp: *thì hiện tại đơn, câu điều kiện, câu bị động...*\n"
            "- Từ vựng: nhập từ vào tab **Giải thích từ vựng**\n"
            "- Dịch thuật: nhập văn bản vào tab **Dịch thuật**"
        ),
        "source": "local_kb",
    }


def explain_vocabulary(word: str, custom_explanation: str = "", vocab_doc: dict = None) -> dict:
    """Giải thích từ vựng."""
    # 1. Giải thích tùy chỉnh từ giáo viên
    if custom_explanation:
        return {"explanation": custom_explanation, "source": "teacher"}
    
    # 2. Tra cứu database
    try:
        from app.services.local_ai_service import explain_vocabulary_local
        result = explain_vocabulary_local(word, vocab_doc)
        if result:
            return result
    except Exception:
        pass
    
    # 3. Gọi AI
    system = (
        "Bạn là từ điển tiếng Anh thông minh cho học sinh Việt Nam. "
        "Giải thích từ vựng theo định dạng markdown rõ ràng."
    )
    prompt = (
        f"Giải thích từ tiếng Anh: **{word}**\n\n"
        "Trình bày theo thứ tự:\n"
        "1. Phiên âm IPA\n"
        "2. Loại từ (noun/verb/adj/adv...)\n"
        "3. Nghĩa tiếng Việt (các nghĩa phổ biến)\n"
        "4. 3 câu ví dụ (kèm dịch tiếng Việt)\n"
        "5. Từ đồng nghĩa / trái nghĩa\n"
        "6. Collocations phổ biến (nếu có)\n"
        "Trả lời bằng tiếng Việt, dùng markdown."
    )
    
    text, source = _call_ai(prompt, system, 700)
    if text:
        return {"explanation": text, "source": source}
    
    return {
        "explanation": f"Không tìm thấy thông tin về từ **'{word}'**. Hãy kiểm tra chính tả và thử lại!",
        "source": "local_kb",
    }


def translate_text(text: str, target_lang: str = "auto", vocab_doc: dict = None) -> dict:
    """Dịch văn bản."""
    # 1. Nếu là từ đơn và có trong DB
    try:
        from app.services.local_ai_service import translate_local, _detect_language
        result = translate_local(text.strip(), vocab_doc)
        if result:
            return result
    except Exception:
        pass
    
    # 2. Gọi AI để dịch
    try:
        from app.services.local_ai_service import _detect_language
        detected = _detect_language(text)
    except Exception:
        detected = "en"
    
    if target_lang == "auto":
        if detected == "vi":
            target_lang = "en"
            target_name = "tiếng Anh"
        else:
            target_lang = "vi"
            target_name = "tiếng Việt"
    else:
        target_name = "tiếng Việt" if target_lang == "vi" else "tiếng Anh"
    
    prompt = (
        f"Dịch đoạn văn sau sang {target_name}.\n"
        "Chỉ trả về bản dịch, không giải thích thêm:\n\n"
        f"{text}"
    )
    
    text_result, source = _call_ai(prompt, "", 1000)
    if text_result:
        return {"translation": text_result, "source": source}
    
    return {"translation": text, "source": "local_kb"}


def summarize_journal(content: str) -> dict:
    """Tóm tắt nhật ký học tập."""
    system = "Bạn là giáo viên hỗ trợ học sinh cải thiện kỹ năng viết và phản ánh."
    prompt = (
        "Tóm tắt nhật ký phản ánh học tập sau bằng tiếng Việt (3-5 câu), "
        "nêu điểm mạnh và gợi ý cải thiện:\n\n"
        f"{content}"
    )
    
    text, source = _call_ai(prompt, system, 400)
    if text:
        return {"summary": text, "source": source}
    return {"summary": "Tóm tắt không khả dụng.", "source": "local_kb"}


def generate_examples(word: str, vocab_doc: dict = None) -> dict:
    """Tạo câu ví dụ cho từ."""
    # 1. Từ DB trước
    try:
        from app.services.local_ai_service import generate_examples_local
        result = generate_examples_local(word, vocab_doc)
        if result:
            return result
    except Exception:
        pass
    
    # 2. Gọi AI
    system = "Bạn là giáo viên tiếng Anh, chuyên tạo câu ví dụ thực tế cho học sinh Việt Nam."
    prompt = (
        f"Tạo 5 câu ví dụ đa dạng sử dụng từ **'{word}'** trong tiếng Anh, "
        "kèm bản dịch tiếng Việt. Sắp xếp từ dễ đến khó. "
        "Format: Câu tiếng Anh → Dịch tiếng Việt"
    )
    
    text, source = _call_ai(prompt, system, 600)
    if text:
        return {"answer": text, "source": source}
    
    return {
        "answer": f"Không thể tạo câu ví dụ cho từ **'{word}'** lúc này. Vui lòng thử lại!",
        "source": "local_kb",
    }


def generate_career_analysis(answers: list) -> dict:
    """Phân tích định hướng nghề nghiệp."""
    answers_text = "\n".join(
        f"- {a.get('question', '')}: {a.get('answer', '')}" for a in answers
    )
    
    system = (
        "Bạn là chuyên gia hướng nghiệp cho học sinh Việt Nam. "
        "Phân tích kết quả khảo sát và trả về JSON với keys: "
        "strengths, weaknesses, career_suggestions, learning_roadmap, development_plan."
    )
    
    text, source = _call_ai(answers_text, system, 1200)
    
    if text:
        import json
        try:
            # Tìm JSON trong response (Gemini có thể thêm markdown)
            json_match = __import__('re').search(r'\{.*\}', text, __import__('re').DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = json.loads(text)
            result["source"] = source
            return result
        except json.JSONDecodeError:
            return {
                "strengths": ["Giao tiếp", "Sáng tạo"],
                "weaknesses": ["Cần phát triển kỹ năng chuyên môn"],
                "career_suggestions": ["Giáo viên", "Hướng dẫn viên du lịch", "Biên phiên dịch"],
                "learning_roadmap": text[:500] if text else "Tiếp tục phát triển kỹ năng tiếng Anh.",
                "development_plan": "Tham gia các hoạt động trải nghiệm thực tế.",
                "source": source,
            }
    
    return {
        "strengths": ["Giao tiếp", "Học hỏi nhanh"],
        "weaknesses": ["Cần cải thiện kỹ năng chuyên môn"],
        "career_suggestions": ["Giáo viên", "Hướng dẫn viên du lịch"],
        "learning_roadmap": "Tiếp tục phát triển kỹ năng tiếng Anh và kỹ năng mềm.",
        "development_plan": "Tham gia các hoạt động trải nghiệm thực tế.",
        "source": "local_kb",
    }
