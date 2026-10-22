"""Generate English rich PPTX via Gemini + new builder."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
from flask import Flask

load_dotenv(os.path.join(ROOT, ".env"))
OUT = os.path.join(ROOT, "scripts", "_studio_out")
os.makedirs(OUT, exist_ok=True)

app = Flask(__name__)
app.config["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
app.config["AI_PROVIDER"] = "gemini"

from app.services import studio_service

with app.app_context():
    deck = studio_service.generate_pptx_draft(
        "Grade 6", "Experiential Learning", "Recycling in Daily Life", slide_count=10,
    )
    print("source=", deck.get("source"), "lang=", deck.get("language"), "slides=", len(deck.get("slides") or []))
    for i, s in enumerate(deck.get("slides") or [], 1):
        title = (s.get("title") or "")[:70]
        print(f"  {i}. [{s.get('layout')}] {title.encode('ascii','replace').decode()}")
    pptx = studio_service.build_pptx_bytes(deck)
    path = os.path.join(OUT, "slide_rich_en.pptx")
    with open(path, "wb") as f:
        f.write(pptx)
    print("PPTX bytes=", len(pptx), "->", path)
    ok = deck.get("source") in ("gemini", "openai", "ai") and len(pptx) > 20000
    print("RESULT", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
