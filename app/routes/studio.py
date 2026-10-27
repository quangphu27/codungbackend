"""Teacher Studio API — AI draft + export DOCX/PPTX."""
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import io
import os
import re
import unicodedata

from app.extensions import get_db
from app.middlewares.auth import teacher_required, admin_required
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.services import studio_service

studio_bp = Blueprint("studio", __name__)


def _safe_download_name(raw: str, fallback: str, ext: str) -> str:
    text = unicodedata.normalize("NFKD", str(raw or fallback))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or fallback
    if not text.lower().endswith(ext):
        text = f"{text[:40]}{ext}"
    return text[:80]


def _quiz_types(data: dict) -> list:
    raw = data.get("quiz_types") or data.get("question_types") or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    allowed = {"multiple_choice", "true_false", "fill_blank", "essay"}
    alias = {
        "mcq": "multiple_choice",
        "trac nghiem": "multiple_choice",
        "trắc nghiệm": "multiple_choice",
        "dung sai": "true_false",
        "đúng/sai": "true_false",
        "true_false": "true_false",
        "dien khuyet": "fill_blank",
        "điền khuyết": "fill_blank",
        "tu luan": "essay",
        "tự luận": "essay",
        "short_answer": "essay",
    }
    out = []
    for item in raw:
        key = str(item).strip().lower()
        mapped = alias.get(key, key.replace(" ", "_"))
        if mapped in allowed and mapped not in out:
            out.append(mapped)
    return out or ["multiple_choice"]


def _text(val, default=""):
    if val is None or isinstance(val, (dict, list)):
        return default
    return str(val).strip()


def _int(val, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(n, hi))


def _book_reference_from_body(data: dict) -> dict | None:
    br = data.get("book_reference")
    if not isinstance(br, dict):
        return None
    text = br.get("text") if isinstance(br.get("text"), str) else ""
    images = []
    raw_imgs = br.get("images")
    if isinstance(raw_imgs, list):
        for img in raw_imgs[:8]:
            if isinstance(img, dict) and img.get("data"):
                images.append({
                    "mime": img.get("mime") or "image/jpeg",
                    "data": img["data"],
                })
    if not text.strip() and not images:
        return None
    return {
        "text": text,
        "images": images,
        "filenames": br.get("filenames") if isinstance(br.get("filenames"), list) else [],
        "image_count": len(images),
        "has_text": bool(text.strip()),
    }


def _base_payload():
    data = request.get_json() or {}
    return {
        "grade": _text(data.get("grade"), "Lớp 6") or "Lớp 6",
        "subject": _text(data.get("subject"), "Ngữ văn") or "Ngữ văn",
        "topic": _text(data.get("topic")),
        "description": _text(data.get("description") or data.get("mo_ta")),
        "language": _text(data.get("language"), "bilingual") or "bilingual",
        # kinds use fixed languages: lesson bilingual, quiz English, slides EN + notes VI
        "extra_requirements": _text(data.get("extra_requirements") or data.get("requirements")),
        "theme_color": _text(data.get("theme_color") or data.get("primary_color"), "#0F2744") or "#0F2744",
        "theme_accent": _text(data.get("theme_accent") or data.get("accent_color"), "#F39C4A") or "#F39C4A",
        "quiz_types": _quiz_types(data),
        "quiz_requirements": _text(data.get("quiz_requirements")),
        "num_questions": _int(data.get("num_questions", 10), 10, 4, 20),
        "difficulty": _text(data.get("difficulty"), "mixed") or "mixed",
        "slide_count": _int(data.get("slide_count", 10), 10, 6, 20),
        "lesson": data.get("lesson") if isinstance(data.get("lesson"), dict) else None,
        "quiz": data.get("quiz") if isinstance(data.get("quiz"), dict) else None,
        "deck": data.get("deck") if isinstance(data.get("deck"), dict) else None,
        "save": bool(data.get("save", True)),
        "light": bool(data.get("light")),
        "book_reference": _book_reference_from_body(data),
        "teacher_english_level": _text(data.get("teacher_english_level"), "A2") or "A2",
        "student_english_level": _text(data.get("student_english_level"), "A2") or "A2",
        "class_size": _text(data.get("class_size")),
        "equipment": _text(data.get("equipment")),
        "duration_minutes": _int(data.get("duration_minutes", 45), 45, 35, 90),
        "presentation_language": _text(data.get("presentation_language"), "english") or "english",
        "pptx_detail": _text(data.get("pptx_detail"), "balanced") or "balanced",
        "worksheet_purpose": _text(data.get("worksheet_purpose"), "explore") or "explore",
        "worksheet_duration": _int(data.get("worksheet_duration", 15), 15, 5, 45),
        "worksheet_language_mode": _text(data.get("worksheet_language_mode"), "english") or "english",
        "worksheet_working_mode": _text(data.get("worksheet_working_mode"), "pair") or "pair",
        "worksheet_difficulty": _text(data.get("worksheet_difficulty"), "standard") or "standard",
        "worksheet": data.get("worksheet") if isinstance(data.get("worksheet"), dict) else None,
    }


def _call_or_light(payload: dict, make, fallback):
    light = bool(payload.get("light"))
    try:
        return make(light)
    except Exception:
        from flask import current_app
        current_app.logger.exception("studio generate failed")
        if not light:
            try:
                return make(True)
            except Exception:
                current_app.logger.exception("studio generate light retry failed")
        return fallback()


def _attach_studio_file_cache(content: dict, cache_kind: str, *, light: bool = False) -> dict:
    """Sau khi AI tạo nội dung JSON, build file Word/PPTX và lưu Cloudinary."""
    if not content or not isinstance(content, dict):
        return content
    from app.services.studio_files import ensure_studio_file

    topic = content.get("topic") or ""
    if cache_kind == "lesson_docx":
        filename = _safe_download_name(topic, "giao_an", ".docx")
        if not filename.startswith("giao_an"):
            filename = f"giao_an_{filename}"
        cache_payload = content
        builder = lambda: studio_service.build_docx_bytes(content)
    elif cache_kind == "quiz_docx":
        filename = _safe_download_name(topic, "de_kiem_tra", ".docx")
        if not filename.startswith("de_"):
            filename = f"de_kiem_tra_{filename}"
        cache_payload = content
        builder = lambda: studio_service.quiz_to_docx_bytes(content)
    elif cache_kind == "pptx":
        filename = _safe_download_name(topic, "slide", ".pptx")
        if not filename.startswith("slide"):
            filename = f"slide_{filename}"
        cache_payload = {**content, "light": light}

        def builder():
            try:
                return studio_service.build_pptx_bytes(content, light=light)
            except Exception:
                from flask import current_app
                current_app.logger.exception("studio pptx cache build failed, retry light")
                return studio_service.build_pptx_bytes(content, light=True)

    else:
        return content

    meta = ensure_studio_file(cache_kind, cache_payload, filename, builder)
    if not meta.get("file_url"):
        return content
    out = dict(content)
    out.update({k: v for k, v in meta.items() if v is not None})
    if cache_kind == "pptx":
        out["light"] = light
    return out


def _send_cached_studio_file(
    kind: str,
    payload: dict,
    filename: str,
    mime: str,
    *,
    builder=None,
    cache_kind: str | None = None,
):
    from app.services.studio_files import fetch_studio_file_bytes

    blob = fetch_studio_file_bytes(kind, payload)
    if not blob and builder:
        try:
            blob = builder()
        except Exception:
            from flask import current_app
            current_app.logger.exception("studio export build failed kind=%s", kind)
            blob = None
    if not blob:
        return jsonify({
            "message": (
                "Không tạo được file. Thử bấm Tạo lại nội dung rồi tải xuống lần nữa."
            ),
        }), 500
    if cache_kind and builder:
        try:
            _attach_studio_file_cache(payload, cache_kind)
        except Exception:
            from flask import current_app
            current_app.logger.exception("studio export cache after build kind=%s", kind)
    return send_file(
        io.BytesIO(blob),
        mimetype=mime,
        as_attachment=True,
        download_name=filename,
    )


def _save_draft(db, user_id, kind: str, payload: dict, result: dict):
    doc = {
        "teacher_id": user_id,
        "kind": kind,
        "grade": payload["grade"],
        "subject": payload["subject"],
        "topic": payload["topic"],
        "content": result,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    inserted = db.studio_drafts.insert_one(doc)
    doc["_id"] = inserted.inserted_id
    return serialize_doc(doc)


@studio_bp.route("/book-reference", methods=["POST"])
@jwt_required()
@teacher_required
def upload_book_reference():
    """Ảnh trang sách + PDF/Word — AI đọc để bám đúng bài khi tạo giáo án/đề/slide."""
    from app.services.studio_reference import process_reference_uploads

    uploads = request.files.getlist("files")
    if not uploads or all(not (u and u.filename) for u in uploads):
        single = request.files.get("file")
        uploads = [single] if single and single.filename else []
    if not uploads:
        return jsonify({"message": "Chọn ít nhất một ảnh trang sách hoặc file PDF/Word."}), 400
    try:
        ref = process_reference_uploads(uploads)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception:
        from flask import current_app
        current_app.logger.exception("book-reference upload")
        return jsonify({"message": "Không xử lý được tài liệu. Thử lại hoặc dùng ảnh/PDF khác."}), 500

    names = ref.get("filenames") or []
    parts = []
    if ref.get("image_count"):
        parts.append(f"{ref['image_count']} ảnh")
    if ref.get("has_text"):
        parts.append("đã trích chữ từ PDF/Word")
    summary = ", ".join(parts) if parts else "Đã nhận tài liệu"
    if names:
        summary = f"{summary} ({', '.join(names[:4])}{'…' if len(names) > 4 else ''})"
    return jsonify({"book_reference": ref, "summary": summary})


@studio_bp.route("/status", methods=["GET"])
@jwt_required()
@teacher_required
def studio_status():
    from app.services.secret_store import gemini_is_configured

    configured = gemini_is_configured()
    return jsonify({
        "gemini_configured": configured,
        "message": (
            "AI đã sẵn sàng"
            if configured
            else "Chưa có API key Gemini. Admin hãy nhập key tại Cài đặt AI."
        ),
    })


@studio_bp.route("/generate/lesson", methods=["POST"])
@jwt_required()
@teacher_required
def generate_lesson():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    def _make_lesson(light):
        return studio_service.generate_lesson_draft(
            grade=payload["grade"],
            subject=payload["subject"],
            topic=payload["topic"],
            language=payload["language"],
            extra_requirements=payload["extra_requirements"],
            description=payload["description"],
            theme_color=payload["theme_color"],
            theme_accent=payload["theme_accent"],
            light=light,
            book_reference=payload.get("book_reference"),
            teacher_english_level=payload.get("teacher_english_level"),
            student_english_level=payload.get("student_english_level"),
            class_size=payload.get("class_size") or "",
            equipment=payload.get("equipment") or "",
            duration_minutes=payload.get("duration_minutes"),
        )

    def _fallback_lesson():
        lesson = studio_service._fallback_lesson(
            payload["grade"], payload["subject"], payload["topic"],
            "bilingual", payload["description"],
        )
        lesson["source"] = "template"
        lesson.pop("note", None)
        lesson["theme_color"] = payload["theme_color"]
        lesson["theme_accent"] = payload["theme_accent"]
        return lesson

    lesson = _call_or_light(payload, _make_lesson, _fallback_lesson)
    # Word build khi bấm Tải — tránh timeout lúc generate (giống PowerPoint).

    draft = None
    if payload["save"]:
        try:
            db = get_db()
            user_id = to_object_id(get_jwt_identity())
            draft = _save_draft(db, user_id, "lesson", payload, lesson)
        except Exception:
            from flask import current_app
            current_app.logger.exception("save lesson draft")
            draft = None

    return jsonify({"lesson": lesson, "draft": draft})


@studio_bp.route("/generate/quiz", methods=["POST"])
@jwt_required()
@teacher_required
def generate_quiz():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    def _make_quiz(light):
        return studio_service.generate_quiz_draft(
            grade=payload["grade"],
            subject=payload["subject"],
            topic=payload["topic"],
            num_questions=payload["num_questions"],
            difficulty=payload["difficulty"],
            language=payload["language"],
            description=payload["description"],
            extra_requirements=payload["extra_requirements"],
            quiz_types=payload["quiz_types"],
            quiz_requirements=payload["quiz_requirements"],
            theme_color=payload["theme_color"],
            theme_accent=payload["theme_accent"],
            light=light,
            book_reference=payload.get("book_reference"),
        )

    def _fallback_quiz():
        quiz = studio_service._fallback_quiz(
            payload["grade"], payload["subject"], payload["topic"],
            payload["num_questions"], payload["quiz_types"], "en",
        )
        quiz["source"] = "practice"
        quiz.pop("note", None)
        quiz["theme_color"] = payload["theme_color"]
        quiz["theme_accent"] = payload["theme_accent"]
        return quiz

    quiz = _call_or_light(payload, _make_quiz, _fallback_quiz)

    draft = None
    if payload["save"]:
        try:
            db = get_db()
            user_id = to_object_id(get_jwt_identity())
            draft = _save_draft(db, user_id, "quiz", payload, quiz)
        except Exception:
            from flask import current_app
            current_app.logger.exception("save quiz draft")
            draft = None

    return jsonify({"quiz": quiz, "draft": draft})


@studio_bp.route("/generate/pptx", methods=["POST"])
@jwt_required()
@teacher_required
def generate_pptx():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    def _make_pptx(light):
        return studio_service.generate_pptx_draft(
            grade=payload["grade"],
            subject=payload["subject"],
            topic=payload["topic"],
            slide_count=payload["slide_count"],
            lesson_context=payload.get("lesson"),
            language=payload["language"],
            description=payload["description"],
            extra_requirements=payload["extra_requirements"],
            theme_color=payload["theme_color"],
            theme_accent=payload["theme_accent"],
            light=light,
            book_reference=payload.get("book_reference"),
            teacher_english_level=payload.get("teacher_english_level"),
            student_english_level=payload.get("student_english_level"),
            duration_minutes=payload.get("duration_minutes"),
            presentation_language=payload.get("presentation_language"),
            pptx_detail=payload.get("pptx_detail"),
        )

    def _fallback_pptx():
        deck = studio_service._fallback_slides(
            payload["grade"], payload["subject"], payload["topic"],
            payload["slide_count"], "en",
        )
        deck["theme_color"] = payload["theme_color"]
        deck["theme_accent"] = payload["theme_accent"]
        deck["description"] = payload["description"]
        deck.pop("note", None)
        return deck

    deck = _call_or_light(payload, _make_pptx, _fallback_pptx)
    # Không build PPTX + ảnh AI lúc generate (dễ timeout) — file tạo khi bấm Tải slide.

    draft = None
    if payload["save"]:
        try:
            db = get_db()
            user_id = to_object_id(get_jwt_identity())
            draft = _save_draft(db, user_id, "pptx", payload, deck)
        except Exception:
            from flask import current_app
            current_app.logger.exception("save pptx draft")
            draft = None

    return jsonify({"deck": deck, "draft": draft})


@studio_bp.route("/generate/worksheet", methods=["POST"])
@jwt_required()
@teacher_required
def generate_worksheet():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    def _make_ws(light):
        return studio_service.generate_worksheet_draft(
            grade=payload["grade"],
            subject=payload["subject"],
            topic=payload["topic"],
            description=payload["description"],
            extra_requirements=payload["extra_requirements"],
            lesson_context=payload.get("lesson"),
            deck_context=payload.get("deck"),
            book_reference=payload.get("book_reference"),
            teacher_english_level=payload.get("teacher_english_level"),
            student_english_level=payload.get("student_english_level"),
            worksheet_purpose=payload.get("worksheet_purpose"),
            worksheet_duration=payload.get("worksheet_duration"),
            language_mode=payload.get("worksheet_language_mode"),
            working_mode=payload.get("worksheet_working_mode"),
            difficulty=payload.get("worksheet_difficulty"),
            theme_color=payload["theme_color"],
            theme_accent=payload["theme_accent"],
            light=light,
        )

    def _fallback_ws():
        from app.services.studio_worksheet_clil import fallback_worksheet
        ws = fallback_worksheet(
            payload["grade"], payload["subject"], payload["topic"],
            payload.get("worksheet_purpose") or "explore",
        )
        ws["theme_color"] = payload["theme_color"]
        ws["theme_accent"] = payload["theme_accent"]
        return ws

    worksheet = _call_or_light(payload, _make_ws, _fallback_ws)
    draft = None
    if payload["save"]:
        try:
            db = get_db()
            user_id = to_object_id(get_jwt_identity())
            draft = _save_draft(db, user_id, "worksheet", payload, worksheet)
        except Exception:
            from flask import current_app
            current_app.logger.exception("save worksheet draft")
            draft = None
    return jsonify({"worksheet": worksheet, "draft": draft})


@studio_bp.route("/export/worksheet-student-docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_worksheet_student_docx():
    payload = _base_payload()
    ws = payload.get("worksheet")
    if not ws:
        return jsonify({"message": "Thiếu phiếu học tập (worksheet)"}), 400
    blob = studio_service.worksheet_student_docx_bytes(ws)
    filename = _safe_download_name(ws.get("topic"), "phieu_hoc_tap", ".docx")
    if not filename.startswith("phieu"):
        filename = f"phieu_hoc_tap_{filename}"
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@studio_bp.route("/export/worksheet-teacher-docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_worksheet_teacher_docx():
    payload = _base_payload()
    ws = payload.get("worksheet")
    if not ws:
        return jsonify({"message": "Thiếu phiếu học tập (worksheet)"}), 400
    blob = studio_service.worksheet_teacher_docx_bytes(ws)
    filename = _safe_download_name(ws.get("topic"), "huong_dan_phieu", ".docx")
    if "huong_dan" not in filename:
        filename = f"huong_dan_phieu_{filename}"
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@studio_bp.route("/generate/eight-step", methods=["POST"])
@jwt_required()
@teacher_required
def generate_eight_step():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400
    def _make_eight(light):
        return studio_service.generate_eight_step_draft(
            grade=payload["grade"],
            subject=payload["subject"],
            topic=payload["topic"],
            description=payload["description"],
            extra_requirements=payload["extra_requirements"],
            lesson_context=payload.get("lesson"),
            quiz_context=payload.get("quiz"),
            light=light,
            book_reference=payload.get("book_reference"),
        )

    def _fallback_eight():
        eight = studio_service._normalize_eight_step(
            {}, payload["grade"], payload["subject"], payload["topic"], payload["description"],
        )
        eight["source"] = "template"
        eight.pop("note", None)
        return eight

    eight = _call_or_light(payload, _make_eight, _fallback_eight)
    draft = None
    if payload["save"]:
        try:
            db = get_db()
            user_id = to_object_id(get_jwt_identity())
            draft = _save_draft(db, user_id, "eight_step", payload, eight)
        except Exception:
            from flask import current_app
            current_app.logger.exception("save eight-step draft")
            draft = None
    return jsonify({"eight_step": eight, "draft": draft})


@studio_bp.route("/save-eight-step", methods=["POST"])
@jwt_required()
@teacher_required
def save_eight_step():
    """Lưu bài học 8 bước (bản nháp) giống /teacher/lessons — có thể sửa tiếp."""
    from app.routes.lessons import SECTION_TYPES
    from app.routes.quizzes import _replace_lesson_quiz, normalize_quiz_questions

    data = request.get_json() or {}
    eight = data.get("eight_step") or data.get("content")
    if not isinstance(eight, dict):
        return jsonify({"message": "Thiếu nội dung bài học 8 bước"}), 400

    class_id = data.get("class_id")
    subject_id = data.get("subject_id")
    if not class_id or not subject_id:
        return jsonify({"message": "Chọn lớp học và môn học trước khi lưu"}), 400

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    class_oid = to_object_id(class_id)
    subject_oid = to_object_id(subject_id)
    if not class_oid:
        return jsonify({"message": "Lớp học không hợp lệ"}), 400
    if not subject_oid:
        return jsonify({"message": "Môn học không hợp lệ"}), 400
    cls = db.classes.find_one({"_id": class_oid})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404
    if not db.subjects.find_one({"_id": subject_oid}):
        return jsonify({"message": "Không tìm thấy môn học"}), 404
    owner = cls.get("teacher_id")
    role = get_jwt().get("role", "teacher")
    if role != "super_admin" and str(owner) != str(teacher_id):
        return jsonify({"message": "Bạn không có quyền lưu vào lớp này"}), 403

    title = (eight.get("title") or data.get("topic") or "Lesson").strip()
    try:
        duration = int(eight.get("duration_minutes") or 45)
    except (TypeError, ValueError):
        duration = 45
    try:
        order = int(data.get("order") or 1)
    except (TypeError, ValueError):
        order = 1
    video = eight.get("video") if isinstance(eight.get("video"), dict) else {}
    video = {
        **video,
        "subtitles": studio_service.normalize_subtitles(video.get("subtitles")),
    }
    lesson = {
        "title": title,
        "description": (eight.get("description") or data.get("description") or "").strip(),
        "class_id": class_oid,
        "subject_id": subject_oid,
        "teacher_id": teacher_id,
        "thumbnail": None,
        "order": order,
        "status": "draft",
        "featured": False,
        "duration_minutes": duration,
        "source": eight.get("source") or "ai",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    lesson_id = db.lessons.insert_one(lesson).inserted_id

    section_content = {
        "warm_up": eight.get("warm_up") or {},
        "vocabulary": {},
        "reading": eight.get("reading") or {},
        "video": video,
        "interactive": eight.get("interactive") or {},
        "practice": eight.get("practice") or {},
        "reflection": eight.get("reflection") or {},
        "quiz": {},
    }
    section_ids = {}
    for i, section_type in enumerate(SECTION_TYPES):
        content = section_content.get(section_type) or {}
        filled = bool(content) and any(v not in (None, "", [], {}) for v in (content.values() if isinstance(content, dict) else [content]))
        if section_type in ("vocabulary", "quiz"):
            filled = False
        inserted = db.lesson_sections.insert_one({
            "lesson_id": lesson_id,
            "section_type": section_type,
            "title": section_type.replace("_", " ").title(),
            "content": content if section_type not in ("vocabulary", "quiz") else {},
            "order": i + 1,
            "status": "completed" if filled else "empty",
            "created_at": utc_now(),
        })
        section_ids[section_type] = str(inserted.inserted_id)

    for v in eight.get("vocabulary") or []:
        if not isinstance(v, dict) or not str(v.get("word") or "").strip():
            continue
        db.vocabularies.insert_one({
            "word": str(v.get("word") or "").strip(),
            "ipa": str(v.get("ipa") or ""),
            "pronunciation_audio": None,
            "meaning_vi": str(v.get("meaning_vi") or ""),
            "example_sentence": str(v.get("example_sentence") or ""),
            "example_translation": "",
            "image": None,
            "category": str(v.get("category") or "school_life"),
            "difficulty": str(v.get("difficulty") or "beginner"),
            "lesson_id": lesson_id,
            "created_by": teacher_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })

    quiz_block = eight.get("quiz") or {}
    questions = normalize_quiz_questions(quiz_block.get("questions") or [])
    quiz_id = None
    if questions:
        quiz_data, err = _replace_lesson_quiz(
            db,
            str(lesson_id),
            teacher_id,
            {
                "title": quiz_block.get("title") or f"Quiz: {title}",
                "class_id": str(class_oid),
                "time_limit_minutes": quiz_block.get("time_limit_minutes") or 20,
                "passing_score": quiz_block.get("passing_score") or 60,
                "questions": questions,
                "source": eight.get("source") or "ai",
                "language": "en",
                "randomize": False,
            },
            role=role,
        )
        if not err:
            quiz_id = quiz_data.get("id")
            db.lesson_sections.update_one(
                {"lesson_id": lesson_id, "section_type": "quiz"},
                {"$set": {"status": "completed", "updated_at": utc_now()}},
            )

    if eight.get("vocabulary"):
        db.lesson_sections.update_one(
            {"lesson_id": lesson_id, "section_type": "vocabulary"},
            {"$set": {"status": "completed", "updated_at": utc_now()}},
        )

    db.classes.update_one({"_id": class_oid}, {"$addToSet": {"lesson_ids": lesson_id}})

    lesson["_id"] = lesson_id
    return jsonify({
        "message": "Đã lưu bài học 8 bước (bản nháp). Có thể chỉnh sửa tiếp.",
        "lesson": serialize_doc(lesson),
        "section_ids": section_ids,
        "quiz_id": quiz_id,
        "edit_path": f"/teacher/lessons/{lesson_id}/edit",
        "view_path": f"/lessons/{lesson_id}",
    }), 201


@studio_bp.route("/export/docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_docx():
    payload = _base_payload()
    lesson = payload.get("lesson")
    if not lesson:
        return jsonify({"message": "Thiếu nội dung giáo án (lesson)"}), 400

    filename = _safe_download_name(lesson.get("topic"), "giao_an", ".docx")
    if not filename.startswith("giao_an"):
        filename = f"giao_an_{filename}"
    return _send_cached_studio_file(
        "lesson_docx",
        lesson,
        filename,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        builder=lambda: studio_service.build_docx_bytes(lesson),
        cache_kind="lesson_docx",
    )


@studio_bp.route("/export/quiz-docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_quiz_docx():
    payload = _base_payload()
    quiz = payload.get("quiz")
    if not quiz:
        return jsonify({"message": "Thiếu đề kiểm tra (quiz)"}), 400

    filename = _safe_download_name(quiz.get("topic"), "de_kiem_tra", ".docx")
    if not filename.startswith("de_"):
        filename = f"de_kiem_tra_{filename}"
    return _send_cached_studio_file(
        "quiz_docx",
        quiz,
        filename,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        builder=lambda: studio_service.quiz_to_docx_bytes(quiz),
        cache_kind="quiz_docx",
    )


@studio_bp.route("/export/pptx", methods=["POST"])
@jwt_required()
@teacher_required
def export_pptx():
    payload = _base_payload()
    deck = payload.get("deck")
    if not deck:
        return jsonify({"message": "Thiếu nội dung slide (deck)"}), 400

    light = bool(payload.get("light") or (request.get_json() or {}).get("light"))
    filename = _safe_download_name(deck.get("topic"), "slide", ".pptx")
    if not filename.startswith("slide"):
        filename = f"slide_{filename}"

    cache_payload = {**deck, "light": light}
    from app.services.studio_files import fetch_studio_file_bytes

    blob = fetch_studio_file_bytes("pptx", cache_payload)
    if not blob:
        try:
            blob = studio_service.build_pptx_bytes({**deck, "light": light}, light=light)
        except Exception:
            from flask import current_app
            current_app.logger.exception("export pptx build failed, retry light")
            blob = studio_service.build_pptx_bytes({**deck, "light": True}, light=True)
    if not blob:
        return jsonify({"message": "Không tạo được file PowerPoint. Thử lại hoặc giảm số slide."}), 500
    try:
        _attach_studio_file_cache({**deck, "light": light}, "pptx", light=light)
    except Exception:
        from flask import current_app
        current_app.logger.exception("pptx cache after export build")
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        as_attachment=True,
        download_name=filename,
    )


@studio_bp.route("/drafts", methods=["GET"])
@jwt_required()
@teacher_required
def list_drafts():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    kind = request.args.get("kind")
    query = {"teacher_id": user_id}
    if kind:
        query["kind"] = kind
    items = list(db.studio_drafts.find(query).sort("created_at", -1).limit(30))
    return jsonify(serialize_doc(items))


@studio_bp.route("/attach-quiz", methods=["POST"])
@jwt_required()
@teacher_required
def attach_ai_quiz():
    """
    Tạo đề AI (nếu chưa có body.quiz) rồi gắn vào bài học bước Kiểm tra.
    Body: lesson_id, topic?, grade?, subject?, num_questions?, quiz? (đã generate sẵn)
    """
    data = request.get_json() or {}
    lesson_id = data.get("lesson_id")
    if not lesson_id:
        return jsonify({"message": "Thiếu lesson_id"}), 400

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "teacher")
    lesson = db.lessons.find_one({"_id": to_object_id(lesson_id)})
    if not lesson:
        return jsonify({"message": "Không tìm thấy bài học"}), 404

    quiz_draft = data.get("quiz") if isinstance(data.get("quiz"), dict) else None
    if not quiz_draft or not (quiz_draft.get("questions") or []):
        return jsonify({"message": "Hãy tạo đề AI trước, rồi gắn đúng đề đó vào bài học"}), 400

    from app.routes.quizzes import _replace_lesson_quiz, normalize_quiz_questions

    topic = (data.get("topic") or lesson.get("title") or quiz_draft.get("topic") or "").strip()
    questions = normalize_quiz_questions(quiz_draft.get("questions") or [])
    if not questions:
        return jsonify({"message": "Đề AI chưa có câu hỏi hợp lệ"}), 400
    payload = {
        "title": quiz_draft.get("title") or f"Kiểm tra: {lesson.get('title', '')}",
        "class_id": str(lesson.get("class_id")) if lesson.get("class_id") else None,
        "time_limit_minutes": quiz_draft.get("time_limit_minutes", 20),
        "passing_score": quiz_draft.get("passing_score", 60),
        "questions": questions,
        "source": quiz_draft.get("source") or "ai",
        "language": "en",
        "max_attempts": data.get("max_attempts", 3),
        "randomize": False,
    }
    quiz_data, err = _replace_lesson_quiz(db, lesson_id, teacher_id, payload, role=role)
    if err:
        return jsonify({"message": err[0]}), err[1]

    quiz_id = quiz_data.get("id")
    stored_qs = quiz_data.get("questions") or questions
    return jsonify({
        "message": "Đã gắn đề AI vào bước Kiểm tra của bài học",
        "quiz": quiz_data,
        "draft": {**quiz_draft, "questions": stored_qs, "id": quiz_id},
        "student_path": f"/quiz/{quiz_id}" if quiz_id else None,
        "grade_path": f"/teacher/quizzes/{quiz_id}" if quiz_id else None,
    }), 201


@studio_bp.route("/publish-quiz", methods=["POST"])
@jwt_required()
@teacher_required
def publish_quiz():
    """Xuất đề Studio thành đề học sinh làm được (có link gửi / xem / chấm)."""
    payload = _base_payload()
    quiz_draft = payload.get("quiz") if isinstance(payload.get("quiz"), dict) else None
    if not quiz_draft or not (quiz_draft.get("questions") or []):
        return jsonify({"message": "Hãy tạo đề AI trước, rồi bấm Tạo link gửi học sinh"}), 400

    from app.routes.quizzes import insert_quiz_questions, load_quiz_questions, normalize_quiz_questions

    questions = normalize_quiz_questions(quiz_draft.get("questions") or [])
    if not questions:
        return jsonify({"message": "Đề AI chưa có câu hỏi hợp lệ"}), 400

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    quiz = {
        "title": quiz_draft.get("title") or f"Đề: {payload['topic']}",
        "lesson_id": None,
        "class_id": None,
        "teacher_id": teacher_id,
        "time_limit_minutes": int(quiz_draft.get("time_limit_minutes") or 20),
        "randomize": False,
        "max_attempts": 3,
        "passing_score": int(quiz_draft.get("passing_score") or 60),
        "hide_answers": True,
        "standalone": True,
        "share_enabled": True,
        "grade": payload["grade"],
        "subject": payload["subject"],
        "topic": payload["topic"] or quiz_draft.get("topic"),
        "language": "en",
        "description": payload["description"] or quiz_draft.get("description") or "",
        "theme_color": payload["theme_color"],
        "theme_accent": payload["theme_accent"],
        "source": quiz_draft.get("source") or "ai",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id
    insert_quiz_questions(db, quiz_id, questions)
    stored = serialize_doc(load_quiz_questions(db, quiz_id))

    quiz["_id"] = quiz_id
    quiz_data = serialize_doc(quiz)
    quiz_data["questions"] = stored
    quiz_data["questions_count"] = len(stored)
    qid = str(quiz_id)
    return jsonify({
        "message": "Đã tạo đề cho học sinh. Gửi link — học sinh chỉ nhập tên và lớp, không cần đăng nhập.",
        "quiz": quiz_data,
        "student_path": f"/quiz/{qid}",
        "grade_path": f"/teacher/quizzes/{qid}",
    }), 201


KIND_LABELS = {
    "lesson": "Giáo án",
    "quiz": "Đề kiểm tra",
    "pptx": "PowerPoint",
    "file": "Tài liệu",
}


def _norm_subject(name: str) -> str:
    text = " ".join(str(name or "").split())
    return text or "Khác"


def _norm_grade(name: str) -> str:
    text = " ".join(str(name or "").split())
    return text or "Khác"


def _grade_sort_key(name: str) -> tuple:
    m = re.search(r"(\d+)", str(name or ""))
    if m:
        return (0, int(m.group(1)))
    return (1, str(name or ""))


def _zero_kind_counts() -> dict:
    return {"total": 0, "lesson": 0, "quiz": 0, "pptx": 0, "file": 0}


def _grade_regex(value: str) -> dict:
    return {"$regex": f"^{re.escape(_norm_grade(value))}$", "$options": "i"}


def _subject_regex(value: str) -> dict:
    return {"$regex": f"^{re.escape(_norm_subject(value))}$", "$options": "i"}


def _ensure_library_catalog(
    db,
    *,
    grade: str,
    subject: str = "",
    topic: str = "",
    description: str = "",
    user_id=None,
) -> None:
    """Đảm bảo khối / môn / bài học tồn tại trong cây Kho (kể cả chưa có file)."""
    grade = _norm_grade(grade)
    subject = _norm_subject(subject) if subject else ""
    topic = (topic or "").strip()
    if not grade or grade == "Khác":
        return
    now = utc_now()
    base = {"updated_at": now}
    if user_id:
        base["created_by"] = user_id

    db.library_catalog.update_one(
        {"catalog_type": "grade", "grade": grade},
        {"$set": {**base, "catalog_type": "grade", "grade": grade, "subject": "", "topic": ""},
         "$setOnInsert": {"created_at": now, "description": ""}},
        upsert=True,
    )
    if not subject or subject == "Khác":
        return
    db.library_catalog.update_one(
        {"catalog_type": "subject", "grade": grade, "subject": subject},
        {"$set": {**base, "catalog_type": "subject", "grade": grade, "subject": subject, "topic": ""},
         "$setOnInsert": {"created_at": now, "description": ""}},
        upsert=True,
    )
    if not topic or topic == "Khác":
        return
    db.library_catalog.update_one(
        {"catalog_type": "topic", "grade": grade, "subject": subject, "topic": topic},
        {"$set": {
            **base,
            "catalog_type": "topic",
            "grade": grade,
            "subject": subject,
            "topic": topic,
            "description": (description or "").strip(),
        },
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


def _merge_predefined_grades(rows: list) -> list:
    from app.utils.gdpt_curriculum import CURRICULUM_GRADES, zero_kind_counts

    seen = {str(r.get("name") or "").lower(): r for r in rows}
    out = []
    for name in CURRICULUM_GRADES:
        row = seen.get(name.lower())
        if row:
            row = dict(row)
            row["predefined"] = True
            out.append(row)
        else:
            out.append({**zero_kind_counts(), "name": name, "catalog_only": True, "predefined": True})
    return out


def _merge_predefined_subjects(rows: list, grade: str) -> list:
    from app.utils.gdpt_curriculum import subjects_for_grade, zero_kind_counts

    names = subjects_for_grade(grade)
    if not names:
        return rows
    seen = {str(r.get("name") or "").lower(): r for r in rows}
    out = []
    for name in names:
        row = seen.get(name.lower())
        if row:
            row = dict(row)
            row["predefined"] = True
            out.append(row)
        else:
            out.append({**zero_kind_counts(), "name": name, "catalog_only": True, "predefined": True})
    return out


def _merge_catalog_grades(db, rows: list) -> list:
    seen = {str(r.get("name") or "").lower() for r in rows}
    for doc in db.library_catalog.find({"catalog_type": "grade"}):
        name = _norm_grade(doc.get("grade"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({**_zero_kind_counts(), "name": name, "catalog_only": True})
    rows.sort(key=lambda r: _grade_sort_key(r["name"]))
    return rows


def _merge_catalog_subjects(db, rows: list, grade: str) -> list:
    seen = {str(r.get("name") or "").lower() for r in rows}
    q = {"catalog_type": "subject", "grade": _grade_regex(grade)}
    for doc in db.library_catalog.find(q):
        name = _norm_subject(doc.get("subject"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({**_zero_kind_counts(), "name": name, "catalog_only": True})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def _merge_catalog_topics(db, rows: list, grade: str, subject: str) -> list:
    seen = {str(r.get("topic") or "").lower() for r in rows}
    q = {
        "catalog_type": "topic",
        "grade": _grade_regex(grade),
        "subject": _subject_regex(subject),
    }
    for doc in db.library_catalog.find(q):
        topic = str(doc.get("topic") or "").strip()
        if not topic or topic.lower() in seen:
            continue
        seen.add(topic.lower())
        rows.append({
            **_zero_kind_counts(),
            "topic": topic,
            "title": topic,
            "description": (doc.get("description") or "").strip(),
            "catalog_only": True,
        })
    rows.sort(key=lambda r: r["topic"].lower())
    return rows


def _library_scope_filter(scope: str, teacher_id) -> dict | None:
    """shared = admin upload & quản lý; personal = giáo viên duyệt từ Teacher Studio."""
    scope = (scope or "").strip().lower()
    if scope == "shared":
        return {"$or": [
            {"library_scope": "shared"},
            {"ai_source": "upload"},
        ]}
    if scope == "personal":
        return {
            "teacher_id": teacher_id,
            "$or": [
                {"library_scope": "personal"},
                {
                    "$and": [
                        {"library_scope": {"$exists": False}},
                        {"ai_source": {"$ne": "upload"}},
                    ],
                },
            ],
        }
    return None


def _item_library_scope(item: dict) -> str:
    if item.get("library_scope") in ("shared", "personal"):
        return item["library_scope"]
    if item.get("ai_source") == "upload":
        return "shared"
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    if content.get("uploaded_by_admin"):
        return "shared"
    return "personal"


def _library_match(extra_query: dict | None = None, scope_filter: dict | None = None) -> dict:
    parts = [{"status": "approved"}]
    if extra_query:
        parts.append(extra_query)
    if scope_filter:
        parts.append(scope_filter)
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def _library_kind_counts_group(field_expr) -> dict:
    return {
        "_id": field_expr,
        "total": {"$sum": 1},
        "lesson": {"$sum": {"$cond": [{"$eq": ["$kind", "lesson"]}, 1, 0]}},
        "quiz": {"$sum": {"$cond": [{"$eq": ["$kind", "quiz"]}, 1, 0]}},
        "pptx": {"$sum": {"$cond": [{"$eq": ["$kind", "pptx"]}, 1, 0]}},
        "file": {"$sum": {"$cond": [{"$eq": ["$kind", "file"]}, 1, 0]}},
    }


def _empty_field_id(field: str) -> dict:
    return {
        "$cond": [
            {"$or": [
                {"$eq": [{"$ifNull": [f"${field}", ""]}, ""]},
                {"$eq": [f"${field}", None]},
            ]},
            "Khác",
            f"${field}",
        ]
    }


def _library_grades(db, extra_query: dict | None = None, scope_filter: dict | None = None):
    match = _library_match(extra_query, scope_filter)
    pipeline = [
        {"$match": match},
        {"$group": _library_kind_counts_group(_empty_field_id("grade"))},
    ]
    rows = []
    for row in db.library_items.aggregate(pipeline):
        name = _norm_grade(row.get("_id"))
        rows.append({
            "name": name,
            "total": int(row.get("total") or 0),
            "lesson": int(row.get("lesson") or 0),
            "quiz": int(row.get("quiz") or 0),
            "pptx": int(row.get("pptx") or 0),
            "file": int(row.get("file") or 0),
        })
    rows.sort(key=lambda r: _grade_sort_key(r["name"]))
    rows = _merge_catalog_grades(db, rows)
    return _merge_predefined_grades(rows)


def _library_subjects(db, extra_query: dict | None = None, *, grade: str = "", scope_filter: dict | None = None):
    match = _library_match(extra_query, scope_filter)
    if grade:
        if grade.lower() == "khác":
            match["$or"] = [
                {"grade": {"$in": ["", "Khác"]}},
                {"grade": {"$exists": False}},
                {"grade": None},
            ]
        else:
            match["grade"] = {"$regex": f"^{re.escape(grade)}$", "$options": "i"}
    pipeline = [
        {"$match": match},
        {"$group": _library_kind_counts_group(_empty_field_id("subject"))},
    ]
    rows = []
    for row in db.library_items.aggregate(pipeline):
        name = _norm_subject(row.get("_id"))
        rows.append({
            "name": name,
            "total": int(row.get("total") or 0),
            "lesson": int(row.get("lesson") or 0),
            "quiz": int(row.get("quiz") or 0),
            "pptx": int(row.get("pptx") or 0),
            "file": int(row.get("file") or 0),
        })
    rows.sort(key=lambda r: r["name"].lower())
    if grade:
        rows = _merge_catalog_subjects(db, rows, grade)
        return _merge_predefined_subjects(rows, grade)
    return rows


def _library_topics(db, extra_query: dict | None = None, *, grade: str = "", subject: str = "", scope_filter: dict | None = None):
    """Bài học = nhóm học liệu theo chủ đề (topic) trong khối + môn."""
    match = _library_match(extra_query, scope_filter)
    if grade:
        if grade.lower() == "khác":
            match.setdefault("$and", []).append({"$or": [
                {"grade": {"$in": ["", "Khác"]}},
                {"grade": {"$exists": False}},
                {"grade": None},
            ]})
        else:
            match["grade"] = {"$regex": f"^{re.escape(grade)}$", "$options": "i"}
    if subject:
        if subject.lower() == "khác":
            match.setdefault("$and", []).append({"$or": [
                {"subject": {"$in": ["", "Khác"]}},
                {"subject": {"$exists": False}},
                {"subject": None},
            ]})
        else:
            match["subject"] = {"$regex": f"^{re.escape(subject)}$", "$options": "i"}
    pipeline = [
        {"$match": match},
        {"$group": {
            **_library_kind_counts_group(_empty_field_id("topic")),
            "title": {"$first": "$title"},
            "description": {"$first": "$description"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = []
    for row in db.library_items.aggregate(pipeline):
        topic = str(row.get("_id") or "").strip() or "Khác"
        rows.append({
            "topic": topic,
            "title": (row.get("title") or topic).strip(),
            "description": (row.get("description") or "").strip(),
            "total": int(row.get("total") or 0),
            "lesson": int(row.get("lesson") or 0),
            "quiz": int(row.get("quiz") or 0),
            "pptx": int(row.get("pptx") or 0),
            "file": int(row.get("file") or 0),
        })
    rows.sort(key=lambda r: r["topic"].lower())
    if grade and subject:
        return _merge_catalog_topics(db, rows, grade, subject)
    return rows


def _library_title(kind: str, content: dict, topic: str) -> str:
    if kind == "lesson":
        return (content.get("title_vi") or content.get("title_en") or content.get("title") or topic or "Giáo án").strip()
    if kind == "quiz":
        return (content.get("title") or topic or "Quiz").strip()
    return (content.get("title") or topic or "Slides").strip()


def _guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    low = (filename or "").lower()
    if low.endswith(".pdf"):
        return "application/pdf"
    if low.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if low.endswith(".doc"):
        return "application/msword"
    if low.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if low.endswith(".ppt"):
        return "application/vnd.ms-powerpoint"
    if low.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if low.endswith(".xls"):
        return "application/vnd.ms-excel"
    if low.endswith(".txt"):
        return "text/plain"
    if low.endswith(".zip"):
        return "application/zip"
    if low.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if low.endswith(".png"):
        return "image/png"
    return fallback


def _library_summary(item: dict) -> dict:
    data = serialize_doc(item) or {}
    data.pop("content", None)
    data["library_scope"] = _item_library_scope(item)
    return data


@studio_bp.route("/library", methods=["GET"])
@jwt_required()
@teacher_required
def list_library():
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    scope_raw = (request.args.get("scope") or "shared").strip().lower()
    if scope_raw not in ("shared", "personal"):
        scope_raw = "shared"
    scope_filter = _library_scope_filter(scope_raw, teacher_id)
    kind = (request.args.get("kind") or "").strip()
    search = (request.args.get("search") or "").strip()
    grade_raw = (request.args.get("grade") or "").strip()
    subject_raw = (request.args.get("subject") or "").strip()
    topic_raw = (request.args.get("topic") or "").strip()
    grade = _norm_grade(grade_raw) if grade_raw else ""
    subject = _norm_subject(subject_raw) if subject_raw else ""
    topic = topic_raw.strip() if topic_raw else ""
    if subject == "Khác" and not subject_raw:
        subject = ""
    if grade == "Khác" and not grade_raw:
        grade = ""
    page = max(1, int(request.args.get("page") or 1))
    limit = min(24, max(6, int(request.args.get("limit") or 12)))
    query = {"status": "approved"}
    if kind in KIND_LABELS:
        query["kind"] = kind
    filters = []

    def _field_filter(field: str, value: str):
        if not value:
            return
        if value.lower() == "khác":
            filters.append({"$or": [
                {field: {"$in": ["", "Khác"]}},
                {field: {"$exists": False}},
                {field: None},
            ]})
        else:
            filters.append({field: {"$regex": f"^{re.escape(value)}$", "$options": "i"}})

    _field_filter("grade", grade)
    _field_filter("subject", subject)
    if topic:
        if topic.lower() == "khác":
            filters.append({"$or": [
                {"topic": {"$in": ["", "Khác"]}},
                {"topic": {"$exists": False}},
                {"topic": None},
            ]})
        else:
            filters.append({"topic": {"$regex": f"^{re.escape(topic)}$", "$options": "i"}})
    if search:
        filters.append({"$or": [
            {"title": {"$regex": search, "$options": "i"}},
            {"topic": {"$regex": search, "$options": "i"}},
            {"subject": {"$regex": search, "$options": "i"}},
            {"grade": {"$regex": search, "$options": "i"}},
            {"teacher_name": {"$regex": search, "$options": "i"}},
        ]})
    if scope_filter:
        filters.append(scope_filter)
    if filters:
        query["$and"] = filters
    extra = {}
    if kind in KIND_LABELS:
        extra["kind"] = kind

    browse = not search
    grades = []
    subjects = []
    topics = []
    if browse and not grade:
        grades = _library_grades(db, extra or None, scope_filter)
    elif browse and grade and not subject:
        subjects = _library_subjects(db, extra or None, grade=grade, scope_filter=scope_filter)
    elif browse and grade and subject and not topic:
        topics = _library_topics(db, extra or None, grade=grade, subject=subject, scope_filter=scope_filter)
    elif browse and not grade and subject:
        subjects = _library_subjects(db, extra or None, scope_filter=scope_filter)

    fetch_items = bool(search or topic or (grade and subject) or (not browse))
    if browse and grade and subject and not topic:
        fetch_items = False

    total = db.library_items.count_documents(query) if fetch_items else 0
    items = []
    if fetch_items:
        items = list(
            db.library_items.find(query, {"content": 0})
            .sort("approved_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        )
    serialized_items = []
    for raw in items:
        row = serialize_doc(raw) or {}
        row.pop("content", None)
        row["library_scope"] = _item_library_scope(raw)
        serialized_items.append(row)

    return jsonify({
        "data": serialized_items,
        "grades": grades,
        "subjects": subjects,
        "topics": topics,
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "scope": scope_raw,
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit) if fetch_items else 1,
    })


@studio_bp.route("/library/catalog", methods=["POST"])
@jwt_required()
@admin_required
def library_catalog_create():
    """Admin tạo khối lớp, môn học hoặc bài học (chủ đề) trong cây Kho học liệu."""
    data = request.get_json() or {}
    ctype = (data.get("type") or "").strip().lower()
    if ctype != "topic":
        return jsonify({"message": "Khối và môn đã cố định theo GDPT; chỉ thêm bài học (type: topic)."}), 400

    grade = _norm_grade(data.get("grade") or "")
    subject = _norm_subject(data.get("subject") or "")
    topic = (data.get("topic") or data.get("title") or "").strip()
    description = (data.get("description") or "").strip()

    if not grade or grade == "Khác":
        return jsonify({"message": "Chọn khối lớp trước"}), 400
    if not subject or subject == "Khác":
        return jsonify({"message": "Chọn môn học trước"}), 400
    if not topic:
        return jsonify({"message": "Nhập tên bài học / chủ đề"}), 400

    from app.utils.gdpt_curriculum import subjects_for_grade

    allowed = {s.lower() for s in subjects_for_grade(grade)}
    if subject.lower() not in allowed:
        return jsonify({"message": f"Môn không thuộc khối {grade} theo chương trình GDPT"}), 400

    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    _ensure_library_catalog(
        db,
        grade=grade,
        subject=subject,
        topic=topic,
        description=description,
        user_id=user_id,
    )

    label = f"{grade} · {subject} · {topic}"

    return jsonify({
        "message": f"Đã thêm {label} vào Kho học liệu",
        "grade": grade,
        "subject": subject if ctype in ("subject", "topic") else "",
        "topic": topic if ctype == "topic" else "",
    }), 201


@studio_bp.route("/library", methods=["POST"])
@jwt_required()
@teacher_required
def publish_to_library():
    """Giáo viên duyệt học liệu AI và đưa vào Kho cho đồng nghiệp xem/tải."""
    payload = _base_payload()
    data = request.get_json() or {}
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "teacher")

    draft_id = data.get("draft_id")
    if draft_id:
        draft_oid = to_object_id(draft_id)
        draft = db.studio_drafts.find_one({"_id": draft_oid}) if draft_oid else None
        if not draft:
            return jsonify({"message": "Không tìm thấy bản nháp"}), 404
        owner = draft.get("teacher_id")
        if role != "super_admin" and str(owner) != str(teacher_id):
            return jsonify({"message": "Bạn không có quyền duyệt bản nháp này"}), 403
        kind = (draft.get("kind") or "").strip()
        content = draft.get("content")
        payload["topic"] = draft.get("topic") or payload["topic"]
        payload["grade"] = draft.get("grade") or payload["grade"]
        payload["subject"] = draft.get("subject") or payload["subject"]
        if isinstance(content, dict) and not payload.get("description"):
            payload["description"] = content.get("description") or ""
    else:
        kind = (data.get("kind") or "").strip()
        content = data.get("content")
        if not content:
            content = payload.get("lesson" if kind == "lesson" else "quiz" if kind == "quiz" else "deck")

    if kind not in KIND_LABELS:
        return jsonify({"message": "Chỉ duyệt giáo án Word, đề hoặc PowerPoint vào kho"}), 400
    if not content or not isinstance(content, dict):
        return jsonify({"message": "Thiếu nội dung học liệu để duyệt vào kho"}), 400

    file_kind = {"lesson": "lesson_docx", "quiz": "quiz_docx", "pptx": "pptx"}.get(kind)
    if file_kind and not content.get("file_url"):
        try:
            content = _attach_studio_file_cache(
                content,
                file_kind,
                light=bool(content.get("light")),
            )
        except Exception:
            from flask import current_app
            current_app.logger.exception("library publish file cache")
    content = dict(content)
    file_url = content.get("file_url")

    user = db.users.find_one({"_id": teacher_id}) or {}
    teacher_name = user.get("full_name") or user.get("name") or "Giáo viên"
    topic = payload["topic"] or content.get("topic") or ""
    title = _library_title(kind, content, topic)
    _ensure_library_catalog(
        db,
        grade=payload["grade"] or content.get("grade") or "",
        subject=payload["subject"] or content.get("subject") or "",
        topic=topic,
        description=payload["description"] or content.get("description") or "",
        user_id=teacher_id,
    )
    now = utc_now()
    doc = {
        "kind": kind,
        "title": title,
        "topic": topic,
        "grade": payload["grade"] or content.get("grade") or "",
        "subject": _norm_subject(payload["subject"] or content.get("subject") or ""),
        "description": payload["description"] or content.get("description") or "",
        "language": "en" if kind == "quiz" else ("en+vi-notes" if kind == "pptx" else "bilingual"),
        "ai_source": content.get("source") or "ai",
        "library_scope": "personal",
        "status": "approved",
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "content": content,
        "file_url": file_url,
        "approved_by": teacher_id,
        "approved_at": now,
        "created_at": now,
        "updated_at": now,
    }
    existing = db.library_items.find_one({
        "teacher_id": teacher_id,
        "library_scope": "personal",
        "kind": kind,
        "grade": doc["grade"],
        "subject": doc["subject"],
        "topic": topic,
        "status": "approved",
    })
    if existing:
        db.library_items.update_one(
            {"_id": existing["_id"]},
            {"$set": {k: v for k, v in doc.items() if k != "created_at"}},
        )
        existing.update(doc)
        existing["created_at"] = existing.get("created_at") or now
        return jsonify({
            "message": "Đã cập nhật học liệu trong Kho",
            "item": _library_summary(existing),
        })

    result = db.library_items.insert_one(doc)
    doc["_id"] = result.inserted_id
    return jsonify({
        "message": "Đã duyệt và đưa vào Kho học liệu",
        "item": _library_summary(doc),
    }), 201


@studio_bp.route("/library/upload", methods=["POST"])
@jwt_required()
@admin_required
def library_upload_material():
    """Admin tải tài liệu (PDF, Word, PPT...) vào một bài học cụ thể trong Kho."""
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    user = db.users.find_one({"_id": teacher_id}) or {}
    teacher_name = user.get("full_name") or user.get("name") or "Admin"

    grade = _norm_grade(request.form.get("grade") or "")
    subject = _norm_subject(request.form.get("subject") or "")
    topic = (request.form.get("topic") or "").strip()
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    upload = request.files.get("file")

    if not grade or grade == "Khác":
        return jsonify({"message": "Chọn khối lớp (grade) cho bài học"}), 400
    if not subject or subject == "Khác":
        return jsonify({"message": "Chọn môn học (subject) cho bài học"}), 400
    if not topic:
        return jsonify({"message": "Chọn bài học / chủ đề (topic) để gắn tài liệu"}), 400
    if not upload or not upload.filename:
        return jsonify({"message": "Chọn file tài liệu để tải lên"}), 400

    try:
        from app.services.cloudinary_service import upload_library_material
        meta = upload_library_material(upload, "library")
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception:
        from flask import current_app
        current_app.logger.exception("library upload failed")
        return jsonify({"message": "Không tải file lên được. Thử lại sau."}), 500

    filename = meta.get("filename") or upload.filename
    file_url = meta.get("url")
    if not file_url:
        return jsonify({"message": "Upload thất bại"}), 500

    content = {
        "filename": filename,
        "file_url": file_url,
        "format": meta.get("format"),
        "bytes": meta.get("bytes"),
        "mime": _guess_mime(filename),
        "public_id": meta.get("public_id"),
        "resource_type": meta.get("resource_type") or "raw",
        "uploaded_by_admin": True,
    }
    doc_title = title or filename
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    item_kind = "pptx" if ext in ("ppt", "pptx") else "file"
    _ensure_library_catalog(
        db,
        grade=grade,
        subject=subject,
        topic=topic,
        description=description,
        user_id=teacher_id,
    )
    now = utc_now()
    doc = {
        "kind": item_kind,
        "title": doc_title,
        "filename": filename,
        "topic": topic,
        "grade": grade,
        "subject": subject,
        "description": description,
        "language": "vi" if item_kind == "file" else "en+vi-notes",
        "ai_source": "upload",
        "library_scope": "shared",
        "status": "approved",
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "content": content,
        "file_url": file_url,
        "approved_by": teacher_id,
        "approved_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = db.library_items.insert_one(doc)
    doc["_id"] = result.inserted_id
    msg = "Đã tải PowerPoint vào kho chung" if item_kind == "pptx" else "Đã tải tài liệu vào kho chung"
    return jsonify({
        "message": msg,
        "item": _library_summary(doc),
    }), 201


@studio_bp.route("/library/<item_id>", methods=["GET"])
@jwt_required()
@teacher_required
def library_detail(item_id):
    db = get_db()
    item = db.library_items.find_one({"_id": to_object_id(item_id), "status": "approved"})
    if not item:
        return jsonify({"message": "Không tìm thấy học liệu"}), 404
    return jsonify(serialize_doc(item))


@studio_bp.route("/library/<item_id>/download", methods=["GET"])
@jwt_required()
@teacher_required
def library_download(item_id):
    db = get_db()
    item = db.library_items.find_one({"_id": to_object_id(item_id), "status": "approved"})
    if not item:
        return jsonify({"message": "Không tìm thấy học liệu"}), 404
    content = item.get("content") or {}
    kind = item.get("kind")
    from app.services.studio_files import fetch_bytes, fetch_studio_file_bytes

    if kind == "file":
        cached_url_val = (content.get("file_url") if isinstance(content, dict) else None) or item.get("file_url")
        blob = fetch_bytes(cached_url_val) if cached_url_val else None
        if not blob:
            return jsonify({"message": "Tài liệu không có bản lưu — hãy tải lên lại"}), 404
        filename = content.get("filename") or item.get("title") or "tai_lieu"
        mime = content.get("mime") or _guess_mime(filename)
        stem, ext = os.path.splitext(filename)
        safe = _safe_download_name(stem, "tai_lieu", ext or ".bin")
        return send_file(io.BytesIO(blob), mimetype=mime, as_attachment=True, download_name=safe)

    file_kind = {"lesson": "lesson_docx", "quiz": "quiz_docx", "pptx": "pptx"}.get(kind)
    if not file_kind:
        return jsonify({"message": "Loại học liệu không hỗ trợ tải"}), 400

    cache_payload = content
    if kind == "pptx":
        cache_payload = {**content, "light": bool(content.get("light"))}

    blob = fetch_studio_file_bytes(
        file_kind,
        cache_payload,
        (content.get("file_url") if isinstance(content, dict) else None) or item.get("file_url"),
    )
    if not blob:
        return jsonify({
            "message": "Chưa có file đã lưu trên Cloudinary. Hãy tạo lại học liệu trong Teacher Studio.",
        }), 404

    if kind == "pptx":
        mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        filename = _safe_download_name(item.get("title"), "slide", ".pptx")
    elif kind == "quiz":
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = _safe_download_name(item.get("title"), "quiz", ".docx")
    else:
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = _safe_download_name(item.get("title"), "giao_an", ".docx")
    return send_file(io.BytesIO(blob), mimetype=mime, as_attachment=True, download_name=filename)


@studio_bp.route("/library/<item_id>", methods=["DELETE"])
@jwt_required()
@teacher_required
def library_delete(item_id):
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "teacher")
    item = db.library_items.find_one({"_id": to_object_id(item_id)})
    if not item:
        return jsonify({"message": "Không tìm thấy học liệu"}), 404
    scope = _item_library_scope(item)
    owner = item.get("teacher_id")
    if scope == "shared":
        if role != "super_admin":
            return jsonify({"message": "Chỉ admin mới được xóa học liệu kho chung"}), 403
    elif role != "super_admin" and str(owner) != str(teacher_id):
        return jsonify({"message": "Chỉ người đăng hoặc admin mới được xóa kho cá nhân"}), 403
    db.library_items.delete_one({"_id": item["_id"]})
    return jsonify({"message": "Đã xóa khỏi Kho học liệu"})
