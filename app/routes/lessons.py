from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import cloudinary.exceptions
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.cloudinary_service import upload_image, upload_video, upload_audio, upload_document

lessons_bp = Blueprint("lessons", __name__)

SECTION_TYPES = [
    "warm_up", "vocabulary", "reading", "video",
    "interactive", "practice", "reflection", "quiz",
]


@lessons_bp.route("/", methods=["GET"])
def list_lessons():
    db = get_db()
    class_id = request.args.get("class_id")
    subject_id = request.args.get("subject_id")
    teacher_id = request.args.get("teacher_id")
    featured = request.args.get("featured")
    status = request.args.get("status", "published")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip = (page - 1) * limit

    query = {}
    if status != "all":
        query["status"] = status
    if class_id:
        query["class_id"] = to_object_id(class_id)
    if subject_id:
        query["subject_id"] = to_object_id(subject_id)
    if teacher_id:
        query["teacher_id"] = to_object_id(teacher_id)
    if featured:
        query["featured"] = True

    total = db.lessons.count_documents(query)
    lessons = list(
        db.lessons.find(query).sort("order", 1).skip(skip).limit(limit)
    )
    return jsonify({
        "data": serialize_doc(lessons),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    })


@lessons_bp.route("/my", methods=["GET"])
@jwt_required()
@teacher_required
def my_lessons():
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    lessons = list(db.lessons.find({"teacher_id": teacher_id}).sort("order", 1))
    return jsonify(serialize_doc(lessons))


@lessons_bp.route("/featured", methods=["GET"])
def featured_lessons():
    db = get_db()
    lessons = list(
        db.lessons.find({"status": "published", "featured": True})
        .sort("created_at", -1)
        .limit(6)
    )
    if not lessons:
        lessons = list(
            db.lessons.find({"status": "published"}).sort("created_at", -1).limit(6)
        )
    return jsonify(serialize_doc(lessons))


@lessons_bp.route("/<lesson_id>", methods=["GET"])
@jwt_required(optional=True)
def get_lesson(lesson_id):
    db = get_db()
    lesson = db.lessons.find_one({"_id": to_object_id(lesson_id)})
    if not lesson:
        return jsonify({"message": "Không tìm thấy bài học"}), 404

    sections = list(
        db.lesson_sections.find({"lesson_id": lesson["_id"]}).sort("order", 1)
    )
    vocabularies = list(db.vocabularies.find({"lesson_id": lesson["_id"]}))
    quiz = db.quizzes.find_one({"lesson_id": lesson["_id"]})

    return jsonify({
        **serialize_doc(lesson),
        "sections": serialize_doc(sections),
        "vocabularies": serialize_doc(vocabularies),
        "quiz": serialize_doc(quiz),
    })


@lessons_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_lesson():
    data = request.get_json() or {}
    db = get_db()

    lesson = {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "class_id": to_object_id(data.get("class_id")),
        "subject_id": to_object_id(data.get("subject_id")),
        "teacher_id": to_object_id(get_jwt_identity()),
        "thumbnail": data.get("thumbnail"),
        "order": int(data.get("order", 0)),
        "status": data.get("status", "draft"),
        "featured": data.get("featured", False),
        "duration_minutes": int(data.get("duration_minutes", 45)),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.lessons.insert_one(lesson)
    lesson_id = result.inserted_id

    for i, section_type in enumerate(SECTION_TYPES):
        db.lesson_sections.insert_one({
            "lesson_id": lesson_id,
            "section_type": section_type,
            "title": section_type.replace("_", " ").title(),
            "content": {},
            "order": i + 1,
            "status": "empty",
            "created_at": utc_now(),
        })

    lesson["_id"] = lesson_id
    return jsonify(serialize_doc(lesson)), 201


@lessons_bp.route("/<lesson_id>", methods=["PUT"])
@jwt_required()
@teacher_required
def update_lesson(lesson_id):
    data = request.get_json() or {}
    db = get_db()
    update = {k: v for k, v in data.items() if k in (
        "title", "description", "order", "status", "featured", "duration_minutes", "thumbnail"
    )}
    update["updated_at"] = utc_now()

    result = db.lessons.update_one(
        {"_id": to_object_id(lesson_id)},
        {"$set": update},
    )
    if result.matched_count == 0:
        return jsonify({"message": "Không tìm thấy bài học"}), 404
    return jsonify({"message": "Cập nhật thành công"})


@lessons_bp.route("/<lesson_id>/sections/<section_id>", methods=["PUT"])
@jwt_required()
@teacher_required
def update_section(lesson_id, section_id):
    data = request.get_json() or {}
    db = get_db()

    update = {
        "content": data.get("content", {}),
        "title": data.get("title"),
        "status": "completed" if data.get("content") else "empty",
        "updated_at": utc_now(),
    }
    content = data.get("content", {})
    if content and any(v for v in content.values() if v not in (None, "", [], {})):
        update["status"] = "completed"
    update = {k: v for k, v in update.items() if v is not None}

    result = db.lesson_sections.update_one(
        {"_id": to_object_id(section_id), "lesson_id": to_object_id(lesson_id)},
        {"$set": update},
    )
    if result.matched_count == 0:
        return jsonify({"message": "Không tìm thấy phần học"}), 404
    return jsonify({"message": "Cập nhật phần học thành công"})


@lessons_bp.route("/<lesson_id>/upload", methods=["POST"])
@jwt_required()
@teacher_required
def upload_lesson_media(lesson_id):
    db = get_db()
    lesson = db.lessons.find_one({"_id": to_object_id(lesson_id)})
    if not lesson:
        return jsonify({"message": "Không tìm thấy bài học"}), 404

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"message": "Không có file được tải lên"}), 400

    media_type = request.form.get("type", "image")
    try:
        if media_type == "video":
            result = upload_video(file, "lessons")
        elif media_type == "audio":
            result = upload_audio(file, "lessons")
        elif media_type == "document":
            result = upload_document(file, "lessons")
        else:
            result = upload_image(file, "lessons")
        return jsonify(result)
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except cloudinary.exceptions.Error as e:
        err = str(e)
        if "413" in err or "Request Entity Too Large" in err:
            return jsonify({
                "message": "Video quá lớn cho Cloudinary (thường tối đa ~100MB). Hãy nén video hoặc chọn file nhỏ hơn.",
            }), 413
        current_app.logger.exception("Cloudinary upload failed")
        return jsonify({"message": "Tải file lên Cloudinary thất bại. Vui lòng thử lại."}), 500
    except Exception as e:
        current_app.logger.exception("Upload lesson media failed")
        msg = str(e) if current_app.debug else "Tải file lên Cloudinary thất bại"
        return jsonify({"message": msg}), 500


@lessons_bp.route("/<lesson_id>/progress", methods=["POST"])
@jwt_required()
def update_progress(lesson_id):
    data = request.get_json() or {}
    user_id = to_object_id(get_jwt_identity())
    db = get_db()

    progress = {
        "lesson_id": to_object_id(lesson_id),
        "student_id": user_id,
        "section_type": data.get("section_type"),
        "completed": data.get("completed", False),
        "watch_percentage": data.get("watch_percentage", 0),
        "score": data.get("score"),
        "updated_at": utc_now(),
    }

    db.students.update_one(
        {"user_id": user_id},
        {
            "$set": {
                f"progress.{lesson_id}.{data.get('section_type')}": progress,
                "updated_at": utc_now(),
            }
        },
        upsert=True,
    )
    return jsonify({"message": "Cập nhật tiến độ thành công"})
