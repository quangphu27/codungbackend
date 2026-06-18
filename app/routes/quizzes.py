from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import random
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required

quizzes_bp = Blueprint("quizzes", __name__)


def grade_answer(question, answer):
    q_type = question.get("question_type")
    correct = question.get("correct_answer")

    if q_type == "multiple_choice":
        return answer == correct
    if q_type == "true_false":
        return str(answer).lower() == str(correct).lower()
    if q_type == "fill_blank":
        return str(answer).strip().lower() == str(correct).strip().lower()
    if q_type == "matching":
        return answer == correct
    if q_type == "ordering":
        return answer == correct
    return False


@quizzes_bp.route("/", methods=["GET"])
@jwt_required()
def list_quizzes():
    db = get_db()
    lesson_id = request.args.get("lesson_id")
    query = {}
    if lesson_id:
        query["lesson_id"] = to_object_id(lesson_id)
    quizzes = list(db.quizzes.find(query))
    return jsonify(serialize_doc(quizzes))


@quizzes_bp.route("/<quiz_id>", methods=["GET"])
@jwt_required()
def get_quiz(quiz_id):
    db = get_db()
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404

    questions = list(db.questions.find({"quiz_id": quiz["_id"]}))
    if quiz.get("randomize"):
        random.shuffle(questions)

    quiz_data = serialize_doc(quiz)
    quiz_data["questions"] = serialize_doc(questions)
    if quiz.get("hide_answers"):
        for q in quiz_data["questions"]:
            q.pop("correct_answer", None)
    return jsonify(quiz_data)


@quizzes_bp.route("/", methods=["POST"])
@jwt_required()
@teacher_required
def create_quiz():
    data = request.get_json() or {}
    db = get_db()

    quiz = {
        "title": data.get("title", ""),
        "lesson_id": to_object_id(data.get("lesson_id")),
        "class_id": to_object_id(data.get("class_id")) if data.get("class_id") else None,
        "teacher_id": to_object_id(get_jwt_identity()),
        "time_limit_minutes": int(data.get("time_limit_minutes", 30)),
        "randomize": data.get("randomize", True),
        "max_attempts": int(data.get("max_attempts", 3)),
        "passing_score": int(data.get("passing_score", 60)),
        "hide_answers": True,
        "created_at": utc_now(),
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id

    for q in data.get("questions", []):
        db.questions.insert_one({
            "quiz_id": quiz_id,
            "question_text": q.get("question_text", ""),
            "question_type": q.get("question_type", "multiple_choice"),
            "options": q.get("options", []),
            "correct_answer": q.get("correct_answer"),
            "points": int(q.get("points", 1)),
            "explanation": q.get("explanation", ""),
        })

    quiz["_id"] = quiz_id
    return jsonify(serialize_doc(quiz)), 201


@quizzes_bp.route("/<quiz_id>/submit", methods=["POST"])
@jwt_required()
def submit_quiz(quiz_id):
    data = request.get_json() or {}
    user_id = to_object_id(get_jwt_identity())
    db = get_db()

    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404

    attempt_count = db.attempts.count_documents({
        "student_id": user_id,
        "quiz_id": quiz["_id"],
    })
    if attempt_count >= quiz.get("max_attempts", 3):
        return jsonify({"message": "Đã hết lượt làm bài"}), 400

    questions = list(db.questions.find({"quiz_id": quiz["_id"]}))
    answers = data.get("answers", {})
    results = []
    total_points = 0
    earned_points = 0

    for q in questions:
        qid = str(q["_id"])
        answer = answers.get(qid)
        is_correct = grade_answer(q, answer)
        points = q.get("points", 1)
        total_points += points
        if is_correct:
            earned_points += points
        results.append({
            "question_id": qid,
            "answer": answer,
            "correct": is_correct,
            "correct_answer": q.get("correct_answer"),
            "explanation": q.get("explanation"),
        })

    score = round((earned_points / total_points) * 100) if total_points else 0
    passed = score >= quiz.get("passing_score", 60)

    attempt = {
        "student_id": user_id,
        "quiz_id": quiz["_id"],
        "lesson_id": quiz.get("lesson_id"),
        "answers": results,
        "score": score,
        "passed": passed,
        "time_taken_seconds": data.get("time_taken_seconds", 0),
        "created_at": utc_now(),
    }
    result = db.attempts.insert_one(attempt)
    attempt["_id"] = result.inserted_id

    return jsonify({
        "attempt": serialize_doc(attempt),
        "score": score,
        "passed": passed,
        "results": results,
    })


@quizzes_bp.route("/<quiz_id>/attempts", methods=["GET"])
@jwt_required()
def get_attempts(quiz_id):
    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    attempts = list(
        db.attempts.find({
            "quiz_id": to_object_id(quiz_id),
            "student_id": user_id,
        }).sort("created_at", -1)
    )
    return jsonify(serialize_doc(attempts))
