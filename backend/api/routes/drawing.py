"""Drawing video routes."""
from __future__ import annotations

import json
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse

from pipeline.drawing.jobs import artifact, cancel, create_job, get_job, list_jobs, remove, start, start_batch, update_options
from pipeline.core.output_paths import downloads_folder

router = APIRouter()
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class StartDrawingJobsIn(BaseModel):
    ids: list[str] = []


@router.get("/api/drawing/jobs")
def drawing_jobs():
    return list_jobs()


@router.post("/api/drawing/jobs")
async def drawing_create(image: UploadFile = File(...), options: str = Form("{}")):
    suffix = Path(image.filename or "image.png").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, "Unsupported image type")
    try:
        parsed = json.loads(options)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid drawing options") from exc
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        temp = Path(handle.name)
        shutil.copyfileobj(image.file, handle)
    try:
        job = create_job(image.filename or "image", temp, parsed if isinstance(parsed, dict) else {})
    finally:
        temp.unlink(missing_ok=True)
    start(job["id"])
    return job


@router.post("/api/drawing/jobs/batch")
async def drawing_create_batch(images: list[UploadFile] = File(...), options: str = Form("{}"), start_now: bool = Form(True)):
    if not images:
        raise HTTPException(400, "No images supplied")
    if len(images) > 100:
        raise HTTPException(400, "Batch is limited to 100 images")
    try:
        parsed = json.loads(options)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid drawing options") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, "Invalid drawing options")
    jobs = []
    for image in images:
        suffix = Path(image.filename or "image.png").suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(400, f"Unsupported image type: {image.filename or 'file'}")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp = Path(handle.name)
            shutil.copyfileobj(image.file, handle)
        try:
            jobs.append(create_job(image.filename or "image", temp, parsed))
        finally:
            temp.unlink(missing_ok=True)
    if start_now:
        start_batch([job["id"] for job in jobs])
    return {"jobs": jobs, "mode": "parallel", "started": start_now}


@router.post("/api/drawing/jobs/start")
def drawing_start_jobs(body: StartDrawingJobsIn):
    ids = [job_id for job_id in body.ids if get_job(job_id) and get_job(job_id).get("status") == "queued"]
    if not ids:
        raise HTTPException(422, "No queued drawing jobs")
    start_batch(ids)
    return {"ok": True, "ids": ids}


@router.get("/api/drawing/jobs/{job_id}")
def drawing_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Drawing job not found")
    return job


@router.post("/api/drawing/jobs/{job_id}/cancel")
def drawing_cancel(job_id: str):
    if not cancel(job_id):
        raise HTTPException(404, "Drawing job not found")
    return {"ok": True}


@router.patch("/api/drawing/jobs/{job_id}")
async def drawing_update(job_id: str, options: dict):
    try:
        job = update_options(job_id, options)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not job:
        raise HTTPException(404, "Drawing job not found")
    return job


@router.delete("/api/drawing/jobs/{job_id}")
def drawing_delete(job_id: str):
    if not remove(job_id):
        raise HTTPException(404, "Drawing job not found")
    return {"ok": True}


@router.get("/api/drawing/jobs/{job_id}/{kind}")
def drawing_artifact(job_id: str, kind: str):
    path = artifact(job_id, kind)
    if not path:
        raise HTTPException(404, "Drawing artifact not ready")
    media = "video/mp4" if kind == "output" else "image/png"
    return FileResponse(path, media_type=media, filename=path.name)


@router.post("/api/drawing/jobs/{job_id}/reveal")
def drawing_reveal(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Không thấy job")
    path = Path(str(job.get("publishedOutput") or job.get("output") or ""))
    folder = path.parent if path.is_file() else downloads_folder("drawing")
    try:
        if sys.platform == "win32" and path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        raise HTTPException(500, f"Không mở được thư mục: {exc}") from exc
    return {"ok": True, "path": str(path if path.is_file() else folder)}
