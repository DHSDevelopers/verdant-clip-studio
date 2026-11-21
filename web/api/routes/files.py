"""Upload and rendered-output endpoints."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024


def _output_path(job_id: str, filename: str | None = None) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    root = Path(OUTPUTS_DIR).resolve()
    job_dir = (root / job_id).resolve()
    if job_dir.parent != root:
        raise HTTPException(status_code=400, detail="Invalid job output directory")
    if filename is None:
        return job_dir
    if not filename or filename in {".", ".."} or any(ch in filename for ch in "/\\:\x00"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    candidate = (job_dir / filename).resolve()
    if candidate.parent != job_dir:
        raise HTTPException(status_code=400, detail="Invalid output path")
    return candidate


@router.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    allowed_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(allowed_exts))}",
        )

    safe_name = file.filename.replace(" ", "_")
    for ch in '<>:"/\\|?*#':
        safe_name = safe_name.replace(ch, "")
    safe_name = "".join(ch for ch in safe_name if ch.isprintable())[-180:]
    safe_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(UPLOAD_DIR, safe_name)

    total = 0
    try:
        with open(dest, "xb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 ** 3)}GB.",
                    )
                f.write(chunk)
        if not total:
            raise HTTPException(status_code=400, detail="Uploaded video is empty")
    except BaseException:
        if os.path.exists(dest):
            os.remove(dest)
        raise

    size_mb = total / (1024 * 1024)
    return {
        "filename": safe_name,
        "size_mb": round(size_mb, 2),
        "message": f"Upload complete: {safe_name} ({size_mb:.1f} MB)",
    }


@router.get("/api/outputs/{job_id}/{filename}")
async def serve_output(job_id: str, filename: str):
    file_path = _output_path(job_id, filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".webm": "video/webm",
        ".json": "application/json",
        ".ass": "text/plain; charset=utf-8",
        ".srt": "text/plain; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    return FileResponse(
        file_path,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=filename,
    )


@router.get("/api/outputs/{job_id}")
async def list_outputs(job_id: str) -> dict:
    job_dir = _output_path(job_id)
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="Job output directory not found")

    files = []
    for fname in sorted(os.listdir(job_dir)):
        try:
            fpath = _output_path(job_id, fname)
        except HTTPException:
            continue
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            files.append(
                {
                    "filename": fname,
                    "size_bytes": size,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "download_url": f"/api/outputs/{quote(job_id, safe='')}/{quote(fname, safe='')}",
                }
            )
    return {"job_id": job_id, "files": files, "total": len(files)}
