from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required, admin_required
from app.services.ai_service import generate_career_analysis
from app.services.pdf_service import generate_career_pdf, generate_portfolio_pdf
from app.services.cloudinary_service import upload_image, upload_video

activities_bp = Blueprint("activities", __name__)
career_bp = Blueprint("career", __name__)
resources_bp = Blueprint("resources", __name__)
assistant_bp = Blueprint("assistant", __name__)
dashboard_bp = Blueprint("dashboard", __name__)
portfolio_bp = Blueprint("portfolio", __name__)
home_bp = Blueprint("home", __name__)
settings_bp = Blueprint("settings", __name__)

ACTIVITY_TOPICS = [
    "vietnamese_culture",
    "environmental_protection",
    "community_service",
    "sustainable_living",
    "local_tourism",
    "traditional_festivals",
]


@activities_bp.route("/", methods=["GET"])
def list_activities():
    db = get_db()
    topic = request.args.get("topic")
    status = request.args.get("status", "published")
    query = {}
    if status != "all":
        query["status"] = status
    if topic:
        query["topic"] = topic
    activities = list(db.activities.find(query).sort("created_at", -1))
    return jsonify(serialize_doc(activities))


@activities_bp.route("/<activity_id>", methods=["GET"])
def get_activity(activity_id):
    db = get_db()
    activity = db.activities.find_one({"_id": to_object_id(activity_id)})
    if not activity:
        return jsonify({"message": "Không tìm thấy hoạt động"}), 404
    return jsonify(serialize_doc(activity))


@activities_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_activity():
    data = request.get_json() or {}
    db = get_db()

    activity = {
        "title": data.get("title", ""),
        "topic": data.get("topic", "vietnamese_culture"),
        "introduction": data.get("introduction", ""),
        "vocabulary": data.get("vocabulary", []),
        "reading": data.get("reading", {}),
        "video": data.get("video", {}),
        "activities": data.get("activities", []),
        "quiz_id": to_object_id(data.get("quiz_id")) if data.get("quiz_id") else None,
        "teacher_id": to_object_id(get_jwt_identity()),
        "status": data.get("status", "draft"),
        "created_at": utc_now(),
    }
    result = db.activities.insert_one(activity)
    activity["_id"] = result.inserted_id
    return jsonify(serialize_doc(activity)), 201


@activities_bp.route("/<activity_id>/complete", methods=["POST"])
@jwt_required()
def complete_activity(activity_id):
    data = request.get_json() or {}
    user_id = to_object_id(get_jwt_identity())
    db = get_db()

    db.students.update_one(
        {"user_id": user_id},
        {"$addToSet": {
            "completed_activities": {
                "activity_id": to_object_id(activity_id),
                "score": data.get("score", 0),
                "completed_at": utc_now(),
            }
        }},
    )
    return jsonify({"message": "Hoàn thành hoạt động"})


@career_bp.route("/tests", methods=["GET"])
@jwt_required()
def list_career_tests():
    db = get_db()
    status = request.args.get("status", "active")
    query = {}
    if status != "all":
        query["status"] = status
    tests = list(db.career_tests.find(query).sort("created_at", -1))
    return jsonify(serialize_doc(tests))


@career_bp.route("/tests", methods=["POST"])
@jwt_required()
@teacher_required
def create_career_test():
    data = request.get_json() or {}
    db = get_db()

    test = {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "questions": data.get("questions", []),
        "teacher_id": to_object_id(get_jwt_identity()),
        "status": "active",
        "created_at": utc_now(),
    }
    result = db.career_tests.insert_one(test)
    test["_id"] = result.inserted_id
    return jsonify(serialize_doc(test)), 201


@career_bp.route("/tests/<test_id>/submit", methods=["POST"])
@jwt_required()
def submit_career_test(test_id):
    data = request.get_json() or {}
    user_id = to_object_id(get_jwt_identity())
    db = get_db()

    answers = data.get("answers", [])
    analysis = generate_career_analysis(answers)

    result_doc = {
        "student_id": user_id,
        "test_id": to_object_id(test_id),
        "answers": answers,
        "analysis": analysis,
        "created_at": utc_now(),
    }
    result = db.career_results.insert_one(result_doc)
    result_doc["_id"] = result.inserted_id

    user = db.users.find_one({"_id": user_id})
    return jsonify(serialize_doc(result_doc))


@career_bp.route("/results/<result_id>/pdf", methods=["GET"])
@jwt_required()
def download_career_pdf(result_id):
    db = get_db()
    result = db.career_results.find_one({"_id": to_object_id(result_id)})
    if not result:
        return jsonify({"message": "Không tìm thấy kết quả"}), 404

    user = db.users.find_one({"_id": result["student_id"]})
    pdf = generate_career_pdf(result.get("analysis", {}), user.get("full_name", ""))
    return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                     download_name="career_report.pdf")


@resources_bp.route("/", methods=["GET"])
def list_resources():
    db = get_db()
    resource_type = request.args.get("type")
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip = (page - 1) * limit

    query = {}
    if resource_type:
        query["type"] = resource_type
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]

    total = db.resources.count_documents(query)
    resources = list(db.resources.find(query).sort("created_at", -1).skip(skip).limit(limit))
    return jsonify({
        "data": serialize_doc(resources),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    })


@resources_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_resource():
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    db = get_db()

    file_data = None
    if "file" in request.files:
        f = request.files["file"]
        if f.content_type and f.content_type.startswith("video"):
            file_data = upload_video(f, "resources")
        elif f.content_type and f.content_type.startswith("image"):
            file_data = upload_image(f, "resources")
        else:
            from app.services.cloudinary_service import upload_document
            file_data = upload_document(f, "resources")

    resource = {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "type": data.get("type", "document"),
        "file": file_data,
        "subject_id": to_object_id(data.get("subject_id")) if data.get("subject_id") else None,
        "teacher_id": to_object_id(get_jwt_identity()),
        "tags": data.get("tags", "").split(",") if data.get("tags") else [],
        "created_at": utc_now(),
    }
    result = db.resources.insert_one(resource)
    resource["_id"] = result.inserted_id
    return jsonify(serialize_doc(resource)), 201


@assistant_bp.route("/ask", methods=["POST"])
@jwt_required()
def ask_question():
    from app.services.ai_service import ask_question as ai_ask
    data = request.get_json() or {}
    result = ai_ask(data.get("question", ""), data.get("context", ""))
    return jsonify(result)


@assistant_bp.route("/vocabulary", methods=["POST"])
@jwt_required()
def explain_vocab():
    from app.services.ai_service import explain_vocabulary
    data = request.get_json() or {}
    db = get_db()
    custom = db.settings.find_one({"key": f"vocab_explanation_{data.get('word', '')}"})
    result = explain_vocabulary(
        data.get("word", ""),
        custom.get("value") if custom else "",
    )
    return jsonify(result)


@assistant_bp.route("/translate", methods=["POST"])
@jwt_required()
def translate():
    from app.services.ai_service import translate_text
    data = request.get_json() or {}
    result = translate_text(data.get("text", ""), data.get("target_lang", "vi"))
    return jsonify(result)


@assistant_bp.route("/examples", methods=["POST"])
@jwt_required()
def generate_examples():
    from app.services.ai_service import ask_question
    data = request.get_json() or {}
    word = data.get("word", "")
    result = ask_question(
        f"Tạo 3 câu ví dụ sử dụng từ '{word}' trong tiếng Anh kèm bản dịch tiếng Việt.",
    )
    return jsonify(result)


@dashboard_bp.route("/admin", methods=["GET"])
@jwt_required()
@admin_required
def admin_dashboard():
    db = get_db()

    stats = {
        "total_teachers": db.users.count_documents({"role": "teacher"}),
        "total_students": db.users.count_documents({"role": "student"}),
        "total_classes": db.classes.count_documents({}),
        "total_lessons": db.lessons.count_documents({}),
        "total_vocabulary": db.vocabularies.count_documents({}),
        "total_quizzes": db.quizzes.count_documents({}),
        "total_activities": db.activities.count_documents({}),
    }

    recent_logs = list(db.activity_logs.find().sort("created_at", -1).limit(20))

    student_growth = []
    for i in range(6):
        student_growth.append({"month": f"T{i+1}", "count": db.users.count_documents({"role": "student"})})

    return jsonify({
        "stats": stats,
        "recent_logs": serialize_doc(recent_logs),
        "charts": {
            "student_growth": student_growth,
            "lesson_completion": [],
            "vocabulary_progress": [],
            "quiz_performance": [],
            "career_trends": [],
        },
    })


@dashboard_bp.route("/teacher", methods=["GET"])
@jwt_required()
def teacher_dashboard():
    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())

    classes = list(db.classes.find({"teacher_id": teacher_id}))
    lessons = list(db.lessons.find({"teacher_id": teacher_id}))
    pending = list(db.practice_submissions.find({"status": "submitted"}).limit(10))

    return jsonify({
        "classes_count": len(classes),
        "lessons_count": len(lessons),
        "pending_submissions": serialize_doc(pending),
        "classes": serialize_doc(classes),
    })


@dashboard_bp.route("/student", methods=["GET"])
@jwt_required()
def student_dashboard():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    student = db.students.find_one({"user_id": user_id})

    attempts = list(db.attempts.find({"student_id": user_id}).sort("created_at", -1).limit(5))
    journals = list(db.journals.find({"student_id": user_id}).sort("created_at", -1).limit(5))

    return jsonify({
        "progress": student.get("progress", {}) if student else {},
        "recent_attempts": serialize_doc(attempts),
        "recent_journals": serialize_doc(journals),
        "class_ids": serialize_doc(student.get("class_ids", [])) if student else [],
    })


@portfolio_bp.route("/", methods=["GET"])
@jwt_required()
def get_portfolio():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    student = db.students.find_one({"user_id": user_id})
    user = db.users.find_one({"_id": user_id}, {"password": 0})

    attempts = list(db.attempts.find({"student_id": user_id}))
    journals = list(db.journals.find({"student_id": user_id}))
    career_results = list(db.career_results.find({"student_id": user_id}))

    avg_score = 0
    if attempts:
        avg_score = sum(a.get("score", 0) for a in attempts) / len(attempts)

    portfolio = {
        "student": serialize_doc(user),
        "stats": {
            "total_quizzes": len(attempts),
            "average_score": round(avg_score, 1),
            "total_journals": len(journals),
            "career_assessments": len(career_results),
            "vocabulary_learned": db.vocabularies.count_documents({}),
        },
        "skills_achieved": student.get("skills_achieved", []) if student else [],
        "certificates": student.get("certificates", []) if student else [],
        "completed_activities": student.get("completed_activities", []) if student else [],
    }
    return jsonify(portfolio)


@portfolio_bp.route("/pdf", methods=["GET"])
@jwt_required()
def download_portfolio_pdf():
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    user = db.users.find_one({"_id": user_id})

    attempts = list(db.attempts.find({"student_id": user_id}))
    avg_score = sum(a.get("score", 0) for a in attempts) / len(attempts) if attempts else 0

    portfolio = {
        "stats": {
            "Tổng bài kiểm tra": len(attempts),
            "Điểm trung bình": f"{avg_score:.1f}%",
        },
        "skills_achieved": [],
    }
    pdf = generate_portfolio_pdf(portfolio, user.get("full_name", ""))
    return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                     download_name="portfolio.pdf")


@home_bp.route("/", methods=["GET"])
def home_data():
    db = get_db()

    return jsonify({
        "featured_subjects": serialize_doc(
            list(db.subjects.find({"status": "active"}).limit(6))
        ),
        "featured_lessons": serialize_doc(
            list(db.lessons.find({"status": "published"}).sort("created_at", -1).limit(6))
        ),
        "vocabulary_highlights": serialize_doc(
            list(db.vocabularies.find().sort("created_at", -1).limit(8))
        ),
        "activities": serialize_doc(
            list(db.activities.find({"status": "published"}).limit(6))
        ),
        "statistics": {
            "total_students": db.users.count_documents({"role": "student"}),
            "total_teachers": db.users.count_documents({"role": "teacher"}),
            "total_lessons": db.lessons.count_documents({"status": "published"}),
            "total_vocabulary": db.vocabularies.count_documents({}),
        },
        "testimonials": [
            {
                "name": "Nguyễn Minh Anh",
                "grade": "Lớp 10",
                "content": "Nền tảng học tập trải nghiệm giúp em học tiếng Anh thông qua các hoạt động thực tế rất thú vị!",
                "rating": 5,
            },
            {
                "name": "Trần Văn Hùng",
                "grade": "Lớp 11",
                "content": "Em thích phần nhật ký phản ánh và hoạt động cộng đồng. Tiếng Anh trở nên dễ học hơn nhiều.",
                "rating": 5,
            },
            {
                "name": "Lê Thị Mai",
                "grade": "Lớp 9",
                "content": "Giáo viên dễ dàng tạo bài học và theo dõi tiến độ của chúng em. Rất hữu ích!",
                "rating": 4,
            },
        ],
        "teachers": serialize_doc(
            list(db.teachers.find().limit(4))
        ),
        "teacher_profiles": [
            {
                "id": "t1",
                "name": "Cô Nguyễn Thị Dung",
                "role": "Giáo viên Experiential Learning",
                "bio": "10 năm kinh nghiệm giảng dạy tiếng Anh qua phương pháp học tập trải nghiệm.",
                "subjects": ["Experiential Learning", "English"],
            },
            {
                "id": "t2",
                "name": "Thầy Trần Minh Tuấn",
                "role": "Giáo viên Khoa học & Môi trường",
                "bio": "Chuyên tổ chức hoạt động thực địa và dự án bảo vệ môi trường.",
                "subjects": ["Science", "Environment"],
            },
            {
                "id": "t3",
                "name": "Cô Lê Hoài An",
                "role": "Giáo viên Văn hóa & Hướng nghiệp",
                "bio": "Hướng dẫn học sinh khám phá văn hóa Việt và định hướng nghề nghiệp.",
                "subjects": ["Culture", "Career Guidance"],
            },
        ],
    })


@settings_bp.route("/", methods=["GET"])
@jwt_required()
def get_settings():
    db = get_db()
    settings = {s["key"]: s["value"] for s in db.settings.find()}
    return jsonify(settings)


@settings_bp.route("/", methods=["PUT"])
@jwt_required()
def update_settings():
    from app.middlewares.auth import admin_required
    data = request.get_json() or {}
    db = get_db()

    for key, value in data.items():
        db.settings.update_one(
            {"key": key},
            {"$set": {"key": key, "value": value, "updated_at": utc_now()}},
            upsert=True,
        )
    return jsonify({"message": "Cập nhật cài đặt thành công"})
