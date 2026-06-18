from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required
from app.services.cloudinary_service import upload_image, upload_audio

vocab_bp = Blueprint("vocabulary", __name__)

CATEGORIES = [
    "environment", "community", "school_life",
    "culture", "technology", "careers",
]


@vocab_bp.route("/", methods=["GET"])
def list_vocabulary():
    db = get_db()
    category = request.args.get("category")
    difficulty = request.args.get("difficulty")
    search = request.args.get("search", "")
    lesson_id = request.args.get("lesson_id")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip = (page - 1) * limit

    query = {}
    if category:
        query["category"] = category
    if difficulty:
        query["difficulty"] = difficulty
    if lesson_id:
        query["lesson_id"] = to_object_id(lesson_id)
    if search:
        query["$or"] = [
            {"word": {"$regex": search, "$options": "i"}},
            {"meaning_vi": {"$regex": search, "$options": "i"}},
        ]

    total = db.vocabularies.count_documents(query)
    items = list(
        db.vocabularies.find(query).sort("word", 1).skip(skip).limit(limit)
    )
    return jsonify({
        "data": serialize_doc(items),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "categories": CATEGORIES,
    })


@vocab_bp.route("/highlights", methods=["GET"])
def highlights():
    db = get_db()
    items = list(db.vocabularies.find().sort("created_at", -1).limit(8))
    return jsonify(serialize_doc(items))


@vocab_bp.route("/<vocab_id>", methods=["GET"])
def get_vocabulary(vocab_id):
    db = get_db()
    item = db.vocabularies.find_one({"_id": to_object_id(vocab_id)})
    if not item:
        return jsonify({"message": "Không tìm thấy từ vựng"}), 404
    return jsonify(serialize_doc(item))


@vocab_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_vocabulary():
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    db = get_db()

    image = None
    audio = None
    if "image" in request.files:
        image = upload_image(request.files["image"], "vocabulary")
    elif data.get("image"):
        image = data["image"] if isinstance(data["image"], dict) else {"url": data["image"]}
    if "audio" in request.files:
        audio = upload_audio(request.files["audio"], "vocabulary")
    elif data.get("pronunciation_audio"):
        audio = data["pronunciation_audio"] if isinstance(data["pronunciation_audio"], dict) else {"url": data["pronunciation_audio"]}

    vocab = {
        "word": data.get("word", ""),
        "ipa": data.get("ipa", ""),
        "pronunciation_audio": audio,
        "meaning_vi": data.get("meaning_vi", ""),
        "example_sentence": data.get("example_sentence", ""),
        "example_translation": data.get("example_translation", ""),
        "image": image,
        "category": data.get("category", "school_life"),
        "difficulty": data.get("difficulty", "beginner"),
        "lesson_id": to_object_id(data.get("lesson_id")) if data.get("lesson_id") else None,
        "created_by": to_object_id(get_jwt_identity()),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    result = db.vocabularies.insert_one(vocab)
    vocab["_id"] = result.inserted_id
    return jsonify(serialize_doc(vocab)), 201


@vocab_bp.route("/<vocab_id>", methods=["PUT"])
@jwt_required()
@teacher_required
def update_vocabulary(vocab_id):
    data = request.get_json() or {}
    db = get_db()
    update = {k: v for k, v in data.items() if k in (
        "word", "ipa", "meaning_vi", "example_sentence",
        "example_translation", "category", "difficulty",
    )}
    update["updated_at"] = utc_now()

    result = db.vocabularies.update_one(
        {"_id": to_object_id(vocab_id)},
        {"$set": update},
    )
    if result.matched_count == 0:
        return jsonify({"message": "Không tìm thấy từ vựng"}), 404
    return jsonify({"message": "Cập nhật thành công"})


@vocab_bp.route("/<vocab_id>", methods=["DELETE"])
@jwt_required()
@teacher_required
def delete_vocabulary(vocab_id):
    db = get_db()
    result = db.vocabularies.delete_one({"_id": to_object_id(vocab_id)})
    if result.deleted_count == 0:
        return jsonify({"message": "Không tìm thấy từ vựng"}), 404
    return jsonify({"message": "Xóa thành công"})
