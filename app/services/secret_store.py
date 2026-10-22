"""Encrypt/decrypt admin-managed API keys stored in MongoDB.

Uses Fernet (AES-128-CBC + HMAC). The Fernet key is derived from SECRET_KEY
so existing deployments do not need a new env var. Keys are never returned
in full via API — only a masked preview.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

GEMINI_SETTING_KEY = "gemini_api_key_enc"
OPENAI_SETTING_KEY = "openai_api_key_enc"
PLACEHOLDER_KEYS = {"", "your-gemini-api-key", "your-openai-api-key"}


def _fernet() -> Fernet:
    secret = (
        current_app.config.get("SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or "dev-secret-key"
    )
    digest = hashlib.sha256(str(secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.strip().encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def mask_secret(plain: str | None) -> str:
    if not plain:
        return ""
    text = plain.strip()
    if len(text) <= 8:
        return "••••••••"
    return f"{text[:4]}••••{text[-4:]}"


def _db_encrypted(setting_key: str) -> str | None:
    try:
        from app.extensions import get_db
        db = get_db()
        if db is None:
            return None
        doc = db.settings.find_one({"key": setting_key})
        if not doc:
            return None
        value = doc.get("value") or ""
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def get_gemini_api_key() -> str | None:
    enc = _db_encrypted(GEMINI_SETTING_KEY)
    if enc:
        plain = decrypt_secret(enc)
        if plain and plain not in PLACEHOLDER_KEYS:
            return plain
    env = current_app.config.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    if env and env not in PLACEHOLDER_KEYS:
        return env
    return None


def get_openai_api_key() -> str | None:
    enc = _db_encrypted(OPENAI_SETTING_KEY)
    if enc:
        plain = decrypt_secret(enc)
        if plain and plain not in PLACEHOLDER_KEYS:
            return plain
    env = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    if env and env not in PLACEHOLDER_KEYS:
        return env
    return None


def gemini_is_configured() -> bool:
    return bool(get_gemini_api_key())
