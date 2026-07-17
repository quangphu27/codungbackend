"""Seed experiential activity articles if collection is empty."""
from datetime import datetime, timezone
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

uri = os.getenv("MONGODB_URI")
if not uri:
    raise RuntimeError("MONGODB_URI not set")

db_name = uri.rsplit("/", 1)[-1].split("?", 1)[0]
db = MongoClient(uri)[db_name]
now = datetime.now(timezone.utc)

ITEMS = [
    {
        "title": "Sharing Vietnamese Culture with the World",
        "subtitle": "Giới thiệu văn hóa Việt Nam với thế giới",
        "topic": "vietnamese_culture",
        "icon": "🏮",
        "order": 1,
        "introduction": (
            "Vietnam has a rich and diverse culture that reflects the nation's history, traditions, and identity. "
            "In this experiential activity, students will explore different aspects of Vietnamese culture and use English "
            "to introduce them to others. Through teamwork, discussions, and creative presentations, students will develop "
            "communication skills while becoming more confident and proud of their cultural heritage."
        ),
        "status": "published",
    },
    {
        "title": "Protecting the Environment for a Better Future",
        "subtitle": "Bảo vệ môi trường vì một tương lai tốt đẹp hơn",
        "topic": "environmental_protection",
        "icon": "🌿",
        "order": 2,
        "introduction": (
            "The environment plays an essential role in our lives, providing clean air, water, and natural resources. "
            "However, pollution, climate change, and waste are becoming serious global challenges. In this experiential activity, "
            "students will explore environmental issues, learn about sustainable habits, and work together to develop practical "
            "solutions for protecting the environment. By using English in real-life situations, students will improve their "
            "communication skills while becoming responsible and environmentally conscious citizens."
        ),
        "status": "published",
    },
    {
        "title": "Small Actions, Big Impact",
        "subtitle": "Hành động nhỏ – Tác động lớn",
        "topic": "community_service",
        "icon": "🤝",
        "order": 3,
        "introduction": (
            "Every small act of kindness can make a big difference in our community. In this experiential activity, students will "
            "discover how simple actions, such as helping others, volunteering, and protecting public spaces, can create a positive "
            "impact. Through teamwork and hands-on activities, students will use English to communicate, share ideas, and reflect on "
            "the importance of community service. This activity encourages students to become responsible, caring, and active citizens "
            "who contribute to a better society."
        ),
        "status": "published",
    },
    {
        "title": "Promoting Local Tourism",
        "subtitle": "Quảng bá du lịch địa phương",
        "topic": "local_tourism",
        "icon": "🗺️",
        "order": 4,
        "introduction": (
            "Every community has unique places, traditions, and stories that deserve to be shared. In this experiential activity, "
            "students will explore local tourist attractions, cultural heritage, traditional cuisine, and natural beauty. They will "
            "use English to introduce their hometown through presentations, videos, travel brochures, or guided tours. This activity "
            "helps students improve their English communication skills while developing a sense of pride and responsibility for "
            "promoting local tourism and preserving local values."
        ),
        "status": "published",
    },
    {
        "title": "The Colors of Vietnamese Festivals",
        "subtitle": "Sắc màu lễ hội Việt Nam",
        "topic": "traditional_festivals",
        "icon": "🎊",
        "order": 5,
        "introduction": (
            "Vietnamese festivals are a colorful reflection of the nation's history, traditions, and cultural identity. "
            "In this experiential activity, students will explore the unique customs, symbols, costumes, traditional games, music, "
            "and foods associated with different festivals across Vietnam. Through interactive activities, group discussions, and "
            "creative presentations in English, students will discover the beauty and significance of these celebrations while "
            "developing their communication skills. This activity also encourages students to appreciate, preserve, and proudly share "
            "Vietnam's rich cultural heritage with others."
        ),
        "status": "published",
    },
    {
        "title": "Healthy Habits, Happy Life",
        "subtitle": "Thói quen tốt – Cuộc sống vui khỏe",
        "topic": "healthy_lifestyle",
        "icon": "🤝",
        "order": 6,
        "introduction": (
            "Healthy habits are the foundation of a happy and balanced life. In this experiential activity, students will explore "
            "the importance of healthy eating, regular exercise, personal hygiene, mental well-being, and good daily routines. "
            "Through interactive activities, discussions, and real-life practice in English, students will learn how small positive "
            "habits can improve their health and quality of life. This activity encourages students to make healthy choices and build "
            "lifelong habits for a happier future."
        ),
        "status": "published",
    },
]

if __name__ == "__main__":
    count = db.activities.count_documents({})
    if count > 0:
        print(f"Activities already exist: {count} - skipped seed")
    else:
        for item in ITEMS:
            db.activities.insert_one({
                **item,
                "vocabulary": [],
                "reading": {},
                "video": {},
                "activities": [],
                "quiz_id": None,
                "teacher_id": None,
                "created_at": now,
                "updated_at": now,
            })
        print(f"Seeded {len(ITEMS)} activities")
