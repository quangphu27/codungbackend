from openai import OpenAI
from flask import current_app


def _get_client():
    api_key = current_app.config.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _fallback_response(prompt: str) -> str:
    return (
        "Xin lỗi, dịch vụ AI chưa được cấu hình. "
        "Vui lòng liên hệ giáo viên để được hỗ trợ thêm."
    )


def ask_question(question: str, context: str = "") -> dict:
    client = _get_client()
    if not client:
        return {"answer": _fallback_response(question), "source": "fallback"}

    system = (
        "Bạn là trợ lý học tiếng Anh cho học sinh Việt Nam. "
        "Trả lời bằng tiếng Việt, giải thích rõ ràng và dễ hiểu."
    )
    user_content = question
    if context:
        user_content = f"Ngữ cảnh: {context}\n\nCâu hỏi: {question}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        max_tokens=800,
    )
    return {
        "answer": response.choices[0].message.content,
        "source": "openai",
    }


def explain_vocabulary(word: str, custom_explanation: str = "") -> dict:
    if custom_explanation:
        return {"explanation": custom_explanation, "source": "teacher"}

    client = _get_client()
    if not client:
        return {"explanation": _fallback_response(word), "source": "fallback"}

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Giải thích từ vựng tiếng Anh cho học sinh Việt Nam.",
            },
            {
                "role": "user",
                "content": (
                    f"Giải thích từ '{word}' bằng tiếng Việt. "
                    "Bao gồm: nghĩa, IPA, ví dụ câu, cách dùng."
                ),
            },
        ],
        max_tokens=600,
    )
    return {
        "explanation": response.choices[0].message.content,
        "source": "openai",
    }


def translate_text(text: str, target_lang: str = "vi") -> dict:
    client = _get_client()
    if not client:
        return {"translation": text, "source": "fallback"}

    lang_map = {"vi": "tiếng Việt", "en": "tiếng Anh"}
    target = lang_map.get(target_lang, target_lang)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": f"Dịch đoạn văn sau sang {target}, chỉ trả về bản dịch:\n\n{text}",
            }
        ],
        max_tokens=1000,
    )
    return {
        "translation": response.choices[0].message.content,
        "source": "openai",
    }


def summarize_journal(content: str) -> dict:
    client = _get_client()
    if not client:
        return {"summary": "Tóm tắt không khả dụng.", "source": "fallback"}

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": (
                    "Tóm tắt nhật ký phản ánh học tập sau bằng tiếng Việt "
                    "(3-5 câu), nêu điểm mạnh và gợi ý cải thiện:\n\n"
                    f"{content}"
                ),
            }
        ],
        max_tokens=400,
    )
    return {
        "summary": response.choices[0].message.content,
        "source": "openai",
    }


def generate_career_analysis(answers: list) -> dict:
    client = _get_client()
    answers_text = "\n".join(
        f"- {a.get('question', '')}: {a.get('answer', '')}" for a in answers
    )

    if not client:
        return {
            "strengths": ["Giao tiếp", "Học hỏi"],
            "weaknesses": ["Cần cải thiện kỹ năng chuyên môn"],
            "career_suggestions": ["Giáo viên", "Hướng dẫn viên du lịch"],
            "learning_roadmap": "Tiếp tục phát triển kỹ năng tiếng Anh và kỹ năng mềm.",
            "development_plan": "Tham gia các hoạt động trải nghiệm thực tế.",
            "source": "fallback",
        }

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Bạn là chuyên gia hướng nghiệp. Phân tích kết quả khảo sát "
                    "và trả về JSON với keys: strengths, weaknesses, "
                    "career_suggestions, learning_roadmap, development_plan."
                ),
            },
            {"role": "user", "content": answers_text},
        ],
        max_tokens=1200,
        response_format={"type": "json_object"},
    )

    import json

    try:
        result = json.loads(response.choices[0].message.content)
        result["source"] = "openai"
        return result
    except json.JSONDecodeError:
        return {
            "strengths": [],
            "weaknesses": [],
            "career_suggestions": [],
            "learning_roadmap": response.choices[0].message.content,
            "development_plan": "",
            "source": "openai",
        }
