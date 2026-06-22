from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import mimetypes
import urllib.request
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.cloudinary_service import prepare_files_list, guess_filename

work_bp = Blueprint("work", __name__)

WORK_TYPES = ("quiz_attempt", "practice", "journal")

SECTION_META = [
    {"key": "warm_up", "label": "Khởi động", "icon": "💬"},
    {"key": "vocabulary", "label": "Từ vựng", "icon": "🔤"},
    {"key": "reading", "label": "Đọc hiểu", "icon": "📖"},
    {"key": "video", "label": "Video", "icon": "🎬"},
    {"key": "interactive", "label": "Tương tác", "icon": "🧩"},
    {"key": "practice", "label": "Thực hành", "icon": "✍️"},
    {"key": "reflection", "label": "Phản ánh", "icon": "📔"},
    {"key": "quiz", "label": "Kiểm tra", "icon": "✅"},
]


def _lesson_brief(db, lesson_id):
    if not lesson_id:
        return None
    lesson = db.lessons.find_one({"_id": lesson_id})
    if not lesson:
        return None
    return {"id": str(lesson["_id"]), "title": lesson.get("title", "")}


def _student_brief(db, student_id):
    if not student_id:
        return None
    user = db.users.find_one({"_id": student_id}, {"password": 0})
    if not user:
        return None
    return {"id": str(user["_id"]), "full_name": user.get("full_name", ""), "email": user.get("email", "")}


def _quiz_brief(db, quiz_id):
    if not quiz_id:
        return None
    quiz = db.quizzes.find_one({"_id": quiz_id})
    if not quiz:
        return None
    return {"id": str(quiz["_id"]), "title": quiz.get("title", "")}


def _teacher_owns_class(db, class_id, teacher_id):
    return db.classes.find_one({
        "_id": to_object_id(class_id),
        "teacher_id": to_object_id(teacher_id),
    })


def _attempt_summary(db, doc):
    quiz = _quiz_brief(db, doc.get("quiz_id"))
    lesson = _lesson_brief(db, doc.get("lesson_id") or (
        db.quizzes.find_one({"_id": doc.get("quiz_id")}) or {}
    ).get("lesson_id"))
    return {
        "id": str(doc["_id"]),
        "type": "quiz_attempt",
        "title": quiz["title"] if quiz else "Bài kiểm tra",
        "lesson": lesson,
        "score": doc.get("score"),
        "passed": doc.get("passed"),
        "status": "passed" if doc.get("passed") else "completed",
        "created_at": doc.get("created_at"),
    }


def _practice_summary(db, doc):
    lesson = _lesson_brief(db, doc.get("lesson_id"))
    return {
        "id": str(doc["_id"]),
        "type": "practice",
        "title": "Bài thực hành",
        "lesson": lesson,
        "score": doc.get("grade"),
        "status": doc.get("status", "submitted"),
        "created_at": doc.get("created_at"),
    }


def _journal_summary(db, doc):
    lesson = _lesson_brief(db, doc.get("lesson_id"))
    return {
        "id": str(doc["_id"]),
        "type": "journal",
        "title": doc.get("title") or "Nhật ký phản ánh",
        "lesson": lesson,
        "status": "submitted",
        "created_at": doc.get("created_at"),
    }


def _merge_history(items):
    return sorted(items, key=lambda x: x.get("created_at") or "", reverse=True)


def _enrich_quiz_answers(db, quiz_id, answers):
    questions = {str(q["_id"]): q for q in db.questions.find({"quiz_id": quiz_id})}
    enriched = []
    for a in answers or []:
        q = questions.get(str(a.get("question_id")), {})
        enriched.append({
            **a,
            "question_text": q.get("question_text", a.get("question_text", "")),
            "question_type": q.get("question_type", ""),
        })
    return enriched


def _class_id_for_teacher_student(db, teacher_id, student_id, lesson_id=None):
    query = {"teacher_id": teacher_id, "student_ids": student_id}
    if lesson_id:
        lesson = db.lessons.find_one({"_id": lesson_id}, {"class_id": 1})
        if lesson and lesson.get("class_id"):
            cls = db.classes.find_one({**query, "_id": lesson["class_id"]})
            if cls:
                return str(cls["_id"])
    cls = db.classes.find_one(query)
    return str(cls["_id"]) if cls else None


def _can_access_practice_submission(db, user_id, role, doc):
    if not doc:
        return False
    if role == "student":
        return doc.get("student_id") == user_id
    if role in ("teacher", "super_admin"):
        lesson = db.lessons.find_one({"_id": doc.get("lesson_id")})
        if lesson and lesson.get("teacher_id") == user_id:
            return True
        return bool(db.classes.find_one({
            "teacher_id": user_id,
            "student_ids": doc.get("student_id"),
        }))
    return False


def _practice_files_payload(files):
    return prepare_files_list(serialize_doc(files or []))


def _teacher_can_view_student(db, teacher_id, student_id, class_id=None):
    if class_id:
        cls = db.classes.find_one({
            "_id": to_object_id(class_id),
            "teacher_id": teacher_id,
            "student_ids": to_object_id(student_id),
        })
        return cls
    return db.classes.find_one({
        "teacher_id": teacher_id,
        "student_ids": to_object_id(student_id),
    })


def _lesson_ids_for_class(db, cls):
    lesson_ids = cls.get("lesson_ids", [])
    lesson_oids = [to_object_id(lid) for lid in lesson_ids if lid]
    if not lesson_oids:
        lesson_oids = [l["_id"] for l in db.lessons.find({"class_id": cls["_id"]}, {"_id": 1})]
    return lesson_oids


def lesson_progress_summary(db, student_id, lesson_id):
    sections = list(db.lesson_sections.find({"lesson_id": lesson_id}).sort("order", 1))
    steps = []
    for section in sections:
        row = _section_work_row(db, student_id, lesson_id, section["section_type"], section)
        steps.append({
            "section_type": row["section_type"],
            "status": row["status"],
            "label": row["label"],
            "icon": row["icon"],
        })
    completed = sum(1 for s in steps if s["status"] not in ("empty", "in_progress"))
    total = len(steps)
    return {
        "steps_completed": completed,
        "steps_total": total,
        "percent": round(completed / total * 100) if total else 0,
        "steps": steps,
    }


def student_lesson_ids(db, user_id):
    student = db.students.find_one({"user_id": user_id})
    class_ids = list(student.get("class_ids", [])) if student else []
    for cls in db.classes.find({"student_ids": user_id}, {"_id": 1}):
        if cls["_id"] not in class_ids:
            class_ids.append(cls["_id"])

    lesson_ids = set()
    for cid in class_ids:
        cls = db.classes.find_one({"_id": cid})
        if cls:
            lesson_ids.update(_lesson_ids_for_class(db, cls))

    if not lesson_ids:
        lesson_ids = {
            l["_id"] for l in db.lessons.find({"status": "published"}, {"_id": 1})
        }
    return list(lesson_ids)


def _section_work_row(db, student_id, lesson_id, section_type, section):
    meta = next((m for m in SECTION_META if m["key"] == section_type), {})
    row = {
        "section_type": section_type,
        "section_id": str(section["_id"]) if section else None,
        "label": meta.get("label", section_type),
        "icon": meta.get("icon", "📌"),
        "status": "empty",
        "work": None,
    }

    sw = db.section_work.find_one({
        "student_id": student_id,
        "lesson_id": lesson_id,
        "section_type": section_type,
    })

    if section_type in ("warm_up", "reading", "vocabulary", "video", "interactive") and sw:
        row["status"] = "completed" if sw.get("completed") else "in_progress"
        row["work"] = serialize_doc(sw)
        return row

    if section_type == "practice":
        sub = db.practice_submissions.find_one(
            {"student_id": student_id, "lesson_id": lesson_id},
            sort=[("created_at", -1)],
        )
        if sub:
            row["status"] = sub.get("status", "submitted")
            row["work"] = {
                "type": "practice",
                "id": str(sub["_id"]),
                "text_content": sub.get("text_content", ""),
                "files": _practice_files_payload(sub.get("files", [])),
                "grade": sub.get("grade"),
                "teacher_comment": sub.get("teacher_comment"),
                "status": sub.get("status"),
                "created_at": sub.get("created_at"),
            }
        return row

    if section_type == "reflection":
        journal = db.journals.find_one(
            {"student_id": student_id, "lesson_id": lesson_id},
            sort=[("created_at", -1)],
        )
        if journal:
            row["status"] = "completed"
            row["work"] = serialize_doc(journal)
        return row

    if section_type == "quiz":
        quiz = db.quizzes.find_one({"lesson_id": lesson_id})
        if quiz:
            attempt = db.attempts.find_one(
                {"student_id": student_id, "quiz_id": quiz["_id"]},
                sort=[("created_at", -1)],
            )
            if attempt:
                row["status"] = "passed" if attempt.get("passed") else "completed"
                row["work"] = {
                    "type": "quiz_attempt",
                    "id": str(attempt["_id"]),
                    "score": attempt.get("score"),
                    "passed": attempt.get("passed"),
                    "answers": _enrich_quiz_answers(db, quiz["_id"], attempt.get("answers", [])),
                    "created_at": attempt.get("created_at"),
                    "quiz_title": quiz.get("title"),
                }
        return row

    if sw:
        row["status"] = "completed" if sw.get("completed") else "in_progress"
        row["work"] = serialize_doc(sw)
    return row


@work_bp.route("/section", methods=["POST"])
@jwt_required()
def save_section_work():
    data = request.get_json() or {}
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    lesson_id = to_object_id(data.get("lesson_id"))
    section_type = data.get("section_type")
    if not lesson_id or not section_type:
        return jsonify({"message": "Thiếu lesson_id hoặc section_type"}), 400

    doc = {
        "student_id": user_id,
        "lesson_id": lesson_id,
        "section_id": to_object_id(data.get("section_id")) if data.get("section_id") else None,
        "section_type": section_type,
        "data": data.get("data", {}),
        "score": data.get("score"),
        "completed": data.get("completed", True),
        "updated_at": utc_now(),
    }
    db.section_work.update_one(
        {"student_id": user_id, "lesson_id": lesson_id, "section_type": section_type},
        {"$set": doc, "$setOnInsert": {"created_at": utc_now()}},
        upsert=True,
    )
    return jsonify({"message": "Đã lưu tiến độ bước học"})


@work_bp.route("/class/<class_id>/student/<student_id>/lessons", methods=["GET"])
@jwt_required()
@teacher_required
def student_lessons_summary(class_id, student_id):
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    cls = _teacher_owns_class(db, class_id, teacher_id)
    if not cls or to_object_id(student_id) not in cls.get("student_ids", []):
        return jsonify({"message": "Không có quyền"}), 403

    lesson_oids = _lesson_ids_for_class(db, cls)
    lessons = list(db.lessons.find({"_id": {"$in": lesson_oids}}).sort("order", 1)) if lesson_oids else []

    result = []
    for lesson in lessons:
        sections = list(db.lesson_sections.find({"lesson_id": lesson["_id"]}).sort("order", 1))
        steps = [_section_work_row(db, to_object_id(student_id), lesson["_id"], s["section_type"], s) for s in sections]
        completed = sum(1 for s in steps if s["status"] not in ("empty", "in_progress"))
        result.append({
            **serialize_doc(lesson),
            "steps_completed": completed,
            "steps_total": len(steps),
        })

    result.sort(key=lambda x: (-x.get("steps_completed", 0), x.get("title", "")))

    return jsonify({
        "student": _student_brief(db, to_object_id(student_id)),
        "class": serialize_doc(cls),
        "lessons": result,
    })


@work_bp.route("/lesson/<lesson_id>/student/<student_id>/steps", methods=["GET"])
@jwt_required()
@teacher_required
def lesson_student_steps(lesson_id, student_id):
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    class_id = request.args.get("class_id")
    student_oid = to_object_id(student_id)
    lesson_oid = to_object_id(lesson_id)

    if not _teacher_can_view_student(db, teacher_id, student_oid, class_id):
        return jsonify({"message": "Không có quyền xem bài làm học sinh này"}), 403

    lesson = db.lessons.find_one({"_id": lesson_oid})
    if not lesson:
        return jsonify({"message": "Không tìm thấy bài học"}), 404

    sections = list(db.lesson_sections.find({"lesson_id": lesson_oid}).sort("order", 1))
    vocabularies = list(db.vocabularies.find({"lesson_id": lesson_oid}))

    steps = []
    for section in sections:
        step = _section_work_row(db, student_oid, lesson_oid, section["section_type"], section)
        step["section_content"] = serialize_doc(section.get("content", {}))
        steps.append(step)

    return jsonify({
        "student": _student_brief(db, student_oid),
        "lesson": serialize_doc(lesson),
        "vocabularies": serialize_doc(vocabularies),
        "steps": steps,
    })


@work_bp.route("/history", methods=["GET"])
@jwt_required()
def student_history():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    work_type = request.args.get("type")

    items = []
    if not work_type or work_type == "quiz_attempt":
        for doc in db.attempts.find({"student_id": user_id}).sort("created_at", -1):
            items.append(_attempt_summary(db, doc))
    if not work_type or work_type == "practice":
        for doc in db.practice_submissions.find({"student_id": user_id}).sort("created_at", -1):
            items.append(_practice_summary(db, doc))
    if not work_type or work_type == "journal":
        for doc in db.journals.find({"student_id": user_id}).sort("created_at", -1):
            items.append(_journal_summary(db, doc))

    return jsonify(_merge_history(items))


@work_bp.route("/class/<class_id>", methods=["GET"])
@jwt_required()
@teacher_required
def class_work(class_id):
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    cls = _teacher_owns_class(db, class_id, teacher_id)
    if not cls:
        return jsonify({"message": "Không tìm thấy lớp học hoặc không có quyền"}), 404

    student_ids = cls.get("student_ids", [])
    lesson_ids = cls.get("lesson_ids", [])
    lesson_oids = [to_object_id(lid) for lid in lesson_ids if lid]
    if not lesson_oids:
        lesson_oids = [
            l["_id"] for l in db.lessons.find({"class_id": cls["_id"]}, {"_id": 1})
        ]

    work_type = request.args.get("type")
    student_filter = request.args.get("student_id")
    if student_filter:
        student_ids = [to_object_id(student_filter)] if to_object_id(student_filter) in student_ids else []

    items = []
    lesson_query = {"lesson_id": {"$in": lesson_oids}} if lesson_oids else {}

    if not work_type or work_type == "quiz_attempt":
        query = {"student_id": {"$in": student_ids}, **lesson_query}
        for doc in db.attempts.find(query).sort("created_at", -1):
            row = _attempt_summary(db, doc)
            row["student"] = _student_brief(db, doc.get("student_id"))
            items.append(row)

    if not work_type or work_type == "practice":
        pq = {"student_id": {"$in": student_ids}}
        if lesson_oids:
            pq["$or"] = [
                {"lesson_id": {"$in": lesson_oids}},
                {"class_id": cls["_id"]},
            ]
        for doc in db.practice_submissions.find(pq).sort("created_at", -1):
            row = _practice_summary(db, doc)
            row["student"] = _student_brief(db, doc.get("student_id"))
            items.append(row)

    if not work_type or work_type == "journal":
        jq = {"student_id": {"$in": student_ids}}
        jq["$or"] = [{"class_id": cls["_id"]}]
        if lesson_oids:
            jq["$or"].append({"lesson_id": {"$in": lesson_oids}})
        for doc in db.journals.find(jq).sort("created_at", -1):
            row = _journal_summary(db, doc)
            row["student"] = _student_brief(db, doc.get("student_id"))
            items.append(row)

    return jsonify({
        "class": serialize_doc(cls),
        "students": [_student_brief(db, sid) for sid in student_ids],
        "data": _merge_history(items),
    })


@work_bp.route("/practice/<submission_id>/files/<int:file_index>", methods=["GET"])
@jwt_required()
def download_practice_file(submission_id, file_index):
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    claims = get_jwt()
    role = claims.get("role", "student")

    doc = db.practice_submissions.find_one({"_id": to_object_id(submission_id)})
    if not doc:
        return jsonify({"message": "Không tìm thấy bài làm"}), 404
    if not _can_access_practice_submission(db, user_id, role, doc):
        return jsonify({"message": "Không có quyền"}), 403

    files = doc.get("files", [])
    if file_index < 0 or file_index >= len(files):
        return jsonify({"message": "Không tìm thấy file"}), 404

    raw_meta = serialize_doc(files[file_index])
    file_meta = prepare_files_list([raw_meta])[0]
    url = file_meta.get("url")
    if not url:
        return jsonify({"message": "File không hợp lệ"}), 404

    filename = guess_filename(file_meta, file_index)
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    try:
        remote = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=60,
        )
        content = remote.read()
        remote_type = remote.headers.get("Content-Type")
        if remote_type and remote_type != "application/octet-stream":
            mimetype = remote_type.split(";")[0].strip()
    except Exception:
        return jsonify({"message": "Không thể tải file từ máy chủ lưu trữ"}), 502

    if not raw_meta.get("filename"):
        if content[:4] == b"%PDF":
            filename = f"file_{file_index + 1}.pdf"
            mimetype = "application/pdf"
        elif content[:8] == b"\x89PNG\r\n\x1a\n":
            filename = f"file_{file_index + 1}.png"
            mimetype = "image/png"
        elif content[:2] in (b"\xff\xd8", b"\xff\xe0"):
            filename = f"file_{file_index + 1}.jpg"
            mimetype = "image/jpeg"

    inline = request.args.get("inline") == "1"
    disposition = "inline" if inline else "attachment"
    return Response(
        content,
        mimetype=mimetype,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


@work_bp.route("/<work_type>/<work_id>", methods=["GET"])
@jwt_required()
def work_detail(work_type, work_id):
    if work_type not in WORK_TYPES:
        return jsonify({"message": "Loại bài làm không hợp lệ"}), 400

    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    claims = get_jwt()
    role = claims.get("role", "student")
    oid = to_object_id(work_id)

    if work_type == "quiz_attempt":
        doc = db.attempts.find_one({"_id": oid})
        if not doc:
            return jsonify({"message": "Không tìm thấy"}), 404
        if role == "student" and doc.get("student_id") != user_id:
            return jsonify({"message": "Không có quyền"}), 403
        if role == "teacher":
            lesson_id = doc.get("lesson_id")
            lesson = db.lessons.find_one({"_id": lesson_id}) if lesson_id else None
            if lesson and lesson.get("teacher_id") != user_id:
                cls = db.classes.find_one({"student_ids": doc.get("student_id"), "teacher_id": user_id})
                if not cls:
                    return jsonify({"message": "Không có quyền"}), 403

        quiz = db.quizzes.find_one({"_id": doc.get("quiz_id")})
        answers = _enrich_quiz_answers(db, doc.get("quiz_id"), doc.get("answers", []))
        class_id = None
        if role == "teacher":
            class_id = _class_id_for_teacher_student(
                db, user_id, doc.get("student_id"), doc.get("lesson_id"),
            )

        return jsonify({
            "type": "quiz_attempt",
            "student": _student_brief(db, doc.get("student_id")),
            "quiz": _quiz_brief(db, doc.get("quiz_id")),
            "lesson": _lesson_brief(db, doc.get("lesson_id")),
            "class_id": class_id,
            "score": doc.get("score"),
            "passed": doc.get("passed"),
            "answers": answers,
            "created_at": doc.get("created_at"),
            "id": str(doc["_id"]),
        })

    if work_type == "practice":
        doc = db.practice_submissions.find_one({"_id": oid})
        if not doc:
            return jsonify({"message": "Không tìm thấy"}), 404
        if role == "student" and doc.get("student_id") != user_id:
            return jsonify({"message": "Không có quyền"}), 403
        if role == "teacher":
            lesson = db.lessons.find_one({"_id": doc.get("lesson_id")})
            allowed = lesson and lesson.get("teacher_id") == user_id
            if not allowed:
                cls = db.classes.find_one({
                    "teacher_id": user_id,
                    "student_ids": doc.get("student_id"),
                })
                allowed = bool(cls)
            if not allowed:
                return jsonify({"message": "Không có quyền"}), 403

        class_id = None
        if role == "teacher":
            class_id = _class_id_for_teacher_student(
                db, user_id, doc.get("student_id"), doc.get("lesson_id"),
            )

        return jsonify({
            "type": "practice",
            "id": str(doc["_id"]),
            "student": _student_brief(db, doc.get("student_id")),
            "lesson": _lesson_brief(db, doc.get("lesson_id")),
            "class_id": class_id,
            "text_content": doc.get("text_content", ""),
            "files": _practice_files_payload(doc.get("files", [])),
            "status": doc.get("status"),
            "grade": doc.get("grade"),
            "teacher_comment": doc.get("teacher_comment"),
            "created_at": doc.get("created_at"),
            "graded_at": doc.get("graded_at"),
        })

    doc = db.journals.find_one({"_id": oid})
    if not doc:
        return jsonify({"message": "Không tìm thấy"}), 404
    if role == "student" and doc.get("student_id") != user_id:
        return jsonify({"message": "Không có quyền"}), 403
    if role == "teacher":
        cls = db.classes.find_one({"teacher_id": user_id, "student_ids": doc.get("student_id")})
        if not cls:
            return jsonify({"message": "Không có quyền"}), 403

    comments = list(db.comments.find({
        "target_type": "journal",
        "target_id": doc["_id"],
    }).sort("created_at", 1))

    class_id = None
    if role == "teacher":
        class_id = _class_id_for_teacher_student(
            db, user_id, doc.get("student_id"), doc.get("lesson_id"),
        )

    return jsonify({
        "type": "journal",
        "id": str(doc["_id"]),
        "student": _student_brief(db, doc.get("student_id")),
        "lesson": _lesson_brief(db, doc.get("lesson_id")),
        "class_id": class_id,
        **serialize_doc(doc),
        "comments": serialize_doc(comments),
    })
