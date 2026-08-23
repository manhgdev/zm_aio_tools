"""Drawing-video jobs using the local streaming whiteboard renderer.

The renderer is based on ``references/whiteboard-stream-animation`` (MIT):
the pen follows a continuous stroke path and deposits ink frame by frame.
"""
from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pipeline.core.config import DATA, safe_child
from pipeline.core.jobs import kill_process_tree
from pipeline.core.media import h264_encoder_args, h264_hardware_encoder

ROOT = DATA / "drawing"
ROOT.mkdir(parents=True, exist_ok=True)
_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_PROCS: dict[str, subprocess.Popen] = {}
_WORKERS: dict[str, threading.Thread] = {}


def _spawn(command: list[str], **kwargs: Any) -> subprocess.Popen:
    """Spawn an isolated process group so cancel kills renderer + its children.

    The stream renderer starts FFmpeg itself.  Without a new group, killing the
    Python parent can leave that FFmpeg process consuming CPU after the user
    pressed Cancel, particularly on macOS.
    """
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)))
    else:
        kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(command, **kwargs)


def _log(job_id: str, message: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.setdefault("logs", []).append(f"[{time.strftime('%H:%M:%S')}] {message}")
        del job["logs"][:-120]


def _update(job_id: str, **values: Any) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(values)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        item = _JOBS.get(job_id)
        return dict(item) if item else None


def list_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(item) for item in _JOBS.values()]


def create_job(filename: str, source: Path, options: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    work = ROOT / job_id
    work.mkdir(parents=True, exist_ok=True)
    ext = source.suffix.lower() if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"} else ".png"
    image = work / f"input{ext}"
    shutil.copy2(source, image)
    output = work / "drawing.mp4"
    job = {
        "id": job_id, "filename": filename, "status": "queued", "progress": 0,
        "step": "queued", "error": "", "logs": [], "work": str(work),
        "input": str(image), "output": str(output), "lineMap": str(work / "line-map.png"),
        "strokePath": str(work / "stroke-path.png"), "options": options,
    }
    with _LOCK:
        _JOBS[job_id] = job
    _log(job_id, "Drawing job created")
    return dict(job)


def _probe_size(source: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(source)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _target_size(source: Path, requested: str) -> tuple[int, int]:
    source_w, source_h = _probe_size(source)
    if requested == "4k":
        long_edge = 3840
    elif requested == "1080p":
        long_edge = 1920
    else:
        long_edge = 1280
    if source_w >= source_h:
        width, height = long_edge, round(long_edge * source_h / source_w)
    else:
        height, width = long_edge, round(long_edge * source_w / source_h)
    return width - width % 2, height - height % 2


def _run(job_id: str, command: list[str], timeout: int = 900) -> None:
    proc = _spawn(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    with _LOCK:
        _PROCS[job_id] = proc
    try:
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            _, stderr = proc.communicate()
            raise TimeoutError("Drawing FFmpeg step timed out")
    finally:
        with _LOCK:
            _PROCS.pop(job_id, None)
    if (get_job(job_id) or {}).get("status") == "cancelled":
        return
    if proc.returncode:
        raise RuntimeError((stderr or "FFmpeg failed").strip()[-1000:])


def _run_streaming_renderer(job_id: str, command: list[str], timeout: int) -> None:
    """Run the renderer while relaying real ink/colour progress to the job.

    The reference renderer emits phase progress on stdout.  Reading it on a
    background thread works on both Windows and macOS; select() on pipes does
    not work reliably on Windows.
    """
    proc = _spawn(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    with _LOCK:
        _PROCS[job_id] = proc
    lines: queue.Queue[str | None] = queue.Queue()

    def collect() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=collect, name=f"drawing-log-{job_id}", daemon=True)
    reader.start()
    started = time.monotonic()
    last_progress = 52
    recent_output: list[str] = []
    try:
        finished = False
        while not finished:
            if time.monotonic() - started > timeout:
                kill_process_tree(proc)
                raise TimeoutError("Drawing renderer timed out")
            try:
                line = lines.get(timeout=.4)
            except queue.Empty:
                if proc.poll() is not None:
                    finished = True
                continue
            if line is None:
                finished = True
                continue
            recent_output.append(line)
            del recent_output[:-30]
            if "起笔进度" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    progress = 52 + round(int(match.group(1)) * .26)
                    if progress > last_progress:
                        last_progress = progress
                        _update(job_id, step="ink", progress=progress)
                        _log(job_id, f"Drawing ink: {match.group(1)}%")
            elif "添彩进度" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    progress = 78 + round(int(match.group(1)) * .12)
                    if progress > last_progress:
                        last_progress = progress
                        _update(job_id, step="color", progress=progress)
                        _log(job_id, f"Drawing colour: {match.group(1)}%")
    finally:
        with _LOCK:
            _PROCS.pop(job_id, None)
    if (get_job(job_id) or {}).get("status") == "cancelled":
        return
    if proc.returncode:
        detail = "\n".join(recent_output[-12:]).strip()
        raise RuntimeError(detail or "Drawing renderer failed")


def _canvas_filter(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xF7F4EE"


def _write_hand_asset(path: Path) -> None:
    """Write a hand-and-pencil PPM sprite without optional image libraries.

    PPM is decoded by the FFmpeg builds we ship on macOS and Windows.  A green
    key background becomes alpha in the filter graph below, so it is a portable
    substitute for an SVG/PNG asset with transparency.
    """
    size, key = 220, (0, 255, 0)
    pixels = bytearray(key * (size * size))

    def put(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            index = (y * size + x) * 3
            pixels[index:index + 3] = bytes(color)

    def ellipse(cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int]) -> None:
        for y in range(max(0, int(cy - ry)), min(size, int(cy + ry) + 1)):
            for x in range(max(0, int(cx - rx)), min(size, int(cx + rx) + 1)):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                    put(x, y, color)

    def line(x1: float, y1: float, x2: float, y2: float, width: float, color: tuple[int, int, int]) -> None:
        dx, dy = x2 - x1, y2 - y1
        length_sq = max(1, dx * dx + dy * dy)
        for y in range(max(0, int(min(y1, y2) - width)), min(size, int(max(y1, y2) + width) + 1)):
            for x in range(max(0, int(min(x1, x2) - width)), min(size, int(max(x1, x2) + width) + 1)):
                amount = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / length_sq))
                px, py = x1 + amount * dx, y1 + amount * dy
                if (x - px) ** 2 + (y - py) ** 2 <= width * width:
                    put(x, y, color)

    skin, shade, pencil, lead = (242, 198, 158), (203, 144, 107), (44, 62, 82), (25, 34, 48)
    ellipse(101, 141, 58, 46, shade)
    ellipse(105, 132, 58, 45, skin)
    for cx, cy in ((65, 104), (82, 92), (100, 88), (118, 94)):
        ellipse(cx, cy, 13, 39, skin)
    ellipse(146, 139, 17, 42, skin)  # thumb
    line(115, 108, 184, 35, 14, lead)
    line(115, 108, 177, 42, 9, pencil)
    line(177, 42, 193, 25, 10, (240, 199, 113))
    line(193, 25, 202, 16, 4, lead)
    path.write_bytes(f"P6\n{size} {size}\n255\n".encode("ascii") + bytes(pixels))


def run(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    try:
        _update(job_id, status="processing", step="line_map", progress=8)
        _log(job_id, "Extracting line map")
        source = Path(job["input"])
        options = job["options"]
        width, height = _target_size(source, str(options.get("resolution", "720p")))
        detail = max(10, min(100, int(options.get("detail", 72))))
        low = max(.02, min(.25, (100 - detail) / 340))
        high = min(.65, low + .13)
        canvas = _canvas_filter(width, height)
        line = Path(job["lineMap"])
        _run(job_id, [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-frames:v", "1",
            "-vf", f"{canvas},format=gray,edgedetect=low={low:.3f}:high={high:.3f},negate", str(line),
        ])
        if (get_job(job_id) or {}).get("status") == "cancelled":
            return
        _update(job_id, step="stroke_path", progress=32)
        _log(job_id, "Ordering drawing strokes")
        stroke = Path(job["strokePath"])
        thickness = max(1, min(8, int(options.get("thickness", 2))))
        # A softened, slightly expanded edge map is the path preview and makes
        # marker/brush presets visibly different without a CV dependency.
        _run(job_id, [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(line), "-frames:v", "1",
            "-vf", f"boxblur={thickness}:1,eq=contrast=1.25", str(stroke),
        ])
        if (get_job(job_id) or {}).get("status") == "cancelled":
            return
        _update(job_id, step="rendering", progress=52)
        encoder = h264_hardware_encoder() or "libx264"
        _log(job_id, f"Rendering continuous drawing strokes (OpenCV CPU; H.264={encoder})")
        duration = max(2, min(60, float(options.get("duration", 10))))
        fps = int(options.get("fps", 30))
        fps = fps if fps in {24, 30, 60} else 30
        mode = str(options.get("mode", "drawing"))
        tool = str(options.get("tool", "pencil"))
        # Detail drives the grid density.  Skeleton paths follow clean line art
        # precisely, while grid paths remain stable on dense photographs.
        grid_edge = max(5, min(18, round(19 - detail * .13)))
        ink_path = "skeleton" if detail >= 68 else "grid"
        renderer = Path(__file__).with_name("stream_runner.py")
        if not renderer.is_file():
            raise RuntimeError("Streaming drawing renderer is not bundled with this build")
        stream_dir = Path(job["work"]) / "stream"
        stream_dir.mkdir(exist_ok=True)
        # The reference renderer paints every frame with OpenCV/NumPy.  1280px
        # internal canvas keeps stroke motion smooth without making a 1080p
        # export paint 2.25× as many pixels; final scale still honors output.
        render_long_edge = min(max(width, height), 1600 if str(options.get("resolution")) == "4k" else 1280)
        render_command = [
            sys.executable, "-u", str(renderer), str(source), "--out-dir", str(stream_dir),
            "--total-ms", str(round(duration * 1000)), "--fps", str(fps),
            "--grid-edge", str(grid_edge), "--ink-path", ink_path,
            "--long-edge", str(render_long_edge),
            "--tool", tool, "--thickness", str(thickness),
        ]
        # Selecting the Pen is actionable: it uses the visible hand/pen tip
        # even when the user leaves the general drawing mode selected.
        if mode != "hand" and tool not in {"pen", "marker", "brush"}:
            render_command.append("--bare-tip")
        _run_streaming_renderer(job_id, render_command, timeout=max(900, int(duration * 90)))
        if (get_job(job_id) or {}).get("status") == "cancelled":
            return
        generated = sorted(stream_dir.glob("*_h264.mp4"), key=lambda item: item.stat().st_mtime)
        if not generated:
            raise RuntimeError("Streaming renderer finished without an MP4 output")
        _update(job_id, step="encoding", progress=90)
        _log(job_id, "Encoding H.264 output")
        # Keep the requested export size/aspect even though the stroke engine
        # internally uses an efficient drawing canvas.
        _run(job_id, [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(generated[-1]),
            "-vf", canvas, "-r", str(fps), *h264_encoder_args(fast=True),
            "-movflags", "+faststart", str(job["output"]),
        ], timeout=max(900, int(duration * 60)))
        if (get_job(job_id) or {}).get("status") == "cancelled":
            return
        _update(job_id, status="done", step="done", progress=100)
        _log(job_id, "Drawing video ready")
    except Exception as exc:
        if (get_job(job_id) or {}).get("status") != "cancelled":
            _update(job_id, status="error", step="error", error=str(exc))
            _log(job_id, f"ERROR: {exc}")
    finally:
        with _LOCK:
            item = _JOBS.get(job_id)
            should_delete = bool(item and item.get("deleteRequested"))
            work = Path(str(item.get("work") or "")) if item else None
            _WORKERS.pop(job_id, None)
            if should_delete:
                _JOBS.pop(job_id, None)
        if should_delete and work:
            shutil.rmtree(work, ignore_errors=True)


def start(job_id: str) -> None:
    if (get_job(job_id) or {}).get("status") == "cancelled":
        return
    worker = threading.Thread(target=run, args=(job_id,), name=f"drawing-{job_id}", daemon=True)
    with _LOCK:
        _WORKERS[job_id] = worker
    worker.start()


def start_batch(job_ids: list[str]) -> None:
    """Render a batch sequentially so local CPU/GPU is never oversubscribed."""
    def worker() -> None:
        for job_id in job_ids:
            if (get_job(job_id) or {}).get("status") == "cancelled":
                continue
            start(job_id)
            while True:
                state = get_job(job_id)
                if not state or state.get("status") in {"done", "error", "cancelled"}:
                    break
                time.sleep(.25)
    threading.Thread(target=worker, name="drawing-batch", daemon=True).start()


def cancel(job_id: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return False
        job["status"] = "cancelled"
        process = _PROCS.get(job_id)
    if process:
        kill_process_tree(process)
    _log(job_id, "Drawing job cancelled; subprocess tree terminated")
    return True


def update_options(job_id: str, options: dict[str, Any]) -> dict[str, Any] | None:
    """Edit a queued drawing job before its renderer starts."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") != "queued":
            raise RuntimeError("Only queued drawing jobs can be edited")
        job["options"] = dict(options)
        job["step"] = "queued"
        job["progress"] = 0
        return dict(job)


def remove(job_id: str) -> bool:
    """Cancel and permanently remove one Drawing job and its owned files."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return False
        job["deleteRequested"] = True
        worker = _WORKERS.get(job_id)
        work = Path(str(job.get("work") or ""))
    cancel(job_id)
    if worker and worker.is_alive():
        # The worker owns its output handles; it removes the job folder in its
        # finally block after the killed process tree has exited.
        return True
    with _LOCK:
        _JOBS.pop(job_id, None)
        _WORKERS.pop(job_id, None)
    shutil.rmtree(work, ignore_errors=True)
    return True


def artifact(job_id: str, name: str) -> Path | None:
    job = get_job(job_id)
    if not job or name not in {"input", "lineMap", "strokePath", "output"}:
        return None
    candidate = Path(job[name])
    root = ROOT / job_id
    if safe_child(root, candidate.name) is None or not candidate.is_file():
        return None
    return candidate
