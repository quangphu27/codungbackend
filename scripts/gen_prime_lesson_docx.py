"""Generate a fully formatted Word lesson plan about Prime Numbers."""
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
    lesson = studio_service.generate_lesson_draft(
        grade="Lớp 6",
        subject="Toán / Mathematics",
        topic="Số nguyên tố / Prime Numbers",
        language="bilingual",
        extra_requirements=(
            "Giáo án đầy đủ: mục tiêu, đồ dùng, tiến trình có thời gian, "
            "hoạt động GV/HS, từ vựng, đánh giá, bài tập về nhà. "
            "Nội dung về định nghĩa số nguyên tố, hợp số, sàng Eratosthenes."
        ),
    )
    def safe(s):
        return str(s or "").encode("ascii", "replace").decode("ascii")

    print("source=", lesson.get("source"))
    print("title=", safe(lesson.get("title_vi") or lesson.get("title_en"))[:80])
    print("sections=", len(lesson.get("sections") or []))
    print("vocab=", len(lesson.get("vocabulary") or []))
    print("objectives_vi=", len(lesson.get("objectives_vi") or []))

    docx = studio_service.build_docx_bytes(lesson)
    path = os.path.join(OUT, "GiaoAn_So_Nguyen_To.docx")
    with open(path, "wb") as f:
        f.write(docx)
    print("OK bytes=", len(docx))
    print("FILE=", path)
