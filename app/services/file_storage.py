# app/services/file_storage.py
import os
import uuid
import shutil
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from ..models import File
from ..config import settings

# ✅ SADECE TEHLİKELİLERİ BLOKLA
DENIED_EXT = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr",
    ".ps1", ".vbs", ".js", ".jar",
    ".dll", ".sys",
    ".sh", ".bash",
    ".php", ".py", ".rb", ".pl",
    ".html", ".htm", ".svg",   # svg/html inline açılırsa XSS riski
}

def sanitize_filename(name: str) -> str:
    # path traversal / garip karakterleri temizle
    name = (name or "file").replace("\\", "_").replace("/", "_").strip()
    # çok uzun isimleri kısalt (DB/UI için)
    return name[:255] if len(name) > 255 else name

def save_uploaded_file(
    db: Session,
    upload: UploadFile,
    entity_type: str,
    entity_id: int,
) -> File:
    filename = sanitize_filename(upload.filename or "file")
    ext = os.path.splitext(filename)[1].lower()

    # uzantısı olmayan dosya da olabilir → izin ver
    if ext and ext in DENIED_EXT:
        raise HTTPException(status_code=400, detail=f"Bu dosya türü yüklenemez: {ext}")

    # (opsiyonel) boyut limiti - streaming ile hesaplamak için aşağıda size alıyoruz
    rel_dir = f"{entity_type}/{entity_id}"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    new_name = f"{uuid.uuid4().hex}{ext}" if ext else f"{uuid.uuid4().hex}"
    rel_path = f"{rel_dir}/{new_name}".replace("\\", "/")
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)

    # ✅ STREAMING WRITE
    with open(abs_path, "wb") as out:
        shutil.copyfileobj(upload.file, out)

    size = os.path.getsize(abs_path)

    # (opsiyonel) max size kontrolü (ör: 200MB)
    max_bytes = getattr(settings, "MAX_UPLOAD_BYTES", None)
    if max_bytes and size > max_bytes:
        # büyükse dosyayı silip hata ver
        try:
            os.remove(abs_path)
        except Exception:
            pass
        raise HTTPException(status_code=413, detail=f"Dosya çok büyük. Maks: {max_bytes} byte")

    file_row = File(
        entity_type=entity_type,
        entity_id=entity_id,
        original_name=filename,
        storage_path=rel_path,
        mime_type=upload.content_type,
        size_bytes=size,
    )
    db.add(file_row)
    db.flush()
    return file_row
