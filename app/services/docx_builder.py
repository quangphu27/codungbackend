"""
Professional lesson-plan DOCX builder for Teacher Studio.
Clear structure, bold headings, font sizes, tables, alignment.
"""
from __future__ import annotations

import io
from typing import Any


NAVY = (0x0F, 0x27, 0x44)
ORANGE = (0xF3, 0x9C, 0x4A)
TEAL = (0x1A, 0x9B, 0x8E)
GRAY = (0x4B, 0x55, 0x63)


def _rgb(tup):
    from docx.shared import RGBColor
    return RGBColor(*tup)


def _set_run(run, *, size=12, bold=False, italic=False, color=None, name="Times New Roman"):
    from docx.shared import Pt
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = _rgb(color)
    # Ensure East Asian font compatibility on Windows/WPS
    try:
        r = run._element
        rPr = r.get_or_add_rPr()
        from docx.oxml.ns import qn
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), name)
        rFonts.set(qn("w:hAnsi"), name)
        rFonts.set(qn("w:eastAsia"), "Times New Roman")
    except Exception:
        pass


def _add_para(doc, text="", *, size=12, bold=False, italic=False, color=None,
              align="left", space_before=0, space_after=6, first_line=False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.shared import Pt, Twips

    p = doc.add_paragraph()
    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    p.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.LEFT)
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if first_line:
        pf.first_line_indent = Pt(18)
    run = p.add_run(str(text or ""))
    _set_run(run, size=size, bold=bold, italic=italic, color=color)
    return p


def _add_heading_custom(doc, text, level=1):
    """Styled section headings (not relying on Word built-in styles alone)."""
    sizes = {0: 18, 1: 14, 2: 13, 3: 12}
    colors = {0: NAVY, 1: NAVY, 2: TEAL, 3: GRAY}
    align = "center" if level == 0 else "left"
    before = 14 if level <= 1 else 10
    p = _add_para(
        doc, text,
        size=sizes.get(level, 12),
        bold=True,
        color=colors.get(level, NAVY),
        align=align,
        space_before=before,
        space_after=6,
    )
    if level == 1:
        # underline feel via bottom border
        try:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "12")
            bottom.set(qn("w:space"), "4")
            bottom.set(qn("w:color"), "0F2744")
            pBdr.append(bottom)
            pPr.append(pBdr)
        except Exception:
            pass
    return p


def _add_bullet(doc, text, *, size=12, bold_prefix=None):
    from docx.shared import Pt
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.35
    if bold_prefix:
        r1 = p.add_run(str(bold_prefix))
        _set_run(r1, size=size, bold=True, color=NAVY)
        r2 = p.add_run(str(text))
        _set_run(r2, size=size, color=GRAY)
    else:
        r = p.add_run(str(text))
        _set_run(r, size=size, color=GRAY)
    return p


def _set_cell_shading(cell, hex_color: str):
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), hex_color)
        shd.set(qn("w:val"), "clear")
        tcPr.append(shd)
    except Exception:
        pass


def _fill_cell(cell, text, *, bold=False, size=11, color=None, center=False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    cell.text = ""
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(str(text or ""))
    _set_run(run, size=size, bold=bold, color=color or NAVY)


def _add_info_table(doc, rows: list[tuple[str, str]]):
    """2-column info table (Label | Value)."""
    from docx.shared import Cm, Pt

    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    table.autofit = True
    for i, (label, value) in enumerate(rows):
        _fill_cell(table.cell(i, 0), label, bold=True, size=11, color=NAVY)
        _fill_cell(table.cell(i, 1), value, size=11, color=GRAY)
        _set_cell_shading(table.cell(i, 0), "E8F1FB")
        table.cell(i, 0).width = Cm(4.5)
        table.cell(i, 1).width = Cm(12)
    doc.add_paragraph()


def _add_data_table(doc, headers: list[str], rows: list[list[Any]]):
    from docx.shared import Pt

    cols = max(len(headers), 1)
    table = doc.add_table(rows=1 + len(rows), cols=cols)
    table.style = "Table Grid"
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        _fill_cell(cell, h, bold=True, size=11, color=(0xFF, 0xFF, 0xFF), center=True)
        _set_cell_shading(cell, "0F2744")
    for r_idx, row in enumerate(rows, start=1):
        for c in range(cols):
            val = row[c] if c < len(row) else ""
            cell = table.cell(r_idx, c)
            _fill_cell(cell, val, size=11, color=GRAY)
            if r_idx % 2 == 0:
                _set_cell_shading(cell, "F7FAFC")
    doc.add_paragraph()


def _procedure_rows(lesson: dict) -> list[list[str]]:
    """Build teaching procedure table from sections."""
    rows = []
    default_times = ["5'", "12'", "15'", "10'", "8'", "5'"]
    for i, sec in enumerate(lesson.get("sections") or []):
        heading = sec.get("heading_vi") or sec.get("heading_en") or f"Step {i+1}"
        content = (sec.get("content_vi") or sec.get("content_en") or "").strip()
        # shorten for table cell
        if len(content) > 220:
            content = content[:217] + "..."
        time = sec.get("duration") or (default_times[i] if i < len(default_times) else "8'")
        teacher = sec.get("teacher_activity") or "Hướng dẫn / Facilitate"
        student = sec.get("student_activity") or "Thực hiện / Practice"
        rows.append([str(time), str(heading), str(content), str(teacher), str(student)])
    return rows


def build_rich_docx_bytes(lesson: dict) -> bytes:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)

    title_vi = lesson.get("title_vi") or lesson.get("title") or "Giáo án trải nghiệm"
    title_en = lesson.get("title_en") or ""
    grade = lesson.get("grade") or ""
    subject = lesson.get("subject") or ""
    topic = lesson.get("topic") or ""
    duration = lesson.get("duration_minutes") or lesson.get("duration") or 45
    materials = lesson.get("materials") or []
    if isinstance(materials, str):
        materials = [materials]

    # ===== HEADER =====
    _add_para(doc, "EXPERIENTIAL LEARNING IN ENGLISH", size=11, bold=True, color=ORANGE, align="center", space_after=2)
    _add_para(doc, "GIÁO ÁN BÀI HỌC TRẢI NGHIỆM", size=12, bold=True, color=NAVY, align="center", space_after=4)
    _add_heading_custom(doc, title_vi, level=0)
    if title_en and title_en != title_vi:
        _add_para(doc, title_en, size=13, bold=True, italic=True, color=TEAL, align="center", space_after=10)

    # ===== INFO TABLE =====
    _add_heading_custom(doc, "I. THÔNG TIN CHUNG / GENERAL INFORMATION", level=1)
    _add_info_table(doc, [
        ("Khối / Grade", grade),
        ("Môn / Subject", subject),
        ("Chủ đề / Topic", topic),
        ("Thời lượng / Duration", f"{duration} minutes"),
        ("Hình thức / Mode", lesson.get("mode") or "Classroom · Experiential Learning"),
        ("Ngôn ngữ / Language", lesson.get("language") or "bilingual"),
    ])

    # ===== OBJECTIVES =====
    _add_heading_custom(doc, "II. MỤC TIÊU BÀI HỌC / LEARNING OBJECTIVES", level=1)
    objs_vi = lesson.get("objectives_vi") or []
    objs_en = lesson.get("objectives_en") or []
    if objs_vi:
        _add_para(doc, "Mục tiêu (Tiếng Việt)", size=12, bold=True, color=TEAL, space_before=4, space_after=4)
        for i, o in enumerate(objs_vi, 1):
            _add_bullet(doc, f" {o}", bold_prefix=f"{i}.")
    if objs_en:
        _add_para(doc, "Objectives (English)", size=12, bold=True, color=TEAL, space_before=8, space_after=4)
        for i, o in enumerate(objs_en, 1):
            _add_bullet(doc, f" {o}", bold_prefix=f"{i}.")

    # ===== MATERIALS =====
    _add_heading_custom(doc, "III. ĐỒ DÙNG DẠY HỌC / MATERIALS", level=1)
    if materials:
        for m in materials:
            _add_bullet(doc, f" {m}")
    else:
        for m in [
            "Projector / slides",
            "Worksheet / handout",
            "Board & markers",
            "Group activity cards",
        ]:
            _add_bullet(doc, f" {m}")

    # ===== PROCEDURE TABLE =====
    _add_heading_custom(doc, "IV. TIẾN TRÌNH DẠY HỌC / TEACHING PROCEDURE", level=1)
    _add_para(
        doc,
        "Bảng tiến trình (thời gian – hoạt động – nội dung – giáo viên – học sinh).",
        size=11, italic=True, color=GRAY, space_after=6,
    )
    proc = _procedure_rows(lesson)
    if not proc:
        proc = [["45'", "Main lesson", f"Explore {topic}", "Guide", "Practice"]]
    _add_data_table(
        doc,
        ["Time", "Stage / Phần", "Content / Nội dung", "Teacher", "Students"],
        proc,
    )

    # ===== DETAILED SECTIONS =====
    _add_heading_custom(doc, "V. NỘI DUNG CHI TIẾT / DETAILED CONTENT", level=1)
    for i, sec in enumerate(lesson.get("sections") or [], 1):
        h_vi = sec.get("heading_vi") or ""
        h_en = sec.get("heading_en") or ""
        heading = h_vi or h_en or f"Phần {i}"
        if h_vi and h_en and h_vi != h_en:
            heading = f"{h_vi} / {h_en}"
        _add_heading_custom(doc, f"{i}. {heading}", level=2)

        if sec.get("duration"):
            _add_para(doc, f"Thời gian / Time: {sec.get('duration')}", size=11, italic=True, color=ORANGE, space_after=4)

        c_vi = (sec.get("content_vi") or "").strip()
        c_en = (sec.get("content_en") or "").strip()
        if c_vi:
            _add_para(doc, "Nội dung (VI):", size=11, bold=True, color=NAVY, space_after=2)
            _add_para(doc, c_vi, size=12, color=GRAY, align="justify", first_line=True, space_after=6)
        if c_en:
            _add_para(doc, "Content (EN):", size=11, bold=True, color=TEAL, space_after=2)
            _add_para(doc, c_en, size=12, color=GRAY, align="justify", first_line=True, space_after=6)

        if sec.get("teacher_activity"):
            _add_para(doc, f"Hoạt động GV / Teacher: {sec['teacher_activity']}", size=11, color=GRAY, space_after=3)
        if sec.get("student_activity"):
            _add_para(doc, f"Hoạt động HS / Students: {sec['student_activity']}", size=11, color=GRAY, space_after=6)

    # ===== VOCABULARY TABLE =====
    vocab = lesson.get("vocabulary") or []
    _add_heading_custom(doc, "VI. TỪ VỰNG / VOCABULARY", level=1)
    if vocab:
        rows = []
        for v in vocab:
            rows.append([
                v.get("term") or "",
                v.get("meaning_vi") or v.get("meaning") or "",
                v.get("example") or "",
            ])
        _add_data_table(doc, ["Term (EN)", "Meaning (VI)", "Example sentence"], rows)
    else:
        _add_para(doc, "Chưa có danh sách từ vựng.", size=11, italic=True, color=GRAY)

    # ===== ASSESSMENT =====
    _add_heading_custom(doc, "VII. KIỂM TRA – ĐÁNH GIÁ / ASSESSMENT", level=1)
    assessment = lesson.get("assessment") or {}
    if isinstance(assessment, str):
        _add_para(doc, assessment, size=12, align="justify", color=GRAY, first_line=True)
    else:
        methods = assessment.get("methods") or [
            "Observation during group work",
            "Oral questions / quick check",
            "Exit ticket or short quiz",
        ]
        criteria = assessment.get("criteria") or [
            "Participation and collaboration",
            "Correct use of key concepts / vocabulary",
            "Ability to apply knowledge to a new situation",
        ]
        _add_para(doc, "Phương pháp / Methods", size=12, bold=True, color=TEAL, space_after=4)
        for m in methods:
            _add_bullet(doc, f" {m}")
        _add_para(doc, "Tiêu chí / Criteria", size=12, bold=True, color=TEAL, space_before=8, space_after=4)
        for c in criteria:
            _add_bullet(doc, f" {c}")

    # ===== HOMEWORK / REFLECTION =====
    _add_heading_custom(doc, "VIII. CỦNG CỐ – BÀI TẬP / CONSOLIDATION & HOMEWORK", level=1)
    homework = lesson.get("homework") or lesson.get("consolidation") or [
        f"Review key ideas about {topic}.",
        "Write 3–5 sentences in English using new vocabulary.",
        "Prepare one real-life example related to the topic for next lesson.",
    ]
    if isinstance(homework, str):
        homework = [homework]
    for h in homework:
        _add_bullet(doc, f" {h}")

    # ===== NOTES =====
    _add_heading_custom(doc, "IX. GHI CHÚ / NOTES", level=1)
    note = lesson.get("notes") or lesson.get("note") or (
        "Giáo viên điều chỉnh thời gian và hoạt động phù hợp năng lực lớp. "
        "Encourage bilingual interaction and experiential tasks."
    )
    _add_para(doc, note, size=11, italic=True, color=GRAY, align="justify")

    # Footer line
    _add_para(doc, "", space_after=8)
    _add_para(
        doc,
        "— Teacher Studio · Experiential Learning Platform —",
        size=9, italic=True, color=ORANGE, align="center", space_before=12,
    )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
