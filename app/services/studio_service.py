"""
Teacher Studio — AI tạo giáo án (DOCX), đề kiểm tra, slide PPTX.
Dùng Gemini (ưu tiên) qua AI Gateway hiện có; API key gắn bằng GEMINI_API_KEY.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from flask import current_app

from app.services.ai_service import _call_ai


SYSTEM_TEACHER = (
    "Bạn là trợ lý biên soạn học liệu song ngữ Việt–Anh cho giáo dục phổ thông Việt Nam. "
    "Trả lời đúng schema JSON được yêu cầu, không thêm markdown/code fence ngoài JSON. "
    "Nội dung sư phạm rõ ràng, phù hợp học sinh phổ thông, có phần tiếng Việt và tiếng Anh."
)


def _strip_json(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _repair_json(text: str) -> str:
    """Sửa lỗi JSON thường gặp / bị cắt giữa chừng."""
    s = text.strip()
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Đóng ngoặc còn thiếu nếu bị truncate
    open_curly = s.count("{") - s.count("}")
    open_square = s.count("[") - s.count("]")
    if open_square > 0 or open_curly > 0:
        # cắt về sau dấu đóng hợp lệ gần nhất trong chuỗi chưa hoàn chỉnh
        # rồi bổ sung ngoặc
        s = s.rstrip().rstrip(",")
        # nếu đang giữa string, đóng string
        if s.count('"') % 2 == 1:
            s += '"'
        s = re.sub(r",\s*$", "", s)
        s += "]" * max(0, open_square)
        s += "}" * max(0, open_curly)
        s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _parse_json(text: str) -> dict | None:
    raw = _strip_json(text)
    for candidate in (raw, _repair_json(raw)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    current_app.logger.warning("Studio AI JSON parse failed")
    return None


def _brief_requirements(description: str = "", extra: str = "", quiz_req: str = "") -> str:
    parts = []
    if description:
        parts.append(f"MÔ TẢ BẮT BUỘC bám sát: {description}")
    if extra:
        parts.append(f"YÊU CẦU THÊM (phải thể hiện trong nội dung): {extra}")
    if quiz_req:
        parts.append(f"YÊU CẦU ĐỀ: {quiz_req}")
    return "\n".join(parts) if parts else "Không có yêu cầu thêm."


def _fallback_lesson(grade: str, subject: str, topic: str, language: str, description: str = "") -> dict:
    return {
        "title_vi": f"Giáo án trải nghiệm: {topic}",
        "title_en": f"Experiential Lesson Plan: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "description": description,
        "duration_minutes": 45,
        "materials": [
            "Projector / slides",
            "Worksheet handout",
            "Board and markers",
            "Group activity cards",
        ],
        "objectives_vi": [
            f"Hiểu khái niệm cơ bản về {topic}",
            "Áp dụng kiến thức vào tình huống thực tế",
            "Phát triển kỹ năng giao tiếp bằng tiếng Anh liên quan chủ đề",
            "Phản ánh và đánh giá quá trình học tập trải nghiệm",
        ],
        "objectives_en": [
            f"Understand basic concepts of {topic}",
            "Apply knowledge in real-life situations",
            "Develop English communication related to the topic",
            "Reflect on the experiential learning process",
        ],
        "sections": [
            {
                "heading_vi": "Khởi động",
                "heading_en": "Warm-up",
                "duration": "5'",
                "content_vi": f"Giáo viên giới thiệu chủ đề {topic} qua câu hỏi mở và hình ảnh; kích hoạt kiến thức nền của học sinh.",
                "content_en": f"Teacher introduces {topic} with open questions and visuals to activate prior knowledge.",
                "teacher_activity": "Đặt câu hỏi mở, chiếu hình ảnh",
                "student_activity": "Trả lời ngắn, chia sẻ trải nghiệm",
            },
            {
                "heading_vi": "Nội dung chính",
                "heading_en": "Main content",
                "duration": "15'",
                "content_vi": f"Trình bày kiến thức cốt lõi về {topic} (lớp {grade} – môn {subject}) kèm ví dụ minh họa.",
                "content_en": f"Present core knowledge about {topic} (grade {grade} – {subject}) with clear examples.",
                "teacher_activity": "Giảng giải, kiểm tra hiểu",
                "student_activity": "Ghi chú, hỏi đáp",
            },
            {
                "heading_vi": "Hoạt động trải nghiệm",
                "heading_en": "Experiential activity",
                "duration": "15'",
                "content_vi": "Học sinh làm việc nhóm, thảo luận và tạo sản phẩm nhỏ liên quan chủ đề, trình bày bằng tiếng Anh.",
                "content_en": "Students work in groups, discuss, create a mini product, and present in English.",
                "teacher_activity": "Quan sát, hỗ trợ nhóm",
                "student_activity": "Thảo luận nhóm, trình bày",
            },
            {
                "heading_vi": "Phản ánh & đánh giá",
                "heading_en": "Reflection & assessment",
                "duration": "10'",
                "content_vi": "Học sinh viết 3 điều đã học; giáo viên nhận xét nhanh và giao nhiệm vụ về nhà.",
                "content_en": "Students write 3 takeaways; teacher gives quick feedback and assigns homework.",
                "teacher_activity": "Nhận xét, tổng kết",
                "student_activity": "Phản ánh, hoàn thành exit ticket",
            },
        ],
        "vocabulary": [
            {"term": "experience", "meaning_vi": "trải nghiệm", "example": "Learning by experience helps students remember better."},
            {"term": "concept", "meaning_vi": "khái niệm", "example": f"Today we learn the main concept of {topic}."},
            {"term": "apply", "meaning_vi": "áp dụng", "example": "Apply the idea in a real situation."},
            {"term": "reflect", "meaning_vi": "phản ánh", "example": "Reflect on what you learned today."},
            {"term": "collaborate", "meaning_vi": "hợp tác", "example": "Collaborate with your group to finish the task."},
        ],
        "assessment": {
            "methods": ["Observation", "Oral check", "Exit ticket"],
            "criteria": ["Participation", "Correct concepts", "Application"],
        },
        "homework": [
            f"Review key ideas about {topic}.",
            "Write 5 English sentences using new vocabulary.",
            "Prepare one real-life example for the next lesson.",
        ],
        "source": "template",
        "note": "Bản mẫu tạm (chưa có GEMINI_API_KEY hoặc AI lỗi). Gắn key để tạo nội dung đầy đủ hơn.",
        "language": language,
    }


def _fallback_quiz(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int,
    quiz_types: list | None = None,
    language: str = "vi",
) -> dict:
    types = quiz_types or ["multiple_choice"]
    questions = []
    for i in range(1, num_questions + 1):
        qtype = types[(i - 1) % len(types)]
        if qtype == "essay":
            questions.append({
                "question_text": f"Câu {i}: Em hãy trình bày suy nghĩ / ý nghĩa của chủ đề {topic}.",
                "question_type": "essay",
                "options": [],
                "correct_answer": f"Bài viết nêu rõ nội dung, ví dụ thực tế và liên hệ {topic}.",
                "sample_answer": f"Học sinh nêu khái niệm, ý nghĩa và một ví dụ gắn với {topic}.",
                "explanation": "Chấm theo ý chính, lập luận và ví dụ.",
                "points": 2,
            })
        elif qtype == "true_false":
            questions.append({
                "question_text": f"Câu {i}: {topic} là hoạt động có ý nghĩa giáo dục.",
                "question_type": "true_false",
                "options": ["Đúng", "Sai"],
                "correct_answer": "Đúng",
                "explanation": f"Chủ đề {topic} mang ý nghĩa giáo dục.",
                "points": 1,
            })
        elif qtype == "fill_blank":
            questions.append({
                "question_text": f"Câu {i}: Điền từ còn thiếu: Hoạt động {topic} giúp học sinh rèn luyện ______.",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "kỹ năng / phẩm chất",
                "explanation": "Học sinh nêu kỹ năng hoặc phẩm chất phù hợp.",
                "points": 1,
            })
        else:
            questions.append({
                "question_text": f"Câu {i}: Khái niệm nào liên quan đến {topic}?",
                "question_type": "multiple_choice",
                "options": [
                    f"A. Nội dung đúng về {topic}",
                    "B. Khái niệm không liên quan",
                    "C. Thông tin sai",
                    "D. Không có đáp án",
                ],
                "correct_answer": f"A. Nội dung đúng về {topic}",
                "explanation": f"Đáp án A phù hợp nhất với chủ đề {topic}.",
                "points": 1,
            })
    return {
        "title": f"Đề kiểm tra: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "language": language,
        "passing_score": 60,
        "time_limit_minutes": 20,
        "questions": questions,
        "source": "template",
        "note": "Đề mẫu tạm. Admin nhập API key để AI tạo đề chuyên sâu hơn.",
    }


def _fallback_slides(grade: str, subject: str, topic: str, slide_count: int, language: str = "vi") -> dict:
    slides = [
        {
            "layout": "title",
            "title": topic,
            "subtitle": f"{subject} · Experiential Learning",
            "bullets": [grade, subject, "Hands-on exploration"],
            "image_keyword": topic,
            "notes": "Opening slide",
        },
        {
            "layout": "content",
            "title": "Learning Objectives",
            "bullets": ["Understand core concepts", "Practice in groups", "Reflect and apply"],
            "image_keyword": "classroom students",
        },
        {
            "layout": "two_column",
            "title": "Warm-up & Context",
            "left_title": "Warm-up",
            "right_title": "Real life",
            "left_bullets": ["Open questions", "Share experiences"],
            "right_bullets": ["Local examples", "Daily connections"],
            "image_keyword": "discussion",
        },
        {
            "layout": "cards",
            "title": f"Core Ideas: {topic}",
            "bullets": ["Define", "Explore", "Apply"],
            "image_keyword": topic,
        },
        {
            "layout": "table",
            "title": "Key Vocabulary",
            "table": {
                "headers": ["Term", "Meaning", "Example"],
                "rows": [
                    ["concept", "main idea", f"We study {topic}."],
                    ["practice", "guided activity", "Work in pairs."],
                    ["reflect", "think back", "What did I learn?"],
                ],
            },
            "bullets": ["concept", "practice", "reflect"],
        },
        {
            "layout": "content",
            "title": "Group Activity",
            "bullets": ["Discuss in teams", "Create a mini product", "Present findings"],
            "image_keyword": "teamwork",
        },
        {
            "layout": "two_column",
            "title": "Examples & Practice",
            "left_title": "Examples",
            "right_title": "Quick check",
            "left_bullets": ["Situation 1", "Situation 2"],
            "right_bullets": ["Quiz question", "Peer feedback"],
        },
        {
            "layout": "content",
            "title": "Reflection",
            "bullets": ["I learned...", "I will apply...", "I still wonder..."],
            "image_keyword": "notebook writing",
        },
        {
            "layout": "table",
            "title": "Lesson Summary",
            "table": {
                "headers": ["Focus", "Action", "Outcome"],
                "rows": [
                    ["Knowledge", "Explain key ideas", "Clear understanding"],
                    ["Skills", "Collaborate", "Shared product"],
                    ["Attitude", "Care & responsibility", "Positive habits"],
                ],
            },
        },
        {
            "layout": "closing",
            "title": "Thank You",
            "bullets": ["Questions welcome", "See you next time"],
            "image_keyword": "celebration",
        },
    ]
    return {
        "title": f"Slides: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "language": language or "vi",
        "slides": slides[: max(6, min(slide_count, 16))],
        "source": "template",
        "note": "Bản slide mẫu (AI chưa sẵn sàng).",
    }


def generate_lesson_draft(
    grade: str,
    subject: str,
    topic: str,
    language: str = "bilingual",
    extra_requirements: str = "",
    description: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
) -> dict:
    req = _brief_requirements(description, extra_requirements)
    prompt = f"""
Tạo giáo án trải nghiệm ĐẦY ĐỦ theo JSON (nội dung sư phạm chi tiết, không viết quá ngắn):
{{
  "title_vi": "...",
  "title_en": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "description": "{description}",
  "duration_minutes": 45,
  "materials": ["...", "..."],
  "objectives_vi": ["...", "...", "...", "..."],
  "objectives_en": ["...", "...", "...", "..."],
  "sections": [
    {{
      "heading_vi": "...",
      "heading_en": "...",
      "duration": "5'",
      "content_vi": "đoạn 3-6 câu chi tiết",
      "content_en": "3-6 full sentences",
      "teacher_activity": "...",
      "student_activity": "..."
    }}
  ],
  "vocabulary": [
    {{"term": "...", "meaning_vi": "...", "example": "English sentence"}}
  ],
  "assessment": {{
    "methods": ["...", "..."],
    "criteria": ["...", "..."]
  }},
  "homework": ["...", "...", "..."],
  "notes": "ghi chú ngắn cho giáo viên"
}}

Yêu cầu BẮT BUỘC:
- 5-6 sections (Khởi động, Kiến thức, Trải nghiệm, Luyện tập, Phản ánh/Đánh giá, ...)
- Mỗi content_vi/content_en đủ ý, rõ ràng, phù hợp lớp {grade}, môn {subject}
- vocabulary 6-10 mục
- Ngôn ngữ ưu tiên: {language} (vi = viết kỹ tiếng Việt; en = English; bilingual = cả hai)
- Màu chủ đạo (ghi vào notes nếu cần đồ dùng/trang trí): {theme_color} / nhấn {theme_accent}
- {req}
Chỉ trả về JSON hợp lệ.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=6000, json_mode=True, timeout=120,
    )
    data = _parse_json(text) if text else None
    if not data or not (data.get("sections") or data.get("objectives_vi")):
        return _fallback_lesson(grade, subject, topic, language, description)
    data.setdefault("grade", grade)
    data.setdefault("subject", subject)
    data.setdefault("topic", topic)
    data.setdefault("description", description)
    data.setdefault("duration_minutes", 45)
    data["source"] = source or "ai"
    data["language"] = language
    data["theme_color"] = theme_color
    data["theme_accent"] = theme_accent
    data.pop("note", None)
    return data


def generate_quiz_draft(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int = 8,
    difficulty: str = "mixed",
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    quiz_types: list | None = None,
    quiz_requirements: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
) -> dict:
    num_questions = max(3, min(int(num_questions or 8), 20))
    types = quiz_types or ["multiple_choice"]
    types_text = ", ".join(types)
    req = _brief_requirements(description, extra_requirements, quiz_requirements)
    lang_rule = {
        "vi": "Viết TOÀN BỘ câu hỏi, đáp án, giải thích bằng tiếng Việt.",
        "en": "Write ALL questions, options, explanations in English.",
        "bilingual": "Câu hỏi tiếng Việt; có thể thêm thuật ngữ English trong ngoặc.",
    }.get(language, "Viết câu hỏi bằng tiếng Việt.")
    prompt = f"""
Tạo đề kiểm tra JSON — PHẢI đúng loại câu và yêu cầu giáo viên:
{{
  "title": "...",
  "grade": "...",
  "subject": "...",
  "topic": "...",
  "description": "{description}",
  "passing_score": 60,
  "time_limit_minutes": 20,
  "questions": [
    {{
      "question_text": "...",
      "question_type": "multiple_choice|true_false|fill_blank|essay",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A. ... hoặc đáp án điền/Đúng-Sai",
      "sample_answer": "gợi ý chấm tự luận (nếu essay)",
      "explanation": "...",
      "points": 1
    }}
  ]
}}

Lớp: {grade}; Môn: {subject}; Chủ đề: {topic}.
Số câu: {num_questions}; Độ khó: {difficulty}.
Loại câu BẮT BUỘC dùng (phân bổ xen kẽ, đủ các loại đã chọn): {types_text}.
- multiple_choice: 4 lựa chọn A–D, correct_answer khớp 1 option.
- true_false: options ["Đúng","Sai"], correct_answer là Đúng hoặc Sai.
- fill_blank: không cần options, correct_answer là từ/cụm cần điền.
- essay: không options; sample_answer là ý chính để giáo viên chấm; points 2–3.
{lang_rule}
{req}
Nội dung sát chủ đề, thực tế Việt Nam, phù hợp học sinh {grade}.
Chỉ trả về JSON.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=4000, json_mode=True, timeout=90,
    )
    data = _parse_json(text) if text else None
    if not data or not data.get("questions"):
        return _fallback_quiz(grade, subject, topic, num_questions, types, language)
    from app.routes.quizzes import normalize_quiz_questions
    data["questions"] = normalize_quiz_questions(data.get("questions"))
    if not data["questions"]:
        return _fallback_quiz(grade, subject, topic, num_questions, types, language)
    data["source"] = source or "ai"
    data.setdefault("grade", grade)
    data.setdefault("subject", subject)
    data.setdefault("topic", topic)
    data.setdefault("description", description)
    data["language"] = language
    data["quiz_types"] = types
    data["theme_color"] = theme_color
    data["theme_accent"] = theme_accent
    data.pop("note", None)
    return data


def _normalize_pptx_slides(slides: list, topic: str, language: str = "vi") -> list[dict]:
    layouts_ok = {"title", "content", "two_column", "table", "cards", "closing"}
    normalized = []
    total = len(slides)
    for idx, s in enumerate(slides[:16]):
        if not isinstance(s, dict):
            continue
        layout = str(s.get("layout") or "").lower().strip()
        if layout not in layouts_ok:
            if idx == 0:
                layout = "title"
            elif idx >= total - 1:
                layout = "closing"
            elif s.get("table"):
                layout = "table"
            elif s.get("left_bullets") or s.get("right_bullets"):
                layout = "two_column"
            else:
                layout = "content"

        def _listify(val, limit=8):
            if isinstance(val, str):
                items = [b.strip() for b in val.split("\n") if b.strip()]
            elif isinstance(val, list):
                items = [str(b).strip() for b in val if str(b).strip()]
            else:
                items = []
            return items[:limit]

        bullets = _listify(s.get("bullets"), 8)
        left = _listify(s.get("left_bullets"), 6)
        right = _listify(s.get("right_bullets"), 6)
        table = s.get("table") if isinstance(s.get("table"), dict) else None
        if table:
            headers = [str(h) for h in (table.get("headers") or [])][:5]
            rows = []
            for row in (table.get("rows") or [])[:6]:
                if isinstance(row, list):
                    rows.append([str(c) for c in row][:5])
            table = {"headers": headers or ["Item", "Details", "Notes"], "rows": rows}

        if not bullets and not left and not table and layout not in ("title", "closing"):
            bullets = ["Key idea", "Example", "Class activity"]

        title = str(s.get("title") or topic)
        if language == "en" and " / " in title:
            title = title.split(" / ")[0].strip()
        title = title[:110]

        normalized.append({
            "layout": layout,
            "title": title,
            "subtitle": str(s.get("subtitle") or "")[:120],
            "bullets": bullets,
            "left_title": str(s.get("left_title") or "Overview")[:40],
            "right_title": str(s.get("right_title") or "Practice")[:40],
            "left_bullets": left,
            "right_bullets": right,
            "table": table,
            "image_keyword": str(s.get("image_keyword") or topic)[:60],
            "notes": str(s.get("notes") or ""),
        })
    return normalized


def _enrich_image_keywords(slides: list[dict], topic: str) -> list[dict]:
    """Ensure each slide has a concrete, content-related image keyword."""
    topic_l = (topic or "").lower()
    # Topic-level visual anchors
    topic_visual = "classroom students learning"
    if any(k in topic_l for k in ("chào cờ", "chao co", "flag", "cờ", "assembly", "national")):
        topic_visual = "school flag ceremony students vietnam"
    elif any(k in topic_l for k in ("recycl", "tái chế", "tai che", "waste")):
        topic_visual = "recycling bins students"
    elif any(k in topic_l for k in ("prime", "nguyên tố", "nguyen to")):
        topic_visual = "mathematics numbers classroom"

    weak = {"", "education", "learning", "background", "abstract", "image", "photo", "topic"}
    for s in slides:
        title = (s.get("title") or "").lower()
        kw = (s.get("image_keyword") or "").strip()
        if kw.lower() in weak or kw.lower() == (topic or "").lower():
            # Derive from title words + topic visual
            words = [w for w in title.replace("/", " ").split() if len(w) > 3][:4]
            derived = " ".join(words) if words else topic_visual
            s["image_keyword"] = f"{derived} {topic_visual}".strip()[:70]
        # Flag-ceremony specific overrides by title cues
        if any(k in title for k in ("flag", "anthem", "ceremony", "assembly", "respect", "line up")):
            s["image_keyword"] = (s.get("image_keyword") or "") + " school flag ceremony"
            s["image_keyword"] = s["image_keyword"][:70]
    return slides


def generate_pptx_draft(
    grade: str,
    subject: str,
    topic: str,
    slide_count: int = 12,
    lesson_context: dict | None = None,
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
) -> dict:
    slide_count = max(6, min(int(slide_count or 12), 16))
    context_hint = ""
    follow_lesson = ""
    if lesson_context:
        sections_brief = []
        for s in (lesson_context.get("sections") or [])[:8]:
            sections_brief.append({
                "heading": s.get("heading_en") or s.get("heading_vi"),
                "duration": s.get("duration"),
                "content": ((s.get("content_en") or s.get("content_vi") or "")[:220]),
                "teacher": s.get("teacher_activity"),
                "student": s.get("student_activity"),
            })
        brief = {
            "title": lesson_context.get("title_en") or lesson_context.get("title_vi"),
            "objectives": (lesson_context.get("objectives_en") or lesson_context.get("objectives_vi") or [])[:5],
            "materials": (lesson_context.get("materials") or [])[:5],
            "sections": sections_brief,
            "vocabulary": [
                {"term": v.get("term"), "meaning": v.get("meaning_vi")}
                for v in (lesson_context.get("vocabulary") or [])[:8]
            ],
            "assessment": lesson_context.get("assessment"),
            "homework": lesson_context.get("homework"),
        }
        context_hint = (
            "CRITICAL: Build the PowerPoint STRICTLY from this lesson plan / report. "
            "Keep the same teaching flow and ideas (do not invent a different lesson):\n"
            + json.dumps(brief, ensure_ascii=False)[:3500]
        )
        follow_lesson = (
            "- Map slides to lesson sections in order (khởi động → kiến thức → hoạt động → luyện tập → phản ánh).\n"
            "- Include one slide for objectives and one vocabulary/table slide from the lesson.\n"
            "- Reuse key points from section content; keep the requested language.\n"
        )

    req = _brief_requirements(description, extra_requirements)
    lang_rule = {
        "vi": "TOÀN BỘ chữ trên slide bằng tiếng Việt (title, bullets, table, notes). image_keyword viết tiếng Anh để tìm ảnh.",
        "en": "ALL slide text in English. image_keyword in English.",
        "bilingual": "Title tiếng Việt; bullets tiếng Việt, có thể kèm thuật ngữ English trong ngoặc. image_keyword tiếng Anh.",
    }.get(language, "Chữ trên slide bằng tiếng Việt. image_keyword tiếng Anh.")
    system_en = (
        "You are an instructional designer creating classroom PowerPoint decks "
        "for Vietnamese secondary schools (Hoạt động trải nghiệm). "
        "When a lesson plan is provided, the slides MUST follow that plan closely. "
        "Prefer Vietnamese school / Vietnam imagery (cờ đỏ sao vàng, học sinh Việt Nam, sân trường). "
        "image_keyword must describe a real photo matching the slide content, Vietnam-first. "
        "Return valid JSON only."
    )

    def _ask(prompt_text: str):
        return _call_ai(
            prompt_text, system_en, max_tokens=8192, json_mode=True, timeout=120,
        )

    prompt = f"""
Tạo dàn ý PowerPoint JSON:
{{
  "title": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "language": "{language}",
  "slides": [
    {{
      "layout": "title|content|two_column|table|cards|closing",
      "title": "...",
      "subtitle": "optional",
      "bullets": ["teaching bullets"],
      "left_title": "optional",
      "right_title": "optional",
      "left_bullets": ["..."],
      "right_bullets": ["..."],
      "table": {{"headers": ["A","B","C"], "rows": [["1","2","3"]]}},
      "image_keyword": "concrete English nouns + Vietnam for a related photo",
      "notes": "presenter notes"
    }}
  ]
}}

Rules:
- Exactly {slide_count} slides.
- {lang_rule}
- Slide 1 layout=title; last slide layout=closing.
- Include at least one layout=table, one layout=two_column, and one layout=cards.
- Content slides: 4–6 bullets, mỗi bullet 8–20 từ.
- two_column: 4 bullets mỗi cột.
- cards: 3–4 cards.
- table: 4–6 hàng sát nội dung.
{follow_lesson}- image_keyword MUST match THAT slide, ưu tiên Việt Nam
  (chào cờ → "vietnam school flag raising ceremony students red flag yellow star";
  sân trường → "vietnamese students lining up schoolyard";
  quốc ca → "students singing vietnam national anthem").
- Never use generic keywords like "background", "abstract", or "education" alone.
- Màu chủ đạo giáo viên chọn: {theme_color}, nhấn {theme_accent} (ghi vào notes nếu cần).
- {req}
Grade: {grade}; Subject: {subject}; Topic: {topic}.
{context_hint}
"""
    text, source = _ask(prompt)
    data = _parse_json(text) if text else None
    slides = (data or {}).get("slides") if data else None

    if not data or not isinstance(slides, list) or len(slides) < 4:
        retry_prompt = f"""
Return PowerPoint JSON with {slide_count} slides for topic "{topic}".
Language: {language}. {lang_rule}
Follow the lesson plan if provided. Layouts: title, content, two_column, table, cards, closing.
Vietnam-first image_keyword per slide. Valid JSON only.
{req}
{context_hint[:1500]}
"""
        text2, source2 = _ask(retry_prompt)
        data2 = _parse_json(text2) if text2 else None
        if data2 and isinstance(data2.get("slides"), list) and len(data2["slides"]) >= 4:
            data, source, slides = data2, source2 or source, data2["slides"]

    if not data or not isinstance(slides, list) or len(slides) < 4:
        return _fallback_slides(grade, subject, topic, slide_count, language)

    normalized = _normalize_pptx_slides(slides, topic, language)
    normalized = _enrich_image_keywords(normalized, topic)
    if len(normalized) < 4:
        return _fallback_slides(grade, subject, topic, slide_count, language)
    data["slides"] = normalized
    data["source"] = source or "ai"
    data["language"] = language
    data["theme_color"] = theme_color
    data["theme_accent"] = theme_accent
    data["description"] = description
    data["based_on_lesson"] = bool(lesson_context)
    data.setdefault("grade", grade)
    data.setdefault("subject", subject)
    data.setdefault("topic", topic)
    data.pop("note", None)
    return data


def build_docx_bytes(lesson: dict) -> bytes:
    from app.services.docx_builder import build_rich_docx_bytes
    return build_rich_docx_bytes(lesson)


def build_pptx_bytes(deck: dict) -> bytes:
    from app.services.pptx_builder import build_rich_pptx_bytes
    return build_rich_pptx_bytes(deck)


def quiz_to_docx_bytes(quiz: dict) -> bytes:
    from app.services.docx_builder import build_quiz_docx_bytes
    return build_quiz_docx_bytes(quiz)
