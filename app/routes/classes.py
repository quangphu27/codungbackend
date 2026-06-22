from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.cloudinary_service import upload_image

classes_bp = Blueprint("classes", __name__)


def _can_manage_class(cls, user_id, role):
    if role == "super_admin":
        return True
    if role == "teacher":
        teacher_id = to_object_id(str(cls.get("teacher_id") or ""))
        owner_id = to_object_id(str(user_id or ""))
        return teacher_id is not None and teacher_id == owner_id
    return False


@classes_bp.route("/", methods=["GET"])
@jwt_required()
def list_classes():
    db = get_db()
    teacher_id = request.args.get("teacher_id")
    student_id = request.args.get("student_id")
    query = {}

    if teacher_id:
        query["teacher_id"] = to_object_id(teacher_id)
    if student_id:
        student = db.students.find_one({"user_id": to_object_id(student_id)})
        if student:
            query["_id"] = {"$in": student.get("class_ids", [])}

    classes = list(db.classes.find(query).sort("created_at", -1))
    return jsonify(serialize_doc(classes))


@classes_bp.route("/<class_id>", methods=["GET"])
@jwt_required()
def get_class(class_id):
    db = get_db()
    cls = db.classes.find_one({"_id": to_object_id(class_id)})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    students = []
    for sid in cls.get("student_ids", []):
        student = db.students.find_one({"user_id": sid})
        if student:
            user = db.users.find_one({"_id": sid}, {"password": 0})
            students.append({**serialize_doc(student), "user": serialize_doc(user)})

    subject = db.subjects.find_one({"_id": cls.get("subject_id")})
    return jsonify({
        **serialize_doc(cls),
        "students": students,
        "subject": serialize_doc(subject),
    })


@classes_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_class():
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    db = get_db()

    thumbnail = None
    if "thumbnail" in request.files:
        thumbnail = upload_image(request.files["thumbnail"], "classes")

    cls = {
        "name": data.get("name", ""),
        "grade": data.get("grade", ""),
        "description": data.get("description", ""),
        "subject_id": to_object_id(data.get("subject_id")),
        "school_year": data.get("school_year", "2025-2026"),
        "thumbnail": thumbnail,
        "status": data.get("status", "active"),
        "teacher_id": to_object_id(get_jwt_identity()),
        "student_ids": [],
        "lesson_ids": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.classes.insert_one(cls)
    cls["_id"] = result.inserted_id
    return jsonify(serialize_doc(cls)), 201


@classes_bp.route("/<class_id>", methods=["PUT"])
@jwt_required()
@teacher_required
def update_class(class_id):
    data = request.get_json() or {}
    db = get_db()
    class_oid = to_object_id(class_id)
    cls = db.classes.find_one({"_id": class_oid})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    claims = get_jwt()
    user_id = to_object_id(get_jwt_identity())
    if not _can_manage_class(cls, user_id, claims.get("role", "teacher")):
        return jsonify({"message": "Không có quyền chỉnh sửa lớp học này"}), 403

    update = {k: v for k, v in data.items() if k in (
        "name", "grade", "description", "school_year", "status"
    )}
    if "subject_id" in data:
        update["subject_id"] = to_object_id(data["subject_id"])
    update["updated_at"] = utc_now()

    db.classes.update_one({"_id": class_oid}, {"$set": update})
    return jsonify({"message": "Cập nhật thành công"})


@classes_bp.route("/<class_id>", methods=["DELETE"])
@jwt_required()
@teacher_required
def delete_class(class_id):
    db = get_db()
    class_oid = to_object_id(class_id)
    cls = db.classes.find_one({"_id": class_oid})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    claims = get_jwt()
    user_id = to_object_id(get_jwt_identity())
    if not _can_manage_class(cls, user_id, claims.get("role", "teacher")):
        return jsonify({"message": "Không có quyền xóa lớp học này"}), 403

    lesson_count = db.lessons.count_documents({"class_id": class_oid})
    if lesson_count > 0:
        return jsonify({
            "message": f"Không thể xóa: lớp còn {lesson_count} bài học. Hãy xóa bài học trước.",
        }), 409

    for sid in cls.get("student_ids", []):
        db.students.update_one(
            {"user_id": sid},
            {"$pull": {"class_ids": class_oid}},
        )

    db.classes.delete_one({"_id": class_oid})
    return jsonify({"message": "Đã xóa lớp học"})


@classes_bp.route("/<class_id>/students", methods=["POST"])
@jwt_required()
@teacher_required
def add_student(class_id):
    data = request.get_json() or {}
    student_user_id = to_object_id(data.get("student_id"))
    db = get_db()
    class_oid = to_object_id(class_id)
    cls = db.classes.find_one({"_id": class_oid})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    claims = get_jwt()
    user_id = to_object_id(get_jwt_identity())
    if not _can_manage_class(cls, user_id, claims.get("role", "teacher")):
        return jsonify({"message": "Không có quyền quản lý lớp học này"}), 403

    db.classes.update_one(
        {"_id": to_object_id(class_id)},
        {"$addToSet": {"student_ids": student_user_id}},
    )
    db.students.update_one(
        {"user_id": student_user_id},
        {"$addToSet": {"class_ids": to_object_id(class_id)}},
    )
    return jsonify({"message": "Thêm học sinh thành công"})


@classes_bp.route("/<class_id>/students/<student_id>", methods=["DELETE"])
@jwt_required()
@teacher_required
def remove_student(class_id, student_id):
    db = get_db()
    oid_class = to_object_id(class_id)
    oid_student = to_object_id(student_id)
    cls = db.classes.find_one({"_id": oid_class})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    claims = get_jwt()
    user_id = to_object_id(get_jwt_identity())
    if not _can_manage_class(cls, user_id, claims.get("role", "teacher")):
        return jsonify({"message": "Không có quyền quản lý lớp học này"}), 403

    db.classes.update_one(
        {"_id": oid_class},
        {"$pull": {"student_ids": oid_student}},
    )
    db.students.update_one(
        {"user_id": oid_student},
        {"$pull": {"class_ids": oid_class}},
    )
    return jsonify({"message": "Xóa học sinh thành công"})


@classes_bp.route("/<class_id>/assign-lessons", methods=["POST"])
@jwt_required()
@teacher_required
def assign_lessons(class_id):
    data = request.get_json() or {}
    lesson_ids = [to_object_id(lid) for lid in data.get("lesson_ids", [])]
    db = get_db()
    class_oid = to_object_id(class_id)
    cls = db.classes.find_one({"_id": class_oid})
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học"}), 404

    claims = get_jwt()
    user_id = to_object_id(get_jwt_identity())
    if not _can_manage_class(cls, user_id, claims.get("role", "teacher")):
        return jsonify({"message": "Không có quyền quản lý lớp học này"}), 403

    db.classes.update_one(
        {"_id": to_object_id(class_id)},
        {"$set": {"lesson_ids": lesson_ids, "updated_at": utc_now()}},
    )
    return jsonify({"message": "Gán bài học thành công"})
