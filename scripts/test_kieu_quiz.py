"""Offline check: Lớp 9 / Ngữ Văn / Truyện Kiều — 10 mixed questions."""
from app.services.studio_service import (
    _complete_quiz_questions,
    _fallback_quiz,
    _is_generic_quiz_item,
    _is_kieu_topic,
)

TYPES = ["multiple_choice", "true_false", "fill_blank", "essay"]
GENERIC_BITS = (
    "what should students do in the lesson",
    "join the class task",
    "skip the lesson",
    "follow the ______ of the teacher",
    "how students take part",
    "lựa chọn a",
)


def _assert_paper(quiz: dict) -> list[str]:
    errors = []
    qs = quiz.get("questions") or []
    if len(qs) != 10:
        errors.append(f"expected 10 questions, got {len(qs)}")
    stems = []
    types_seen = set()
    tf_answers = []
    for i, q in enumerate(qs, 1):
        stem = str(q.get("question_text") or "")
        low = stem.lower()
        stems.append(low)
        qtype = q.get("question_type")
        types_seen.add(qtype)
        answer = str(q.get("correct_answer") or "").strip()
        if _is_generic_quiz_item(q):
            errors.append(f"Q{i} generic: {stem}")
        if any(bit in low for bit in GENERIC_BITS):
            errors.append(f"Q{i} filler stem: {stem}")
        if not answer:
            errors.append(f"Q{i} missing correct_answer")
        if qtype == "true_false":
            tf_answers.append(answer)
            if answer not in ("True", "False"):
                errors.append(f"Q{i} TF answer must be True/False, got {answer!r}")
        if qtype == "fill_blank":
            if q.get("options"):
                errors.append(f"Q{i} fill_blank should have empty options")
            if not answer:
                errors.append(f"Q{i} fill_blank missing answer")
        if qtype == "essay":
            if q.get("options"):
                errors.append(f"Q{i} essay should have empty options")
            if not (answer or q.get("sample_answer")):
                errors.append(f"Q{i} essay missing sample/answer")
        if qtype == "multiple_choice":
            opts = q.get("options") or []
            if len(opts) < 4:
                errors.append(f"Q{i} MCQ needs 4 options")
            if answer not in opts:
                errors.append(f"Q{i} MCQ answer not in options: {answer!r}")
    if len(stems) != len(set(stems)):
        errors.append("duplicate question stems")
    for t in TYPES:
        if t not in types_seen:
            errors.append(f"missing question type {t}")
    if len(tf_answers) >= 2 and set(tf_answers) == {"True"}:
        errors.append("true/false answers are all True")
    return errors


def _print_paper(quiz: dict, label: str):
    print(f"\n=== {label} ===")
    print(f"title: {quiz.get('title')}  source: {quiz.get('source')}")
    for i, q in enumerate(quiz.get("questions") or [], 1):
        print(f"Q{i} [{q['question_type']}] {q['question_text']}")
        print(f"    answer={q.get('correct_answer')!r} options={q.get('options')}")


def main():
    assert _is_kieu_topic("Ngữ Văn", "Truyện Kiều của Nguyễn Du")
    junk = _complete_quiz_questions(
        [
            {
                "question_text": 'Question 1: What should students do in the lesson “Truyện Kiều của Nguyễn Du”?',
                "question_type": "multiple_choice",
                "options": [
                    "A. Join the class task about Truyện Kiều của Nguyễn Du and follow the teacher",
                    "B. Skip the lesson and stay on the phone",
                    "C. Leave school before it starts",
                    "D. Copy a random answer without reading",
                ],
                "correct_answer": "A. Join the class task about Truyện Kiều của Nguyễn Du and follow the teacher",
            },
            {
                "question_text": 'Question 2: Students in Lớp 9 can practise this lesson by doing the tasks of “Truyện Kiều của Nguyễn Du”.',
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
            },
            {
                "question_text": 'Question 3: Complete: In the lesson “Truyện Kiều của Nguyễn Du”, students should follow the ______ of the teacher.',
                "question_type": "fill_blank",
                "options": ["Lựa chọn A", "Lựa chọn B", "Lựa chọn C", "Lựa chọn D"],
                "correct_answer": "",
            },
        ],
        "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du", 10, TYPES,
    )
    junk_errors = _assert_paper({"questions": junk})
    if junk_errors:
        print("FAIL scrub generic fillers:")
        for e in junk_errors:
            print(" -", e)
        raise SystemExit(1)
    print("PASS scrub: generic fillers replaced with Truyện Kiều items.")

    quiz = _fallback_quiz(
        "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du",
        10, TYPES, "en",
    )
    quiz["questions"] = _complete_quiz_questions(
        quiz["questions"], "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du", 10, TYPES,
    )
    _print_paper(quiz, "fallback bank")
    errors = _assert_paper(quiz)
    if errors:
        print("FAIL fallback:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print("PASS fallback: 10 unique Truyện Kiều items, mixed types, answers present.")

    from app import create_app
    from app.services.studio_service import generate_quiz_draft

    app = create_app()
    with app.app_context():
        live = generate_quiz_draft(
            grade="Lớp 9",
            subject="Ngữ Văn",
            topic="Truyện Kiều của Nguyễn Du",
            num_questions=10,
            difficulty="mixed",
            language="en",
            description="Học sinh lớp 9 ôn nhân vật, thể loại lục bát và chủ đề tài mệnh tương đố.",
            quiz_types=TYPES,
            quiz_requirements="6 câu trắc nghiệm + 2 đúng/sai + điền khuyết + tự luận; bám sát Truyện Kiều",
        )
    _print_paper(live, "generate_quiz_draft")
    live_errors = _assert_paper(live)
    if live_errors:
        print("FAIL generate:")
        for e in live_errors:
            print(" -", e)
        raise SystemExit(1)
    print("PASS generate_quiz_draft.")


if __name__ == "__main__":
    main()
