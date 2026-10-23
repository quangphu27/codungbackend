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


def _base_payload():
    data = request.get_json() or {}
    return {
        "grade": (data.get("grade") or "Lớp 6").strip(),
        "subject": (data.get("subject") or "Hoạt động trải nghiệm").strip(),
        "topic": (data.get("topic") or "").strip(),
        "description": (data.get("description") or data.get("mo_ta") or "").strip(),
        "language": data.get("language") or "bilingual",
        "extra_requirements": data.get("extra_requirements") or data.get("requirements") or "",
        "theme_color": (data.get("theme_color") or data.get("primary_color") or "#0F2744").strip(),
        "theme_accent": (data.get("theme_accent") or data.get("accent_color") or "#F39C4A").strip(),
        "quiz_types": _quiz_types(data),
        "quiz_requirements": (data.get("quiz_requirements") or "").strip(),
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
        description=payload["description"],
        theme_color=payload["theme_color"],
        theme_accent=payload["theme_accent"],
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
        language=payload["language"],
        description=payload["description"],
        extra_requirements=payload["extra_requirements"],
        quiz_types=payload["quiz_types"],
        quiz_requirements=payload["quiz_requirements"],
        theme_color=payload["theme_color"],
        theme_accent=payload["theme_accent"],
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
        language=payload["language"],
        description=payload["description"],
        extra_requirements=payload["extra_requirements"],
        theme_color=payload["theme_color"],
        theme_accent=payload["theme_accent"],
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
            subject=(data.get("subject") or "Hoạt động trải nghiệm").strip(),
            topic=topic,
            num_questions=int(data.get("num_questions") or 8),
            difficulty=data.get("difficulty") or "mixed",
            language=data.get("language") or "bilingual",
            description=(data.get("description") or "").strip(),
            extra_requirements=data.get("extra_requirements") or "",
            quiz_types=_quiz_types(data),
            quiz_requirements=(data.get("quiz_requirements") or "").strip(),
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

    quiz_id = quiz_data.get("id")
    return jsonify({
        "message": "Đã gắn đề AI vào bước Kiểm tra của bài học",
        "quiz": quiz_data,
        "draft": quiz_draft,
        "student_path": f"/quiz/{quiz_id}" if quiz_id else None,
        "grade_path": f"/teacher/quizzes/{quiz_id}" if quiz_id else None,
    }), 201


@studio_bp.route("/publish-quiz", methods=["POST"])
@jwt_required()
@teacher_required
def publish_quiz():
    """Xuất đề Studio thành đề học sinh làm được (có link gửi / xem / chấm)."""
    payload = _base_payload()
    quiz_draft = payload.get("quiz")
    if not quiz_draft:
        if not payload["topic"]:
            return jsonify({"message": "Thiếu đề hoặc chủ đề"}), 400
        quiz_draft = studio_service.generate_quiz_draft(
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
        )

    from app.routes.quizzes import normalize_quiz_questions

    questions = normalize_quiz_questions(quiz_draft.get("questions") or [])
    if not questions:
        return jsonify({"message": "Đề chưa có câu hỏi hợp lệ"}), 400

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    quiz = {
        "title": quiz_draft.get("title") or f"Đề: {payload['topic']}",
        "lesson_id": None,
        "class_id": None,
        "teacher_id": teacher_id,
        "time_limit_minutes": int(quiz_draft.get("time_limit_minutes") or 20),
        "randomize": True,
        "max_attempts": 3,
        "passing_score": int(quiz_draft.get("passing_score") or 60),
        "hide_answers": True,
        "standalone": True,
        "share_enabled": True,
        "grade": payload["grade"],
        "subject": payload["subject"],
        "topic": payload["topic"] or quiz_draft.get("topic"),
        "description": payload["description"] or quiz_draft.get("description") or "",
        "theme_color": payload["theme_color"],
        "theme_accent": payload["theme_accent"],
        "source": quiz_draft.get("source") or "ai",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id
    for q in questions:
        db.questions.insert_one({
            "quiz_id": quiz_id,
            "question_text": q.get("question_text", ""),
            "question_type": q.get("question_type", "multiple_choice"),
            "options": q.get("options", []),
            "correct_answer": q.get("correct_answer"),
            "points": int(q.get("points", 1)),
            "explanation": q.get("explanation", ""),
            "sample_answer": q.get("sample_answer") or "",
        })

    quiz["_id"] = quiz_id
    quiz_data = serialize_doc(quiz)
    quiz_data["questions_count"] = len(questions)
    qid = str(quiz_id)
    return jsonify({
        "message": "Đã tạo đề cho học sinh. Gửi link làm bài, xem và chấm bên dưới.",
        "quiz": quiz_data,
        "student_path": f"/quiz/{qid}",
        "grade_path": f"/teacher/quizzes/{qid}",
    }), 201
