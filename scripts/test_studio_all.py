"""Verify all Teacher Studio generators + file builders."""
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
from flask import Flask

load_dotenv(os.path.join(ROOT, ".env"))

OUT = os.path.join(ROOT, "scripts", "_studio_out")
os.makedirs(OUT, exist_ok=True)

AI_SOURCES = {"gemini", "openai", "ai"}


def _p(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    app = Flask(__name__)
    app.config["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
    app.config["AI_PROVIDER"] = os.getenv("AI_PROVIDER", "gemini")
    app.config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")
    logging.basicConfig(level=logging.WARNING)

    from app.services import studio_service

    grade = "Lớp 6"
    subject = "Experiential Learning"
    topic = "Recycling in Daily Life"
    failures = []

    with app.app_context():
        t0 = time.time()
        _p("=== 1/4 LESSON ===")
        lesson = studio_service.generate_lesson_draft(
            grade, subject, topic, "bilingual",
            teacher_english_level="A2",
            student_english_level="A2",
        )
        docx = studio_service.build_docx_bytes(lesson)
        _p(f"  source={lesson.get('source')} sections={len(lesson.get('sections') or [])} docx={len(docx)}")
        if len(docx) < 3000:
            failures.append("lesson docx too small")
        if lesson.get("source") not in AI_SOURCES and lesson.get("source") != "template":
            failures.append(f"lesson bad source {lesson.get('source')}")

        _p("=== 2/4 QUIZ ===")
        quiz = studio_service.generate_quiz_draft(
            grade, subject, topic, num_questions=6,
            quiz_types=["multiple_choice", "true_false"],
            difficulty="mixed",
        )
        qdoc = studio_service.quiz_to_docx_bytes(quiz)
        qs = quiz.get("questions") or []
        _p(f"  source={quiz.get('source')} questions={len(qs)} docx={len(qdoc)}")
        if len(qs) < 4:
            failures.append("quiz too few questions")
        if len(qdoc) < 2000:
            failures.append("quiz docx too small")

        _p("=== 3/4 PPTX ===")
        deck = studio_service.generate_pptx_draft(
            grade, subject, topic, slide_count=8, lesson_context=lesson,
        )
        pptx = studio_service.build_pptx_bytes(deck, light=True)
        slides = deck.get("slides") or []
        _p(f"  source={deck.get('source')} slides={len(slides)} pptx={len(pptx)}")
        if len(slides) < 6:
            failures.append("pptx too few slides")
        if len(pptx) < 8000:
            failures.append("pptx too small")

        _p("=== 4/4 WORKSHEET ===")
        ws = studio_service.generate_worksheet_draft(
            grade, subject, topic,
            lesson_context=lesson,
            deck_context=deck,
            worksheet_purpose="explore",
        )
        ws_st = studio_service.worksheet_student_docx_bytes(ws)
        ws_gv = studio_service.worksheet_teacher_docx_bytes(ws)
        acts = ws.get("activities") or ws.get("sections") or []
        _p(f"  source={ws.get('source')} acts={len(acts)} student={len(ws_st)} teacher={len(ws_gv)}")
        if len(ws_st) < 2000 or len(ws_gv) < 2000:
            failures.append("worksheet docx too small")

        elapsed = time.time() - t0
        _p(f"=== ELAPSED {elapsed:.1f}s ===")
        if failures:
            _p("FAIL: " + "; ".join(failures))
            return 1
        _p("PASS all studio generators + exports")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
