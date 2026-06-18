import os

import cloudinary.uploader
import cloudinary.utils
from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_AUDIO = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp3"}
ALLOWED_DOC = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _cloudinary_folder(subfolder: str) -> str:
    prefix = current_app.config.get("CLOUDINARY_FOLDER_PREFIX", "codung")
    return f"{prefix}/{subfolder}"


def _upload(file: FileStorage, resource_type: str, folder: str):
    if not file or not file.filename:
        return None
    original_name = secure_filename(file.filename) or "file"
    name, ext = os.path.splitext(original_name)
    ext = ext.lstrip(".").lower()
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    options = {
        "resource_type": resource_type,
        "folder": _cloudinary_folder(folder),
    }
    if resource_type == "raw":
        options["use_filename"] = True
        options["unique_filename"] = True
        options["filename_override"] = original_name
    # Video lớn: upload theo chunk để ổn định hơn
    if resource_type == "video" and size > 20 * 1024 * 1024:
        options["chunk_size"] = 6 * 1024 * 1024
    result = cloudinary.uploader.upload(file, **options)
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
