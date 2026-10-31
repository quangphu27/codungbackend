"""EDUBRIDGE Master Prompt + Subject Rule Engine — giáo án CLIL (Word Teacher Studio)."""
from __future__ import annotations

SYSTEM_LESSON_CLIL = (
    "ROLE: Vietnam GDPT lesson-plan expert, CLIL specialist, academic English by subject, "
    "and pedagogical advisor for Vietnamese teachers whose English may be limited.\n"
    "TASK: Produce a complete ENGLISH lesson plan usable on class, grounded in uploaded "
    "textbook pages/files when provided. Teachers must know exactly what to say, ask, "
    "what students do, sample answers, and how to respond at each step.\n"
    "RULES: (1) Analyse all uploaded materials/images; prioritise source terminology; "
    "never invent textbook facts; flag unreadable parts in source_notes. "
    "(2) Distinguish source content from AI-added examples/dialogue. "
    "(3) Do not claim full GDPT 2018 alignment without evidence. "
    "(4) Main plan in ENGLISH; Vietnamese only inside english_support_notes appendix. "
    "(5) No vague lines like 'Teacher explains the lesson' without script. "
    "(6) Each activity: objectives, content, expected outcomes, 3-column organisation "
    "(teacher | students | contents), assessment, classroom instructions, teacher script, "
    "questions with expected answers, support/feedback/transition language. "
    "(7) Subject Rule Engine R1–R12 applies. JSON only, no markdown."
)

SUBJECT_CLIL_RULES: dict[str, str] = {
    "math": (
        "MATH: Keep formulas/definitions from source. Steps in worked examples. "
        "MCQ-style checks use numbers. Assessment = solving problems, not grammar."
    ),
    "physics": (
        "PHYSICS: Phenomenon → law → formula → units (SI) → worked example → application. "
        "Include safe lab language if experiments appear in source."
    ),
    "chemistry": (
        "CHEMISTRY: Names, equations, mol calculations as in source. "
        "Balance equations; state conditions. No wrong formulas."
    ),
    "biology": (
        "BIOLOGY: Structures, processes, diagrams vocabulary. "
        "Observation/report language; avoid turning lesson into general English class."
    ),
    "natural_science": (
        "NATURAL SCIENCE: Hypothesis–experiment–conclusion scaffolding. "
        "Measurement vocabulary; link to Vietnamese context when relevant."
    ),
    "history": (
        "HISTORY: Time, place, actors, cause–course–result–significance. "
        "Source-based questions; no invented dates/events."
    ),
    "geography": (
        "GEOGRAPHY: Location, climate, relief, population, economy tied to topic. "
        "Map/chart language; data interpretation tasks."
    ),
    "literature": (
        "LITERATURE: Author, genre, form, characters, plot, theme, devices. "
        "Quote short lines only when essential; teach analysis not generic discussion."
    ),
    "literature_kieu": (
        "TRUYỆN KIỀU: Nguyễn Du, lục bát, Thúy Kiều, Kim Trọng, Hoạn Thư, "
        "tài mệnh tương đố, filial piety — facts must match the text."
    ),
    "english": (
        "ENGLISH SUBJECT: Communicative functions + grammar/vocab OF the topic; "
        "still content-rich, not only drill."
    ),
    "civic": (
        "CIVIC / ECON-LAW: Rights, duties, legal situations, ethical choices. "
        "Case discussion with clear expected reasoning."
    ),
    "experiential": (
        "EXPERIENTIAL: Only if subject is experiential learning — "
        "experience cycle, skills, reflection; not fake science/math content."
    ),
    "general": (
        "GENERAL SUBJECT: Use correct discipline terminology from source; "
        "competency-based tasks observable in class."
    ),
}


def english_level_directive(teacher_level: str, student_level: str) -> str:
    tl = (teacher_level or "A2").upper().strip()
    sl = (student_level or "A2").upper().strip()
    if tl not in ("A1", "A2", "B1", "B2"):
        tl = "A2"
    if sl not in ("A1", "A2", "B1", "B2"):
        sl = "A2"
    lines = [
        f"Teacher English level (assumed unless user confirms): {tl}.",
        f"Students' English level: {sl}.",
        "Adjust ALL teacher scripts and instructions to teacher level:",
        "- A1/A2: very short sentences, high-frequency words, more modelling and repetition.",
        "- B1: standard classroom English, some academic terms with gloss.",
        "- B2: richer academic vocabulary but still clear delivery scripts.",
        f"Student expected answers calibrated to {sl}.",
        "Mark in lesson_header that levels are assumptions if user did not specify.",
    ]
    return "\n".join(lines)


def subject_clil_rules(profile: str) -> str:
    return SUBJECT_CLIL_RULES.get(profile) or SUBJECT_CLIL_RULES["general"]


def lesson_clil_user_prompt(
    *,
    brief: str,
    teach: str,
    subject: str,
    grade: str,
    topic: str,
    profile: str,
    teacher_english_level: str,
    student_english_level: str,
    class_size: str,
    equipment: str,
    duration_minutes: int,
    has_book_reference: bool,
) -> str:
    book_line = (
        "Uploaded textbook/images are attached — READ them first; base all content on them."
        if has_book_reference
        else "No upload — use topic + description; note limits in source_notes."
    )
    equip = equipment.strip() or "Projector, board, textbook (assume if unknown)"
    size = class_size.strip() or "typical class (assume ~35 if unknown)"
    rules = subject_clil_rules(profile)
    level = english_level_directive(teacher_english_level, student_english_level)
    schema = f"""
{brief}
{teach}
{level}
SUBJECT RULE ENGINE ({subject}, profile={profile}):
{rules}
MATERIALS INPUT: {book_line}
Class size: {size}. Equipment: {equip}. Duration: {duration_minutes} minutes total (activities must sum exactly).

OUTPUT: One JSON object, lesson_format="edubridge_clil", teaching language ENGLISH.
Structure (fill every field with real content, not placeholders):
{{
  "lesson_format": "edubridge_clil",
  "title_en": "English lesson title",
  "title_vi": "Vietnamese title for header only",
  "description": "2-3 English sentences on what this lesson teaches",
  "duration_minutes": {duration_minutes},
  "lesson_header": {{
    "week": "...",
    "period": "...",
    "unit_topic": "...",
    "lesson_title": "...",
    "textbook_source": "...",
    "teaching_language": "English",
    "teacher_english_level": "{teacher_english_level}",
    "student_english_level": "{student_english_level}",
    "teaching_approach": "CLIL, active learning, competency-based",
    "class_size": "{size}",
    "equipment": "{equip}"
  }},
  "objectives": {{
    "knowledge": ["By the end, students will be able to ... (3-5 items)"],
    "competences": ["..."],
    "personal_qualities": ["..."],
    "digital_competence": null
  }},
  "materials": {{
    "textbook": ["..."],
    "equipment": ["..."],
    "worksheets": ["..."],
    "digital": ["..."],
    "other": ["..."]
  }},
  "subject_language_analysis": "Short English paragraph on key content + language focus",
  "vocabulary": [
    {{"term":"...","ipa":"/.../ or omit if unsure","meaning_vi":"...","explanation_en":"...","example":"..."}}
  ],
  "anticipated_difficulties": [
    {{"difficulty":"...","solution":"..."}}
  ],
  "activities": [
    {{
      "name": "WARM-UP",
      "duration": "5'",
      "objectives": "...",
      "content": "...",
      "expected_outcomes": "...",
      "organisation": [
        {{"teacher_en":"verbatim script + questions","student_en":"actions + sample answers","contents":"knowledge / tasks / answers"}}
      ],
      "assessment": "...",
      "classroom_instructions": ["Look at the picture."],
      "teacher_script": ["..."],
      "teacher_questions": [{{"question":"...","expected_answer":"...","support_language":"..."}}],
      "feedback_language": ["Good try."],
      "transition": "Now, let's ..."
    }},
    {{"name":"ACTIVITY 1: PRESENTATION / DISCOVERY","duration":"...","objectives":"...","content":"...","expected_outcomes":"...","organisation":[...],"assessment":"...","classroom_instructions":[],"teacher_script":[],"teacher_questions":[],"feedback_language":[],"transition":""}},
    {{"name":"ACTIVITY 2: PRACTICE","duration":"...","..."}},
    {{"name":"ACTIVITY 3: APPLICATION","duration":"...","..."}},
    {{"name":"CONSOLIDATION","duration":"...","..."}}
  ],
  "exercises": [
    {{"instructions_en":"...","tasks":["..."],"expected_answers":["..."],"answer_key":"...","assessment_criteria":["..."]}}
  ],
  "english_support_notes": {{
    "essential_expressions": [{{"en":"...","vi":"..."}}],
    "difficult_terminology": [{{"term":"...","ipa":"...","vi":"..."}}],
    "pronunciation_support": [{{"phrase":"...","ipa":"...","note":"..."}}],
    "simplified_explanations": [{{"concept":"...","standard_en":"...","simple_en":"...","vietnamese_support":"..."}}],
    "classroom_situations": [{{"situation":"Student silent","english_response":"..."}}]
  }},
  "source_notes": "Unreadable parts or assumptions — empty string if none",
  "objectives_en": ["mirror objectives.knowledge for compatibility"],
  "core_content_en": "80-120 words subject summary",
  "sections": []
}}
Include 8-12 vocabulary rows when possible (omit IPA if not confident).
activities: at least WARM-UP, PRESENTATION, PRACTICE, APPLICATION, CONSOLIDATION; durations sum to {duration_minutes}.
Map teaching flow to Chương trình GDPT 2018 (Vietnam): Khởi động → Hình thành kiến thức → Luyện tập → Vận dụng
(use English activity names but cover all four stages with real {subject} content on "{topic}").
When textbook/upload is provided: use its terminology, examples, and page order — do not invent facts.
english_support_notes: 15-20 essential expressions; keep Vietnamese ONLY there.
Grade {grade}, subject {subject}, topic "{topic}". Complete JSON once.
"""
    return schema


def lesson_clil_compact_prompt(subject: str, topic: str, grade: str, duration_minutes: int) -> str:
    return (
        f'JSON edubridge_clil lesson, {duration_minutes} min, {grade} {subject}, topic "{topic}". '
        "activities with organisation rows + english_support_notes. English plan. Complete JSON."
    )


def normalize_edubridge_clil_lesson(out: dict, fb: dict | None = None) -> dict:
    """Chuẩn hóa JSON CLIL + map activities → sections (preview / tương thích cũ)."""
    if not isinstance(out, dict):
        return out
    is_clil = out.get("lesson_format") == "edubridge_clil" or isinstance(out.get("activities"), list)
    if not is_clil:
        return out

    out.setdefault("lesson_format", "edubridge_clil")
    out["language"] = "en"

    mats = out.get("materials")
    if isinstance(mats, dict):
        flat: list[str] = []
        for val in mats.values():
            if isinstance(val, list):
                flat.extend(str(x) for x in val if x)
        if flat:
            out["materials"] = flat

    obj = out.get("objectives")
    if isinstance(obj, dict):
        know = obj.get("knowledge") or []
        if isinstance(know, list) and know:
            out["objectives_en"] = know
            out["knowledge_en"] = know
        comp = obj.get("competences") or []
        qual = obj.get("personal_qualities") or []
        if comp:
            out["skills_en"] = comp
        if qual:
            out["qualities_en"] = qual

    vocab = out.get("vocabulary") or []
    for v in vocab:
        if isinstance(v, dict) and v.get("explanation_en") and not v.get("example"):
            v["example"] = v.get("explanation_en")

    activities = [a for a in (out.get("activities") or []) if isinstance(a, dict)]
    sections: list[dict] = []
    for act in activities:
        org = [r for r in (act.get("organisation") or []) if isinstance(r, dict)]
        teacher_parts = [str(r.get("teacher_en") or "").strip() for r in org if r.get("teacher_en")]
        student_parts = [str(r.get("student_en") or "").strip() for r in org if r.get("student_en")]
        scripts = act.get("teacher_script") or []
        if isinstance(scripts, list):
            teacher_parts.extend(str(s) for s in scripts if s)
        content_en = (act.get("content") or "").strip()
        if teacher_parts:
            content_en = (content_en + "\n\n" if content_en else "") + "\n".join(teacher_parts)
        sections.append({
            "heading_en": act.get("name") or "Activity",
            "heading_vi": act.get("name") or "Hoạt động",
            "duration": act.get("duration") or "",
            "content_en": content_en[:4000],
            "content_vi": (act.get("objectives") or "")[:800],
            "teacher_activity_en": " | ".join(teacher_parts)[:2000],
            "student_activity_en": " | ".join(student_parts)[:2000],
            "teacher_activity": " | ".join(teacher_parts)[:500],
            "student_activity": " | ".join(student_parts)[:500],
            "expected_product": act.get("expected_outcomes") or "",
            "questions": [
                q.get("question") for q in (act.get("teacher_questions") or [])
                if isinstance(q, dict) and q.get("question")
            ],
            "organisation": org,
            "activity_assessment": act.get("assessment") or "",
            "classroom_instructions": act.get("classroom_instructions") or [],
        })
    if sections:
        out["sections"] = sections
    elif fb and fb.get("sections"):
        out["sections"] = fb.get("sections")

    if not out.get("core_content_en") and out.get("subject_language_analysis"):
        out["core_content_en"] = str(out["subject_language_analysis"])[:1200]

    hw: list[str] = []
    for ex in out.get("exercises") or []:
        if not isinstance(ex, dict):
            continue
        for t in ex.get("tasks") or []:
            if t:
                hw.append(str(t))
    if hw:
        out["homework"] = hw[:6]

    return out
