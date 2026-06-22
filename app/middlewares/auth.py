from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request


ROLES = {
    "super_admin": 3,
    "teacher": 2,
    "student": 1,
}


def role_required(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user_role = claims.get("role", "student")
            if user_role == "super_admin":
                return fn(*args, **kwargs)
            if user_role not in allowed_roles:
                return jsonify({"message": "Không có quyền truy cập"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(fn):
    return role_required("super_admin")(fn)


def teacher_required(fn):
    return role_required("super_admin", "teacher")(fn)


def student_only_required(fn):
    return role_required("student")(fn)


def student_required(fn):
    return role_required("super_admin", "teacher", "student")(fn)
