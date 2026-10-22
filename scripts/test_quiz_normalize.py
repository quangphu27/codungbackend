"""Unit checks for quiz answer normalization / MCQ match."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.routes.quizzes import normalize_quiz_questions, grade_answer, _mcq_match


def main():
    qs = normalize_quiz_questions([
        {
            "question_text": "What is recycling?",
            "options": ["A. Reusing materials", "B. Throwing trash", "C. Burning", "D. Ignoring"],
            "correct_answer": "A",
            "explanation": "Reuse",
        },
        {
            "question_text": "Empty",
            "options": ["A. x", "B. y"],
            "correct_answer": "B. y",
        },
        {
            "question_text": "",
            "options": ["A. skip"],
            "correct_answer": "A",
        },
    ])
    assert len(qs) == 2, qs
    assert qs[0]["correct_answer"] == "A. Reusing materials", qs[0]
    assert qs[1]["correct_answer"] == "B. y", qs[1]

    q = {
        "question_type": "multiple_choice",
        "options": qs[0]["options"],
        "correct_answer": qs[0]["correct_answer"],
    }
    assert grade_answer(q, "A. Reusing materials")
    assert grade_answer(q, "A")
    assert not grade_answer(q, "B")
    assert _mcq_match("A", "A. Reusing materials", qs[0]["options"])

    from app.services.studio_service import build_docx_bytes, build_pptx_bytes

    docx = build_docx_bytes({
        "title_vi": "Test",
        "title_en": "Test EN",
        "grade": "Lop 6",
        "subject": "EL",
        "topic": "Recycling",
        "objectives_vi": ["Obj 1"],
        "objectives_en": ["Obj 1"],
        "sections": [{"heading_vi": "Warm", "content_vi": "Hi", "heading_en": "Warm", "content_en": "Hi"}],
        "vocabulary": [{"term": "recycle", "meaning_vi": "tai che", "example": "We recycle."}],
    })
    pptx = build_pptx_bytes({
        "title": "Test",
        "topic": "Recycling",
        "slides": [
            {"title": "Intro", "bullets": ["One", "Two"], "notes": ""},
            {"title": "Main", "bullets": ["A", "B", "C"], "notes": "note"},
        ],
    })
    assert len(docx) > 5000 and len(pptx) > 10000
    print("PASS normalize + export builders", len(docx), len(pptx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
