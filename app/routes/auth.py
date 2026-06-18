from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
from app.extensions import get_db, limiter
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.utils.validators import hash_password, verify_password, validate_email, validate_password
from app.middlewares.auth import role_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "").strip()

    if not validate_email(email):
        return jsonify({"message": "Email không hợp lệ"}), 400
    valid, msg = validate_password(password)
    if not valid:
        return jsonify({"message": msg}), 400

    # Chỉ học sinh được tự đăng ký; giáo viên do admin tạo
    role = "student"

    db = get_db()
    if db.users.find_one({"email": email}):
        return jsonify({"message": "Email đã tồn tại"}), 409

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
    profile.update({"grade": data.get("grade", ""), "class_ids": [], "progress": {}})
    db.students.insert_one(profile)

    access_token = create_access_token(
        identity=str(user_id),
        additional_claims={"role": role, "email": email},
    )
    refresh_token = create_refresh_token(identity=str(user_id))

    return jsonify({
        "message": "Đăng ký thành công",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize_doc({**user, "_id": user_id}),
    }), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("20 per hour")
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    db = get_db()
    user = db.users.find_one({"email": email})
    if not user or not verify_password(password, user["password"]):
        return jsonify({"message": "Email hoặc mật khẩu không đúng"}), 401
    if user.get("status") != "active":
        return jsonify({"message": "Tài khoản đã bị khóa"}), 403

    access_token = create_access_token(
        identity=str(user["_id"]),
        additional_claims={"role": user["role"], "email": user["email"]},
    )
    refresh_token = create_refresh_token(identity=str(user["_id"]))

    db.activity_logs.insert_one({
        "user_id": user["_id"],
        "action": "login",
        "details": {},
        "created_at": utc_now(),
    })

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize_doc(user),
    })


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    db = get_db()
    user = db.users.find_one({"_id": to_object_id(user_id)})
    if not user:
        return jsonify({"message": "Người dùng không tồn tại"}), 404

    access_token = create_access_token(
        identity=str(user["_id"]),
        additional_claims={"role": user["role"], "email": user["email"]},
    )
    return jsonify({"access_token": access_token})


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    db = get_db()
    user = db.users.find_one({"_id": to_object_id(user_id)}, {"password": 0})
    if not user:
        return jsonify({"message": "Người dùng không tồn tại"}), 404

    profile = None
    if user["role"] == "teacher":
        profile = db.teachers.find_one({"user_id": user["_id"]})
    elif user["role"] == "student":
        profile = db.students.find_one({"user_id": user["_id"]})

    return jsonify({
        "user": serialize_doc(user),
        "profile": serialize_doc(profile),
    })


@auth_bp.route("/me", methods=["PUT"])
@jwt_required()
def update_me():
    data = request.get_json() or {}
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    user = db.users.find_one({"_id": user_id})
    if not user:
        return jsonify({"message": "Người dùng không tồn tại"}), 404

    user_update = {}
    if data.get("full_name"):
        user_update["full_name"] = data["full_name"].strip()
    if data.get("email"):
        email = data["email"].strip().lower()
        if not validate_email(email):
            return jsonify({"message": "Email không hợp lệ"}), 400
        if db.users.find_one({"email": email, "_id": {"$ne": user_id}}):
            return jsonify({"message": "Email đã được sử dụng"}), 409
        user_update["email"] = email

    if user_update:
        user_update["updated_at"] = utc_now()
        db.users.update_one({"_id": user_id}, {"$set": user_update})

    if user["role"] == "student" and "grade" in data:
        db.students.update_one(
            {"user_id": user_id},
            {"$set": {"grade": data.get("grade", "")}},
            upsert=True,
        )
    if user["role"] == "teacher":
        teacher_update = {}
        if "bio" in data:
            teacher_update["bio"] = data.get("bio", "")
        if "phone" in data:
            teacher_update["phone"] = data.get("phone", "")
        if teacher_update:
            db.teachers.update_one(
                {"user_id": user_id},
                {"$set": teacher_update},
                upsert=True,
            )

    updated_user = db.users.find_one({"_id": user_id}, {"password": 0})
    profile = None
    if updated_user["role"] == "teacher":
        profile = db.teachers.find_one({"user_id": user_id})
    elif updated_user["role"] == "student":
        profile = db.students.find_one({"user_id": user_id})

    return jsonify({
        "message": "Cập nhật thông tin thành công",
        "user": serialize_doc(updated_user),
        "profile": serialize_doc(profile),
    })


@auth_bp.route("/change-password", methods=["PUT"])
@jwt_required()
def change_password():
    data = request.get_json() or {}
    current = data.get("current_password", "")
    new_pass = data.get("new_password", "")

    valid, msg = validate_password(new_pass)
    if not valid:
        return jsonify({"message": msg}), 400

    db = get_db()
    user = db.users.find_one({"_id": to_object_id(get_jwt_identity())})
    if not verify_password(current, user["password"]):
        return jsonify({"message": "Mật khẩu hiện tại không đúng"}), 400

    db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password": hash_password(new_pass), "updated_at": utc_now()}},
    )
    return jsonify({"message": "Đổi mật khẩu thành công"})
