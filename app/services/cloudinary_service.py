import io
import os
import re

import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils
from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

LIBRARY_MAX_BYTES = 50 * 1024 * 1024

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_AUDIO = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp3"}
ALLOWED_DOC = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-excel",
    "text/plain",
    "application/zip",
}


def _cloudinary_folder(subfolder: str) -> str:
    prefix = current_app.config.get("CLOUDINARY_FOLDER_PREFIX", "codung")
    return f"{prefix}/{subfolder}"


def _ensure_cloudinary_configured() -> None:
    try:
        from app.services.studio_files import ensure_cloudinary
        ensure_cloudinary()
    except Exception:
        url = current_app.config.get("CLOUDINARY_URL") or os.getenv("CLOUDINARY_URL")
        if url:
            cloudinary.config(cloudinary_url=url, secure=True)


def _safe_filename(raw: str) -> str:
    name = secure_filename(raw or "") or ""
    if name and name != "file":
        return name
    base = re.sub(r"[^\w.\-]+", "_", (raw or "file").strip()) or "file"
    return base[:180]


def _upload(file: FileStorage, resource_type: str, folder: str):
    if not file or not file.filename:
        return None
    _ensure_cloudinary_configured()
    original_name = _safe_filename(file.filename)
    name, ext = os.path.splitext(original_name)
    ext = ext.lstrip(".").lower()
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size <= 0:
        raise ValueError("File rỗng hoặc không đọc được")
    if folder == "library" and size > LIBRARY_MAX_BYTES:
        mb = max(1, int(size / (1024 * 1024)))
        raise ValueError(f"File quá lớn ({mb} MB). Kho học liệu giới hạn 50 MB mỗi file.")
    payload = file.read()
    if not payload:
        raise ValueError("Không đọc được nội dung file")
    upload_source = io.BytesIO(payload)
    options = {
        "resource_type": resource_type,
        "folder": _cloudinary_folder(folder),
    }
    if resource_type == "raw":
        options["use_filename"] = True
        options["unique_filename"] = True
        options["filename_override"] = original_name
        if ext:
            options["format"] = ext
    # Video lớn: upload theo chunk để ổn định hơn
    if resource_type == "video" and size > 20 * 1024 * 1024:
        options["chunk_size"] = 6 * 1024 * 1024
    try:
        result = cloudinary.uploader.upload(upload_source, **options)
    except cloudinary.exceptions.Error as exc:
        msg = str(exc).lower()
        if "too large" in msg or "file size" in msg:
            raise ValueError(
                "File vượt giới hạn Cloudinary. Hãy nén PowerPoint/PDF hoặc tách file nhỏ hơn."
            ) from exc
        if "invalid" in msg and "api" in msg:
            raise ValueError("Cấu hình Cloudinary trên server chưa đúng. Liên hệ quản trị.") from exc
        raise ValueError(f"Cloudinary từ chối upload: {exc}") from exc
    fmt = result.get("format") or ext or None
    public_id = result.get("public_id", "")
    url = result.get("secure_url")
    if resource_type == "raw" and fmt and public_id and not public_id.endswith(f".{fmt}"):
        built = cloudinary.utils.cloudinary_url(
            f"{public_id}.{fmt}",
            resource_type="raw",
            secure=True,
        )
        url = built[0] if isinstance(built, tuple) else built
    return {
        "url": url,
        "public_id": public_id,
        "format": fmt,
        "bytes": result.get("bytes"),
        "filename": original_name,
        "resource_type": resource_type,
    }


def upload_image(file: FileStorage, folder: str = "images"):
    if file.content_type not in ALLOWED_IMAGE:
        raise ValueError("Định dạng ảnh không được hỗ trợ")
    return _upload(file, "image", folder)


def upload_video(file: FileStorage, folder: str = "videos"):
    allowed = ALLOWED_VIDEO | {"video/x-msvideo", "application/octet-stream"}
    if file.content_type not in allowed and not (file.filename or "").lower().endswith((".mp4", ".webm", ".mov", ".avi")):
        raise ValueError("Định dạng video không được hỗ trợ (MP4, WebM, MOV)")
    return _upload(file, "video", folder)


def upload_audio(file: FileStorage, folder: str = "audio"):
    if file.content_type not in ALLOWED_AUDIO:
        raise ValueError("Định dạng âm thanh không được hỗ trợ")
    return _upload(file, "video", folder)


def upload_document(file: FileStorage, folder: str = "documents"):
    if file.content_type not in ALLOWED_DOC and file.content_type not in ALLOWED_IMAGE:
        raise ValueError("Định dạng tài liệu không được hỗ trợ")
    resource_type = "raw" if file.content_type in ALLOWED_DOC else "image"
    return _upload(file, resource_type, folder)


_LIBRARY_EXT = (
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".txt", ".zip", ".jpg", ".jpeg", ".png",
)


def upload_library_material(file: FileStorage, folder: str = "library"):
    """Tài liệu admin tải lên Kho học liệu (raw trên Cloudinary)."""
    if not file or not file.filename:
        raise ValueError("Thiếu file")
    name = (file.filename or "").lower()
    ok_type = file.content_type in ALLOWED_DOC or file.content_type in ALLOWED_IMAGE
    ok_ext = any(name.endswith(ext) for ext in _LIBRARY_EXT)
    if not ok_type and not ok_ext:
        raise ValueError("Định dạng không hỗ trợ (PDF, Word, PowerPoint, Excel, ảnh, ZIP...)")
    resource_type = "image" if file.content_type in ALLOWED_IMAGE or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")) else "raw"
    meta = _upload(file, resource_type, folder)
    if not meta or not meta.get("url"):
        raise ValueError("Upload không trả về URL — thử lại hoặc kiểm tra Cloudinary.")
    return meta


def delete_file(public_id: str, resource_type: str = "image"):
    if public_id:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)


def guess_filename(file_meta: dict, index: int = 0) -> str:
    if file_meta.get("filename"):
        return file_meta["filename"]
    fmt = file_meta.get("format")
    if fmt:
        return f"file_{index + 1}.{fmt}"
    return f"file_{index + 1}"


def prepare_file_meta(file_meta: dict, index: int = 0) -> dict:
    if not file_meta:
        return file_meta
    meta = dict(file_meta)
    meta["filename"] = guess_filename(meta, index)
    if not meta.get("resource_type"):
        name = meta["filename"].lower()
        if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            meta["resource_type"] = "image"
        elif name.endswith((".mp4", ".webm", ".mov", ".avi")):
            meta["resource_type"] = "video"
        else:
            meta["resource_type"] = "raw"
    return meta


def prepare_files_list(files):
    return [prepare_file_meta(f, i) for i, f in enumerate(files or [])]
