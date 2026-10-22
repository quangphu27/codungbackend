from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import random
from app.extensions import get_db
from app.utils.helpers import serialize_doc, utc_now, to_object_id
from app.middlewares.auth import teacher_required

quizzes_bp = Blueprint("quizzes", __name__)


def _mcq_match(answer, correct, options=None):
    """So khớp đáp án trắc nghiệm linh hoạt (A / A. text / full option)."""
    a = str(answer or "").strip()
    c = str(correct or "").strip()
    if not a or not c:
        return False
    if a == c:
        return True
    if a.lower() == c.lower():
        return True

    def _letter(s):
        s = s.strip()
        if not s:
            return ""
        ch = s[0].upper()
        if ch in "ABCD" and (len(s) == 1 or s[1] in ".) :" ):
            return ch
        return ""

    la, lc = _letter(a), _letter(c)
    if la and lc and la == lc:
        return True
    if la and options:
        for opt in options:
            if str(opt).strip().upper().startswith(la) and (
                len(str(opt).strip()) == 1 or str(opt).strip()[1] in ".) :"
            ):
                return str(opt).strip() == c or _letter(str(opt)) == lc
    return False


def grade_answer(question, answer):
    q_type = question.get("question_type")
    correct = question.get("correct_answer")

    if q_type == "multiple_choice":
        return _mcq_match(answer, correct, question.get("options"))
    if q_type == "true_false":
        return str(answer).lower() == str(correct).lower()
    if q_type == "fill_blank":
        return str(answer).strip().lower() == str(correct).strip().lower()
    if q_type == "matching":
        return answer == correct
    if q_type == "ordering":
        return answer == correct
    return False


def normalize_quiz_questions(questions):
    """Chuẩn hoá options + correct_answer để đáp án khớp một option."""
    normalized = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        correct = str(q.get("correct_answer") or "").strip()
        if opts and correct and correct not in opts:
            letter = correct[0].upper() if correct else ""
            matched = None
            if letter in "ABCD":
                for o in opts:
                    ou = o.upper().lstrip()
                    if ou.startswith(letter + ".") or ou.startswith(letter + ")") or ou == letter:
                        matched = o
                        break
                if not matched:
                    idx = ord(letter) - ord("A")
                    if 0 <= idx < len(opts):
                        matched = opts[idx]
            if not matched:
                matched = next(
                    (o for o in opts if correct.lower() in o.lower() or o.lower() in correct.lower()),
                    opts[0],
                )
            correct = matched
        if not correct and opts:
            correct = opts[0]
        normalized.append({
            "question_text": str(q.get("question_text") or "").strip(),
            "question_type": q.get("question_type") or "multiple_choice",
            "options": opts or ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"],
            "correct_answer": correct,
            "points": int(q.get("points") or 1),
            "explanation": str(q.get("explanation") or ""),
        })
    return [q for q in normalized if q["question_text"]]


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
    from flask_jwt_extended import get_jwt

    db = get_db()
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404

    questions = list(db.questions.find({"quiz_id": quiz["_id"]}))
    role = get_jwt().get("role", "student")
    # Giáo viên/admin xem đáp án để sửa; học sinh làm bài thì ẩn
    reveal_answers = role in ("teacher", "super_admin") or request.args.get("include_answers") == "1"

    if quiz.get("randomize") and not reveal_answers:
        random.shuffle(questions)

    quiz_data = serialize_doc(quiz)
    quiz_data["questions"] = serialize_doc(questions)
    if quiz.get("hide_answers") and not reveal_answers:
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

    for q in normalize_quiz_questions(data.get("questions", [])):
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


def _replace_lesson_quiz(db, lesson_id, teacher_id, data, role: str = "teacher"):
    """Xóa quiz cũ của bài học (nếu có) rồi tạo quiz mới kèm câu hỏi."""
    from flask_jwt_extended import get_jwt

    lesson_oid = to_object_id(lesson_id)
    if not lesson_oid:
        return None, ("lesson_id không hợp lệ", 400)

    lesson = db.lessons.find_one({"_id": lesson_oid})
    if not lesson:
        return None, ("Không tìm thấy bài học", 404)

    role = role or get_jwt().get("role", "teacher")
    if role != "super_admin":
        owner = lesson.get("teacher_id")
        if owner and to_object_id(str(owner)) != to_object_id(str(teacher_id)):
            return None, ("Bạn không có quyền gắn đề vào bài học này", 403)

    for old in db.quizzes.find({"lesson_id": lesson_oid}):
        db.questions.delete_many({"quiz_id": old["_id"]})
        db.attempts.delete_many({"quiz_id": old["_id"]})
        db.quizzes.delete_one({"_id": old["_id"]})

    questions = normalize_quiz_questions(data.get("questions") or [])
    if not questions:
        return None, ("Cần ít nhất 1 câu hỏi", 400)

    quiz = {
        "title": data.get("title") or f"Kiểm tra: {lesson.get('title', '')}",
        "lesson_id": lesson_oid,
        "class_id": to_object_id(data.get("class_id")) if data.get("class_id") else lesson.get("class_id"),
        "teacher_id": teacher_id,
        "time_limit_minutes": int(data.get("time_limit_minutes", 30)),
        "randomize": data.get("randomize", True),
        "max_attempts": int(data.get("max_attempts", 3)),
        "passing_score": int(data.get("passing_score", 60)),
        "hide_answers": True,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source": data.get("source") or "manual",
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id

    for q in questions:
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
    quiz_data = serialize_doc(quiz)
    quiz_data["questions"] = serialize_doc(list(db.questions.find({"quiz_id": quiz_id})))
    quiz_data["questions_count"] = len(questions)
    return quiz_data, None


@quizzes_bp.route("/attach-to-lesson", methods=["POST"])
@jwt_required()
@teacher_required
def attach_quiz_to_lesson():
    """Gắn / thay đề kiểm tra vào bài học (dùng cho đề AI hoặc form thủ công)."""
    from flask_jwt_extended import get_jwt

    data = request.get_json() or {}
    lesson_id = data.get("lesson_id")
    if not lesson_id:
        return jsonify({"message": "Thiếu lesson_id"}), 400

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "teacher")
    quiz_data, err = _replace_lesson_quiz(db, lesson_id, teacher_id, data, role=role)
    if err:
        return jsonify({"message": err[0]}), err[1]
    return jsonify({"message": "Đã gắn đề vào bài học", "quiz": quiz_data}), 201


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
