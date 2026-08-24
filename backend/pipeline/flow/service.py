"""Persistent-account Google Flow worker built around flow-py."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pipeline.core.config import PUBLIC_DATA
from pipeline.core.output_paths import item_output_folder, nested_output_folder, safe_output_part
from . import store

_PROJECT_RE = re.compile(r"/flow/project/([^/?#]+)")
_TERMINAL = {"done", "failed", "cancelled", "action_required"}


class FlowService:
    def __init__(self) -> None:
        self._account_locks: dict[str, threading.Lock] = {}
        self._cancelled: set[str] = set()
        self._guard = threading.RLock()

    def accounts(self) -> list[dict[str, Any]]:
        return store.list_rows("accounts")

    def jobs(self) -> list[dict[str, Any]]:
        return sorted(store.list_rows("jobs"), key=lambda row: row.get("createdAt", 0), reverse=True)

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
            raise RuntimeError("Cancel the Flow job before deleting it")
        removed = store.delete_row("jobs", job_id)
        if removed:
            shutil.rmtree(self._output_folder(job, create=False), ignore_errors=True)
        return removed

    def connect(self, account_id: str) -> dict[str, Any]:
        account = store.get_row("accounts", account_id)
        if not account:
            raise KeyError(account_id)
        store.patch_row("accounts", account_id, {"status": "connecting", "error": None, "updatedAt": time.time()})
        self._log("info", "account_connecting", account_id=account_id)
        threading.Thread(target=lambda: asyncio.run(self._login(account_id)), daemon=True, name=f"flow-login-{account_id}").start()
        return store.get_row("accounts", account_id) or account

    async def _login(self, account_id: str) -> None:
        try:
            from flow._browser import BrowserManager, FLOW_BASE_URL
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
            try:
                from flow._api import FlowAPI
                credit_info = await FlowAPI(browser, project_id=project_id).get_credits()
                credits = int(credit_info.credits)
                credits_synced_at = time.time()
            except Exception:
                pass
            await browser.stop()
            store.patch_row("accounts", account_id, {"status": "online", "projectId": project_id, "email": email or (store.get_row("accounts", account_id) or {}).get("email", ""), "credits": credits, "creditsSyncedAt": credits_synced_at, "updatedAt": time.time(), "error": None})
            self._log("success", "account_connected", account_id=account_id, details={"projectId": project_id, "credits": credits})
        except Exception as exc:
            store.patch_row("accounts", account_id, {"status": "reconnect", "error": str(exc), "updatedAt": time.time()})
            self._log("error", "account_connect_failed", account_id=account_id, message=str(exc))

    def enqueue(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        prompts = [str(value).strip() for value in payload.get("prompts", []) if str(value).strip()]
        account_id = str(payload.get("accountId") or "")
        if not prompts or not store.get_row("accounts", account_id):
            raise ValueError("Prompts and a valid Flow account are required")
        created = []
        for index, prompt in enumerate(prompts, 1):
            now = time.time()
            job = {
                "id": uuid.uuid4().hex[:12], "inputIndex": index, "kind": payload.get("kind", "video"),
                "mode": payload.get("mode", "text"), "prompt": prompt, "accountId": account_id,
                "settings": dict(payload.get("settings") or {}), "sourceFiles": list(payload.get("sourceFiles") or []),
                "status": "queued", "stage": "queued", "progress": 0, "mediaIds": [], "outputs": [],
                "error": None, "createdAt": now, "updatedAt": now,
            }
            store.put_row("jobs", job)
            self._log("info", "job_queued", job_id=job["id"], account_id=account_id, details={"kind": job["kind"], "inputIndex": index})
            created.append(job)
            threading.Thread(target=self._run_sync, args=(job["id"],), daemon=True, name=f"flow-job-{job['id']}").start()
        return created

    def _run_sync(self, job_id: str) -> None:
        job = store.get_row("jobs", job_id)
        if not job:
            return
        account_id = str(job["accountId"])
        with self._guard:
            lock = self._account_locks.setdefault(account_id, threading.Lock())
        with lock:
            if job_id in self._cancelled:
                return
            asyncio.run(self._run(job_id))

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
            if await candidate.is_visible() and re.search(r"\bx[1-4]\b", label):
                visible_pill = candidate
                break
        if visible_pill is None:
            raise RuntimeError("FLOW_UI_CHANGED: generation settings control was not found")
        await visible_pill.click()
        tabs = page.locator('[role="tab"]')
        await tabs.first.wait_for(state="visible", timeout=5_000)
        video_tab = tabs.filter(has_text="Video").first
        if await video_tab.count() == 0:
            raise RuntimeError("FLOW_UI_CHANGED: Video mode tab was not found")
        await video_tab.click()
        await asyncio.sleep(0.5)

        setting_pills = page.locator('button[aria-haspopup="menu"]')
        video_summary = setting_pills.filter(has_text=re.compile(r"Video", re.I)).last
        if await video_summary.count() == 0 or not await video_summary.is_visible():
            raise RuntimeError("FLOW_MODE_MISMATCH: Flow did not switch from Image to Video")

        model_buttons = setting_pills.filter(has_text=re.compile(r"Omni|Veo", re.I))
        if await model_buttons.count() == 0:
            raise RuntimeError("FLOW_UI_CHANGED: video model selector was not found")
        model_button = model_buttons.last
        current_model = (await model_button.inner_text()).strip()
        if model.lower() not in current_model.lower():
            await model_button.click()
            await asyncio.sleep(0.25)
            choices = page.locator('[role="menuitem"], [role="option"]')
            selected = False
            for index in range(await choices.count()):
                choice = choices.nth(index)
                text = (await choice.inner_text()).strip()
                if await choice.is_visible() and model.lower() in text.lower():
                    await choice.click()
                    selected = True
                    break
            if not selected:
                raise RuntimeError(f"FLOW_MODEL_UNAVAILABLE: {model}")

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
            if len(completed) >= expected_count:
                completed.sort()
                return [media_id for _, media_id in completed[:expected_count]]
            store.patch_row("jobs", job_id, {
                "stage": "generating",
                "progress": min(90, 20 + int((timeout_s - (deadline - time.monotonic())) / 12)),
                "updatedAt": time.time(),
            })
            await asyncio.sleep(5)
        raise RuntimeError("FLOW_GENERATION_TIMEOUT: no completed video appeared in project data")

    async def _run(self, job_id: str) -> None:
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
            from flow._browser import BrowserManager
            from flow._client import FlowClient
            # Generation uses the already-authenticated persistent profile in
            # background mode. Only the explicit account-connect flow opens a
            # visible Chrome window for interactive Google sign-in.
            browser = BrowserManager(headless=True, profile_dir=store.profile_dir(account["id"]))
            await browser.start()
            self._log("info", "browser_ready", job_id=job_id, account_id=account["id"])
            api = FlowAPI(browser, project_id=account["projectId"], default_timeout_s=600)
            client = FlowClient(api, browser, account["projectId"])
            settings = job.get("settings") or {}
            store.patch_row("jobs", job_id, {"status": "processing", "stage": "submitting", "progress": 5, "updatedAt": time.time()})
            if job["kind"] == "video":
                source = next(iter(job.get("sourceFiles") or []), None)
                model = str(settings.get("model") or "Veo 3.1 - Fast").replace("3.1 Fast", "3.1 - Fast").replace("3.1 Quality", "3.1 - Quality")
                page = await browser.page()
                await client._ensure_project_page(page)
                await self._prepare_video_mode(page, model)
                project_before = await api.get_project_data()
                baseline_ids = {
                    str(media.get("name") or "")
                    for media in project_before.get("projectContents", {}).get("media", [])
                }
                remote = await client.generate_video(job["prompt"], model=model, aspect="portrait" if settings.get("ratio") == "9:16" else "landscape", count=int(settings.get("count", 1)), start_image=source)
                media_ids = [item.media_name for item in remote]
                if not media_ids:
                    media_ids = await self._wait_for_project_videos(
                        api, baseline_ids, int(settings.get("count", 1)), job_id
                    )
                self._log("success", "generation_submitted", job_id=job_id, account_id=account["id"], details={"model": model, "mediaIds": media_ids})
                store.patch_row("jobs", job_id, {"mediaIds": media_ids, "stage": "generating", "progress": 20})
                outputs = []
                remote_by_id = {item.media_name: item for item in remote}
                for output_index, media_id in enumerate(media_ids, 1):
                    self._check_cancel(job_id)
                    remote_job = remote_by_id.get(media_id)
                    status = None
                    if remote_job is not None:
                        status = await client.wait_for_video(remote_job, timeout_s=900, on_poll=lambda _s, elapsed: store.patch_row("jobs", job_id, {"progress": min(90, 20 + int(elapsed / 12)), "updatedAt": time.time()}))
                    suffix = "mp4"
                    output = self._output_path(job, output_index, suffix)
                    media_url = (
                        status.fife_url
                        if status is not None and status.fife_url
                        else f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}"
                    )
                    await client.download(media_url, output)
                    outputs.append(str(output))
                    self._log("success", "output_downloaded", job_id=job_id, account_id=account["id"], details={"outputIndex": output_index, "path": str(output)})
            else:
                # Flow keeps uploaded references in the composer. Upload them
                # through the real file input before the intercepted submit.
                for source in job.get("sourceFiles") or []:
                    await client._ui.upload_image(await browser.page(), source)
                images = await client.generate_image(job["prompt"], aspect={"9:16": "portrait", "1:1": "square"}.get(settings.get("ratio"), "landscape"), count=int(settings.get("count", 1)), reference_images=job.get("sourceFiles") or None)
                media_ids = [image.media_name for image in images]
                self._log("success", "generation_submitted", job_id=job_id, account_id=account["id"], details={"model": settings.get("model"), "mediaIds": media_ids})
                store.patch_row("jobs", job_id, {"mediaIds": media_ids, "stage": "downloading", "progress": 80})
                outputs = []
                for output_index, image in enumerate(images, 1):
                    self._check_cancel(job_id)
                    output = self._output_path(job, output_index, str(settings.get("format", "png")).lower())
                    await client.download(image.fife_url, output)
                    outputs.append(str(output))
                    self._log("success", "output_downloaded", job_id=job_id, account_id=account["id"], details={"outputIndex": output_index, "path": str(output)})
            store.patch_row("jobs", job_id, {"status": "done", "stage": "done", "progress": 100, "outputs": outputs, "updatedAt": time.time()})
            self._log("success", "job_completed", job_id=job_id, account_id=account["id"], details={"outputCount": len(outputs)})
        except asyncio.CancelledError:
            store.patch_row("jobs", job_id, {"status": "cancelled", "stage": "cancelled", "progress": 0, "updatedAt": time.time()})
            self._log("warning", "job_cancelled", job_id=job_id, account_id=account["id"])
        except Exception as exc:
            action = "action_required" if "LOGIN_REQUIRED" in str(exc) or "recaptcha" in str(exc).lower() else "failed"
            failed_stage = (store.get_row("jobs", job_id) or {}).get("stage")
            store.patch_row("jobs", job_id, {"status": action, "stage": action, "error": str(exc), "updatedAt": time.time()})
            self._log("error", "job_failed", job_id=job_id, account_id=account["id"], message=str(exc), details={"stage": failed_stage})
        finally:
            if browser:
                await browser.stop()

    def _output_folder(self, job: dict[str, Any], *, create: bool = True) -> Path:
        """One shared output root, then one child folder per Flow job."""
        settings = job.get("settings") or {}
        selected = Path(str(settings.get("outputDir") or "")).expanduser()
        desktop = os.environ.get("VIDEO_CLONE_DESKTOP") == "1"
        if desktop and selected.is_absolute():
            root = selected
            if bool(settings.get("createTimeFolder", True)):
                created_at = float(job.get("createdAt") or time.time())
                root /= time.strftime("%Y%m%d_%H%M%S", time.localtime(created_at))
            return item_output_folder(root, job["id"], create=create)
        return nested_output_folder(
            PUBLIC_DATA / "flow",
            settings.get("outputDir") or "results",
            job["id"],
            create=create,
        )

    def _output_path(self, job: dict[str, Any], output_index: int, suffix: str) -> Path:
        folder = self._output_folder(job)
        settings = job.get("settings") or {}
        prefix = safe_output_part(settings.get("filePrefix") or job["kind"], str(job["kind"]))
        safe_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix).lower() or ("mp4" if job["kind"] == "video" else "png")
        return folder / f"{int(job['inputIndex']):03d}__{job['id']}__{prefix}_{output_index:02d}.{safe_suffix}"

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
