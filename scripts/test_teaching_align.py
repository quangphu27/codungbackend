"""Offline: Word/PPTX fallbacks stick to Topic + Subject teaching content."""
from app.services.studio_service import (
    _fallback_lesson,
    _fallback_slides,
    _fit_slide_count,
    _is_generic_teaching_text,
    _is_kieu_topic,
    _scrub_generic_lesson,
    _scrub_generic_slides,
    _teaching_content_rules,
)


def _must_contain(blob: str, words: tuple[str, ...], label: str) -> None:
    low = blob.lower()
    missing = [w for w in words if w.lower() not in low]
    assert not missing, f"{label} missing {missing}"


def _must_not_contain(blob: str, words: tuple[str, ...], label: str) -> None:
    low = blob.lower()
    hit = [w for w in words if w.lower() in low]
    assert not hit, f"{label} has slogan {hit}"


def main() -> None:
    assert _is_kieu_topic("Ngu Van", "Truyen Kieu")
    assert _is_kieu_topic("Ngữ Văn", "Truyện Kiều")

    from app.services.studio_service import _normalize_gdpt_sections

    lesson = _fallback_lesson("Lớp 9", "Ngữ Văn", "Truyện Kiều", "bilingual")
    assert len(lesson["sections"]) == 4
    assert lesson["sections"][1]["heading_vi"] == "Hình thành kiến thức mới"
    assert lesson["sections"][3]["heading_vi"] == "Vận dụng"
    norm = _normalize_gdpt_sections(lesson["sections"])
    assert len(norm) == 4 and norm[0]["heading_vi"].startswith("Mở đầu")
    blob = " ".join([
        lesson["title_vi"],
        lesson["title_en"],
        lesson.get("core_content_vi", ""),
        lesson.get("core_content_en", ""),
        " ".join(lesson["objectives_vi"]),
        " ".join(s["content_vi"] + " " + s["content_en"] for s in lesson["sections"]),
    ])
    _must_contain(blob, ("Nguyễn Du", "Thúy Kiều", "lục bát", "hiếu", "Kim Trọng"), "lesson")
    _must_not_contain(
        blob,
        ("hands-on", "mini product", "experiential learning", "create a mini"),
        "lesson",
    )

    slides = _fallback_slides("Lớp 9", "Ngữ Văn", "Truyện Kiều", 10, "en")["slides"]
    assert len(slides) == 10
    sblob = " ".join(
        str(s.get("title") or "") + " " + " ".join(s.get("bullets") or [])
        for s in slides
    )
    _must_contain(sblob, ("Nguyễn Du", "lục bát", "Thúy Kiều", "Hoạn Thư"), "slides")
    _must_not_contain(
        sblob,
        ("hands-on exploration", "create a mini product", "experiential learning", "I learned"),
        "slides",
    )

    math = _fallback_lesson("Lớp 12", "Toán", "Đạo hàm", "bilingual")
    assert "Đạo hàm" in math["title_vi"]
    assert "trải nghiệm" not in math["title_vi"].lower()

    padded = _fit_slide_count(
        [{"layout": "title", "title": "Truyện Kiều", "bullets": ["open"]}],
        10,
        "Truyện Kiều",
        "en",
        "Lớp 9",
        "Ngữ Văn",
    )
    assert len(padded) == 10
    pblob = " ".join(str(s.get("title") or "") for s in padded).lower()
    assert any(k in pblob for k in ("kiều", "luc", "character", "author", "nguyễn", "theme"))

    generic = {
        "title_vi": "Giáo án trải nghiệm chính",
        "title_en": "Experiential Learning",
        "core_content_vi": "Học sinh tạo sản phẩm nhỏ",
        "core_content_en": "Create a mini product",
        "sections": [{
            "heading_vi": "Trải nghiệm chính",
            "heading_en": "Experience",
            "content_vi": "hands-on",
            "content_en": "hands-on",
        }],
        "vocabulary": [{"term": "experience", "meaning_vi": "trải nghiệm"}],
    }
    clean = _scrub_generic_lesson(generic, lesson)
    assert "Kiều" in (clean.get("title_vi") or "") or "Ngữ văn" in (clean.get("title_vi") or "")
    assert "mini product" not in (clean.get("core_content_en") or "").lower()

    dirty_slides = [
        {"layout": "title", "title": "Hi", "bullets": ["x"]},
        {"layout": "content", "title": "Group", "bullets": ["Create a mini product", "hands-on exploration"]},
        {"layout": "closing", "title": "Bye", "bullets": []},
    ]
    fixed = _scrub_generic_slides(dirty_slides, slides)
    assert not _is_generic_teaching_text(" ".join(fixed[1].get("bullets") or []))

    rules = _teaching_content_rules("Lớp 9", "Ngữ Văn", "Truyện Kiều")
    assert "CHỦ ĐỀ" in rules and "Nguyễn Du" in rules
    print("PASS teaching-align Word/PPTX")


if __name__ == "__main__":
    main()
