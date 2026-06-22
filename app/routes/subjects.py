from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.cloudinary_service import upload_image

subjects_bp = Blueprint("subjects", __name__)


@subjects_bp.route("/", methods=["GET"])
def list_subjects():
    db = get_db()
    status = request.args.get("status", "active")
    search = request.args.get("search", "")
    difficulty = request.args.get("difficulty")

    query = {"status": status} if status != "all" else {}
    if difficulty:
        query["difficulty_level"] = difficulty
    if search:
        query["$text"] = {"$search": search}

    subjects = list(db.subjects.find(query).sort("name", 1))
    return jsonify(serialize_doc(subjects))


@subjects_bp.route("/featured", methods=["GET"])
def featured_subjects():
    db = get_db()
    subjects = list(db.subjects.find({"status": "active", "featured": True}).limit(6))
    if not subjects:
        subjects = list(db.subjects.find({"status": "active"}).limit(6))
    return jsonify(serialize_doc(subjects))


@subjects_bp.route("/<subject_id>", methods=["GET"])
def get_subject(subject_id):
    db = get_db()
    subject = db.subjects.find_one({"_id": to_object_id(subject_id)})
    if not subject:
        return jsonify({"message": "Không tìm thấy môn học"}), 404
    return jsonify(serialize_doc(subject))


@subjects_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_subject():
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    db = get_db()

    thumbnail = None
    if "thumbnail" in request.files:
        thumbnail = upload_image(request.files["thumbnail"], "subjects")

    subject = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "thumbnail": thumbnail,
        "difficulty_level": data.get("difficulty_level", "beginner"),
        "status": data.get("status", "active"),
        "featured": data.get("featured", "false") == "true",
        "created_by": to_object_id(get_jwt_identity()),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.subjects.insert_one(subject)
    subject["_id"] = result.inserted_id
    return jsonify(serialize_doc(subject)), 201


@subjects_bp.route("/<subject_id>", methods=["PUT"])
@jwt_required()
@teacher_required
def update_subject(subject_id):
    data = request.get_json() or {}
    db = get_db()
    subject_oid = to_object_id(subject_id)
    subject = db.subjects.find_one({"_id": subject_oid})
    if not subject:
        return jsonify({"message": "Không tìm thấy môn học"}), 404

    update = {k: v for k, v in data.items() if k in (
        "name", "description", "difficulty_level", "status", "featured"
    )}
    update["updated_at"] = utc_now()

    db.subjects.update_one({"_id": subject_oid}, {"$set": update})
    return jsonify({"message": "Cập nhật thành công"})


@subjects_bp.route("/<subject_id>", methods=["DELETE"])
@jwt_required()
@teacher_required
def delete_subject(subject_id):
    db = get_db()
    subject_oid = to_object_id(subject_id)
    subject = db.subjects.find_one({"_id": subject_oid})
    if not subject:
        return jsonify({"message": "Không tìm thấy môn học"}), 404

    class_count = db.classes.count_documents({"subject_id": subject_oid})
    lesson_count = db.lessons.count_documents({"subject_id": subject_oid})
    if class_count or lesson_count:
        return jsonify({
            "message": (
                f"Không thể xóa: môn đang được dùng bởi {class_count} lớp "
                f"và {lesson_count} bài học."
            ),
        }), 409

    db.subjects.delete_one({"_id": subject_oid})
    return jsonify({"message": "Xóa thành công"})
