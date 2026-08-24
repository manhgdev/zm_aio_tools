"""Google Flow account and generation API."""
from __future__ import annotations

import shutil
import subprocess
import sys
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pipeline.flow import service
from pipeline.flow import store

router = APIRouter(prefix="/api/flow", tags=["flow"])


class AccountIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=160)
    plan: str = Field(default="Pro", pattern="^(Pro|Ultra)$")
    projectId: str = Field(default="", max_length=160)
    isDefault: bool = False


class GenerateIn(BaseModel):
    prompts: list[str] = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(image|video)$")
    mode: str = Field(default="text", pattern="^(text|edit|reference|frame)$")
    accountId: str
    settings: dict[str, Any] = {}
    sourceFiles: list[str] = []


@router.get("/accounts")
def accounts_list():
    return {"accounts": service.accounts()}


@router.post("/accounts")
def accounts_create(body: AccountIn):
    return service.save_account(body.model_dump())


@router.put("/accounts/{account_id}")
def accounts_update(account_id: str, body: AccountIn):
    if not store.get_row("accounts", account_id):
        raise HTTPException(404, "Flow account not found")
    return service.save_account(body.model_dump(), account_id)


@router.delete("/accounts/{account_id}")
def accounts_delete(account_id: str):
    try:
        removed = service.delete_account(account_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not removed:
        raise HTTPException(404, "Flow account not found")
    return {"ok": True}


@router.post("/accounts/{account_id}/connect")
def accounts_connect(account_id: str):
    try:
        return service.connect(account_id)
    except KeyError as exc:
        raise HTTPException(404, "Flow account not found") from exc


@router.post("/assets")
async def asset_upload(files: list[UploadFile] = File(...)):
    if not files or len(files) > 3:
        raise HTTPException(400, "Upload between one and three reference images")
    folder = store.root() / "uploads" / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in files:
        suffix = Path(item.filename or "image.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(400, f"Unsupported image type: {item.filename}")
        output = folder / f"{len(saved) + 1:02d}{suffix}"
        with output.open("wb") as handle:
            shutil.copyfileobj(item.file, handle)
        saved.append({"name": item.filename, "path": str(output)})
    return {"files": saved}


@router.get("/jobs")
def jobs_list():
    # Include the account snapshot so the active-job poll also refreshes
    # credits without adding another recurring request from the frontend.
    return {"jobs": service.jobs(), "accounts": service.accounts()}


@router.get("/logs")
def logs_list():
    return {"logs": service.logs()}


@router.delete("/logs")
def logs_clear():
    service.clear_logs()
    return {"ok": True}


@router.post("/jobs")
def jobs_create(body: GenerateIn):
    try:
        return {"jobs": service.enqueue(body.model_dump())}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/jobs/cancel-all")
def jobs_cancel_all():
    return {"ok": True, "cancelled": service.cancel_all(), "jobs": service.jobs()}


@router.delete("/jobs")
def jobs_delete_all():
    return {"ok": True, "deleted": service.delete_all_jobs(), "jobs": service.jobs()}


@router.post("/jobs/{job_id}/cancel")
def jobs_cancel(job_id: str):
    job = service.cancel(job_id)
    if not job:
        raise HTTPException(404, "Flow job not found")
    return job


@router.post("/jobs/{job_id}/retry")
def jobs_retry(job_id: str):
    job = service.retry(job_id)
    if not job:
        raise HTTPException(404, "Flow job not found")
    return job


@router.delete("/jobs/{job_id}")
def jobs_delete(job_id: str):
    removed = service.delete_job(job_id)
    if not removed:
        raise HTTPException(404, "Flow job not found")
    return {"ok": True}


@router.get("/jobs/{job_id}/outputs/{output_index}")
def jobs_output(job_id: str, output_index: int, download: bool = False):
    job = store.get_row("jobs", job_id)
    outputs = list(job.get("outputs") or []) if job else []
    if output_index < 0 or output_index >= len(outputs):
        raise HTTPException(404, "Flow output not found")
    path = Path(outputs[output_index])
    if not path.is_file():
        raise HTTPException(404, "Flow output file is missing")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name if download else None)


@router.post("/jobs/{job_id}/outputs/{output_index}/reveal")
def jobs_output_reveal(job_id: str, output_index: int):
    job = store.get_row("jobs", job_id)
    outputs = list(job.get("outputs") or []) if job else []
    if output_index < 0 or output_index >= len(outputs):
        raise HTTPException(404, "Flow output not found")
    path = Path(outputs[output_index])
    if not path.is_file():
        raise HTTPException(404, "Flow output file is missing")
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
    return {"ok": True, "path": str(path)}
