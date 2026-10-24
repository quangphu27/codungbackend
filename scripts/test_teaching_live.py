"""Live light generate: Lớp 9 / Ngữ Văn / Truyện Kiều — lesson + slides on topic."""
from app import create_app
from app.services.studio_service import generate_lesson_draft, generate_pptx_draft, _is_generic_teaching_text

NEED = ("nguyễn du", "kiều", "lục bát")
BAD = ("hands-on exploration", "create a mini product", "experiential learning")


def _blob_lesson(d: dict) -> str:
    parts = [
        d.get("title_vi"), d.get("title_en"),
        d.get("core_content_vi"), d.get("core_content_en"),
        " ".join(d.get("objectives_vi") or []),
        " ".join(d.get("objectives_en") or []),
    ]
    for s in d.get("sections") or []:
        parts.append(f"{s.get('heading_vi')} {s.get('content_vi')} {s.get('content_en')}")
    return " ".join(str(p or "") for p in parts).lower()


def _blob_slides(d: dict) -> str:
    bits = []
    for s in d.get("slides") or []:
        bits.append(str(s.get("title") or ""))
        bits.extend(s.get("bullets") or [])
        bits.extend(s.get("left_bullets") or [])
        bits.extend(s.get("right_bullets") or [])
    return " ".join(str(x or "") for x in bits).lower()


def main() -> None:
    app = create_app()
    with app.app_context():
        lesson = generate_lesson_draft(
            grade="Lớp 9",
            subject="Ngữ Văn",
            topic="Truyện Kiều",
            description="Dạy tác giả, lục bát, nhân vật và chữ hiếu.",
            light=True,
        )
        pptx = generate_pptx_draft(
            grade="Lớp 9",
            subject="Ngữ Văn",
            topic="Truyện Kiều",
            slide_count=10,
            lesson_context=lesson,
            description="Dạy tác giả, lục bát, nhân vật và chữ hiếu.",
            light=True,
        )
    lb = _blob_lesson(lesson)
    sb = _blob_slides(pptx)
    print("LESSON source=", lesson.get("source"), "title=", lesson.get("title_vi"))
    print("LESSON core=", (lesson.get("core_content_vi") or "")[:180])
    print("PPTX source=", pptx.get("source"), "n=", len(pptx.get("slides") or []))
    for i, s in enumerate(pptx.get("slides") or [], 1):
        print(f"  S{i} {s.get('layout')} | {s.get('title')} | {s.get('bullets')}")
    errors = []
    if not any(k in lb for k in NEED):
        errors.append("lesson missing Kiều knowledge")
    if not any(k in sb for k in NEED):
        errors.append("slides missing Kiều knowledge")
    if any(b in lb for b in BAD) or _is_generic_teaching_text(lb):
        errors.append("lesson still generic slogan")
    if any(b in sb for b in BAD):
        errors.append("slides still generic slogan")
    if errors:
        print("FAIL", errors)
        raise SystemExit(1)
    print("PASS live light lesson+pptx on Truyện Kiều")


if __name__ == "__main__":
    main()
