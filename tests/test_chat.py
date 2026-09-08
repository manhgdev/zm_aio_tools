import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from pipeline.chat.store import ChatStore


def test_chat_history_survives_restart_and_streams_are_interrupted(tmp_path):
    db = tmp_path / "chat.sqlite3"
    store = ChatStore(db, tmp_path / "attachments")
    conversation = store.create_conversation("Test")
    message = store.create_message(conversation["id"], "assistant", "partial", status="streaming")
    store.close()

    reopened = ChatStore(db, tmp_path / "attachments")
    assert reopened.get_conversation(conversation["id"])["title"] == "Test"
    assert next(item for item in reopened.list_messages(conversation["id"]) if item["id"] == message["id"])["status"] == "interrupted"


def test_legacy_conversation_schema_gets_provider_id_migration(tmp_path):
    db = tmp_path / "chat.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, account_id TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    connection.execute("INSERT INTO conversations VALUES ('legacy', 'Legacy', 'openrouter', 'openrouter/free', 'now', 'now')")
    connection.commit()
    connection.close()

    assert ChatStore(db, tmp_path / "attachments").get_conversation("legacy")["provider_id"] == "openrouter"


def test_attachment_filename_cannot_escape_conversation(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = store.create_conversation("Files")
    with pytest.raises(ValueError):
        store.save_attachment(conversation["id"], "../secret.txt", b"no")


def test_account_payload_never_contains_secret(tmp_path):
    from pipeline.chat.service import ChatService

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    payload = json.dumps(service.list_accounts())
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_v1_rejects_tool_execution_and_unknown_modes(tmp_path):
    from pipeline.chat.service import ChatService

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    with pytest.raises(ValueError, match="Tool execution"):
        service.validate_prompt({"content": "run", "toolCall": {"name": "flow"}})
    with pytest.raises(ValueError, match="Unsupported chat mode"):
        service.validate_prompt({"content": "run", "mode": "video"})


def test_accounts_use_one_internal_chrome_runtime_and_hide_it_from_api(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    first = store.create_account("Work", tmp_path / "profiles" / "one")
    second = store.create_account("Personal", tmp_path / "profiles" / "two")
    assert first["browser_family"] == second["browser_family"] == "chrome"
    payload = json.dumps(store.list_accounts(public=True))
    assert "browser_family" not in payload
    assert "profile_path" not in payload


def test_legacy_edge_account_is_normalized_without_losing_profile(tmp_path):
    db = tmp_path / "chat.sqlite3"
    profile = tmp_path / "profiles" / "legacy"
    store = ChatStore(db, tmp_path / "attachments")
    account = store.create_account("Legacy", profile)
    store._db.execute("UPDATE chat_accounts SET browser_family='edge' WHERE id=?", (account["id"],))
    store._db.commit()
    store.close()

    migrated = ChatStore(db, tmp_path / "attachments").get_account(account["id"])
    assert migrated["browser_family"] == "chrome"
    assert migrated["profile_path"] == str(profile)


def test_chat_account_api_does_not_require_browser_family(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.chat as route
    from pipeline.chat.service import ChatService
    from pipeline.core import license as license_module

    monkeypatch.setattr(route, "service", ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")))
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)
    response = TestClient(create_app()).post("/api/chat/accounts", json={"provider": "chatgpt_account", "label": "Codex"})

    assert response.status_code == 200
    assert response.json()["status"] == "signed_out"
    assert "browser_family" not in response.json()


class _MemorySecrets:
    value = None

    def load(self):
        return self.value

    def save(self, value):
        self.value = value

    def delete(self):
        self.value = None


class _NoopCallbackServer:
    def shutdown(self):
        pass

    def server_close(self):
        pass


class _Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _OAuthClient:
    def post(self, _url, **_kwargs):
        return _Response({"access_token": "header.payload.sig", "refresh_token": "refresh", "expires_in": 3600})


def test_oauth_login_builds_pkce_url_and_waits_for_callback(monkeypatch):
    from pipeline.chat.auth import ChatGPTAuth

    monkeypatch.setattr(ChatGPTAuth, "_callback_server", staticmethod(lambda *_args: _NoopCallbackServer()))
    auth = ChatGPTAuth(token_store=_MemorySecrets(), client=_OAuthClient(), browser_opener=lambda _url: None)
    login = auth.start_login()
    try:
        assert "oauth/authorize" in login["authorizationUrl"]
        assert "code_challenge=" in login["authorizationUrl"]
        assert auth.poll(login["loginId"])["status"] == "pending"
    finally:
        state = auth._pending.pop(login["loginId"])
        state.server.shutdown()
        state.server.server_close()


def test_expired_oauth_refresh_marks_token_unusable():
    from pipeline.chat.auth import ChatGPTAuth

    secrets = _MemorySecrets()
    secrets.value = {"access_token": "old", "refresh_token": "refresh", "expires_at": 0}

    class Client:
        def post(self, *_args, **_kwargs):
            return _Response({}, 401)

    with pytest.raises(RuntimeError, match="session expired"):
        ChatGPTAuth(token_store=secrets, client=Client()).tokens()
    assert secrets.load() is None


def test_oauth_token_exchange_failure_clears_pending_login(monkeypatch):
    from pipeline.chat.auth import ChatGPTAuth

    class Client:
        def post(self, *_args, **_kwargs):
            raise RuntimeError("token exchange failed")

    monkeypatch.setattr(ChatGPTAuth, "_callback_server", staticmethod(lambda *_args: _NoopCallbackServer()))
    auth = ChatGPTAuth(token_store=_MemorySecrets(), client=Client())
    login = auth.start_login(open_browser=False)
    auth._pending[login["loginId"]].code = "oauth-code"

    with pytest.raises(RuntimeError, match="token exchange failed"):
        auth.poll(login["loginId"])
    assert not auth.login_pending


def test_login_uses_visible_flow_chrome_once_and_closes_after_oauth(monkeypatch, tmp_path):
    from pipeline.chat.auth import ChatGPTAuth
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    service = ChatService(store=store)
    started, stopped = threading.Event(), threading.Event()
    seen = []

    async def visible_login(profile, url, complete):
        seen.append((profile, url))
        started.set()
        while not complete.is_set():
            await __import__("asyncio").sleep(0.001)
        stopped.set()

    monkeypatch.setattr("pipeline.chat.service.chrome_executable", lambda: tmp_path / "chrome")
    monkeypatch.setattr(ChatGPTAuth, "_callback_server", staticmethod(lambda *_args: _NoopCallbackServer()))
    monkeypatch.setattr(service, "_show_codex_login", visible_login)
    login = service.open_browser_login(account["id"])
    assert login["loginId"]
    assert started.wait(1)
    assert seen[0][0] == tmp_path / "profile"
    assert "oauth/authorize" in seen[0][1]

    auth = service.auth_for(account["id"])
    auth._pending[login["loginId"]].error = "cancelled"
    assert service.poll_login(account["id"], login["loginId"])["status"] == "failed"
    assert stopped.wait(1)


def test_stale_login_reuses_the_same_persistent_chrome_profile(monkeypatch, tmp_path):
    from pipeline.chat.auth import ChatGPTAuth
    from pipeline.chat.service import ChatService

    profile = tmp_path / "profile"
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", profile)
    store.update_account(account["id"], status="connecting")
    service = ChatService(store=store)
    seen = []

    async def visible_login(path, _url, _complete):
        seen.append(path)

    monkeypatch.setattr("pipeline.chat.service.chrome_executable", lambda: tmp_path / "chrome")
    monkeypatch.setattr(ChatGPTAuth, "_callback_server", staticmethod(lambda *_args: _NoopCallbackServer()))
    monkeypatch.setattr(service, "_show_codex_login", visible_login)

    assert service.open_browser_login(account["id"])["loginId"]
    for _ in range(100):
        if seen:
            break
        time.sleep(0.01)
    assert seen == [profile]
    assert store.get_account(account["id"])["profile_path"] == str(profile)


def test_stale_connecting_status_recovers_without_touching_profile(tmp_path):
    from pipeline.chat.service import ChatService

    profile = tmp_path / "profile"
    profile.mkdir()
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", profile)
    store.update_account(account["id"], status="connecting")

    recovered = ChatService(store=store).list_accounts()[0]

    assert recovered["status"] == "signed_out"
    assert Path(store.get_account(account["id"])["profile_path"]) == profile
    assert profile.is_dir()


def test_stale_connecting_status_restores_saved_codex_token(monkeypatch, tmp_path):
    from pipeline.chat.service import ChatService

    profile = tmp_path / "profile"
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", profile)
    store.update_account(account["id"], status="connecting")
    service = ChatService(store=store)

    class Auth:
        login_pending = False

        def status(self):
            return {"status": "connected", "email": "user@example.com"}

    monkeypatch.setattr(service, "auth_for", lambda _account_id: Auth())
    recovered = service.list_accounts()[0]

    assert recovered["status"] == "connected"
    assert recovered["configured"] is True
    assert recovered["email"] == "us***@example.com"
    assert store.get_account(account["id"])["profile_path"] == str(profile)


def test_login_requires_google_chrome(monkeypatch, tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    monkeypatch.setattr("pipeline.chat.service.chrome_executable", lambda: None)

    with pytest.raises(RuntimeError, match="CHAT_CHROME_REQUIRED"):
        ChatService(store=store).open_browser_login(account["id"])


def test_codex_models_and_chat_use_token_api_without_browser(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    store.update_account(account["id"], status="connected")
    conversation = store.create_conversation("Codex", account_id=account["id"], model="gpt-5", provider_id="chatgpt_web")

    class Auth:
        def status(self):
            return {"status": "connected", "configured": True}

        def tokens(self):
            return {"access_token": "token", "account_id": "account", "expires_at": time.time() + 3600}

    class Provider:
        def __init__(self, _auth):
            pass

        def models(self):
            return ["gpt-5"]

        def stream(self, _model, _messages, _cancel, attachments=None):
            assert attachments == []
            yield "Codex answer"

    service = ChatService(store=store)
    monkeypatch.setattr(service, "auth_for", lambda _account_id: Auth())
    monkeypatch.setattr("pipeline.chat.service.ChatGPTAccountProvider", Provider)
    monkeypatch.setattr("pipeline.chat.service.BrowserManager", lambda *_args, **_kwargs: pytest.fail("ChatGPT Codex chat must not open Chrome"))

    assert service.provider_models("chatgpt_web")[0]["id"] == "gpt-5"
    events = "".join(service.stream_message(conversation["id"], {"content": "hello", "provider": "chatgpt_web", "model": "gpt-5"}))
    assert "Codex answer" in events
    assert store.get_conversation(conversation["id"])["account_id"] == account["id"]


def test_expired_codex_token_requires_reauthentication(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    store.update_account(account["id"], status="connected")

    class ExpiredAuth:
        def tokens(self):
            raise RuntimeError("ChatGPT session expired; sign in again")

    service = ChatService(store=store)
    monkeypatch.setattr(service, "auth_for", lambda _account_id: ExpiredAuth())
    assert service.browser_health(account["id"])["status"] == "reauth_required"
    assert store.get_account(account["id"])["status"] == "reauth_required"


def test_transient_token_check_preserves_connected_session(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    store.update_account(account["id"], status="connected")

    class OfflineAuth:
        def tokens(self):
            raise RuntimeError("temporary network failure")

    service = ChatService(store=store)
    monkeypatch.setattr(service, "auth_for", lambda _account_id: OfflineAuth())
    health = service.browser_health(account["id"])
    assert health["status"] == "connected"
    assert health["errorCode"] == "CHATGPT_TOKEN_CHECK_FAILED"


def test_non_chat_mode_is_rejected_for_codex_api(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Codex", tmp_path / "profile")
    store.update_account(account["id"], status="connected")
    conversation = store.create_conversation("Codex", account_id=account["id"], provider_id="chatgpt_web")

    class Auth:
        def status(self):
            return {"status": "connected"}

    service = ChatService(store=store)
    monkeypatch.setattr(service, "auth_for", lambda _account_id: Auth())
    events = "".join(service.stream_message(conversation["id"], {"content": "find", "mode": "search", "provider": "chatgpt_web"}))
    assert "CHAT_PROVIDER_CAPABILITY_UNAVAILABLE" in events


def test_api_provider_stream_does_not_use_codex_browser(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = store.create_conversation("Groq", account_id="groq", model="model", provider_id="groq")

    class Provider:
        def stream(self, _model, _messages, _cancel, attachments=None):
            assert attachments == []
            yield "ok"

    service = ChatService(store=store)
    monkeypatch.setattr(service, "resolve_provider", lambda provider, model: (provider, model, {"id": model, "capabilities": ["text"]}))
    monkeypatch.setattr(service, "_api_provider", lambda _provider: Provider())
    events = "".join(service.stream_message(conversation["id"], {"content": "hello", "provider": "groq", "model": "model"}))
    assert '"content": "ok"' in events


def test_api_provider_empty_stream_fails_instead_of_leaving_answer_pending(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = store.create_conversation("NVIDIA", account_id="nvidia", model="model", provider_id="nvidia")

    class EmptyProvider:
        def stream(self, *_args, **_kwargs):
            return iter(())

    service = ChatService(store=store)
    monkeypatch.setattr(service, "resolve_provider", lambda provider, model: (provider, model, {"id": model, "capabilities": ["text"]}))
    monkeypatch.setattr(service, "_api_provider", lambda _provider: EmptyProvider())
    events = "".join(service.stream_message(conversation["id"], {"content": "hello", "provider": "nvidia", "model": "model"}))
    assert "CHAT_PROVIDER_EMPTY_RESPONSE" in events
    assert store.list_messages(conversation["id"])[-1]["status"] == "failed"
