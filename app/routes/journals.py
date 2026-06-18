from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.ai_service import summarize_journal
from app.services.cloudinary_service import upload_image, upload_video, upload_document

journals_bp = Blueprint("journals", __name__)
practice_bp = Blueprint("practice", __name__)


@journals_bp.route("/", methods=["GET"])
@jwt_required()
def list_journals():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    lesson_id = request.args.get("lesson_id")

    query = {"student_id": user_id}
    if lesson_id:
        query["lesson_id"] = to_object_id(lesson_id)

    journals = list(db.journals.find(query).sort("created_at", -1))
    return jsonify(serialize_doc(journals))


@journals_bp.route("/<journal_id>", methods=["GET"])
@jwt_required()
def get_journal(journal_id):
    db = get_db()
    journal = db.journals.find_one({"_id": to_object_id(journal_id)})
    if not journal:
        return jsonify({"message": "Không tìm thấy nhật ký"}), 404

    comments = list(db.comments.find({
        "target_type": "journal",
        "target_id": journal["_id"],
    }).sort("created_at", 1))
    return jsonify({
        **serialize_doc(journal),
        "comments": serialize_doc(comments),
    })


@journals_bp.route("/", methods=["POST"])
@jwt_required()
def create_journal():
    data = request.get_json() or {}
    user_id = to_object_id(get_jwt_identity())
    db = get_db()

    content = data.get("reflection_content", "")
    ai_summary = summarize_journal(content)

    journal = {
        "student_id": user_id,
        "lesson_id": to_object_id(data.get("lesson_id")),
        "class_id": to_object_id(data.get("class_id")) if data.get("class_id") else None,
        "title": data.get("title", ""),
        "reflection_content": content,
        "what_learned": data.get("what_learned", ""),
        "skills_developed": data.get("skills_developed", ""),
        "feelings": data.get("feelings", ""),
        "future_improvement": data.get("future_improvement", ""),
        "ai_summary": ai_summary.get("summary"),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.journals.insert_one(journal)
    journal["_id"] = result.inserted_id
    return jsonify(serialize_doc(journal)), 201


@journals_bp.route("/<journal_id>/comment", methods=["POST"])
@jwt_required()
@teacher_required
def comment_journal(journal_id):
    data = request.get_json() or {}
    db = get_db()

    comment = {
        "target_type": "journal",
        "target_id": to_object_id(journal_id),
        "author_id": to_object_id(get_jwt_identity()),
        "content": data.get("content", ""),
        "created_at": utc_now(),
    }
    result = db.comments.insert_one(comment)
    comment["_id"] = result.inserted_id
    return jsonify(serialize_doc(comment)), 201


@practice_bp.route("/submit", methods=["POST"])
@jwt_required()
def submit_practice():
    user_id = to_object_id(get_jwt_identity())
    data = request.form.to_dict() if request.form else {}
    db = get_db()

    files = []
    for key in request.files:
        f = request.files[key]
        if f.content_type and f.content_type.startswith("image"):
            files.append(upload_image(f, "practice"))
        elif f.content_type and f.content_type.startswith("video"):
            files.append(upload_video(f, "practice"))
        else:
            files.append(upload_document(f, "practice"))

    lesson_id = to_object_id(data.get("lesson_id"))
    lesson = db.lessons.find_one({"_id": lesson_id}) if lesson_id else None

    submission = {
        "student_id": user_id,
        "lesson_id": lesson_id,
        "class_id": lesson.get("class_id") if lesson else to_object_id(data.get("class_id")),
        "section_id": to_object_id(data.get("section_id")) if data.get("section_id") else None,
        "text_content": data.get("text_content", ""),
        "files": files,
        "status": "submitted",
        "grade": None,
        "teacher_comment": None,
        "created_at": utc_now(),
    }
    result = db.practice_submissions.insert_one(submission)
    submission["_id"] = result.inserted_id
    return jsonify(serialize_doc(submission)), 201


@practice_bp.route("/<submission_id>/grade", methods=["PUT"])
@jwt_required()
@teacher_required
def grade_practice(submission_id):
    data = request.get_json() or {}
    db = get_db()

    db.practice_submissions.update_one(
        {"_id": to_object_id(submission_id)},
        {"$set": {
            "grade": data.get("grade"),
            "teacher_comment": data.get("comment", ""),
            "status": "graded",
            "graded_at": utc_now(),
            "graded_by": to_object_id(get_jwt_identity()),
        }},
    )
    return jsonify({"message": "Chấm điểm thành công"})
