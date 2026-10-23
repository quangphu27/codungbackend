from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import random
from app.extensions import get_db, limiter
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

    if q_type in ("essay", "short_answer"):
        return None
    if q_type == "multiple_choice":
        return _mcq_match(answer, correct, question.get("options"))
    if q_type == "true_false":
        a = str(answer).strip().lower()
        c = str(correct).strip().lower()
        truthy = {"true", "đúng", "dung", "đung", "yes", "1"}
        falsy = {"false", "sai", "no", "0"}
        if a in truthy:
            a = "true"
        if a in falsy:
            a = "false"
        if c in truthy:
            c = "true"
        if c in falsy:
            c = "false"
        return a == c
    if q_type == "fill_blank":
        return str(answer).strip().lower() == str(correct).strip().lower()
    if q_type == "matching":
        return answer == correct
    if q_type == "ordering":
        return answer == correct
    return False


def _stem(q: dict) -> str:
    return str(
        (q or {}).get("question_text")
        or (q or {}).get("question")
        or (q or {}).get("prompt")
        or ""
    ).strip()


def load_quiz_questions(db, quiz_id):
    return list(db.questions.find({"quiz_id": quiz_id}).sort([("order", 1), ("_id", 1)]))


def insert_quiz_questions(db, quiz_id, questions):
    docs = []
    for i, q in enumerate(normalize_quiz_questions(questions)):
        docs.append({
            "quiz_id": quiz_id,
            "order": i,
            "question_text": q.get("question_text", ""),
            "question_type": q.get("question_type", "multiple_choice"),
            "options": q.get("options", []),
            "correct_answer": q.get("correct_answer"),
            "points": int(q.get("points", 1) or 1),
            "explanation": q.get("explanation", ""),
            "sample_answer": q.get("sample_answer") or "",
        })
    if docs:
        db.questions.insert_many(docs)
    return docs


def normalize_quiz_questions(questions):
    """Chuẩn hoá options + correct_answer để đáp án khớp một option."""
    normalized = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        q_type = q.get("question_type") or q.get("type") or "multiple_choice"
        if q_type in ("short_answer", "open", "tu_luan"):
            q_type = "essay"
        if q_type == "essay":
            text = _stem(q)
            if not text:
                continue
            normalized.append({
                "question_text": text,
                "question_type": "essay",
                "options": [],
                "correct_answer": str(q.get("correct_answer") or q.get("sample_answer") or "").strip(),
                "sample_answer": str(q.get("sample_answer") or q.get("correct_answer") or "").strip(),
                "points": int(q.get("points") or 2),
                "explanation": str(q.get("explanation") or ""),
            })
            continue
        if q_type in ("fill_blank", "fill-in", "fill_in", "dien_khuyet"):
            text = _stem(q)
            if not text:
                continue
            normalized.append({
                "question_text": text,
                "question_type": "fill_blank",
                "options": [],
                "correct_answer": str(q.get("correct_answer") or "").strip(),
                "sample_answer": "",
                "points": int(q.get("points") or 1),
                "explanation": str(q.get("explanation") or ""),
            })
            continue
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        correct = str(q.get("correct_answer") or "").strip()
        if q_type == "true_false":
            mapped = []
            for o in opts:
                low = o.lower().strip()
                if low in ("đúng", "dung", "true", "yes", "1"):
                    mapped.append("True")
                elif low in ("sai", "false", "no", "0"):
                    mapped.append("False")
                else:
                    mapped.append(o)
            opts = mapped or ["True", "False"]
            cl = correct.lower().strip()
            if cl in ("đúng", "dung", "true", "yes", "1"):
                correct = "True"
            elif cl in ("sai", "false", "no", "0"):
                correct = "False"
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
        text = _stem(q)
        if not text:
            continue
        normalized.append({
            "question_text": text,
            "question_type": q_type or "multiple_choice",
            "options": opts or (["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"] if q_type == "multiple_choice" else []),
            "correct_answer": correct,
            "points": int(q.get("points") or 1),
            "explanation": str(q.get("explanation") or ""),
            "sample_answer": str(q.get("sample_answer") or ""),
        })
    return [q for q in normalized if q["question_text"]]


def _guest_identity(data):
    name = str((data or {}).get("student_name") or "").strip()
    klass = str((data or {}).get("class_name") or "").strip()
    if len(name) < 2:
        return None, "Nhập họ và tên"
    if len(name) > 80:
        return None, "Họ và tên quá dài"
    if len(klass) < 1:
        return None, "Nhập lớp"
    if len(klass) > 40:
        return None, "Tên lớp quá dài"
    return {
        "student_name": name,
        "class_name": klass,
        "student_name_key": name.lower(),
        "class_name_key": klass.lower(),
    }, None


def _questions_without_answers(questions):
    out = []
    for q in serialize_doc(questions) or []:
        q.pop("correct_answer", None)
        q.pop("sample_answer", None)
        q.pop("explanation", None)
        out.append(q)
    return out


def _score_submission(questions, answers, passing_score=60):
    results = []
    total_points = 0
    earned_points = 0
    pending_review = False
    answers = answers or {}
    for q in questions:
        qid = str(q["_id"])
        answer = answers.get(qid)
        is_correct = grade_answer(q, answer)
        points = int(q.get("points", 1) or 1)
        total_points += points
        awarded = 0
        needs_review = is_correct is None
        if needs_review:
            pending_review = True
        elif is_correct:
            awarded = points
            earned_points += points
        results.append({
            "question_id": qid,
            "question_text": q.get("question_text"),
            "question_type": q.get("question_type"),
            "answer": answer,
            "correct": is_correct,
            "needs_review": needs_review,
            "points": points,
            "awarded_points": awarded,
            "correct_answer": q.get("correct_answer"),
            "sample_answer": q.get("sample_answer") or "",
            "explanation": q.get("explanation"),
        })
    score = round((earned_points / total_points) * 100) if total_points else 0
    passed = (not pending_review) and score >= int(passing_score or 60)
    return {
        "results": results,
        "score": score,
        "earned_points": earned_points,
        "total_points": total_points,
        "passed": passed,
        "pending_review": pending_review,
    }


def _public_quiz_payload(quiz, questions):
    qs = list(questions)
    if quiz.get("randomize"):
        random.shuffle(qs)
    data = serialize_doc(quiz)
    data.pop("teacher_id", None)
    data["questions"] = _questions_without_answers(qs)
    data["questions_count"] = len(qs)
    data["guest_entry"] = True
    return data


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

    questions = load_quiz_questions(db, quiz["_id"])
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
            q.pop("sample_answer", None)
            q.pop("explanation", None)
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
        "share_enabled": True,
        "created_at": utc_now(),
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id

    insert_quiz_questions(db, quiz_id, data.get("questions", []))

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
        "share_enabled": True,
        "language": data.get("language") or "en",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source": data.get("source") or "manual",
    }
    result = db.quizzes.insert_one(quiz)
    quiz_id = result.inserted_id

    insert_quiz_questions(db, quiz_id, questions)

    quiz["_id"] = quiz_id
    quiz_data = serialize_doc(quiz)
    quiz_data["questions"] = serialize_doc(load_quiz_questions(db, quiz_id))
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


@quizzes_bp.route("/<quiz_id>/public", methods=["GET"])
@limiter.limit("60 per minute")
def get_quiz_public(quiz_id):
    db = get_db()
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404
    questions = load_quiz_questions(db, quiz["_id"])
    return jsonify(_public_quiz_payload(quiz, questions))


@quizzes_bp.route("/<quiz_id>/guest-submit", methods=["POST"])
@limiter.limit("30 per hour")
def guest_submit_quiz(quiz_id):
    data = request.get_json() or {}
    identity, err = _guest_identity(data)
    if err:
        return jsonify({"message": err}), 400

    db = get_db()
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404

    attempt_count = db.attempts.count_documents({
        "quiz_id": quiz["_id"],
        "guest": True,
        "student_name_key": identity["student_name_key"],
        "class_name_key": identity["class_name_key"],
    })
    if attempt_count >= quiz.get("max_attempts", 3):
        return jsonify({"message": "Đã hết lượt làm bài"}), 400

    questions = load_quiz_questions(db, quiz["_id"])
    graded = _score_submission(questions, data.get("answers", {}), quiz.get("passing_score", 60))
    attempt = {
        "student_id": None,
        "guest": True,
        "student_name": identity["student_name"],
        "class_name": identity["class_name"],
        "student_name_key": identity["student_name_key"],
        "class_name_key": identity["class_name_key"],
        "quiz_id": quiz["_id"],
        "lesson_id": quiz.get("lesson_id"),
        "answers": graded["results"],
        "score": graded["score"],
        "earned_points": graded["earned_points"],
        "total_points": graded["total_points"],
        "passed": graded["passed"],
        "pending_review": graded["pending_review"],
        "time_taken_seconds": data.get("time_taken_seconds", 0),
        "created_at": utc_now(),
    }
    result = db.attempts.insert_one(attempt)
    attempt["_id"] = result.inserted_id
    return jsonify({
        "attempt": serialize_doc(attempt),
        "score": graded["score"],
        "passed": graded["passed"],
        "pending_review": graded["pending_review"],
        "results": graded["results"],
    })


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

    questions = load_quiz_questions(db, quiz["_id"])
    graded = _score_submission(questions, data.get("answers", {}), quiz.get("passing_score", 60))
    attempt = {
        "student_id": user_id,
        "guest": False,
        "quiz_id": quiz["_id"],
        "lesson_id": quiz.get("lesson_id"),
        "answers": graded["results"],
        "score": graded["score"],
        "earned_points": graded["earned_points"],
        "total_points": graded["total_points"],
        "passed": graded["passed"],
        "pending_review": graded["pending_review"],
        "time_taken_seconds": data.get("time_taken_seconds", 0),
        "created_at": utc_now(),
    }
    result = db.attempts.insert_one(attempt)
    attempt["_id"] = result.inserted_id

    return jsonify({
        "attempt": serialize_doc(attempt),
        "score": graded["score"],
        "passed": graded["passed"],
        "pending_review": graded["pending_review"],
        "results": graded["results"],
    })


@quizzes_bp.route("/<quiz_id>/attempts", methods=["GET"])
@jwt_required()
def get_attempts(quiz_id):
    from flask_jwt_extended import get_jwt

    db = get_db()
    user_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "student")
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404

    is_owner = role in ("teacher", "super_admin") and (
        role == "super_admin" or str(quiz.get("teacher_id")) == str(user_id)
    )
    query = {"quiz_id": quiz["_id"]}
    if not is_owner:
        query["student_id"] = user_id
    attempts = list(db.attempts.find(query).sort("created_at", -1))
    if is_owner:
        for a in attempts:
            if a.get("guest") or not a.get("student_id"):
                a["student"] = {
                    "full_name": a.get("student_name") or "Học sinh",
                    "email": None,
                    "class_name": a.get("class_name") or "",
                }
            else:
                student = db.users.find_one(
                    {"_id": a.get("student_id")},
                    {"full_name": 1, "email": 1},
                )
                a["student"] = serialize_doc(student) if student else None
    quiz_data = serialize_doc(quiz)
    if not is_owner:
        quiz_data.pop("hide_answers", None)
    return jsonify({
        "quiz": quiz_data,
        "attempts": serialize_doc(attempts),
        "is_owner": is_owner,
    })


@quizzes_bp.route("/<quiz_id>/attempts/<attempt_id>/grade", methods=["PUT"])
@jwt_required()
@teacher_required
def grade_attempt(quiz_id, attempt_id):
    from flask_jwt_extended import get_jwt

    db = get_db()
    teacher_id = to_object_id(get_jwt_identity())
    role = get_jwt().get("role", "teacher")
    quiz = db.quizzes.find_one({"_id": to_object_id(quiz_id)})
    if not quiz:
        return jsonify({"message": "Không tìm thấy bài kiểm tra"}), 404
    if role != "super_admin" and str(quiz.get("teacher_id")) != str(teacher_id):
        return jsonify({"message": "Không có quyền chấm đề này"}), 403

    attempt = db.attempts.find_one({
        "_id": to_object_id(attempt_id),
        "quiz_id": quiz["_id"],
    })
    if not attempt:
        return jsonify({"message": "Không tìm thấy bài làm"}), 404

    data = request.get_json() or {}
    grades = data.get("grades") or {}
    comment = (data.get("comment") or "").strip()
    answers = list(attempt.get("answers") or [])
    earned = 0
    total = 0
    pending = False
    for item in answers:
        qid = str(item.get("question_id") or "")
        points = int(item.get("points") or 1)
        total += points
        if qid in grades:
            try:
                awarded = max(0, min(points, int(grades[qid])))
            except (TypeError, ValueError):
                awarded = 0
            item["awarded_points"] = awarded
            item["needs_review"] = False
            item["correct"] = awarded >= points
            item["teacher_graded"] = True
        if item.get("needs_review"):
            pending = True
        earned += int(item.get("awarded_points") or 0)

    score = round((earned / total) * 100) if total else 0
    passed = (not pending) and score >= quiz.get("passing_score", 60)
    db.attempts.update_one(
        {"_id": attempt["_id"]},
        {"$set": {
            "answers": answers,
            "score": score,
            "earned_points": earned,
            "total_points": total,
            "passed": passed,
            "pending_review": pending,
            "teacher_comment": comment,
            "graded_at": utc_now(),
            "graded_by": teacher_id,
        }},
    )
    attempt.update({
        "answers": answers,
        "score": score,
        "passed": passed,
        "pending_review": pending,
        "teacher_comment": comment,
    })
    return jsonify({
        "message": "Đã lưu điểm chấm",
        "attempt": serialize_doc(attempt),
        "score": score,
        "passed": passed,
        "pending_review": pending,
    })
