# app/services/file_storage.py
import os
import uuid
from fastapi import UploadFile
from sqlalchemy.orm import Session
from ..models import File
from ..config import settings

ALLOWED_EXT = {".dxf", ".pdf", ".png", ".jpg", ".jpeg", ".step", ".stp"}

def save_uploaded_file(
    db: Session,
    upload: UploadFile,
    entity_type: str,
    entity_id: int,
) -> File:
    filename = upload.filename or "file"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXT:
        raise ValueError(f"Unsupported file type: {ext}")

    # storage path: die/12/<uuid>.dxf
    rel_dir = f"{entity_type}/{entity_id}"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    new_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = f"{rel_dir}/{new_name}".replace("\\", "/")
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

    # dosyayı kaydet
    with open(abs_path, "wb") as out:
        out.write(upload.file.read())

    file_row = File(
        entity_type=entity_type,
        entity_id=entity_id,
        original_name=filename,
        storage_path=rel_path,
        mime_type=upload.content_type,
        size_bytes=os.path.getsize(abs_path),
    )
    db.add(file_row)
    db.flush()
    return file_row
