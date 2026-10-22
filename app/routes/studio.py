"""Teacher Studio API — AI draft + export DOCX/PPTX."""
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import io
import re
import unicodedata

from app.extensions import get_db
from app.middlewares.auth import teacher_required
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


def _base_payload():
    data = request.get_json() or {}
    return {
        "grade": (data.get("grade") or "Lớp 6").strip(),
        "subject": (data.get("subject") or "Experiential Learning").strip(),
        "topic": (data.get("topic") or "").strip(),
        "language": data.get("language") or "bilingual",
        "extra_requirements": data.get("extra_requirements") or data.get("requirements") or "",
        "num_questions": data.get("num_questions", 8),
        "difficulty": data.get("difficulty") or "mixed",
        "slide_count": data.get("slide_count", 12),
        "lesson": data.get("lesson"),
        "quiz": data.get("quiz"),
        "deck": data.get("deck"),
        "save": bool(data.get("save", True)),
    }


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


@studio_bp.route("/status", methods=["GET"])
@jwt_required()
@teacher_required
def studio_status():
    from app.services.secret_store import gemini_is_configured

    configured = gemini_is_configured()
    return jsonify({
        "gemini_configured": configured,
        "message": (
            "Gemini sẵn sàng"
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

    lesson = studio_service.generate_lesson_draft(
        grade=payload["grade"],
        subject=payload["subject"],
        topic=payload["topic"],
        language=payload["language"],
        extra_requirements=payload["extra_requirements"],
    )

    draft = None
    if payload["save"]:
        db = get_db()
        user_id = to_object_id(get_jwt_identity())
        draft = _save_draft(db, user_id, "lesson", payload, lesson)

    return jsonify({"lesson": lesson, "draft": draft})


@studio_bp.route("/generate/quiz", methods=["POST"])
@jwt_required()
@teacher_required
def generate_quiz():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    quiz = studio_service.generate_quiz_draft(
        grade=payload["grade"],
        subject=payload["subject"],
        topic=payload["topic"],
        num_questions=payload["num_questions"],
        difficulty=payload["difficulty"],
    )

    draft = None
    if payload["save"]:
        db = get_db()
        user_id = to_object_id(get_jwt_identity())
        draft = _save_draft(db, user_id, "quiz", payload, quiz)

    return jsonify({"quiz": quiz, "draft": draft})


@studio_bp.route("/generate/pptx", methods=["POST"])
@jwt_required()
@teacher_required
def generate_pptx():
    payload = _base_payload()
    if not payload["topic"]:
        return jsonify({"message": "Vui lòng nhập chủ đề"}), 400

    deck = studio_service.generate_pptx_draft(
        grade=payload["grade"],
        subject=payload["subject"],
        topic=payload["topic"],
        slide_count=payload["slide_count"],
        lesson_context=payload.get("lesson"),
    )

    draft = None
    if payload["save"]:
        db = get_db()
        user_id = to_object_id(get_jwt_identity())
        draft = _save_draft(db, user_id, "pptx", payload, deck)

    return jsonify({"deck": deck, "draft": draft})


@studio_bp.route("/export/docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_docx():
    payload = _base_payload()
    lesson = payload.get("lesson")
    if not lesson:
        return jsonify({"message": "Thiếu nội dung giáo án (lesson)"}), 400

    content = studio_service.build_docx_bytes(lesson)
    filename = _safe_download_name(lesson.get("topic"), "giao_an", ".docx")
    if not filename.startswith("giao_an"):
        filename = f"giao_an_{filename}"
    return send_file(
        io.BytesIO(content),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@studio_bp.route("/export/quiz-docx", methods=["POST"])
@jwt_required()
@teacher_required
def export_quiz_docx():
    payload = _base_payload()
    quiz = payload.get("quiz")
    if not quiz:
        return jsonify({"message": "Thiếu đề kiểm tra (quiz)"}), 400

    content = studio_service.quiz_to_docx_bytes(quiz)
    filename = _safe_download_name(quiz.get("topic"), "de_kiem_tra", ".docx")
    if not filename.startswith("de_"):
        filename = f"de_kiem_tra_{filename}"
    return send_file(
        io.BytesIO(content),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@studio_bp.route("/export/pptx", methods=["POST"])
@jwt_required()
@teacher_required
def export_pptx():
    payload = _base_payload()
    deck = payload.get("deck")
    if not deck:
        return jsonify({"message": "Thiếu nội dung slide (deck)"}), 400

    content = studio_service.build_pptx_bytes(deck)
    filename = _safe_download_name(deck.get("topic"), "slide", ".pptx")
    if not filename.startswith("slide"):
        filename = f"slide_{filename}"
    return send_file(
        io.BytesIO(content),
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

    quiz_draft = data.get("quiz")
    if not quiz_draft:
        topic = (data.get("topic") or lesson.get("title") or "Bài kiểm tra").strip()
        quiz_draft = studio_service.generate_quiz_draft(
            grade=(data.get("grade") or "Lớp 10").strip(),
            subject=(data.get("subject") or "Experiential Learning").strip(),
            topic=topic,
            num_questions=int(data.get("num_questions") or 8),
            difficulty=data.get("difficulty") or "mixed",
        )

    from app.routes.quizzes import _replace_lesson_quiz

    payload = {
        "title": quiz_draft.get("title") or f"Kiểm tra: {lesson.get('title', '')}",
        "class_id": str(lesson.get("class_id")) if lesson.get("class_id") else None,
        "time_limit_minutes": quiz_draft.get("time_limit_minutes", 20),
        "passing_score": quiz_draft.get("passing_score", 60),
        "questions": quiz_draft.get("questions") or [],
        "source": quiz_draft.get("source") or "ai",
        "max_attempts": data.get("max_attempts", 3),
        "randomize": data.get("randomize", True),
    }
    quiz_data, err = _replace_lesson_quiz(db, lesson_id, teacher_id, payload, role=role)
    if err:
        return jsonify({"message": err[0]}), err[1]

    return jsonify({
        "message": "Đã gắn đề AI vào bước Kiểm tra của bài học",
        "quiz": quiz_data,
        "draft": quiz_draft,
    }), 201
