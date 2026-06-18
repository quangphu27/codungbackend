from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def generate_career_pdf(result: dict, student_name: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#0F2744"),
        spaceAfter=20,
    )
    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#F39C4A"),
        spaceAfter=10,
    )

    story = []
    story.append(Paragraph("BÁO CÁO HƯỚNG NGHIỆP", title_style))
    story.append(Paragraph(f"Học sinh: {student_name}", styles["Normal"]))
    story.append(Spacer(1, 20))

    sections = [
        ("Điểm mạnh", result.get("strengths", [])),
        ("Điểm yếu", result.get("weaknesses", [])),
        ("Gợi ý nghề nghiệp", result.get("career_suggestions", [])),
    ]

    for title, items in sections:
        story.append(Paragraph(title, heading_style))
        if isinstance(items, list):
            for item in items:
                story.append(Paragraph(f"• {item}", styles["Normal"]))
        else:
            story.append(Paragraph(str(items), styles["Normal"]))
        story.append(Spacer(1, 12))

    story.append(Paragraph("Lộ trình học tập", heading_style))
    story.append(Paragraph(result.get("learning_roadmap", ""), styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Kế hoạch phát triển", heading_style))
    story.append(Paragraph(result.get("development_plan", ""), styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_portfolio_pdf(portfolio: dict, student_name: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#0F2744"),
        spaceAfter=20,
    )

    story = []
    story.append(Paragraph("HỒ SƠ HỌC TẬP", title_style))
    story.append(Paragraph(f"Học sinh: {student_name}", styles["Normal"]))
    story.append(Spacer(1, 20))

    stats = portfolio.get("stats", {})
    if stats:
        data = [["Chỉ số", "Giá trị"]]
        for key, value in stats.items():
            data.append([key, str(value)])
        table = Table(data, colWidths=[8 * cm, 8 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2744")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(table)

    skills = portfolio.get("skills_achieved", [])
    if skills:
        story.append(Spacer(1, 20))
        story.append(Paragraph("Kỹ năng đạt được:", styles["Heading2"]))
        for skill in skills:
            story.append(Paragraph(f"• {skill}", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer
