"""
Teacher Studio — AI tạo giáo án (DOCX), đề kiểm tra, slide PPTX.
Dùng Gemini Pro (ưu tiên) qua AI Gateway; API key gắn bằng GEMINI_API_KEY.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from flask import current_app

from app.services.ai_service import _call_ai


SYSTEM_TEACHER = (
    "Bạn là chuyên gia cao cấp biên soạn giáo án, đề kiểm tra và học liệu Hoạt động trải nghiệm "
    "theo Chương trình GDPT 2018 Việt Nam. "
    "CHỈ dùng thông tin giáo viên cung cấp (lớp, môn, chủ đề, mô tả, yêu cầu thêm, ngôn ngữ, màu sắc). "
    "Không đổi chủ đề, không viết generic. "
    "Viết nội dung DÀI, chuẩn sư phạm, có tình huống thật ở trường Việt Nam, lời giáo viên và câu hỏi gợi ý. "
    "Trả về đúng JSON, không markdown."
)


def _teacher_brief(
    *,
    grade: str,
    subject: str,
    topic: str,
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    theme_color: str = "",
    theme_accent: str = "",
    extra_lines: str = "",
) -> str:
    return (
        "THÔNG TIN GIÁO VIÊN (bắt buộc bám sát từng dòng):\n"
        f"- Khối/Lớp: {grade}\n"
        f"- Môn học: {subject}\n"
        f"- Chủ đề: {topic}\n"
        f"- Mô tả: {description.strip() or '(không có mô tả — khai thác sâu đúng chủ đề trên)'}\n"
        f"- Ngôn ngữ soạn: {language}\n"
        f"- Yêu cầu thêm: {extra_requirements.strip() or '(không)'}\n"
        f"- Màu chủ đạo / nhấn: {theme_color or '-'} / {theme_accent or '-'}\n"
        + (f"{extra_lines.strip()}\n" if extra_lines else "")
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
                "question_text": f"Question {i}: Explain the meaning of “{topic}” and give one real-life example.",
                "question_type": "essay",
                "options": [],
                "correct_answer": f"A clear explanation of {topic} with a real example and personal connection.",
                "sample_answer": f"Define {topic}, explain why it matters, and give one school-life example.",
                "explanation": "Score ideas, examples, and organisation.",
                "points": 2,
            })
        elif qtype == "true_false":
            questions.append({
                "question_text": f"Question {i}: “{topic}” is an educational experiential activity.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": f"{topic} has educational value in experiential learning.",
                "points": 1,
            })
        elif qtype == "fill_blank":
            questions.append({
                "question_text": f"Question {i}: Complete: Experiential activities about {topic} help students practise ______.",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "life skills",
                "explanation": "Students name a skill or quality.",
                "points": 1,
            })
        else:
            questions.append({
                "question_text": f"Question {i}: Which idea best relates to {topic}?",
                "question_type": "multiple_choice",
                "options": [
                    f"A. A correct idea about {topic}",
                    "B. An unrelated concept",
                    "C. Incorrect information",
                    "D. None of the above",
                ],
                "correct_answer": f"A. A correct idea about {topic}",
                "explanation": f"Option A best matches {topic}.",
                "points": 1,
            })
    return {
        "title": f"Quiz: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "language": language,
        "passing_score": 60,
        "time_limit_minutes": 20,
        "questions": questions,
        "source": "template",
        "note": "Temporary English quiz template. Add a Gemini API key for a fuller paper.",
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
    for s in slides:
        if not s.get("notes"):
            s["notes"] = (
                f"Gợi ý giảng: trình bày slide “{s.get('title')}” bằng tiếng Anh; "
                f"hỏi học sinh 1–2 câu kiểm tra hiểu; liên hệ chủ đề {topic}."
            )
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
    language = "bilingual"
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
    )
    lang_rule = (
        "GIÁO ÁN SONG NGỮ BẮT BUỘC: mỗi mục có đủ tiếng Việt VÀ tiếng Anh, độ dài tương đương, "
        "không rút gọn một phía. title_vi + title_en; objectives_vi + objectives_en; "
        "knowledge/skills/qualities cả VI và EN; mỗi section có heading_vi/heading_en, content_vi/content_en, "
        "teacher_activity và student_activity bằng tiếng Việt, kèm teacher_activity_en / student_activity_en."
    )
    prompt = f"""
{brief}

Soạn GIÁO ÁN TRẢI NGHIỆM ĐẦY ĐỦ, DÀI, dùng được luôn trên lớp (không viết ngắn/sơ sài). JSON:
{{
  "title_vi": "...",
  "title_en": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "description": "diễn giải lại mô tả GV thành đoạn 4-6 câu",
  "duration_minutes": 45,
  "materials": ["đồ dùng cụ thể, có màu {theme_color}/{theme_accent} nếu trang trí"],
  "objectives_vi": ["năng lực/phẩm chất/kiến thức — mỗi mục 1-2 câu"],
  "objectives_en": ["..."],
  "knowledge_vi": ["kiến thức trọng tâm, mỗi ý 2-3 câu"],
  "knowledge_en": ["core knowledge, 2-3 sentences each"],
  "skills_vi": ["kỹ năng"],
  "skills_en": ["skills"],
  "qualities_vi": ["phẩm chất"],
  "qualities_en": ["qualities"],
  "core_content_vi": "Bài viết 180-280 chữ: kiến thức cốt lõi GV sẽ dạy, ví dụ thực tế trường Việt Nam, gắn đúng chủ đề và mô tả.",
  "core_content_en": "Full English equivalent of core_content_vi (not a short summary).",
  "sections": [
    {{
      "heading_vi": "...",
      "heading_en": "...",
      "duration": "7'",
      "content_vi": "8-14 câu: mục tiêu hoạt động, cách tiến hành từng bước, câu hỏi GV, câu trả lời dự kiến, sản phẩm HS.",
      "content_en": "...",
      "procedure_steps": ["Bước 1: ...", "Bước 2: ...", "Bước 3: ..."],
      "teacher_activity": "lời/hành động GV cụ thể (tiếng Việt)",
      "teacher_activity_en": "teacher talk/actions in English",
      "student_activity": "việc HS làm cụ thể (tiếng Việt)",
      "student_activity_en": "student actions in English",
      "expected_product": "sản phẩm/kết quả quan sát được",
      "questions": ["câu hỏi gợi mở 1", "câu hỏi 2"]
    }}
  ],
  "vocabulary": [
    {{"term": "English term", "meaning_vi": "...", "example": "câu ví dụ gắn chủ đề"}}
  ],
  "assessment": {{
    "methods": ["..."],
    "criteria": ["tiêu chí quan sát được"],
    "rubric": ["Đạt: ...", "Cần hỗ trợ: ..."]
  }},
  "homework": ["nhiệm vụ cụ thể, có hạn và sản phẩm"],
  "differentiation": "cách hỗ trợ HS yếu / nâng cao HS khá, 4-6 câu",
  "notes": "tổ chức sân/lớp, an toàn, dùng màu chủ đạo khi trang trí"
}}

YÊU CẦU BẮT BUỘC:
- {lang_rule}
- Đúng lớp {grade}, môn {subject}, ĐÚNG chủ đề "{topic}". Mọi ví dụ phải lấy từ mô tả/yêu cầu thêm (nếu có).
- 6-7 sections: Khởi động; Hình thành kiến thức; Trải nghiệm chính; Luyện tập/vận dụng; Trình bày sản phẩm; Phản ánh – đánh giá (có thể thêm Kết nối thực tiễn).
- Mỗi content_vi tối thiểu ~80 từ, có đối thoại GV–HS, không gạch đầu dòng chung chung.
- procedure_steps 3-5 bước/phần. vocabulary 8-12 từ. materials 6-10 mục.
- Nếu yêu cầu thêm nhắc hoạt động nhóm / thời gian / từ vựng / trang trí: phải thể hiện rõ trong sections/materials/notes.
Chỉ trả JSON hợp lệ.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=16384, json_mode=True, timeout=180,
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
    language = "en"
    num_questions = max(3, min(int(num_questions or 8), 20))
    types = quiz_types or ["multiple_choice"]
    types_text = ", ".join(types)
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
        extra_lines=(
            f"- Yêu cầu đề: {quiz_requirements or '(không)'}\n"
            f"- Loại câu: {types_text}\n"
            f"- Số câu: {num_questions}; Độ khó: {difficulty}"
        ),
    )
    lang_rule = (
        "STUDENT QUIZ IN ENGLISH ONLY. Write ALL titles, questions, options, sample answers and explanations in English. "
        "true_false options MUST be exactly [\"True\",\"False\"]. Do not use Vietnamese on the student paper."
    )
    prompt = f"""
{brief}

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
- true_false: options ["True","False"], correct_answer is True or False.
- fill_blank: no options; correct_answer is the missing English word/phrase.
- essay: no options; sample_answer is the marking key in English; points 2–3.
{lang_rule}
Questions must follow the teacher brief, not generic. Suitable for grade {grade}, Vietnam school context, written in English.
Return JSON only.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=8192, json_mode=True, timeout=150,
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
            "image_keyword": str(s.get("image_keyword") or topic)[:80],
            "image_scene": str(s.get("image_scene") or "")[:220],
            "notes": str(s.get("notes") or s.get("notes_vi") or ""),
        })
    return normalized


_VISUAL_GLOSSARY = (
    ("chào cờ", "vietnam school flag raising ceremony students"),
    ("chao co", "vietnam school flag raising ceremony students"),
    ("quốc kỳ", "vietnam red flag yellow star"),
    ("quoc ky", "vietnam red flag yellow star"),
    ("quốc ca", "students singing vietnam national anthem"),
    ("quoc ca", "students singing vietnam national anthem"),
    ("xếp hàng", "vietnamese students lining up schoolyard"),
    ("xep hang", "vietnamese students lining up schoolyard"),
    ("sân trường", "vietnam schoolyard students assembly"),
    ("san truong", "vietnam schoolyard students assembly"),
    ("tôn trọng", "students saluting vietnam national flag"),
    ("ton trong", "students saluting vietnam national flag"),
    ("cờ đỏ", "vietnam red flag yellow star"),
    ("sao vàng", "vietnam yellow star red flag"),
    ("lễ chào", "vietnam school monday flag ceremony"),
    ("đoàn kết", "vietnamese students holding hands school"),
    ("tái chế", "vietnam students recycling plastic bottles"),
    ("môi trường", "vietnam school green trees students"),
    ("nhóm", "vietnamese students teamwork classroom"),
    ("thảo luận", "vietnamese students discussion classroom"),
    ("viết", "students writing notebook classroom vietnam"),
    ("trình bày", "student presenting in front of class vietnam"),
)


def _visual_from_text(*parts: str) -> str:
    blob = " ".join(str(p or "") for p in parts).lower()
    hits = [en for vi, en in _VISUAL_GLOSSARY if vi in blob]
    if hits:
        return hits[0]
    return ""


def _enrich_image_keywords(slides: list[dict], topic: str) -> list[dict]:
    """Keyword ảnh lấy từ tiêu đề + bullets từng slide, ưu tiên cảnh Việt Nam."""
    topic_visual = _visual_from_text(topic) or "vietnamese students school experiential activity"
    weak = {
        "", "education", "learning", "background", "abstract", "image", "photo",
        "topic", "slide", "content", "school", "students",
    }
    for s in slides:
        title = s.get("title") or ""
        bullets = s.get("bullets") or s.get("left_bullets") or []
        body = " ".join(str(b) for b in bullets[:3])
        mapped = _visual_from_text(title, body, topic)
        kw = (s.get("image_keyword") or "").strip()
        if kw.lower() in weak or kw.lower() == (topic or "").lower() or len(kw.split()) < 3:
            words = [w for w in title.replace("/", " ").split() if len(w) > 3][:5]
            derived = " ".join(words)
            s["image_keyword"] = (mapped or f"{derived} {topic_visual}").strip()[:80]
        elif mapped and "vietnam" not in kw.lower() and "viet" not in kw.lower():
            s["image_keyword"] = f"{kw} {mapped}".strip()[:80]
        if not (s.get("image_scene") or "").strip():
            cue = (body or title or topic).strip()[:160]
            s["image_scene"] = (
                f"Vietnamese secondary school scene for '{title}': {cue}. "
                "Natural classroom or schoolyard, matching this slide only."
            )[:220]
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
    language = "en"
    slide_count = max(6, min(int(slide_count or 12), 16))
    context_hint = ""
    follow_lesson = ""
    if lesson_context:
        sections_brief = []
        for s in (lesson_context.get("sections") or [])[:8]:
            sections_brief.append({
                "heading": s.get("heading_en") or s.get("heading_vi"),
                "duration": s.get("duration"),
                "content": ((s.get("content_en") or s.get("content_vi") or "")[:420]),
                "teacher": s.get("teacher_activity"),
                "student": s.get("student_activity"),
            })
        brief = {
            "title": lesson_context.get("title_en") or lesson_context.get("title_vi"),
            "description": (lesson_context.get("description") or "")[:400],
            "core_content": (lesson_context.get("core_content_en") or lesson_context.get("core_content_vi") or "")[:500],
            "objectives": (lesson_context.get("objectives_en") or lesson_context.get("objectives_vi") or [])[:6],
            "materials": (lesson_context.get("materials") or [])[:8],
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
            + json.dumps(brief, ensure_ascii=False)[:4500]
        )
        follow_lesson = (
            "- Map slides to lesson sections in order (khởi động → kiến thức → hoạt động → luyện tập → phản ánh).\n"
            "- Include one slide for objectives and one vocabulary/table slide from the lesson.\n"
            "- Reuse key points from section content; keep the requested language.\n"
        )

    brief_txt = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
    )
    lang_rule = (
        "SLIDE TEXT IN ENGLISH ONLY (title, subtitle, bullets, table, cards, closing). "
        "Presenter notes (field notes) MUST be Vietnamese for the teacher: cách giảng slide này, câu hỏi hỏi HS, thời gian gợi ý. "
        "image_keyword and image_scene in English."
    )
    system_en = (
        "You are a senior instructional designer creating classroom PowerPoint decks "
        "for Vietnamese secondary schools (Hoạt động trải nghiệm). "
        "On-slide text is English. Teacher presenter notes are Vietnamese. "
        "When a lesson plan is provided, the slides MUST follow that plan closely. "
        "Prefer Vietnamese school / Vietnam imagery (cờ đỏ sao vàng, học sinh Việt Nam, sân trường). "
        "image_keyword and image_scene must describe the EXACT photo of THAT slide, Vietnam-first. "
        "Return valid JSON only."
    )

    def _ask(prompt_text: str):
        return _call_ai(
            prompt_text, system_en, max_tokens=12288, json_mode=True, timeout=180,
        )

    prompt = f"""
{brief_txt}

Tạo dàn ý PowerPoint JSON (slide đẹp, giảng được, ảnh sát từng slide):
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
      "image_keyword": "5-8 English nouns describing the EXACT scene of THIS slide, Vietnam school",
      "image_scene": "1 sentence: the exact photograph to generate (who, where, action), Vietnam school, matching THIS slide",
      "notes": "Vietnamese teacher notes: how to teach this slide, questions to ask, timing"
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
{follow_lesson}- image_keyword MUST describe the photo of THAT slide only (derived from slide title + bullets), ưu tiên Việt Nam.
- image_scene: 1 câu cụ thể (ai, ở đâu, đang làm gì) để AI vẽ/chụp đúng nội dung slide, không generic.
  Ví dụ: chào cờ → "vietnam school flag raising ceremony students red flag yellow star";
  xếp hàng → "vietnamese students lining up schoolyard";
  quốc ca → "students singing vietnam national anthem";
  tôn trọng → "students saluting vietnam national flag".
- Cấm keyword chung: background, abstract, education, learning, template.
- Mỗi content slide có 1 ý kiến thức thật lấy từ giáo án/mô tả, không slogan.
- Màu chủ đạo: {theme_color} / {theme_accent}.
{context_hint}
"""
    text, source = _ask(prompt)
    data = _parse_json(text) if text else None
    slides = (data or {}).get("slides") if data else None

    if not data or not isinstance(slides, list) or len(slides) < 4:
        retry_prompt = f"""
Return PowerPoint JSON with {slide_count} slides for topic "{topic}".
On-slide text English; notes Vietnamese for the teacher. {lang_rule}
Follow the lesson plan if provided. Layouts: title, content, two_column, table, cards, closing.
Vietnam-first image_keyword per slide matching THAT slide title. Valid JSON only.
{brief_txt}
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


def _parse_timecode(value, default: float = 0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", ".")
    parts = raw.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return default
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 1:
        return nums[0]
    return default


def _normalize_subtitles(raw) -> list[dict]:
    out = []
    for i, line in enumerate(raw or []):
        if isinstance(line, str):
            text = line.strip()
            start = float(i * 6)
            end = start + 6
        elif isinstance(line, dict):
            text = str(line.get("text") or "").strip()
            start = _parse_timecode(line.get("start"), i * 6)
            end = _parse_timecode(line.get("end"), start + 6)
        else:
            continue
        if not text:
            continue
        if end <= start:
            end = start + 6
        out.append({"start": start, "end": end, "text": text})
    return out


normalize_subtitles = _normalize_subtitles


def _mcq_items(raw, limit: int = 6) -> list[dict]:
    out = []
    for q in raw or []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or q.get("question_text") or "").strip()
        if not text:
            continue
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:4]
        while len(opts) < 4:
            opts.append(f"Option {len(opts) + 1}")
        correct = str(q.get("correct_answer") or "").strip()
        if correct and correct not in opts:
            letter = correct[0].upper() if correct else ""
            if letter in "ABCD" and ord(letter) - 65 < len(opts):
                correct = opts[ord(letter) - 65]
            else:
                correct = next((o for o in opts if correct.lower() in o.lower()), opts[0])
        out.append({
            "question": text,
            "type": "multiple_choice",
            "options": opts,
            "correct_answer": correct or opts[0],
        })
        if len(out) >= limit:
            break
    return out


def _fallback_eight_step(grade: str, subject: str, topic: str, description: str = "") -> dict:
    return {
        "title": topic or "Experiential lesson",
        "description": description or f"An 8-step English lesson on {topic} for {grade}.",
        "duration_minutes": 45,
        "warm_up": {
            "questions": [
                {
                    "question": f"What do you already know about {topic}?",
                    "type": "multiple_choice",
                    "options": ["I have tried it", "I have heard about it", "I am not sure", "It is new to me"],
                    "correct_answer": "I have heard about it",
                },
                {
                    "question": f"Why is {topic} useful for students?",
                    "type": "multiple_choice",
                    "options": ["It builds life skills", "It wastes time", "It is only for tests", "It has no meaning"],
                    "correct_answer": "It builds life skills",
                },
            ]
        },
        "vocabulary": [
            {"word": "experience", "ipa": "/ɪkˈspɪəriəns/", "meaning_vi": "trải nghiệm", "example_sentence": "We learn by experience.", "category": "school_life", "difficulty": "beginner"},
            {"word": "community", "ipa": "/kəˈmjuːnəti/", "meaning_vi": "cộng đồng", "example_sentence": "Students serve the community.", "category": "community", "difficulty": "beginner"},
            {"word": "respect", "ipa": "/rɪˈspekt/", "meaning_vi": "tôn trọng", "example_sentence": "We show respect at the flag ceremony.", "category": "culture", "difficulty": "beginner"},
            {"word": "collaborate", "ipa": "/kəˈlæbəreɪt/", "meaning_vi": "hợp tác", "example_sentence": "Collaborate with your group.", "category": "school_life", "difficulty": "intermediate"},
            {"word": "reflect", "ipa": "/rɪˈflekt/", "meaning_vi": "phản ánh", "example_sentence": "Reflect on what you learned today.", "category": "school_life", "difficulty": "intermediate"},
            {"word": topic.split()[0] if topic else "activity", "ipa": "", "meaning_vi": topic or "hoạt động", "example_sentence": f"Today we explore {topic}.", "category": "school_life", "difficulty": "beginner"},
        ],
        "reading": {
            "passage": (
                f"{topic} is an important experiential activity for {grade} students. "
                "In Vietnamese schools, students learn by doing: they observe, discuss, and create a small product. "
                "This helps them use English, work in teams, and connect the lesson with real life."
            ),
            "translation": (
                f"{topic} là hoạt động trải nghiệm quan trọng với học sinh {grade}. "
                "Học sinh học bằng cách làm: quan sát, thảo luận và tạo sản phẩm nhỏ. "
                "Điều này giúp các em dùng tiếng Anh, làm việc nhóm và gắn bài học với đời sống."
            ),
            "questions": [
                {
                    "question": f"What is the main idea of the passage about {topic}?",
                    "type": "multiple_choice",
                    "options": ["Learning by doing", "Memorising only", "Skipping group work", "Avoiding English"],
                    "correct_answer": "Learning by doing",
                },
                {
                    "question": "What do students create in the activity?",
                    "type": "multiple_choice",
                    "options": ["A small product", "A long exam", "Nothing", "Only homework"],
                    "correct_answer": "A small product",
                },
            ],
        },
        "video": {
            "video_prompt": f"Short classroom video: Vietnamese students practising {topic} in English.",
            "subtitles": [
                {"start": 0, "end": 8, "text": f"Today we learn about {topic}."},
                {"start": 8, "end": 16, "text": "Watch, discuss, and try it yourself."},
            ],
        },
        "interactive": {
            "activities": [{
                "type": "matching",
                "title": f"Match ideas about {topic}",
                "description": "Match each English word with its meaning.",
                "pairs": [
                    {"left": "experience", "right": "trải nghiệm"},
                    {"left": "respect", "right": "tôn trọng"},
                    {"left": "collaborate", "right": "hợp tác"},
                    {"left": "reflect", "right": "phản ánh"},
                ],
            }]
        },
        "practice": {
            "instructions": (
                f"Work in groups of 4. Create a mini poster or 5-sentence talk about {topic}. "
                "Use at least 5 new words. Upload a photo or a short recording of your product."
            ),
            "allow_upload": True,
        },
        "reflection": {
            "instructions": (
                f"Write 80–120 words in English: What did you learn about {topic}? "
                "What will you do differently next time? Give one real example from school life."
            ),
        },
        "quiz": {
            "title": f"Quiz: {topic}",
            "time_limit_minutes": 20,
            "passing_score": 60,
            "questions": [
                {
                    "question_text": f"Which sentence best describes {topic}?",
                    "question_type": "multiple_choice",
                    "options": [
                        f"A. An experiential activity about {topic}",
                        "B. An unrelated idea",
                        "C. Incorrect information",
                        "D. None of the above",
                    ],
                    "correct_answer": f"A. An experiential activity about {topic}",
                    "explanation": "Choose the option that matches the lesson topic.",
                    "points": 1,
                },
                {
                    "question_text": f"{topic} can help students practise English and life skills.",
                    "question_type": "true_false",
                    "options": ["True", "False"],
                    "correct_answer": "True",
                    "points": 1,
                },
                {
                    "question_text": f"Write 4–6 sentences about why {topic} matters in your school.",
                    "question_type": "essay",
                    "options": [],
                    "correct_answer": "Clear idea, example, and personal connection.",
                    "sample_answer": "Students explain the activity, give an example, and say what they will do.",
                    "points": 2,
                },
            ],
        },
        "source": "template",
        "language": "en",
    }


def _normalize_eight_step(data: dict, grade: str, subject: str, topic: str, description: str = "") -> dict:
    fb = _fallback_eight_step(grade, subject, topic, description)
    if not isinstance(data, dict):
        return fb
    warm = data.get("warm_up") if isinstance(data.get("warm_up"), dict) else {}
    reading = data.get("reading") if isinstance(data.get("reading"), dict) else {}
    video = data.get("video") if isinstance(data.get("video"), dict) else {}
    interactive = data.get("interactive") if isinstance(data.get("interactive"), dict) else {}
    practice = data.get("practice") if isinstance(data.get("practice"), dict) else {}
    reflection = data.get("reflection") if isinstance(data.get("reflection"), dict) else {}
    quiz = data.get("quiz") if isinstance(data.get("quiz"), dict) else {}
    vocab = []
    for v in data.get("vocabulary") or []:
        if not isinstance(v, dict):
            continue
        word = str(v.get("word") or v.get("term") or "").strip()
        if not word:
            continue
        vocab.append({
            "word": word,
            "ipa": str(v.get("ipa") or ""),
            "meaning_vi": str(v.get("meaning_vi") or v.get("meaning") or ""),
            "example_sentence": str(v.get("example_sentence") or v.get("example") or ""),
            "category": str(v.get("category") or "school_life"),
            "difficulty": str(v.get("difficulty") or "beginner"),
        })
    activities = []
    for act in interactive.get("activities") or []:
        if isinstance(act, dict) and act.get("type"):
            activities.append(act)
    if not activities:
        activities = fb["interactive"]["activities"]
    from app.routes.quizzes import normalize_quiz_questions
    quiz_qs = normalize_quiz_questions(quiz.get("questions") or fb["quiz"]["questions"])
    out = {
        "title": str(data.get("title") or topic)[:160],
        "description": str(data.get("description") or description or fb["description"])[:800],
        "duration_minutes": int(data.get("duration_minutes") or 45),
        "warm_up": {"questions": _mcq_items(warm.get("questions") or fb["warm_up"]["questions"], 6)},
        "vocabulary": vocab or fb["vocabulary"],
        "reading": {
            "passage": str(reading.get("passage") or fb["reading"]["passage"]),
            "translation": str(reading.get("translation") or fb["reading"]["translation"]),
            "questions": _mcq_items(reading.get("questions") or fb["reading"]["questions"], 6),
        },
        "video": {
            "video_prompt": str(video.get("video_prompt") or fb["video"]["video_prompt"]),
            "subtitles": _normalize_subtitles(video.get("subtitles") or fb["video"]["subtitles"]),
        },
        "interactive": {"activities": activities[:3]},
        "practice": {
            "instructions": str(practice.get("instructions") or fb["practice"]["instructions"]),
            "allow_upload": True,
        },
        "reflection": {
            "instructions": str(reflection.get("instructions") or fb["reflection"]["instructions"]),
        },
        "quiz": {
            "title": str(quiz.get("title") or f"Quiz: {topic}"),
            "time_limit_minutes": int(quiz.get("time_limit_minutes") or 20),
            "passing_score": int(quiz.get("passing_score") or 60),
            "questions": quiz_qs or fb["quiz"]["questions"],
        },
        "source": data.get("source") or "ai",
        "language": "en",
        "grade": grade,
        "subject": subject,
        "topic": topic,
    }
    return out


def generate_eight_step_draft(
    grade: str,
    subject: str,
    topic: str,
    description: str = "",
    extra_requirements: str = "",
    lesson_context: dict | None = None,
    quiz_context: dict | None = None,
) -> dict:
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language="en",
        description=description, extra_requirements=extra_requirements,
    )
    context = ""
    if lesson_context:
        context += "Lesson plan JSON (reuse ideas, do not copy layout):\n" + json.dumps({
            "title_en": lesson_context.get("title_en"),
            "objectives_en": (lesson_context.get("objectives_en") or [])[:5],
            "vocabulary": (lesson_context.get("vocabulary") or [])[:8],
            "core": (lesson_context.get("core_content_en") or lesson_context.get("core_content_vi") or "")[:500],
        }, ensure_ascii=False)[:2500]
    if quiz_context and quiz_context.get("questions"):
        context += "\nExisting quiz (may reuse):\n" + json.dumps(quiz_context.get("questions")[:8], ensure_ascii=False)[:2000]
    prompt = f"""
{brief}

Create a complete 8-step Experiential Learning LESSON for the student platform.
Student-facing text in ENGLISH. Vocabulary meanings and reading translation in Vietnamese.
JSON only:
{{
  "title": "English lesson title",
  "description": "2-3 English sentences",
  "duration_minutes": 45,
  "warm_up": {{
    "questions": [
      {{"question": "...", "type": "multiple_choice", "options": ["A","B","C","D"], "correct_answer": "A"}}
    ]
  }},
  "vocabulary": [
    {{"word": "English word", "ipa": "/.../", "meaning_vi": "...", "example_sentence": "...", "category": "school_life", "difficulty": "beginner"}}
  ],
  "reading": {{
    "passage": "180-260 words English reading about the topic, Vietnam school context",
    "translation": "Vietnamese translation",
    "questions": [
      {{"question": "...", "type": "multiple_choice", "options": ["A","B","C","D"], "correct_answer": "A"}}
    ]
  }},
  "video": {{
    "video_prompt": "what classroom video the teacher should upload",
    "subtitles": [{{"start": "00:00:00", "end": "00:00:06", "text": "English line"}}]
  }},
  "interactive": {{
    "activities": [
      {{"type": "matching", "title": "...", "description": "...", "pairs": [{{"left": "EN", "right": "VI"}}]}}
    ]
  }},
  "practice": {{"instructions": "English task for students, with a product to upload", "allow_upload": true}},
  "reflection": {{"instructions": "English journal prompt 80-120 words"}},
  "quiz": {{
    "title": "...",
    "time_limit_minutes": 20,
    "passing_score": 60,
    "questions": [
      {{"question_text": "...", "question_type": "multiple_choice", "options": ["A. ...","B. ...","C. ...","D. ..."], "correct_answer": "A. ...", "explanation": "...", "points": 1}}
    ]
  }}
}}
Rules:
- Exactly this topic / grade / subject.
- warm_up: 4 questions. reading: 4 questions. vocabulary: 8-10 words.
- quiz: 6-8 questions in ENGLISH, mix multiple_choice + true_false + 1 essay. true_false options ["True","False"].
- matching: 4-6 pairs.
{context}
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=12288, json_mode=True, timeout=180,
    )
    data = _parse_json(text) if text else None
    out = _normalize_eight_step(data or {}, grade, subject, topic, description)
    if not data:
        out["source"] = "template"
        out["note"] = "Bản mẫu 8 bước. Gắn API key Gemini để AI soạn đầy đủ hơn."
    else:
        out["source"] = source or "ai"
        out.pop("note", None)
    return out


def build_docx_bytes(lesson: dict) -> bytes:
    from app.services.docx_builder import build_rich_docx_bytes
    return build_rich_docx_bytes(lesson)


def build_pptx_bytes(deck: dict) -> bytes:
    from app.services.pptx_builder import build_rich_pptx_bytes
    return build_rich_pptx_bytes(deck)


def quiz_to_docx_bytes(quiz: dict) -> bytes:
    from app.services.docx_builder import build_quiz_docx_bytes
    return build_quiz_docx_bytes(quiz)
