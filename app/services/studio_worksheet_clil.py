"""EDUBRIDGE — Phiếu học tập CLIL (Student Worksheet + Teacher Guide)."""
from __future__ import annotations

import json

from app.services.studio_lesson_clil import english_level_directive, subject_clil_rules

SYSTEM_WORKSHEET_CLIL = (
    "ROLE: Vietnam GDPT worksheet designer, CLIL expert, active learning, academic English by subject.\n"
    "TASK: Create a complete STUDENT WORKSHEET (activity-based, not a question list) plus "
    "TEACHER GUIDE & ANSWER KEY as separate JSON sections.\n"
    "RULES: Align with lesson plan / PPT / textbook when provided; never invent unreadable source facts; "
    "progressive tasks; response space; print-friendly A4; student version WITHOUT answers; "
    "teacher version WITH scripts EN+VI, answer key, criteria. JSON only."
)

PURPOSE_LABELS = {
    "warmup": "Warm-up / Engage",
    "explore": "Knowledge exploration",
    "practice": "Practice",
    "apply": "Application",
    "assess": "Assessment / Exit ticket",
}


def _context_block(lesson: dict | None, deck: dict | None) -> str:
    parts = []
    if lesson and isinstance(lesson, dict):
        brief = {
            "title_en": lesson.get("title_en") or lesson.get("title_vi"),
            "objectives_en": (lesson.get("objectives_en") or [])[:6],
            "core_content_en": (lesson.get("core_content_en") or "")[:600],
            "activities": [
                {"name": a.get("name"), "content": (a.get("content") or "")[:300]}
                for a in (lesson.get("activities") or [])[:6]
                if isinstance(a, dict)
            ],
            "sections": [
                {"h": s.get("heading_en"), "c": (s.get("content_en") or "")[:300]}
                for s in (lesson.get("sections") or [])[:6]
                if isinstance(s, dict)
            ],
        }
        parts.append("LESSON PLAN:\n" + json.dumps(brief, ensure_ascii=False)[:4000])
    if deck and isinstance(deck, dict):
        slides = []
        for s in (deck.get("slides") or [])[:12]:
            if isinstance(s, dict):
                slides.append({
                    "title": s.get("title"),
                    "type": s.get("slide_type"),
                    "bullets": (s.get("bullets") or [])[:4],
                })
        parts.append("POWERPOINT:\n" + json.dumps({"title": deck.get("title"), "slides": slides}, ensure_ascii=False)[:2500])
    return "\n\n".join(parts)


def worksheet_clil_user_prompt(
    *,
    brief: str,
    teach: str,
    subject: str,
    grade: str,
    topic: str,
    profile: str,
    worksheet_purpose: str,
    worksheet_duration: int,
    language_mode: str,
    working_mode: str,
    difficulty: str,
    teacher_english_level: str,
    student_english_level: str,
    lesson_context: dict | None,
    deck_context: dict | None,
    has_book_reference: bool,
) -> str:
    purpose = PURPOSE_LABELS.get(worksheet_purpose, worksheet_purpose)
    rules = subject_clil_rules(profile)
    level = english_level_directive(teacher_english_level, student_english_level)
    ctx = _context_block(lesson_context, deck_context)
    src = (
        "Use uploaded textbook/images as primary source."
        if has_book_reference
        else ("Use lesson/PPT below." if ctx else "Use topic/description; mark assumptions in teacher_guide.")
    )
    lang = (language_mode or "english").lower()
    return f"""
{brief}
{teach}
{level}
Language mode: {lang}. Working mode: {working_mode}. Difficulty: {difficulty}.
Worksheet purpose: {purpose}. Time for worksheet: {worksheet_duration} minutes (match task load).
SUBJECT RULES ({profile}): {rules}
{src}
{ctx}

Return JSON:
{{
  "worksheet_format": "edubridge_clil_worksheet",
  "subject": "{subject}",
  "grade": "{grade}",
  "topic": "{topic}",
  "worksheet_purpose": "{worksheet_purpose}",
  "duration_minutes": {worksheet_duration},
  "student": {{
    "title": "Worksheet title in English (or VI if language mode vietnamese)",
    "learning_goal": "1-2 sentences: After this activity, you can...",
    "header_fields": true,
    "key_words": [{{"term":"...","meaning_vi":"...","explanation_en":"..."}}],
    "tasks": [
      {{
        "number": 1,
        "title": "Task 1. Observe and identify",
        "instructions": "Short clear instructions",
        "learning_material": "Text, table, or describe diagram for print",
        "items": ["specific questions or steps"],
        "response_type": "lines|blanks|table|draw_box|mcq|short_answer",
        "response_lines": 4,
        "table_template": {{"headers":["A","B"],"rows":[["",""],["",""]]}},
        "time_minutes": 5
      }}
    ],
    "reflection": ["I can ...", "I need help with ..."],
    "exit_question": "optional one question"
  }},
  "teacher_guide": {{
    "objectives": ["..."],
    "suggested_duration": "{worksheet_duration} min",
    "organisation": "{working_mode}",
    "teacher_says_en": "Full script paragraph",
    "vietnamese_support": "Hướng dẫn tổ chức bằng tiếng Việt",
    "answer_key": [{{"task": 1, "expected": "..."}}],
    "common_mistakes": ["..."],
    "suggested_feedback": ["..."],
    "assessment_criteria": ["..."],
    "transition": "Next activity..."
  }}
}}

Requirements:
- 2-4 tasks (not 15 random questions); each task = activity with product.
- Student JSON must NOT contain answer key text in items visible to students.
- Include response space hints (lines, blanks, table cells).
- key_words: 3-6 terms max unless not needed.
- Align with lesson/PPT activity if context provided.
Grade {grade}, subject {subject}, topic "{topic}". Complete JSON.
"""


def worksheet_clil_compact(subject: str, topic: str, grade: str) -> str:
    return (
        f'JSON edubridge_clil_worksheet {grade} {subject} "{topic}" '
        "with student.tasks and teacher_guide.answer_key. Complete JSON."
    )


def normalize_worksheet(out: dict, fb: dict, grade: str, subject: str, topic: str) -> dict:
    if not isinstance(out, dict):
        return fb
    out.setdefault("worksheet_format", "edubridge_clil_worksheet")
    out["grade"] = grade
    out["subject"] = subject
    out["topic"] = topic
    if not isinstance(out.get("student"), dict):
        out["student"] = fb.get("student") or {}
    if not isinstance(out.get("teacher_guide"), dict):
        out["teacher_guide"] = fb.get("teacher_guide") or {}
    st = out["student"]
    if not st.get("title"):
        st["title"] = f"Worksheet: {topic}"
    if not st.get("tasks"):
        st["tasks"] = fb.get("student", {}).get("tasks") or []
    return out


def fallback_worksheet(grade: str, subject: str, topic: str, purpose: str = "practice") -> dict:
    return {
        "worksheet_format": "edubridge_clil_worksheet",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "worksheet_purpose": purpose,
        "duration_minutes": 15,
        "source": "template",
        "student": {
            "title": f"Worksheet: {topic}",
            "learning_goal": f"After this activity, you can explain key ideas about {topic} in {subject}.",
            "header_fields": True,
            "key_words": [
                {"term": "concept", "meaning_vi": "khái niệm", "explanation_en": "An important idea in this lesson."},
            ],
            "tasks": [
                {
                    "number": 1,
                    "title": "Task 1. Read and identify",
                    "instructions": f"Read the information about “{topic}”. Write the main idea in 2–3 sentences.",
                    "learning_material": f"Key point: This worksheet focuses on “{topic}” in {subject} ({grade}).",
                    "items": ["What is the main idea?", "Give one example from the lesson."],
                    "response_type": "lines",
                    "response_lines": 5,
                    "time_minutes": 8,
                },
                {
                    "number": 2,
                    "title": "Task 2. Apply",
                    "instructions": "Answer the question using what you learned.",
                    "items": [f"How can you use knowledge of “{topic}” in a real situation?"],
                    "response_type": "lines",
                    "response_lines": 4,
                    "time_minutes": 7,
                },
            ],
            "reflection": ["I can explain the main idea.", "I need more practice with: ___"],
            "exit_question": f"In one sentence, what did you learn about {topic}?",
        },
        "teacher_guide": {
            "objectives": [f"Check understanding of {topic}"],
            "suggested_duration": "15 min",
            "organisation": "individual",
            "teacher_says_en": "You have 15 minutes. Read each task carefully and write your answers.",
            "vietnamese_support": "Phát phiếu, nhắc HS đọc kỹ từng nhiệm vụ và ghi câu trả lời đầy đủ.",
            "answer_key": [
                {"task": 1, "expected": "Answers should mention core facts of the topic from the lesson."},
                {"task": 2, "expected": "A reasonable application linked to the subject content."},
            ],
            "common_mistakes": ["Copying without understanding", "Leaving tasks blank"],
            "suggested_feedback": ["Good try — add one fact from the textbook.", "Correct — can you give another example?"],
            "assessment_criteria": ["Uses subject vocabulary", "Answer matches lesson content"],
            "transition": "Collect worksheets and discuss Task 2 with the class.",
        },
    }
