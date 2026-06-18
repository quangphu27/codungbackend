from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import admin_required, teacher_required

from app.utils.validators import hash_password, validate_email, validate_password

users_bp = Blueprint("users", __name__)


def _create_user_account(db, data, role):
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "").strip()

    if not validate_email(email):
        return None, ("Email không hợp lệ", 400)
    valid, msg = validate_password(password)
    if not valid:
        return None, (msg, 400)
    if not full_name:
        return None, ("Họ tên không được để trống", 400)
    if db.users.find_one({"email": email}):
        return None, ("Email đã tồn tại", 409)

    user = {
        "email": email,
        "password": hash_password(password),
        "full_name": full_name,
        "role": role,
        "avatar": None,
        "status": "active",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.users.insert_one(user)
    user_id = result.inserted_id

    profile = {"user_id": user_id, "created_at": utc_now()}
    if role == "teacher":
        profile.update({"bio": data.get("bio", ""), "subjects": [], "phone": data.get("phone", "")})
        db.teachers.insert_one(profile)
    else:
        profile.update({"grade": data.get("grade", ""), "class_ids": [], "progress": {}})
        db.students.insert_one(profile)

    user["_id"] = user_id
    return user, None


@users_bp.route("/", methods=["GET"])
@jwt_required()
@admin_required
def list_users():
    db = get_db()
    role = request.args.get("role")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip = (page - 1) * limit

    query = {}
    if role:
        query["role"] = role

    total = db.users.count_documents(query)
    users = list(
        db.users.find(query, {"password": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    return jsonify({
        "data": serialize_doc(users),
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    })


@users_bp.route("/", methods=["POST"])
@jwt_required()
@admin_required
def create_user():
    """Admin tạo tài khoản giáo viên hoặc học sinh."""
    data = request.get_json() or {}
    role = data.get("role", "teacher")

    if role not in ("teacher", "student"):
        return jsonify({"message": "Vai trò không hợp lệ. Chỉ tạo được giáo viên hoặc học sinh."}), 400

    db = get_db()
    user, error = _create_user_account(db, data, role)
    if error:
        message, code = error
        return jsonify({"message": message}), code

    return jsonify({
        "message": f"Tạo tài khoản {'giáo viên' if role == 'teacher' else 'học sinh'} thành công",
        "user": serialize_doc({**user, "password": None}),
    }), 201


@users_bp.route("/<user_id>", methods=["GET"])
@jwt_required()
@admin_required
def get_user(user_id):
    db = get_db()
    user = db.users.find_one({"_id": to_object_id(user_id)}, {"password": 0})
    if not user:
        return jsonify({"message": "Không tìm thấy người dùng"}), 404
    return jsonify(serialize_doc(user))


@users_bp.route("/<user_id>/status", methods=["PUT"])
@jwt_required()
@admin_required
def update_status(user_id):
    data = request.get_json() or {}
    status = data.get("status", "active")
    if status not in ("active", "inactive", "banned"):
        return jsonify({"message": "Trạng thái không hợp lệ"}), 400

    db = get_db()
    result = db.users.update_one(
        {"_id": to_object_id(user_id)},
        {"$set": {"status": status, "updated_at": utc_now()}},
    )
    if result.matched_count == 0:
        return jsonify({"message": "Không tìm thấy người dùng"}), 404
    return jsonify({"message": "Cập nhật trạng thái thành công"})


@users_bp.route("/teachers", methods=["GET"])
@jwt_required()
def list_teachers():
    db = get_db()
    teachers = list(db.teachers.find())
    result = []
    for t in teachers:
        user = db.users.find_one({"_id": t["user_id"]}, {"password": 0})
        if user:
            result.append({**serialize_doc(t), "user": serialize_doc(user)})
    return jsonify(serialize_doc(result))


@users_bp.route("/students", methods=["GET"])
@jwt_required()
@teacher_required
def list_students():
    db = get_db()
    class_id = request.args.get("class_id")
    query = {}
    if class_id:
        query["class_ids"] = to_object_id(class_id)

    students = list(db.students.find(query))
    result = []
    for s in students:
        user = db.users.find_one({"_id": s["user_id"]}, {"password": 0})
        if user:
            result.append({**serialize_doc(s), "user": serialize_doc(user)})
    return jsonify(serialize_doc(result))
