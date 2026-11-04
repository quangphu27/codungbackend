"""Smoke test: POST /studio/library/upload with multiple files (mocked Cloudinary/DB)."""
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from bson import ObjectId

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask_jwt_extended import create_access_token

from app import create_app  # noqa: E402


def main() -> int:
    app = create_app()
    app.config["TESTING"] = True
    admin_id = ObjectId()
    fake_user = {"_id": admin_id, "full_name": "Admin Test"}
    def fake_save(db, upload, **kw):
        return {
            "id": str(ObjectId()),
            "kind": "file",
            "title": upload.filename,
            "filename": upload.filename,
        }

    with app.app_context():
        token = create_access_token(
            identity=str(admin_id),
            additional_claims={"role": "super_admin", "email": "admin@test"},
        )
        with patch("app.routes.studio.get_db") as gdb:
            db = MagicMock()
            db.users.find_one.return_value = fake_user
            gdb.return_value = db
            with patch("app.routes.studio._ensure_library_catalog"):
                with patch(
                    "app.routes.studio._library_save_uploaded_file",
                    side_effect=fake_save,
                ):
                    client = app.test_client()
                    form = {
                        "grade": "Lớp 10",
                        "subject": "Toán học",
                        "topic": "Chương 1",
                    }
                    data = {
                        **form,
                        "file": [
                            (io.BytesIO(b"a" * 10), "a.pdf"),
                            (io.BytesIO(b"b" * 10), "b.pdf"),
                            (io.BytesIO(b"c" * 10), "c.pdf"),
                        ],
                    }
                    r = client.post(
                        "/api/studio/library/upload",
                        data=data,
                        content_type="multipart/form-data",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    j = r.get_json() or {}
                    print("status:", r.status_code)
                    print("message:", j.get("message"))
                    print("items:", len(j.get("items") or []))
                    print("errors:", j.get("errors"))
                    if r.status_code != 201:
                        return 1
                    if len(j.get("items") or []) != 3:
                        return 1
                    if j.get("errors"):
                        return 1
                    print("OK multi-file upload")
                    return 0


if __name__ == "__main__":
    raise SystemExit(main())
