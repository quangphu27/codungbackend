"""E2E: Gemini → lesson + pptx drafts → DOCX/PPTX bytes (minimal Flask context)."""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
from flask import Flask

load_dotenv(os.path.join(ROOT, ".env"))

OUT = os.path.join(ROOT, "scripts", "_studio_out")
os.makedirs(OUT, exist_ok=True)


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
    logging.basicConfig(level=logging.INFO)

    from app.services import studio_service

    with app.app_context():
        topic = "Recycling in Daily Life"
        grade = "Lớp 6"
        subject = "Experiential Learning"

        _p("=== Generate LESSON ===")
        lesson = studio_service.generate_lesson_draft(grade, subject, topic, "bilingual")
        title = lesson.get("title_en") or lesson.get("title_vi") or ""
        _p(f"source={lesson.get('source')} title={title}")
        _p(f"sections={len(lesson.get('sections') or [])} vocab={len(lesson.get('vocabulary') or [])}")

        docx = studio_service.build_docx_bytes(lesson)
        docx_path = os.path.join(OUT, "giao_an_test.docx")
        with open(docx_path, "wb") as f:
            f.write(docx)
        _p(f"DOCX ok: {len(docx)} bytes -> {docx_path}")

        _p("=== Generate PPTX deck ===")
        deck = studio_service.generate_pptx_draft(
            grade, subject, topic, slide_count=10, lesson_context=lesson,
        )
        _p(f"source={deck.get('source')} slides={len(deck.get('slides') or [])}")
        for i, s in enumerate((deck.get("slides") or [])[:3], 1):
            st = (s.get("title") or "")[:80]
            _p(f"  slide{i}: {st} ({len(s.get('bullets') or [])} bullets)")

        pptx = studio_service.build_pptx_bytes(deck)
        pptx_path = os.path.join(OUT, "slide_test.pptx")
        with open(pptx_path, "wb") as f:
            f.write(pptx)
        _p(f"PPTX ok: {len(pptx)} bytes -> {pptx_path}")

        ok = (
            lesson.get("source") in ("gemini", "openai", "ai")
            and deck.get("source") in ("gemini", "openai", "ai")
            and len(docx) > 5000
            and len(pptx) > 10000
            and len(deck.get("slides") or []) >= 6
        )
        _p("=== RESULT === " + ("PASS" if ok else "PARTIAL/FALLBACK"))
        if lesson.get("source") == "template" or deck.get("source") == "template":
            _p("WARNING: used template fallback")
            return 2
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
