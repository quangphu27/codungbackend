"""MongoDB index definitions for all collections."""


def create_indexes(db):
  indexes = {
      "users": [
          [("email", 1), {"unique": True}],
          [("role", 1)],
          [("status", 1)],
          [("created_at", -1)],
      ],
      "teachers": [
          [("user_id", 1), {"unique": True}],
          [("subjects", 1)],
      ],
      "students": [
          [("user_id", 1), {"unique": True}],
          [("class_ids", 1)],
          [("grade", 1)],
      ],
      "classes": [
          [("teacher_id", 1)],
          [("subject_id", 1)],
          [("school_year", 1)],
          [("status", 1)],
          [("name", "text"), {"name": "class_text"}],
      ],
      "subjects": [
          [("name", 1)],
          [("status", 1)],
          [("difficulty_level", 1)],
          [("name", "text"), {"name": "subject_text"}],
      ],
      "lessons": [
          [("class_id", 1)],
          [("subject_id", 1)],
          [("teacher_id", 1)],
          [("status", 1)],
          [("order", 1)],
          [("title", "text"), {"name": "lesson_text"}],
      ],
      "lesson_sections": [
          [("lesson_id", 1)],
          [("section_type", 1)],
          [("lesson_id", 1), ("section_type", 1)],
      ],
      "vocabularies": [
          [("word", 1)],
          [("category", 1)],
          [("difficulty", 1)],
          [("lesson_id", 1)],
          [("word", "text"), {"name": "vocab_text"}],
      ],
      "quizzes": [
          [("lesson_id", 1)],
          [("class_id", 1)],
          [("teacher_id", 1)],
      ],
      "questions": [
          [("quiz_id", 1)],
          [("question_type", 1)],
      ],
      "attempts": [
          [("student_id", 1)],
          [("quiz_id", 1)],
          [("lesson_id", 1)],
          [("student_id", 1), ("quiz_id", 1)],
          [("created_at", -1)],
      ],
      "journals": [
          [("student_id", 1)],
          [("lesson_id", 1)],
          [("class_id", 1)],
          [("created_at", -1)],
      ],
      "activities": [
          [("topic", 1)],
          [("status", 1)],
          [("teacher_id", 1)],
      ],
      "career_tests": [
          [("teacher_id", 1)],
          [("status", 1)],
      ],
      "career_results": [
          [("student_id", 1)],
          [("test_id", 1)],
          [("created_at", -1)],
      ],
      "resources": [
          [("type", 1)],
          [("subject_id", 1)],
          [("teacher_id", 1)],
          [("title", "text"), {"name": "resource_text"}],
      ],
      "notifications": [
          [("user_id", 1)],
          [("read", 1)],
          [("created_at", -1)],
      ],
      "comments": [
          [("target_type", 1), ("target_id", 1)],
          [("author_id", 1)],
      ],
      "reports": [
          [("type", 1)],
          [("created_by", 1)],
          [("created_at", -1)],
      ],
      "settings": [
          [("key", 1), {"unique": True}],
      ],
      "practice_submissions": [
          [("student_id", 1)],
          [("lesson_id", 1)],
          [("status", 1)],
      ],
      "portfolios": [
          [("student_id", 1), {"unique": True}],
      ],
      "activity_logs": [
          [("user_id", 1)],
          [("action", 1)],
          [("created_at", -1)],
      ],
  }

  for collection_name, collection_indexes in indexes.items():
      collection = db[collection_name]
      for index_def in collection_indexes:
          if len(index_def) == 2 and isinstance(index_def[1], dict):
              keys, options = index_def
              key_list = keys if isinstance(keys, list) else [keys]
              collection.create_index(key_list, **options)
          else:
              keys = index_def[0] if len(index_def) == 1 else index_def
              key_list = keys if isinstance(keys, list) else [keys]
              collection.create_index(key_list)
