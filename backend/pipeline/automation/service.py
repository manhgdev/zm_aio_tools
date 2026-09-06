from __future__ import annotations

import re
import json
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from pipeline.core.app_config import load_app_config
from pipeline.core.output_paths import downloads_folder, safe_output_part, selected_or_default
from .prompts import audio_first_prompt
from .store import AutomationStore


_TOPIC_PROMPT_VERSION = "audio-first-2d-v2"


class AutomationCancelled(RuntimeError):
    pass


class AutomationService:
    """Durable multi-job queue with stage-level pause/retry controls."""

    def __init__(
        self,
        *,
        store: AutomationStore | None = None,
        runner: Callable[[str], None] | None = None,
        max_workers: int = 2,
    ):
        self.store = store or AutomationStore()
        self.settings_path = self.store.db_path.parent / "settings.json"
        self._runner = runner or self._run_pipeline
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 8)), thread_name_prefix="automation")
        self._futures: dict[str, Future[Any]] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._chat_gate = threading.Lock()

    def get_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "language": "vi",
            "textProvider": "openrouter",
            "textModel": "openrouter/free",
            "chatModel": "GPT-5.6 Sol",
            "tts": {"voice": "system", "speed": 1.0, "volume": 1.0, "pitch": 0.0, "style": "tu_nhien"},
            "flow": {"accountId": "", "model": "Nano Banana 2", "ratio": "16:9", "resolution": "1K", "concurrency": "3", "promptEngine": "vi"},
            "compose": {
                "resolution": "auto", "targetPlatform": "auto", "fps": 30, "crf": 20, "encoder": "auto",
                "effect": "none", "transitionDuration": 0.28, "zoom": "off", "speed": 100, "volume": 100, "previewSeconds": 0,
                "allowMissingMedia": False, "subtitleEnabled": True, "removeMetadata": False,
                "subtitleFontFamily": "system", "subtitleSize": 8, "subtitleOffset": 0, "subtitleMargin": 34,
                "subtitleBackground": "solid", "subtitleColor": "#ffffff", "subtitleBgColor": "#000000", "subtitleOpacity": 55,
                "drawingEnabled": False, "drawingMode": "hand", "drawingTool": "pencil", "drawingDetail": 72, "drawingThickness": 2, "drawingStrokeOrder": "natural",
                "delogoEnabled": False, "delogoAuto": True, "delogoX": 80, "delogoY": 82, "delogoW": 18, "delogoH": 12,
                "logoEnabled": False, "logoSource": "text", "logoText": "ZM AIO TOOL", "logoIcon": "★", "logoFontSize": 32, "logoColor": "#ffffff", "logoSize": 8, "logoOpacity": 85, "logoX": 88, "logoY": 88, "logoMotion": "fixed", "logoScope": "full", "logoStart": 0, "logoEnd": 10, "logoVisibleSec": 4, "logoHiddenSec": 2, "logoFadeSec": 0.5, "logoSafeMargin": 4,
            },
            "outputDir": "",
        }
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                clean = self._public_settings(saved)
                if "textProvider" not in clean and clean.get("chatModel"):
                    clean["textProvider"] = "chatgpt_web"
                    clean["textModel"] = str(clean["chatModel"])
                return {**defaults, **clean}
        except (OSError, ValueError, TypeError):
            pass
        return defaults

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        clean = self._public_settings(dict(settings or {}))
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.settings_path.with_suffix(".tmp")
        temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.settings_path)
        return self.get_settings()

    def start(self) -> None:
        """Resume queued work and jobs interrupted by a previous app restart."""
        for job in self.store.list_jobs():
            if job["status"] == "queued":
                self.start_job(job["id"])
            elif job["status"] == "interrupted" and (job.get("error") or {}).get("code") == "AUTOMATION_INTERRUPTED":
                self.store.update_job(job["id"], status="queued", error=None)
                self.start_job(job["id"])

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def create_job(self, input_mode: str, title: str, settings: dict[str, Any], input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = str(input_mode or "").strip().lower()
        if mode not in {"topic", "ai_topic", "script", "bundle"}:
            raise ValueError("AUTOMATION_INPUT_MODE_INVALID")
        clean_settings = self._public_settings(settings or {})
        # Persist the provider/model decision with the job. This keeps retries
        # deterministic and prevents a later global setting change from
        # silently switching an already queued job to another provider.
        if not clean_settings.get("textProvider"):
            clean_settings["textProvider"] = "chatgpt_web" if clean_settings.get("chatModel") else "openrouter"
        if not clean_settings.get("textModel"):
            clean_settings["textModel"] = str(clean_settings.get("chatModel") or ("openrouter/free" if clean_settings["textProvider"] == "openrouter" else ""))
        item = self.store.create_job(mode, title, clean_settings, input_data)
        self.store.append_log(item["id"], "info", "Job đã được tạo và xếp hàng.", stage="input")
        return self.public_job(item["id"])

    def public_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        # Never expose local input/output paths or accidental secrets to the UI.
        public = {**job}
        public_input = dict(job.get("input") or {})
        for key in ("script", "audio", "srt", "prompts", "watermark"):
            if public_input.get(key):
                public_input[key] = Path(str(public_input[key])).name
        public["input"] = public_input
        public["artifacts"] = {
            str(name): {
                "available": Path(str(path)).is_file() or Path(str(path)).is_dir(),
                "filename": Path(str(path)).name,
            }
            for name, path in (job.get("artifacts") or {}).items()
            if isinstance(name, str) and path
        }
        public["settings"] = self._public_settings(job.get("settings") or {})
        public["logs"] = self.store.list_logs(job_id)
        return public

    @staticmethod
    def _public_settings(settings: dict[str, Any]) -> dict[str, Any]:
        blocked = {"apikey", "api_key", "token", "accesstoken", "refreshtoken", "secret", "password"}
        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(k): clean(v) for k, v in value.items() if str(k).replace("-", "").replace("_", "").lower() not in blocked}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        result = clean(settings)
        return result if isinstance(result, dict) else {}

    def list_jobs(self) -> list[dict[str, Any]]:
        return [self.public_job(job["id"]) for job in self.store.list_jobs()]

    def list_logs(self, job_id: str) -> list[dict[str, Any]]:
        if not self.store.get_job(job_id):
            raise KeyError(job_id)
        return self.store.list_logs(job_id)

    def start_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        with self._lock:
            current = self._futures.get(job_id)
            if current and not current.done():
                return self.public_job(job_id)
            if job["status"] not in {"queued", "paused", "interrupted", "failed", "cancelled"}:
                return self.public_job(job_id)
            self._cancel[job_id] = threading.Event()
            self.store.update_job(job_id, status="running", error=None)
            self.store.append_log(job_id, "info", "Job bắt đầu/tiếp tục.", stage=str(job.get("stage") or "input"))
            self._futures[job_id] = self._executor.submit(self._execute, job_id)
        return self.public_job(job_id)

    def pause_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        with self._lock:
            event = self._cancel.get(job_id)
            if event:
                event.set()
        if job["status"] in {"running", "queued"}:
            self.store.update_job(job_id, status="paused")
            self.store.append_log(job_id, "warning", "Đã tạm dừng theo yêu cầu.", stage=str(job.get("stage") or "input"))
        return self.public_job(job_id)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        return self.start_job(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        with self._lock:
            event = self._cancel.get(job_id)
            if event:
                event.set()
        if job["status"] not in {"completed", "cancelled"}:
            self.store.update_job(job_id, status="cancelled")
            self.store.append_log(job_id, "warning", "Đã hủy job.", stage=str(job.get("stage") or "input"))
        return self.public_job(job_id)

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """Cancel active work and remove every artifact owned by this automation job."""
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        with self._lock:
            event = self._cancel.get(job_id)
            if event:
                event.set()
            future = self._futures.get(job_id)
            active_future = bool(future and not future.done())
            if future and future.cancel():
                # A queued future can be cancelled before _execute starts;
                # no worker will run its finally block to clean this marker.
                active_future = False
        # Provider children have their own queues. Delete them rather than only
        # cancelling: each child owns a Flow output file which belongs solely to
        # this parent automation job.
        for child_id in job.get("child_job_ids") or []:
            try:
                from pipeline.flow import service as flow_service
                flow_service.delete_job(str(child_id))
            except Exception:
                pass
        # _compose creates exactly one isolated directory per automation job.
        # Do not remove the configured root because other jobs may share it.
        compose_root = selected_or_default("automation", str((job.get("settings") or {}).get("outputDir") or ""))
        output_dir = compose_root / safe_output_part(job.get("title"), "job") / job_id
        shutil.rmtree(output_dir, ignore_errors=True)
        deleted = self.store.delete_job(job_id)
        workspace = self.store.jobs_root / job_id
        shutil.rmtree(workspace, ignore_errors=True)
        with self._lock:
            self._futures.pop(job_id, None)
            if not active_future:
                self._cancel.pop(job_id, None)
        return {"id": job_id, "deleted": deleted}

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] not in {"completed", "paused", "failed", "interrupted"}:
            return self.public_job(job_id)
        # An explicit parent retry also requeues terminal Flow children. This
        # lets the user reconnect Flow after a reCAPTCHA/login interruption and
        # continue the same batch without generating duplicate prompts.
        try:
            from pipeline.flow import service as flow_service
            snapshot = {str(row.get("id")): row for row in flow_service.jobs()}
            for child_id in job.get("child_job_ids") or []:
                child = snapshot.get(str(child_id)) or {}
                if child.get("status") in {"failed", "action_required"}:
                    flow_service.retry(str(child_id))
        except Exception:
            # The Flow module is optional for non-Flow automation jobs.
            pass
        patch: dict[str, Any] = {"status": "queued", "error": None}
        if job["status"] == "completed":
            artifacts = dict(job.get("artifacts") or {})
            artifacts.pop("video", None)
            patch["artifacts"] = artifacts
        self.store.update_job(job_id, **patch)
        self.store.append_log(job_id, "info", "Đã đưa lại chặng ghép video vào hàng đợi.", stage="compose")
        return self.start_job(job_id)

    def update_job_settings(self, job_id: str, *, title: str | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = str(title).strip()[:160] or job["title"]
        if settings is not None:
            patch["settings"] = dict(settings)
            if dict(settings) != dict(job.get("settings") or {}):
                artifacts = dict(job.get("artifacts") or {})
                for key in ("video", "images"):
                    artifacts.pop(key, None)
                patch["artifacts"] = artifacts
                input_data = dict(job.get("input") or {})
                for marker, key in (("generatedScript", "script"), ("generatedAudio", "audio"), ("generatedSrt", "srt"), ("generatedPrompts", "prompts")):
                    if input_data.pop(marker, False):
                        input_data.pop(key, None)
                        artifacts.pop(key, None)
                patch["input"] = input_data
        if patch:
            self.store.update_job(job_id, **patch)
            self.store.append_log(job_id, "info", "Đã cập nhật cài đặt job.", stage=str(job.get("stage") or "input"))
        return self.public_job(job_id)

    def select_topic(self, job_id: str, topic: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job.get("status") != "awaiting_topic":
            raise ValueError("AUTOMATION_TOPIC_NOT_READY")
        selected = str(topic or "").strip()
        if not selected or len(selected) > 2000:
            raise ValueError("AUTOMATION_TOPIC_INVALID")
        input_data = dict(job.get("input") or {})
        candidates = input_data.get("topicCandidates") or []
        if candidates and selected not in {str(item) for item in candidates}:
            raise ValueError("AUTOMATION_TOPIC_NOT_IN_CHOICES")
        input_data["selectedTopic"] = selected
        self.store.update_job(job_id, input=input_data, status="queued", stage="script", error=None)
        self.store.append_log(job_id, "info", "Đã chọn chủ đề, tiếp tục tạo script.", stage="script")
        return self.start_job(job_id)

    def wait_for_idle(self, timeout: float = 0) -> bool:
        deadline = time.monotonic() + max(0, timeout)
        while True:
            with self._lock:
                active = [future for future in self._futures.values() if not future.done()]
            if not active:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(job_id)
        return bool(event and event.is_set())

    def set_stage(self, job_id: str, stage: str, progress: float, message: str = "") -> None:
        self.store.update_job(job_id, status="running", stage=stage, progress=max(0, min(100, float(progress))))
        if message:
            self.store.append_log(job_id, "info", message, stage=stage)

    def save_artifact(self, job_id: str, name: str, path: Path | str, *, stage: str | None = None) -> None:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        artifacts = dict(job.get("artifacts") or {})
        artifacts[str(name)] = str(target)
        self.store.update_job(job_id, artifacts=artifacts, stage=stage or job.get("stage") or "input")

    def _execute(self, job_id: str) -> None:
        try:
            self._runner(job_id)
            job = self.store.get_job(job_id)
            if job and job["status"] == "running":
                self.store.update_job(job_id, status="completed", stage="done", progress=100, error=None)
                self.store.append_log(job_id, "success", "Job hoàn thành.", stage="done")
        except AutomationCancelled:
            job = self.store.get_job(job_id)
            if job and job["status"] != "cancelled":
                self.store.update_job(job_id, status="paused")
                self.store.append_log(job_id, "warning", "Job đã tạm dừng.", stage=str(job.get("stage") or "input"))
        except Exception as exc:
            job = self.store.get_job(job_id)
            if not job:
                return
            if job["status"] == "cancelled":
                return
            code = self._error_code(exc)
            error = {"code": code, "message": str(exc)[:4000]}
            self.store.update_job(job_id, status="paused", error=error)
            self.store.append_log(job_id, "error", str(exc), stage=str(job.get("stage") or "input"), details={"code": code})
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)

    @staticmethod
    def _error_code(exc: Exception) -> str:
        text = str(exc).strip()
        match = re.match(r"([A-Z][A-Z0-9_]{2,})", text)
        return match.group(1) if match else "AUTOMATION_STAGE_FAILED"

    @staticmethod
    def flow_failure_retryable(status: str, error: str) -> bool:
        """Distinguish a transient Flow submit error from a required action."""
        if str(status) != "failed":
            return False
        return not re.search(
            r"LOGIN_REQUIRED|GENERATION_FAILED|GENERATION_REJECTED|FLOW_EMPTY_OUTPUT|MODEL_UNAVAILABLE|SETTING_MISMATCH|UI_CHANGED",
            str(error or ""),
            re.I,
        )

    def _run_pipeline(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        workspace = self.store.workspace(job_id)
        inputs = dict(job.get("input") or {})
        mode = str(job.get("input_mode") or "topic")
        settings = dict(job.get("settings") or {})
        self.set_stage(job_id, "input", 3, "Đang chuẩn bị input cho job.")
        canonical = self._prepare_inputs(job_id, inputs, workspace)
        self._check_cancel(job_id)

        # AI topic mode intentionally pauses after producing choices.
        topic = str(inputs.get("selectedTopic") or inputs.get("topic") or "").strip()
        if mode == "ai_topic" and not inputs.get("selectedTopic"):
            candidates_path = workspace / "topic_candidates.json"
            cached_candidates = None
            if candidates_path.is_file():
                try:
                    cached = json.loads(candidates_path.read_text(encoding="utf-8"))
                    if isinstance(cached, dict) and cached.get("promptVersion") == _TOPIC_PROMPT_VERSION:
                        cached_candidates = cached.get("candidates")
                except (OSError, ValueError, TypeError):
                    cached_candidates = None
            if cached_candidates is not None:
                candidates = cached_candidates
            else:
                self.set_stage(job_id, "topic", 8, "Đang tạo 5 chủ đề để bạn chọn.")
                content, _ = self._request_chat(job_id, self._topic_prompt(topic, settings), [])
                candidates = self._topic_candidates(content)
                if not candidates:
                    raise RuntimeError("AUTOMATION_TOPIC_EMPTY")
                candidates_path.write_text(json.dumps({"promptVersion": _TOPIC_PROMPT_VERSION, "candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
                inputs["topicCandidates"] = candidates
                self.store.update_job(job_id, input=inputs, artifacts={**(job.get("artifacts") or {}), "topicCandidates": str(candidates_path)})
            if not isinstance(candidates, list) or len(candidates) != 5 or any(not str(item).strip() for item in candidates):
                raise RuntimeError("AUTOMATION_TOPIC_INCOMPLETE")
            inputs["topicCandidates"] = candidates
            self.store.update_job(job_id, input=inputs, status="awaiting_topic", stage="topic", progress=8, error=None)
            self.store.append_log(job_id, "info", "Đã tạo 5 chủ đề; đang chờ bạn chọn.", stage="topic", details={"candidates": candidates})
            return

        script = canonical.get("script")
        if not script and topic:
            self.set_stage(job_id, "script", 12, "Đang tạo script sạch bằng provider AI đã chọn.")
            content, artifact = self._request_chat(job_id, self._script_prompt(topic, settings), [])
            script = workspace / "script.txt"
            self._write_text_result(script, artifact, content)
            self.save_artifact(job_id, "script", script, stage="script")
            inputs["script"] = str(script); inputs["generatedScript"] = True
            self.store.update_job(job_id, input=inputs)
            canonical["script"] = script
        if script:
            self.store.update_job(job_id, stage="script", progress=18)

        audio = canonical.get("audio")
        srt = canonical.get("srt")
        if not audio and script:
            self.set_stage(job_id, "tts", 24, "Đang tạo audio và SRT bằng TTS.")
            tts_cfg = settings.get("tts") if isinstance(settings.get("tts"), dict) else {}
            from pipeline.tts.studio import synth_text_job, ensure_wav, ensure_mp3
            result = synth_text_job(
                text=script.read_text(encoding="utf-8-sig", errors="replace"),
                voice=str(tts_cfg.get("voice") or "system"),
                lang=str(settings.get("language") or "vi"),
                speed=float(tts_cfg.get("speed") or 1.0), volume=float(tts_cfg.get("volume") or 1.0),
                pitch=float(tts_cfg.get("pitch") or 0.0), style=str(tts_cfg.get("style") or "tu_nhien"),
                match_duration="none", auto_split=True, title=job["title"],
            )
            tts_id = str(result.get("id") or "")
            if not tts_id:
                raise RuntimeError("AUTOMATION_TTS_EMPTY")
            from pipeline.tts.voice_store import TTS_OUTPUT
            source_dir = TTS_OUTPUT / tts_id
            audio = workspace / "audio.wav"
            srt = workspace / "subtitles.srt"
            shutil.copy2(ensure_wav(tts_id), audio)
            shutil.copy2(source_dir / "subs.srt", srt)
            self.save_artifact(job_id, "audio", audio, stage="tts")
            self.save_artifact(job_id, "srt", srt, stage="srt")
            inputs.update({"audio": str(audio), "srt": str(srt), "generatedAudio": True, "generatedSrt": True})
            self.store.update_job(job_id, input=inputs)
            # Keep the MP3 beside the job for the user even if composition uses WAV.
            try:
                shutil.copy2(ensure_mp3(tts_id), workspace / "audio.mp3")
                self.save_artifact(job_id, "audioMp3", workspace / "audio.mp3", stage="tts")
            except Exception:
                pass
        if not srt and not canonical.get("prompts"):
            raise RuntimeError("AUTOMATION_SRT_REQUIRED")

        prompts = canonical.get("prompts")
        if not prompts and (srt or audio):
            self.set_stage(job_id, "image_prompt", 39, "Đang phân tích SRT và tạo prompt ảnh.")
            # Prefer SRT (text) for timing and dialogue; chat LLMs do not accept audio attachments.
            files = [path for path in (srt,) if path] or ([script] if script else [])
            content, artifact = self._request_chat(job_id, self._image_prompt_request(settings), files)
            prompts = workspace / "image_prompts.txt"
            self._write_text_result(prompts, artifact, content)
            # Format prompt file so each prompt is separated by a blank line
            clean = self._extract_prompt_lines(prompts.read_text(encoding="utf-8"))
            if clean:
                prompts.write_text(clean + "\n", encoding="utf-8")
            self._validate_prompt_file(prompts)
            self.save_artifact(job_id, "prompts", prompts, stage="image_prompt")
            inputs["prompts"] = str(prompts); inputs["generatedPrompts"] = True
            self.store.update_job(job_id, input=inputs)
            canonical["prompts"] = prompts
        elif prompts:
            self._validate_prompt_file(prompts)

        if prompts:
            self.set_stage(job_id, "flow_images", 48, "Đang đưa prompt vào Flow để tạo ảnh.")
            images = self._run_flow_images(job_id, prompts, settings, workspace)
        else:
            images = []
        self._check_cancel(job_id)
        if not images:
            raise RuntimeError("AUTOMATION_IMAGES_EMPTY")
        self.set_stage(job_id, "compose", 82, "Đang ghép ảnh, audio và SRT thành video.")
        self._compose(job_id, images, audio, srt, prompts, settings, workspace)
        self.set_stage(job_id, "done", 100, "Đã hoàn thành video cuối.")

    def _check_cancel(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if self.is_cancelled(job_id) or (job and job.get("status") == "paused"):
            raise AutomationCancelled("AUTOMATION_PAUSED")

    def _prepare_inputs(self, job_id: str, inputs: dict[str, Any], workspace: Path) -> dict[str, Path]:
        mapping = {"script": "script", "audio": "audio", "srt": "subtitles", "prompts": "image_prompts"}
        result: dict[str, Path] = {}
        for key, filename in mapping.items():
            raw = str(inputs.get(key) or "").strip()
            if not raw:
                continue
            source = Path(raw).expanduser().resolve()
            if not source.is_file():
                raise RuntimeError(f"AUTOMATION_INPUT_MISSING: {key}")
            target = workspace / f"{filename}{source.suffix.lower()}"
            if source != target.resolve():
                shutil.copy2(source, target)
            result[key] = target
            self.save_artifact(job_id, key, target, stage="input")
        return result

    def _topic_prompt(self, topic: str, settings: dict[str, Any]) -> str:
        language = "English" if str(settings.get("language") or "vi").lower() == "en" else "Vietnamese"
        if language == "English":
            instruction = f"STAGE 1 — TOPIC SELECTION. When the user only says start or provides no specific topic, generate exactly 5 potentially engaging educational YouTube video ideas in English that fit this Audio-First 2D engine. Return this compact table and nothing else:\n| # | Video Topic |\n|---|---|\n| 1 | ... |\n| 2 | ... |\n| 3 | ... |\n| 4 | ... |\n| 5 | ... |\nThen write exactly: Choose 1-5 to begin. Starting hint: {topic or 'suggest a strong educational topic.'}"
        else:
            instruction = f"GIAI ĐOẠN 1 — CHỌN CHỦ ĐỀ. Khi người dùng chỉ nói bắt đầu hoặc chưa đưa chủ đề cụ thể, hãy tạo đúng 5 ý tưởng video YouTube giáo dục có khả năng thu hút bằng tiếng Việt, phù hợp với engine Audio-First 2D. Chỉ trả về bảng ngắn này và không thêm nội dung khác:\n| # | Chủ đề video |\n|---|---|\n| 1 | ... |\n| 2 | ... |\n| 3 | ... |\n| 4 | ... |\n| 5 | ... |\nSau đó viết đúng: Chọn số 1-5 để bắt đầu. Gợi ý ban đầu: {topic or 'hãy tự đề xuất chủ đề giáo dục có khả năng thu hút cao.'}"
        prefix = str(settings.get("systemPrompt") or "").strip()
        base = self._audio_first_engine_prompt(settings)
        return (prefix + "\n\n" if prefix else "") + base + "\n\n" + instruction

    @staticmethod
    def _audio_first_engine_prompt(settings: dict[str, Any]) -> str:
        """Return the same complete Audio-First engine used in the Flow prompt library."""
        engine = str((settings.get("flow") or {}).get("promptEngine") or settings.get("language") or "vi")
        return audio_first_prompt(engine)

    def _script_prompt(self, topic: str, settings: dict[str, Any]) -> str:
        prefix = str(settings.get("systemPrompt") or "").strip()
        language = "English" if str(settings.get("language") or "vi").lower() == "en" else "Vietnamese"
        instruction = (
            f"Final topic: {topic}\n"
            "Reply with ONLY the raw narration text — no preamble, no filename mention, no explanation, no markdown. "
            "Start immediately with the first word of the narration."
            if language == "English" else
            f"Chủ đề cuối cùng: {topic}\n"
            "Chỉ trả về đúng nội dung lời thuyết minh thuần văn bản — không mở đầu, không nhắc tên file, không giải thích, không markdown. "
            "Bắt đầu ngay bằng từ đầu tiên của lời thuyết minh."
        )
        engine = self._audio_first_engine_prompt(settings)
        return (prefix + "\n\n" if prefix else "") + engine + "\n" + instruction

    def _image_prompt_request(self, settings: dict[str, Any]) -> str:
        prefix = str(settings.get("systemPrompt") or "").strip()
        language = "English" if str(settings.get("language") or "vi").lower() == "en" else "Vietnamese"
        instruction = (
            "Read the attached SRT with timecodes (or script), split visual beats by meaning, then output ONLY the image prompt lines. "
            "Format: 001_[00:00:00.000-00:00:05.000] <English description>. Separate each prompt with a blank line. "
            "IMPORTANT: every second of the video must be covered — do NOT stop early, do NOT skip any segment. "
            "No preamble, no explanation, no filename mention — start immediately with line 001."
            if language == "English" else
            "Đọc file SRT có timecode (hoặc kịch bản) đính kèm, chia visual beat theo ý nghĩa, rồi chỉ xuất ra các dòng prompt ảnh. "
            "Mỗi prompt theo dạng: 001_[00:00:00.000-00:00:05.000] <mô tả tiếng Anh>. Mỗi prompt cách nhau 1 dòng trống. "
            "QUAN TRỌNG: phải phủ kín toàn bộ thời lượng video — không được dừng sớm, không được bỏ sót đoạn nào. "
            "Không mở đầu, không giải thích, không nhắc tên file — bắt đầu ngay bằng dòng 001."
        )
        instruction = self._audio_first_engine_prompt(settings) + "\n" + instruction
        return (prefix + "\n\n" if prefix else "") + instruction

    @staticmethod
    def _topic_candidates(content: str) -> list[str]:
        values: list[str] = []
        for line in str(content or "").splitlines():
            raw = line.strip()
            if not raw:
                continue
            if re.match(r"^\|?\s*#\s*\|", raw) or re.fullmatch(r"\|?\s*[-:|\s]+\|?", raw):
                continue
            # The canonical Audio-First prompt asks for a Markdown table. Also
            # accept numbered/bulleted output from providers that simplify it.
            table = re.match(r"^\|?\s*\d+\s*\|\s*(.*?)\s*\|?\s*$", raw)
            if table:
                clean = table.group(1).strip(" |")
            else:
                clean = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
            clean = re.sub(r"^#+\s*", "", clean).strip(" |")
            lowered = clean.casefold()
            if (
                not clean
                or len(clean) > 300
                or lowered in {"chủ đề video", "video topic", "chủ đề", "topic"}
                or re.match(r"^(?:chọn|choose)\b", lowered)
                or not re.search(r"[\wÀ-ỹ]", clean)
                or re.fullmatch(r"[-:|\s]+", clean)
            ):
                continue
            values.append(clean)
        return list(dict.fromkeys(values))[:5]

    @staticmethod
    def _strip_ai_meta(text: str) -> str:
        """Remove AI preamble/postamble lines when no artifact file was attached.

        Pattern: lines that are clearly AI commentary rather than content —
        e.g. 'Đã tạo file...', 'Tên file:', 'Hãy tạo audio...', trailing ```.
        ponytail: simple line-filter; upgrade to LLM post-processing if needed.
        """
        # Strip outer fenced code blocks first
        text = re.sub(r"^```(?:txt|text|markdown)?\s*", "", text.strip(), flags=re.I)
        text = re.sub(r"\s*```$", "", text.strip(), flags=re.I)
        # Drop lines that look like AI meta commentary
        _META = re.compile(
            r"^(?:"
            r"(?:Đã tạo|Đã nhận|Đã phân tích|I(?:'ve| have) (?:created|generated|attached|analyzed))"
            r"|(?:Tên file|File name|Filename)\s*:"
            r"|(?:Hãy tạo|Please (?:create|generate|use|send))"
            r"|(?:Bạn có thể|You can)"
            r"|(?:Lưu ý|Note)\s*:"
            r"|```"
            r")",
            re.I,
        )
        lines = [ln for ln in text.splitlines() if not _META.match(ln.strip())]
        return "\n".join(lines).strip()

    @classmethod
    def _write_text_result(cls, target: Path, artifact: Path | None, content: str) -> None:
        source = artifact if artifact and artifact.is_file() else None
        if source:
            text = source.read_text(encoding="utf-8-sig", errors="replace")
            text = re.sub(r"^```(?:txt|text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I).strip()
        else:
            # No artifact: AI pasted content inline — strip meta commentary
            text = cls._strip_ai_meta(str(content or ""))
        if not text:
            raise RuntimeError("AUTOMATION_CHAT_EMPTY_ARTIFACT")
        target.write_text(text + "\n", encoding="utf-8")

    @staticmethod
    def _extract_prompt_lines(text: str) -> str:
        """Keep valid timecode prompt blocks (NNN_[HH:MM:SS...] ...).

        A prompt block starts with the NNN_[ marker line and includes all
        subsequent non-blank lines that belong to the same entry (multi-line
        descriptions). Blocks are separated by a blank line in the output.
        """
        blocks: list[str] = []
        current: list[str] = []
        for ln in text.splitlines():
            stripped = ln.strip()
            if re.match(r"^\d{3}_\[", stripped):
                # Start of a new prompt block
                if current:
                    blocks.append("\n".join(current))
                current = [stripped]
            elif current and stripped:
                # Continuation line of the current block
                current.append(stripped)
            else:
                # Blank line → end of current block
                if current:
                    blocks.append("\n".join(current))
                    current = []
        if current:
            blocks.append("\n".join(current))
        return "\n\n".join(blocks)

    @staticmethod
    def _plain_prompt_lines(text: str) -> list[str]:
        return [line.strip() for line in str(text or "").splitlines() if line.strip()]

    @classmethod
    def _has_timed_prompts(cls, path: Path) -> bool:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return bool(cls._extract_prompt_lines(text))

    @staticmethod
    def _validate_prompt_file(path: Path) -> None:
        from pipeline.srt_image import parse_timing_cues_detailed
        try:
            cues = parse_timing_cues_detailed(path)
        except Exception:
            cues = []
        if not cues and not AutomationService._plain_prompt_lines(path.read_text(encoding="utf-8-sig", errors="replace")):
            raise RuntimeError("AUTOMATION_PROMPTS_EMPTY")

    def _request_chat(self, job_id: str, prompt: str, files: list[Path]) -> tuple[str, Path | None]:
        self._check_cancel(job_id)
        from api.routes.chat import service as chat_service
        current_job = self.store.get_job(job_id) or {}
        input_data = dict(current_job.get("input") or {})
        settings = dict(current_job.get("settings") or {})
        selected_provider = str(settings.get("textProvider") or "").strip().lower()
        selected_model = str(settings.get("textModel") or settings.get("chatModel") or "").strip()
        # Jobs created before the provider selector used ChatGPT Web implicitly.
        if not selected_provider:
            selected_provider = "chatgpt_web" if settings.get("chatModel") else chat_service.DEFAULT_API_PROVIDER
        if selected_provider == "chatgpt_web":
            account = chat_service.primary_account()
            if not account or account.get("status") != "connected":
                raise RuntimeError("CHATGPT_LOGIN_REQUIRED")
            stored_provider = account["id"]
            selected_model = selected_model or str(account.get("last_model") or chat_service.DEFAULT_MODEL)
        else:
            stored_provider = selected_provider
            selected_model = selected_model or (chat_service.DEFAULT_API_MODEL if selected_provider == "openrouter" else "")
            try:
                chat_service.resolve_provider(selected_provider, selected_model)
            except Exception as exc:
                code = getattr(exc, "code", "CHAT_PROVIDER_UNAVAILABLE")
                secret = str(load_app_config().get("cloud", {}).get(selected_provider, {}).get("apiKey") or "")
                detail = exc.safe_message(secret) if hasattr(exc, "safe_message") else str(exc).replace(secret, "[REDACTED]")
                raise RuntimeError(f"{code}: {detail[:500]}") from None
        conversation_id = str(input_data.get("chatConversationId") or "")
        conversation = chat_service.store.get_conversation(conversation_id) if conversation_id else None
        conversation_provider = str(conversation.get("provider_id") or conversation.get("account_id") or "") if conversation else ""
        legacy_web_conversation = bool(
            conversation
            and selected_provider == "chatgpt_web"
            and str(conversation.get("account_id") or "") == str(stored_provider)
        )
        if conversation and conversation_provider != selected_provider and not legacy_web_conversation:
            conversation = None
        if not conversation:
            conversation = chat_service.store.create_conversation(
                current_job.get("title") or "Automation",
                stored_provider,
                selected_model,
                provider_id=selected_provider,
            )
            input_data["chatConversationId"] = conversation["id"]
            self.store.update_job(job_id, input=input_data)
        attachment_ids: list[str] = []
        for path in files:
            if not path or not path.is_file():
                continue
            suffix = path.suffix.lower()
            content_type = "audio/wav" if suffix == ".wav" else "audio/mpeg" if suffix == ".mp3" else "text/plain"
            saved = chat_service.store.save_attachment(conversation["id"], path.name, path.read_bytes(), max_size=100 * 1024 * 1024, content_type=content_type)
            attachment_ids.append(saved["id"])
        artifact_path: Path | None = None
        content = ""
        with self._chat_gate:
            for raw in chat_service.stream_message(conversation["id"], {"content": prompt, "attachmentIds": attachment_ids, "mode": "chat", "provider": selected_provider, "model": selected_model}):
                for block in str(raw).split("\n\n"):
                    event = ""
                    data = ""
                    for line in block.splitlines():
                        if line.startswith("event: "): event = line[7:].strip()
                        elif line.startswith("data: "): data = line[6:].strip()
                    if not data: continue
                    try: payload = json.loads(data)
                    except ValueError: continue
                    if event == "content.delta": content += str(payload.get("delta") or "")
                    elif event == "message.completed" and payload.get("content") is not None: content = str(payload.get("content") or content)
                    elif event == "artifact.completed":
                        artifact = payload.get("artifact") or {}
                        aid = str(artifact.get("id") or "")
                        if aid:
                            try:
                                candidate = chat_service.store.attachment_path(aid)
                                if candidate.is_file() and candidate.suffix.lower() in {".txt", ".md", ".markdown"}: artifact_path = candidate
                            except (KeyError, ValueError):
                                pass
                    elif event == "message.failed":
                        code = str(payload.get("errorCode") or "CHAT_PROVIDER_REQUEST_FAILED")
                        detail = str(payload.get("error") or "").strip()
                        raise RuntimeError(f"{code}: {detail[:500]}" if detail else code)
        return content, artifact_path

    def _run_flow_images(self, job_id: str, prompts: Path, settings: dict[str, Any], workspace: Path) -> list[Path]:
        from pipeline.flow import service as flow_service
        flow_cfg = settings.get("flow") if isinstance(settings.get("flow"), dict) else {}
        account_id = str(flow_cfg.get("accountId") or "")
        account = next((row for row in flow_service.accounts() if str(row.get("id")) == account_id), None) if account_id else None
        if not account or account.get("status") != "online":
            raise RuntimeError("FLOW_LOGIN_REQUIRED")
        text = prompts.read_text(encoding="utf-8-sig", errors="replace")
        prompt_lines = [line.strip() for line in text.splitlines() if re.match(r"^\d{3}_\[", line.strip())]
        if not prompt_lines:
            prompt_lines = self._plain_prompt_lines(text)
        image_dir = workspace / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        cached = sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".avif"})
        if prompt_lines and len(cached) >= len(prompt_lines):
            self.store.update_job(job_id, artifacts={**(self.store.get_job(job_id).get("artifacts") or {}), "images": str(image_dir)})
            self.store.append_log(job_id, "info", "Đã dùng lại ảnh Flow từ checkpoint.", stage="flow_images")
            return cached[:len(prompt_lines)]
        parent = self.store.get_job(job_id) or {}
        existing_child_ids = [str(value) for value in (parent.get("child_job_ids") or []) if str(value)]
        existing_snapshot = {str(row.get("id")): row for row in flow_service.jobs()}
        if existing_child_ids and all(child_id in existing_snapshot for child_id in existing_child_ids):
            # Resuming a failed parent must observe the already queued Flow
            # children instead of creating a second batch for the same scenes.
            child_ids = existing_child_ids
        else:
            jobs = flow_service.enqueue({
                "prompts": prompt_lines,
                "kind": "image", "mode": "text", "accountId": account_id,
                "settings": {"model": str(flow_cfg.get("model") or "Nano Banana 2"), "ratio": str(flow_cfg.get("ratio") or "16:9"), "resolution": str(flow_cfg.get("resolution") or "1K"), "count": int(flow_cfg.get("count") or 1), "concurrency": str(flow_cfg.get("concurrency") or "3"), "outputDir": f"automation_{job_id}"},
            })
            child_ids = [str(item["id"]) for item in jobs]
            self.store.update_job(job_id, child_job_ids=child_ids)
        outputs: list[Path] = []
        pending = set(child_ids)
        retried_children: set[str] = set()
        while pending:
            try:
                self._check_cancel(job_id)
            except AutomationCancelled:
                # Do not leave provider children consuming the Flow account after
                # the parent job has been paused or cancelled.
                for child_id in pending:
                    try:
                        flow_service.cancel(child_id)
                    except Exception:
                        pass
                raise
            flow_snapshot = {str(row.get("id")): row for row in flow_service.jobs()}
            for child_id in list(pending):
                child = flow_snapshot.get(child_id, {})
                status = str(child.get("status") or "")
                if status in {"failed", "action_required", "cancelled"}:
                    error = str(child.get("error") or child_id)
                    if self.flow_failure_retryable(status, error) and child_id not in retried_children:
                        retried_children.add(child_id)
                        self.store.append_log(job_id, "warning", f"Flow ảnh {child.get('inputIndex') or child_id} lỗi tạm thời, đang thử lại.", stage="flow_images", details={"code": "FLOW_IMAGE_RETRY"})
                        flow_service.retry(child_id)
                        continue
                    raise RuntimeError(f"FLOW_IMAGE_FAILED: {error}")
                if status != "done":
                    continue
                source = Path(str((child.get("outputs") or [""])[0]))
                if not source.is_file():
                    raise RuntimeError(f"FLOW_IMAGE_OUTPUT_MISSING: ảnh {child.get('inputIndex') or child_id} không có file đầu ra")
                target = image_dir / f"{int(child.get('inputIndex') or len(outputs) + 1):03d}{source.suffix.lower() or '.png'}"
                shutil.copy2(source, target)
                outputs.append(target)
                pending.remove(child_id)
                self.set_stage(job_id, "flow_images", 48 + (len(outputs) / max(1, len(child_ids))) * 30, f"Đã tạo {len(outputs)}/{len(child_ids)} ảnh Flow.")
            time.sleep(0.5)
        outputs.sort(key=lambda path: path.name)
        if outputs:
            self.store.update_job(job_id, artifacts={**(self.store.get_job(job_id).get("artifacts") or {}), "images": str(image_dir)})
        return outputs

    def _compose(self, job_id: str, images: list[Path], audio: Path | None, srt: Path | None, prompts: Path | None, settings: dict[str, Any], workspace: Path) -> None:
        from pipeline import srt_image
        existing = Path(str((self.store.get_job(job_id).get("artifacts") or {}).get("video") or ""))
        if existing.is_file():
            self.store.append_log(job_id, "info", "Đã dùng lại video từ checkpoint.", stage="compose")
            return
        compose = settings.get("compose") if isinstance(settings.get("compose"), dict) else {}
        raw_watermark = str((self.store.get_job(job_id).get("input") or {}).get("watermark") or "")
        watermark = Path(raw_watermark) if raw_watermark else None
        if watermark is not None and not watermark.is_file():
            watermark = None
        configured = str(settings.get("outputDir") or "").strip()
        from pipeline.core.output_paths import selected_or_default
        base_dir = selected_or_default("automation", configured)
        output_dir = base_dir / safe_output_part(self.store.get_job(job_id)["title"], "job") / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        subtitle_enabled = bool(compose.get("subtitleEnabled", True))
        options = {
            "resolution": str(compose.get("resolution") or "auto"),
            "targetPlatform": str(compose.get("targetPlatform") or "auto"),
            "fps": int(compose.get("fps") or 30),
            "crf": int(compose.get("crf") or 20),
            "encoder": str(compose.get("encoder") or "auto"),
            "effect": str(compose.get("effect") or "none"),
            "transitionDuration": float(compose.get("transitionDuration") or 0.28),
            "zoom": str(compose.get("zoom") or "off"),
            "speed": float(compose.get("speed") or 100),
            "volume": float(compose.get("volume") or 100),
            "previewSeconds": float(compose.get("previewSeconds") or 0),
            "removeMetadata": bool(compose.get("removeMetadata", False)),
            "allowMissingMedia": bool(compose.get("allowMissingMedia", False)),
            "subtitleFontFamily": str(compose.get("subtitleFontFamily") or "system"),
            "subtitleSize": float(compose.get("subtitleSize") or 8),
            "subtitleOffset": float(compose.get("subtitleOffset") or 0),
            "subtitleMargin": float(compose.get("subtitleMargin") or 34),
            "subtitleBackground": str(compose.get("subtitleBackground") or "solid"),
            "subtitleColor": str(compose.get("subtitleColor") or "#ffffff"),
            "subtitleBgColor": str(compose.get("subtitleBgColor") or "#000000"),
            "subtitleOpacity": float(compose.get("subtitleOpacity") or 55),
            "delogo": {"enabled": bool(compose.get("delogoEnabled", False)), "auto": bool(compose.get("delogoAuto", True)), "x": float(compose.get("delogoX") or 80), "y": float(compose.get("delogoY") or 82), "w": float(compose.get("delogoW") or 18), "h": float(compose.get("delogoH") or 12)},
            "drawing": {"enabled": bool(compose.get("drawingEnabled", False)), "mode": str(compose.get("drawingMode") or "hand"), "tool": str(compose.get("drawingTool") or "pencil"), "detail": int(compose.get("drawingDetail") or 72), "thickness": int(compose.get("drawingThickness") or 2), "strokeOrder": str(compose.get("drawingStrokeOrder") or "natural"), "resolution": "1080p"},
            "logo": {"enabled": bool(compose.get("logoEnabled", False)), "source": str(compose.get("logoSource") or "text"), "text": str(compose.get("logoText") or "ZM AIO TOOL"), "icon": str(compose.get("logoIcon") or "★"), "fontSize": int(compose.get("logoFontSize") or 32), "color": str(compose.get("logoColor") or "#ffffff"), "size": float(compose.get("logoSize") or 8), "opacity": float(compose.get("logoOpacity") or 85), "x": float(compose.get("logoX") or 88), "y": float(compose.get("logoY") or 88), "motion": str(compose.get("logoMotion") or "fixed"), "scope": str(compose.get("logoScope") or "full"), "start": float(compose.get("logoStart") or 0), "end": float(compose.get("logoEnd") or 10), "visibleSec": float(compose.get("logoVisibleSec") or 4), "hiddenSec": float(compose.get("logoHiddenSec") or 2), "fadeSec": float(compose.get("logoFadeSec") or .5), "safeMargin": float(compose.get("logoSafeMargin") or 4)},
        }
        work = workspace / "render-work"
        # The SRT renderer writes its concat manifest into the work directory.
        # Automation owns this directory (unlike the direct SRT upload route),
        # so create it before handing the job to the renderer.
        work.mkdir(parents=True, exist_ok=True)
        timeline = prompts if prompts and self._has_timed_prompts(prompts) else None
        render_job = srt_image.create_job("output.mp4", work, images, audio, timeline, srt if subtitle_enabled else None, options, watermark, output_dir / "output.mp4")
        srt_image.start(render_job["id"])
        while True:
            try:
                self._check_cancel(job_id)
            except AutomationCancelled:
                try:
                    srt_image.cancel(render_job["id"])
                except Exception:
                    pass
                raise
            state = srt_image.get_job(render_job["id"]) or {}
            progress = float(state.get("progress") or 0)
            self.set_stage(job_id, "compose", 82 + progress * 0.17, f"Đang ghép video: {progress:.0f}%.")
            if state.get("status") == "done":
                output = Path(str(state.get("output") or ""))
                self.save_artifact(job_id, "video", output, stage="compose")
                return
            if state.get("status") == "error":
                raise RuntimeError(f"COMPOSE_FAILED: {state.get('error') or 'renderer error'}")
            if state.get("status") == "cancelled":
                raise AutomationCancelled("AUTOMATION_PAUSED")
            time.sleep(0.5)


service = AutomationService()
