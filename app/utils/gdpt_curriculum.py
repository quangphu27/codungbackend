"""Khối lớp & môn học GDPT — Teacher Studio và Kho học liệu."""
from __future__ import annotations

import re

CURRICULUM_GRADES = tuple(f"Lớp {i}" for i in range(6, 13))

SUBJECTS_THCS = (
    "Ngữ văn",
    "Toán",
    "Giáo dục công dân",
    "Lịch sử và Địa lí",
    "Khoa học tự nhiên",
    "Công nghệ",
    "Tin học",
    "Giáo dục thể chất",
    "Nghệ thuật (Âm nhạc và Mĩ thuật)",
    "Hoạt động trải nghiệm, hướng nghiệp",
    "Nội dung giáo dục của địa phương",
)

SUBJECTS_THPT = (
    "Ngữ văn",
    "Toán",
    "Lịch sử",
    "Địa lí",
    "Giáo dục kinh tế và pháp luật",
    "Vật lí",
    "Hóa học",
    "Sinh học",
    "Công nghệ",
    "Tin học",
    "Âm nhạc",
    "Mĩ thuật",
    "Giáo dục thể chất",
    "Giáo dục quốc phòng và an ninh",
    "Hoạt động trải nghiệm, hướng nghiệp",
    "Nội dung giáo dục của địa phương",
)

STUDIO_GDPT_SUBJECTS = tuple(dict.fromkeys(SUBJECTS_THCS + SUBJECTS_THPT))


def _grade_num(grade: str) -> int:
    m = re.search(r"(\d+)", str(grade or ""))
    return int(m.group(1)) if m else 0


def subjects_for_grade(grade: str) -> tuple[str, ...]:
    n = _grade_num(grade)
    if n >= 10:
        return SUBJECTS_THPT
    if n >= 6:
        return SUBJECTS_THCS
    return ()


def zero_kind_counts() -> dict:
    return {"total": 0, "lesson": 0, "quiz": 0, "pptx": 0, "file": 0}
