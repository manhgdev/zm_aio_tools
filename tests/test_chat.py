from __future__ import annotations

import json
import sqlite3
import os
import threading
import time

import pytest

from pipeline.chat.store import ChatStore


def test_chat_history_survives_restart_and_streams_are_interrupted(tmp_path):
    db = tmp_path / "chat.sqlite3"
    store = ChatStore(db, tmp_path / "attachments")
    conv = store.create_conversation("Xin chào")
    store.create_message(conv["id"], "user", "Chào bạn")
    pending = store.create_message(conv["id"], "assistant", "", status="streaming")
    store.close()

    reopened = ChatStore(db, tmp_path / "attachments")
    messages = reopened.list_messages(conv["id"])
    assert messages[0]["content"] == "Chào bạn"
    assert next(x for x in messages if x["id"] == pending["id"])["status"] == "interrupted"


def test_chat_thread_url_survives_restart(tmp_path):
    db = tmp_path / "chat.sqlite3"
    store = ChatStore(db, tmp_path / "attachments")
    conv = store.create_conversation("Thread")
    store.update_conversation(conv["id"], provider_thread_url="https://chatgpt.com/c/thread-123")
    store.close()

    reopened = ChatStore(db, tmp_path / "attachments")
    assert reopened.get_conversation(conv["id"])["provider_thread_url"] == "https://chatgpt.com/c/thread-123"


def test_conversation_persists_provider_id_separately_from_account_id(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Web", account_id="account-1", model="GPT-5.6 Sol", provider_id="chatgpt_web")
    assert conv["account_id"] == "account-1"
    assert conv["provider_id"] == "chatgpt_web"


def test_legacy_conversation_schema_gets_provider_id_migration(tmp_path):
    db = tmp_path / "chat.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, account_id TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    connection.execute("INSERT INTO conversations VALUES ('legacy', 'Legacy', 'openrouter', 'openrouter/free', 'now', 'now')")
    connection.commit()
    connection.close()

    store = ChatStore(db, tmp_path / "attachments")
    assert store.get_conversation("legacy")["provider_id"] == "openrouter"


def test_chat_store_migrates_old_conversation_schema_without_reordering_fields(tmp_path):
    db = tmp_path / "chat.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, account_id TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    connection.commit()
    connection.close()

    store = ChatStore(db, tmp_path / "attachments")
    conv = store.create_conversation("Migrated")
    assert conv["provider_thread_url"] == ""
    assert conv["created_at"]
    assert conv["updated_at"]


def test_attachment_filename_cannot_escape_conversation(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Files")
    with pytest.raises(ValueError):
        store.save_attachment(conv["id"], "../secret.txt", b"no")


def test_account_payload_never_contains_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_CLONE_DATA", str(tmp_path))
    from pipeline.chat.service import ChatService

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    payload = json.dumps(service.list_accounts())
    assert "apiKey" not in payload
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_v1_rejects_tool_execution(tmp_path):
    from pipeline.chat.service import ChatService

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    with pytest.raises(ValueError, match="Tool execution"):
        service.validate_prompt({"content": "run", "toolCall": {"name": "flow"}})


def test_chat_modes_are_explicit_and_unknown_modes_are_rejected(tmp_path):
    from pipeline.chat.browser import ChatBrowserManager
    from pipeline.chat.service import ChatService

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    assert ChatBrowserManager.mode_pattern("search").search("Search the web")
    assert ChatBrowserManager.mode_pattern("research").search("Nghiên cứu sâu")
    assert ChatBrowserManager.mode_pattern("image").search("Create image")
    assert ChatBrowserManager.mode_error("image") == "CHAT_BROWSER_MODE_IMAGE_UNAVAILABLE"
    with pytest.raises(ValueError, match="Unsupported chat mode"):
        service.validate_prompt({"content": "make this", "mode": "video"})


def test_browser_selects_a_visible_requested_tool_or_reports_it_unavailable(tmp_path):
    import asyncio
    from pipeline.chat.browser import ChatBrowserManager

    class EmptyLocator:
        async def count(self): return 0

    class Tool:
        clicked = False
        async def is_visible(self): return True
        async def click(self, **_kwargs): self.clicked = True

    class ToolLocator:
        def __init__(self, tool): self.tool = tool
        async def count(self): return 1
        def nth(self, _index): return self.tool

    tool = Tool()
    class ToolPage:
        def get_by_role(self, role, **_kwargs): return ToolLocator(tool) if role == "menuitem" else EmptyLocator()

    manager = ChatBrowserManager("account", tmp_path / "profile", "chrome")
    asyncio.run(manager._activate_mode(ToolPage(), "image"))
    assert tool.clicked is True

    class Keyboard:
        async def press(self, _key): pass

    class EmptyPage:
        keyboard = Keyboard()
        def get_by_role(self, *_args, **_kwargs): return EmptyLocator()
        def locator(self, *_args, **_kwargs): return EmptyLocator()

    with pytest.raises(RuntimeError, match="CHAT_BROWSER_MODE_RESEARCH_UNAVAILABLE"):
        asyncio.run(manager._activate_mode(EmptyPage(), "research"))


def test_renaming_a_conversation_trims_title_and_keeps_a_valid_name(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = store.create_conversation("Original")

    renamed = store.update_conversation(conversation["id"], title="  New title  ")
    unchanged = store.update_conversation(conversation["id"], title="   ")

    assert renamed["title"] == "New title"
    assert unchanged["title"] == "New title"


class _MemorySecrets:
    value = None
    def load(self): return self.value
    def save(self, value): self.value = value
    def delete(self): self.value = None


class _Response:
    def __init__(self, data, status=200): self.data, self.status_code = data, status
    def json(self): return self.data
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class _OAuthClient:
    def __init__(self): self.poll_count = 0
    def post(self, url, **kwargs):
        if url.endswith("/deviceauth/usercode"):
            return _Response({"device_auth_id": "dev", "user_code": "ABCD-EFGH", "interval": 2})
        if url.endswith("/deviceauth/token"):
            self.poll_count += 1
            return _Response({}, 403) if self.poll_count == 1 else _Response({"authorization_code": "code", "code_verifier": "verifier", "code_challenge": "challenge"})
        return _Response({"access_token": "header.payload.sig", "refresh_token": "refresh", "expires_in": 3600})


def test_device_login_pending_then_saves_tokens_only_in_secret_store():
    from pipeline.chat.auth import ChatGPTAuth
    secrets = _MemorySecrets()
    auth = ChatGPTAuth(token_store=secrets, client=_OAuthClient())
    login = auth.start_login(open_browser=False)
    assert "token" not in json.dumps(login).lower()
    assert auth.poll(login["loginId"])["status"] == "pending"
    assert auth.poll(login["loginId"])["status"] == "connected"
    assert secrets.value["refresh_token"] == "refresh"
    assert "refresh_token" not in json.dumps(auth.status())


def test_multiple_accounts_keep_distinct_profiles_and_hide_paths(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    first = store.create_account("Work", "chrome", tmp_path / "profiles" / "one")
    second = store.create_account("Personal", "edge", tmp_path / "profiles" / "two")
    assert first["id"] != second["id"]
    public = store.list_accounts(public=True)
    assert {item["browser_family"] for item in public} == {"chrome", "edge"}
    assert "profile_path" not in json.dumps(public)


def test_attachment_limits_mime_and_message_link(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Files")
    message = store.create_message(conv["id"], "user", "read this")
    saved = store.save_attachment(conv["id"], "notes.txt", b"hello", message_id=message["id"], content_type="text/plain")
    assert saved["message_id"] == message["id"]
    assert store.list_attachments(conv["id"])[0]["content_type"] == "text/plain"
    with pytest.raises(ValueError, match="type"):
        store.save_attachment(conv["id"], "payload.exe", b"MZ", content_type="application/octet-stream")


def test_attachment_uses_extension_when_browser_reports_generic_mime(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Timeline")

    saved = store.save_attachment(conv["id"], "captions.srt", b"1\n00:00:00,000 --> 00:00:01,000\nHello", content_type="application/octet-stream")

    assert saved["content_type"] in {"application/x-subrip", "text/plain"}


def test_browser_discovery_order(monkeypatch, tmp_path):
    from pipeline.chat.browser import discover_browser
    candidates = {"chrome": tmp_path / "chrome", "edge": tmp_path / "edge", "brave": tmp_path / "brave"}
    candidates["edge"].write_text("")
    candidates["brave"].write_text("")
    monkeypatch.setattr("pipeline.chat.browser.browser_candidates", lambda: candidates)
    assert discover_browser()[0] == "edge"


def test_browser_login_process_is_detached_from_app(monkeypatch, tmp_path):
    import pipeline.chat.browser as browser

    executable = tmp_path / "chrome"
    executable.write_text("")
    monkeypatch.setattr(browser, "discover_browser", lambda _preferred=None: ("chrome", executable))
    calls = {}
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *args, **kwargs: calls.update(kwargs))
    browser.open_profile_url(tmp_path / "profile", "chrome", "https://chatgpt.com/")
    if os.name == "nt":
        assert calls["creationflags"]
    else:
        assert calls["start_new_session"] is True


def test_closed_chat_window_is_not_reported_as_profile_locked(tmp_path, monkeypatch):
    import asyncio
    from pipeline.chat.browser import ChatBrowserManager

    manager = ChatBrowserManager("account", tmp_path / "profile", "chrome")

    async def closed_window_start(*, headless=False):
        raise RuntimeError("CHAT_BROWSER_WINDOW_CLOSED")

    monkeypatch.setattr(manager, "start", closed_window_start)
    result = asyncio.run(manager.health())

    assert result["status"] == "browser_only"
    assert result["errorCode"] == "CHAT_BROWSER_WINDOW_CLOSED"


def test_service_preserves_closed_window_state_without_profile_lock_message(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")

    class Browser:
        async def health(self):
            raise RuntimeError("CHAT_BROWSER_WINDOW_CLOSED")

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", lambda *args: Browser())
    result = ChatService(store=store).browser_health(account["id"])

    assert result["status"] == "browser_only"
    assert result["errorCode"] == "CHAT_BROWSER_WINDOW_CLOSED"


def test_debug_target_detection_ignores_chrome_internal_targets():
    from pipeline.chat.browser import _has_page_target

    assert _has_page_target([{"type": "browser_ui", "url": "chrome://newtab"}]) is False
    assert _has_page_target([{"type": "page", "url": "https://chatgpt.com/"}]) is True


def test_attachment_cannot_be_attached_across_conversations(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    first = store.create_conversation("One")
    second = store.create_conversation("Two")
    attachment = store.save_attachment(first["id"], "notes.txt", b"hello", content_type="text/plain")
    message = store.create_message(second["id"], "user", "steal")
    with pytest.raises(ValueError, match="belong"):
        store.attach_to_message(second["id"], message["id"], [attachment["id"]])


def test_send_message_rejects_invalid_attachment_before_opening_sse(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.chat as route
    from pipeline.core import license as license_module

    local_store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = local_store.create_conversation("Files", account_id="openrouter", model="openrouter/free")
    attachment = local_store.save_attachment(conversation["id"], "note.txt", b"hello", content_type="text/plain")
    other = local_store.create_conversation("Other")
    service = __import__("pipeline.chat.service", fromlist=["ChatService"]).ChatService(store=local_store)
    monkeypatch.setattr(route, "service", service)
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)

    response = TestClient(create_app()).post(
        f"/api/chat/conversations/{other['id']}/messages",
        json={"content": "read", "attachmentIds": [attachment["id"]]},
    )

    assert response.status_code == 400
    assert "conversation" in response.text.lower() or "belong" in response.text.lower()


def test_conversation_route_returns_provider_id_and_separate_account_id(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.chat as route
    from pipeline.core import license as license_module

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    service = __import__("pipeline.chat.service", fromlist=["ChatService"]).ChatService(store=store)
    monkeypatch.setattr(route, "service", service)
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)

    response = TestClient(create_app()).post(
        "/api/chat/conversations",
        json={"title": "Web", "provider": "chatgpt_web", "accountId": "account-1", "model": "GPT-5.6 Sol"},
    )

    assert response.status_code == 200
    assert response.json()["provider_id"] == "chatgpt_web"
    assert response.json()["account_id"] == "account-1"


def test_refresh_rotation_is_single_flight():
    from pipeline.chat.auth import ChatGPTAuth
    secrets = _MemorySecrets()
    secrets.value = {"access_token": "old", "refresh_token": "refresh", "expires_at": 0}
    class Client:
        calls = 0
        def post(self, *_args, **_kwargs):
            self.calls += 1
            time.sleep(.02)
            return _Response({"access_token": "new", "refresh_token": "rotated", "expires_in": 3600})
    client = Client(); auth = ChatGPTAuth(token_store=secrets, client=client)
    results = []
    threads = [threading.Thread(target=lambda: results.append(auth.tokens()["access_token"])) for _ in range(5)]
    [thread.start() for thread in threads]; [thread.join() for thread in threads]
    assert results == ["new"] * 5
    assert client.calls == 1


def test_attachment_rejects_spoofed_image_mime(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Files")
    with pytest.raises(ValueError, match="content"):
        store.save_attachment(conv["id"], "fake.png", b"not an image", content_type="image/png")


def test_chatgpt_generated_file_button_allows_only_safe_supported_artifacts():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.artifact_file_info("audio_script_30_ngay_song_nhu_nguoi_tien_su.txt") == (
        "audio_script_30_ngay_song_nhu_nguoi_tien_su.txt",
        "text/plain",
    )
    assert ChatBrowserManager.artifact_file_info("notes.MD") == ("notes.MD", "text/markdown")
    assert ChatBrowserManager.artifact_file_info("../secret.txt") is None
    assert ChatBrowserManager.artifact_file_info("script.exe") is None


def test_chatgpt_conversation_url_is_an_active_session_while_library_is_open():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.is_active_conversation_url("https://chatgpt.com/c/abc-123") is True
    assert ChatBrowserManager.is_active_conversation_url("https://chatgpt.com/share/abc-123") is False


def test_browser_does_not_reuse_temporary_web_thread_url():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.is_temporary_thread_url("https://chatgpt.com/c/WEB:abc-123") is True
    assert ChatBrowserManager.is_temporary_thread_url("https://chatgpt.com/c/abc-123") is False


def test_browser_submit_button_pattern_supports_localized_file_composer():
    from pipeline.chat.browser import ChatBrowserManager

    pattern = ChatBrowserManager.send_button_pattern()
    assert pattern.search("Gửi câu lệnh")
    assert pattern.search("Send prompt")


def test_browser_detects_replaced_assistant_turn_with_same_text():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.assistant_turn_changed(1, 1, "new-id", {"old-id"}, "Download file TXT", "Download file TXT") is True


def test_chatgpt_generated_artifact_rejects_an_empty_download():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.has_generated_file_content(b"script") is True
    assert ChatBrowserManager.has_generated_file_content(b"") is False


def test_unknown_account_is_not_silently_treated_as_openai(tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Missing", account_id="deleted-account")
    service = ChatService(store=store)
    events = "".join(service.stream_message(conv["id"], {"content": "hello"}))
    assert "ACCOUNT_NOT_FOUND" in events
    assert "fallback.required" not in events


def test_chatgpt_account_chat_uses_web_session_and_selected_model(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    conv = store.create_conversation("Web chat", account_id=account["id"], model="gpt-web-model")
    store.update_conversation(conv["id"], provider_thread_url="https://chatgpt.com/c/existing-thread")
    calls = {}

    class Browser:
        def __init__(self, account_id, profile, family):
            calls["account_id"], calls["profile"], calls["family"] = account_id, profile, family

        async def run(self, prompt, mode, files, cancel, model, thread_url="", on_delta=None):
            calls["model"] = model
            calls["thread_url"] = thread_url
            return {"content": "web answer", "thread_url": "https://chatgpt.com/c/1", "artifacts": []}

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    events = "".join(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    assert "web answer" in events
    assert calls == {"account_id": account["id"], "profile": __import__("pathlib").Path(account["profile_path"]), "family": "chrome", "model": "gpt-web-model", "thread_url": "https://chatgpt.com/c/existing-thread"}


def test_browser_chat_forwards_incremental_deltas(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    conv = store.create_conversation("Web chat", account_id=account["id"])

    class Browser:
        def __init__(self, *_args):
            pass

        async def run(self, *_args, on_delta=None, **_kwargs):
            if on_delta:
                on_delta("first ")
                on_delta("second")
            return {"content": "first second", "thread_url": "", "artifacts": []}

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    events = list(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    deltas = [line for event in events if event.startswith("event: content.delta") for line in event.splitlines() if line.startswith("data:")]
    assert len(deltas) == 2
    assert '"delta": "first "' in deltas[0]
    assert '"delta": "second"' in deltas[1]


def test_browser_chat_uses_saved_model_for_legacy_conversation(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected", last_model="GPT-5.5")
    conv = store.create_conversation("Legacy chat", account_id=account["id"], model="")
    seen = {}

    class Browser:
        def __init__(self, *_args):
            pass

        async def run(self, _prompt, _mode, _files, _cancel, model, _thread_url="", on_delta=None):
            seen["model"] = model
            return {"content": "ok", "thread_url": "", "artifacts": []}

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    list(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    assert seen["model"] == "GPT-5.5"
    assert store.get_conversation(conv["id"])["model"] == "GPT-5.5"


def test_browser_chat_defaults_to_gpt_5_6_sol(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    conv = store.create_conversation("New chat", account_id=account["id"], model="")
    seen = {}

    class Browser:
        def __init__(self, *_args):
            pass

        async def run(self, _prompt, _mode, _files, _cancel, model, _thread_url="", on_delta=None):
            seen["model"] = model
            return {"content": "ok", "thread_url": "", "artifacts": []}

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    list(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    assert seen["model"] == "GPT-5.6 Sol"
    assert store.get_conversation(conv["id"])["model"] == "GPT-5.6 Sol"


def test_browser_chat_rejects_unauthenticated_profile_without_waiting(tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="browser_only")
    conv = store.create_conversation("Web chat", account_id=account["id"])
    events = "".join(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    assert "CHAT_BROWSER_NOT_AUTHENTICATED" in events
    assert "CHAT_BROWSER_NO_OUTPUT" not in events


def test_expired_browser_session_marks_account_for_reauthentication(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    conv = store.create_conversation("Web chat", account_id=account["id"])

    class Browser:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            raise RuntimeError("CHAT_BROWSER_NOT_AUTHENTICATED")

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    events = "".join(ChatService(store=store).stream_message(conv["id"], {"content": "hello"}))
    assert "CHAT_BROWSER_NOT_AUTHENTICATED" in events
    assert store.get_account(account["id"])["status"] == "reauth_required"


def test_web_model_discovery_extracts_supported_labels():
    from pipeline.chat.browser import ChatBrowserManager

    models = ChatBrowserManager._model_names(["GPT-5.5 Thinking", "GPT-5.5", "o3-mini", "o4-mini", "Settings"])
    assert models == ["GPT-5.5 Thinking", "GPT-5.5", "o3-mini", "o4-mini"]
    assert "GPT Business" not in ChatBrowserManager._model_names(["GPT Business của mạnhg"])


def test_browser_uses_web_default_for_gpt_5_6_sol_without_model_picker():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.requires_model_picker("GPT-5.6 Sol") is False
    assert ChatBrowserManager.requires_model_picker("gpt-5.6 sol") is False
    assert ChatBrowserManager.requires_model_picker("GPT-5.5") is True


def test_connected_web_session_keeps_default_model_when_picker_discovery_is_empty(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    service = ChatService(store=store)
    monkeypatch.setattr(service, "models", lambda _account_id: [])

    models = service.provider_models("chatgpt_web")

    assert models[0]["id"] == "GPT-5.6 Sol"
    assert models[0]["available"] is True


def test_browser_output_reader_detects_updated_last_assistant_without_new_node():
    import asyncio
    from pipeline.chat.browser import ChatBrowserManager

    class Item:
        def __init__(self, text):
            self.text = text

        async def is_visible(self):
            return True

        async def inner_text(self):
            return self.text

    class Locator:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    locator = Locator([Item("previous answer"), Item("new streamed answer")])
    count, text = asyncio.run(ChatBrowserManager._latest_assistant_text(locator))

    assert count == 2
    assert text == "new streamed answer"


def test_browser_final_text_keeps_streamed_text_when_dom_snapshot_is_empty():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager._final_text("", "📄 Tải file TXT lời thuyết minh") == "📄 Tải file TXT lời thuyết minh"


def test_browser_recognizes_localized_generated_file_card_without_filename():
    from pipeline.chat.browser import ChatBrowserManager

    assert ChatBrowserManager.is_generated_file_label("📄 Tải file TXT lời thuyết minh") is True
    assert ChatBrowserManager.is_generated_file_label("Attach file") is False


def test_service_drops_stale_workspace_label_from_model_choices(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], last_model="GPT Business")

    class Browser:
        def __init__(self, *_args, **_kwargs):
            pass

        async def models(self):
            return ["GPT-5.6 Sol", "GPT-5.5"]

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    assert ChatService(store=store).models(account["id"]) == ["GPT-5.6 Sol", "GPT-5.5"]


def test_service_exposes_only_one_web_account(tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    store.create_account("First", "chrome", tmp_path / "profiles" / "one")
    store.create_account("Second", "edge", tmp_path / "profiles" / "two")
    accounts = ChatService(store=store).list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["provider"] == "chatgpt_web"


def test_browser_login_pending_is_not_reported_as_connected(tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="browser_only")
    public = ChatService(store=store).list_accounts()[0]
    assert public["status"] == "browser_only"
    assert public["configured"] is False


def test_browser_discovery_and_health_do_not_launch_chromium_when_cdp_is_unavailable(tmp_path, monkeypatch):
    import asyncio
    import pipeline.chat.browser as browser
    from pipeline.chat.browser import ChatBrowserManager

    executable = tmp_path / "chrome"
    executable.write_text("")
    launch_calls = []

    class FakeChromium:
        async def launch_persistent_context(self, *args, **kwargs):
            launch_calls.append((args, kwargs))
            raise AssertionError("discovery must not launch a browser")

    class FakePlaywright:
        chromium = FakeChromium()

        async def start(self):
            return self

        async def stop(self):
            pass

    monkeypatch.setattr(browser, "discover_browser", lambda _preferred=None: ("chrome", executable))
    monkeypatch.setattr(browser, "_debug_targets", lambda _port: None)
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: FakePlaywright())

    manager = ChatBrowserManager("account", tmp_path / "profile", "chrome")
    with pytest.raises(RuntimeError, match="CHAT_BROWSER_WINDOW_CLOSED"):
        asyncio.run(manager.models())

    health = asyncio.run(manager.health())

    assert launch_calls == []
    assert health["status"] == "browser_only"
    assert health["errorCode"] == "CHAT_BROWSER_WINDOW_CLOSED"


def test_health_failure_is_reported_as_unavailable(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    class Browser:
        async def health(self):
            raise RuntimeError("profile locked")
    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", lambda *args: Browser())
    health = ChatService(store=store).browser_health(account["id"])
    assert health["status"] == "unavailable"
    assert health["errorCode"] == "CHAT_BROWSER_HEALTH_FAILED"


def test_concurrent_health_probe_does_not_downgrade_saved_session(tmp_path):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    service = ChatService(store=store)

    class BusyLock:
        def acquire(self, **_kwargs):
            return False

        def release(self):
            raise AssertionError("busy lock must not be released")

    service._health_locks[account["id"]] = BusyLock()
    result = service.browser_health(account["id"])
    assert result["errorCode"] == "CHAT_BROWSER_BUSY"
    assert store.get_account(account["id"])["status"] == "connected"


def test_cancelled_browser_generation_finishes_as_interrupted_not_failed(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    account = store.create_account("Web", "chrome", tmp_path / "profiles" / "web")
    store.update_account(account["id"], status="connected")
    conv = store.create_conversation("Stop", account_id=account["id"])

    class Browser:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run(self, _prompt, _mode, _files, cancel, *_args, **_kwargs):
            assert cancel.is_set()
            raise RuntimeError("CHAT_BROWSER_CANCELLED")

    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", Browser)
    service = ChatService(store=store)
    stream = service.stream_message(conv["id"], {"content": "long request"})
    assert "message.started" in next(stream)
    assert service.cancel(conv["id"]) is True
    events = "".join(stream)

    assert 'event: message.completed' in events
    assert '"status": "interrupted"' in events
    assert 'event: message.failed' not in events
    assert store.list_messages(conv["id"])[-1]["status"] == "interrupted"


def test_api_provider_stream_does_not_require_chatgpt_browser(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService

    store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conv = store.create_conversation("Groq", account_id="groq", model="openai/gpt-oss-20b", provider_id="groq")

    class FakeProvider:
        def stream(self, _model, _messages, _cancel, attachments=None):
            assert attachments == []
            yield "ok"

    def fail_if_browser_is_used(*_args, **_kwargs):
        raise AssertionError("API chat must not open ChatGPT Web")

    service = ChatService(store=store)
    monkeypatch.setattr(service, "resolve_provider", lambda provider, model: (provider, model, {"id": model, "capabilities": ["text"]}))
    monkeypatch.setattr(service, "_api_provider", lambda _provider: FakeProvider())
    monkeypatch.setattr("pipeline.chat.service.ChatBrowserManager", fail_if_browser_is_used)
    events = list(service.stream_message(conv["id"], {"content": "hello", "provider": "groq", "model": "openai/gpt-oss-20b"}))
    assert any('event: message.completed' in event and '"content": "ok"' in event for event in events)
