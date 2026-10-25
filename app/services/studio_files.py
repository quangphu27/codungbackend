"""Cache Teacher Studio Word/PPTX on Cloudinary so later downloads skip rebuild."""
from __future__ import annotations

import hashlib
import io
import json
import urllib.request

import cloudinary
import cloudinary.uploader
from flask import current_app

from app.extensions import get_db
from app.utils.helpers import utc_now

CLOUDINARY_CLOUD = "dnqrhfnas"
CLOUDINARY_KEY = "295111514962362"
CLOUDINARY_SECRET = "tw1thR91iRrkFb2cGswzw2F2VXY"
CLOUDINARY_URL = f"cloudinary://{CLOUDINARY_KEY}:{CLOUDINARY_SECRET}@{CLOUDINARY_CLOUD}"


def ensure_cloudinary() -> None:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET,
        cloudinary_url=CLOUDINARY_URL,
        secure=True,
    )


def _stable_hash(kind: str, payload) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{kind}\n{raw}".encode("utf-8")).hexdigest()
    return digest[:40]


def _strip_cache_fields(payload):
    if not isinstance(payload, dict):
        return payload
    skip = {
        "file_url", "file_hash", "file_public_id", "file_bytes",
        "draft_id", "note", "source",
    }
    return {k: v for k, v in payload.items() if k not in skip}


def fetch_bytes(url: str) -> bytes | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EduBridgeStudio/1.0"})
        with urllib.request.urlopen(req, timeout=25) as res:
            data = res.read()
        if data and len(data) > 80:
            return data
    except Exception:
        current_app.logger.exception("studio file fetch failed")
    return None


def upload_raw_bytes(blob: bytes, filename: str, public_id: str) -> dict:
    ensure_cloudinary()
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()
    result = cloudinary.uploader.upload(
        io.BytesIO(blob),
        resource_type="raw",
        public_id=public_id,
        overwrite=True,
        format=ext,
        use_filename=False,
        unique_filename=False,
        filename_override=filename,
    )
    return {
        "url": result.get("secure_url") or result.get("url"),
        "public_id": result.get("public_id"),
        "bytes": result.get("bytes") or len(blob),
        "filename": filename,
        "format": result.get("format") or ext,
        "resource_type": "raw",
    }


def cached_url(kind: str, payload: dict) -> str | None:
    db = get_db()
    if db is None:
        return None
    file_hash = _stable_hash(kind, _strip_cache_fields(payload if isinstance(payload, dict) else {}))
    rec = db.studio_files.find_one({"hash": file_hash})
    return (rec or {}).get("url")


def ensure_studio_file(kind: str, payload: dict, filename: str, builder) -> dict:
    """Build Word/PPTX once per content hash, upload to Cloudinary, return cache metadata."""
    ensure_cloudinary()
    body = _strip_cache_fields(payload if isinstance(payload, dict) else {})
    file_hash = _stable_hash(kind, body)
    db = get_db()
    if db is not None:
        cached = db.studio_files.find_one({"hash": file_hash})
        if cached and cached.get("url"):
            current_app.logger.info("studio file cache hit %s %s", kind, file_hash)
            return {
                "file_url": cached["url"],
                "file_hash": file_hash,
                "file_public_id": cached.get("public_id"),
                "file_bytes": cached.get("bytes"),
            }

    blob = builder()
    if not blob:
        return {}
    try:
        meta = upload_raw_bytes(blob, filename, f"codung/studio/{kind}/{file_hash}")
        if db is not None and meta.get("url"):
            db.studio_files.update_one(
                {"hash": file_hash},
                {"$set": {
                    "hash": file_hash,
                    "kind": kind,
                    "url": meta["url"],
                    "public_id": meta.get("public_id"),
                    "filename": filename,
                    "bytes": meta.get("bytes"),
                    "updated_at": utc_now(),
                },
                    "$setOnInsert": {"created_at": utc_now()}},
                upsert=True,
            )
        return {
            "file_url": meta.get("url"),
            "file_hash": file_hash,
            "file_public_id": meta.get("public_id"),
            "file_bytes": meta.get("bytes") or len(blob),
        }
    except Exception:
        current_app.logger.exception("studio file upload failed")
        return {}


def fetch_studio_file_bytes(kind: str, payload: dict, file_url: str | None = None) -> bytes | None:
    """Download bytes from Cloudinary only — never rebuild."""
    url = file_url
    if not url and isinstance(payload, dict):
        url = payload.get("file_url")
    if url:
        data = fetch_bytes(url)
        if data:
            return data
    url = cached_url(kind, payload if isinstance(payload, dict) else {})
    if url:
        return fetch_bytes(url)
    return None


def get_or_build_file(kind: str, payload: dict, filename: str, builder) -> bytes:
    """Ensure file is on Cloudinary, then return cached bytes (used in tests/scripts)."""
    meta = ensure_studio_file(kind, payload, filename, builder)
    data = fetch_studio_file_bytes(kind, payload, meta.get("file_url"))
    if data:
        return data
    blob = builder()
    if not blob:
        return blob
    current_app.logger.warning("studio file fetch failed after ensure %s", kind)
    return blob
