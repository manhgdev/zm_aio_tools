from __future__ import annotations

import json
import threading
import asyncio
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.core.app_config import load_app_config, provider_api_keys, provider_credentials
from pipeline.core.config import DATA
from .auth import ChatGPTAuth
from .providers import (
    API_PROVIDER_IDS,
    PROVIDER_LABELS,
    ChatGPTAccountProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    ProviderError,
    encode_attachment,
    normalize_model,
)
from .store import ChatStore
from .browser import ChatBrowserManager, SUPPORTED_CHAT_MODES, discover_browser, open_profile_url, profile_debug_port


# Live chat probes on 2026-09-06 showed that Groq and NVIDIA expose audio,
# guard, embedding, retired, and otherwise non-chat models in /models. Keep
# only ids that produced a streamed response through this app's chat contract.
# ponytail: this allowlist intentionally trades automatic catalogue expansion
# for a truthful picker; upgrade to provider capability metadata once those
# APIs reliably distinguish active text-chat models.
_VERIFIED_CHAT_MODELS = {
    "groq": frozenset({
        "allam-2-7b", "groq/compound", "groq/compound-mini",
        "openai/gpt-oss-120b", "openai/gpt-oss-20b",
        "openai/gpt-oss-safeguard-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b",
    }),
    "nvidia": frozenset({
        "google/gemma-4-31b-it", "meta/llama-3.2-11b-vision-instruct",
        "meta/muse-glimmer-30b", "minimaxai/minimax-m3",
        "nvidia/ising-calibration-1.5-31b", "nvidia/llama-3.1-nemoguard-8b-content-safety",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-content-safety",
        "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/riva-translate-4b-instruct-v1.1",
        "nvidia/riva-translate-4b-instruct-v2", "openai/gpt-oss-20b", "poolside/laguna-xs-2.1",
    }),
}
_UNAVAILABLE_CHAT_MODELS = {
    "openrouter": frozenset({
        "google/lyria-3-clip-preview", "google/lyria-3-pro-preview",
        "thinkingmachines/inkling-small:free", "thinkingmachines/inkling:free",
    }),
}


class ChatService:
    MAX_PROMPT = 100_000
    DEFAULT_MODEL = "GPT-5.6 Sol"
    DEFAULT_API_PROVIDER = "openrouter"
    DEFAULT_API_MODEL = "openrouter/free"
    # Stable fallbacks keep a configured provider selectable when its model
    # discovery endpoint is temporarily unavailable. Actual chat requests
    # still validate the key/model at the provider boundary.
    PROVIDER_FALLBACK_MODELS = {
        "groq": ("openai/gpt-oss-20b",),
        "nvidia": ("openai/gpt-oss-20b",),
    }

    def __init__(self, store=None):
        self.store = store or ChatStore(DATA / "chat" / "chat.sqlite3", DATA / "chat" / "attachments")
        self.chatgpt_auth = ChatGPTAuth()
        self._auth: dict[str, ChatGPTAuth] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._browser_locks: dict[str, threading.Lock] = {}
        self._health_locks: dict[str, threading.Lock] = {}
        self._model_cache: dict[str, tuple[float, list[dict]]] = {}
        self._model_cache_ttl = 300.0

    def clear_model_cache(self) -> None:
        """Forget provider discovery results after API credentials change."""
        self._model_cache.clear()

    def list_accounts(self):
        items = self.store.list_accounts(public=True)
        if not items:
            return []
        # Web mode intentionally exposes one account. Older duplicate rows remain
        # available to migration code but are never selectable or used for jobs.
        item = items[0]
        # Prefer the DB-persisted status (set by open_browser_login / browser_health)
        # over a cold oauth probe, so that browser_only / reauth_required states
        # survive a service restart without requiring a live browser round-trip.
        db_status = str(item.get("status") or "signed_out")
        email = item.get("email", "")
        if "@" in email:
            name, domain = email.split("@", 1)
            email = f"{name[:2]}***@{domain}"
        return [{**item, "provider": "chatgpt_web", "experimental": False,
             "configured": db_status == "connected",
             "status": db_status,
                 "email": email}]

    def primary_account(self):
        rows = self.store.list_accounts()
        return rows[0] if rows else None

    def _api_provider(self, provider_id: str):
        pid = str(provider_id or "").strip().lower()
        if pid not in API_PROVIDER_IDS:
            raise ProviderError("CHAT_PROVIDER_UNSUPPORTED", f"Unsupported chat provider: {pid}")
        try:
            cfg = provider_credentials(pid)
            keys = provider_api_keys(pid)
        except Exception as exc:
            raise ProviderError("CHAT_PROVIDER_KEY_MISSING", str(exc)) from None
        if pid == "gemini":
            return GeminiProvider(pid, cfg["apiKey"], cfg["baseUrl"])
        return OpenAICompatibleProvider(pid, cfg["apiKey"], cfg["baseUrl"], keys)

    @staticmethod
    def _public_model(item: dict, *, provider: str) -> dict:
        result = {
            "id": str(item.get("id") or ""),
            "label": str(item.get("label") or item.get("id") or ""),
            "provider": provider,
            "free": bool(item.get("free")),
            "capabilities": list(item.get("capabilities") or ["text"]),
            "available": bool(item.get("available", True)),
            "reason": str(item.get("reason") or ""),
        }
        return result

    def provider_models(self, provider_id: str, *, refresh: bool = False) -> list[dict]:
        pid = str(provider_id or "").strip().lower()
        if pid == "chatgpt_web":
            account = self.primary_account()
            if not account or account.get("status") not in {"connected"}:
                return []
            try:
                raw = ChatGPTAccountProvider(self.auth_for(account["id"])).models()
            except Exception:
                raw = []
            # GPT-5.6 Sol is the current Web default and does not require the
            # model picker. Keep it selectable when the picker is temporarily
            # unavailable, while still preferring every model the Web session
            # actually reports.
            if not raw:
                raw = [self.DEFAULT_MODEL]
            return [
                {"id": item, "label": item, "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": "Active ChatGPT API session"}
                for item in raw
            ]
        now = time.monotonic()
        cached = self._model_cache.get(pid)
        if cached and not refresh and now - cached[0] < self._model_cache_ttl:
            return cached[1]
        try:
            # Model discovery is a UI preflight. Keep a stalled provider from
            # blocking the whole Chat tab while still allowing a normal API
            # round trip on slower networks.
            records = self._api_provider(pid).model_records(timeout=8.0)
            free = [self._public_model(item, provider=pid) for item in records if item.get("free")]
            verified = _VERIFIED_CHAT_MODELS.get(pid)
            if verified is not None:
                free = [item for item in free if item["id"] in verified]
            unavailable = _UNAVAILABLE_CHAT_MODELS.get(pid, ())
            if unavailable:
                free = [item for item in free if item["id"] not in unavailable]
            # OpenRouter documents a dynamic free router even when /models is
            # temporarily unavailable or does not list it in the response.
            if pid == "openrouter" and not any(item["id"] == self.DEFAULT_API_MODEL for item in free):
                free.insert(0, {"id": self.DEFAULT_API_MODEL, "label": "Free Models Router", "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": "OpenRouter free router"})
            # Some provider catalogues omit pricing/metadata even though the
            # authenticated key can use the models. Keep the provider visible
            # with a documented default instead of rendering it disabled.
            if pid in self.PROVIDER_FALLBACK_MODELS and not free:
                free = [{"id": model, "label": model, "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": f"{pid} configured model fallback"} for model in self.PROVIDER_FALLBACK_MODELS[pid]]
            self._model_cache[pid] = (now, free)
            return free
        except ProviderError as exc:
            # The free router is a documented OpenRouter model id. Preserve a
            # cached/selectable router during a transient /models outage, but
            # never mask authentication or quota responses.
            if pid == "openrouter" and exc.code == "CHAT_PROVIDER_MODELS_UNAVAILABLE":
                router = [{"id": self.DEFAULT_API_MODEL, "label": "Free Models Router", "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": "OpenRouter free router"}]
                self._model_cache[pid] = (now, router)
                return router
            if pid in self.PROVIDER_FALLBACK_MODELS and exc.code == "CHAT_PROVIDER_MODELS_UNAVAILABLE":
                fallback = [{"id": model, "label": model, "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": f"{pid} configured model fallback"} for model in self.PROVIDER_FALLBACK_MODELS[pid]]
                self._model_cache[pid] = (now, fallback)
                return fallback
            raise
        except Exception as exc:
            raise ProviderError("CHAT_PROVIDER_MODELS_UNAVAILABLE", str(exc)) from None

    def providers(self, *, refresh: bool = False) -> list[dict]:
        result: list[dict] = []
        account = self.primary_account()
        if account:
            connected = account.get("status") == "connected"
            result.append({
                "id": "chatgpt_web", "label": PROVIDER_LABELS["chatgpt_web"], "kind": "api",
                "configured": connected, "status": "connected" if connected else str(account.get("status") or "signed_out"),
                "capabilities": ["text"],
                "models": self.provider_models("chatgpt_web"),
                "reason": "Active ChatGPT Web session" if connected else "ChatGPT Web session is not connected",
            })
        else:
            # Keep the Web transport visible even before its isolated profile
            # exists.  Previously this provider was omitted entirely, which
            # made the only way to start ChatGPT login disappear from the UI.
            result.append({
                "id": "chatgpt_web", "label": PROVIDER_LABELS["chatgpt_web"], "kind": "api",
                "configured": False, "status": "signed_out",
                "capabilities": ["text"],
                "models": [], "loginRequired": True,
                "reason": "ChatGPT Web profile is not configured",
            })
        cloud = load_app_config().get("cloud", {})
        configured_ids = [pid for pid in API_PROVIDER_IDS if bool(cloud.get(pid, {}).get("apiKey"))]
        # Discovery is independent per provider. Run configured calls in
        # parallel so one unavailable endpoint cannot make the Chat tab wait
        # through five sequential timeouts.
        with ThreadPoolExecutor(max_workers=max(1, len(configured_ids)), thread_name_prefix="chat-models") as executor:
            futures = {pid: executor.submit(self.provider_models, pid, refresh=refresh) for pid in configured_ids}
            for pid in API_PROVIDER_IDS:
                configured = pid in futures
                if not configured:
                    result.append({"id": pid, "label": PROVIDER_LABELS[pid], "kind": "api", "configured": False, "status": "missing_key", "models": [], "capabilities": ["text"]})
                    continue
                try:
                    models = futures[pid].result()
                    status = "ready" if models else "free_unavailable"
                    result.append({"id": pid, "label": PROVIDER_LABELS[pid], "kind": "api", "configured": True, "status": status, "models": models, "capabilities": sorted({cap for item in models for cap in item.get("capabilities", [])}) or ["text"], "reason": "" if models else "CHAT_FREE_MODEL_UNAVAILABLE"})
                except ProviderError as exc:
                    secret = str(cloud.get(pid, {}).get("apiKey") or "")
                    result.append({"id": pid, "label": PROVIDER_LABELS[pid], "kind": "api", "configured": True, "status": "error", "models": [], "capabilities": ["text"], "errorCode": exc.code, "reason": exc.safe_message(secret)})
                except Exception as exc:
                    result.append({"id": pid, "label": PROVIDER_LABELS[pid], "kind": "api", "configured": True, "status": "error", "models": [], "capabilities": ["text"], "errorCode": "CHAT_PROVIDER_MODELS_UNAVAILABLE", "reason": str(exc)[:300]})
        return result

    def resolve_provider(self, provider_id: str, model: str = "") -> tuple[str, str, dict | None]:
        pid = str(provider_id or "").strip().lower()
        if pid == "chatgpt_web":
            account = self.primary_account()
            if not account or self.auth_for(account["id"]).status().get("status") != "connected":
                raise ProviderError("CHATGPT_LOGIN_REQUIRED", "ChatGPT Web session is not connected")
            choices = self.provider_models(pid)
            selected = choices[0]["id"] if choices else self.DEFAULT_MODEL
            return pid, selected, {"capabilities": ["text"]}
        choices = self.provider_models(pid)
        selected = str(model or (choices[0]["id"] if choices else ""))
        found = next((item for item in choices if item["id"].casefold() == selected.casefold()), None)
        if not found:
            raise ProviderError("CHAT_FREE_MODEL_UNAVAILABLE", "No verified free model is available for this provider")
        return pid, selected, found

    def _attachment_payloads(self, attachments: list[dict], provider: str, capabilities: list[str]) -> list[dict]:
        payloads: list[dict] = []
        for item in attachments:
            path = self.store.attachment_path(item["id"])
            content_type = str(item.get("content_type") or "")
            if content_type.startswith("text/") or content_type in {"application/x-subrip", "application/json"}:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                payloads.append({"name": item["name"], "text": text[:200_000]})
            elif content_type.startswith("image/"):
                if "vision" not in capabilities:
                    raise ProviderError("CHAT_ATTACHMENT_UNSUPPORTED", f"{provider} model does not accept image attachments")
                encoded = encode_attachment(str(path), content_type)
                payloads.append(encoded)
            elif content_type.startswith("audio/"):
                if "audio" not in capabilities:
                    raise ProviderError("CHAT_ATTACHMENT_UNSUPPORTED", f"{provider} model does not accept audio attachments")
                encoded = encode_attachment(str(path), content_type)
                payloads.append(encoded)
            else:
                raise ProviderError("CHAT_ATTACHMENT_UNSUPPORTED", f"{provider} model does not accept this attachment")
        return payloads

    def auth_for(self, account_id):
        if account_id not in self._auth:
            account = self.store.get_account(account_id)
            opener = None
            if account:
                def opener(url):
                    return open_profile_url(
                        Path(account["profile_path"]),
                        account["browser_family"],
                        url,
                        debug_port=profile_debug_port(account_id),
                    )
            self._auth[account_id] = ChatGPTAuth(account_id=account_id, browser_opener=opener)
        return self._auth[account_id]

    def create_account(self, label, browser_family=None):
        existing = self.primary_account()
        if existing:
            return {k: v for k, v in existing.items() if k != "profile_path"}
        family = browser_family or "api"
        account_id = __import__("uuid").uuid4().hex
        profile = DATA / "chat" / "profiles" / account_id
        # Store supplies the canonical id; rename the empty profile target after creation.
        item = self.store.create_account(label, family, profile, account_id=account_id)
        return {k: v for k, v in item.items() if k != "profile_path"}

    def delete_account(self, account_id, delete_history=False):
        self.auth_for(account_id).logout()
        self._auth.pop(account_id, None)
        return self.store.delete_account(account_id, delete_history=delete_history)

    def open_browser_login(self, account_id):
        account = self.store.get_account(account_id)
        if not account:
            raise KeyError(account_id)
        result = self.auth_for(account_id).start_login(open_browser=True)
        self.store.update_account(account_id, status="browser_only")
        return {"accountId": account_id, **result}

    def browser_health(self, account_id):
        account = self.store.get_account(account_id)
        if not account:
            raise KeyError(account_id)
        lock = self._health_locks.setdefault(account_id, threading.Lock())
        if not lock.acquire(blocking=False):
            saved = next((item for item in self.list_accounts() if item["id"] == account_id), {})
            return {**saved, "errorCode": "CHAT_BROWSER_BUSY", "active": False}
        try:
            manager = ChatBrowserManager(account_id, Path(account["profile_path"]), account["browser_family"])
            try:
                result = asyncio.run(manager.health())
            except Exception as exc:
                msg = str(exc)
                if "CHAT_BROWSER_WINDOW_CLOSED" in msg:
                    # Window closed during a login flow — the browser was open
                    # so the account is at least browser_only. Preserve
                    # 'connected' if it was already promoted, but never
                    # downgrade it to signed_out.
                    current = str(account.get("status") or "signed_out")
                    preserved = current if current == "connected" else "browser_only"
                    self.store.update_account(account_id, status=preserved)
                    saved = next((item for item in self.list_accounts() if item["id"] == account_id), {})
                    return {**saved, "errorCode": "CHAT_BROWSER_WINDOW_CLOSED", "active": False}
                self.store.update_account(account_id, status="unavailable")
                saved = next((item for item in self.list_accounts() if item["id"] == account_id), {})
                return {**saved, "errorCode": "CHAT_BROWSER_HEALTH_FAILED", "active": False}
            health_status = str(result.get("status") or "unavailable")
            error_code = str(result.get("errorCode") or "")
            if error_code == "CHAT_BROWSER_WINDOW_CLOSED":
                # Closed window during login: preserve previous DB status
                saved = next((item for item in self.list_accounts() if item["id"] == account_id), {})
                return {**saved, "errorCode": error_code, "active": result.get("active", False)}
            self.store.update_account(account_id, status=health_status)
            saved = next((item for item in self.list_accounts() if item["id"] == account_id), {})
            return {**saved, **result, "active": result.get("active", False)}
        finally:
            lock.release()

    def browser_logout(self, account_id):
        account = self.store.get_account(account_id)
        if not account:
            raise KeyError(account_id)
        self.auth_for(account_id).logout()
        self.store.update_account(account_id, status="signed_out", email="")
        return {"accountId": account_id, "status": "signed_out"}

    def validate_prompt(self, payload):
        if payload.get("toolCall"):
            raise ValueError("Tool execution is disabled in Chat V1")
        if str(payload.get("mode") or "chat") not in SUPPORTED_CHAT_MODES:
            raise ValueError("Unsupported chat mode")
        text = str(payload.get("content") or "").strip()
        if not text:
            raise ValueError("Message is empty")
        if len(text.encode("utf-8")) > self.MAX_PROMPT:
            raise ValueError("Message is too large")
        return text

    def validate_attachments(self, conversation_id: str, attachment_ids) -> list[str]:
        """Validate ownership/count before a streaming response is opened."""
        if attachment_ids is None:
            return []
        if not isinstance(attachment_ids, (list, tuple)):
            raise ValueError("Attachment ids must be a list")
        ids = list(dict.fromkeys(str(value) for value in attachment_ids))
        if len(ids) > 10:
            raise ValueError("A message can contain at most 10 attachments")
        owned = {str(item["id"]) for item in self.store.list_attachments(conversation_id)}
        if any(value not in owned for value in ids):
            raise ValueError("Attachment does not belong to this conversation")
        return ids

    def models(self, account_id):
        account = self.store.get_account(account_id)
        if account:
            # Always use ChatBrowserManager for browser accounts so tests can
            # monkeypatch it without needing a real oauth token.
            try:
                manager = ChatBrowserManager(account["id"], Path(account["profile_path"]), account["browser_family"])
                models = asyncio.run(manager.models())
            except Exception:
                models = []
            # Only expose labels confirmed by the current Web model picker.
            # Older builds stored the workspace label (for example
            # ``GPT Business``) as ``last_model``; returning it here creates a
            # selectable option that ChatGPT cannot actually use.
            if account.get("last_model") and any(account["last_model"].casefold() == item.casefold() for item in models):
                models = [account["last_model"], *[item for item in models if item.casefold() != account["last_model"].casefold()]]
            return list(dict.fromkeys(models))
        if account_id != "openai_api": return []
        cfg = load_app_config()["cloud"]["openai"]
        if not cfg["apiKey"]:
            return []
        try:
            return OpenAIProvider(cfg["apiKey"], cfg["baseUrl"]).models()
        except Exception:
            return [cfg["model"]]

    def remember_model(self, account_id, model):
        if account_id != "openai_api" and model:
            self.store.update_account(account_id, last_model=model)

    @staticmethod
    def event(kind, **data):
        return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def cancel(self, conversation_id):
        event = self._cancels.get(conversation_id)
        if event:
            event.set()
        return bool(event)

    def stream_message(self, conversation_id, payload):
        content = self.validate_prompt(payload)
        conv = self.store.get_conversation(conversation_id)
        if not conv:
            raise KeyError(conversation_id)
        attachment_ids = self.validate_attachments(conversation_id, payload.get("attachmentIds", []))
        retry_assistant_id = str(payload.get("retry_assistant_id") or "").strip()
        if retry_assistant_id:
            # Retry in-place: reuse the failed assistant message; no new user message.
            # Delete any messages that were created after the failed one.
            all_msgs = self.store.list_messages(conversation_id)
            after = [m for m in all_msgs if m["id"] == retry_assistant_id]
            if not after:
                raise KeyError(retry_assistant_id)
            idx = next(i for i, m in enumerate(all_msgs) if m["id"] == retry_assistant_id)
            for m in all_msgs[idx + 1:]:
                self.store.delete_message(m["id"])
            self.store.update_message(retry_assistant_id, content="", status="streaming", error=None)
            assistant = self.store.get_message(retry_assistant_id)
            prior_user = next((m for m in reversed(all_msgs[:idx]) if m["role"] == "user"), None)
            attachments = self.store.attach_to_message(conversation_id, prior_user["id"], []) if prior_user else []
        else:
            user_message = self.store.create_message(conversation_id, "user", content)
            attachments = self.store.attach_to_message(conversation_id, user_message["id"], attachment_ids)
            assistant = self.store.create_message(conversation_id, "assistant", "", status="streaming")
        cancel = threading.Event()
        self._cancels[conversation_id] = cancel
        accumulated = ""
        use_browser = False
        mode = str(payload.get("mode") or "chat")
        account_record = self.primary_account()
        provider = None
        requested_provider = str(payload.get("provider") or conv.get("provider_id") or conv.get("account_id") or "").strip().lower()
        if requested_provider == "openai_api":
            requested_provider = "openai"
        if account_record and requested_provider == str(account_record["id"]).lower():
            requested_provider = "chatgpt_web"
        if not requested_provider:
            requested_provider = self.DEFAULT_API_PROVIDER
        selected_provider = "chatgpt_web" if requested_provider == "chatgpt_web" else requested_provider
        selected_model = self.DEFAULT_MODEL if selected_provider == "chatgpt_web" else str(payload.get("model") or conv.get("model") or "")
        usage: dict | None = None
        if not selected_model and selected_provider == self.DEFAULT_API_PROVIDER:
            selected_model = self.DEFAULT_API_MODEL
        # Emit provider/model immediately so the UI can show what is being
        # attempted while discovery or browser work is still in progress.
        yield self.event("message.started", messageId=assistant["id"], provider=selected_provider, model=selected_model or None)
        try:
            history = self.store.list_messages(conversation_id)[:-1]
            if requested_provider not in {"chatgpt_web", *API_PROVIDER_IDS, "openai_api", ""}:
                raise ProviderError("ACCOUNT_NOT_FOUND", "ChatGPT Web session was not found")
            has_api_token = self.auth_for(account_record["id"]).status().get("status") == "connected" if account_record else False
            if requested_provider == "chatgpt_web" and account_record and account_record.get("status") in {"connected", "browser_only"} and not has_api_token:
                if not account_record:
                    raise ProviderError("ACCOUNT_NOT_FOUND", "ChatGPT Web session was not found")
                use_browser = True
                if account_record.get("status") != "connected":
                    raise ProviderError("CHAT_BROWSER_NOT_AUTHENTICATED", "ChatGPT Web session is not connected")
                choices = self.provider_models("chatgpt_web")
                selected_model = (conv.get("model") or "") if conv.get("model") in {item["id"] for item in choices} else (choices[0]["id"] if choices else self.DEFAULT_MODEL)
                if not selected_model:
                    selected_model = self.DEFAULT_MODEL
                if conv.get("model") != selected_model or conv.get("provider_id") != "chatgpt_web" or conv.get("account_id") != account_record["id"]:
                    self.store.update_conversation(conversation_id, provider_id="chatgpt_web", account_id=account_record["id"], model=selected_model)
                    conv["model"] = selected_model
                yield self.event("tool.started", tool=mode, transport="chatgpt_browser", model=selected_model or None)
                paths = [str(self.store.attachment_path(item["id"])) for item in attachments]
                lock = self._browser_locks.setdefault(account_record["id"], threading.Lock())
                if not lock.acquire(blocking=False):
                    raise RuntimeError("CHAT_BROWSER_BUSY")
                manager = ChatBrowserManager(account_record["id"], Path(account_record["profile_path"]), account_record["browser_family"])
                updates: queue.Queue[tuple[str, object]] = queue.Queue()
                result_holder: dict[str, object] = {}

                def on_delta(delta):
                    if delta:
                        updates.put(("delta", str(delta)))

                def run_browser():
                    try:
                        result_holder["result"] = asyncio.run(manager.run(content, mode, paths, cancel, selected_model, conv.get("provider_thread_url", ""), on_delta=on_delta))
                    except BaseException as exc:
                        result_holder["error"] = exc
                    finally:
                        updates.put(("done", None))

                worker = threading.Thread(target=run_browser, name=f"chat-browser-{account_record['id'][:8]}", daemon=True)
                try:
                    worker.start()
                    while worker.is_alive() or not updates.empty():
                        try:
                            kind, value = updates.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        if kind == "delta":
                            accumulated += str(value)
                            yield self.event("content.delta", messageId=assistant["id"], delta=str(value))
                    worker.join()
                    if "error" in result_holder:
                        raise result_holder["error"]
                    result = result_holder["result"]
                finally:
                    if worker.is_alive():
                        cancel.set()
                        worker.join(timeout=10)
                    lock.release()
                raw_usage = result.get("usage") if isinstance(result, dict) else None
                usage = raw_usage if isinstance(raw_usage, dict) else None
                final_content = str(result["content"] or "")
                # If the browser returned before the first DOM delta (or a
                # markdown reflow prevented a safe suffix), complete the
                # stream with the authoritative final snapshot without
                # duplicating text already sent to the client.
                if not accumulated and final_content:
                    accumulated = final_content
                    yield self.event("content.delta", messageId=assistant["id"], delta=final_content)
                else:
                    accumulated = final_content
                thread_url = str(result.get("thread_url") or "")
                if thread_url:
                    self.store.update_conversation(conversation_id, provider_thread_url=thread_url)
                for artifact in result["artifacts"]:
                    saved = self.store.save_artifact(conversation_id, assistant["id"], artifact["name"], artifact["content"], artifact["content_type"])
                    yield self.event("artifact.completed", messageId=assistant["id"], artifact={**saved, "url": f"/api/chat/artifacts/{saved['id']}"})
                yield self.event("tool.completed", tool=mode, transport="chatgpt_browser")
            else:
                if mode != "chat":
                    raise ProviderError("CHAT_PROVIDER_CAPABILITY_UNAVAILABLE", "This mode is available only with ChatGPT Web")
                selected_provider, selected_model, model_info = self.resolve_provider(
                    requested_provider or self.DEFAULT_API_PROVIDER,
                    str(payload.get("model") or conv.get("model") or ""),
                )
                if conv.get("provider_id") != selected_provider or conv.get("model") != selected_model:
                    self.store.update_conversation(
                        conversation_id,
                        provider_id=selected_provider,
                        account_id=selected_provider,
                        model=selected_model,
                    )
                if selected_provider == "chatgpt_web":
                    provider = ChatGPTAccountProvider(self.auth_for(account_record["id"]))
                elif selected_provider == "openai":
                    cfg = load_app_config()["cloud"]["openai"]
                    provider = OpenAIProvider(cfg["apiKey"], cfg["baseUrl"])
                else:
                    provider = self._api_provider(selected_provider)
                if model_info and "text" not in model_info.get("capabilities", ["text"]):
                    raise ProviderError("CHAT_PROVIDER_CAPABILITY_UNAVAILABLE", "Selected model does not support text chat")
                payloads = self._attachment_payloads(attachments, selected_provider, list(model_info.get("capabilities", ["text"]) if model_info else ["text"]))
                text_attachments = [item for item in payloads if item.get("text")]
                if text_attachments and history:
                    history[-1]["content"] = str(history[-1].get("content") or "") + "\n\n" + "\n\n".join(f"[{item['name']}]\n{item['text']}" for item in text_attachments)
                native_attachments = [item for item in payloads if item.get("data")]
                yield self.event("tool.started", tool=mode, transport=selected_provider, model=selected_model)
                stream_events = getattr(provider, "stream_events", None)
                if callable(stream_events):
                    deltas = stream_events(selected_model, history, cancel, attachments=native_attachments)
                    for kind, delta in deltas:
                        if kind == "content.delta":
                            accumulated += delta
                        yield self.event(kind, messageId=assistant["id"], delta=delta)
                else:
                    for delta in provider.stream(selected_model, history, cancel, attachments=native_attachments):
                        accumulated += delta
                        yield self.event("content.delta", messageId=assistant["id"], delta=delta)
                raw_usage = getattr(provider, "last_usage", None)
                usage = raw_usage if isinstance(raw_usage, dict) else None
                if not accumulated and not cancel.is_set():
                    raise ProviderError("CHAT_PROVIDER_EMPTY_RESPONSE", "Provider completed without returning any text")
                yield self.event("tool.completed", tool=mode, transport=selected_provider, model=selected_model)
            status = "interrupted" if cancel.is_set() else "completed"
            self.store.update_message(assistant["id"], content=accumulated, status=status)
            yield self.event("message.completed", messageId=assistant["id"], content=accumulated, status=status, provider=selected_provider, model=selected_model, usage=usage)
        except Exception as exc:
            api_key = None
            try:
                api_key = load_app_config()["cloud"].get(selected_provider, {}).get("apiKey") if selected_provider else None
            except Exception:
                pass
            if isinstance(exc, ProviderError):
                error_code = exc.code
                safe_error = exc.safe_message(api_key or "")
            else:
                error_code = "CHAT_PROVIDER_ERROR"
                safe_error = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
            # Browser cancellation deliberately raises to leave its polling
            # loop immediately. It is a normal terminal state, not an error.
            if cancel.is_set() or "CHAT_BROWSER_CANCELLED" in safe_error:
                self.store.update_message(assistant["id"], content=accumulated, status="interrupted")
                yield self.event("message.completed", messageId=assistant["id"], content=accumulated, status="interrupted", provider=selected_provider, model=selected_model or None, usage=None)
                return
            if use_browser and "CHAT_BROWSER_NOT_AUTHENTICATED" in safe_error and account_record:
                self.store.update_account(account_record["id"], status="reauth_required")
            self.store.update_message(assistant["id"], content=accumulated, status="failed", error=f"{error_code}: {safe_error}")
            yield self.event("message.failed", messageId=assistant["id"], error=safe_error, errorCode=error_code, provider=selected_provider or None, model=selected_model or None)
        finally:
            self._cancels.pop(conversation_id, None)
