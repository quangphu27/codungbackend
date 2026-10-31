"""EDUBRIDGE Master Prompt — PowerPoint CLIL (Teacher Studio)."""
from __future__ import annotations

import json

from app.services.studio_lesson_clil import english_level_directive, subject_clil_rules

SYSTEM_PPTX_CLIL = (
    "ROLE: EDUBRIDGE PowerPoint designer, CLIL pedagogy expert, Vietnam GDPT 2018 specialist, "
    "academic English by subject.\n"
    "TASK: Design an English classroom deck (16:9) that TEACHES — one slide one purpose, "
    "active learning, accurate subject content, rich Speaker Notes for Vietnamese teachers.\n"
    "RULES: Follow approved lesson plan when provided; else textbook/upload; never guess unreadable source. "
    "Align flow with GDPT 2018: warm-up → knowledge formation → practice → application (plus consolidation). "
    "On-slide English (simple, accurate). Vietnamese support ONLY in Speaker Notes unless bilingual mode. "
    "Do not show answers on question slides before students think. "
    "Every content slide needs substantive bullets (not placeholders) and image_keyword + image_scene tied to THAT slide. "
    "Editable text layouts — no placeholder slides. JSON only."
)

DETAIL_HINTS = {
    "compact": "Compact deck: fewer bullets, strong visuals, minimal text; still full Speaker Notes.",
    "balanced": "Balanced: knowledge + interaction slides; 4–6 bullets max on content slides.",
    "detailed": "Detailed: more examples, practice slides, step-by-step solutions in notes.",
}


def _lesson_json_for_pptx(lesson_context: dict | None) -> str:
    if not lesson_context or not isinstance(lesson_context, dict):
        return ""
    brief: dict = {
        "title_en": lesson_context.get("title_en") or lesson_context.get("title_vi"),
        "description": (lesson_context.get("description") or "")[:500],
        "duration_minutes": lesson_context.get("duration_minutes"),
        "objectives_en": (lesson_context.get("objectives_en") or [])[:8],
        "core_content_en": (lesson_context.get("core_content_en") or lesson_context.get("core_content_vi") or "")[:800],
        "materials": lesson_context.get("materials"),
        "vocabulary": (lesson_context.get("vocabulary") or [])[:12],
        "homework": lesson_context.get("homework"),
        "lesson_format": lesson_context.get("lesson_format"),
    }
    obj = lesson_context.get("objectives")
    if isinstance(obj, dict):
        brief["objectives_clil"] = obj
    acts = []
    for a in (lesson_context.get("activities") or [])[:10]:
        if not isinstance(a, dict):
            continue
        acts.append({
            "name": a.get("name"),
            "duration": a.get("duration"),
            "objectives": (a.get("objectives") or "")[:300],
            "content": (a.get("content") or "")[:400],
        })
    if acts:
        brief["activities"] = acts
    else:
        secs = []
        for s in (lesson_context.get("sections") or [])[:8]:
            if isinstance(s, dict):
                secs.append({
                    "heading": s.get("heading_en") or s.get("heading_vi"),
                    "duration": s.get("duration"),
                    "content": (s.get("content_en") or s.get("content_vi") or "")[:420],
                })
        brief["sections"] = secs
    return json.dumps(brief, ensure_ascii=False)[:5500]


def presentation_language_rule(mode: str) -> str:
    m = (mode or "english").lower().strip()
    if m.startswith("bi"):
        return (
            "PRESENTATION LANGUAGE: Bilingual selective — slide body primarily English; "
            "add short Vietnamese only for hard terms on slide when necessary. "
            "Full Vietnamese teacher support in Speaker Notes."
        )
    return (
        "PRESENTATION LANGUAGE: English on slides. "
        "Vietnamese meanings, IPA, and teacher script in Speaker Notes only."
    )


def pptx_clil_user_prompt(
    *,
    brief: str,
    teach: str,
    subject: str,
    grade: str,
    topic: str,
    profile: str,
    slide_count: int,
    duration_minutes: int,
    teacher_english_level: str,
    student_english_level: str,
    presentation_language: str,
    pptx_detail: str,
    lesson_context: dict | None,
    has_book_reference: bool,
    has_lesson: bool,
) -> str:
    lesson_block = _lesson_json_for_pptx(lesson_context)
    lesson_priority = ""
    if lesson_block:
        lesson_priority = (
            "PRIORITY 1 — APPROVED LESSON PLAN (align slides, timing, terms, exercises):\n"
            f"{lesson_block}\n"
        )
    elif has_book_reference:
        lesson_priority = (
            "PRIORITY 1 — UPLOADED TEXTBOOK / PDF / IMAGES (mandatory): "
            "Read attached pages; match terminology, examples, and sequence from the book. "
            "Do not invent textbook facts. deck_status=aligned_source.\n"
        )
    else:
        lesson_priority = (
            "No lesson plan or upload — build from topic/description; "
            "set deck_status to proposed_draft in JSON.\n"
        )

    detail = DETAIL_HINTS.get((pptx_detail or "balanced").lower(), DETAIL_HINTS["balanced"])
    rules = subject_clil_rules(profile)
    level = english_level_directive(teacher_english_level, student_english_level)
    plang = presentation_language_rule(presentation_language)

    return f"""
{brief}
{teach}
{level}
{plang}
Detail level: {detail}
SUBJECT RULES ({profile}): {rules}
{lesson_priority}
Duration: {duration_minutes} minutes across slides (note timing in Speaker Notes).
MANDATORY: Final deck must contain exactly {slide_count} slides (teacher setting). Each slide = full teaching moment
(3–6 bullets on content slides; practice slides with real tasks). Do not pad with empty slides.

GDPT 2018 flow across the deck: Khởi động → Hình thành kiến thức → Luyện tập → Vận dụng → consolidation/exit.

WORKFLOW (internal): (1) Analyse lesson/sources (2) Script each slide (3) Pick layout (4) Quality check.

Return JSON:
{{
  "title": "English deck title",
  "deck_format": "edubridge_clil_pptx",
  "deck_status": "{'aligned_lesson' if has_lesson else 'proposed_draft'}",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "slide_count_planned": {slide_count},
  "slides": [
    {{
      "slide_type": "title|warm_up|objectives|vocabulary|explore|practice|application|consolidation|exit_ticket|homework|closing",
      "layout": "title|content|two_column|table|cards|closing",
      "title": "Specific slide title (not Content 1)",
      "subtitle": "optional",
      "learning_purpose": "one teaching purpose",
      "student_action": "Observe / Discuss / Predict / Complete...",
      "visual_element": "what image/diagram/chart to show",
      "visual_type": "photo|diagram|table|timeline|graph|model",
      "bullets": ["short English on slide — max 5-6"],
      "left_title": "optional",
      "right_title": "optional",
      "left_bullets": [],
      "right_bullets": [],
      "table": {{"headers":["A","B"],"rows":[["1","2"]]}},
      "image_keyword": "English keywords for Vietnam-relevant photo of THIS slide",
      "image_scene": "One sentence: exact scene matching slide content",
      "hide_answer_on_slide": true,
      "notes": "Speaker Notes (plain text): objective; time; teacher script EN; 1-2 questions+answers; VI support for GV; transition"
    }}
  ]
}}

Keep each slide JSON small: max 5 bullets, notes under 600 characters per slide (no huge nested objects).

Structure guide:
1 Title — subject, grade, visual
2 Warm-up — question/situation, NO answer on slide
3 Learning objectives — 2-4 "By the end, you can..."
4 Key vocabulary — few terms + visuals; IPA/VI in notes
5–N Knowledge exploration — observe/discover/explain/example/check (split if long)
Practice slides — MCQ, T/F, fill, matching, problem (question slide then answer in notes or next slide)
Application — real task
Consolidation — 3-5 key points or diagram
Exit ticket — 1-3 checks
Homework — specific task aligned with lesson
Closing — thank you / questions

RULES: One slide one purpose. Teach don't summarize. Accurate {subject} content on "{topic}".
English on slide; full teacher script in speaker_notes. Question slides: hide_answer_on_slide true.
Include layouts: table, two_column, cards where pedagogically useful.
Return exactly {min(slide_count, 8)} slides in this response (batch 1 of {slide_count} total — remaining batches continue the same lesson).
"""


def pptx_continuation_prompt(
    *,
    brief: str,
    teach: str,
    subject: str,
    grade: str,
    topic: str,
    slide_count: int,
    need: int,
    existing_titles: list[str],
    lesson_context: dict | None,
    last_batch: bool,
) -> str:
    lesson_block = _lesson_json_for_pptx(lesson_context)
    lesson_snip = f"\nLESSON PLAN (keep aligning):\n{lesson_block}\n" if lesson_block else ""
    closing = (
        "Include homework + closing slides in this batch."
        if last_batch
        else "Do not add closing/thank-you yet — more slides follow."
    )
    return f"""{brief}
{teach}
{lesson_snip}
Create exactly {need} MORE CLIL slides for “{topic}” ({grade}, {subject}).
Total deck size must be {slide_count} slides; these are continuation slides only.
JSON: {{"slides":[...]}} — each slide: slide_type, layout, title, bullets (3–6 on content slides),
image_keyword, image_scene (must describe THIS slide's subject matter), notes (EN script + VI support, ≤600 chars).
Do not repeat titles: {existing_titles}.
English on slide; accurate {subject} content; bám sách/giáo án nếu đã có trong prompt đính kèm.
{closing}
Complete JSON.
"""


def pptx_clil_compact_prompt(subject: str, topic: str, grade: str, slide_count: int) -> str:
    n = min(slide_count, 8)
    return (
        f'JSON edubridge_clil_pptx, exactly {slide_count} slides total (return {n} now if batched), '
        f'{grade} {subject}, "{topic}", GDPT 2018 flow. '
        'Each slide: layout, title, 3+ bullets, image_keyword, image_scene, visual_element, '
        '"notes" (EN script + VI support). Bám SGK nếu có đính kèm. Complete JSON.'
    )


def format_speaker_notes_for_pptx(slide: dict) -> str:
    """Gộp speaker_notes → chuỗi Notes trong file PPTX."""
    if not isinstance(slide, dict):
        return ""
    raw = slide.get("notes") or slide.get("notes_vi") or ""
    if raw and not slide.get("speaker_notes"):
        return str(raw).strip()

    sn = slide.get("speaker_notes")
    if not isinstance(sn, dict):
        return str(raw).strip()

    parts: list[str] = []
    if sn.get("teaching_objective"):
        parts.append(f"Objective: {sn['teaching_objective']}")
    if sn.get("duration"):
        parts.append(f"Time: {sn['duration']}")
    script = sn.get("teacher_script")
    if isinstance(script, list) and script:
        parts.append("TEACHER SCRIPT (EN):\n" + "\n".join(f"• {s}" for s in script if s))
    elif isinstance(script, str) and script.strip():
        parts.append(f"TEACHER SCRIPT (EN):\n{script.strip()}")
    qs = sn.get("questions")
    if isinstance(qs, list) and qs:
        q_lines = []
        for q in qs:
            if isinstance(q, dict):
                q_lines.append(f"Q: {q.get('question') or ''}\nA: {q.get('expected_answer') or ''}")
            elif q:
                q_lines.append(str(q))
        if q_lines:
            parts.append("QUESTIONS & ANSWERS:\n" + "\n".join(q_lines))
    if sn.get("simple_explanation"):
        parts.append(f"Simple explanation: {sn['simple_explanation']}")
    if sn.get("vietnamese_support"):
        parts.append(f"Hỗ trợ GV (VI): {sn['vietnamese_support']}")
    if sn.get("pronunciation"):
        parts.append(f"Pronunciation: {sn['pronunciation']}")
    if sn.get("answer_key"):
        parts.append(f"Answer key: {sn['answer_key']}")
    if sn.get("transition"):
        parts.append(f"Transition: {sn['transition']}")
    if slide.get("learning_purpose"):
        parts.append(f"Slide purpose: {slide['learning_purpose']}")
    if slide.get("student_action"):
        parts.append(f"Student action: {slide['student_action']}")
    merged = "\n\n".join(p for p in parts if p).strip()
    return merged or str(raw).strip()


def normalize_clil_pptx_slide_fields(slide: dict) -> dict:
    """Bổ sung notes từ speaker_notes; giữ metadata CLIL."""
    if not isinstance(slide, dict):
        return slide
    notes = format_speaker_notes_for_pptx(slide)
    if notes:
        slide = {**slide, "notes": notes}
    return slide
