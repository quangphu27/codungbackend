"""Test Gemini + DOCX/PPTX pipeline for Teacher Studio."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

key = os.getenv("GEMINI_API_KEY") or ""
print(f"GEMINI key: prefix={key[:10]!r} len={len(key)}")

MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
]


def try_gemini():
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": 'Reply JSON only: {"ok": true, "msg": "hello"}'}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }).encode()
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as res:
                data = json.loads(res.read())
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"MODEL OK: {model} -> {text[:100]}")
                return True
        except Exception as e:
            print(f"MODEL FAIL: {model} -> {str(e)[:200]}")
    return False


def test_exports():
    # Import builders without full Flask app init by loading module file pieces
    from pptx import Presentation
    from docx import Document
    import io

    # Minimal DOCX
    doc = Document()
    doc.add_heading("Test Giao an", 0)
    doc.add_paragraph("Noi dung thu nghiem Teacher Studio")
    buf = io.BytesIO()
    doc.save(buf)
    print(f"DOCX bytes: {len(buf.getvalue())}")

    # Minimal PPTX
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, prs.slide_width, 1000000)
    box.text_frame.paragraphs[0].text = "Slide test"
    buf2 = io.BytesIO()
    prs.save(buf2)
    print(f"PPTX bytes: {len(buf2.getvalue())}")


if __name__ == "__main__":
    ok = try_gemini()
    print("Gemini usable:", ok)
    test_exports()
    print("DONE")
