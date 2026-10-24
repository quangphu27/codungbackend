"""Mọi môn trên Teacher Studio phải có giáo án fallback chuẩn GDPT 2018 (4 hoạt động)."""
from app.services.studio_service import (
    STUDIO_GDPT_SUBJECTS,
    _fallback_lesson,
    _is_generic_teaching_text,
    _normalize_gdpt_sections,
    _subject_profile_key,
)

SAMPLE_TOPICS = {
    "Ngữ văn": "Chiếc thuyền ngoài xa",
    "Tiếng Anh": "Past simple tense",
    "Toán": "Đạo hàm",
    "Lịch sử": "Cách mạng tháng Tám 1945",
    "Địa lý": "Khí hậu Việt Nam",
    "Giáo dục công dân": "Quyền và nghĩa vụ công dân",
    "Vật lý": "Định luật Ohm",
    "Hóa học": "Phản ứng oxi hóa khử",
    "Sinh học": "Quang hợp",
    "Khoa học tự nhiên": "Năng lượng và chuyển hóa",
    "Công nghệ": "An toàn điện trong gia đình",
    "Tin học": "Thuật toán sắp xếp",
    "Giáo dục thể chất": "Bài thể dục phát triển chung",
    "Mĩ thuật": "Màu sắc trong tranh",
    "Âm nhạc": "Khuông nhạc và nốt nhạc",
    "Hoạt động trải nghiệm": "Kỹ năng giao tiếp tích cực",
}


def _lesson_blob(lesson: dict) -> str:
    parts = [
        lesson.get("title_vi"), lesson.get("core_content_vi"),
        " ".join(lesson.get("objectives_vi") or []),
    ]
    for s in lesson.get("sections") or []:
        parts.append(s.get("content_vi") or "")
    return " ".join(str(p or "") for p in parts)


def main() -> None:
    errors = []
    for subject in STUDIO_GDPT_SUBJECTS:
        topic = SAMPLE_TOPICS[subject]
        lesson = _fallback_lesson("Lớp 9", subject, topic, "bilingual")
        profile = _subject_profile_key(subject, topic)
        secs = _normalize_gdpt_sections(lesson.get("sections"))
        if len(secs) != 4:
            errors.append(f"{subject}: expected 4 sections, got {len(secs)}")
        if secs[0]["heading_vi"] != "Mở đầu (Khởi động)":
            errors.append(f"{subject}: wrong stage 1 heading")
        if secs[2]["heading_vi"] != "Luyện tập":
            errors.append(f"{subject}: wrong stage 3 heading")
        if topic not in _lesson_blob(lesson):
            errors.append(f"{subject}: topic missing in lesson blob")
        if lesson.get("subject") != subject:
            errors.append(f"{subject}: subject field mismatch")
        if profile != "experiential" and _is_generic_teaching_text(_lesson_blob(lesson)):
            errors.append(f"{subject}: generic experiential filler in fallback")
        if subject == "Ngữ văn" and "Nguyễn Du" in _lesson_blob(lesson) and "Kiều" not in topic:
            errors.append(f"{subject}: wrongly used Truyện Kiều template for {topic}")
        if subject == "Toán" and profile != "math":
            errors.append(f"{subject}: expected math profile, got {profile}")

    if errors:
        print("FAIL all-subjects GDPT lesson:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print(f"PASS all {len(STUDIO_GDPT_SUBJECTS)} subjects — GDPT 4-stage fallback + correct profile.")


if __name__ == "__main__":
    main()
