"""Completed video exports and their cached thumbnails."""
from __future__ import annotations

import os
import re
import json
import hashlib
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pipeline.core.config import PUBLIC_DATA
from pipeline.core.media import ffprobe_duration, video_size
from pipeline.core.output_paths import downloads_folder

router = APIRouter()
_RENDER_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class RenderRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _export_mp4_paths() -> list[Path]:
    """All known completed Clone, Review and standalone-tool videos."""
    paths: list[Path] = []
    flat = PUBLIC_DATA / "exports"
    if flat.is_dir():
        paths.extend(flat.glob("*.mp4"))
    if PUBLIC_DATA.is_dir():
        for project_dir in PUBLIC_DATA.iterdir():
            if not project_dir.is_dir() or project_dir.name == "exports":
                continue
            sub = project_dir / "exports"
            if sub.is_dir():
                paths.extend(sub.glob("*.mp4"))
    # Các tool độc lập không có project nên xuất mặc định vào Downloads.
    # Include chúng để các bản render cũ cũng xuất hiện, không chỉ job mới.
    for folder in (
        downloads_folder("video-clone"),
        downloads_folder("film"),
        downloads_folder("flow"),
        downloads_folder("download-video"),
        downloads_folder("subtitle-image"),
        downloads_folder("drawing"),
        downloads_folder("cleaner"),
        downloads_folder("batch"),
    ):
        if folder.is_dir():
            paths.extend(folder.rglob("*.mp4"))
    # User-facing filenames may contain spaces, Unicode or share a basename in
    # different output folders. Deduplicate by absolute path, not by filename.
    seen: set[str] = set()
    uniq: list[Path] = []
    for candidate in paths:
        if not candidate.is_file():
            continue
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(candidate)
    uniq.sort(key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True)
    return uniq


def _render_id(output: Path, paths: list[Path]) -> str:
    """Keep legacy IDs when unique; hash path for unsafe/duplicate filenames."""
    stem = output.stem
    duplicates = sum(path.stem == stem for path in paths) > 1
    if _RENDER_ID.fullmatch(stem) and not duplicates:
        return stem
    digest = hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"media-{digest}"


def _render_path(render_id: str) -> Path | None:
    if not _RENDER_ID.fullmatch(render_id):
        return None
    paths = _export_mp4_paths()
    return next((path for path in paths if _render_id(path, paths) == render_id), None)


def _project_id(output: Path, saved: dict[str, Any]) -> str:
    explicit = str(saved.get("projectId") or "").strip()
    if explicit:
        return explicit
    if output.parent == PUBLIC_DATA / "exports":
        return output.stem.split("-", 1)[0]
    try:
        relative = output.resolve().relative_to(PUBLIC_DATA.resolve())
    except ValueError:
        return ""
    if len(relative.parts) >= 3 and relative.parts[1] == "exports":
        return relative.parts[0]
    return ""


from concurrent.futures import ThreadPoolExecutor

_PROBE_CACHE: dict[str, tuple[float, int, int, int, float]] = {}


def _probe_video_info(path: Path) -> dict[str, Any] | None:
    try:
        st = path.stat()
        mtime, size = st.st_mtime, st.st_size
        cached = _PROBE_CACHE.get(str(path))
        if cached and cached[0] == mtime and cached[1] == size:
            w, h, dur = cached[2], cached[3], cached[4]
        else:
            w, h = video_size(path)
            dur = ffprobe_duration(path)
            _PROBE_CACHE[str(path)] = (mtime, size, w, h, dur)

        if w <= 0 or h <= 0 or dur <= 0:
            return None
        return {
            "path": path,
            "width": w,
            "height": h,
            "duration": dur,
            "sizeBytes": size,
            "mtime": mtime,
        }
    except Exception:
        return None


def list_rendered_videos() -> list[dict[str, Any]]:
    paths = _export_mp4_paths()
    if not paths:
        return []
    # ponytail: giới hạn 120 video mới nhất để phản hồi siêu tốc dưới 0.1s
    paths = paths[:120]
    archived_projects = {path.stem.split("-", 1)[0] for path in paths if "-" in path.stem}

    with ThreadPoolExecutor(max_workers=16) as pool:
        probed_results = list(pool.map(_probe_video_info, paths))

    items: list[dict[str, Any]] = []
    for info in probed_results:
        if not info:
            continue
        output: Path = info["path"]
        render_id = _render_id(output, paths)
        try:
            sidecar = output.with_suffix(".json")
            saved = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
            project_id = _project_id(output, saved)
            if output.stem == project_id and project_id in archived_projects:
                continue
            name = str(saved.get("name") or "").strip() or output.stem
        except Exception:
            name = output.stem
            project_id = ""

        items.append({
            "renderId": render_id,
            "projectId": project_id,
            "canEdit": bool(project_id),
            "name": name,
            "createdAt": datetime.fromtimestamp(info["mtime"], timezone.utc).isoformat(),
            "sizeBytes": info["sizeBytes"],
            "duration": info["duration"],
            "width": info["width"],
            "height": info["height"],
            "videoUrl": f"/api/renders/{render_id}/video",
            "downloadUrl": f"/api/renders/{render_id}/video?download=1",
            "thumbnailUrl": f"/api/renders/{render_id}/thumbnail",
        })
    return sorted(items, key=lambda item: item["createdAt"], reverse=True)


def ensure_thumbnail(render_id: str) -> Path:
    output = _render_path(render_id)
    if output is None:
        raise FileNotFoundError(render_id)
    thumbnail = PUBLIC_DATA / "exports" / "thumbnails" / f"{render_id}.jpg"
    if thumbnail.is_file() and thumbnail.stat().st_mtime >= output.stat().st_mtime:
        return thumbnail
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    temp = thumbnail.with_name(f"{render_id}.{uuid.uuid4().hex}.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1",
             "-i", str(output), "-frames:v", "1", "-vf", "scale=640:-2",
             "-q:v", "3", str(temp)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        temp.replace(thumbnail)
        return thumbnail
    finally:
        temp.unlink(missing_ok=True)


@router.get("/api/renders")
def api_renders():
    desktop = os.environ.get("VIDEO_CLONE_DESKTOP") == "1" or bool(getattr(sys, "frozen", False))
    return {"items": list_rendered_videos(), "canReveal": desktop}


@router.put("/api/renders/{render_id}")
def api_rename_render(render_id: str, body: RenderRenameIn):
    path = _render_path(render_id)
    if path is None:
        raise HTTPException(404, "Khong tim thay file render")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Ten render khong duoc de trong")
    sidecar = path.with_suffix(".json")
    # Giữ projectId thật từ sidecar (tên render tự đặt không chứa project id)
    project_id = render_id.split("-", 1)[0]
    try:
        if sidecar.is_file():
            project_id = str(json.loads(sidecar.read_text(encoding="utf-8")).get("projectId") or project_id)
    except (OSError, ValueError):
        pass
    sidecar.write_text(
        json.dumps({"name": name, "projectId": project_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"renderId": render_id, "name": name}


@router.delete("/api/renders/{render_id}")
def api_delete_render(render_id: str):
    path = _render_path(render_id)
    if path is None:
        raise HTTPException(404, "Khong tim thay file render")
    exports = PUBLIC_DATA / "exports"
    # The UI can issue a duplicate delete after another tab has removed the
    # file; deletion must remain idempotent while metadata is cleaned up.
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
    (exports / "thumbnails" / f"{render_id}.jpg").unlink(missing_ok=True)
    # Bản "dễ tìm" <project>.mp4 chỉ bị ẩn khi còn bản lưu trữ <project>-*.mp4;
    # xóa bản lưu trữ cuối cùng thì dọn luôn để video không hiện lại trong tab.
    project_id = render_id.split("-", 1)[0]
    if "-" in render_id and not any(exports.glob(f"{project_id}-*.mp4")):
        (exports / f"{project_id}.mp4").unlink(missing_ok=True)
        (exports / f"{project_id}.json").unlink(missing_ok=True)
        (exports / "thumbnails" / f"{project_id}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/api/renders/{render_id}/video")
def api_render_video(render_id: str, download: bool = False):
    path = _render_path(render_id)
    if path is None:
        raise HTTPException(404)
    if download:
        return FileResponse(path, filename=path.name, media_type="video/mp4")
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")


@router.get("/api/renders/{render_id}/thumbnail")
def api_render_thumbnail(render_id: str):
    try:
        path = ensure_thumbnail(render_id)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        raise HTTPException(404, "Khong tao duoc thumbnail") from None
    return FileResponse(path, media_type="image/jpeg")


@router.post("/api/renders/{render_id}/reveal")
def api_reveal_render(render_id: str):
    import platform

    path = _render_path(render_id)
    if path is None:
        raise HTTPException(404, "Khong tim thay file render")
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True, "path": str(path.resolve())}
