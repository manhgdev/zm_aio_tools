"""Persistent-account Google Flow worker built around flow-py."""
from __future__ import annotations

import asyncio
import logging
import os
import re
try:
    from flow._models import GenerationMode as _GenerationMode
except Exception:  # ponytail: graceful if flow lib version lacks this
    _GenerationMode = None
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from pipeline.core.config import PUBLIC_DATA
from pipeline.core.output_paths import safe_output_part, selected_or_default
from . import store

_PROJECT_RE = re.compile(r"/flow/project/([^/?#]+)")
_TERMINAL = {"done", "failed", "cancelled", "action_required"}
_DEFAULT_CONCURRENT_JOBS_PER_ACCOUNT = 3
_MAX_CONCURRENT_JOBS_PER_ACCOUNT = 6
_PROFILE_COPY_IGNORES = {
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "GraphiteDawnCache", "GPUPersistentCache", "ShaderCache", "GrShaderCache",
    "Crashpad", "SingletonCookie", "SingletonLock", "SingletonSocket", "LOCK",
}
_IMAGE_UI_MODELS = {"Nano Banana Pro", "Nano Banana 2", "Nano Banana 2 Lite"}
_VIDEO_UI_MODELS = {
    "Omni Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast",
    "Veo 3.1 - Quality", "Veo 3.1 - Lite [Lower Priority]",
}


def _detect_plan(credit_info: Any) -> str | None:
    """Map Flow's Credits object to 'Pro' or 'Ultra'.

    Google Flow exposes ``userPaygateTier`` (e.g. PAYGATE_TIER_ONE/TWO)
    and ``sku`` (e.g. labs_pro_monthly, labs_ultra_monthly).  We try both
    fields so the detection stays robust across API versions.
    Returns None when we cannot determine the tier (caller keeps existing).
    """
    tier = str(getattr(credit_info, "tier", "") or "").lower()
    sku  = str(getattr(credit_info, "sku",  "") or "").lower()
    combined = tier + " " + sku
    if "ultra" in combined or "tier_two" in combined or "tier_2" in combined:
        return "Ultra"
    if "pro" in combined or "tier_one" in combined or "tier_1" in combined:
        return "Pro"
    return None



def _job_concurrency(settings: dict[str, Any]) -> int:
    try:
        value = int(settings.get("concurrency", _DEFAULT_CONCURRENT_JOBS_PER_ACCOUNT))
    except (TypeError, ValueError):
        value = _DEFAULT_CONCURRENT_JOBS_PER_ACCOUNT
    return max(1, min(_MAX_CONCURRENT_JOBS_PER_ACCOUNT, value))


def _match_model_choice(requested: str, text: str) -> bool:
    req = requested.strip().lower()
    t = re.sub(r"\s+", " ", text).strip().lower()
    if req in t:
        return True
    if req == "omni flash":
        return "omni" in t or "flash" in t
    if "lower priority" in req:
        return "lower priority" in t or "lite [lower priority]" in t
    if req == "veo 3.1 - lite":
        return "lite" in t and "lower" not in t
    if req == "veo 3.1 - fast":
        return "fast" in t
    if req == "veo 3.1 - quality":
        return "quality" in t
    if "nano banana" in req:
        return "nano" in t or "banana" in t or "imagen" in t
    return False


async def _click_settings_pill(pill, tabs) -> bool:
    """Open Flow settings, retrying with a forced click for Windows DPI."""
    for force in (False, True):
        try:
            await pill.click(force=force)
        except Exception:
            if force:
                return False
            continue
        await asyncio.sleep(.35)
        for index in range(await tabs.count()):
            if await tabs.nth(index).is_visible():
                return True
    return False


class FlowService:
    def __init__(self) -> None:
        self._account_active: dict[str, int] = {}
        self._claimed_media_ids: set[str] = set()
        self._cancelled: set[str] = set()
        self._guard = threading.RLock()
        self._account_condition = threading.Condition(self._guard)

    def _claim_media_ids(self, candidates: list[str], expected_count: int) -> list[str]:
        """Atomically assign project media so concurrent jobs cannot share one output."""
        with self._guard:
            persisted = {
                str(media_id)
                for job in self.jobs()
                for media_id in (job.get("mediaIds") or [])
                if str(media_id)
            }
            used = persisted | self._claimed_media_ids
            selected = [media_id for media_id in candidates if media_id not in used][:expected_count]
            if len(selected) == expected_count:
                self._claimed_media_ids.update(selected)
                return selected
            return []

    def accounts(self) -> list[dict[str, Any]]:
        return store.list_rows("accounts")

    def jobs(self) -> list[dict[str, Any]]:
        # Queue order is FIFO: the first prompt stays at the top and is the
        # first job resumed after an app restart.  History can still sort by
        # timestamp in the UI when a newest-first view is appropriate.
        rows: list[dict[str, Any]] = []
        for row in sorted(store.list_rows("jobs"), key=lambda item: item.get("createdAt", 0)):
            item = self._migrate_legacy_kind_output_folder(dict(row))
            # The queue must expose the same concrete folder used by the
            # worker; the saved setting can legitimately be just "test".
            settings = item.get("settings")
            if isinstance(settings, dict) and str(settings.get("outputDir") or "").strip():
                output_dir = str(settings.get("outputDir") or "")
                # The queue must always report the same on-disk folder used
                # by the worker, including in the browser build.
                item["displayOutputFolder"] = str(self._display_output_folder(item))
                item["outputFolder"] = str(self._output_folder(item, create=False))
            rows.append(item)
        return rows

    def _migrate_legacy_kind_output_folder(self, job: dict[str, Any]) -> dict[str, Any]:
        """Move legacy flat Flow outputs into ``flow/<kind>/<user-name>``."""
        settings = job.get("settings")
        kind = str(job.get("kind") or "")
        if not isinstance(settings, dict) or kind not in {"video", "image"}:
            return job
        original = str(settings.get("outputDir") or "").strip()
        normalized = original.replace("\\", "/").rstrip("/")
        suffixes = (f"/{kind}", f"-{kind}")
        base = next((normalized[: -len(suffix)] for suffix in suffixes if normalized.endswith(suffix)), normalized)
        if not base:
            return job
        migrated = dict(job)
        migrated_settings = dict(settings)
        migrated_settings["outputDir"] = base
        migrated["settings"] = migrated_settings
        target_folder = self._output_folder(migrated)
        migrated_outputs = []
        source_folders: set[Path] = set()
        for raw_output in job.get("outputs") or []:
            output = Path(str(raw_output))
            target = target_folder / output.name
            if output != target and output.is_file():
                source_folders.add(output.parent)
                if not target.exists():
                    shutil.move(str(output), str(target))
            migrated_outputs.append(str(target if target.exists() else output))
        for source_folder in source_folders:
            try:
                source_folder.rmdir()
            except OSError:
                pass
        migrated["outputs"] = migrated_outputs
        migrated["outputFolder"] = str(target_folder)
        if (
            original != base
            or migrated_outputs != list(job.get("outputs") or [])
            or (bool(job.get("outputFolder")) and str(job.get("outputFolder")) != str(target_folder))
        ):
            store.patch_row("jobs", str(job.get("id") or ""), {
                "settings": migrated_settings,
                "outputs": migrated_outputs,
                "outputFolder": str(target_folder),
            })
        return migrated

    def logs(self) -> list[dict[str, Any]]:
        return sorted(store.list_rows("logs"), key=lambda row: row.get("createdAt", 0), reverse=True)[:1000]

    def clear_logs(self) -> None:
        for row in store.list_rows("logs"):
            store.delete_row("logs", str(row.get("id") or ""))

    def _log(
        self,
        level: str,
        event: str,
        *,
        job_id: str = "",
        account_id: str = "",
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        store.put_row("logs", {
            "id": uuid.uuid4().hex[:16],
            "level": level,
            "event": event,
            "jobId": job_id,
            "accountId": account_id,
            "message": message,
            "details": details or {},
            "createdAt": time.time(),
        })

    def start(self) -> None:
        """Resume work that was queued or interrupted by an app restart."""
        for job in self.jobs():
            if job.get("status") in {"queued", "processing"}:
                store.patch_row("jobs", job["id"], {"status": "queued", "stage": "queued", "progress": 0, "updatedAt": time.time()})
                threading.Thread(target=self._run_sync, args=(job["id"],), daemon=True, name=f"flow-resume-{job['id']}").start()
            elif job.get("status") == "done" and not self._outputs_exist(job.get("outputs")):
                store.patch_row("jobs", job["id"], {
                    "status": "failed",
                    "stage": "failed",
                    "progress": 0,
                    "error": "FLOW_EMPTY_OUTPUT: generation finished without a downloaded media file",
                    "updatedAt": time.time(),
                })

    @staticmethod
    def _outputs_exist(outputs: Any) -> bool:
        paths = [Path(str(value)) for value in (outputs or []) if str(value)]
        return bool(paths) and all(path.is_file() and path.stat().st_size > 0 for path in paths)

    def save_account(self, payload: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
        now = time.time()
        existing = store.get_row("accounts", account_id or "") or {}
        row = {
            **existing,
            "id": account_id or uuid.uuid4().hex[:12],
            "label": str(payload.get("label") or existing.get("label") or "Flow account").strip(),
            "email": str(payload.get("email") or existing.get("email") or "").strip(),
            "plan": str(payload.get("plan") or existing.get("plan") or "Pro"),
            "projectId": str(payload.get("projectId") or existing.get("projectId") or "").strip(),
            "status": existing.get("status", "reconnect"),
            "credits": existing.get("credits"),
            "creditsSyncedAt": existing.get("creditsSyncedAt"),
            "isDefault": bool(payload.get("isDefault", existing.get("isDefault", not self.accounts()))),
            "createdAt": existing.get("createdAt", now),
            "updatedAt": now,
        }
        if row["isDefault"]:
            for account in self.accounts():
                if account["id"] != row["id"]:
                    store.patch_row("accounts", account["id"], {"isDefault": False})
        return store.put_row("accounts", row)

    def delete_account(self, account_id: str) -> bool:
        if any(job.get("accountId") == account_id and job.get("status") not in _TERMINAL for job in self.jobs()):
            raise RuntimeError("Account still has active Flow jobs")
        removed = store.delete_row("accounts", account_id)
        if removed:
            shutil.rmtree(store.root() / "profiles" / account_id, ignore_errors=True)
        return removed

    def delete_job(self, job_id: str) -> bool:
        job = store.get_row("jobs", job_id)
        if not job:
            return False
        if job.get("status") not in _TERMINAL:
            self._cancelled.add(job_id)
            store.patch_row("jobs", job_id, {"status": "cancelled", "stage": "cancelled", "progress": 0, "updatedAt": time.time()})
        removed = store.delete_row("jobs", job_id)
        if removed:
            # Output folders can now be shared by multiple prompts. Only remove
            # artifacts belonging to this job, then remove the folder if empty.
            for raw_output in job.get("outputs") or []:
                try:
                    output = Path(str(raw_output))
                    if output.is_file():
                        output.unlink()
                except OSError:
                    pass
            try:
                self._output_folder(job, create=False).rmdir()
            except OSError:
                pass
        return removed

    def cancel_all(self) -> int:
        count = 0
        for job in self.jobs():
            if job.get("status") not in _TERMINAL and self.cancel(str(job["id"])):
                count += 1
        return count

    def cancel_output_folder_jobs(self, output_dir: str, kind: str = "") -> int:
        """Cancel only queued or running jobs stored in one Flow folder."""
        selected = str(output_dir or "").strip()
        if not selected:
            return 0
        count = 0
        for job in self.jobs():
            if str((job.get("settings") or {}).get("outputDir") or "").strip() != selected:
                continue
            if kind and str(job.get("kind") or "") != kind:
                continue
            if job.get("status") not in _TERMINAL and self.cancel(str(job["id"])):
                count += 1
        return count

    def delete_all_jobs(self) -> int:
        count = 0
        for job in self.jobs():
            if self.delete_job(str(job["id"])):
                count += 1
        return count

    def delete_output_folder_jobs(self, output_dir: str, kind: str = "") -> int:
        """Delete only the jobs and real artifacts belonging to one Flow folder."""
        selected = str(output_dir or "").strip()
        if not selected:
            return 0
        matched = [
            job for job in self.jobs()
            if str((job.get("settings") or {}).get("outputDir") or "").strip() == selected
            and (not kind or str(job.get("kind") or "") == kind)
        ]
        if not matched:
            return 0
        folder = self._output_folder(matched[0], create=False)
        count = 0
        for job in matched:
            if self.delete_job(str(job["id"])):
                count += 1
        # Remove untracked remnants too (for example an interrupted download),
        # but only after restricting the operation to the matched output path.
        shutil.rmtree(folder, ignore_errors=True)
        return count

    def connect(self, account_id: str) -> dict[str, Any]:
        account = store.get_row("accounts", account_id)
        if not account:
            raise KeyError(account_id)
        store.patch_row("accounts", account_id, {"status": "connecting", "error": None, "updatedAt": time.time()})
        self._log("info", "account_connecting", account_id=account_id)
        threading.Thread(target=lambda: asyncio.run(self._login(account_id)), daemon=True, name=f"flow-login-{account_id}").start()
        return store.get_row("accounts", account_id) or account

    async def sync_credits_for_account(self, account_id: str) -> dict[str, Any]:
        """Fetch fresh credits from Google Flow using the existing browser profile.

        Uses a headless Chrome session with the already-saved login profile — no
        interactive sign-in needed.  Returns the updated account row.
        """
        account = store.get_row("accounts", account_id)
        if not account:
            raise KeyError(account_id)
        project_id = str(account.get("projectId") or "")
        if account.get("status") != "online" or not project_id:
            raise RuntimeError("FLOW_LOGIN_REQUIRED: account must be connected before syncing credits")
        from flow._api import FlowAPI
        from .browser import BrowserManager
        browser = BrowserManager(headless=True, profile_dir=store.profile_dir(account_id))
        try:
            await browser.start()
            api = FlowAPI(browser, project_id=project_id)
            credit_info = await api.get_credits()
            patch: dict[str, Any] = {
                "credits": int(credit_info.credits),
                "creditsSyncedAt": time.time(),
                "updatedAt": time.time(),
            }
            detected_plan = _detect_plan(credit_info)
            if detected_plan:
                patch["plan"] = detected_plan
            store.patch_row("accounts", account_id, patch)
        finally:
            try:
                await browser.stop()
            except Exception:
                pass
        return store.get_row("accounts", account_id) or account


    def sync_all_credits(self) -> list[dict[str, Any]]:
        """Fire-and-forget credit sync for every online account.

        Spawns one background thread per online account and returns immediately
        with the current (pre-sync) account list.  The frontend's normal polling
        will pick up the updated balances on the next GET /accounts or /jobs.
        """
        online = [a for a in self.accounts() if a.get("status") == "online" and a.get("projectId")]
        for account in online:
            account_id = account["id"]
            threading.Thread(
                target=lambda aid=account_id: asyncio.run(self.sync_credits_for_account(aid)),
                daemon=True,
                name=f"flow-sync-{account_id}",
            ).start()
        return self.accounts()



    async def _login(self, account_id: str) -> None:
        try:
            from .browser import BrowserManager, FLOW_BASE_URL
            browser = BrowserManager(headless=False, profile_dir=store.profile_dir(account_id))
            await browser.start()
            page = await browser.page()
            await page.goto(FLOW_BASE_URL, wait_until="domcontentloaded")
            deadline = time.monotonic() + 600
            project_id = ""
            while time.monotonic() < deadline:
                match = _PROJECT_RE.search(page.url)
                signed_in = "accounts.google.com" not in page.url
                if match:
                    project_id = match.group(1)
                    break
                if signed_in and "labs.google" in page.url:
                    links = await page.locator('a[href*="/flow/project/"]').all()
                    if links:
                        href = await links[0].get_attribute("href") or ""
                        match = _PROJECT_RE.search(href)
                        if match:
                            project_id = match.group(1)
                            break
                await asyncio.sleep(2)
            if not project_id:
                await browser.stop()
                raise RuntimeError("Login timed out or no Google Flow project was opened")
            email = await page.evaluate("() => window.__NEXT_DATA__?.props?.pageProps?.session?.user?.email || ''")
            credits = None
            credits_synced_at = None
            detected_plan = None
            try:
                from flow._api import FlowAPI
                credit_info = await FlowAPI(browser, project_id=project_id).get_credits()
                credits = int(credit_info.credits)
                credits_synced_at = time.time()
                detected_plan = _detect_plan(credit_info)
                _log.info("Plan detected on connect: %s (tier=%s sku=%s)",
                          detected_plan, getattr(credit_info, 'tier', ''), getattr(credit_info, 'sku', ''))
            except Exception:
                pass
            await browser.stop()
            patch: dict[str, Any] = {
                "status": "online", "projectId": project_id,
                "email": email or (store.get_row("accounts", account_id) or {}).get("email", ""),
                "credits": credits, "creditsSyncedAt": credits_synced_at,
                "updatedAt": time.time(), "error": None,
            }
            if detected_plan:
                patch["plan"] = detected_plan
            store.patch_row("accounts", account_id, patch)
            self._log("success", "account_connected", account_id=account_id, details={"projectId": project_id, "credits": credits, "plan": detected_plan})
        except Exception as exc:
            store.patch_row("accounts", account_id, {"status": "reconnect", "error": str(exc), "updatedAt": time.time()})
            self._log("error", "account_connect_failed", account_id=account_id, message=str(exc))

    def enqueue(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        prompts = [str(value).strip() for value in payload.get("prompts", []) if str(value).strip()]
        account_id = str(payload.get("accountId") or "")
        if not prompts or not store.get_row("accounts", account_id):
            raise ValueError("Prompts and a valid Flow account are required")
        settings = dict(payload.get("settings") or {})
        settings["concurrency"] = _job_concurrency(settings)
        kind = str(payload.get("kind") or "video")
        mode = str(payload.get("mode") or "text")
        input_type = str(payload.get("inputType") or "prompt").lower()
        if input_type not in {"prompt", "txt", "csv", "json"}:
            input_type = "prompt"
        source_files = list(payload.get("sourceFiles") or [])
        series_context = dict(payload.get("seriesContext") or {})
        if kind == "image":
            if str(settings.get("model") or "Nano Banana 2") not in _IMAGE_UI_MODELS:
                raise ValueError(f"Unsupported Flow image model: {settings.get('model')}")
            if mode != "text" and not source_files:
                raise ValueError("Image edit/reference mode requires at least one source image")
        else:
            if str(settings.get("model") or "Veo 3.1 - Fast") not in _VIDEO_UI_MODELS:
                raise ValueError(f"Unsupported Flow video model: {settings.get('model')}")
        created = []
        for index, prompt in enumerate(prompts, 1):
            now = time.time()
            job_input_index = int(payload.get("inputIndex") or series_context.get("sceneIndex") or index)
            job = {
                "id": uuid.uuid4().hex[:12], "inputIndex": job_input_index, "kind": kind,
                "mode": mode, "prompt": prompt, "accountId": account_id,
                "inputType": input_type,
                "settings": settings, "sourceFiles": source_files,
                "seriesContext": series_context,
                "status": "queued", "stage": "queued", "progress": 0, "mediaIds": [], "outputs": [],
                "error": None, "createdAt": now, "updatedAt": now,
            }
            job["outputFolder"] = str(self._output_folder(job, create=False))
            job["displayOutputFolder"] = str(self._display_output_folder(job))
            store.put_row("jobs", job)
            if series_context:
                from . import series
                series.register_job(job)
            self._log("info", "job_queued", job_id=job["id"], account_id=account_id, details={"kind": job["kind"], "inputIndex": job_input_index})
            created.append(job)
            threading.Thread(target=self._run_sync, args=(job["id"],), daemon=True, name=f"flow-job-{job['id']}").start()
        return created

    def _run_sync(self, job_id: str) -> None:
        job = store.get_row("jobs", job_id)
        if not job:
            return
        account_id = str(job["accountId"])
        concurrency = _job_concurrency(job.get("settings") or {})
        with self._account_condition:
            while self._account_active.get(account_id, 0) >= concurrency:
                self._account_condition.wait()
            self._account_active[account_id] = self._account_active.get(account_id, 0) + 1
        # ponytail: one auto-retry for transient failures (timeout / UI selector);
        # hard errors (LOGIN_REQUIRED, GENERATION_FAILED/REJECTED, CANCELLED) skip retry.
        _HARD_ERROR = re.compile(
            r"LOGIN_REQUIRED|GENERATION_FAILED|GENERATION_REJECTED|FLOW_EMPTY_OUTPUT",
            re.I,
        )
        try:
            if job_id in self._cancelled:
                return
            runtime_profile = self._clone_runtime_profile(account_id, job_id)
            try:
                asyncio.run(self._run(job_id, profile_dir=runtime_profile))
            finally:
                shutil.rmtree(runtime_profile, ignore_errors=True)

            # Check whether _run marked the job as a transient failure → auto-retry once
            finished = store.get_row("jobs", job_id) or {}
            if finished.get("status") == "failed" and not _HARD_ERROR.search(str(finished.get("error") or "")):
                _log.warning(
                    "auto-retry job %s after transient failure: %s",
                    job_id, finished.get("error"),
                )
                time.sleep(3)
                store.patch_row("jobs", job_id, {"status": "queued", "stage": "queued", "progress": 0, "error": None, "outputs": []})
                runtime_profile2 = self._clone_runtime_profile(account_id, job_id)
                try:
                    asyncio.run(self._run(job_id, profile_dir=runtime_profile2))
                finally:
                    shutil.rmtree(runtime_profile2, ignore_errors=True)
        finally:
            with self._account_condition:
                self._account_active[account_id] -= 1
                self._account_condition.notify_all()

    def _clone_runtime_profile(self, account_id: str, job_id: str) -> Path:
        """Copy login state into an isolated, cache-free profile for one job."""
        source = store.profile_dir(account_id)
        target = store.root() / "runtime-profiles" / account_id / job_id
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            target,
            ignore=lambda _directory, names: sorted(_PROFILE_COPY_IGNORES.intersection(names)),
        )
        return target

    async def _prepare_video_mode(self, page, model: str) -> None:
        """Open Flow's live settings popover and verify Video mode.

        flow-py's JavaScript click can race the localized Agent UI and leave
        Image mode selected. Use trusted Playwright clicks against the controls
        observed in the current account instead.
        """
        model_pills = page.locator('button[aria-haspopup="menu"]')
        visible_pill = None
        for index in range(await model_pills.count() - 1, -1, -1):
            candidate = model_pills.nth(index)
            label = (await candidate.inner_text()).strip()
            # x[1-4]\b (no leading \b): matches both "x1" and "crop_16_9x1"
            if await candidate.is_visible() and re.search(r"x[1-4]\b", label):
                visible_pill = candidate
                break
        if visible_pill is None:
            raise RuntimeError("FLOW_UI_CHANGED: generation settings control was not found")
        await visible_pill.click()
        await asyncio.sleep(1.0)
        # Tab "Video" — dùng regex để catch cả localized variants; fallback force-click nếu is_visible() fail (Windows DPI)
        video_tab_loc = page.locator('[role="tab"]').filter(has=page.locator('text=/^Video/i'))
        if await video_tab_loc.count() == 0:
            # Thử regex rộng hơn: bất kỳ tab nào KHÔNG phải Image/Hình/S/M/L/Landscape/Portrait/Square
            all_tabs = page.locator('[role="tab"]')
            await all_tabs.first.wait_for(state="attached", timeout=10_000)
            video_tab_loc = all_tabs.filter(has=page.locator('text=/^Video/i'))
        if await video_tab_loc.count() == 0:
            tab_texts = []
            all_tabs2 = page.locator('[role="tab"]')
            for i in range(min(10, await all_tabs2.count())):
                try:
                    tab_texts.append((await all_tabs2.nth(i).inner_text()).strip())
                except Exception:
                    pass
            raise RuntimeError(f"FLOW_UI_CHANGED: Video mode tab was not found — tabs={tab_texts}")
        # Force click — is_visible() unreliable trên Windows DPI
        await video_tab_loc.first.click(force=True)
        await asyncio.sleep(0.6)

        setting_pills = page.locator('button[aria-haspopup="menu"]')
        video_summary = setting_pills.filter(has_text=re.compile(r"Video", re.I)).last
        if await video_summary.count() == 0 or not await video_summary.is_visible():
            raise RuntimeError("FLOW_MODE_MISMATCH: Flow did not switch from Image to Video")

        model_buttons = setting_pills.filter(has_text=re.compile(r"Omni|Veo", re.I))
        if await model_buttons.count() == 0:
            raise RuntimeError("FLOW_UI_CHANGED: video model selector was not found")
        model_button = model_buttons.last
        current_model = (await model_button.inner_text()).strip()
        if not _match_model_choice(model, current_model):
            await model_button.click()
            await asyncio.sleep(0.25)
            choices = page.locator('[role="menuitem"], [role="option"]')
            selected = False
            for index in range(await choices.count()):
                choice = choices.nth(index)
                text = (await choice.inner_text()).strip()
                if await choice.is_visible() and _match_model_choice(model, text):
                    await choice.click()
                    selected = True
                    break
            if not selected:
                raise RuntimeError(f"FLOW_MODEL_UNAVAILABLE: {model}")

    async def _prepare_ui_model(self, page, kind: str, model: str, *, ui=None) -> None:  # noqa: C901
        """Select a current Flow UI model for models without a stable REST key.

        Strategy:
        1. Ensure settings panel is open via pill click (x[1-4] or any visible pill).
        2. Switch to the correct mode tab (Image/Video).
        3. Click the model family selector and pick the right option.
        """
        try:
            await page.wait_for_selector('button[aria-haspopup="menu"]', timeout=30_000, state="attached")
        except Exception:
            _log.warning("_prepare_ui_model: settings pill not found within 30s — proceeding anyway")

        family = re.compile(r"Nano Banana|Imagen", re.I) if kind == "image" else re.compile(r"Omni|Veo", re.I)
        mode_pattern = (
            re.compile(r"Image|H\u00ecnh \u1ea3nh", re.I) if kind == "image"
            else re.compile(r"Video", re.I)
        )

        async def _visible_mode_tab():
            loc = page.locator('[role="tab"]').filter(has_text=mode_pattern)
            # 1. Prefer truly visible tab
            for index in range(await loc.count()):
                candidate = loc.nth(index)
                if await candidate.is_visible():
                    return candidate
            # 2. Fallback: Windows DPI can make is_visible() unreliable — use first attached tab
            if await loc.count() > 0:
                _log.warning("_visible_mode_tab: %s tab not visible but attached — DPI fallback", kind)
                return loc.first
            return None

        async def _model_pill_already_visible() -> bool:
            loc = page.locator('button[aria-haspopup="menu"]').filter(has_text=family)
            for index in range(await loc.count()):
                if await loc.nth(index).is_visible():
                    return True
            return False

        mode_tab = await _visible_mode_tab()
        if mode_tab is None:
            for attempt in range(3):
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

                # Critical: focus the prompt textarea before clicking the settings
                # pill.  In the current Flow UI the pill only opens the mode/model/
                # aspect panel when the prompt input already has focus; otherwise it
                # opens the reference-image media picker.
                try:
                    ed = page.locator("div[contenteditable]").first
                    if await ed.count() > 0:
                        await ed.click()
                        await asyncio.sleep(0.4)
                except Exception:
                    pass

                pills = page.locator('button[aria-haspopup="menu"]')
                trigger = None
                # 1. Pill với x[1-4] (matches cả "x1" và "crop_16_9x1")
                for index in range(await pills.count() - 1, -1, -1):
                    candidate = pills.nth(index)
                    text = (await candidate.inner_text()).strip()
                    if await candidate.is_visible() and re.search(r"x[1-4]\b", text):
                        trigger = candidate
                        break
                # 2. Pill có text chứa Image/Video/Hình ảnh/Imagen
                if trigger is None:
                    img_kw = re.compile(r"Image|Hình|Imagen|Photo", re.I)
                    for index in range(await pills.count() - 1, -1, -1):
                        candidate = pills.nth(index)
                        if await candidate.is_visible() and img_kw.search((await candidate.inner_text()).strip()):
                            trigger = candidate
                            break
                # 3. Bất kỳ pill visible nào (aria-haspopup="menu")
                if trigger is None:
                    for index in range(await pills.count() - 1, -1, -1):
                        candidate = pills.nth(index)
                        if await candidate.is_visible():
                            trigger = candidate
                            break
                if trigger is None:
                    _log.warning(
                        "_prepare_ui_model attempt %d: no settings pill found — skipping open",
                        attempt + 1,
                    )
                else:
                    opened = await _click_settings_pill(trigger, page.locator('[role="tab"]'))
                    if not opened:
                        _log.warning(
                            "_prepare_ui_model attempt %d: settings pill did not open panel",
                            attempt + 1,
                        )
                await asyncio.sleep(1.2)
                mode_tab = await _visible_mode_tab()
                if mode_tab is not None:
                    break

                all_tabs = page.locator('[role="tab"]')
                tab_texts: list[str] = []
                for idx in range(min(10, await all_tabs.count())):
                    try:
                        tab_texts.append((await all_tabs.nth(idx).inner_text()).strip())
                    except Exception:
                        pass
                _log.warning(
                    "_prepare_ui_model attempt %d: no %s tab visible; tabs=%s",
                    attempt + 1, kind, tab_texts,
                )

        if mode_tab is None:
            if await _model_pill_already_visible():
                _log.info(
                    "_prepare_ui_model: %s tab not found but model pill present — skipping",
                    kind,
                )
            else:
                raise RuntimeError(f"FLOW_UI_CHANGED: {kind} mode tab was not found")
        elif await mode_tab.get_attribute("aria-selected") != "true":
            await mode_tab.click()
            await asyncio.sleep(0.6)



        # ------------------------------------------------------------------
        # Step 3: find and click model family selector, pick the right option
        # ------------------------------------------------------------------
        selectors = page.locator('button[aria-haspopup="menu"]').filter(has_text=family)
        selector = None
        for index in range(await selectors.count() - 1, -1, -1):
            candidate = selectors.nth(index)
            if await candidate.is_visible():
                selector = candidate
                break
        if selector is None:
            raise RuntimeError(f"FLOW_UI_CHANGED: {kind} model selector was not found")
        if not _match_model_choice(model, await selector.inner_text()):
            await selector.click()
            await asyncio.sleep(0.5)
            choices = page.locator('[role="menuitem"], [role="option"]')
            selected = False
            for index in range(await choices.count()):
                choice = choices.nth(index)
                text = (await choice.inner_text()).strip()
                if await choice.is_visible() and _match_model_choice(model, text):
                    await choice.click()
                    selected = True
                    break
            if not selected:
                visible_texts = []
                for index in range(await choices.count()):
                    choice = choices.nth(index)
                    if await choice.is_visible():
                        visible_texts.append((await choice.inner_text()).strip())
                raise RuntimeError(f"FLOW_MODEL_UNAVAILABLE: {model} — available: {visible_texts}")


    async def _prepare_ui_format(self, page, ratio: str, duration: str | None = None) -> None:
        """Select current numeric Flow tabs and verify the requested format.

        Recent Flow builds label aspect tabs ``16:9``/``9:16``/``1:1`` rather
        than the older Landscape/Portrait/Square labels used by flow-py.
        """
        async def visible_tab(label: str):
            matches = page.locator('[role="tab"]').filter(
                has_text=re.compile(re.escape(label))
            )
            for index in range(await matches.count()):
                candidate = matches.nth(index)
                if await candidate.is_visible():
                    return candidate
            return None

        ratio_label = ratio if ratio in {"16:9", "9:16", "1:1", "4:3", "3:4"} else "16:9"
        ratio_tab = None
        for attempt in range(4):
            ratio_tab = await visible_tab(ratio_label)
            if ratio_tab is not None:
                break
            # Model selection can leave a transient menu open or close the
            # settings popover. Focus textarea (so pill opens settings not media picker),
            # then reopen via pill click.
            if attempt:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
            # Focus textarea trước khi click pill
            try:
                ed = page.locator("div[contenteditable]").first
                if await ed.count() > 0:
                    await ed.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass
            trigger = None
            # 1. Pill x[1-4] (matches "x1" và "crop_16_9x1")
            buttons = page.locator("button")
            for index in range(await buttons.count() - 1, -1, -1):
                candidate = buttons.nth(index)
                text = (await candidate.inner_text()).strip()
                if (
                    await candidate.is_visible()
                    and re.search(r"x[1-4]\b", text)
                    and await candidate.get_attribute("role") != "tab"
                ):
                    trigger = candidate
                    break
            # 2. Fallback: bất kỳ pill aria-haspopup visible
            if trigger is None:
                pills = page.locator('button[aria-haspopup="menu"]')
                for index in range(await pills.count() - 1, -1, -1):
                    candidate = pills.nth(index)
                    if await candidate.is_visible():
                        trigger = candidate
                        break
            if trigger is not None:
                await trigger.click()
            await asyncio.sleep(0.75)
        if ratio_tab is None:
            raise RuntimeError(f"FLOW_UI_CHANGED: aspect ratio {ratio_label} was not found")
        if await ratio_tab.get_attribute("aria-selected") != "true":
            await ratio_tab.click()
            await asyncio.sleep(0.3)
        if await ratio_tab.get_attribute("aria-selected") != "true":
            raise RuntimeError(f"FLOW_SETTING_MISMATCH: aspect ratio {ratio_label} was not selected")


        if duration is None:
            return
        duration_label = f"{duration}s" if duration in {"4", "6", "8"} else "8s"
        duration_tab = await visible_tab(duration_label)
        if duration_tab is None:
            raise RuntimeError(f"FLOW_UI_CHANGED: duration {duration_label} was not found")
        if await duration_tab.get_attribute("aria-selected") != "true":
            await duration_tab.click()
            await asyncio.sleep(0.3)
        if await duration_tab.get_attribute("aria-selected") != "true":
            raise RuntimeError(f"FLOW_SETTING_MISMATCH: duration {duration_label} was not selected")

    async def _wait_for_project_videos(
        self,
        api,
        baseline_ids: set[str],
        expected_count: int,
        job_id: str,
        timeout_s: int = 900,
    ) -> list[str]:
        """Resolve new Omni/Veo media IDs from project data.

        Omni Flash can return an empty ``jobs`` array from the legacy video
        endpoint interceptor. Project data remains authoritative and includes
        the generated video's stable media ID and status.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self._check_cancel(job_id)
            data = await api.get_project_data()
            completed: list[tuple[str, str]] = []
            for media in data.get("projectContents", {}).get("media", []):
                media_id = str(media.get("name") or "")
                if not media_id or media_id in baseline_ids or "video" not in media:
                    continue
                metadata = media.get("mediaMetadata") or {}
                status = str((metadata.get("mediaStatus") or {}).get("mediaGenerationStatus") or "")
                if status in {"MEDIA_GENERATION_STATUS_FAILED", "MEDIA_GENERATION_STATUS_REJECTED"}:
                    raise RuntimeError(f"FLOW_GENERATION_FAILED: {media_id} ({status})")
                if status in {
                    "MEDIA_GENERATION_STATUS_COMPLETE",
                    "MEDIA_GENERATION_STATUS_SUCCESS",
                    "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                }:
                    completed.append((str(metadata.get("createTime") or ""), media_id))
            if completed:
                completed.sort()
                claimed = self._claim_media_ids(
                    [media_id for _, media_id in completed],
                    expected_count,
                )
                if claimed:
                    return claimed
            store.patch_row("jobs", job_id, {
                "stage": "generating",
                "progress": min(90, 20 + int((timeout_s - (deadline - time.monotonic())) / 12)),
                "updatedAt": time.time(),
            })
            await asyncio.sleep(5)
        raise RuntimeError("FLOW_GENERATION_TIMEOUT: no completed video appeared in project data")

    async def _sync_credits(self, api, account_id: str) -> None:
        """Refresh the persisted balance without turning a successful job into a failure."""
        try:
            credit_info = await api.get_credits()
            store.patch_row("accounts", account_id, {
                "credits": int(credit_info.credits),
                "creditsSyncedAt": time.time(),
                "updatedAt": time.time(),
            })
        except Exception:
            # Credit reporting is secondary to generation. A later job or
            # reconnect can refresh it if Google's balance endpoint is busy.
            pass

    async def _run(self, job_id: str, *, profile_dir: Path | None = None) -> None:
        job = store.get_row("jobs", job_id)
        account = store.get_row("accounts", str(job.get("accountId"))) if job else None
        if not job or not account:
            return
        browser = None
        try:
            self._log("info", "job_started", job_id=job_id, account_id=account["id"], details={"kind": job["kind"]})
            if account.get("status") != "online" or not account.get("projectId"):
                raise RuntimeError("FLOW_LOGIN_REQUIRED: connect the Google Flow account first")
            from flow._api import FlowAPI
            from .browser import BrowserManager
            from flow._client import FlowClient
            # Generation uses the already-authenticated persistent profile in
            # background mode. Only the explicit account-connect flow opens a
            # visible Chrome window for interactive Google sign-in.
            browser = BrowserManager(headless=True, profile_dir=profile_dir or store.profile_dir(account["id"]))
            await browser.start()
            self._log("info", "browser_ready", job_id=job_id, account_id=account["id"])
            api = FlowAPI(browser, project_id=account["projectId"], default_timeout_s=600)
            client = FlowClient(api, browser, account["projectId"])
            settings = job.get("settings") or {}
            store.patch_row("jobs", job_id, {"status": "processing", "stage": "submitting", "progress": 5, "updatedAt": time.time()})
            if job["kind"] == "video":
                source = next(iter(job.get("sourceFiles") or []), None)
                model = str(settings.get("model") or "Veo 3.1 - Fast").replace("3.1 Fast", "3.1 - Fast").replace("3.1 Quality", "3.1 - Quality")
                ratio = str(settings.get("ratio") or "16:9")
                page = await browser.page()
                await client._ensure_project_page(page)
                await self._prepare_ui_model(page, "video", model, ui=client._ui)
                await self._prepare_ui_format(page, ratio, str(settings.get("duration") or "8"))
                project_data = await api.get_project_data()
                baseline_ids = {
                    str(media.get("name"))
                    for media in project_data.get("projectContents", {}).get("media", [])
                    if media.get("name")
                }
                async def ready(*_args, **_kwargs):
                    return True
                # If we have a start image, switch to FRAME_TO_VIDEO NOW while the
                # settings panel is still open from _prepare_ui_model above.
                # switch_mode.open_settings_panel will see the panel as already open
                # and skip the unreliable JS click; it then Playwright-clicks the
                # "Frames" tab which does trigger React events correctly.
                # This must happen BEFORE the no-ops below so generate_video does not
                # re-attempt the switch and inadvertently close the panel.
                if source:
                    from flow._models import GenerationMode
                    await client._ui.switch_mode(page, GenerationMode.FRAME_TO_VIDEO)
                client._ui.open_settings_panel = ready
                client._ui.switch_mode = ready   # already done (or not needed for text mode)
                client._ui.set_aspect_ratio = ready
                extend_from = store.get_row("jobs", str(settings.get("extendFromJobId") or ""))
                if extend_from and (extend_from.get("mediaIds") or []):
                    media_id = str(extend_from["mediaIds"][0])
                    project_data = await api.get_project_data()
                    media = next((item for item in project_data.get("projectContents", {}).get("media", []) if str(item.get("name") or "") == media_id), {})
                    workflow_id = str(media.get("workflowId") or "")
                    if not workflow_id:
                        raise RuntimeError("FLOW_EXTEND_WORKFLOW_MISSING: prior video has no workflow")
                    # Use the authenticated Flow editor, which mints the
                    # extension token that the raw endpoint rejects on 403.
                    remote = [await client.extend_video(media_id, workflow_id, job["prompt"])]
                else:
                    remote = await client.generate_video(
                        job["prompt"], model=model,
                        aspect="portrait" if ratio == "9:16" else "landscape",
                        count=max(1, min(4, int(settings.get("count", 1)))), start_image=source,
                        timeout_s=300,
                    )
                media_ids = [item.media_name for item in remote]
                if not media_ids:
                    media_ids = await self._wait_for_project_videos(
                        api,
                        baseline_ids,
                        max(1, min(4, int(settings.get("count", 1)))),
                        job_id,
                    )
                self._log("success", "generation_submitted", job_id=job_id, account_id=account["id"], details={"model": model, "mediaIds": media_ids})
                await self._sync_credits(api, account["id"])
                store.patch_row("jobs", job_id, {"mediaIds": media_ids, "stage": "generating", "progress": 20})
                outputs = []
                remote_by_id = {item.media_name: item for item in remote}
                for output_index, media_id in enumerate(media_ids, 1):
                    self._check_cancel(job_id)
                    remote_job = remote_by_id.get(media_id)
                    status = None
                    if remote_job is not None:
                        status = await api.wait_for_video(remote_job, timeout_s=900, on_poll=lambda _s, elapsed: store.patch_row("jobs", job_id, {"progress": min(90, 20 + int(elapsed / 12)), "updatedAt": time.time()}))
                    suffix = "mp4"
                    output = self._output_path(job, output_index, suffix)
                    media_url = (
                        status.fife_url
                        if status is not None and status.fife_url
                        else f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}"
                    )
                    await api.download(media_url, output)
                    outputs.append(str(output))
                    self._log("success", "output_downloaded", job_id=job_id, account_id=account["id"], details={"outputIndex": output_index, "path": str(output)})
            else:
                model = str(settings.get("model") or "Nano Banana 2")
                sources = job.get("sourceFiles") or []
                page = await browser.page()
                await client._ensure_project_page(page)
                await self._prepare_ui_model(page, "image", model, ui=client._ui)
                await self._prepare_ui_format(page, str(settings.get("ratio") or "16:9"))
                for source in sources:
                    await client._ui.upload_image(page, source)
                async def ready(*_args, **_kwargs):
                    return True
                client._ui.open_settings_panel = ready
                client._ui.switch_mode = ready
                client._ui.set_aspect_ratio = ready
                images = await client.generate_image(
                    job["prompt"], aspect={"9:16": "portrait", "1:1": "square"}.get(settings.get("ratio"), "landscape"),
                    count=max(1, min(4, int(settings.get("count", 1)))), reference_images=sources or None,
                    timeout_s=300,
                )
                media_ids = [image.media_name for image in images]
                self._log("success", "generation_submitted", job_id=job_id, account_id=account["id"], details={"model": settings.get("model"), "mediaIds": media_ids})
                await self._sync_credits(api, account["id"])
                store.patch_row("jobs", job_id, {"mediaIds": media_ids, "stage": "downloading", "progress": 80})
                outputs = []
                for output_index, image in enumerate(images, 1):
                    self._check_cancel(job_id)
                    output = self._output_path(job, output_index, str(settings.get("format", "png")).lower())
                    await api.download(image.fife_url, output)
                    outputs.append(str(output))
                    self._log("success", "output_downloaded", job_id=job_id, account_id=account["id"], details={"outputIndex": output_index, "path": str(output)})
            if not self._outputs_exist(outputs):
                raise RuntimeError("FLOW_EMPTY_OUTPUT: generation finished without a downloaded media file")
            store.patch_row("jobs", job_id, {"status": "done", "stage": "done", "progress": 100, "outputs": outputs, "updatedAt": time.time()})
            if job.get("seriesContext"):
                from . import series
                series.mark_job_complete(job, outputs)
            self._log("success", "job_completed", job_id=job_id, account_id=account["id"], details={"outputCount": len(outputs)})
        except asyncio.CancelledError:
            store.patch_row("jobs", job_id, {"status": "cancelled", "stage": "cancelled", "progress": 0, "updatedAt": time.time()})
            self._log("warning", "job_cancelled", job_id=job_id, account_id=account["id"])
        except Exception as exc:
            action = "action_required" if "LOGIN_REQUIRED" in str(exc) or "recaptcha" in str(exc).lower() else "failed"
            failed_stage = (store.get_row("jobs", job_id) or {}).get("stage")
            store.patch_row("jobs", job_id, {"status": action, "stage": action, "error": str(exc), "updatedAt": time.time()})
            if job.get("seriesContext"):
                from . import series
                series.mark_job_error(job, str(exc))
            self._log("error", "job_failed", job_id=job_id, account_id=account["id"], message=str(exc), details={"stage": failed_stage})
        finally:
            if browser:
                await browser.stop()

    def _output_folder(self, job: dict[str, Any], *, create: bool = True) -> Path:
        """Return ``flow/<kind>/<user-name>`` without hidden job folders."""
        settings = job.get("settings") or {}
        selected = Path(str(settings.get("outputDir") or "results")).expanduser()
        kind = safe_output_part(job.get("kind") or "video", "video")
        flow_tab = f"flow-{kind}"  # → ~/Downloads/ZM_AIO_TOOL/flow/video/ or .../flow/image/
        series_context = job.get("seriesContext") or {}
        if series_context:
            root = selected_or_default(flow_tab, "")
            series_root = root / "series" / safe_output_part(series_context.get("seriesSlug") or series_context.get("seriesTitle") or "series", "series")
            folder = series_root / "anchors" if series_context.get("artifact") == "anchor" else series_root / f"tap-{int(series_context.get('episodeIndex') or 1):02d}"
        elif selected.is_absolute():
            flow_root = selected_or_default(flow_tab, "")
            try:
                relative = selected.relative_to(flow_root)
            except ValueError:
                # Path nằm ngoài flow_root → đặt vào flow_root/tên-folder
                # VD: user chọn ~/Downloads/test → ~/Downloads/ZM_AIO_TOOL/flow/video/test
                folder = flow_root / safe_output_part(selected.name or "results", "results")
            else:
                parts = list(relative.parts)
                if parts and parts[0] in {"image", "video"}:
                    parts = parts[1:]
                folder = flow_root / safe_output_part(parts[-1] if parts else "results", "results")

        else:
            root = selected_or_default(flow_tab, "")
            folder = root / safe_output_part(selected, "results")
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        return folder


    def _display_output_folder(self, job: dict[str, Any]) -> Path:
        """Return the real worker destination shown in the queue UI."""
        return self._output_folder(job, create=False)

    def _output_path(self, job: dict[str, Any], output_index: int, suffix: str) -> Path:
        folder = self._output_folder(job)
        settings = job.get("settings") or {}
        prefix = safe_output_part(settings.get("filePrefix") or job["kind"], str(job["kind"]))
        safe_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix).lower() or ("mp4" if job["kind"] == "video" else "png")
        series_context = job.get("seriesContext") or {}
        if series_context and series_context.get("sceneIndex"):
            scene_idx = int(series_context.get("sceneIndex") or 1)
            variant = f"_{output_index:02d}" if max(1, int(settings.get("count", 1))) > 1 else ""
            return folder / f"canh-{scene_idx:03d}__{job['id'][:8]}__{prefix}{variant}.{safe_suffix}"
        input_index = int(job["inputIndex"])
        variant = f"_{output_index:02d}" if max(1, int(settings.get("count", 1))) > 1 else ""
        return folder / f"{input_index:03d}__{job['id']}__{prefix}_{input_index:03d}{variant}.{safe_suffix}"

    def _check_cancel(self, job_id: str) -> None:
        if job_id in self._cancelled:
            raise asyncio.CancelledError

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        self._cancelled.add(job_id)
        job = store.patch_row("jobs", job_id, {"status": "cancelled", "stage": "cancelled", "progress": 0, "updatedAt": time.time()})
        if job:
            self._log("warning", "job_cancel_requested", job_id=job_id, account_id=str(job.get("accountId") or ""))
        return job

    def retry(self, job_id: str) -> dict[str, Any] | None:
        self._cancelled.discard(job_id)
        job = store.patch_row("jobs", job_id, {"status": "queued", "stage": "queued", "progress": 0, "error": None, "outputs": [], "updatedAt": time.time()})
        if job:
            self._log("info", "job_retry", job_id=job_id, account_id=str(job.get("accountId") or ""))
            threading.Thread(target=self._run_sync, args=(job_id,), daemon=True, name=f"flow-job-{job_id}").start()
        return job


service = FlowService()
