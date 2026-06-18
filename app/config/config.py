import os
from datetime import timedelta
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()


def _db_name_from_mongodb_uri(uri: str) -> str | None:
    """Lấy tên database từ path trong connection string (mongodb://.../dbname)."""
    if not uri:
        return None
    parsed = urlparse(uri)
    path = (parsed.path or "").strip("/")
    if not path:
        return None
    # Bỏ query string nếu có trong path
    return path.split("?")[0].split("/")[0] or None


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-dev-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    # Ưu tiên tên DB trong URI; fallback MONGODB_DB hoặc experiential_learning
    MONGODB_DB = (
        os.getenv("MONGODB_DB")
        or _db_name_from_mongodb_uri(os.getenv("MONGODB_URI", ""))
        or "experiential_learning"
    )

    # Cloudinary: ưu tiên CLOUDINARY_URL (cloudinary://key:secret@cloud_name)
    CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
    CLOUDINARY_FOLDER_PREFIX = os.getenv("CLOUDINARY_FOLDER_PREFIX", "codung")

    # Fallback nếu không dùng CLOUDINARY_URL
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True") == "True"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

    RATELIMIT_DEFAULT = "200 per hour"
    RATELIMIT_STORAGE_URI = "memory://"

    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
