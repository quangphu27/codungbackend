"""Generate a complete English PowerPoint about Prime Numbers (10-15 slides)."""
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
        grade="Grade 6",
        subject="Mathematics",
        topic="Prime Numbers",
        slide_count=12,
        lesson_context={
            "title_en": "Prime Numbers",
            "objectives_en": [
                "Define prime and composite numbers",
                "Identify primes using divisibility rules",
                "Use the Sieve of Eratosthenes",
                "Apply primes in puzzles and real life",
            ],
            "sections": [
                {"heading_en": "What is a prime number?"},
                {"heading_en": "Primes vs composites"},
                {"heading_en": "Sieve of Eratosthenes"},
                {"heading_en": "Practice and games"},
            ],
            "vocabulary": [
                {"term": "prime"},
                {"term": "composite"},
                {"term": "factor"},
                {"term": "divisible"},
                {"term": "sieve"},
            ],
        },
    )

    slides = deck.get("slides") or []
    print("source=", deck.get("source"), "slides=", len(slides))
    for i, s in enumerate(slides, 1):
        title = (s.get("title") or "")[:70]
        layout = s.get("layout")
        img = s.get("image_keyword") or ""
        print(f"{i:02d} [{layout}] {title} | {img}")

    pptx = studio_service.build_pptx_bytes(deck)
    path = os.path.join(OUT, "Prime_Numbers_Slides.pptx")
    with open(path, "wb") as f:
        f.write(pptx)
    print("OK bytes=", len(pptx))
    print("FILE=", path)
