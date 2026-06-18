from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient
import cloudinary
import os

jwt = JWTManager()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)
db = None
mongo_client = None


def _init_cloudinary(app):
    cloudinary_url = app.config.get("CLOUDINARY_URL") or os.getenv("CLOUDINARY_URL")
    if cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
    else:
        cloudinary.config(
            cloud_name=app.config["CLOUDINARY_CLOUD_NAME"],
            api_key=app.config["CLOUDINARY_API_KEY"],
            api_secret=app.config["CLOUDINARY_API_SECRET"],
            secure=True,
        )


def init_extensions(app):
    global db, mongo_client

    jwt.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    CORS(
        app,
        origins=app.config["CORS_ORIGINS"],
        supports_credentials=True,
    )

    mongo_client = MongoClient(app.config["MONGODB_URI"])
    db = mongo_client[app.config["MONGODB_DB"]]
    app.logger.info(f"MongoDB connected to database: {app.config['MONGODB_DB']}")

    _init_cloudinary(app)


def get_db():
    return db
