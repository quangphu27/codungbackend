"""Build pptx_subject_prompts_v4.json from EDUBRIDGE EMI/CLIL V4.0 docx."""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from docx import Document

DOCX = os.path.join(ROOT, "DOC-20261030-WA0002_1.docx")
OUT = os.path.join(ROOT, "app", "data", "pptx_subject_prompts_v4.json")

SUBJECT_MAP = {
    "01. MÔN TOÁN": "math",
    "02. MÔN VẬT LÍ": "physics",
    "03. MÔN HÓA HỌC": "chemistry",
    "04. MÔN SINH HỌC": "biology",
    "05. MÔN TIN HỌC": "informatics",
    "06. MÔN CÔNG NGHỆ": "technology",
    "07. MÔN LỊCH SỬ": "history",
    "08. MÔN ĐỊA LÍ": "geography",
    "09. MÔN NGỮ VĂN": "literature",
    "10. MÔN GIÁO DỤC KINH TẾ VÀ PHÁP LUẬT": "civic",
}

PPT_SECTION_MARKERS = (
    "II. Nguyên tắc bám sát SGK",
    "III. Tiến trình sư phạm",
    "IV. Kiểu hình minh họa",
    "VI. Hoạt động tương tác",
    "VII. Gợi ý phân bố slide",
    "VIII. Sản phẩm AI phải xuất",
    "IX. Speaker Notes",
    "X. Quy cách trình bày",
)

SKIP_SECTIONS = ("I. Thông tin đầu vào", "V. Câu giao tiếp")


def _is_heading1(text: str) -> str | None:
    t = text.strip()
    for label in SUBJECT_MAP:
        if t == label or t.endswith(label.split(". ", 1)[-1]):
            return label
    m = re.match(r"(\d{2})\.\s+MÔN\s+", t, re.I)
    if m:
        for label in SUBJECT_MAP:
            if label.startswith(m.group(1)):
                return label
    return None


def _is_heading2(text: str) -> str | None:
    t = text.strip()
    for mark in PPT_SECTION_MARKERS:
        if t.startswith(mark):
            return mark
    for skip in SKIP_SECTIONS:
        if t.startswith(skip):
            return skip
    return None


def _filter_viii(lines: list[str]) -> list[str]:
    keep = []
    for line in lines:
        low = line.lower()
        if any(k in low for k in (
            "ppt", "slide", "speaker", "thuyết minh", "teacher",
            "16:9", "bullet", "bố cục", "hình minh họa",
        )):
            keep.append(line)
    return keep or lines[:8]


def parse_docx(path: str) -> dict:
    doc = Document(path)
    paras = [(p.style.name if p.style else "", (p.text or "").strip()) for p in doc.paragraphs]

    global_bits: list[str] = []
    for style, text in paras[:8]:
        if text and "NGUYÊN TẮC" in text or text.startswith("ĐẦU VÀO") or text.startswith("ĐẦU RA"):
            global_bits.append(text)

    subjects: dict[str, dict] = {}
    current_key: str | None = None
    current_title = ""
    focus = ""
    section_title: str | None = None
    section_lines: list[str] = []
    sections: dict[str, list[str]] = {}

    def flush_section():
        nonlocal section_title, section_lines
        if not current_key or not section_title:
            section_lines = []
            return
        lines = list(section_lines)
        if section_title.startswith("VIII."):
            lines = _filter_viii(lines)
        sections[section_title] = lines
        section_title = None
        section_lines = []

    def flush_subject():
        nonlocal current_key, sections, focus, current_title
        flush_section()
        if not current_key:
            return
        profile = SUBJECT_MAP.get(current_title)
        if not profile:
            return
        parts = []
        if focus:
            parts.append(f"TRỌNG TÂM MÔN: {focus}")
        for mark in PPT_SECTION_MARKERS:
            for st, lines in sections.items():
                if st.startswith(mark.split(".")[0] + "."):
                    if mark.split(".")[0] in st:
                        parts.append(st)
                        parts.extend(lines)
                        break
        subjects[profile] = {
            "title_vi": current_title,
            "focus": focus,
            "prompt_en_clil": "\n".join(parts).strip(),
        }
        sections = {}
        focus = ""

    for style, text in paras:
        if not text:
            continue
        h1 = _is_heading1(text) if "Heading 1" in style or re.match(r"\d{2}\.\s+MÔN", text) else None
        if h1 and h1 in SUBJECT_MAP:
            flush_subject()
            current_title = h1
            current_key = SUBJECT_MAP[h1]
            continue
        if not current_key:
            continue
        if text.startswith("Trọng tâm:"):
            focus = text.replace("Trọng tâm:", "").strip()
            continue
        if text.startswith("PROMPT ") and "EDUBRIDGE" in text:
            continue
        h2 = _is_heading2(text) if "Heading 2" in style else None
        if not h2:
            for mark in PPT_SECTION_MARKERS + SKIP_SECTIONS:
                if text.startswith(mark):
                    h2 = mark if mark in PPT_SECTION_MARKERS else mark
                    break
        if h2:
            if h2 in SKIP_SECTIONS:
                flush_section()
                section_title = None
                continue
            flush_section()
            section_title = text if text.startswith("I") or text.startswith("II") else h2
            continue
        if section_title and section_title not in SKIP_SECTIONS:
            section_lines.append(text)

    flush_subject()

    shared_ii = ""
    if subjects.get("math", {}).get("prompt_en_clil"):
        m = subjects["math"]["prompt_en_clil"]
        if "II." in m:
            shared_ii = m.split("III.")[0].strip()

    global_pptx = """
EDUBRIDGE EMI/CLIL V4.0 — PowerPoint JSON output (Teacher Studio).
ĐẦU VÀO: nội dung SGK/upload đã kiểm chứng; không bịa công thức, số liệu, định luật, trích dẫn.
ĐẦU RA JSON: slides only (English on slide; Vietnamese in Speaker Notes).
Không LaTeX — công thức dạng text/equation chỉnh sửa được. Một ý lớn/slide; tối đa 3 bullets ngắn (≤15 từ/ý) trên slide kiến thức.
Mỗi slide: image_keyword + image_scene + visual_element mô tả đúng kiến thức SGK (sơ đồ/bản đồ/đồ thị/thí nghiệm — không ảnh trang trí).
Speaker Notes 60–100+ từ EN: script GV, classroom English, expected answers, misconceptions — không chỉ lặp bullet.
Ẩn đáp án trên slide câu hỏi; đáp án ở Notes. Bám GDPT 2018 + CLIL 4Cs. Chỉ slide mà SGK thực sự hỗ trợ.
""".strip()

    return {
        "version": "EMI-CLIL-V4.0",
        "source_doc": os.path.basename(path),
        "global_pptx_rules": global_pptx,
        "shared_sgk_clil_rules": shared_ii,
        "subjects": subjects,
    }


def main():
    if not os.path.isfile(DOCX):
        print("Missing", DOCX)
        return 1
    data = parse_docx(DOCX)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Wrote", OUT, "subjects:", list(data["subjects"].keys()))
    for k, v in data["subjects"].items():
        print(f"  {k}: {len(v.get('prompt_en_clil') or '')} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
