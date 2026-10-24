"""
Teacher Studio — AI tạo giáo án (DOCX), đề kiểm tra, slide PPTX.
Dùng Gemini Pro (ưu tiên) qua AI Gateway; API key gắn bằng GEMINI_API_KEY.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from typing import Any

from flask import current_app

from app.services.ai_service import _call_ai


class StudioGenerateError(Exception):
    """AI không tạo được học liệu — không dùng bản mẫu tạm."""


SYSTEM_MATH_EXAM = (
    "You are a Vietnam high-school mathematics examiner (GDPT 2018). "
    "Write a real exam: every item must require computing a derivative, integral, limit, or solving an equation. "
    "Options must be distinct formulas or numbers (include typical student mistakes). "
    "FORBIDDEN question stems: 'which concept relates to', 'khái niệm nào liên quan', "
    "'correct content about the topic', 'nội dung đúng về'. "
    "FORBIDDEN options: 'unrelated concept', 'incorrect information', 'none of the above', "
    "'khái niệm không liên quan', 'thông tin sai', 'không có đáp án'. "
    "Student paper in ENGLISH. JSON only."
)


SYSTEM_TEACHER = (
    "Bạn là chuyên gia biên soạn giáo án, đề và học liệu theo Chương trình GDPT 2018. "
    "Đúng MÔN, đúng CHỦ ĐỀ, đúng thuật ngữ và kiến thức môn học. "
    "Giáo án theo 4 hoạt động: Mở đầu → Hình thành kiến thức mới → Luyện tập → Vận dụng. "
    "Không gán mọi môn thành Hoạt động trải nghiệm. Trả về đúng JSON, không markdown."
)

SYSTEM_LESSON = (
    "Bạn soạn giáo án song ngữ Việt–Anh theo Chương trình GDPT 2018: đúng MÔN, đúng CHỦ ĐỀ, "
    "đúng thuật ngữ sư phạm và kiến thức môn học. Tiến trình đúng 4 hoạt động: "
    "Mở đầu (Khởi động) → Hình thành kiến thức mới → Luyện tập → Vận dụng. "
    "Không biến mọi môn thành Hoạt động trải nghiệm. JSON hợp lệ, không markdown."
)

SYSTEM_EIGHT_STEP = (
    "You create 8-step English-medium lessons for Vietnamese GDPT 2018 classes. "
    "Content must match the EXACT subject and topic with correct subject terminology — "
    "not generic experiential-learning filler. Student text in English; meaning_vi and reading "
    "translation in Vietnamese. Quiz items are real exam questions for that subject. JSON only."
)


def _subject_blob(subject: str, topic: str) -> str:
    return f"{subject or ''} {topic or ''}".lower()


def _is_math_topic(subject: str = "", topic: str = "") -> bool:
    blob = _subject_blob(subject, topic)
    keys = (
        "toán", "toan", "math", "đạo hàm", "dao ham", "derivative",
        "tích phân", "tich phan", "integral", "nguyên hàm", "nguyen ham",
        "hình học", "hinh hoc", "đại số", "dai so", "giải tích", "giai tich",
        "phương trình", "phuong trinh", "bất phương trình", "logarit", "logarithm",
        "mũ", "lượng giác", "luong giac", "vector", "xác suất", "xac suat",
        "tổ hợp", "to hop", "hàm số", "ham so", "giới hạn", "gioi han",
        "calculus", "algebra", "geometry", "trigonometry",
    )
    return any(k in blob for k in keys)


def _is_literature_subject(subject: str = "") -> bool:
    blob = _fold_text(subject or "")
    return any(k in blob for k in ("ngu van", "van hoc", "literature"))


def _is_literature_topic(subject: str = "", topic: str = "") -> bool:
    """Chủ đề/tác phẩm văn học (không chỉ vì môn là Ngữ văn)."""
    blob = _fold_text(f"{topic or ''} {subject or ''}")
    return any(k in blob for k in (
        "truyen kieu", "nguyen du", "tac pham", "tho ", "van ban", "truyen ngan",
        "chi tiet", "nhan vat", "the tho", "doc hieu",
    ))


def _is_experiential_subject(subject: str = "") -> bool:
    blob = _fold_text(subject or "")
    return any(k in blob for k in (
        "trai nghiem", "experiential", "hoat dong trai nghiem",
    ))


GDPT2018_LESSON_STAGES = (
    ("Mở đầu (Khởi động)", "Opening (Warm-up)"),
    ("Hình thành kiến thức mới", "Knowledge formation"),
    ("Luyện tập", "Practice"),
    ("Vận dụng", "Application"),
)


def _gdpt2018_lesson_frame(subject: str) -> str:
    stages = "\n".join(
        f"{i}. {vi} / {en}" for i, (vi, en) in enumerate(GDPT2018_LESSON_STAGES, 1)
    )
    extra = ""
    if not _is_experiential_subject(subject):
        extra = (
            "- Môn hiện tại KHÔNG phải Hoạt động trải nghiệm: cấm cấu trúc/khẩu hiệu trải nghiệm, "
            "cấm “tạo sản phẩm nhóm” thay cho bài tập môn học.\n"
        )
    return f"""
TIẾN TRÌNH DẠY HỌC (Chương trình GDPT 2018 — đúng 4 hoạt động, đúng thứ tự):
{stages}
{extra}
"""


def _subject_gdpt_terminology(grade: str, subject: str, topic: str) -> str:
    blob = _fold_text(f"{subject} {topic}")
    profile = _subject_profile_key(subject, topic)
    if profile in ("literature_kieu", "literature") or _is_kieu_topic(subject, topic):
        return f"""
THUẬT NGỮ NGỮ VĂN (GDPT 2018): tác giả, hoàn cảnh sáng tác, thể loại, thể thơ, nhân vật, xung đột,
chủ đề, tư tưởng, nghệ thuật (biện pháp tu từ, hình ảnh), đọc hiểu, phân tích, cảm thụ.
Dạy “{topic}” bằng kiến thức tác phẩm — không dạy kỹ năng sống chung.
"""
    if _is_math_topic(subject, topic):
        return f"""
THUẬT NGỮ TOÁN (GDPT 2018): khái niệm, định lý, tính chất, công thức, mệnh đề, bài toán,
lập luận, tính toán, rút gọn, biện luận, kiểm tra nghiệm. Lớp {grade}, chủ đề “{topic}”.
"""
    if any(k in blob for k in ("tieng anh", "english", "anh van")):
        return f"""
THUẬT NGỮ TIẾNG ANH (GDPT 2018): vocabulary, grammar, pronunciation, reading comprehension,
listening, speaking, writing, communicative functions — gắn chủ đề “{topic}”, lớp {grade}.
"""
    if any(k in blob for k in ("lich su", "history", "su hoc")):
        return f"""
THUẬT NGỮ LỊCH SỬ (GDPT 2018): thời gian, không gian, nhân vật lịch sử, sự kiện, giai đoạn,
nguyên nhân – diễn biến – kết quả – ý nghĩa, nguồn sử liệu, bản đồ tư duy.
"""
    if any(k in blob for k in ("dia ly", "geography", "dia li")):
        return f"""
THUẬT NGỮ ĐỊA LÝ (GDPT 2018): vị trí địa lý, khí hậu, địa hình, dân cư, kinh tế, tài nguyên,
biểu đồ, bản đồ, môi trường, vùng lãnh thổ — chủ đề “{topic}”.
"""
    if any(k in blob for k in ("cong dan", "gdcd", "civic", "kinh te", "phap luat")):
        return f"""
THUẬT NGỮ GDCD / KINH TẾ & PHÁP LUẬT (GDPT 2018): quyền, nghĩa vụ, pháp luật, công dân,
giá trị, chuẩn mực, tình huống thực tiễn, phân tích và lựa chọn hành vi.
"""
    if any(k in blob for k in ("vat ly", "physics")):
        return f"""
THUẬT NGỮ VẬT LÝ (GDPT 2018): hiện tượng, định luật, công thức, đơn vị SI, thí nghiệm,
mô hình, giải bài tập có số liệu — chủ đề “{topic}”, lớp {grade}.
"""
    if any(k in blob for k in ("hoa hoc", "chemistry", "hoa ")):
        return f"""
THUẬT NGỮ HÓA HỌC (GDPT 2018): nguyên tố, hợp chất, phản ứng, cân bằng, mol, nồng độ,
phương trình hóa học, tính toán hóa học — chủ đề “{topic}”.
"""
    if any(k in blob for k in ("sinh hoc", "biology", "sinh ")):
        return f"""
THUẬT NGỮ SINH HỌC (GDPT 2018): tế bào, cơ thể, quá trình sinh học, di truyền, hệ sinh thái,
quan sát, mô hình, thí nghiệm — chủ đề “{topic}”.
"""
    if any(k in blob for k in ("khoa hoc", "science", "tu nhien")):
        return f"""
THUẬT NGỮ KHOA HỌC TỰ NHIÊN (GDPT 2018): hiện tượng, giả thuyết, thí nghiệm, đo lường,
công thức, vận dụng vào tình huống — chủ đề “{topic}”, lớp {grade}.
"""
    if _is_experiential_subject(subject):
        return f"""
MÔN HOẠT ĐỘNG TRẢI NGHIỆM (GDPT 2018): chủ đề trải nghiệm, kỹ năng sống, tham gia thực hành,
phản ánh trải nghiệm — chỉ khi môn là Hoạt động trải nghiệm / Experiential Learning.
"""
    return f"""
THUẬT NGỮ MÔN {subject} (GDPT 2018): dùng đúng khái niệm, định nghĩa, quy trình, bài tập
của môn {subject} về “{topic}” (lớp {grade}). Không lẫn sang môn khác hoặc khẩu hiệu chung.
"""


def _normalize_gdpt_sections(sections: list | None) -> list[dict]:
    """Chuẩn hóa tiến trình 4 hoạt động GDPT 2018."""
    src = [s for s in (sections or []) if isinstance(s, dict)]
    defaults = [
        ("5'", "Kết nối kiến thức, đặt vấn đề bài học.", "Elicit prior knowledge and state the problem."),
        ("15'", "Hình thành kiến thức mới của bài.", "Students acquire the new knowledge of the lesson."),
        ("15'", "Bài tập củng cố kiến thức và kỹ năng.", "Exercises to consolidate knowledge and skills."),
        ("10'", "Vận dụng kiến thức vào tình huống/bài tập.", "Apply knowledge to a situation or task."),
    ]
    out = []
    for i, (vi, en) in enumerate(GDPT2018_LESSON_STAGES):
        base = dict(src[i]) if i < len(src) else {}
        out.append({
            **base,
            "heading_vi": vi,
            "heading_en": en,
            "duration": base.get("duration") or defaults[i][0],
            "content_vi": (base.get("content_vi") or defaults[i][1]).strip(),
            "content_en": (base.get("content_en") or defaults[i][2]).strip(),
            "teacher_activity": base.get("teacher_activity") or "Hướng dẫn, đặt câu hỏi, chốt kiến thức",
            "student_activity": base.get("student_activity") or "Trả lời, làm bài, trình bày",
        })
    return out


# Danh mục môn Teacher Studio — mỗi môn có gợi ý chuẩn GDPT 2018 (dùng cho AI + fallback).
STUDIO_GDPT_SUBJECTS = (
    "Ngữ văn", "Tiếng Anh", "Toán", "Lịch sử", "Địa lý", "Giáo dục công dân",
    "Vật lý", "Hóa học", "Sinh học", "Khoa học tự nhiên", "Công nghệ", "Tin học",
    "Giáo dục thể chất", "Mĩ thuật", "Âm nhạc", "Hoạt động trải nghiệm",
)


def _subject_profile_key(subject: str, topic: str = "") -> str:
    b = _fold_text(subject or "")
    if _is_experiential_subject(subject):
        return "experiential"
    if _is_kieu_topic(subject, topic):
        return "literature_kieu"
    if _is_literature_subject(subject):
        return "literature"
    if _is_math_topic(subject, topic) or "toan" in b:
        return "math"
    if any(k in b for k in ("tieng anh", "english", "anh van")):
        return "english"
    if "lich su" in b or "history" in b:
        return "history"
    if "dia ly" in b or "geography" in b:
        return "geography"
    if any(k in b for k in ("cong dan", "gdcd", "civic")):
        return "civic"
    if "vat ly" in b or "physics" in b:
        return "physics"
    if "hoa hoc" in b or "chemistry" in b:
        return "chemistry"
    if "sinh hoc" in b or "biology" in b:
        return "biology"
    if "khoa hoc tu nhien" in b or "natural science" in b:
        return "natural_science"
    if "cong nghe" in b or "technology" in b:
        return "technology"
    if "tin hoc" in b or "informatics" in b or "computer" in b:
        return "informatics"
    if any(k in b for k in ("the duc", "the chat", "pe ", "physical")):
        return "pe"
    if "mi thuat" in b or "art" in b:
        return "art"
    if "am nhac" in b or "music" in b:
        return "music"
    return "general"


def _gdpt_stage_contents(profile: str, grade: str, subject: str, topic: str) -> list[dict]:
    """Nội dung 4 hoạt động theo đúng tính chất môn (fallback + kiểm tra)."""
    t, g, s = topic, grade, subject
    packs = {
        "literature_kieu": [
            (f"Hỏi kiến thức nền về “{t}”: tác giả, thể loại.", f"Ask prior knowledge about “{t}”: author and genre."),
            (f"Giảng kiến thức tác phẩm “{t}”: tác giả, thể thơ, nhân vật, chủ đề.", f"Teach work knowledge: author, form, characters, themes."),
            (f"Đọc hiểu / phiếu nhân vật – sự kiện sát “{t}”.", f"Close reading worksheet on “{t}”."),
            (f"Viết đoạn phân tích chủ đề hoặc nhân vật trong “{t}”.", f"Write a short analysis of “{t}”."),
        ],
        "literature": [
            (f"Kết nối bài cũ; hỏi HS biết gì về “{t}”.", f"Link to prior lessons; elicit knowledge of “{t}”."),
            (f"Hình thành kiến thức: tác giả, bối cảnh, nội dung, nghệ thuật của “{t}”.", f"Teach author, context, content and style of “{t}”."),
            (f"Luyện đọc hiểu / phân tích đoạn trích “{t}”.", f"Practice comprehension and analysis of “{t}”."),
            (f"Vận dụng: liên hệ ý nghĩa “{t}” với đời sống / viết 5–7 câu.", f"Apply the meaning of “{t}” in a short writing task."),
        ],
        "math": [
            (f"Ôn khái niệm liên quan; nêu bài toán mở đầu về “{t}”.", f"Review related ideas; pose an opening problem on “{t}”."),
            (f"Giảng định nghĩa, công thức, ví dụ minh họa “{t}” ({g}).", f"Teach definition, formula and worked example of “{t}”."),
            (f"Luyện tập: 3–5 bài tính đúng mức {g}.", f"Practice: 3–5 calculation exercises at {g} level."),
            (f"Vận dụng: bài toán thực tế / bài nâng cao ngắn về “{t}”.", f"Apply “{t}” to a contextual or extended problem."),
        ],
        "english": [
            (f"Warm-up: từ vựng / cấu trúc liên quan “{t}”.", f"Warm-up: vocabulary or grammar linked to “{t}”."),
            (f"Dạy ngôn ngữ mục tiêu của bài “{t}” (lexis / grammar / function).", f"Teach the target language of “{t}”."),
            (f"Controlled practice: bài tập nói/viết ngắn về “{t}”.", f"Controlled speaking/writing practice on “{t}”."),
            (f"Freer practice: tình huống giao tiếp sử dụng “{t}”.", f"Communicative task using “{t}”."),
        ],
        "history": [
            (f"Đặt vấn đề lịch sử về “{t}”; xem tranh / bản đồ.", f"Pose the historical question on “{t}”; use a visual source."),
            (f"Hình thành: thời gian, không gian, diễn biến, ý nghĩa “{t}”.", f"Teach time, place, course and significance of “{t}”."),
            (f"Luyện tập: trắc nghiệm / sơ đồ tư duy sự kiện “{t}”.", f"Practice: quiz or mind map of “{t}”."),
            (f"Vận dụng: tại sao “{t}” quan trọng với Việt Nam / thế giới?", f"Apply: why “{t}” matters today."),
        ],
        "geography": [
            (f"Khởi động: vị trí / hiện tượng liên quan “{t}”.", f"Warm-up: location or phenomenon of “{t}”."),
            (f"Giảng khái niệm, đặc điểm, biểu đồ/bản đồ “{t}”.", f"Teach concepts, features and maps of “{t}”."),
            (f"Luyện đọc bản đồ / biểu đồ / số liệu “{t}”.", f"Practice reading maps or data on “{t}”."),
            (f"Vận dụng: tình huống địa lý thực tế về “{t}”.", f"Apply “{t}” to a real geographic situation."),
        ],
        "civic": [
            (f"Khởi động: tình huống đời sống liên quan “{t}”.", f"Warm-up: real-life situation about “{t}”."),
            (f"Giảng khái niệm, quy định, giá trị trong “{t}”.", f"Teach concepts, rules and values in “{t}”."),
            (f"Thảo luận / xử lý tình huống “{t}”.", f"Discuss or resolve a case study on “{t}”."),
            (f"Vận dụng: lựa chọn hành vi đúng theo “{t}”.", f"Apply “{t}” to choose responsible behaviour."),
        ],
        "physics": [
            (f"Quan sát hiện tượng mở đầu “{t}”.", f"Observe the opening phenomenon of “{t}”."),
            (f"Giảng định luật, công thức, đơn vị SI của “{t}”.", f"Teach law, formula and SI units for “{t}”."),
            (f"Luyện giải bài tập có số liệu “{t}”.", f"Practice numerical problems on “{t}”."),
            (f"Vận dụng: thí nghiệm / bài toán thực tế “{t}”.", f"Apply “{t}” in an experiment or real problem."),
        ],
        "chemistry": [
            (f"Khởi động: hiện tượng hóa học liên quan “{t}”.", f"Warm-up: chemical phenomenon linked to “{t}”."),
            (f"Giảng khái niệm, phương trình, quy tắc “{t}”.", f"Teach concepts, equations and rules of “{t}”."),
            (f"Luyện cân bằng / tính toán mol “{t}”.", f"Practice balancing and mole calculations for “{t}”."),
            (f"Vận dụng: bài tập tổng hợp “{t}”.", f"Apply “{t}” in a synthesis exercise."),
        ],
        "biology": [
            (f"Khởi động: quan sát mẫu / tranh “{t}”.", f"Warm-up: observe a specimen or diagram of “{t}”."),
            (f"Giảng quá trình, cấu trúc, chức năng “{t}”.", f"Teach process, structure and function of “{t}”."),
            (f"Luyện sơ đồ / bài tập trắc nghiệm “{t}”.", f"Practice diagrams or MCQ on “{t}”."),
            (f"Vận dụng: bảo vệ môi trường / sức khỏe liên quan “{t}”.", f"Apply “{t}” to health or environment."),
        ],
        "natural_science": [
            (f"Khởi động: câu hỏi hiện tượng “{t}”.", f"Warm-up question on phenomenon “{t}”."),
            (f"Giảng kiến thức cốt lõi và thí nghiệm “{t}”.", f"Teach core knowledge and experiment for “{t}”."),
            (f"Luyện tập tính toán / quan sát “{t}”.", f"Practice calculation or observation on “{t}”."),
            (f"Vận dụng STEM ngắn về “{t}”.", f"Short STEM application of “{t}”."),
        ],
        "technology": [
            (f"Khởi động: sản phẩm / quy trình liên quan “{t}”.", f"Warm-up: product or process linked to “{t}”."),
            (f"Giảng nguyên lý, quy trình, an toàn “{t}”.", f"Teach principles, procedure and safety for “{t}”."),
            (f"Thực hành mô phỏng / phiếu thao tác “{t}”.", f"Simulated practice worksheet on “{t}”."),
            (f"Vận dụng: thiết kế / cải tiến sản phẩm “{t}”.", f"Apply “{t}” in a small design task."),
        ],
        "informatics": [
            (f"Khởi động: bài toán / ứng dụng “{t}”.", f"Warm-up problem or app related to “{t}”."),
            (f"Giảng khái niệm, thuật toán, cú pháp “{t}”.", f"Teach concepts, algorithm or syntax of “{t}”."),
            (f"Luyện trên máy / pseudocode “{t}”.", f"Practice on computer or pseudocode for “{t}”."),
            (f"Vận dụng: mini-project “{t}”.", f"Apply “{t}” in a mini project."),
        ],
        "pe": [
            (f"Khởi động: chạy nhẹ, xoay khớp; nêu mục tiêu “{t}”.", f"Light run and joint rotation; state goals of “{t}”."),
            (f"Hướng dẫn kỹ thuật động tác “{t}”.", f"Demonstrate techniques of “{t}”."),
            (f"Luyện tập theo nhóm / trạm “{t}”.", f"Station practice of “{t}”."),
            (f"Vận dụng: trò chơi vận động / thi đua ngắn “{t}”.", f"Apply “{t}” in a short game or relay."),
        ],
        "art": [
            (f"Quan sát tác phẩm mẫu liên quan “{t}”.", f"Observe sample artworks about “{t}”."),
            (f"Giảng yếu tố mỹ thuật, quy trình tạo hình “{t}”.", f"Teach art elements and process for “{t}”."),
            (f"Thực hành phác / tô màu “{t}”.", f"Practice sketching or colouring “{t}”."),
            (f"Vận dụng: hoàn thiện sản phẩm & trưng bày “{t}”.", f"Finish and present artwork on “{t}”."),
        ],
        "music": [
            (f"Nghe mẫu / hát khởi động liên quan “{t}”.", f"Listen or sing a warm-up linked to “{t}”."),
            (f"Dạy nốt, nhịp, kỹ thuật biểu diễn “{t}”.", f"Teach notes, rhythm and performance skills for “{t}”."),
            (f"Luyện tập cá nhân / nhóm “{t}”.", f"Rehearse “{t}” in pairs or groups."),
            (f"Vận dụng: trình diễn ngắn bài “{t}”.", f"Perform a short piece on “{t}”."),
        ],
        "experiential": [
            (f"Khởi động: chia sẻ trải nghiệm liên quan chủ đề “{t}”.", f"Share prior experiences about “{t}”."),
            (f"Tìm hiểu mục tiêu, kỹ năng, quy trình trải nghiệm “{t}”.", f"Learn goals, skills and steps for “{t}”."),
            (f"Thực hành hoạt động trải nghiệm “{t}”.", f"Carry out the experiential activity “{t}”."),
            (f"Phản ánh, đánh giá và rút kinh nghiệm “{t}”.", f"Reflect and evaluate “{t}”."),
        ],
    }
    rows = packs.get(profile)
    if not rows:
        rows = [
            (f"Kết nối kiến thức đã học về “{t}” (môn {s}).", f"Link prior knowledge of “{t}” in {s}."),
            (f"Giảng kiến thức cốt lõi “{t}” theo chương trình {s}.", f"Teach core knowledge of “{t}” in {s}."),
            (f"Luyện tập bài tập sát “{t}”.", f"Practice exercises on “{t}”."),
            (f"Vận dụng “{t}” vào tình huống học tập / thực tiễn.", f"Apply “{t}” to a task or situation."),
        ]
    sections = []
    for i, (vi, en) in enumerate(rows):
        sections.append({
            "heading_vi": GDPT2018_LESSON_STAGES[i][0],
            "heading_en": GDPT2018_LESSON_STAGES[i][1],
            "duration": ("5'", "15'", "15'", "10'")[i],
            "content_vi": vi,
            "content_en": en,
            "teacher_activity": "Hướng dẫn, đặt câu hỏi, chốt kiến thức môn học",
            "student_activity": "Trả lời, làm bài, trình bày theo yêu cầu bài",
        })
    return sections


def _subject_gdpt_materials(profile: str, subject: str) -> list[str]:
    base = {
        "literature_kieu": ["SGK Ngữ văn", "Phiếu nhân vật", "Bảng lục bát", "Máy chiếu"],
        "literature": ["SGK Ngữ văn", "Phiếu đọc hiểu", "Bảng phụ", "Máy chiếu"],
        "math": ["SGK Toán", "Máy tính cầm tay", "Phiếu bài tập", "Bảng"],
        "english": ["SGK Tiếng Anh", "Audio / video", "Phiếu bài tập", "Flashcards"],
        "history": ["SGK Lịch sử", "Bản đồ / tranh ảnh", "Phiếu học tập", "Timeline"],
        "geography": ["SGK Địa lý", "Bản đồ", "Biểu đồ", "Phiếu số liệu"],
        "civic": ["SGK GDCD", "Tình huống pháp luật", "Phiếu thảo luận", "Máy chiếu"],
        "physics": ["SGK Vật lý", "Dụng cụ thí nghiệm", "Máy tính", "Phiếu bài tập"],
        "chemistry": ["SGK Hóa học", "Hóa chất / mô hình", "Phiếu thí nghiệm", "Bảng PTHH"],
        "biology": ["SGK Sinh học", "Mẫu vật / tranh", "Kính hiển vi / mô hình", "Phiếu quan sát"],
        "natural_science": ["SGK KHTN", "Bộ thí nghiệm", "Phiếu ghi chép", "Máy chiếu"],
        "technology": ["SGK Công nghệ", "Dụng cụ / vật liệu", "Sơ đồ quy trình", "Phiếu an toàn"],
        "informatics": ["SGK Tin học", "Máy tính", "Phần mềm lập trình", "Phiếu thuật toán"],
        "pe": ["Còi", "Dụng cụ thể thao", "Sân / phòng gym", "Phiếu theo dõi"],
        "art": ["Giấy / màu", "Mẫu tác phẩm", "Dụng cụ vẽ", "Máy chiếu"],
        "music": ["Nhạc cụ / app nhạc", "Bảng nốt", "Loa", "Phiếu bài hát"],
        "experiential": ["Phiếu trải nghiệm", "Vật liệu thực hành", "Nhật ký", "Máy quay / ảnh"],
    }
    return base.get(profile) or [f"SGK {subject}", "Phiếu bài tập", "Bảng", "Máy chiếu"]


def _enforce_gdpt_lesson_quality(out: dict, fb: dict, grade: str, subject: str, topic: str) -> dict:
    """Sau AI: luôn đúng 4 hoạt động, đúng môn, không slogan lạ."""
    profile = _subject_profile_key(subject, topic)
    out["sections"] = _normalize_gdpt_sections(out.get("sections"))
    blob = " ".join([
        str(out.get("title_vi") or ""),
        str(out.get("core_content_vi") or ""),
        str(out.get("core_content_en") or ""),
        " ".join(str(x) for x in (out.get("objectives_vi") or [])),
        " ".join(str(s.get("content_vi") or "") for s in out.get("sections") or []),
    ])
    if topic and _fold_text(topic) not in _fold_text(blob):
        out["core_content_vi"] = fb.get("core_content_vi") or out.get("core_content_vi")
        out["core_content_en"] = fb.get("core_content_en") or out.get("core_content_en")
    if not _is_experiential_subject(subject) and _is_generic_teaching_text(blob):
        out = _scrub_generic_lesson(out, fb)
    if len(out.get("sections") or []) != 4:
        out["sections"] = _normalize_gdpt_sections(fb.get("sections"))
    if not out.get("materials"):
        out["materials"] = _subject_gdpt_materials(profile, subject)
    out["subject"] = subject
    out["topic"] = topic
    out["grade"] = grade
    return out


def _quiz_subject_rules(grade: str, subject: str, topic: str) -> str:
    if _is_math_topic(subject, topic):
        return f"""
CONTENT RULES — MATHEMATICS ({grade} · {subject} · {topic}):
- At least 70% of items REQUIRE actual calculation (compute, differentiate, integrate, evaluate, solve).
- Use concrete functions and numbers at {grade} level, exactly about “{topic}”. Example style:
  “Let f(x) = x^3 - 3x^2 + 2. Find f'(x).” with options like 3x^2-6x, 3x^2-3x, x^2-6x, 3x-6.
- Distractors = common student mistakes (forgot chain rule, wrong sign, dropped coefficient).
- fill_blank: the computed result (e.g. 2x, 6, 1/2).
- essay: “Show the steps to compute …” with a marking key of the main steps + final answer.
- At most 1–2 conceptual items (definition/property). NEVER write generic “what is the meaning of {topic}?”.
- Write formulas in plain text: f(x)=..., f'(x)=..., ∫, ^ for powers.
- FORBIDDEN (reject these): “Khái niệm nào liên quan đến {topic}?”, “Which concept relates to {topic}?”,
  options “Nội dung đúng về {topic} / Khái niệm không liên quan / Thông tin sai / Không có đáp án”.
- Each MCQ option must itself be a formula or a number, not a comment about the topic.
"""
    lit_profile = _subject_profile_key(subject, topic)
    if lit_profile in ("literature", "literature_kieu"):
        return f"""
CONTENT RULES — LITERATURE ({grade} · {subject} · {topic}):
- Ask about the AUTHOR, CHARACTERS, PLOT EVENTS, VERSE FORM and THEMES of “{topic}”.
- For Truyện Kiều: Nguyễn Du, Thúy Kiều, Thúy Vân, Kim Trọng, Hoạn Thư, lục bát, tài mệnh tương đố, hiếu.
- MCQ options are names, forms or facts — never classroom behaviour.
- true_false: mix True and False; never two identical True statements.
- fill_blank: missing name/form (Nguyễn Du, Thúy Kiều, lục bát); options [].
- essay: 6–8 English sentences + sample_answer; options [].
- FORBIDDEN: “what should students do in the lesson”, “join the class task”, “skip the lesson”,
  “follow the ____ of the teacher”, “write about how students take part”.
"""
    blob = _subject_blob(subject, topic)
    if any(k in blob for k in ("khoa học", "khoa hoc", "science", "vật lý", "vat ly", "hóa", "hoa hoc", "sinh", "physics", "chemistry", "biology")):
        return f"""
CONTENT RULES — SCIENCE ({grade} · {topic}):
- Items must use formulas, units, numbers or experimental situations of THIS topic.
- Include calculation / apply-the-formula questions, not only definitions.
- Distractors are plausible wrong units or wrong substitutions.
"""
    return f"""
CONTENT RULES — THIS TOPIC ONLY ({grade} · {subject} · {topic}):
- Every item must be unusable if the topic is changed (names, facts, procedures of “{topic}”).
- Ban generic prompts like “why is this useful” or “what is experiential learning” unless the topic is exactly that.
- Use Vietnam school situations tied to {topic}.
- FORBIDDEN stems/options: “which concept relates to”, “correct content about”, “unrelated concept”,
  “incorrect information”, “none of the above”, and the Vietnamese equivalents
  (“khái niệm nào liên quan”, “nội dung đúng về”, “không liên quan”, “thông tin sai”, “không có đáp án”).
"""


_GENERIC_Q_RE = re.compile(
    r"(khái niệm nào|khai niem nao"
    r"|which (idea|concept|sentence) best"
    r"|nội dung đúng về|noi dung dung ve|a correct idea about|correct content about"
    r"|khái niệm không liên quan|không liên quan|khong lien quan|unrelated (concept|idea)"
    r"|thông tin sai|thong tin sai|incorrect information"
    r"|không có đáp án|khong co dap an|none of the above"
    r"|experiential activit|give one accurate fact"
    r"|what should students do in the lesson"
    r"|join the class task about"
    r"|practise this lesson by doing the tasks"
    r"|follow the _{2,} of the teacher"
    r"|how students take part in"
    r"|write 6.?8 sentences about how students)",
    re.I,
)
_GENERIC_OPT_RE = re.compile(
    r"(nội dung đúng|noi dung dung|không liên quan|khong lien quan"
    r"|thông tin sai|thong tin sai|không có đáp án|khong co dap an"
    r"|unrelated (concept|idea)|incorrect information|none of the above"
    r"|a correct idea about|correct content about|experiential activity about"
    r"|join the class task|skip the lesson and stay|leave school before"
    r"|copy a random answer|stay on the phone)",
    re.I,
)


def _is_generic_quiz_item(q: dict) -> bool:
    if not isinstance(q, dict):
        return True
    text = str(q.get("question_text") or q.get("question") or "")
    opts = [str(o) for o in (q.get("options") or [])]
    blob = " ".join([text] + opts)
    if _GENERIC_Q_RE.search(blob):
        return True
    if sum(1 for o in opts if _GENERIC_OPT_RE.search(o)) >= 2:
        return True
    return False


def _fold_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _scrub_quiz_questions(
    questions: list,
    grade: str,
    subject: str,
    topic: str,
    need: int,
    quiz_types: list | None = None,
) -> list:
    kept = []
    seen = set()
    for q in questions or []:
        if not isinstance(q, dict) or _is_generic_quiz_item(q):
            continue
        key = str(q.get("question_text") or q.get("question") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(q)
        if len(kept) >= need:
            return kept[:need]
    extra = (
        _fallback_math_questions(topic, need, quiz_types or ["multiple_choice", "true_false", "fill_blank", "essay"])
        if _is_math_topic(subject, topic)
        else _fallback_topic_questions(grade, subject, topic, need, quiz_types)
    )
    for q in extra:
        key = str(q.get("question_text") or "").strip().lower()
        if not key or key in seen:
            continue
        kept.append(q)
        seen.add(key)
        if len(kept) >= need:
            break
    return kept[:need]


def _teacher_brief(
    *,
    grade: str,
    subject: str,
    topic: str,
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    theme_color: str = "",
    theme_accent: str = "",
    extra_lines: str = "",
) -> str:
    return (
        "THÔNG TIN GIÁO VIÊN (bắt buộc bám sát từng dòng):\n"
        f"- Khối/Lớp: {grade}\n"
        f"- Môn học: {subject}\n"
        f"- Chủ đề: {topic}\n"
        f"- Mô tả: {description.strip() or '(không có mô tả — khai thác sâu đúng chủ đề trên)'}\n"
        f"- Ngôn ngữ soạn: {language}\n"
        f"- Yêu cầu thêm: {extra_requirements.strip() or '(không)'}\n"
        f"- Màu chủ đạo / nhấn: {theme_color or '-'} / {theme_accent or '-'}\n"
        + (f"{extra_lines.strip()}\n" if extra_lines else "")
    )


def _teaching_content_rules(grade: str, subject: str, topic: str) -> str:
    """Bắt buộc Word/slide dạy đúng môn + đúng Chủ đề, phục vụ giảng dạy."""
    extra = ""
    if _subject_profile_key(subject, topic) in ("literature", "literature_kieu"):
        extra = f"""
MÔN NGỮ VĂN — dạy tác phẩm “{topic}”:
- Kiến thức bắt buộc: tác giả, hoàn cảnh sáng tác, thể loại/thể thơ, nhân vật, sự kiện, chủ đề/tư tưởng.
- Truyện Kiều: Nguyễn Du, Đoạn trường tân thanh, lục bát; Thúy Kiều, Thúy Vân, Kim Trọng, Hoạn Thư; tài mệnh tương đố, chữ hiếu.
- Hoạt động lớp: đọc hiểu, bảng nhân vật, phân tích câu thơ, thảo luận chủ đề — không phải trò chơi chung.
"""
    elif _is_math_topic(subject, topic):
        extra = f"""
MÔN TOÁN — dạy đúng kiến thức “{topic}”:
- Định nghĩa, công thức, ví dụ tính toán, bài luyện theo lớp {grade}.
- Cấm chỉ nói “thảo luận nhóm / tạo sản phẩm” mà không có bài toán thật.
"""
    elif any(k in _subject_blob(subject, topic) for k in (
        "khoa học", "khoa hoc", "science", "vật lý", "vat ly", "hóa", "hoa hoc",
        "sinh", "physics", "chemistry", "biology",
    )):
        extra = f"""
MÔN KHOA HỌC — dạy hiện tượng/công thức/thí nghiệm của “{topic}”.
"""
    ban = (
        "CẤM (trừ môn Hoạt động trải nghiệm): khẩu hiệu trải nghiệm chung, "
        "“hands-on exploration”, “create a mini product”, “I learned / I will apply”."
        if not _is_experiential_subject(subject)
        else "Môn Hoạt động trải nghiệm: bám chủ đề trải nghiệm và kỹ năng sống của bài."
    )
    return f"""
HỌC LIỆU GIẢNG DẠY — CHƯƠNG TRÌNH GDPT 2018 (bắt buộc):
- Đúng lớp {grade}, môn {subject}, CHỦ ĐỀ “{topic}”.
- Mỗi đoạn/bullet phải là kiến thức hoặc kỹ năng môn học về “{topic}”, đúng thuật ngữ môn.
- Nếu đổi chủ đề thì nội dung phải SAI (tên, sự kiện, công thức, nhân vật của đúng chủ đề này).
- Tổ chức lớp chỉ là CÁCH dạy kiến thức đó, không thay cho nội dung môn học.
{ban}
{_gdpt2018_lesson_frame(subject)}
{_subject_gdpt_terminology(grade, subject, topic)}
{extra}
"""


def _is_generic_teaching_text(text: str) -> bool:
    blob = _fold_text(text or "")
    return any(m in blob for m in (
        "hands-on", "mini product", "experiential learning", "create a mini",
        "i learned", "i will apply", "i still wonder",
        "trai nghiem chinh", "hoat dong trai nghiem", "tao san pham nho",
        "leader recorder", "timekeeper",
    ))


def _scrub_generic_lesson(out: dict, fb: dict) -> dict:
    if not isinstance(out, dict) or not isinstance(fb, dict):
        return out
    title_blob = f"{out.get('title_vi') or ''} {out.get('title_en') or ''}"
    if _is_generic_teaching_text(title_blob):
        out["title_vi"] = fb.get("title_vi") or out.get("title_vi")
        out["title_en"] = fb.get("title_en") or out.get("title_en")
    core_blob = f"{out.get('core_content_vi') or ''} {out.get('core_content_en') or ''}"
    if _is_generic_teaching_text(core_blob):
        if fb.get("core_content_vi"):
            out["core_content_vi"] = fb["core_content_vi"]
        if fb.get("core_content_en"):
            out["core_content_en"] = fb["core_content_en"]
    fb_secs = [s for s in (fb.get("sections") or []) if isinstance(s, dict)]
    secs = out.get("sections") or []
    for i, sec in enumerate(secs):
        if not isinstance(sec, dict):
            continue
        blob = " ".join(str(sec.get(k) or "") for k in (
            "heading_vi", "heading_en", "content_vi", "content_en",
            "teacher_activity", "student_activity",
        ))
        if _is_generic_teaching_text(blob) and i < len(fb_secs):
            secs[i] = fb_secs[i]
    out["sections"] = secs
    voc = [v for v in (out.get("vocabulary") or []) if isinstance(v, dict)]
    if voc and any(_is_generic_teaching_text(f"{v.get('term') or ''} {v.get('meaning_vi') or ''}") for v in voc):
        out["vocabulary"] = fb.get("vocabulary") or voc
    return out


def _slide_text_blob(slide: dict) -> str:
    bits = [slide.get("title"), slide.get("subtitle")]
    bits.extend(slide.get("bullets") or [])
    bits.extend(slide.get("left_bullets") or [])
    bits.extend(slide.get("right_bullets") or [])
    return " ".join(str(x or "") for x in bits)


def _scrub_generic_slides(slides: list, fb_slides: list) -> list:
    items = [s for s in (slides or []) if isinstance(s, dict)]
    pool = [
        dict(s) for s in (fb_slides or [])
        if isinstance(s, dict) and str(s.get("layout") or "") not in ("title", "closing")
    ]
    used = set()
    out = []
    for s in items:
        layout = str(s.get("layout") or "")
        if layout in ("title", "closing") or not _is_generic_teaching_text(_slide_text_blob(s)):
            out.append(s)
            continue
        replacement = None
        for j, cand in enumerate(pool):
            if j in used:
                continue
            replacement = dict(cand)
            used.add(j)
            break
        out.append(replacement or s)
    return out


def _strip_json(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _repair_json(text: str) -> str:
    """Sửa lỗi JSON thường gặp / bị cắt giữa chừng."""
    s = text.strip()
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Đóng ngoặc còn thiếu nếu bị truncate
    open_curly = s.count("{") - s.count("}")
    open_square = s.count("[") - s.count("]")
    if open_square > 0 or open_curly > 0:
        # cắt về sau dấu đóng hợp lệ gần nhất trong chuỗi chưa hoàn chỉnh
        # rồi bổ sung ngoặc
        s = s.rstrip().rstrip(",")
        # nếu đang giữa string, đóng string
        if s.count('"') % 2 == 1:
            s += '"'
        s = re.sub(r",\s*$", "", s)
        s += "]" * max(0, open_square)
        s += "}" * max(0, open_curly)
        s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _parse_json(text: str) -> dict | None:
    raw = _strip_json(text)
    for candidate in (raw, _repair_json(raw)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    current_app.logger.warning("Studio AI JSON parse failed")
    return None


def _ask_studio_json(
    prompt: str,
    system: str,
    *,
    max_tokens: int = 4096,
    timeout: int = 40,
    compact_prompt: str | None = None,
) -> tuple[dict | None, str | None]:
    """Gọi AI lấy JSON. Nếu lỗi/rỗng thì gọi lại bản gọn hơn."""
    data = None
    source = None
    try:
        text, source = _call_ai(
            prompt, system, max_tokens=max_tokens, json_mode=True, timeout=timeout,
        )
        data = _parse_json(text) if text else None
        if data:
            return data, source or "gemini"
    except Exception:
        current_app.logger.exception("studio AI call failed")
    retry = compact_prompt or (
        "Return COMPLETE valid JSON only. Keep every text field short (2-5 sentences). Do not truncate.\n\n"
        + (prompt if len(prompt) < 6000 else prompt[-5500:])
    )
    try:
        text, source = _call_ai(
            retry, system,
            max_tokens=min(int(max_tokens), 3072),
            json_mode=True,
            timeout=min(int(timeout), 35),
        )
        data = _parse_json(text) if text else None
        if data:
            return data, source or "gemini"
    except Exception:
        current_app.logger.exception("studio AI compact retry failed")
    return None, None


def _merge_ai_json(base: dict | None, extra: dict | None) -> dict:
    if not extra:
        return dict(base or {})
    if not base:
        return dict(extra)
    out = dict(base)
    for key, val in extra.items():
        if key in ("sections", "slides", "questions", "vocabulary", "materials", "homework",
                   "objectives_vi", "objectives_en", "knowledge_vi", "knowledge_en"):
            cur = list(out.get(key) or []) if isinstance(out.get(key), list) else []
            add = val if isinstance(val, list) else []
            if key == "sections":
                ai_list = [s for s in add if isinstance(s, dict)]
                fb_list = [s for s in cur if isinstance(s, dict)]
                if len(ai_list) >= 4:
                    out[key] = ai_list
                else:
                    seen = {
                        (str(s.get("heading_vi") or ""), str(s.get("heading_en") or ""))
                        for s in ai_list
                    }
                    mixed = list(ai_list)
                    for item in fb_list:
                        mark = (str(item.get("heading_vi") or ""), str(item.get("heading_en") or ""))
                        if mark not in seen:
                            mixed.append(item)
                            seen.add(mark)
                    out[key] = mixed
            elif key == "vocabulary":
                seen = {
                    str(x.get("term") or x.get("word") or "").strip().lower()
                    for x in cur if isinstance(x, dict)
                }
                for item in add:
                    if not isinstance(item, dict):
                        continue
                    term = str(item.get("term") or item.get("word") or "").strip().lower()
                    if term and term not in seen:
                        cur.append(item)
                        seen.add(term)
                out[key] = cur
            elif key in ("questions", "slides"):
                out[key] = cur + add if cur else add
            else:
                out[key] = cur if cur else add
        elif val not in (None, "", [], {}):
            out[key] = val
        elif key not in out:
            out[key] = val
    return out


def _brief_requirements(description: str = "", extra: str = "", quiz_req: str = "") -> str:
    parts = []
    if description:
        parts.append(f"MÔ TẢ BẮT BUỘC bám sát: {description}")
    if extra:
        parts.append(f"YÊU CẦU THÊM (phải thể hiện trong nội dung): {extra}")
    if quiz_req:
        parts.append(f"YÊU CẦU ĐỀ: {quiz_req}")
    return "\n".join(parts) if parts else "Không có yêu cầu thêm."


def _fallback_lesson(grade: str, subject: str, topic: str, language: str, description: str = "") -> dict:
    if _is_kieu_topic(subject, topic):
        return {
            "title_vi": f"Giáo án Ngữ văn: {topic}",
            "title_en": f"Literature lesson: {topic}",
            "grade": grade,
            "subject": subject,
            "topic": topic,
            "description": description or f"Dạy kiến thức tác phẩm {topic} cho học sinh {grade}.",
            "duration_minutes": 45,
            "materials": ["SGK Ngữ văn", "Phiếu nhân vật", "Bảng lục bát", "Máy chiếu"],
            "objectives_vi": [
                "Nêu được tác giả Nguyễn Du và thể loại lục bát của Truyện Kiều",
                "Nhận diện nhân vật Thúy Kiều, Thúy Vân, Kim Trọng, Hoạn Thư",
                "Giải thích tài mệnh tương đố và chữ hiếu qua một sự kiện",
            ],
            "objectives_en": [
                "Name Nguyễn Du and the lục bát form of Truyện Kiều",
                "Identify Kiều, Vân, Kim Trọng and Hoạn Thư",
                "Explain tài mệnh tương đố and filial piety with one plot event",
            ],
            "core_content_vi": (
                "Truyện Kiều (Đoạn trường tân thanh) của Nguyễn Du kể số phận Vương Thúy Kiều. "
                "Tác phẩm viết bằng lục bát. Kiều phải bán mình cứu cha, xa Kim Trọng, chịu oan ức với Hoạn Thư. "
                "Chủ đề lớn: tài mệnh tương đố và chữ hiếu."
            ),
            "core_content_en": (
                "Truyện Kiều by Nguyễn Du follows Vương Thúy Kiều in lục bát verse. "
                "She sells herself to save her father, is parted from Kim Trọng, and suffers under Hoạn Thư. "
                "Key ideas: talent versus fate, and filial piety."
            ),
            "sections": [
                {
                    "heading_vi": "Mở đầu (Khởi động)",
                    "heading_en": "Opening (Warm-up)",
                    "duration": "5'",
                    "content_vi": "Hỏi: Ai viết Truyện Kiều? Nhân vật chính là ai? Ghi nhanh Nguyễn Du – Thúy Kiều.",
                    "content_en": "Ask who wrote Truyện Kiều and who the heroine is. Board: Nguyễn Du – Thúy Kiều.",
                    "teacher_activity": "Hỏi tác giả, nhân vật",
                    "student_activity": "Trả lời ngắn đúng kiến thức tác phẩm",
                },
                {
                    "heading_vi": "Hình thành kiến thức mới",
                    "heading_en": "Knowledge formation",
                    "duration": "12'",
                    "content_vi": "Giảng: Nguyễn Du, lục bát, Kiều–Vân–Kim Trọng–Hoạn Thư, tình tiết bán mình cứu cha.",
                    "content_en": "Teach author, lục bát, the four key characters, and the self-sale to save the father.",
                    "teacher_activity": "Giảng tác giả, thể thơ, nhân vật",
                    "student_activity": "Ghi bảng nhân vật và sự kiện",
                },
                {
                    "heading_vi": "Luyện tập",
                    "heading_en": "Practice",
                    "duration": "18'",
                    "content_vi": "Nhóm điền bảng: nhân vật / vai trò / sự kiện. Nêu một dẫn chứng tài mệnh tương đố.",
                    "content_en": "Groups fill a character–role–event table and give one example of tài mệnh tương đố.",
                    "teacher_activity": "Phát phiếu nhân vật, chấm nhanh",
                    "student_activity": "Điền bảng, nêu dẫn chứng từ truyện",
                },
                {
                    "heading_vi": "Vận dụng",
                    "heading_en": "Application",
                    "duration": "10'",
                    "content_vi": "Viết 4–5 câu: vì sao Kiều phải bán mình? Chữ hiếu thể hiện thế nào? Liên hệ ý nghĩa tác phẩm.",
                    "content_en": "Write 4–5 sentences on filial piety and tài mệnh tương đố with plot evidence.",
                    "teacher_activity": "Thu phiếu, nhận xét kiến thức",
                    "student_activity": "Trả lời bằng sự kiện trong truyện",
                },
            ],
            "vocabulary": [
                {"term": "lục bát", "meaning_vi": "thể thơ 6–8", "example": "Truyện Kiều is written in lục bát."},
                {"term": "filial piety", "meaning_vi": "chữ hiếu", "example": "Kiều shows filial piety when she saves her father."},
                {"term": "fate", "meaning_vi": "số mệnh", "example": "Talent and fate conflict in Kiều’s life."},
                {"term": "heroine", "meaning_vi": "nữ chính", "example": "Thúy Kiều is the heroine."},
                {"term": "verse novel", "meaning_vi": "truyện thơ", "example": "Truyện Kiều is a verse novel by Nguyễn Du."},
            ],
            "assessment": {
                "methods": ["Character table", "Oral check", "Short written answer"],
                "criteria": ["Correct author/form", "Correct characters", "One plot fact"],
            },
            "homework": [
                "Học thuộc: tác giả, thể thơ, 4 nhân vật chính.",
                "Viết 6 câu tiếng Anh về chữ hiếu của Kiều.",
            ],
            "source": "template",
            "language": language,
        }
    profile = _subject_profile_key(subject, topic)
    sections = _gdpt_stage_contents(profile, grade, subject, topic)
    return {
        "title_vi": f"Giáo án {subject}: {topic}",
        "title_en": f"{subject} lesson: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "description": description or (
            f"Giáo án GDPT 2018 — {grade}, môn {subject}, chủ đề “{topic}”."
        ),
        "duration_minutes": 45,
        "materials": _subject_gdpt_materials(profile, subject),
        "objectives_vi": [
            f"Nêu được kiến thức cốt lõi của “{topic}” (môn {subject}, {grade})",
            f"Thực hiện bài luyện tập đúng thuật ngữ môn {subject}",
            f"Vận dụng kiến thức “{topic}” vào tình huống/bài tập",
        ],
        "objectives_en": [
            f"State the core knowledge of “{topic}” in {subject} ({grade})",
            f"Complete practice using correct {subject} terminology",
            f"Apply “{topic}” in a task or situation",
        ],
        "core_content_vi": (
            f"Bài học môn {subject} ({grade}) theo GDPT 2018, chủ đề “{topic}”. "
            f"Giáo viên dạy đúng kiến thức và thuật ngữ của môn {subject}, "
            "qua 4 hoạt động: Mở đầu — Hình thành kiến thức mới — Luyện tập — Vận dụng."
        ),
        "core_content_en": (
            f"GDPT 2018 lesson in {subject} ({grade}) on “{topic}”: "
            "subject-specific knowledge and terms through the four standard activities."
        ),
        "sections": sections,
        "vocabulary": [
            {"term": topic.split()[0] if topic else "topic", "meaning_vi": topic, "example": f"Today we study {topic}."},
            {"term": "definition", "meaning_vi": "định nghĩa", "example": f"Define key ideas of {topic}."},
            {"term": subject.split()[0] if subject else "subject", "meaning_vi": subject, "example": f"This is a {subject} lesson."},
            {"term": "practice", "meaning_vi": "luyện tập", "example": f"Practise {topic}."},
            {"term": "application", "meaning_vi": "vận dụng", "example": f"Apply {topic} in a task."},
        ],
        "assessment": {
            "methods": ["Oral check", "Subject exercise", "Application task"],
            "criteria": [f"Correct {subject} knowledge", "Correct terminology", "Completed practice"],
        },
        "homework": [
            f"Ôn kiến thức “{topic}” (môn {subject}).",
            f"Làm bài tập vận dụng về “{topic}”.",
        ],
        "source": "template",
        "language": language,
    }


def _fallback_math_questions(topic: str, num_questions: int, types: list) -> list[dict]:
    t = (topic or "").lower()
    if any(k in t for k in ("tích phân", "tich phan", "integral", "nguyên hàm", "nguyen ham")):
        bank = [
            {
                "question_text": "Compute ∫ 2x dx.",
                "question_type": "multiple_choice",
                "options": ["A. x^2 + C", "B. 2x^2 + C", "C. x + C", "D. 2 + C"],
                "correct_answer": "A. x^2 + C",
                "explanation": "The antiderivative of 2x is x^2 + C.",
                "points": 1,
            },
            {
                "question_text": "∫_0^1 3x^2 dx equals 1.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "[x^3]_0^1 = 1.",
                "points": 1,
            },
            {
                "question_text": "Fill the result: ∫ 6x dx = ______ + C",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "3x^2",
                "explanation": "Coefficient 6 / 2 = 3.",
                "points": 1,
            },
            {
                "question_text": "Compute ∫_0^2 (3x^2 - 2x) dx. Show the steps and the final number.",
                "question_type": "essay",
                "options": [],
                "correct_answer": "4",
                "sample_answer": "Antiderivative x^3 - x^2. At 2: 8-4=4. At 0: 0. Result 4.",
                "explanation": "Award method and the value 4.",
                "points": 2,
            },
            {
                "question_text": "The antiderivative of cos x is sin x + C.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "d/dx (sin x) = cos x.",
                "points": 1,
            },
            {
                "question_text": "Find ∫ (4x^3) dx.",
                "question_type": "multiple_choice",
                "options": ["A. x^4 + C", "B. 4x^4 + C", "C. 12x^2 + C", "D. x^3 + C"],
                "correct_answer": "A. x^4 + C",
                "explanation": "4 * x^4 / 4 = x^4 + C.",
                "points": 1,
            },
        ]
    else:
        bank = [
            {
                "question_text": "Let f(x) = x^3 - 3x^2 + 2. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 3x^2 - 6x", "B. 3x^2 - 3x", "C. x^2 - 6x", "D. 3x - 6"],
                "correct_answer": "A. 3x^2 - 6x",
                "explanation": "Power rule: 3x^2 - 6x.",
                "points": 1,
            },
            {
                "question_text": "If f(x) = e^x then f'(x) = e^x.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "The derivative of e^x is itself.",
                "points": 1,
            },
            {
                "question_text": "Fill: d/dx (x^2) = ______",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "2x",
                "explanation": "Power rule.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = (2x + 1)^3. Find f'(x). Show the chain-rule steps.",
                "question_type": "essay",
                "options": [],
                "correct_answer": "6(2x+1)^2",
                "sample_answer": "u=2x+1, y=u^3, y'=3u^2 * 2 = 6(2x+1)^2.",
                "explanation": "Award chain rule and the factor 6.",
                "points": 2,
            },
            {
                "question_text": "f(x) = sin x. What is f'(π/2)?",
                "question_type": "multiple_choice",
                "options": ["A. 0", "B. 1", "C. -1", "D. π/2"],
                "correct_answer": "A. 0",
                "explanation": "f'(x)=cos x, cos(π/2)=0.",
                "points": 1,
            },
            {
                "question_text": "The derivative of a constant function is 0.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "d/dx (c) = 0.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = 5x^4 - 2x. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 20x^3 - 2", "B. 5x^3 - 2", "C. 20x^4 - 2", "D. 4x^3 - 2"],
                "correct_answer": "A. 20x^3 - 2",
                "explanation": "Power rule: 20x^3 - 2.",
                "points": 1,
            },
            {
                "question_text": "If y = ln x then y' = 1/x (for x > 0).",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "Standard derivative of ln x.",
                "points": 1,
            },
            {
                "question_text": "Fill: d/dx (cos x) = ______",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "-sin x",
                "explanation": "Derivative of cosine is -sine.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = x^2 + 4x. Find f'(1).",
                "question_type": "multiple_choice",
                "options": ["A. 6", "B. 5", "C. 2", "D. 8"],
                "correct_answer": "A. 6",
                "explanation": "f'(x)=2x+4, so f'(1)=6.",
                "points": 1,
            },
            {
                "question_text": "Compute the derivative of f(x) = (x^2 + 1)(x - 3) using the product rule. Give f'(x).",
                "question_type": "essay",
                "options": [],
                "correct_answer": "3x^2 - 6x + 1",
                "sample_answer": "u=x^2+1, v=x-3. u'=2x, v'=1. f'=2x(x-3)+(x^2+1)=3x^2-6x+1.",
                "explanation": "Award product rule and simplified f'(x).",
                "points": 2,
            },
            {
                "question_text": "Let f(x) = x^3. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 3x^2", "B. 3x", "C. x^2", "D. 3"],
                "correct_answer": "A. 3x^2",
                "explanation": "Power rule: 3x^2.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = 2x^3. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 6x^2", "B. 2x^2", "C. 6x^3", "D. 3x^2"],
                "correct_answer": "A. 6x^2",
                "explanation": "2 * 3x^2 = 6x^2.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = 7x. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 7", "B. 7x", "C. x", "D. 0"],
                "correct_answer": "A. 7",
                "explanation": "The derivative of cx is c.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = 1/x. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. -1/x^2", "B. 1/x^2", "C. ln x", "D. 1/x"],
                "correct_answer": "A. -1/x^2",
                "explanation": "x^{-1} differentiates to -x^{-2}.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = √x. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 1/(2√x)", "B. √x / 2", "C. 2√x", "D. 1/√x"],
                "correct_answer": "A. 1/(2√x)",
                "explanation": "x^{1/2} → (1/2) x^{-1/2}.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = sin(3x). Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 3 cos(3x)", "B. cos(3x)", "C. 3 sin(3x)", "D. -3 cos(3x)"],
                "correct_answer": "A. 3 cos(3x)",
                "explanation": "Chain rule: cos(3x) * 3.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = e^{2x}. Find f'(x).",
                "question_type": "multiple_choice",
                "options": ["A. 2e^{2x}", "B. e^{2x}", "C. 2x e^{2x}", "D. e^x"],
                "correct_answer": "A. 2e^{2x}",
                "explanation": "Chain rule: e^{2x} * 2.",
                "points": 1,
            },
            {
                "question_text": "d/dx (tan x) = 1/cos^2 x.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "Equivalent to sec^2 x.",
                "points": 1,
            },
            {
                "question_text": "If f'(x) > 0 on an interval then f is increasing there.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "Sign of the first derivative.",
                "points": 1,
            },
            {
                "question_text": "Fill: d/dx (x^5) = ______",
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": "5x^4",
                "explanation": "Power rule.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = 3x^2 - 4x + 1. Find f'(2).",
                "question_type": "multiple_choice",
                "options": ["A. 8", "B. 6", "C. 4", "D. 12"],
                "correct_answer": "A. 8",
                "explanation": "f'(x)=6x-4, f'(2)=8.",
                "points": 1,
            },
            {
                "question_text": "The slope of the tangent to y = x^2 at x = 1 is 2.",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
                "explanation": "y' = 2x, at x=1 the slope is 2.",
                "points": 1,
            },
            {
                "question_text": "Find the second derivative of f(x) = x^3.",
                "question_type": "multiple_choice",
                "options": ["A. 6x", "B. 3x^2", "C. 6", "D. x"],
                "correct_answer": "A. 6x",
                "explanation": "f'=3x^2, f''=6x.",
                "points": 1,
            },
            {
                "question_text": "Let f(x) = x sin x. Find f'(x) using the product rule. Show the steps.",
                "question_type": "essay",
                "options": [],
                "correct_answer": "sin x + x cos x",
                "sample_answer": "u=x, v=sin x. u'=1, v'=cos x. f'=sin x + x cos x.",
                "explanation": "Award product rule and the expanded derivative.",
                "points": 2,
            },
        ]
    types = types or ["multiple_choice"]
    out = []
    used = set()
    type_i = 0
    for _ in range(num_questions * 4):
        if len(out) >= num_questions:
            break
        want = types[type_i % len(types)]
        type_i += 1
        pool = [q for q in bank if q["question_type"] == want] or bank
        picked = next((q for q in pool if q["question_text"] not in used), None)
        if not picked:
            continue
        used.add(picked["question_text"])
        out.append(dict(picked))
    for q in bank:
        if len(out) >= num_questions:
            break
        if q["question_text"] not in used:
            used.add(q["question_text"])
            out.append(dict(q))
    return out[:num_questions]


def _is_kieu_topic(subject: str, topic: str) -> bool:
    blob = _fold_text(f"{subject} {topic}")
    return any(k in blob for k in (
        "truyen kieu", "nguyen du", "thuy kieu", "kim trong", "hoan thu",
    ))


def _pick_typed_questions(bank: list[dict], types: list, num_questions: int) -> list[dict]:
    types = types or ["multiple_choice"]
    out = []
    used = set()
    type_i = 0
    for _ in range(num_questions * 6):
        if len(out) >= num_questions:
            break
        want = types[type_i % len(types)]
        type_i += 1
        pool = [q for q in bank if q.get("question_type") == want] or bank
        picked = next((q for q in pool if q["question_text"] not in used), None)
        if not picked:
            continue
        used.add(picked["question_text"])
        out.append(dict(picked))
    for q in bank:
        if len(out) >= num_questions:
            break
        if q["question_text"] not in used:
            used.add(q["question_text"])
            out.append(dict(q))
    return out[:num_questions]


def _kieu_exam_bank() -> list[dict]:
    return [
        {
            "question_text": "Who wrote the verse novel Truyện Kiều?",
            "question_type": "multiple_choice",
            "options": ["A. Nguyễn Du", "B. Hồ Xuân Hương", "C. Nguyễn Trãi", "D. Nguyễn Bỉnh Khiêm"],
            "correct_answer": "A. Nguyễn Du",
            "explanation": "Nguyễn Du (1765–1820) wrote Đoạn trường tân thanh, known as Truyện Kiều.",
            "points": 1,
        },
        {
            "question_text": "Who is the main female character of Truyện Kiều?",
            "question_type": "multiple_choice",
            "options": ["A. Thúy Kiều", "B. Hoạn Thư", "C. Đạm Tiên", "D. Thúy Vân"],
            "correct_answer": "A. Thúy Kiều",
            "explanation": "Vương Thúy Kiều is the tragic heroine.",
            "points": 1,
        },
        {
            "question_text": "Kim Trọng is best described as:",
            "question_type": "multiple_choice",
            "options": [
                "A. Kiều’s fiancé and first love",
                "B. Kiều’s father",
                "C. A mandarin who arrests Kiều",
                "D. Kiều’s younger brother",
            ],
            "correct_answer": "A. Kiều’s fiancé and first love",
            "explanation": "Kiều and Kim Trọng exchange vows under the moon before her family crisis.",
            "points": 1,
        },
        {
            "question_text": "Thúy Vân is Kiều’s:",
            "question_type": "multiple_choice",
            "options": ["A. Younger sister", "B. Mother", "C. Teacher", "D. Servant"],
            "correct_answer": "A. Younger sister",
            "explanation": "Thúy Vân later marries Kim Trọng while Kiều is away.",
            "points": 1,
        },
        {
            "question_text": "Truyện Kiều is mainly written in which Vietnamese verse form?",
            "question_type": "multiple_choice",
            "options": ["A. Lục bát", "B. Free verse", "C. Sonnet", "D. Haiku"],
            "correct_answer": "A. Lục bát",
            "explanation": "The narrative uses lục bát (6–8) lines.",
            "points": 1,
        },
        {
            "question_text": "The theme “tài mệnh tương đố” in Truyện Kiều means:",
            "question_type": "multiple_choice",
            "options": [
                "A. Talent and fate are in conflict",
                "B. War is better than peace",
                "C. Students must copy the teacher",
                "D. Love always wins easily",
            ],
            "correct_answer": "A. Talent and fate are in conflict",
            "explanation": "Beautiful, talented Kiều still suffers because of fate.",
            "points": 1,
        },
        {
            "question_text": "Nguyễn Du wrote Truyện Kiều.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": "The author is Nguyễn Du.",
            "points": 1,
        },
        {
            "question_text": "Thúy Kiều is only a minor character in Truyện Kiều.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "False",
            "explanation": "She is the main character.",
            "points": 1,
        },
        {
            "question_text": "Kim Trọng is Kiều’s first love.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": "They pledge love before her family disaster.",
            "points": 1,
        },
        {
            "question_text": "Hoạn Thư is Kiều’s younger sister.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "False",
            "explanation": "Hoạn Thư is Thúc Sinh’s jealous wife; Thúy Vân is the sister.",
            "points": 1,
        },
        {
            "question_text": "Complete: Truyện Kiều was written by ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": "Nguyễn Du",
            "explanation": "The author is Nguyễn Du.",
            "points": 1,
        },
        {
            "question_text": "Complete: The heroine of Truyện Kiều is ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": "Thúy Kiều",
            "explanation": "Vương Thúy Kiều.",
            "points": 1,
        },
        {
            "question_text": "Complete: Kiều’s first love is ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": "Kim Trọng",
            "explanation": "Kim Trọng.",
            "points": 1,
        },
        {
            "question_text": "Complete: Truyện Kiều is written in the verse form ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": "lục bát",
            "explanation": "Lục bát (six-eight verse).",
            "points": 1,
        },
        {
            "question_text": "Explain in 6–8 English sentences why Thúy Kiều has to leave home and sell herself. Give one event from the story.",
            "question_type": "essay",
            "options": [],
            "correct_answer": "Kiều sacrifices herself to save her family after her father is arrested; she is sold into a brothel.",
            "sample_answer": (
                "Kiều’s father and brother are arrested after a false accusation. "
                "To pay the officials and save her family, she agrees to be sold in marriage. "
                "The matchmaker Mã Giám Sinh tricks her and she is forced into a brothel. "
                "This shows her filial piety (hiếu) and the unfair fate of a talented woman."
            ),
            "explanation": "Score: family crisis, sacrifice, one named event, personal comment.",
            "points": 2,
        },
        {
            "question_text": "Compare Thúy Kiều and Thúy Vân in 6–8 English sentences. What does each sister represent?",
            "question_type": "essay",
            "options": [],
            "correct_answer": "Kiều is talented but unlucky; Vân is calmer and later lives a stable life with Kim Trọng.",
            "sample_answer": (
                "Kiều is more beautiful and gifted, yet she suffers. "
                "Vân is quieter and later marries Kim Trọng. "
                "Nguyễn Du contrasts talent versus a peaceful fate."
            ),
            "explanation": "Score contrast, fate, and one example.",
            "points": 2,
        },
        {
            "question_text": "From whose Chinese novel did Nguyễn Du adapt Truyện Kiều?",
            "question_type": "multiple_choice",
            "options": [
                "A. Thanh Tâm Tài Nhân’s Kim Vân Kiều",
                "B. Romance of the Three Kingdoms",
                "C. Journey to the West",
                "D. The Tale of Genji",
            ],
            "correct_answer": "A. Thanh Tâm Tài Nhân’s Kim Vân Kiều",
            "explanation": "Đoạn trường tân thanh retells Kim Vân Kiều truyện.",
            "points": 1,
        },
        {
            "question_text": "Hoạn Thư is mainly known in the story as:",
            "question_type": "multiple_choice",
            "options": [
                "A. Thúc Sinh’s jealous wife who punishes Kiều",
                "B. Kiều’s kind aunt",
                "C. A Buddhist nun who writes the poem",
                "D. Kim Trọng’s mother",
            ],
            "correct_answer": "A. Thúc Sinh’s jealous wife who punishes Kiều",
            "explanation": "Hoạn Thư is famous for jealousy and later a moment of generosity.",
            "points": 1,
        },
        {
            "question_text": "Explain in 6–8 English sentences the idea “tài mệnh tương đố” using Kiều’s life.",
            "question_type": "essay",
            "options": [],
            "correct_answer": "Talent and fate conflict: Kiều is gifted but suffers injustice and exile.",
            "sample_answer": (
                "Tài mệnh tương đố means talent and fate clash. "
                "Kiều is beautiful and skilled at music and poetry, yet she is sold and suffers. "
                "Nguyễn Du shows a talented woman crushed by family duty and social injustice."
            ),
            "explanation": "Score definition, Kiều example, and a comment on fate.",
            "points": 2,
        },
    ]


def _general_topic_exam_bank(grade: str, subject: str, topic: str) -> list[dict]:
    title = topic or subject or "this lesson"
    return [
        {
            "question_text": f"Which focus belongs to the lesson “{title}”?",
            "question_type": "multiple_choice",
            "options": [
                f"A. Facts, people and events of “{title}”",
                "B. A Wi-Fi password",
                "C. Yesterday’s football score",
                "D. A random cooking recipe",
            ],
            "correct_answer": f"A. Facts, people and events of “{title}”",
            "explanation": "Stay on the named topic.",
            "points": 1,
        },
        {
            "question_text": f"This {subject} lesson is mainly about:",
            "question_type": "multiple_choice",
            "options": [
                f"A. {title}",
                "B. Computer hardware only",
                "C. Driving rules",
                "D. Weather on Mars",
            ],
            "correct_answer": f"A. {title}",
            "explanation": "The topic title is the exam focus.",
            "points": 1,
        },
        {
            "question_text": f"Students of {grade} study “{title}” in {subject}.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": f"The paper is written for {grade}.",
            "points": 1,
        },
        {
            "question_text": f"“{title}” is a chemistry formula, not a lesson topic.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "False",
            "explanation": "It is the lesson topic.",
            "points": 1,
        },
        {
            "question_text": f"Complete: The title of this lesson is ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": title,
            "explanation": "Use the exact topic.",
            "points": 1,
        },
        {
            "question_text": f"Complete: The school subject of this paper is ______.",
            "question_type": "fill_blank",
            "options": [],
            "correct_answer": subject or "Literature",
            "explanation": "Copy the subject name.",
            "points": 1,
        },
        {
            "question_text": f"Write 6–8 English sentences on the main idea of “{title}”. Give one concrete example.",
            "question_type": "essay",
            "options": [],
            "correct_answer": f"State the main idea of {title} and one example.",
            "sample_answer": f"The lesson “{title}” asks students to explain the content and give a real example.",
            "explanation": "Score main idea, example, organisation.",
            "points": 2,
        },
        {
            "question_text": f"In 6–8 English sentences, explain why “{title}” matters for {grade} students.",
            "question_type": "essay",
            "options": [],
            "correct_answer": f"Link {title} to knowledge and values for {grade}.",
            "sample_answer": f"“{title}” helps {grade} students understand the work and discuss its meaning.",
            "explanation": "Score reason, example, comment.",
            "points": 2,
        },
        {
            "question_text": f"Which class is this “{title}” paper written for?",
            "question_type": "multiple_choice",
            "options": [f"A. {grade}", "B. Kindergarten only", "C. University physics", "D. A driving school"],
            "correct_answer": f"A. {grade}",
            "explanation": f"Grade is {grade}.",
            "points": 1,
        },
        {
            "question_text": f"A student can ignore the content of “{title}” and still score full marks.",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "False",
            "explanation": "The exam tests the topic itself.",
            "points": 1,
        },
    ]


def _fallback_topic_questions(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int,
    quiz_types: list | None = None,
) -> list[dict]:
    types = quiz_types or ["multiple_choice"]
    bank = _kieu_exam_bank() if _is_kieu_topic(subject, topic) else _general_topic_exam_bank(grade, subject, topic)
    return _pick_typed_questions(bank, types, num_questions)


def _complete_quiz_questions(
    questions: list,
    grade: str,
    subject: str,
    topic: str,
    need: int,
    quiz_types: list | None = None,
) -> list[dict]:
    """Dedup, drop fillers, pad from the topic bank, keep types and answers complete."""
    from app.routes.quizzes import normalize_quiz_questions

    types = quiz_types or ["multiple_choice"]
    qs = _scrub_quiz_questions(
        normalize_quiz_questions(questions),
        grade, subject, topic, need, types,
    )
    bank = _fallback_topic_questions(grade, subject, topic, max(need, 16), types)
    stems = {
        str(q.get("question_text") or "").strip().lower()
        for q in qs
    }
    for extra in bank:
        if len(qs) >= need:
            break
        stem = str(extra.get("question_text") or "").strip().lower()
        if stem and stem not in stems:
            qs.append(dict(extra))
            stems.add(stem)

    present = {q.get("question_type") for q in qs}
    if len(qs) >= len(types):
        counts: dict[str, int] = {}
        for q in qs:
            t = q.get("question_type") or "multiple_choice"
            counts[t] = counts.get(t, 0) + 1
        for want in types:
            if want in present:
                continue
            extra = next(
                (
                    dict(q) for q in bank
                    if q.get("question_type") == want
                    and str(q.get("question_text") or "").strip().lower() not in stems
                ),
                None,
            )
            if not extra:
                continue
            replace_i = next(
                (i for i in range(len(qs) - 1, -1, -1) if counts.get(qs[i].get("question_type"), 0) >= 2),
                None,
            )
            if replace_i is None:
                if len(qs) < need:
                    qs.append(extra)
                    stems.add(str(extra.get("question_text") or "").strip().lower())
                    present.add(want)
                continue
            old_t = qs[replace_i].get("question_type")
            counts[old_t] = counts.get(old_t, 1) - 1
            qs[replace_i] = extra
            counts[want] = counts.get(want, 0) + 1
            present.add(want)
            stems.add(str(extra.get("question_text") or "").strip().lower())

    tf_idx = [i for i, q in enumerate(qs) if q.get("question_type") == "true_false"]
    tf_answers = {str(qs[i].get("correct_answer") or "") for i in tf_idx}
    if len(tf_idx) >= 2 and tf_answers <= {"True"}:
        false_bank = [
            dict(q) for q in bank
            if q.get("question_type") == "true_false"
            and str(q.get("correct_answer") or "") == "False"
            and str(q.get("question_text") or "").strip().lower() not in stems
        ]
        for n, i in enumerate(tf_idx):
            if n == 0 or not false_bank:
                continue
            extra = false_bank.pop(0)
            stems.add(str(extra.get("question_text") or "").strip().lower())
            extra["options"] = ["True", "False"]
            qs[i] = extra

    out = []
    for q in qs[:need]:
        item = dict(q)
        qtype = item.get("question_type") or "multiple_choice"
        if qtype in ("fill_blank", "essay"):
            item["options"] = []
            if not str(item.get("correct_answer") or "").strip():
                item["correct_answer"] = str(item.get("sample_answer") or topic)
        elif qtype == "true_false":
            item["options"] = ["True", "False"]
            if item.get("correct_answer") not in ("True", "False"):
                item["correct_answer"] = "True"
        elif qtype == "multiple_choice":
            opts = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
            while len(opts) < 4:
                opts.append(f"Option {len(opts) + 1}")
            item["options"] = opts[:4]
            if item.get("correct_answer") not in item["options"]:
                item["correct_answer"] = item["options"][0]
        out.append(item)
    return out


def _fallback_quiz(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int,
    quiz_types: list | None = None,
    language: str = "vi",
) -> dict:
    types = quiz_types or ["multiple_choice"]
    if _is_math_topic(subject, topic):
        questions = _fallback_math_questions(topic, num_questions, types)
        title = f"Practice quiz: {topic}"
    else:
        questions = _fallback_topic_questions(grade, subject, topic, num_questions, types)
        title = f"Quiz: {topic}"
    questions = _complete_quiz_questions(
        questions, grade, subject, topic, num_questions, types,
    )
    return {
        "title": title,
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "language": language,
        "passing_score": 60,
        "time_limit_minutes": 20,
        "questions": questions,
        "source": "practice",
        "note": None,
    }


def _fallback_slides(grade: str, subject: str, topic: str, slide_count: int, language: str = "vi") -> dict:
    if _is_kieu_topic(subject, topic) or _is_literature_topic(subject, topic):
        slides = [
            {
                "layout": "title",
                "title": topic,
                "subtitle": f"{subject} · {grade}",
                "bullets": [grade, subject, "Nguyễn Du · lục bát · Thúy Kiều"],
                "image_keyword": "truyen kieu nguyen du book vietnam literature class",
                "notes": "Mở bài: ghi bảng Nguyễn Du – Truyện Kiều – lục bát. Hỏi HS nữ chính là ai.",
            },
            {
                "layout": "content",
                "title": "Learning objectives",
                "bullets": [
                    "Name Nguyễn Du and the work Đoạn trường tân thanh",
                    "Identify lục bát and four main characters",
                    "Explain tài mệnh tương đố and chữ hiếu with one plot event",
                ],
                "image_keyword": "vietnam literature textbook truyen kieu classroom",
                "notes": "Đọc mục tiêu: tác giả, thể thơ, nhân vật, chủ đề. Không nói kỹ năng sống chung.",
            },
            {
                "layout": "two_column",
                "title": "Author and the work",
                "left_title": "Nguyễn Du",
                "right_title": "Truyện Kiều",
                "left_bullets": ["Poet of late Lê – early Nguyễn", "Courtesy name Tố Như", "Wrote from folk tale Kim Vân Kiều"],
                "right_bullets": ["Also called Đoạn trường tân thanh", "A verse novel in lục bát", "Heroine: Vương Thúy Kiều"],
                "image_keyword": "nguyen du portrait vietnam poet classroom poster",
                "notes": "Chốt: Nguyễn Du sáng tác Truyện Kiều / Đoạn trường tân thanh bằng lục bát.",
            },
            {
                "layout": "cards",
                "title": "Form: lục bát",
                "bullets": [
                    "Six-syllable line + eight-syllable line",
                    "Rhyme links the 6th sound of the 8-syllable line",
                    "Used for long narrative verse in Vietnamese",
                    "Truyện Kiều is the model lục bát work",
                ],
                "image_keyword": "luc bat verse lines chalkboard vietnam",
                "notes": "Viết một cặp lục bát mẫu lên bảng; hỏi HS đếm tiếng 6–8.",
            },
            {
                "layout": "table",
                "title": "Main characters",
                "table": {
                    "headers": ["Character", "Role", "Key event"],
                    "rows": [
                        ["Thúy Kiều", "Heroine", "Sells herself to save her father"],
                        ["Thúy Vân", "Younger sister", "Marries Kim Trọng in Kiều’s place"],
                        ["Kim Trọng", "Beloved", "Parted from Kiều, later reunited"],
                        ["Hoạn Thư", "Jealous wife", "Torments Kiều out of jealousy"],
                    ],
                },
                "bullets": ["Kiều", "Vân", "Kim Trọng", "Hoạn Thư"],
                "notes": "HS điền miệng vai trò từng nhân vật. Sai tên là sai kiến thức bài.",
            },
            {
                "layout": "two_column",
                "title": "Plot you must know",
                "left_title": "What happens",
                "right_title": "Why it matters",
                "left_bullets": [
                    "Kiều meets Kim Trọng and pledges love",
                    "Her father is framed; she sells herself",
                    "She suffers in a brothel and under Hoạn Thư",
                ],
                "right_bullets": [
                    "Love is broken by family disaster",
                    "Chữ hiếu: she sacrifices for her father",
                    "Tài mệnh tương đố: talent meets a hard fate",
                ],
                "image_keyword": "thuy kieu story scene vietnam literature",
                "notes": "Kể 3 mốc: gặp Kim Trọng – bán mình – Hoạn Thư. Hỏi chữ hiếu nằm ở mốc nào.",
            },
            {
                "layout": "content",
                "title": "Themes to teach",
                "bullets": [
                    "Tài mệnh tương đố: beauty and talent bring a bitter fate",
                    "Chữ hiếu: Kiều sells herself to save her father",
                    "Compassion for the fallen woman in feudal society",
                    "Hope of reunion after years of suffering",
                ],
                "image_keyword": "vietnam students discussing truyen kieu themes",
                "notes": "Bắt HS lấy 1 sự kiện chứng minh tài mệnh hoặc chữ hiếu.",
            },
            {
                "layout": "table",
                "title": "Lesson vocabulary",
                "table": {
                    "headers": ["Term", "Meaning", "Use in this lesson"],
                    "rows": [
                        ["lục bát", "6–8 verse form", "Truyện Kiều is written in lục bát."],
                        ["filial piety", "chữ hiếu", "Kiều shows filial piety."],
                        ["fate", "số mệnh", "Talent conflicts with fate."],
                        ["heroine", "nữ chính", "Thúy Kiều is the heroine."],
                    ],
                },
                "bullets": ["lục bát", "filial piety", "fate", "heroine"],
                "notes": "Đọc thuật ngữ; yêu cầu đặt câu có tên nhân vật.",
            },
            {
                "layout": "content",
                "title": "Close reading task",
                "bullets": [
                    "Fill the character–role–event table",
                    "Quote one fact that shows chữ hiếu",
                    "Explain in 4 sentences why Kiều must leave Kim Trọng",
                ],
                "image_keyword": "students writing character table literature class vietnam",
                "notes": "Phát phiếu nhân vật. Không cho làm poster kỹ năng sống.",
            },
            {
                "layout": "closing",
                "title": "Review Truyện Kiều",
                "bullets": [
                    "Author: Nguyễn Du · Form: lục bát",
                    "Homework: 6 English sentences on chữ hiếu",
                ],
                "image_keyword": "vietnam classroom end of literature lesson",
                "notes": "Chốt 3 ý: tác giả, thể thơ, chữ hiếu. Giao bài về nhà.",
            },
        ]
        extras = [
            {
                "layout": "two_column",
                "title": "Kiều and Vân",
                "left_title": "Thúy Kiều",
                "right_title": "Thúy Vân",
                "left_bullets": ["Elder sister", "More talented and beautiful", "Bears a tragic fate"],
                "right_bullets": ["Younger sister", "Gentle, less striking", "Marries Kim Trọng first"],
                "image_keyword": "two sisters comparison literature vietnam",
                "notes": "So sánh tài sắc và số phận hai chị em. Hỏi vì sao Vân lấy Kim Trọng.",
            },
            {
                "layout": "content",
                "title": "Hoạn Thư episode",
                "bullets": [
                    "Hoạn Thư is the jealous wife of Thúc Sinh",
                    "She captures Kiều and makes her a servant",
                    "The episode shows cruelty born of jealousy",
                    "Kiều later meets her again and chooses mercy",
                ],
                "image_keyword": "hoan thu truyen kieu scene classroom",
                "notes": "Chốt: Hoạn Thư hành hạ Kiều vì ghen. Hỏi HS Kiều xử sự ra sao khi gặp lại.",
            },
            {
                "layout": "cards",
                "title": "Check the work",
                "bullets": [
                    "Who wrote Truyện Kiều?",
                    "What verse form is used?",
                    "Why does Kiều sell herself?",
                    "Name Kim Trọng and Hoạn Thư’s roles",
                ],
                "image_keyword": "oral check literature vietnam classroom",
                "notes": "Hỏi nhanh 4 câu kiến thức. Sai tên nhân vật thì chữa ngay.",
            },
            {
                "layout": "content",
                "title": "A lục bát couplet",
                "bullets": [
                    "Read one 6–8 couplet from the opening",
                    "Count the syllables: 6 then 8",
                    "Find the linking rhyme",
                    "Say what the couplet tells about Kiều",
                ],
                "image_keyword": "poetry lines luc bat chalkboard vietnam",
                "notes": "Đọc một cặp lục bát; HS đếm tiếng và chỉ vần.",
            },
            {
                "layout": "content",
                "title": "Homework on the text",
                "bullets": [
                    "Learn: author, form, four characters",
                    "Write 6 English sentences on chữ hiếu",
                    "Prepare one event that shows tài mệnh tương đố",
                ],
                "image_keyword": "homework notebook truyen kieu vietnam",
                "notes": "Giao đúng kiến thức tác phẩm, không giao ‘kể về trải nghiệm’.",
            },
        ]
    else:
        slides = [
            {
                "layout": "title",
                "title": topic,
                "subtitle": f"{subject} · {grade}",
                "bullets": [grade, subject, f"Teaching the topic: {topic}"],
                "image_keyword": f"{subject} {topic} vietnam classroom",
                "notes": f"Mở bài môn {subject}: hôm nay học kiến thức “{topic}”.",
            },
            {
                "layout": "content",
                "title": "Learning objectives",
                "bullets": [
                    f"State the core knowledge of “{topic}” in {subject}",
                    f"Use the correct {subject} terms for this topic",
                    f"Complete a short exercise that needs “{topic}”",
                ],
                "image_keyword": f"{subject} lesson objectives vietnam classroom",
                "notes": f"Đọc mục tiêu kiến thức bài “{topic}”, không đọc khẩu hiệu trải nghiệm.",
            },
            {
                "layout": "two_column",
                "title": f"Warm-up on {topic}",
                "left_title": "Ask",
                "right_title": "We will learn",
                "left_bullets": [
                    f"What do you already know about {topic}?",
                    f"Which {subject} terms belong to this topic?",
                ],
                "right_bullets": [
                    f"The key idea of {topic}",
                    "One worked example",
                    "One practice task",
                ],
                "image_keyword": f"teacher asking about {topic} vietnam class",
                "notes": f"Kích hoạt kiến thức nền đúng “{topic}”.",
            },
            {
                "layout": "cards",
                "title": f"Core knowledge: {topic}",
                "bullets": [
                    f"Definition / main fact of {topic}",
                    f"A clear example from {subject}",
                    f"How this idea is used in {grade}",
                ],
                "image_keyword": f"{topic} teaching board {subject}",
                "notes": f"Giảng định nghĩa và ví dụ của “{topic}”.",
            },
            {
                "layout": "table",
                "title": "Key terms",
                "table": {
                    "headers": ["Term", "Meaning", "In this lesson"],
                    "rows": [
                        [topic.split()[0] if topic else "term", topic, f"We study {topic}."],
                        ["definition", "định nghĩa", f"Write the definition of {topic}."],
                        ["example", "ví dụ", f"Give one {subject} example."],
                    ],
                },
                "bullets": ["definition", "example", topic],
                "notes": f"Chốt thuật ngữ môn {subject} gắn với “{topic}”.",
            },
            {
                "layout": "content",
                "title": f"Practice: {topic}",
                "bullets": [
                    f"Complete a short task that only works if you know {topic}",
                    f"Use {subject} terms in the answer",
                    "Check and correct with the class",
                ],
                "image_keyword": f"students practising {topic} {subject} vietnam",
                "notes": f"Phiếu luyện tập sát “{topic}”, không phải trò chơi chung.",
            },
            {
                "layout": "two_column",
                "title": "Example and check",
                "left_title": "Worked example",
                "right_title": "Quick check",
                "left_bullets": [f"A model item on {topic}", "Show the steps / evidence"],
                "right_bullets": [f"One question on {topic}", "Peer check the answer"],
            },
            {
                "layout": "content",
                "title": f"Consolidate {topic}",
                "bullets": [
                    f"Restate two key facts about {topic}",
                    "Name one term you must remember",
                    "Ask one remaining content question",
                ],
                "image_keyword": f"students summarising {topic} vietnam classroom",
                "notes": f"HS nêu lại kiến thức “{topic}”, không viết ‘I learned / I will apply’ chung.",
            },
            {
                "layout": "table",
                "title": "Lesson summary",
                "table": {
                    "headers": ["Focus", "Content", "Check"],
                    "rows": [
                        ["Knowledge", f"Core idea of {topic}", "Say it in one sentence"],
                        ["Terms", f"{subject} vocabulary", "Use two terms correctly"],
                        ["Practice", f"Exercise on {topic}", "Correct the class task"],
                    ],
                },
            },
            {
                "layout": "closing",
                "title": f"Review: {topic}",
                "bullets": [f"Homework: 3 items on {topic}", "Questions on today’s knowledge"],
                "image_keyword": f"{subject} lesson close vietnam classroom",
                "notes": f"Chốt kiến thức “{topic}” và giao bài về nhà đúng môn.",
            },
        ]
        extras = [
            {
                "layout": "content",
                "title": f"Why {topic} is taught",
                "bullets": [
                    f"It is required knowledge in {subject} for {grade}",
                    "It unlocks the next lesson in this unit",
                    f"Students need it to solve {subject} tasks",
                ],
                "image_keyword": f"{subject} textbook {topic} vietnam",
                "notes": f"Nêu vị trí kiến thức “{topic}” trong môn {subject}.",
            },
            {
                "layout": "two_column",
                "title": "Common mistakes",
                "left_title": "Watch out",
                "right_title": "Correct",
                "left_bullets": [f"Mixing {topic} with a nearby idea", "Using the wrong term"],
                "right_bullets": [f"Keep the definition of {topic}", f"Use {subject} terms only"],
                "image_keyword": f"teacher correcting {topic} on board vietnam",
            },
            {
                "layout": "content",
                "title": "Guided example",
                "bullets": [
                    f"Read a model item about {topic}",
                    "Mark the key term / step",
                    "Try a similar item in pairs",
                ],
                "image_keyword": f"worked example {topic} {subject} vietnam",
            },
            {
                "layout": "cards",
                "title": f"Check: {topic}",
                "bullets": [
                    f"What is the main idea of {topic}?",
                    "Give one correct term",
                    "Give one example from the lesson",
                ],
                "image_keyword": f"oral check {subject} vietnam classroom",
            },
            {
                "layout": "content",
                "title": "Homework",
                "bullets": [
                    f"Review the core knowledge of {topic}",
                    f"Do 3 {subject} items on this topic",
                    "Prepare one question for next class",
                ],
                "image_keyword": f"homework {topic} {subject} notebook",
            },
        ]
    n = max(6, min(int(slide_count or 10), 20))
    title_slide, closing = slides[0], slides[-1]
    middles = slides[1:-1] + extras
    out = [title_slide]
    for i in range(n - 2):
        item = dict(middles[i % len(middles)])
        if i >= len(middles):
            item["title"] = f"{item.get('title')} ({i // len(middles) + 2})"
        out.append(item)
    out.append(closing)
    for s in out:
        if not s.get("notes"):
            s["notes"] = (
                f"Gợi ý giảng: trình bày slide “{s.get('title')}” bằng tiếng Anh; "
                f"hỏi học sinh 1–2 câu kiểm tra hiểu; liên hệ chủ đề {topic}."
            )
    return {
        "title": f"Slides: {topic}",
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "language": language or "vi",
        "slides": out,
        "source": "template",
        "note": "Bản slide mẫu (AI chưa sẵn sàng).",
    }


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj[:40]]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return obj
    return str(obj)


def generate_lesson_draft(
    grade: str,
    subject: str,
    topic: str,
    language: str = "bilingual",
    extra_requirements: str = "",
    description: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
    light: bool = False,
) -> dict:
    language = "bilingual"
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
    )

    def _finish(data: dict | None, source: str | None) -> dict:
        fb = _fallback_lesson(grade, subject, topic, language, description)
        if data:
            out = _scrub_generic_lesson(_merge_ai_json(fb, data), fb)
            out["source"] = source or "gemini"
        else:
            out = fb
            out["source"] = "template"
        out["grade"] = grade
        out["subject"] = subject
        out["topic"] = topic
        out["description"] = out.get("description") or description
        out["duration_minutes"] = _as_int(out.get("duration_minutes"), 45)
        out["language"] = language
        out["theme_color"] = theme_color
        out["theme_accent"] = theme_accent
        out = _enforce_gdpt_lesson_quality(out, fb, grade, subject, topic)
        out.pop("note", None)
        return _json_safe(out)

    teach = _teaching_content_rules(grade, subject, topic)
    profile = _subject_profile_key(subject, topic)
    prompt = f"""
{brief}
{teach}
BẮT BUỘC: Tìm hiểu đúng chương trình GDPT 2018 môn {subject} ({grade}) về “{topic}” trước khi viết.
Sai môn, sai thuật ngữ, sai kiến thức chuyên môn là KHÔNG CHẤP NHẬN. Loại môn: {profile}.
Soạn giáo án GIẢNG DẠY SONG NGỮ đúng môn {subject} và đúng CHỦ ĐỀ “{topic}”. JSON đầy đủ một lần (không cắt):
{{
  "title_vi": "...", "title_en": "...",
  "description": "2-3 câu: dạy kiến thức gì của chủ đề này",
  "duration_minutes": 45,
  "materials": ["đồ dùng 1", "đồ dùng 2", "đồ dùng 3", "đồ dùng 4"],
  "objectives_vi": ["mục tiêu kiến thức 1", "mục tiêu kiến thức 2", "mục tiêu kiến thức 3"],
  "objectives_en": ["knowledge objective 1", "knowledge objective 2", "knowledge objective 3"],
  "core_content_vi": "60-90 chữ: kiến thức then chốt của “{topic}” (tên, sự kiện, công thức, nhân vật…)",
  "core_content_en": "English equivalent, 60-90 words, same facts",
  "sections": [
    {{"heading_vi":"Mở đầu (Khởi động)","heading_en":"Opening (Warm-up)","duration":"5'","content_vi":"3-5 câu kết nối kiến thức, đặt vấn đề","content_en":"3-5 sentences","teacher_activity":"...","student_activity":"...","procedure_steps":["Bước 1","Bước 2"]}},
    {{"heading_vi":"Hình thành kiến thức mới","heading_en":"Knowledge formation","duration":"15'","content_vi":"3-5 câu giảng đúng “{topic}”","content_en":"...","teacher_activity":"...","student_activity":"...","procedure_steps":["Bước 1","Bước 2"]}},
    {{"heading_vi":"Luyện tập","heading_en":"Practice","duration":"15'","content_vi":"3-5 câu bài tập sát “{topic}”","content_en":"...","teacher_activity":"...","student_activity":"...","procedure_steps":["Bước 1","Bước 2"]}},
    {{"heading_vi":"Vận dụng","heading_en":"Application","duration":"10'","content_vi":"3-5 câu vận dụng kiến thức vào tình huống/bài tập","content_en":"...","teacher_activity":"...","student_activity":"...","procedure_steps":["Bước 1","Bước 2"]}}
  ],
  "vocabulary": [{{"term":"thuật ngữ môn học","meaning_vi":"...","example":"câu có kiến thức “{topic}”"}}],
  "homework": ["bài tập đúng chủ đề 1", "bài tập đúng chủ đề 2"]
}}
Lớp {grade}, môn {subject}, CHỦ ĐỀ “{topic}”. ĐÚNG 4 hoạt động GDPT 2018, 5 từ vựng môn học. Mỗi content 3-5 câu kiến thức. JSON hoàn chỉnh.
"""
    compact = f"""
{brief}
{teach}
JSON giáo án GDPT 2018 song ngữ, đúng 4 hoạt động, không cắt:
{{"title_vi":"...","title_en":"...","objectives_vi":["..."],"objectives_en":["..."],"core_content_vi":"...","core_content_en":"...","sections":[{{"heading_vi":"Mở đầu (Khởi động)","heading_en":"Opening (Warm-up)","duration":"5'","content_vi":"...","content_en":"...","teacher_activity":"...","student_activity":"..."}},{{"heading_vi":"Hình thành kiến thức mới","heading_en":"Knowledge formation","duration":"15'","content_vi":"...","content_en":"...","teacher_activity":"...","student_activity":"..."}},{{"heading_vi":"Luyện tập","heading_en":"Practice","duration":"15'","content_vi":"...","content_en":"...","teacher_activity":"...","student_activity":"..."}},{{"heading_vi":"Vận dụng","heading_en":"Application","duration":"10'","content_vi":"...","content_en":"...","teacher_activity":"...","student_activity":"..."}}],"vocabulary":[{{"term":"...","meaning_vi":"...","example":"..."}}],"homework":["..."]}}
Môn {subject}. CHỦ ĐỀ “{topic}”. Thuật ngữ và nội dung đúng môn GDPT 2018.
"""
    try:
        if light:
            data, source = _ask_studio_json(
                compact, SYSTEM_LESSON, max_tokens=2048, timeout=30, compact_prompt=compact,
            )
        else:
            data, source = _ask_studio_json(
                prompt, SYSTEM_LESSON, max_tokens=4096, timeout=40, compact_prompt=compact,
            )
        return _finish(data, source)
    except Exception:
        current_app.logger.exception("generate_lesson_draft failed")
        try:
            data, source = _ask_studio_json(
                compact, SYSTEM_LESSON, max_tokens=2048, timeout=25, compact_prompt=compact,
            )
            return _finish(data, source)
        except Exception:
            return _finish(None, None)


def _quiz_ai_fail_message() -> str:
    try:
        from app.services.secret_store import gemini_is_configured
        if not gemini_is_configured():
            return "Chưa có API key Gemini. Admin hãy nhập key tại Cài đặt AI."
    except Exception:
        pass
    return "AI không tạo được đề. Thử lại sau."


def generate_quiz_draft(
    grade: str,
    subject: str,
    topic: str,
    num_questions: int = 10,
    difficulty: str = "mixed",
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    quiz_types: list | None = None,
    quiz_requirements: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
    light: bool = False,
) -> dict:
    language = "en"
    num_questions = max(3, min(int(num_questions or 10), 20))
    types = quiz_types or ["multiple_choice"]
    types_text = ", ".join(types)
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
        extra_lines=(
            f"- Yêu cầu đề: {quiz_requirements or '(không)'}\n"
            f"- Loại câu: {types_text}\n"
            f"- Số câu: {num_questions}; Độ khó: {difficulty}"
        ),
    )
    lang_rule = (
        "STUDENT QUIZ IN ENGLISH ONLY. Write ALL titles, questions, options, sample answers and explanations in English. "
        "true_false options MUST be exactly [\"True\",\"False\"]. Do not use Vietnamese on the student paper."
    )
    math_example = """
  "questions": [
    {
      "question_text": "Let f(x) = x^3 - 3x^2 + 2. Find f'(x).",
      "question_type": "multiple_choice",
      "options": ["A. 3x^2 - 6x", "B. 3x^2 - 3x", "C. x^2 - 6x", "D. 3x - 6"],
      "correct_answer": "A. 3x^2 - 6x",
      "explanation": "Power rule: 3x^2 - 6x.",
      "points": 1
    }
  ]""" if _is_math_topic(subject, topic) else """
  "questions": [
    {
      "question_text": "A specific exam item about the given topic (not a meta-question).",
      "question_type": "multiple_choice",
      "options": ["A. Concrete answer 1", "B. Concrete answer 2", "C. Concrete answer 3", "D. Concrete answer 4"],
      "correct_answer": "A. Concrete answer 1",
      "explanation": "...",
      "points": 1
    }
  ]"""
    teach = _teaching_content_rules(grade, subject, topic)
    prompt = f"""
{brief}
{teach}

This is a GRADED EXAM paper for {subject} / {topic} (GDPT 2018) — real subject knowledge and terminology.
NOT an ice-breaker, NOT experiential-learning filler unless subject is Hoạt động trải nghiệm.
Write {num_questions} REAL questions. JSON only:
{{
  "title": "Practice: {topic}",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "description": "{description}",
  "passing_score": 60,
  "time_limit_minutes": 20,{math_example}
}}

Lớp: {grade}; Môn: {subject}; Chủ đề: {topic}.
Số câu: {num_questions}; Độ khó: {difficulty}.
Loại câu BẮT BUỘC dùng (phân bổ xen kẽ): {types_text}.
- multiple_choice: 4 lựa chọn A–D, each option is a real answer (formula/number/fact), correct_answer khớp 1 option.
- true_false: options ["True","False"].
- fill_blank: the computed missing result.
- essay: “Show the steps…” with sample_answer; points 2–3.
FORBIDDEN questions/options (do not write these at all):
- “Khái niệm nào liên quan đến {topic}?” / “Which concept relates to {topic}?”
- “Nội dung đúng về {topic}” / “Khái niệm không liên quan” / “Thông tin sai” / “Không có đáp án”
- “A correct idea about {topic}” / “An unrelated concept” / “Incorrect information” / “None of the above”
- “What should students do in the lesson” / “Join the class task” / “Skip the lesson”
- Classroom-behaviour fillers. Ask about people, events, form and themes of “{topic}”.
If the topic is Truyện Kiều / Nguyễn Du: ask about Nguyễn Du, Thúy Kiều, Thúy Vân, Kim Trọng, Hoạn Thư, lục bát, tài mệnh.
true_false: mix True and False answers; never two identical True stems.
fill_blank: options must be [] and correct_answer is the missing word (e.g. Nguyễn Du).
essay: options [] and sample_answer filled.
{lang_rule}
{_quiz_subject_rules(grade, subject, topic)}
Return JSON only.
"""
    system = SYSTEM_MATH_EXAM if _is_math_topic(subject, topic) else (
        SYSTEM_TEACHER + " For this quiz, write a real exam. Never use placeholder/meta options."
    )

    def _bank_quiz():
        fb = _fallback_quiz(grade, subject, topic, num_questions, types, language)
        fb["questions"] = _complete_quiz_questions(
            fb.get("questions"), grade, subject, topic, num_questions, types,
        )
        fb["source"] = "practice"
        fb["quiz_types"] = types
        fb["theme_color"] = theme_color
        fb["theme_accent"] = theme_accent
        fb.pop("note", None)
        return fb

    try:
        compact_quiz = (
            f"{brief}\nJSON exam on \"{topic}\", {min(num_questions, 10)} English questions, types {types_text}. "
            "Facts only (people, events, form). No classroom-behaviour fillers. Mix True/False. "
            "fill_blank and essay: options []. Complete JSON.\n"
            '{"title":"...","questions":[{"question_text":"...","question_type":"multiple_choice","options":["A. ...","B. ...","C. ...","D. ..."],"correct_answer":"A. ...","points":1}]}'
        )
        data, source = _ask_studio_json(
            compact_quiz if light else prompt,
            system,
            max_tokens=2048 if light else 4096,
            timeout=30 if light else 40,
            compact_prompt=compact_quiz,
        )
        raw = (data or {}).get("questions") if data else []
        questions = _complete_quiz_questions(
            raw, grade, subject, topic, num_questions, types,
        )
        if len(questions) < max(3, min(num_questions, 4)):
            return _bank_quiz()
        data = data or {}
        data["questions"] = questions
        data["source"] = source or "ai"
        data.setdefault("grade", grade)
        data.setdefault("subject", subject)
        data.setdefault("topic", topic)
        data.setdefault("description", description)
        data["language"] = language
        data["quiz_types"] = types
        data["theme_color"] = theme_color
        data["theme_accent"] = theme_accent
        data.pop("note", None)
        return data
    except Exception:
        current_app.logger.exception("generate_quiz_draft failed")
        return _bank_quiz()


def _normalize_pptx_slides(slides: list, topic: str, language: str = "vi") -> list[dict]:
    layouts_ok = {"title", "content", "two_column", "table", "cards", "closing"}
    normalized = []
    total = len(slides)
    limit = min(20, max(len(slides), 6))
    for idx, s in enumerate(slides[:limit]):
        if not isinstance(s, dict):
            continue
        layout = str(s.get("layout") or "").lower().strip()
        if layout not in layouts_ok:
            if idx == 0:
                layout = "title"
            elif idx >= total - 1:
                layout = "closing"
            elif s.get("table"):
                layout = "table"
            elif s.get("left_bullets") or s.get("right_bullets"):
                layout = "two_column"
            else:
                layout = "content"

        def _listify(val, limit=8):
            if isinstance(val, str):
                items = [b.strip() for b in val.split("\n") if b.strip()]
            elif isinstance(val, list):
                items = [str(b).strip() for b in val if str(b).strip()]
            else:
                items = []
            return items[:limit]

        bullets = _listify(s.get("bullets"), 8)
        left = _listify(s.get("left_bullets"), 6)
        right = _listify(s.get("right_bullets"), 6)
        table = s.get("table") if isinstance(s.get("table"), dict) else None
        if table:
            headers = [str(h) for h in (table.get("headers") or [])][:5]
            rows = []
            for row in (table.get("rows") or [])[:6]:
                if isinstance(row, list):
                    rows.append([str(c) for c in row][:5])
            table = {"headers": headers or ["Item", "Details", "Notes"], "rows": rows}

        if not bullets and not left and not table and layout not in ("title", "closing"):
            bullets = ["Key idea", "Example", "Class activity"]

        title = str(s.get("title") or topic)
        if language == "en" and " / " in title:
            title = title.split(" / ")[0].strip()
        title = title[:110]

        normalized.append({
            "layout": layout,
            "title": title,
            "subtitle": str(s.get("subtitle") or "")[:120],
            "bullets": bullets,
            "left_title": str(s.get("left_title") or "Overview")[:40],
            "right_title": str(s.get("right_title") or "Practice")[:40],
            "left_bullets": left,
            "right_bullets": right,
            "table": table,
            "image_keyword": str(s.get("image_keyword") or topic)[:80],
            "image_scene": str(s.get("image_scene") or "")[:220],
            "notes": str(s.get("notes") or s.get("notes_vi") or ""),
        })
    return normalized


_VISUAL_GLOSSARY = (
    ("chào cờ", "vietnam school flag raising ceremony students"),
    ("chao co", "vietnam school flag raising ceremony students"),
    ("quốc kỳ", "vietnam red flag yellow star"),
    ("quoc ky", "vietnam red flag yellow star"),
    ("quốc ca", "students singing vietnam national anthem"),
    ("quoc ca", "students singing vietnam national anthem"),
    ("xếp hàng", "vietnamese students lining up schoolyard"),
    ("xep hang", "vietnamese students lining up schoolyard"),
    ("sân trường", "vietnam schoolyard students assembly"),
    ("san truong", "vietnam schoolyard students assembly"),
    ("tôn trọng", "students saluting vietnam national flag"),
    ("ton trong", "students saluting vietnam national flag"),
    ("cờ đỏ", "vietnam red flag yellow star"),
    ("sao vàng", "vietnam yellow star red flag"),
    ("lễ chào", "vietnam school monday flag ceremony"),
    ("đoàn kết", "vietnamese students holding hands school"),
    ("tái chế", "vietnam students recycling plastic bottles"),
    ("môi trường", "vietnam school green trees students"),
    ("nhóm", "vietnamese students teamwork classroom"),
    ("thảo luận", "vietnamese students discussion classroom"),
    ("viết", "students writing notebook classroom vietnam"),
    ("trình bày", "student presenting in front of class vietnam"),
)


def _visual_from_text(*parts: str) -> str:
    blob = " ".join(str(p or "") for p in parts).lower()
    hits = [en for vi, en in _VISUAL_GLOSSARY if vi in blob]
    if hits:
        return hits[0]
    return ""


def _enrich_image_keywords(slides: list[dict], topic: str) -> list[dict]:
    """Keyword ảnh lấy từ tiêu đề + bullets từng slide, ưu tiên cảnh Việt Nam."""
    topic_visual = _visual_from_text(topic) or "vietnamese students school experiential activity"
    weak = {
        "", "education", "learning", "background", "abstract", "image", "photo",
        "topic", "slide", "content", "school", "students",
    }
    for s in slides:
        title = s.get("title") or ""
        bullets = s.get("bullets") or s.get("left_bullets") or []
        body = " ".join(str(b) for b in bullets[:3])
        mapped = _visual_from_text(title, body, topic)
        kw = (s.get("image_keyword") or "").strip()
        if kw.lower() in weak or kw.lower() == (topic or "").lower() or len(kw.split()) < 3:
            words = [w for w in title.replace("/", " ").split() if len(w) > 3][:5]
            derived = " ".join(words)
            s["image_keyword"] = (mapped or f"{derived} {topic_visual}").strip()[:80]
        elif mapped and "vietnam" not in kw.lower() and "viet" not in kw.lower():
            s["image_keyword"] = f"{kw} {mapped}".strip()[:80]
        if not (s.get("image_scene") or "").strip():
            cue = (body or title or topic).strip()[:160]
            s["image_scene"] = (
                f"Vietnamese secondary school scene for '{title}': {cue}. "
                "Natural classroom or schoolyard, matching this slide only."
            )[:220]
    return slides


def _fit_slide_count(
    slides: list,
    slide_count: int,
    topic: str,
    language: str,
    grade: str = "",
    subject: str = "",
) -> list[dict]:
    """Cắt hoặc bổ sung cho đúng số slide giáo viên yêu cầu."""
    n = max(6, min(int(slide_count or 10), 20))
    items = [s for s in (slides or []) if isinstance(s, dict)]
    if len(items) == n:
        if items:
            items[0]["layout"] = "title"
            items[-1]["layout"] = "closing"
        return items
    if len(items) > n:
        head, tail = items[0], items[-1]
        mid = items[1:-1][: max(0, n - 2)]
        out = [head] + mid
        if n >= 2:
            if str(tail.get("layout") or "") != "closing":
                tail = {**tail, "layout": "closing"}
            out.append(tail)
        out[0]["layout"] = "title"
        return out[:n]
    fb = _fallback_slides(grade, subject, topic, n, language).get("slides") or []
    closing = None
    core = list(items)
    if core and str(core[-1].get("layout") or "") == "closing":
        closing = core.pop()
    if not core and fb:
        core = [fb[0]]
    extras = [s for s in fb[1:-1] if isinstance(s, dict)]
    seen = {str(s.get("title") or "").strip().lower() for s in core}
    i = 0
    while len(core) < n - 1 and extras:
        extra = dict(extras[i % len(extras)])
        title = str(extra.get("title") or f"Slide {len(core) + 1}")
        if title.lower() in seen:
            title = f"{title} ({len(core) + 1})"
            extra["title"] = title
        seen.add(title.lower())
        core.append(extra)
        i += 1
        if i > 40:
            break
    if closing is None:
        closing = fb[-1] if fb else {
            "layout": "closing", "title": "Thank You",
            "bullets": ["Questions welcome", "See you next lesson"],
            "notes": "Tổng kết và hỏi HS còn thắc mắc gì.",
        }
    core.append(closing)
    if core:
        core[0]["layout"] = "title"
        core[-1]["layout"] = "closing"
    return core[:n]


def generate_pptx_draft(
    grade: str,
    subject: str,
    topic: str,
    slide_count: int = 10,
    lesson_context: dict | None = None,
    language: str = "vi",
    description: str = "",
    extra_requirements: str = "",
    theme_color: str = "#0F2744",
    theme_accent: str = "#F39C4A",
    light: bool = False,
) -> dict:
    language = "en"
    slide_count = max(6, min(int(slide_count or 10), 20))
    context_hint = ""
    follow_lesson = ""
    if lesson_context:
        sections_brief = []
        for s in (lesson_context.get("sections") or [])[:8]:
            sections_brief.append({
                "heading": s.get("heading_en") or s.get("heading_vi"),
                "duration": s.get("duration"),
                "content": ((s.get("content_en") or s.get("content_vi") or "")[:420]),
                "teacher": s.get("teacher_activity"),
                "student": s.get("student_activity"),
            })
        brief = {
            "title": lesson_context.get("title_en") or lesson_context.get("title_vi"),
            "description": (lesson_context.get("description") or "")[:400],
            "core_content": (lesson_context.get("core_content_en") or lesson_context.get("core_content_vi") or "")[:500],
            "objectives": (lesson_context.get("objectives_en") or lesson_context.get("objectives_vi") or [])[:6],
            "materials": (lesson_context.get("materials") or [])[:8],
            "sections": sections_brief,
            "vocabulary": [
                {"term": v.get("term"), "meaning": v.get("meaning_vi")}
                for v in (lesson_context.get("vocabulary") or [])[:8]
            ],
            "assessment": lesson_context.get("assessment"),
            "homework": lesson_context.get("homework"),
        }
        context_hint = (
            "CRITICAL: Build the PowerPoint STRICTLY from this lesson plan / report. "
            "Keep the same teaching flow and ideas (do not invent a different lesson):\n"
            + json.dumps(brief, ensure_ascii=False)[:4500]
        )
        follow_lesson = (
            "- Map slides to GDPT 2018 lesson flow: Mở đầu → Hình thành kiến thức mới → Luyện tập → Vận dụng.\n"
            "- Include one slide for knowledge objectives and one vocabulary/table slide from the lesson.\n"
            "- Reuse key facts (names, events, formulas) from section content; keep the requested language.\n"
            "- Match the subject’s terminology; do not replace with generic experiential slogans.\n"
        )

    brief_txt = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language=language,
        description=description, extra_requirements=extra_requirements,
        theme_color=theme_color, theme_accent=theme_accent,
    )
    lang_rule = (
        "SLIDE TEXT IN ENGLISH ONLY (title, subtitle, bullets, table, cards, closing). "
        "Presenter notes (field notes) MUST be Vietnamese for the teacher: cách giảng slide này, câu hỏi hỏi HS, thời gian gợi ý. "
        "image_keyword and image_scene in English."
    )
    teach = _teaching_content_rules(grade, subject, topic)
    system_en = (
        "You are a subject teacher designing classroom PowerPoint decks to TEACH "
        "the exact school subject and topic (GDPT 2018), not generic experiential activities. "
        "Every title and bullet must be knowledge of that topic. "
        "On-slide text is English. Teacher presenter notes are Vietnamese. "
        "When a lesson plan is provided, the slides MUST follow that plan closely. "
        "Prefer Vietnamese school / Vietnam imagery matching THIS topic. "
        "image_keyword and image_scene must describe the EXACT photo of THAT slide, Vietnam-first. "
        "Return valid JSON only."
    )

    def _pack(deck: dict, source: str | None, slides: list) -> dict:
        deck["slides"] = slides
        deck["source"] = source or "ai"
        deck["language"] = language
        deck["theme_color"] = theme_color
        deck["theme_accent"] = theme_accent
        deck["description"] = description
        deck["based_on_lesson"] = bool(lesson_context)
        deck.setdefault("grade", grade)
        deck.setdefault("subject", subject)
        deck.setdefault("topic", topic)
        deck.pop("note", None)
        return deck

    prompt = f"""
{brief_txt}
{teach}

Tạo dàn ý PowerPoint JSON để GIẢNG DẠY đúng môn {subject}, đúng CHỦ ĐỀ “{topic}” (slide đẹp, giảng được, ảnh sát từng slide):
{{
  "title": "...",
  "grade": "{grade}",
  "subject": "{subject}",
  "topic": "{topic}",
  "language": "{language}",
  "slides": [
    {{
      "layout": "title|content|two_column|table|cards|closing",
      "title": "...",
      "subtitle": "optional",
      "bullets": ["teaching bullets"],
      "left_title": "optional",
      "right_title": "optional",
      "left_bullets": ["..."],
      "right_bullets": ["..."],
      "table": {{"headers": ["A","B","C"], "rows": [["1","2","3"]]}},
      "image_keyword": "5-8 English nouns describing the EXACT scene of THIS slide, Vietnam school",
      "image_scene": "1 sentence: the exact photograph to generate (who, where, action), Vietnam school, matching THIS slide",
      "notes": "Vietnamese teacher notes: how to teach this slide, questions to ask, timing"
    }}
  ]
}}

Rules:
- Return exactly {min(slide_count, 7)} slides in THIS response (first part of a {slide_count}-slide deck).
- Do not write the closing slide yet unless {slide_count} <= 7.
- {lang_rule}
- Slide 1 layout=title. Closing slide only in the final batch.
- Include at least one layout=table, one layout=two_column, and one layout=cards.
- Content slides: 4–6 bullets, mỗi bullet 8–20 từ.
- two_column: 4 bullets mỗi cột.
- cards: 3–4 cards.
- table: 4–6 hàng sát nội dung.
{follow_lesson}- image_keyword MUST describe the photo of THAT slide only (derived from slide title + bullets), ưu tiên Việt Nam.
- image_scene: 1 câu cụ thể (ai, ở đâu, đang làm gì) để AI vẽ/chụp đúng nội dung slide, không generic.
  Ví dụ: chào cờ → "vietnam school flag raising ceremony students red flag yellow star";
  xếp hàng → "vietnamese students lining up schoolyard";
  quốc ca → "students singing vietnam national anthem";
  tôn trọng → "students saluting vietnam national flag".
- Cấm keyword chung: background, abstract, education, learning, template.
- Mỗi content slide có 1 ý kiến thức thật của “{topic}” (tên, sự kiện, công thức, nhân vật), không slogan trải nghiệm.
- Cấm bullet: hands-on exploration, create a mini product, I learned / I will apply, classroom roles (Leader/Recorder).
- Màu chủ đạo: {theme_color} / {theme_accent}.
{context_hint}
"""
    first_n = min(slide_count, 7)
    compact_pptx = (
        f"{brief_txt}\n{teach}\n"
        f"JSON PowerPoint giảng dạy môn {subject}, chủ đề “{topic}”, exactly {first_n} slides, short knowledge bullets, complete JSON.\n"
        '{"title":"...","slides":[{"layout":"title","title":"...","bullets":["..."],"notes":"..."}]}\n'
        "Slide 1 title. English on slide, Vietnamese notes. No experiential slogans."
    )
    try:
        data, source = _ask_studio_json(
            compact_pptx if light else prompt,
            system_en,
            max_tokens=2048 if light else 3072,
            timeout=30 if light else 40,
            compact_prompt=compact_pptx,
        )
        slides = (data or {}).get("slides") if data else None
        if not isinstance(slides, list):
            slides = []
        rounds = 0
        while (not light) and len(slides) < slide_count and rounds < 2:
            need = min(6, slide_count - len(slides))
            titles = [str(s.get("title") or "") for s in slides if isinstance(s, dict)]
            last_batch = len(slides) + need >= slide_count
            more, src2 = _ask_studio_json(
                f"""{brief_txt}
{teach}
Create exactly {need} MORE slides that TEACH more knowledge of “{topic}” in {subject}.
JSON: {{"slides":[...]}}.
Do not repeat these titles: {titles}.
Each slide = author / character / event / formula / definition of THIS topic — not classroom slogans.
English on-slide text, Vietnamese notes. Topic "{topic}".
{"The LAST slide must be layout=closing." if last_batch else "Do not use closing layout yet."}
Short bullets. Complete JSON, do not truncate.
""",
                system_en, max_tokens=3072, timeout=35,
            )
            extra = (more or {}).get("slides") if more else None
            if not isinstance(extra, list) or not extra:
                break
            slides.extend(extra)
            source = source or src2
            data = data or {"title": topic}
            rounds += 1
        normalized = _normalize_pptx_slides(slides, topic, language)
        normalized = _enrich_image_keywords(normalized, topic)
        normalized = _fit_slide_count(normalized, slide_count, topic, language, grade, subject)
        normalized = _scrub_generic_slides(
            normalized, _fallback_slides(grade, subject, topic, slide_count, language).get("slides") or [],
        )
        return _pack(data or {"title": topic}, source or "gemini", normalized)
    except Exception:
        current_app.logger.exception("generate_pptx_draft failed")
        try:
            compact, src = _ask_studio_json(compact_pptx, system_en, max_tokens=2048, timeout=30)
            slides = (compact or {}).get("slides") if compact else []
            normalized = _enrich_image_keywords(
                _normalize_pptx_slides(slides or [], topic, language), topic,
            )
            normalized = _fit_slide_count(normalized, slide_count, topic, language, grade, subject)
            normalized = _scrub_generic_slides(
                normalized, _fallback_slides(grade, subject, topic, slide_count, language).get("slides") or [],
            )
            return _pack(compact or {"title": topic}, src or "gemini", normalized)
        except Exception:
            current_app.logger.exception("generate_pptx_draft compact failed")
        fb = _fallback_slides(grade, subject, topic, slide_count, language)
        fb["theme_color"] = theme_color
        fb["theme_accent"] = theme_accent
        fb["description"] = description
        fb["based_on_lesson"] = bool(lesson_context)
        fb.pop("note", None)
        return fb


def _parse_timecode(value, default: float = 0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", ".")
    parts = raw.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return default
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 1:
        return nums[0]
    return default


def _normalize_subtitles(raw) -> list[dict]:
    out = []
    for i, line in enumerate(raw or []):
        if isinstance(line, str):
            text = line.strip()
            start = float(i * 6)
            end = start + 6
        elif isinstance(line, dict):
            text = str(line.get("text") or "").strip()
            start = _parse_timecode(line.get("start"), i * 6)
            end = _parse_timecode(line.get("end"), start + 6)
        else:
            continue
        if not text:
            continue
        if end <= start:
            end = start + 6
        out.append({"start": start, "end": end, "text": text})
    return out


normalize_subtitles = _normalize_subtitles
scrub_quiz_questions = _scrub_quiz_questions


def _mcq_items(raw, limit: int = 6) -> list[dict]:
    out = []
    for q in raw or []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or q.get("question_text") or "").strip()
        if not text:
            continue
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:4]
        if _is_generic_quiz_item({"question_text": text, "options": opts}):
            continue
        while len(opts) < 4:
            opts.append(f"Option {len(opts) + 1}")
        correct = str(q.get("correct_answer") or "").strip()
        if correct and correct not in opts:
            letter = correct[0].upper() if correct else ""
            if letter in "ABCD" and ord(letter) - 65 < len(opts):
                correct = opts[ord(letter) - 65]
            else:
                correct = next((o for o in opts if correct.lower() in o.lower()), opts[0])
        out.append({
            "question": text,
            "type": "multiple_choice",
            "options": opts,
            "correct_answer": correct or opts[0],
        })
        if len(out) >= limit:
            break
    return out


def _fallback_eight_step(grade: str, subject: str, topic: str, description: str = "") -> dict:
    lesson = _fallback_lesson(grade, subject, topic, "en", description)
    core_en = lesson.get("core_content_en") or lesson.get("core_content_vi") or topic
    vocab = []
    for v in (lesson.get("vocabulary") or [])[:6]:
        vocab.append({
            "word": v.get("term") or topic,
            "ipa": "",
            "meaning_vi": v.get("meaning_vi") or "",
            "example_sentence": v.get("example") or f"We study {topic}.",
            "category": "subject",
            "difficulty": "intermediate",
        })
    if not vocab:
        vocab = [{"word": topic, "ipa": "", "meaning_vi": topic, "example_sentence": f"Today: {topic}.", "category": "subject", "difficulty": "beginner"}]
    pairs = [{"left": v["word"], "right": v["meaning_vi"]} for v in vocab[:4]]
    if _is_kieu_topic(subject, topic):
        warm = [
            {
                "question": "Who wrote Truyện Kiều?",
                "type": "multiple_choice",
                "options": ["Nguyễn Du", "Nguyễn Trãi", "Hồ Xuân Hương", "Tố Hữu"],
                "correct_answer": "Nguyễn Du",
            },
            {
                "question": "Who is the heroine of Truyện Kiều?",
                "type": "multiple_choice",
                "options": ["Thúy Kiều", "Thúy Vân", "Hoạn Thư", "Kim Trọng"],
                "correct_answer": "Thúy Kiều",
            },
        ]
        read_qs = [
            {
                "question": "In which verse form is Truyện Kiều written?",
                "type": "multiple_choice",
                "options": ["lục bát", "song thất lục bát", "thơ tứ tuyệt", "prose only"],
                "correct_answer": "lục bát",
            },
            {
                "question": "Why does Thúy Kiều sell herself?",
                "type": "multiple_choice",
                "options": ["To save her father", "To marry Kim Trọng", "To flee Hoạn Thư", "To study abroad"],
                "correct_answer": "To save her father",
            },
        ]
    else:
        warm = [
            {
                "question": f"Which subject are we studying today?",
                "type": "multiple_choice",
                "options": [subject, "Experiential Learning only", "Unrelated topic", "Free time"],
                "correct_answer": subject,
            },
            {
                "question": f"What is today's topic in {subject}?",
                "type": "multiple_choice",
                "options": [topic, "A random slogan", "Skip the lesson", "No topic"],
                "correct_answer": topic,
            },
        ]
        read_qs = [
            {
                "question": f"The passage is mainly about which topic?",
                "type": "multiple_choice",
                "options": [topic, "Classroom rules only", "Unrelated skills", "No main idea"],
                "correct_answer": topic,
            },
            {
                "question": f"This lesson belongs to which subject?",
                "type": "multiple_choice",
                "options": [subject, "Math only", "PE only", "None"],
                "correct_answer": subject,
            },
        ]
    return {
        "title": f"{subject}: {topic}",
        "description": description or f"GDPT 2018 · {grade} · {subject} · {topic}.",
        "duration_minutes": 45,
        "warm_up": {"questions": warm},
        "vocabulary": vocab,
        "reading": {
            "passage": core_en if len(str(core_en)) > 40 else (
                f"In {grade} {subject}, students study “{topic}”. "
                f"They learn key terms and facts, practise exercises, then apply the knowledge."
            ),
            "translation": lesson.get("core_content_vi") or f"Bài học môn {subject} về “{topic}” theo GDPT 2018.",
            "questions": read_qs,
        },
        "video": {
            "video_prompt": f"Classroom video: {grade} students learning {topic} in {subject} (English medium).",
            "subtitles": [
                {"start": 0, "end": 8, "text": f"Today: {topic} in {subject}."},
                {"start": 8, "end": 16, "text": "Read, practise, then apply the knowledge."},
            ],
        },
        "interactive": {
            "activities": [{
                "type": "matching",
                "title": f"Match {subject} terms: {topic}",
                "description": "Match each English term with its Vietnamese meaning.",
                "pairs": pairs,
            }]
        },
        "practice": {
            "instructions": (
                f"Complete a short {subject} exercise on “{topic}” (GDPT 2018 practice stage). "
                f"Write 5–8 English sentences using at least 4 vocabulary words from the lesson."
            ),
            "allow_upload": True,
        },
        "reflection": {
            "instructions": (
                f"Write 80–120 words in English: two key facts you learned about “{topic}” in {subject}, "
                "and one way to apply them in a school task."
            ),
        },
        "quiz": {
            "title": f"Quiz: {topic}",
            "time_limit_minutes": 20,
            "passing_score": 60,
            "questions": _fallback_quiz(
                grade, subject, topic, 8,
                ["multiple_choice", "true_false", "fill_blank", "essay"],
                "en",
            )["questions"],
        },
        "source": "template",
        "language": "en",
    }


def _as_int(val, default: int) -> int:
    try:
        if val is None or isinstance(val, (list, dict, bool)):
            return default
        token = str(val).strip().split()[0].replace(",", ".")
        return int(float(token))
    except Exception:
        return default


def _normalize_eight_step(data: dict, grade: str, subject: str, topic: str, description: str = "") -> dict:
    fb = _fallback_eight_step(grade, subject, topic, description)
    if not isinstance(data, dict):
        return fb
    warm = data.get("warm_up") if isinstance(data.get("warm_up"), dict) else {}
    reading = data.get("reading") if isinstance(data.get("reading"), dict) else {}
    video = data.get("video") if isinstance(data.get("video"), dict) else {}
    interactive = data.get("interactive") if isinstance(data.get("interactive"), dict) else {}
    practice = data.get("practice") if isinstance(data.get("practice"), dict) else {}
    reflection = data.get("reflection") if isinstance(data.get("reflection"), dict) else {}
    quiz = data.get("quiz") if isinstance(data.get("quiz"), dict) else {}
    vocab = []
    for v in data.get("vocabulary") or []:
        if not isinstance(v, dict):
            continue
        word = str(v.get("word") or v.get("term") or "").strip()
        if not word:
            continue
        vocab.append({
            "word": word,
            "ipa": str(v.get("ipa") or ""),
            "meaning_vi": str(v.get("meaning_vi") or v.get("meaning") or ""),
            "example_sentence": str(v.get("example_sentence") or v.get("example") or ""),
            "category": str(v.get("category") or "school_life"),
            "difficulty": str(v.get("difficulty") or "beginner"),
        })
    activities = []
    for act in interactive.get("activities") or []:
        if isinstance(act, dict) and act.get("type"):
            activities.append(act)
    if not activities:
        activities = fb["interactive"]["activities"]
    from app.routes.quizzes import normalize_quiz_questions
    eight_types = ["multiple_choice", "true_false", "fill_blank", "essay"]
    quiz_qs = _scrub_quiz_questions(
        normalize_quiz_questions(quiz.get("questions") or []),
        grade, subject, topic, 8, eight_types,
    )
    if len(quiz_qs) < 4:
        quiz_qs = _scrub_quiz_questions(
            fb["quiz"]["questions"], grade, subject, topic, 8, eight_types,
        )
    out = {
        "title": str(data.get("title") or topic)[:160],
        "description": str(data.get("description") or description or fb["description"])[:800],
        "duration_minutes": _as_int(data.get("duration_minutes"), 45),
        "warm_up": {"questions": _mcq_items(warm.get("questions") or fb["warm_up"]["questions"], 6)},
        "vocabulary": vocab or fb["vocabulary"],
        "reading": {
            "passage": str(reading.get("passage") or fb["reading"]["passage"]),
            "translation": str(reading.get("translation") or fb["reading"]["translation"]),
            "questions": _mcq_items(reading.get("questions") or fb["reading"]["questions"], 6),
        },
        "video": {
            "video_prompt": str(video.get("video_prompt") or fb["video"]["video_prompt"]),
            "subtitles": _normalize_subtitles(video.get("subtitles") or fb["video"]["subtitles"]),
        },
        "interactive": {"activities": activities[:3]},
        "practice": {
            "instructions": str(practice.get("instructions") or fb["practice"]["instructions"]),
            "allow_upload": True,
        },
        "reflection": {
            "instructions": str(reflection.get("instructions") or fb["reflection"]["instructions"]),
        },
        "quiz": {
            "title": str(quiz.get("title") or f"Quiz: {topic}"),
            "time_limit_minutes": _as_int(quiz.get("time_limit_minutes"), 20),
            "passing_score": _as_int(quiz.get("passing_score"), 60),
            "questions": quiz_qs,
        },
        "source": data.get("source") or "ai",
        "language": "en",
        "grade": grade,
        "subject": subject,
        "topic": topic,
    }
    return out


def generate_eight_step_draft(
    grade: str,
    subject: str,
    topic: str,
    description: str = "",
    extra_requirements: str = "",
    lesson_context: dict | None = None,
    quiz_context: dict | None = None,
    light: bool = False,
) -> dict:
    teach = _teaching_content_rules(grade, subject, topic)
    brief = _teacher_brief(
        grade=grade, subject=subject, topic=topic, language="en",
        description=description, extra_requirements=extra_requirements,
    )
    hint = ""
    if isinstance(lesson_context, dict):
        title = lesson_context.get("title_en") or lesson_context.get("title_vi") or ""
        objs = (lesson_context.get("objectives_en") or lesson_context.get("objectives_vi") or [])[:3]
        if title or objs:
            hint = f"Follow this lesson: {title}. Objectives: {'; '.join(str(x) for x in objs)}.\n"
    system = SYSTEM_EIGHT_STEP
    if _is_math_topic(subject, topic):
        system = SYSTEM_EIGHT_STEP + " " + SYSTEM_MATH_EXAM

    def _ask(prompt_text: str) -> dict | None:
        data, _src = _ask_studio_json(
            prompt_text, system, max_tokens=3072, timeout=35,
        )
        return data

    compact_eight = f"""
{brief}
{teach}
Compact 8-step JSON (GDPT 2018 subject content): title, warm_up 3 MCQs on "{topic}", 4–6 subject vocabulary,
reading 90–130 words on "{topic}" + 2 MCQs, matching 4 pairs, practice = subject exercise, quiz 4 items.
Complete JSON, do not truncate.
"""
    if light:
        try:
            retry, src = _ask_studio_json(compact_eight, system, max_tokens=2048, timeout=30)
            out = _normalize_eight_step(retry or {}, grade, subject, topic, description)
            out["source"] = "gemini" if retry else "template"
            out.pop("note", None)
            return out
        except Exception:
            current_app.logger.exception("generate_eight_step_draft light failed")
            out = _normalize_eight_step({}, grade, subject, topic, description)
            out["source"] = "template"
            out.pop("note", None)
            return out

    try:
        part1 = _ask(f"""
{brief}
{teach}
{hint}
Create the FIRST HALF of an 8-step lesson. JSON only:
{{
  "title": "English title",
  "description": "2 short English sentences",
  "duration_minutes": 45,
  "warm_up": {{"questions": [{{"question":"...","options":["A","B","C","D"],"correct_answer":"A"}}]}},
  "vocabulary": [{{"word":"...","ipa":"/.../","meaning_vi":"...","example_sentence":"..."}}],
  "reading": {{
    "passage": "90-130 English words: subject knowledge of this topic (GDPT 2018), not generic experiential text",
    "translation": "Vietnamese translation",
    "questions": [{{"question":"...","options":["A","B","C","D"],"correct_answer":"A"}}]
  }},
  "video": {{
    "video_prompt": "classroom video the teacher should film",
    "subtitles": [{{"start":"00:00:00","end":"00:00:08","text":"English line"}}]
  }}
}}
Rules: warm_up 3 MCQs, vocabulary 6 words, reading 3 MCQs, 2 subtitle lines. Exact topic "{topic}".
""")
        quiz_hint = ""
        if isinstance(quiz_context, dict) and quiz_context.get("questions"):
            quiz_hint = "Write a NEW 6-item quiz on the same topic (do not copy placeholders).\n"
        part2 = _ask(f"""
{brief}
{teach}
{hint}{quiz_hint}
Create the SECOND HALF of the 8-step lesson. JSON only:
{{
  "interactive": {{"activities": [{{"type":"matching","title":"...","description":"...","pairs":[{{"left":"EN","right":"VI"}}]}}]}},
  "practice": {{"instructions": "English instructions for a {subject} exercise on '{topic}' (practice stage)"}},
  "reflection": {{"instructions": "English writing: 2 facts learned + 1 application of '{topic}' in {subject}"}},
  "quiz": {{
    "title": "Quiz: {topic}",
    "time_limit_minutes": 20,
    "passing_score": 60,
    "questions": [
      {{"question_text":"...","question_type":"multiple_choice","options":["A. ...","B. ...","C. ...","D. ..."],"correct_answer":"A. ...","explanation":"...","points":1}}
    ]
  }}
}}
Rules: 4 matching pairs. Quiz 6 English items: 4 MCQ + 1 true_false (options True/False) + 1 essay.
{_quiz_subject_rules(grade, subject, topic)}
FORBIDDEN: “Khái niệm nào liên quan đến {topic}?”, “Which sentence best describes {topic}?”,
“Nội dung đúng về / Khái niệm không liên quan / Thông tin sai / Không có đáp án”.
""")
        data: dict = {}
        if part1:
            data.update(part1)
        if part2:
            data.update(part2)
        out = _normalize_eight_step(data, grade, subject, topic, description)
        if part1 or part2:
            out["source"] = "gemini"
            out.pop("note", None)
        else:
            retry, _src = _ask_studio_json(
                compact_eight, system, max_tokens=2048, timeout=30,
            )
            out = _normalize_eight_step(retry or {}, grade, subject, topic, description)
            if retry:
                out["source"] = "gemini"
                out.pop("note", None)
            else:
                out["source"] = "template"
                out.pop("note", None)
        return out
    except Exception:
        current_app.logger.exception("generate_eight_step_draft failed")
        try:
            retry, src = _ask_studio_json(compact_eight, system, max_tokens=2048, timeout=25)
            out = _normalize_eight_step(retry or {}, grade, subject, topic, description)
            out["source"] = "gemini" if retry else "template"
            out.pop("note", None)
            return out
        except Exception:
            out = _normalize_eight_step({}, grade, subject, topic, description)
            out["source"] = "template"
            out.pop("note", None)
            return out


def build_docx_bytes(lesson: dict) -> bytes:
    from app.services.docx_builder import build_rich_docx_bytes
    return build_rich_docx_bytes(lesson)


def build_pptx_bytes(deck: dict, light: bool = False) -> bytes:
    from app.services.pptx_builder import build_rich_pptx_bytes
    payload = dict(deck or {})
    if light:
        payload["light"] = True
    return build_rich_pptx_bytes(payload)


def quiz_to_docx_bytes(quiz: dict) -> bytes:
    from app.services.docx_builder import build_quiz_docx_bytes
    return build_quiz_docx_bytes(quiz)
