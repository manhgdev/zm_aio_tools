from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from pipeline.core.output_paths import downloads_folder
from pipeline.automation import service
from api.i18n import current_locale

router = APIRouter(prefix="/api/automation", tags=["automation"])

_INPUT_MODES = {"topic", "ai_topic", "script", "bundle"}
_ALLOWED_EXTENSIONS = {
    "script": {".txt", ".md", ".markdown"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"},
    "srt": {".srt", ".vtt", ".ass", ".ssa", ".csv", ".tsv", ".json", ".lrc"},
    "prompts": {".txt", ".md", ".markdown", ".csv", ".tsv", ".json"},
}
_MAX_FILE_BYTES = 100 * 1024 * 1024


def _t(vi: str, en: str) -> str:
    # API consumers receive a stable code and can localize the message.
    return vi if current_locale() == "vi" else en


def _settings(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return service.get_settings()
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "AUTOMATION_SETTINGS_INVALID", "message": _t("Cài đặt không hợp lệ", "Invalid automation settings")}) from exc
    if not isinstance(value, dict):
        raise HTTPException(422, detail={"code": "AUTOMATION_SETTINGS_INVALID", "message": _t("Cài đặt không hợp lệ", "Invalid automation settings")})
    return value


async def _save_upload(job_id: str, upload: UploadFile | None, kind: str) -> str | None:
    if upload is None or not upload.filename:
        return None
    filename = Path(upload.filename).name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in _ALLOWED_EXTENSIONS[kind]:
        raise HTTPException(422, detail={"code": "AUTOMATION_FILE_TYPE_INVALID", "message": _t("Định dạng file không được hỗ trợ", "File type is not supported")})
    content = await upload.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(413, detail={"code": "AUTOMATION_FILE_TOO_LARGE", "message": _t("File vượt quá 100 MB", "File exceeds 100 MB")})
    target = service.store.workspace(job_id) / "input" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return str(target)


@router.get("/settings")
def get_settings():
    return service.get_settings()


@router.put("/settings")
def put_settings(body: dict[str, Any]):
    return service.save_settings(body)


@router.get("/jobs")
def list_jobs():
    return {"jobs": service.list_jobs()}


@router.post("/jobs")
async def create_job(
    inputMode: str = Form("topic"),
    title: str = Form(""),
    topic: str = Form(""),
    settings: str = Form(""),
    script: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    srt: UploadFile | None = File(None),
    prompts: UploadFile | None = File(None),
    startNow: bool = Form(True),
):
    mode = inputMode.strip().lower()
    if mode not in _INPUT_MODES:
        raise HTTPException(422, detail={"code": "AUTOMATION_INPUT_MODE_INVALID", "message": _t("Chế độ đầu vào không hợp lệ", "Invalid input mode")})
    # An empty topic is intentional: the AI-topic stage will suggest five
    # ideas for the user to choose. URLs are not fetched by this workflow.
    if mode == "topic" and not topic.strip():
        mode = "ai_topic"
    if len(topic.strip()) > 2_000:
        raise HTTPException(422, detail={"code": "AUTOMATION_TOPIC_TOO_LARGE", "message": _t("Chủ đề vượt quá 2.000 ký tự", "Topic exceeds 2,000 characters")})
    if mode == "script" and script is None:
        raise HTTPException(422, detail={"code": "AUTOMATION_SCRIPT_REQUIRED", "message": _t("Cần chọn file script", "A script file is required")})
    if mode == "bundle" and not any((audio, srt, prompts, script)):
        raise HTTPException(422, detail={"code": "AUTOMATION_FILES_REQUIRED", "message": _t("Cần ít nhất một file đầu vào", "At least one input file is required")})
    chosen = _settings(settings)
    job = service.create_job(mode, title.strip()[:160] or topic[:80] or "Automation", chosen, {"topic": topic.strip()})
    for upload, kind in ((script, "script"), (audio, "audio"), (srt, "srt"), (prompts, "prompts")):
        path = await _save_upload(job["id"], upload, kind)
        if path:
            current = service.store.get_job(job["id"]) or {}
            inputs = dict(current.get("input") or {})
            inputs[kind] = path
            service.store.update_job(job["id"], input=inputs)
    if startNow:
        job = service.start_job(job["id"])
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    try:
        return service.public_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    try:
        return service.delete_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc


@router.patch("/jobs/{job_id}")
def update_job(job_id: str, body: dict[str, Any]):
    settings = body.get("settings")
    if settings is not None and not isinstance(settings, dict):
        raise HTTPException(422, detail={"code": "AUTOMATION_SETTINGS_INVALID", "message": _t("Cài đặt không hợp lệ", "Invalid automation settings")})
    try:
        return service.update_job_settings(job_id, title=body.get("title"), settings=settings)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc


@router.get("/jobs/{job_id}/logs")
def get_logs(job_id: str):
    try:
        return {"logs": service.list_logs(job_id)}
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc


def _artifact_path(job_id: str, artifact_name: str) -> tuple[dict[str, Any], Path]:
    """Resolve a persisted artifact without allowing arbitrary file reads."""
    try:
        job = service.store.get_job(job_id)
    except (TypeError, ValueError):
        job = None
    if not job:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")})
    key = str(artifact_name or "").strip()
    if not key or key in {".", ".."} or "/" in key or "\\" in key:
        raise HTTPException(400, detail={"code": "AUTOMATION_ARTIFACT_INVALID", "message": _t("Artifact không hợp lệ", "Invalid artifact")})
    raw = (job.get("artifacts") or {}).get(key)
    if not raw:
        raise HTTPException(404, detail={"code": "AUTOMATION_ARTIFACT_NOT_FOUND", "message": _t("Chưa có file đầu ra", "Artifact is not available")})
    target = Path(str(raw)).expanduser().resolve()
    workspace = service.store.workspace(job_id).resolve()
    output_root = (downloads_folder("subtitle-image") / "automation").resolve()
    configured_value = str((job.get("settings") or {}).get("outputDir") or "").strip()
    configured_root = Path(configured_value).expanduser().resolve() if configured_value else None
    try:
        target.relative_to(workspace)
    except ValueError:
        try:
            target.relative_to(output_root)
        except ValueError as exc:
            if configured_root is None:
                raise HTTPException(403, detail={"code": "AUTOMATION_ARTIFACT_FORBIDDEN", "message": _t("Artifact không nằm trong vùng an toàn", "Artifact is outside the safe output area")}) from exc
            try:
                target.relative_to(configured_root)
            except ValueError:
                raise HTTPException(403, detail={"code": "AUTOMATION_ARTIFACT_FORBIDDEN", "message": _t("Artifact không nằm trong vùng an toàn", "Artifact is outside the safe output area")}) from exc
    if not target.is_file():
        raise HTTPException(404, detail={"code": "AUTOMATION_ARTIFACT_NOT_FOUND", "message": _t("File đầu ra chưa sẵn sàng", "Artifact file is not ready")})
    return job, target


@router.get("/jobs/{job_id}/artifacts/{artifact_name}")
def artifact(job_id: str, artifact_name: str):
    _job, target = _artifact_path(job_id, artifact_name)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=target.name)


@router.post("/jobs/{job_id}/open-folder")
def open_folder(job_id: str):
    job = service.store.get_job(job_id)
    if not job:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")})
    raw = (job.get("artifacts") or {}).get("video") or (job.get("artifacts") or {}).get("images")
    if not raw:
        raise HTTPException(404, detail={"code": "AUTOMATION_OUTPUT_NOT_READY", "message": _t("Chưa có thư mục đầu ra", "Output folder is not ready")})
    folder = Path(str(raw)).expanduser().resolve()
    if folder.is_file():
        folder = folder.parent
    workspace = service.store.workspace(job_id).resolve()
    output_root = (downloads_folder("subtitle-image") / "automation").resolve()
    configured_value = str((job.get("settings") or {}).get("outputDir") or "").strip()
    configured_root = Path(configured_value).expanduser().resolve() if configured_value else None
    try:
        folder.relative_to(workspace)
    except ValueError:
        try:
            folder.relative_to(output_root)
        except ValueError as exc:
            if configured_root is None:
                raise HTTPException(403, detail={"code": "AUTOMATION_ARTIFACT_FORBIDDEN", "message": _t("Thư mục không nằm trong vùng an toàn", "Folder is outside the safe output area")}) from exc
            try:
                folder.relative_to(configured_root)
            except ValueError:
                raise HTTPException(403, detail={"code": "AUTOMATION_ARTIFACT_FORBIDDEN", "message": _t("Thư mục không nằm trong vùng an toàn", "Folder is outside the safe output area")}) from exc
    if not folder.is_dir():
        raise HTTPException(404, detail={"code": "AUTOMATION_OUTPUT_NOT_READY", "message": _t("Thư mục đầu ra chưa sẵn sàng", "Output folder is not ready")})
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(500, detail={"code": "AUTOMATION_OPEN_FOLDER_FAILED", "message": _t("Không mở được thư mục đầu ra", "Could not open the output folder")}) from exc
    return {"ok": True, "path": str(folder)}


@router.get("/jobs/{job_id}/events")
def events(job_id: str):
    if not service.store.get_job(job_id):
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")})

    def stream():
        last = ""
        while True:
            try:
                snapshot = service.public_job(job_id)
            except KeyError:
                return
            data = json.dumps(snapshot, ensure_ascii=False)
            if data != last:
                last = data
                yield f"event: job.updated\ndata: {data}\n\n"
            if snapshot["status"] in {"completed", "paused", "interrupted", "failed", "cancelled"}:
                return
            time.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _mutate(job_id: str, action: str):
    try:
        method = {"resume": service.resume_job, "pause": service.pause_job, "cancel": service.cancel_job, "retry": service.retry_job}[action]
        return method(job_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc


@router.post("/jobs/{job_id}/resume")
def resume(job_id: str):
    return _mutate(job_id, "resume")


@router.post("/jobs/{job_id}/select-topic")
def select_topic(job_id: str, body: dict[str, Any]):
    try:
        return service.select_topic(job_id, str(body.get("topic") or ""))
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "AUTOMATION_JOB_NOT_FOUND", "message": _t("Không tìm thấy job", "Automation job not found")}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc), "message": _t("Chủ đề không hợp lệ", "Invalid topic")}) from exc


@router.post("/jobs/{job_id}/pause")
def pause(job_id: str):
    return _mutate(job_id, "pause")


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    return _mutate(job_id, "cancel")


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str):
    return _mutate(job_id, "retry")
