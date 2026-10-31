"""Per-subject PowerPoint prompts — EDUBRIDGE EMI/CLIL V4.0 (from DOC-20261030-WA0002_1.docx)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "pptx_subject_prompts_v4.json"

_PROFILE_ALIASES = {
    "literature_kieu": "literature",
    "english": "general",
    "experiential": "general",
    "natural_science": "biology",
    "pe": "general",
    "art": "general",
    "music": "general",
    "general": "general",
}

_KIEU_EXTRA = (
    "TRUYỆN KIỀU / NGỮ VĂN: Nguyễn Du, thể lục bát, nhân vật Thúy Kiều–Kim Trọng–Hoạn Thư; "
    "slide = bằng chứng thơ, diễn giải đoạn trích — không bịa sự kiện ngoài tác phẩm."
)


@lru_cache(maxsize=1)
def _catalog() -> dict:
    if not _DATA_PATH.is_file():
        return {"global_pptx_rules": "", "subjects": {}}
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _condense_subject_body(text: str, max_chars: int = 2200) -> str:
    if len(text) <= max_chars:
        return text
    chunks: list[str] = []
    for block in re.split(r"(?=II\.|III\.|IV\.|VII\.|IX\.)", text):
        block = block.strip()
        if not block:
            continue
        head = block.split("\n", 1)[0]
        if any(head.startswith(p) for p in ("III.", "IV.", "VII.", "IX.", "TRỌNG TÂM")):
            chunks.append(block)
    merged = "\n\n".join(chunks).strip()
    if len(merged) > max_chars:
        merged = merged[: max_chars - 20].rstrip() + "\n… (rút gọn V4)"
    return merged or text[:max_chars]


def subject_pptx_v4_prompt(profile: str, *, light: bool = False) -> str:
    """Prompt chuyên sâu PPT theo môn (V4.0)."""
    cat = _catalog()
    global_rules = (cat.get("global_pptx_rules") or "").strip()
    key = _PROFILE_ALIASES.get(profile, profile)
    subj = (cat.get("subjects") or {}).get(key)
    if not subj and key != "general":
        subj = (cat.get("subjects") or {}).get("math")
    body = (subj or {}).get("prompt_en_clil") or ""
    if light:
        body = _condense_subject_body(body, 1800)
    elif len(body) > 4800:
        body = _condense_subject_body(body, 4800)
    extra = ""
    if profile == "literature_kieu":
        extra = _KIEU_EXTRA
    parts = [p for p in (global_rules, extra, body) if p]
    return "\n\n".join(parts)


def subject_pptx_focus(profile: str) -> str:
    cat = _catalog()
    key = _PROFILE_ALIASES.get(profile, profile)
    subj = (cat.get("subjects") or {}).get(key) or {}
    return str(subj.get("focus") or "").strip()
