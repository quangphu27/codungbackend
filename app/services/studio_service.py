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


def _fallback_lesson(grade: str, subject: str, topic: str, language: str) -> dict:
    return {
        "title_vi": f"Giáo án trải nghiệm: {topic}",
        "title_en": f"Experiential Lesson Plan: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
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


def _fallback_quiz(grade: str, subject: str, topic: str, num_questions: int) -> dict:
    questions = []
    for i in range(1, num_questions + 1):
        questions.append({
            "question_text": f"Câu {i}: Khái niệm nào liên quan đến {topic}?",
            "question_type": "multiple_choice",
            "options": [
                f"A. Khái niệm đúng về {topic}",
                "B. Khái niệm không liên quan",
                "C. Thông tin sai",
                "D. Không có đáp án",
            ],
            "correct_answer": f"A. Khái niệm đúng về {topic}",
            "explanation": f"Đáp án A phù hợp nhất với chủ đề {topic}.",
            "points": 1,
        })
    return {
        "title": f"Đề kiểm tra: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "passing_score": 60,
        "time_limit_minutes": 20,
        "questions": questions,
        "source": "template",
        "note": "Đề mẫu tạm. Gắn GEMINI_API_KEY để AI tạo đề chuyên sâu hơn.",
    }


def _fallback_slides(grade: str, subject: str, topic: str, slide_count: int) -> dict:
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
        "language": "en",
        "slides": slides[: max(6, min(slide_count, 16))],
        "source": "template",
        "note": "Template deck (AI unavailable). Set GEMINI_API_KEY for richer English slides.",
    }


def generate_lesson_draft(
    grade: str,
    subject: str,
    topic: str,
    language: str = "bilingual",
    extra_requirements: str = "",
) -> dict:
    prompt = f"""
Tạo giáo án trải nghiệm ĐẦY ĐỦ theo JSON (nội dung sư phạm chi tiết, không viết quá ngắn):
{{
  "title_vi": "...",
  "title_en": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
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

Yêu cầu:
- 5-6 sections (Khởi động, Kiến thức, Trải nghiệm, Luyện tập, Phản ánh/Đánh giá, ...)
- Mỗi content_vi/content_en đủ ý, rõ ràng, phù hợp lớp {grade}
- vocabulary 6-10 mục
- Ngôn ngữ ưu tiên: {language}
- Yêu cầu thêm: {extra_requirements or "không"}
Chỉ trả về JSON hợp lệ.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=6000, json_mode=True, timeout=120,
    )
    data = _parse_json(text) if text else None
    if not data or not (data.get("sections") or data.get("objectives_vi")):
        return _fallback_lesson(grade, subject, topic, language)
    data.setdefault("grade", grade)
    data.setdefault("subject", subject)
    data.setdefault("topic", topic)
    data.setdefault("duration_minutes", 45)
    data["source"] = source or "ai"
    data["language"] = language
    data.pop("note", None)
    return data


def generate_quiz_draft(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int = 8,
    difficulty: str = "mixed",
) -> dict:
    num_questions = max(3, min(int(num_questions or 8), 20))
    prompt = f"""
Tạo đề kiểm tra trắc nghiệm JSON:
{{
  "title": "...",
  "grade": "...",
  "subject": "...",
  "topic": "...",
  "passing_score": 60,
  "time_limit_minutes": 20,
  "questions": [
    {{
      "question_text": "...",
      "question_type": "multiple_choice",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A. ...",
      "explanation": "...",
      "points": 1
    }}
  ]
}}

Lớp: {grade}; Môn: {subject}; Chủ đề: {topic};
Số câu: {num_questions}; Độ khó: {difficulty}.
Câu hỏi bằng tiếng Anh kèm gợi ý tiếng Việt trong explanation nếu cần.
Chỉ trả về JSON.
"""
    text, source = _call_ai(
        prompt, SYSTEM_TEACHER, max_tokens=4000, json_mode=True, timeout=90,
    )
    data = _parse_json(text) if text else None
    if not data or not data.get("questions"):
        return _fallback_quiz(grade, subject, topic, num_questions)
    from app.routes.quizzes import normalize_quiz_questions
    data["questions"] = normalize_quiz_questions(data.get("questions"))
    if not data["questions"]:
        return _fallback_quiz(grade, subject, topic, num_questions)
    data["source"] = source or "ai"
    data.setdefault("grade", grade)
    data.setdefault("subject", subject)
    data.setdefault("topic", topic)
    data.pop("note", None)
    return data


def _normalize_pptx_slides(slides: list, topic: str) -> list[dict]:
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

        # Strip Vietnamese leftovers from titles if mixed with " / "
        title = str(s.get("title") or topic)
        if " / " in title:
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
            "- Map slides to lesson sections in order (warm-up → main → activity → practice → reflection).\n"
            "- Include one slide for objectives and one vocabulary/table slide from the lesson.\n"
            "- Reuse key points from section content; expand into clear English teaching bullets.\n"
        )

    system_en = (
        "You are an instructional designer creating polished English-only classroom PowerPoint decks "
        "for Vietnamese secondary schools (Experiential Learning). "
        "When a lesson plan is provided, the slides MUST follow that plan closely. "
        "All slide text MUST be English only — no Vietnamese. "
        "image_keyword must describe a real photo matching the slide content. "
        "Return valid JSON only."
    )

    def _ask(prompt_text: str):
        return _call_ai(
            prompt_text, system_en, max_tokens=8192, json_mode=True, timeout=120,
        )

    prompt = f"""
Create an English-only PowerPoint outline as JSON:
{{
  "title": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "language": "en",
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
      "image_keyword": "concrete English nouns for a related photo",
      "notes": "presenter notes in English"
    }}
  ]
}}

Rules:
- Exactly {slide_count} slides.
- ALL text in English (titles, bullets, table cells, notes).
- Slide 1 layout=title; last slide layout=closing.
- Include at least one layout=table, one layout=two_column, and one layout=cards.
- Content slides: 5–6 bullets, each 12–22 words.
- two_column: 4–5 bullets per side.
- cards: 3–4 cards, 15–30 words each.
- table: 4–6 meaningful rows.
{follow_lesson}- image_keyword MUST match THAT slide (e.g. flag ceremony → "vietnam school flag raising ceremony students";
  lining up → "students lining up schoolyard"; national anthem → "students singing national anthem").
- Never use generic keywords like "background", "abstract", or "education" alone.
Grade: {grade}; Subject: {subject}; Topic: {topic}.
{context_hint}
"""
    text, source = _ask(prompt)
    data = _parse_json(text) if text else None
    slides = (data or {}).get("slides") if data else None

    if not data or not isinstance(slides, list) or len(slides) < 4:
        retry_prompt = f"""
Return English-only PowerPoint JSON with {slide_count} slides for topic "{topic}".
Follow the lesson plan if provided. Layouts: title, content, two_column, table, cards, closing.
Concrete image_keyword per slide. No Vietnamese. Valid JSON only.
{context_hint[:1500]}
"""
        text2, source2 = _ask(retry_prompt)
        data2 = _parse_json(text2) if text2 else None
        if data2 and isinstance(data2.get("slides"), list) and len(data2["slides"]) >= 4:
            data, source, slides = data2, source2 or source, data2["slides"]

    if not data or not isinstance(slides, list) or len(slides) < 4:
        return _fallback_slides(grade, subject, topic, slide_count)

    normalized = _normalize_pptx_slides(slides, topic)
    normalized = _enrich_image_keywords(normalized, topic)
    if len(normalized) < 4:
        return _fallback_slides(grade, subject, topic, slide_count)
    data["slides"] = normalized
    data["source"] = source or "ai"
    data["language"] = "en"
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
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    doc.add_heading(quiz.get("title") or "Đề kiểm tra", level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(
        f"Lớp: {quiz.get('grade', '')} | Môn: {quiz.get('subject', '')} | "
        f"Chủ đề: {quiz.get('topic', '')} | Thời gian: {quiz.get('time_limit_minutes', 20)} phút"
    )

    for i, q in enumerate(quiz.get("questions") or [], 1):
        doc.add_heading(f"Câu {i}", level=2)
        doc.add_paragraph(q.get("question_text") or "")
        for opt in q.get("options") or []:
            doc.add_paragraph(str(opt), style="List Bullet")

    doc.add_page_break()
    doc.add_heading("Đáp án", level=1)
    for i, q in enumerate(quiz.get("questions") or [], 1):
        ans = q.get("correct_answer") or "—"
        exp = q.get("explanation") or ""
        line = f"Câu {i}: {ans}"
        if exp:
            line += f" ({exp})"
        doc.add_paragraph(line)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
