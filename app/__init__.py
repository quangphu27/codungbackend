from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge
from app.config.config import Config
from app.extensions import init_extensions, limiter
from app.models.database import create_indexes
from app.routes.auth import auth_bp
from app.routes.users import users_bp
from app.routes.subjects import subjects_bp
from app.routes.classes import classes_bp
from app.routes.lessons import lessons_bp
from app.routes.vocabulary import vocab_bp
from app.routes.quizzes import quizzes_bp
from app.routes.journals import journals_bp, practice_bp
from app.routes.work import work_bp
from app.routes.api import (
    activities_bp, career_bp, resources_bp, assistant_bp,
    dashboard_bp, portfolio_bp, home_bp, settings_bp,
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    init_extensions(app)

    with app.app_context():
        from app.extensions import get_db
        db = get_db()
        if db is not None:
            try:
                create_indexes(db)
                _seed_initial_data(db)
                _seed_sample_users(db)
            except Exception as e:
                app.logger.warning(f"Database init skipped: {e}")

    prefix = "/api"

    app.register_blueprint(auth_bp, url_prefix=f"{prefix}/auth")
    app.register_blueprint(users_bp, url_prefix=f"{prefix}/users")
    app.register_blueprint(subjects_bp, url_prefix=f"{prefix}/subjects")
    app.register_blueprint(classes_bp, url_prefix=f"{prefix}/classes")
    app.register_blueprint(lessons_bp, url_prefix=f"{prefix}/lessons")
    app.register_blueprint(vocab_bp, url_prefix=f"{prefix}/vocabulary")
    app.register_blueprint(quizzes_bp, url_prefix=f"{prefix}/quizzes")
    app.register_blueprint(journals_bp, url_prefix=f"{prefix}/journals")
    app.register_blueprint(practice_bp, url_prefix=f"{prefix}/practice")
    app.register_blueprint(work_bp, url_prefix=f"{prefix}/work")
    app.register_blueprint(activities_bp, url_prefix=f"{prefix}/activities")
    app.register_blueprint(career_bp, url_prefix=f"{prefix}/career")
    app.register_blueprint(resources_bp, url_prefix=f"{prefix}/resources")
    app.register_blueprint(assistant_bp, url_prefix=f"{prefix}/assistant")
    app.register_blueprint(dashboard_bp, url_prefix=f"{prefix}/dashboard")
    app.register_blueprint(portfolio_bp, url_prefix=f"{prefix}/portfolio")
    app.register_blueprint(home_bp, url_prefix=f"{prefix}/home")
    app.register_blueprint(settings_bp, url_prefix=f"{prefix}/settings")

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "app": "Experiential Learning API"})

    @app.errorhandler(RequestEntityTooLarge)
    def file_too_large(e):
        max_mb = app.config.get("MAX_UPLOAD_MB") or (app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024))
        return jsonify({
            "message": f"File quá lớn. Kích thước tối đa cho phép là {max_mb}MB.",
        }), 413

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"message": "Không tìm thấy"}), 404

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({"message": "Quá nhiều yêu cầu. Vui lòng thử lại sau."}), 429

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"message": "Lỗi máy chủ nội bộ"}), 500

    return app


def _seed_initial_data(db):
    from app.utils.validators import hash_password
    from app.utils.helpers import utc_now

    if db.users.find_one({"role": "super_admin"}):
        return

    admin = {
        "email": "admin@experiential.edu.vn",
        "password": hash_password("admin123"),
        "full_name": "Super Admin",
        "role": "super_admin",
        "status": "active",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    db.users.insert_one(admin)

    subjects_data = [
        {
            "name": "Experiential Learning",
            "description": "Học tiếng Anh thông qua trải nghiệm thực tế - phương pháp học tập chủ đạo của nền tảng.",
            "difficulty_level": "intermediate",
            "status": "active",
            "featured": True,
            "created_at": utc_now(),
        },
        {
            "name": "Science",
            "description": "Khám phá khoa học qua các hoạt động thực hành.",
            "difficulty_level": "beginner",
            "status": "active",
            "featured": False,
            "created_at": utc_now(),
        },
        {
            "name": "English",
            "description": "Nâng cao kỹ năng tiếng Anh toàn diện.",
            "difficulty_level": "beginner",
            "status": "active",
            "featured": True,
            "created_at": utc_now(),
        },
    ]
    db.subjects.insert_many(subjects_data)

    sample_vocab = [
        {
            "word": "sustainable",
            "ipa": "/səˈsteɪnəbl/",
            "meaning_vi": "bền vững",
            "example_sentence": "We need sustainable solutions for the environment.",
            "example_translation": "Chúng ta cần các giải pháp bền vững cho môi trường.",
            "category": "environment",
            "difficulty": "intermediate",
            "created_at": utc_now(),
        },
        {
            "word": "community",
            "ipa": "/kəˈmjuːnəti/",
            "meaning_vi": "cộng đồng",
            "example_sentence": "Our community works together to help others.",
            "example_translation": "Cộng đồng chúng ta cùng nhau giúp đỡ người khác.",
            "category": "community",
            "difficulty": "beginner",
            "created_at": utc_now(),
        },
        {
            "word": "experience",
            "ipa": "/ɪkˈspɪəriəns/",
            "meaning_vi": "trải nghiệm",
            "example_sentence": "Learning through experience is very effective.",
            "example_translation": "Học qua trải nghiệm rất hiệu quả.",
            "category": "school_life",
            "difficulty": "beginner",
            "created_at": utc_now(),
        },
        {
            "word": "festival",
            "ipa": "/ˈfestɪvl/",
            "meaning_vi": "lễ hội",
            "example_sentence": "The Tet festival is the most important holiday in Vietnam.",
            "example_translation": "Tết là ngày lễ quan trọng nhất ở Việt Nam.",
            "category": "culture",
            "difficulty": "beginner",
            "created_at": utc_now(),
        },
    ]
    db.vocabularies.insert_many(sample_vocab)

    db.settings.insert_one({
        "key": "site_name",
        "value": "EXPERIENTIAL LEARNING",
        "updated_at": utc_now(),
    })
    db.settings.insert_one({
        "key": "ai_enabled",
        "value": True,
        "updated_at": utc_now(),
    })


def _seed_sample_users(db):
    """Tạo tài khoản giáo viên & học sinh mẫu nếu chưa tồn tại."""
    from app.routes.users import _create_user_account

    samples = [
        {
            "email": "teacher@experiential.edu.vn",
            "password": "teacher123",
            "full_name": "Nguyễn Thị Dung",
            "role": "teacher",
            "phone": "0335088789",
            "bio": "Giáo viên Experiential Learning — 10 năm kinh nghiệm.",
        },
        {
            "email": "student@experiential.edu.vn",
            "password": "student123",
            "full_name": "Nguyễn Minh Anh",
            "role": "student",
            "grade": "10A1",
        },
        {
            "email": "student2@experiential.edu.vn",
            "password": "student123",
            "full_name": "Trần Văn Hùng",
            "role": "student",
            "grade": "11B2",
        },
    ]

    for data in samples:
        role = data.pop("role")
        if db.users.find_one({"email": data["email"]}):
            continue
        _create_user_account(db, data, role)
