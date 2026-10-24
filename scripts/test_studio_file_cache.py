"""Verify Studio Word/PPTX are stored once and reloaded without rebuild."""
import time

from app import create_app
from app.services import studio_service
from app.services.studio_files import get_or_build_file


def main():
    lesson = studio_service._fallback_lesson(
        "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du", "bilingual", "",
    )
    quiz = studio_service._fallback_quiz(
        "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du", 6,
        ["multiple_choice", "true_false", "fill_blank", "essay"], "en",
    )
    deck = studio_service._fallback_slides(
        "Lớp 9", "Ngữ Văn", "Truyện Kiều của Nguyễn Du", 6, "en",
    )
    deck["light"] = True

    app = create_app()
    with app.app_context():
        t1 = time.perf_counter()
        docx1 = get_or_build_file(
            "lesson_docx", lesson, "giao_an_kieu.docx",
            lambda: studio_service.build_docx_bytes(lesson),
        )
        t2 = time.perf_counter()
        docx2 = get_or_build_file(
            "lesson_docx", lesson, "giao_an_kieu.docx",
            lambda: (_ for _ in ()).throw(RuntimeError("MUST NOT REBUILD DOCX")),
        )
        t3 = time.perf_counter()
        q1 = get_or_build_file(
            "quiz_docx", quiz, "de_kieu.docx",
            lambda: studio_service.quiz_to_docx_bytes(quiz),
        )
        t4 = time.perf_counter()
        q2 = get_or_build_file(
            "quiz_docx", quiz, "de_kieu.docx",
            lambda: (_ for _ in ()).throw(RuntimeError("MUST NOT REBUILD QUIZ")),
        )
        t5 = time.perf_counter()
        p1 = get_or_build_file(
            "pptx", deck, "slide_kieu.pptx",
            lambda: studio_service.build_pptx_bytes(deck, light=True),
        )
        t6 = time.perf_counter()
        p2 = get_or_build_file(
            "pptx", deck, "slide_kieu.pptx",
            lambda: (_ for _ in ()).throw(RuntimeError("MUST NOT REBUILD PPTX")),
        )
        t7 = time.perf_counter()

    print(f"docx first={t2 - t1:.2f}s cached={t3 - t2:.2f}s bytes={len(docx1)} same={docx1 == docx2}")
    print(f"quiz first={t4 - t3:.2f}s cached={t5 - t4:.2f}s bytes={len(q1)} same={q1 == q2}")
    print(f"pptx first={t6 - t5:.2f}s cached={t7 - t6:.2f}s bytes={len(p1)} same={p1 == p2}")
    assert docx1 == docx2 and q1 == q2 and p1 == p2
    assert docx1[:2] == b"PK" and q1[:2] == b"PK" and p1[:2] == b"PK"
    assert t3 - t2 < t2 - t1
    assert t5 - t4 < t4 - t3
    assert t7 - t6 < t6 - t5
    print("PASS save and reload Word/PPTX from cache; second download does not rebuild")


if __name__ == "__main__":
    main()
