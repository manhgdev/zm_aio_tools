from __future__ import annotations

import os
import sys
import threading
import subprocess
import hashlib
import tempfile
import re
import asyncio
import json
import signal
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

CHAT_MODE_PATTERNS = {
    "search": r"(?:search(?: the web)?|tìm kiếm(?: web)?)",
    "research": r"(?:deep research|nghiên cứu sâu)",
    "image": r"(?:create image|tạo ảnh)",
}
SUPPORTED_CHAT_MODES = frozenset({"chat", *CHAT_MODE_PATTERNS})


def browser_candidates() -> dict[str, Path]:
    if sys.platform == "darwin":
        return {
            "chrome": Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "edge": Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            "brave": Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        }
    if sys.platform == "win32":
        program = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        program_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        return {
            "chrome": next((p for p in (program / "Google/Chrome/Application/chrome.exe", program_x86 / "Google/Chrome/Application/chrome.exe", local / "Google/Chrome/Application/chrome.exe") if p.is_file()), local / "Google/Chrome/Application/chrome.exe"),
            "edge": next((p for p in (program / "Microsoft/Edge/Application/msedge.exe", program_x86 / "Microsoft/Edge/Application/msedge.exe") if p.is_file()), program / "Microsoft/Edge/Application/msedge.exe"),
            "brave": next((p for p in (program / "BraveSoftware/Brave-Browser/Application/brave.exe", local / "BraveSoftware/Brave-Browser/Application/brave.exe") if p.is_file()), program / "BraveSoftware/Brave-Browser/Application/brave.exe"),
        }
    return {"chrome": Path("/usr/bin/google-chrome"), "edge": Path("/usr/bin/microsoft-edge"), "brave": Path("/usr/bin/brave-browser")}


def discover_browser(preferred: str | None = None):
    candidates = browser_candidates()
    order = ([preferred] if preferred in candidates else []) + [x for x in ("chrome", "edge", "brave") if x != preferred]
    return next(((name, candidates[name]) for name in order if candidates[name].is_file()), (None, None))


def profile_debug_port(account_id: str) -> int:
    """Return a stable localhost-only CDP port for the isolated account profile."""
    return 47000 + (int(hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:8], 16) % 1000)


def open_profile_url(profile_path: Path, browser_family: str, url: str, debug_port: int | None = None):
    from urllib.parse import urlparse
    if urlparse(url).hostname not in ChatBrowserManager.ALLOWED_HOSTS:
        raise ValueError("Browser URL is not allowed")
    family, executable = discover_browser(browser_family)
    if not executable: raise RuntimeError("No supported browser installed")
    if debug_port and _has_page_target(_debug_targets(debug_port)):
        # Reuse the already-running isolated browser; launching the same
        # profile again would only produce a misleading profile-lock error.
        return family
    Path(profile_path).mkdir(parents=True, exist_ok=True)
    args = [str(executable), f"--user-data-dir={profile_path}", "--no-first-run", "--no-default-browser-check"]
    if debug_port:
        args.extend([f"--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={debug_port}"])
    args.append(url)
    launch_options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        # Keep the user-facing browser alive when the ZMTool process exits.
        launch_options["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    else:
        launch_options["start_new_session"] = True
    subprocess.Popen(args, **launch_options)
    return family


def _debug_targets(debug_port: int, timeout: float = 0.5) -> list[dict] | None:
    """Read the isolated browser's CDP targets without attaching Playwright.

    Chromium can stay alive after its last window is closed on macOS. In that
    state Playwright's CDP attach may fail before exposing a browser context,
    while starting another persistent context reports a misleading profile
    lock. A small CDP preflight lets callers distinguish that state safely.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(debug_port)}/json/list", timeout=timeout) as response:
            payload = json.load(response)
        return payload if isinstance(payload, list) else []
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _has_page_target(targets: list[dict] | None) -> bool:
    return any(isinstance(item, dict) and item.get("type") == "page" for item in (targets or []))


def _stop_debug_browser(debug_port: int) -> None:
    """Stop only the browser process listening on this account's CDP port."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, check=False,
            )
            pids = {line.split()[-1] for line in result.stdout.splitlines() if f":{debug_port}" in line and line.split()[-1].isdigit()}
            for pid in pids:
                subprocess.run(["taskkill", "/PID", pid, "/T"], capture_output=True, check=False)
            return
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{int(debug_port)}", "-sTCP:LISTEN"],
            capture_output=True, text=True, check=False,
        )
        for value in result.stdout.split():
            if value.isdigit():
                os.kill(int(value), signal.SIGTERM)
    except (OSError, ValueError):
        return


class ChatBrowserManager:
    """One persistent, isolated browser profile and one operation at a time per account."""
    ALLOWED_HOSTS = {"chatgpt.com", "auth.openai.com", "openai.com"}
    ALLOWED_SUFFIXES = (".openai.com", ".chatgpt.com", ".oaiusercontent.com")
    DEFAULT_MODEL = "GPT-5.6 Sol"
    GENERATED_FILE_TYPES = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".pdf": "application/pdf",
    }
    MODE_PATTERNS = CHAT_MODE_PATTERNS

    def __init__(self, account_id: str, profile_path: Path, browser_family: str, debug_port: int | None = None):
        self.account_id, self.profile_path, self.browser_family = account_id, Path(profile_path), browser_family
        self.debug_port = profile_debug_port(account_id) if debug_port is None else debug_port
        self.lock = threading.Lock()
        self._pw = self._browser = self._context = None
        self._connected = False

    async def start(self, headless=False, *, allow_launch=False):
        """Attach to the isolated browser, optionally launching it on purpose.

        Discovery and health checks must be read-only.  In particular, a
        missing CDP endpoint is a closed-window state, not permission to start
        a temporary persistent context that the caller will immediately close.
        Only an explicit user action (login) or an actual generation may opt
        into launching a browser.
        """
        from playwright.async_api import async_playwright
        family, executable = discover_browser(self.browser_family)
        if not executable and allow_launch:
            raise RuntimeError("No supported browser installed")
        if family:
            self.browser_family = family
        self.profile_path.mkdir(parents=True, exist_ok=True)
        try:
            self._pw = await async_playwright().start()
            # Login opens a visible Chromium process with localhost CDP
            # enabled. Attach to it instead of trying to launch the same
            # locked profile.
            if self.debug_port:
                targets = _debug_targets(self.debug_port)
                if targets is None:
                    if not allow_launch:
                        raise RuntimeError("CHAT_BROWSER_WINDOW_CLOSED")
                elif not _has_page_target(targets):
                    # Chromium can leave a stale CDP listener after its last
                    # tab closes. Playwright cannot attach that process, so
                    # restart only the process owned by this account's port.
                    _stop_debug_browser(self.debug_port)
                    open_profile_url(self.profile_path, self.browser_family, "https://chatgpt.com/", debug_port=self.debug_port)
                    for _ in range(40):
                        await asyncio.sleep(0.15)
                        targets = _debug_targets(self.debug_port)
                        if targets is not None and _has_page_target(targets):
                            break
                if targets is not None:
                    try:
                        self._browser = await self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.debug_port}")
                        if self._browser.contexts:
                            self._context = self._browser.contexts[0]
                            self._connected = True
                            return self
                        self._browser = None
                    except Exception:
                        self._browser = None
                        if not allow_launch:
                            raise RuntimeError("CHAT_BROWSER_ATTACH_FAILED")
            if not allow_launch:
                raise RuntimeError("CHAT_BROWSER_WINDOW_CLOSED")
            if not executable:
                raise RuntimeError("No supported browser installed")
            self._context = await self._pw.chromium.launch_persistent_context(
                str(self.profile_path),
                executable_path=str(executable),
                headless=headless,
                viewport={"width": 1440, "height": 900},
            )
            return self
        except Exception:
            # Do not leave a Playwright transport behind when an attach-only
            # probe reports a closed window.
            try:
                await self.stop()
            except Exception:
                self._browser = self._context = self._pw = None
                self._connected = False
            raise

    async def page(self):
        pages = self._context.pages
        for page in pages:
            if urlparse(page.url).hostname in self.ALLOWED_HOSTS:
                return page
        for page in pages:
            if page.url and page.url != "about:blank":
                return page
        return pages[0] if pages else await self._context.new_page()

    async def minimize(self, page) -> None:
        if not self._connected or not self._context:
            return
        try:
            session = await self._context.new_cdp_session(page)
            window = await session.send("Browser.getWindowForTarget")
            await session.send("Browser.setWindowBounds", {
                "windowId": window["windowId"],
                "bounds": {"windowState": "minimized"},
            })
        except Exception:
            pass

    @staticmethod
    def _model_names(texts):
        import re
        found = []
        for text in texts:
            # Model picker entries are short labels (for example
            # ``GPT-5.6 Sol``).  Do not mistake workspace labels such as
            # ``GPT Business`` for a model, and retain the visible suffix so
            # the run path can select the same entry in the Web UI.
            for value in re.findall(r"\b(?:GPT[- ]?\d+[A-Za-z0-9.]*(?:[- ][A-Za-z][A-Za-z0-9.-]*)*|o[1-9](?:[- ][A-Za-z0-9.]+)*)\b", text, re.I):
                value = " ".join(value.split())
                if value.lower() not in {item.lower() for item in found} and len(value) < 80:
                    found.append(value)
        return found[:30]

    @classmethod
    def requires_model_picker(cls, model: str) -> bool:
        """The Web default is GPT-5.6 Sol with Instant reasoning."""
        return bool(model and model.casefold() != cls.DEFAULT_MODEL.casefold())

    @staticmethod
    def send_button_pattern():
        """Semantic labels used by the Web composer send action."""
        return re.compile(r"^(?:send(?:\s+(?:prompt|message|request))?|gửi(?:\s+(?:câu lệnh|tin nhắn|yêu cầu))?)$", re.I)

    @staticmethod
    def assistant_turn_changed(count: int, before_count: int, message_id: str, baseline_ids: set[str], text: str, baseline_text: str) -> bool:
        """Detect a new assistant turn even when the Web reuses its text."""
        return count > before_count or bool(message_id and message_id not in baseline_ids) or bool(text and text != baseline_text)

    @staticmethod
    async def _composer_value(composer) -> str:
        """Read text from either the current contenteditable or textarea."""
        try:
            if await composer.get_attribute("contenteditable") == "true":
                return (await composer.inner_text()).strip()
            return (await composer.input_value()).strip()
        except Exception:
            return ""

    async def _click_send_button(self, page) -> bool:
        """Click the localized Web send button without relying on coordinates."""
        buttons = page.get_by_role("button", name=self.send_button_pattern())
        for index in range(await buttons.count() - 1, -1, -1):
            button = buttons.nth(index)
            try:
                if not await button.is_visible() or await button.is_disabled():
                    continue
                await button.evaluate("element => element.click()")
                return True
            except Exception:
                try:
                    await button.click(timeout=2_000, force=True)
                    return True
                except Exception:
                    continue
        return False

    async def _submit_prompt(self, page, composer, files: list[str] | None = None) -> None:
        """Submit text reliably when attachments make Enter a newline."""
        if files:
            # File uploads are asynchronous. Wait briefly for the send action
            # to become enabled, then click it; pressing Enter with an upload
            # pending only inserts a newline in current ChatGPT Web layouts.
            for _ in range(40):
                await self._click_send_button(page)
                await page.wait_for_timeout(300)
                if not await self._composer_value(composer):
                    break
            else:
                await composer.press("Enter")
        else:
            if not await self._click_send_button(page):
                await composer.press("Enter")

        await page.wait_for_timeout(350)
        # Older layouts may not expose a semantic send label. If Enter left
        # the prompt in the composer and no generation is active, use the
        # button fallback rather than waiting five minutes for a response.
        if await self._composer_value(composer):
            stop = page.get_by_role("button", name=re.compile(r"Stop|Dừng", re.I))
            if not (await stop.count() and await stop.is_visible()):
                await self._click_send_button(page)

    @classmethod
    def mode_pattern(cls, mode: str):
        if mode == "chat":
            return None
        pattern = cls.MODE_PATTERNS.get(mode)
        if not pattern:
            raise ValueError("Unsupported chat mode")
        return re.compile(pattern, re.I)

    @staticmethod
    def mode_error(mode: str) -> str:
        return f"CHAT_BROWSER_MODE_{mode.upper()}_UNAVAILABLE"

    async def _click_mode_option(self, page, pattern, *, include_buttons=False) -> bool:
        roles = ("menuitem", "menuitemradio", "option") + (("button",) if include_buttons else ())
        for role in roles:
            options = page.get_by_role(role, name=pattern)
            for index in range(await options.count()):
                option = options.nth(index)
                if not await option.is_visible():
                    continue
                await option.click(timeout=3_000)
                return True
        return False

    async def _activate_mode(self, page, mode: str) -> None:
        """Select a real ChatGPT composer tool or fail instead of sending a normal chat."""
        pattern = self.mode_pattern(mode)
        if not pattern:
            return
        if await self._click_mode_option(page, pattern):
            return

        tool_buttons = page.locator("button[aria-haspopup='menu'], button[aria-haspopup='dialog']")
        for index in range(await tool_buttons.count()):
            button = tool_buttons.nth(index)
            if not await button.is_visible():
                continue
            label = " ".join(filter(None, [await button.get_attribute("aria-label"), await button.inner_text()]))
            if re.search(r"(?:instant|tức thì|thinking|suy nghĩ|reasoning|mức độ suy nghĩ|model)", label, re.I):
                continue
            try:
                await button.click(timeout=3_000)
                await page.wait_for_timeout(250)
                if await self._click_mode_option(page, pattern, include_buttons=True):
                    return
            except Exception:
                pass
            await page.keyboard.press("Escape")
        raise RuntimeError(self.mode_error(mode))

    @classmethod
    def artifact_file_info(cls, name: str | None):
        """Return a safe generated-file name and MIME type, or ``None``."""
        name = (name or "").strip()
        if not name or len(name) > 180 or name in {".", ".."} or any(item in name for item in ("/", "\\", "\0")):
            return None
        content_type = cls.GENERATED_FILE_TYPES.get(Path(name).suffix.lower())
        return (name, content_type) if content_type else None

    @classmethod
    def is_generated_file_label(cls, label: str | None) -> bool:
        """Recognize a localized generated-file card before its filename is visible."""
        text = " ".join(str(label or "").split()).lower()
        if not text or re.search(r"(?:attach|đính kèm|upload)", text, re.I):
            return False
        return bool(cls.artifact_file_info(text) or re.search(r"(?:download|tải)\s+(?:the\s+)?(?:file|tệp)|(?:file|tệp)\s+(?:txt|markdown|pdf)", text, re.I))

    @staticmethod
    def has_generated_file_content(content: bytes) -> bool:
        return bool(content)

    @classmethod
    def is_active_conversation_url(cls, url: str) -> bool:
        """A private conversation stays authenticated while its Library is open."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.scheme == "https" and (parsed.hostname or "").lower() == "chatgpt.com" and parsed.path.startswith("/c/")

    @classmethod
    def is_temporary_thread_url(cls, url: str) -> bool:
        """Return whether ChatGPT's local-only ``WEB:`` route is present.

        The Web client can briefly use a ``WEB:<id>`` route while a new chat is
        being composed. It is not a server conversation ID and replaying a
        job against it leaves only the user turn, eventually timing out with
        ``CHAT_BROWSER_NO_OUTPUT``. A fresh page must be used in that case.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if not cls.is_active_conversation_url(url):
            return False
        thread_id = parsed.path[len("/c/"):].split("/", 1)[0]
        return thread_id.casefold().startswith("web:")

    async def _generated_file_artifacts(self, page, assistant):
        """Download supported ChatGPT Library files attached to one reply.

        ChatGPT renders generated files as buttons, not links.  Only click a
        file-shaped button inside the current assistant reply, then its exact
        Library download control; this avoids fetching model-provided URLs.
        """
        import re

        artifacts, seen = [], set()
        file_buttons = assistant.get_by_role("button")
        for index in range(await file_buttons.count()):
            button = file_buttons.nth(index)
            if not await button.is_visible():
                continue
            label = await button.get_attribute("aria-label") or await button.inner_text()
            info = self.artifact_file_info(label)
            if not info and not self.is_generated_file_label(label):
                continue
            known_name = info[0] if info else ""
            if known_name and known_name in seen:
                continue
            if known_name:
                seen.add(known_name)
            try:
                await button.click(timeout=3_000)
                download_button = page.get_by_role("button", name=re.compile(r"^(?:download file|tải xuống tệp)$", re.I)).last
                library_file = (page.get_by_role("button", name=known_name) if known_name else page.get_by_role("button", name=re.compile(r"[^/\\s]+\.(?:txt|md|markdown|pdf)$", re.I))).last
                for _ in range(12):
                    if await download_button.count() and await download_button.is_visible():
                        break
                    if await library_file.count() and await library_file.is_visible():
                        await library_file.click(timeout=3_000, force=True)
                        await page.wait_for_timeout(300)
                        if await download_button.count() and await download_button.is_visible():
                            break
                    await page.wait_for_timeout(250)
                else:
                    continue
                if not await download_button.count() or not await download_button.is_visible():
                    download_link = page.locator("a[download]:visible").last
                    if not await download_link.count():
                        continue
                    async with page.expect_download(timeout=8_000) as pending_download:
                        await download_link.click(timeout=3_000, force=True)
                else:
                    async with page.expect_download(timeout=8_000) as pending_download:
                        await download_button.click(timeout=3_000, force=True)
                download = await pending_download.value
                saved_info = self.artifact_file_info(download.suggested_filename) or info
                if not saved_info:
                    continue
                with tempfile.NamedTemporaryFile(prefix="zm-chat-artifact-", suffix=".tmp", delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    await download.save_as(str(temporary_path))
                    if temporary_path.stat().st_size > 25 * 1024 * 1024:
                        continue
                    content = temporary_path.read_bytes()
                    if self.has_generated_file_content(content):
                        artifacts.append({"name": saved_info[0], "content": content, "content_type": saved_info[1]})
                finally:
                    temporary_path.unlink(missing_ok=True)
            except Exception:
                # A changed Web Library must not fail an otherwise completed
                # answer. The response text remains available to the user.
                continue
            finally:
                close_library = page.get_by_test_id("close-button").last
                if await close_library.count() and await close_library.is_visible():
                    try:
                        await close_library.evaluate("element => element.click()")
                    except Exception:
                        pass
        return artifacts

    @staticmethod
    def _assistant_locator(page):
        """Locate assistant turns across current and recently changed Web DOMs."""
        return page.locator(
            "[data-message-author-role='assistant'],"
            "[data-turn='assistant'],"
            "[data-testid*='conversation-turn-assistant']"
        )

    @staticmethod
    async def _latest_assistant_text(locator):
        """Read the newest visible assistant turn, even when its node is reused."""
        count = await locator.count()
        for index in range(count - 1, -1, -1):
            item = locator.nth(index)
            try:
                if not await item.is_visible():
                    continue
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if text:
                return count, text
        return count, ""

    @staticmethod
    def _final_text(snapshot: str, streamed: str) -> str:
        """Keep streamed deltas when the Web replaces the final DOM node."""
        return (snapshot or "").strip() or (streamed or "").strip()

    @staticmethod
    def _is_transient_assistant_text(text: str) -> bool:
        return text.strip().casefold() in {"đã ngừng suy nghĩ", "stopped thinking"}

    async def models(self):
        """Read the account's visible model picker; never call the Codex API."""
        try:
            await self.start(headless=False)
            page = await self.page()
            if not page.url or page.url == "about:blank":
                await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(1_000)
            import re
            texts = await page.get_by_role("button").all_inner_texts()
            # ChatGPT keeps the complete model list behind the current-model
            # button. Open it once so the selector reflects the account's
            # actual entitlement instead of only the selected model.
            buttons = page.get_by_role("button")
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                if not await button.is_visible():
                    continue
                label = (await button.inner_text()).strip()
                has_menu = (await button.get_attribute("aria-haspopup")) == "menu"
                if not has_menu or not re.search(r"(?:instant|tức thì|thinking|suy nghĩ|model)", label, re.I):
                    continue
                try:
                    await button.click(timeout=2_000)
                    await page.wait_for_timeout(250)
                    texts.extend(await page.get_by_role("menuitem").all_inner_texts())
                    texts.extend(await page.get_by_role("option").all_inner_texts())
                    # Radix renders the selectable model rows as
                    # menuitemradio, not menuitem. Ignore disabled plan-only
                    # entries so the selector contains models the account can
                    # actually use.
                    radios = page.get_by_role("menuitemradio")
                    for radio_index in range(await radios.count()):
                        radio = radios.nth(radio_index)
                        if not await radio.is_visible() or await radio.get_attribute("aria-disabled") == "true" or await radio.get_attribute("data-disabled") is not None:
                            continue
                        texts.append(await radio.inner_text())
                    break
                except Exception:
                    continue
            await page.keyboard.press("Escape")
            return self._model_names(texts)
        finally:
            await self.stop()

    async def health(self):
        """Check the isolated Web session without returning page text or cookies."""
        try:
            await self.start(headless=True)
            page = await self.page()
            if not page.url or page.url == "about:blank":
                await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(1_000)
            current = page.url.lower()
            import re
            login_controls = page.get_by_role("button", name=re.compile(r"^(?:log ?in|login|sign in|đăng nhập)$", re.I))
            for index in range(await login_controls.count()):
                if await login_controls.nth(index).is_visible():
                    return {"status": "reauth_required", "active": False, "loginRequired": True, "url": current.split("?", 1)[0]}
            composer = page.locator("#prompt-textarea:visible, textarea[placeholder]:visible, [contenteditable='true']:visible").first
            logged_in = await composer.count() > 0 and await composer.is_visible()
            if logged_in or self.is_active_conversation_url(current):
                # ChatGPT's Cloudflare challenge rejects Chromium headless.
                # Keep the one authenticated CDP browser alive and minimize
                # its isolated window; later requests attach without opening
                # another login window or copying stale cookies.
                await self.minimize(page)
                return {"status": "connected", "active": True}
            return {"status": "reauth_required", "active": False, "loginRequired": True, "url": current.split("?", 1)[0]}
        except Exception as exc:
            detail = str(exc)
            if "CHAT_BROWSER_WINDOW_CLOSED" in detail:
                return {"status": "browser_only", "active": False, "errorCode": "CHAT_BROWSER_WINDOW_CLOSED"}
            if "ProcessSingleton" in detail or "profile directory" in detail:
                return {"status": "unavailable", "active": False, "errorCode": "CHAT_BROWSER_PROFILE_LOCKED", "error": "Browser profile is already open. Close the ChatGPT Web window and check again."}
            return {"status": "unavailable", "active": False, "errorCode": "CHAT_BROWSER_HEALTH_FAILED", "error": detail.replace(str(self.profile_path), "<browser-profile>")[-1000:]}
        finally:
            await self.stop()

    async def logout(self):
        """End the profile session by clearing only this account's browser storage."""
        await self.start(headless=True)
        try:
            await self._context.clear_cookies()
            for page in self._context.pages:
                try:
                    await page.evaluate("window.localStorage.clear(); window.sessionStorage.clear();")
                except Exception:
                    pass
            return {"status": "signed_out"}
        finally:
            await self.stop()

    async def stop(self):
        if not self._connected and self._context:
            await self._context.close()
        # For a CDP connection, stopping Playwright closes only our transport;
        # calling Browser.close() would terminate the user's visible browser.
        if self._pw: await self._pw.stop()
        self._browser = self._context = self._pw = None
        self._connected = False

    async def run(self, prompt: str, mode: str, files: list[str] | None = None, cancel=None, model: str = "", thread_url: str = "", on_delta=None):
        """Attach to the one authenticated browser without reopening sign-in."""
        await self.start(headless=False, allow_launch=False)
        page = None
        try:
            page = await self.page()
            await self.minimize(page)
            target = "https://chatgpt.com/"
            if thread_url:
                from urllib.parse import urlparse
                parsed = urlparse(thread_url)
                if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.ALLOWED_HOSTS or not parsed.path.startswith("/c/"):
                    raise RuntimeError("CHAT_BROWSER_INVALID_THREAD")
                target = "https://chatgpt.com/" if self.is_temporary_thread_url(thread_url) else thread_url
            await page.goto(target, wait_until="domcontentloaded")
            import re
            login_controls = page.get_by_role("button", name=re.compile(r"^(?:log ?in|login|sign in|đăng nhập)$", re.I))
            for index in range(await login_controls.count()):
                if await login_controls.nth(index).is_visible():
                    raise RuntimeError("CHAT_BROWSER_NOT_AUTHENTICATED")
            composer = page.locator("#prompt-textarea:visible, textarea[placeholder]:visible, [contenteditable='true']:visible").first
            await composer.wait_for(state="visible", timeout=90_000)
            stop = page.get_by_role("button", name=re.compile(r"Stop|Dừng", re.I))
            if await stop.count() and await stop.is_visible():
                raise RuntimeError("CHAT_BROWSER_BUSY")
            # GPT-5.6 Sol with ``Tức thì``/Instant is ChatGPT Web's default.
            # Do not turn a transiently unmounted model menu into a hard
            # failure for the default request; only open it for an explicit
            # non-default model choice.
            if self.requires_model_picker(model):
                picker = page.get_by_role("button", name=re.compile(r"(?:instant|tức thì|thinking|suy nghĩ|reasoning|mức độ suy nghĩ)", re.I)).first
                if not await picker.count() or not await picker.is_visible():
                    raise RuntimeError("CHAT_BROWSER_MODEL_PICKER_UNAVAILABLE")
                await picker.click(timeout=3_000)
                await page.wait_for_timeout(500)
                model_item = page.get_by_role("menuitemradio", name=re.compile(rf"^{re.escape(model)}$", re.I)).first
                if not await model_item.count() or not await model_item.is_visible() or await model_item.get_attribute("aria-disabled") == "true" or await model_item.get_attribute("data-disabled") is not None:
                    await page.keyboard.press("Escape")
                    raise RuntimeError("CHAT_BROWSER_MODEL_UNAVAILABLE")
                try:
                    # The menu is portaled behind the composer in current
                    # ChatGPT layouts, so a DOM click is the fast/semantic
                    # path and avoids a pointless Playwright hit-test timeout.
                    await model_item.evaluate("element => element.click()")
                    await page.wait_for_timeout(250)
                    if await model_item.get_attribute("aria-checked") != "true":
                        raise RuntimeError("Model row did not become selected")
                except Exception as exc:
                    if await stop.count() and await stop.is_visible():
                        await page.keyboard.press("Escape")
                        raise RuntimeError("CHAT_BROWSER_BUSY") from exc
                    # If a browser variant rejects the DOM event, keep a
                    # semantic pointer-click fallback without coordinates.
                    try:
                        await model_item.scroll_into_view_if_needed(timeout=2_000)
                        await model_item.click(timeout=3_000, force=True)
                        await page.wait_for_timeout(250)
                        if await model_item.get_attribute("aria-checked") != "true":
                            raise RuntimeError("Model row did not become selected")
                    except Exception as final_exc:
                        await page.keyboard.press("Escape")
                        raise RuntimeError("CHAT_BROWSER_MODEL_SELECT_FAILED") from final_exc
                await page.keyboard.press("Escape")
            await self._activate_mode(page, mode)
            for file_path in files or []:
                file_input = page.locator("input[type=file]").first
                await file_input.set_input_files(file_path)
            assistant_locator = self._assistant_locator(page)
            assistant_count_before = await assistant_locator.count()
            baseline_ids = set()
            for index in range(assistant_count_before):
                message_id = await assistant_locator.nth(index).get_attribute("data-message-id")
                if message_id:
                    baseline_ids.add(message_id)
            await composer.fill(prompt)
            await self._submit_prompt(page, composer, files)
            await page.locator("main").wait_for(state="visible", timeout=30_000)
            # Read the newest assistant node while ChatGPT is generating. The
            # previous implementation waited for the final DOM and emitted one
            # large SSE chunk, which made a normal answer feel frozen.
            assistant = assistant_locator.last
            _, baseline_text = await self._latest_assistant_text(assistant_locator)
            last_text = baseline_text
            saw_new_assistant = False
            stable_rounds = 0
            for attempt in range(1_200):
                if cancel and cancel.is_set():
                    if await stop.count() and await stop.is_visible():
                        try:
                            # Current ChatGPT menus can place an invisible
                            # overlay above the composer. Dispatching the
                            # button's native click avoids waiting for a hit
                            # test that can never succeed.
                            await stop.evaluate("element => element.click()")
                        except Exception:
                            try: await stop.click(timeout=2_000, force=True)
                            except Exception: pass
                    raise RuntimeError("CHAT_BROWSER_CANCELLED")
                count, current_text = await self._latest_assistant_text(assistant_locator)
                if self._is_transient_assistant_text(current_text):
                    current_text = ""
                latest_id = ""
                if count:
                    try:
                        latest_id = await assistant_locator.nth(count - 1).get_attribute("data-message-id") or ""
                    except Exception:
                        pass
                if self.assistant_turn_changed(count, assistant_count_before, latest_id, baseline_ids, current_text, baseline_text):
                    saw_new_assistant = True
                    assistant = assistant_locator.nth(count - 1) if count else assistant_locator.last
                    if current_text and current_text != last_text:
                        if current_text.startswith(last_text):
                            delta = current_text[len(last_text):]
                            if delta and on_delta:
                                on_delta(delta)
                            last_text = current_text
                        else:
                            # Web rendering can briefly reformat markdown. Do
                            # not duplicate/rewrite already streamed text; the
                            # final snapshot below remains authoritative.
                            last_text = current_text
                        stable_rounds = 0
                    elif current_text:
                        stable_rounds += 1
                stop_visible = await stop.count() > 0 and await stop.is_visible()
                if not stop_visible and saw_new_assistant and last_text and stable_rounds >= 4:
                    # Some ChatGPT variants do not expose a Stop button. A
                    # short stable tail is the completion signal in that case.
                    break
                if attempt >= 179 and not saw_new_assistant and not stop_visible:
                    raise RuntimeError("CHAT_BROWSER_RESPONSE_TIMEOUT")
                await page.wait_for_timeout(250)
            if not saw_new_assistant:
                assistant = assistant_locator.last
            _, snapshot_text = await self._latest_assistant_text(assistant_locator)
            if self._is_transient_assistant_text(snapshot_text):
                snapshot_text = ""
            if not snapshot_text and await assistant_locator.count():
                snapshot_text = (await assistant_locator.last.inner_text()).strip()
                if self._is_transient_assistant_text(snapshot_text):
                    snapshot_text = ""
            text = self._final_text(snapshot_text, last_text)
            artifact_scope = assistant if await assistant.count() else page.locator("main")
            artifacts = await self._generated_file_artifacts(page, artifact_scope)
            if not text and not artifacts: raise RuntimeError("CHAT_BROWSER_NO_OUTPUT")
            if on_delta and text.startswith(last_text) and len(text) > len(last_text):
                on_delta(text[len(last_text):])
            if mode == "image":
                from urllib.parse import urlparse
                for index, image in enumerate(await artifact_scope.locator("img").all()):
                    src = await image.get_attribute("src")
                    host = (urlparse(src or "").hostname or "").lower()
                    if not src or not (host in self.ALLOWED_HOSTS or host.endswith(self.ALLOWED_SUFFIXES)): continue
                    response = await self._context.request.get(src)
                    body = await response.body()
                    content_type = (response.headers.get("content-type") or "").split(";", 1)[0]
                    if response.ok and content_type.startswith("image/") and len(body) <= 25 * 1024 * 1024:
                        extension = {"image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(content_type, "png")
                        artifacts.append({"name": f"chatgpt-image-{index + 1}.{extension}", "content": body, "content_type": content_type})
            return {"content": text, "thread_url": page.url, "artifacts": artifacts}
        finally:
            await self.stop()
