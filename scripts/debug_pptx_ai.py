"""Debug raw Gemini response for PPTX draft."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
from flask import Flask

load_dotenv(os.path.join(ROOT, ".env"))

app = Flask(__name__)
app.config["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
app.config["AI_PROVIDER"] = "gemini"

from app.services.ai_service import _call_ai
from app.services.studio_service import SYSTEM_TEACHER, _parse_json, _strip_json

prompt = """
Tạo outline slide PowerPoint JSON:
{
  "title": "...",
  "grade": "Lớp 6",
  "subject": "Experiential Learning",
  "topic": "Recycling in Daily Life",
  "slides": [
    {"title": "...", "bullets": ["...", "..."], "notes": "..."}
  ]
}

Số slide đúng khoảng 8. Mỗi slide 3-5 bullet ngắn.
Chỉ trả về JSON.
"""

OUT = os.path.join(ROOT, "scripts", "_studio_out")
os.makedirs(OUT, exist_ok=True)

with app.app_context():
    text, source = _call_ai(prompt, SYSTEM_TEACHER, max_tokens=3500, json_mode=True, timeout=90)
    raw_path = os.path.join(OUT, "pptx_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(text or "")
    print("source:", source)
    print("raw_len:", len(text or ""))
    print("saved:", raw_path)
    stripped = _strip_json(text or "")
    data = _parse_json(text or "")
    print("parsed:", bool(data), "slides:", len((data or {}).get("slides") or []) if data else 0)
    if not data and text:
        try:
            json.loads(stripped)
        except Exception as e:
            print("json error:", type(e).__name__, str(e)[:200])
            import re
            fixed = re.sub(r",\s*([}\]])", r"\1", stripped)
            try:
                data2 = json.loads(fixed)
                print("fixed OK slides:", len(data2.get("slides") or []))
            except Exception as e2:
                print("fixed fail:", type(e2).__name__, str(e2)[:200])
                # check if truncated
                print("ends_with:", repr(stripped[-80:]))
                print("brace_open:", stripped.count("{"), "close:", stripped.count("}"))
                print("brack_open:", stripped.count("["), "close:", stripped.count("]"))
