from __future__ import annotations

import json

import pytest

from pipeline.chat.service import ChatService
from pipeline.chat.providers import (
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderError,
    normalize_model,
)


def test_openrouter_free_models_are_marked_and_paid_models_are_hidden():
    free = normalize_model("openrouter", {"id": "qwen/qwen3-8b:free", "pricing": {"prompt": "0", "completion": "0"}})
    priced = normalize_model("openrouter", {"id": "openai/gpt-4o", "pricing": {"prompt": "0.005", "completion": "0.015"}})
    assert free["free"] is True
    assert priced["free"] is False
    assert normalize_model("openrouter", {"id": "Qwen/Qwen3:FREE"})["free"] is True


def test_nvidia_is_available_as_a_chat_provider():
    from pipeline.chat.providers import API_PROVIDER_IDS, PROVIDER_LABELS

    assert "nvidia" in API_PROVIDER_IDS
    assert PROVIDER_LABELS["nvidia"] == "NVIDIA NIM"
    assert normalize_model("nvidia", {"id": "meta/llama-3.1-8b-instruct"})["free"] is True
    assert normalize_model("openrouter", {"id": "free-metadata", "pricing": {"prompt": "$0", "completion": "0"}})["free"] is True


def test_gemini_free_allowlist_is_conservative():
    assert normalize_model("gemini", {"name": "models/gemini-2.5-flash-lite"})["free"] is True
    assert normalize_model("gemini", "models/gemini-2.5-flash-lite")["id"] == "gemini-2.5-flash-lite"
    assert normalize_model("gemini", "models/gemini-2.5-flash-lite")["free"] is True
    assert normalize_model("gemini", {"name": "models/gemini-unknown-pro"})["free"] is False


def test_gemini_specialized_models_are_not_listed_as_free_text_chat_models():
    for model_id in (
        "gemini-2.5-flash-image",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-3.1-flash-image-preview",
    ):
        item = normalize_model("gemini", {"name": f"models/{model_id}"})
        assert item["free"] is False, model_id


def test_gemini_provider_catalog_only_returns_standard_text_chat_models(tmp_path, monkeypatch):
    from pipeline.chat.store import ChatStore

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))

    class Catalog:
        def model_records(self, **_kwargs):
            return [
                normalize_model("gemini", {"name": "models/gemini-2.5-flash"}),
                normalize_model("gemini", {"name": "models/gemini-2.5-flash-image"}),
                normalize_model("gemini", {"name": "models/gemini-2.5-flash-preview-tts"}),
            ]

    monkeypatch.setattr(service, "_api_provider", lambda _provider: Catalog())
    models = service.provider_models("gemini", refresh=True)
    assert [item["id"] for item in models] == ["gemini-2.5-flash"]


def test_grok_without_zero_pricing_is_not_free():
    model = normalize_model("grok", {"id": "grok-4.6"})
    assert model["free"] is False
    assert "free" in model["reason"].lower()


def test_grok_developer_model_is_available_when_catalog_omits_pricing():
    model = normalize_model("grok", {"id": "grok-3-mini"})
    assert model["free"] is True


def test_gemini_flash_and_gemma_families_are_available_on_free_tier():
    for model_id in ("gemini-flash-latest", "gemini-3.8-flash", "gemma-4-31b-it"):
        assert normalize_model("gemini", {"name": f"models/{model_id}"})["free"] is True


def test_groq_catalog_models_are_available_for_configured_key():
    free = normalize_model("groq", {"id": "openai/gpt-oss-20b"})
    unknown = normalize_model("groq", {"id": "some-paid-or-unknown-model"})
    unknown_zero_price = normalize_model(
        "groq",
        {"id": "some-unknown-model", "pricing": {"prompt": "0", "completion": "0"}},
    )
    assert free["free"] is True
    assert unknown["free"] is True
    assert unknown_zero_price["free"] is True


def test_groq_is_a_first_class_cloud_provider():
    from pipeline.core.app_config import PROVIDERS, _default_cloud

    assert "groq" in PROVIDERS
    assert _default_cloud()["groq"]["baseUrl"] == "https://api.groq.com/openai/v1"


def test_openai_compatible_model_discovery_rotates_to_a_valid_configured_key(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url, headers):
            calls.append(headers["Authorization"])
            return _Response(
                {"data": [{"id": "openai/gpt-oss-20b"}]},
                status_code=401 if len(calls) == 1 else 200,
            )

    monkeypatch.setattr("httpx.Client", Client)
    provider = OpenAICompatibleProvider(
        "groq", "stale-key", "https://example.test/v1", ["stale-key", "working-key"]
    )
    models = provider.model_records()
    assert models[0]["id"] == "openai/gpt-oss-20b"
    assert calls == ["Bearer stale-key", "Bearer working-key"]
    assert provider.api_key == "working-key"


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_openai_compatible_stream_normalizes_content_and_redacts_errors(monkeypatch):
    class StreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Xin "}}]}'
            yield 'data: {"choices":[{"delta":{"content":"chào"}}]}'
            yield "data: [DONE]"

    monkeypatch.setattr("httpx.stream", lambda *_args, **_kwargs: StreamResponse())
    provider = OpenAICompatibleProvider("openrouter", "secret", "https://example.test/v1")
    assert "".join(provider.stream("qwen/qwen3-8b:free", [{"role": "user", "content": "hi"}], __import__("threading").Event())) == "Xin chào"


def test_openai_compatible_stream_rotates_key_before_first_chunk(monkeypatch):
    calls = []

    class StreamResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield "data: [DONE]"

    def stream(_method, _url, headers, **_kwargs):
        calls.append(headers["Authorization"])
        return StreamResponse(401 if len(calls) == 1 else 200)

    monkeypatch.setattr("httpx.stream", stream)
    provider = OpenAICompatibleProvider("groq", "stale-key", "https://example.test/v1", ["stale-key", "working-key"])
    assert "".join(provider.stream("openai/gpt-oss-20b", [{"role": "user", "content": "hi"}], __import__("threading").Event())) == "ok"
    assert calls == ["Bearer stale-key", "Bearer working-key"]
    assert provider.api_key == "working-key"


def test_openai_compatible_stream_events_preserves_reasoning_chunks(monkeypatch):
    class StreamResponse:
        status_code = 200

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"answer"}}]}'
            yield "data: [DONE]"

    monkeypatch.setattr("httpx.stream", lambda *_args, **_kwargs: StreamResponse())
    provider = OpenAICompatibleProvider("openrouter", "secret", "https://example.test/v1")
    events = list(provider.stream_events("qwen/qwen3-8b:free", [{"role": "user", "content": "hi"}], __import__("threading").Event()))
    assert events == [("reasoning.delta", "think"), ("content.delta", "answer")]


def test_openai_compatible_stream_events_keeps_usage_metadata(monkeypatch):
    class StreamResponse:
        status_code = 200

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"answer"}}]}'
            yield 'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}'
            yield "data: [DONE]"

    monkeypatch.setattr("httpx.stream", lambda *_args, **_kwargs: StreamResponse())
    provider = OpenAICompatibleProvider("openrouter", "secret", "https://example.test/v1")
    list(provider.stream_events("qwen/qwen3-8b:free", [{"role": "user", "content": "hi"}], __import__("threading").Event()))
    assert provider.last_usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


def test_gemini_stream_parses_sse_chunks(monkeypatch):
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            class Response:
                status_code = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def raise_for_status(self):
                    return None

                def iter_lines(self):
                    yield 'data: {"candidates":[{"content":{"parts":[{"text":"A"}]}}]}'
                    yield 'data: {"candidates":[{"content":{"parts":[{"text":"B"}]}}]}'

            return Response()

    monkeypatch.setattr("httpx.Client", lambda **_kwargs: Client())
    provider = GeminiProvider("gemini", "secret", "https://example.test/v1beta")
    assert "".join(provider.stream("gemini-2.5-flash-lite", [{"role": "user", "content": "hi"}], __import__("threading").Event())) == "AB"


def test_gemini_stream_keeps_usage_metadata(monkeypatch):
    class Client:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def stream(self, *_args, **_kwargs):
            class Response:
                status_code = 200

                def __enter__(self): return self
                def __exit__(self, *_args): return False
                def iter_lines(self):
                    yield 'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}],"usageMetadata":{"promptTokenCount":4,"candidatesTokenCount":3,"totalTokenCount":7}}'

            return Response()

    monkeypatch.setattr("httpx.Client", lambda **_kwargs: Client())
    provider = GeminiProvider("gemini", "secret", "https://example.test/v1beta")
    list(provider.stream("gemini-2.5-flash-lite", [{"role": "user", "content": "hi"}], __import__("threading").Event()))
    assert provider.last_usage == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}


def test_provider_error_has_stable_code_without_secret():
    error = ProviderError("CHAT_PROVIDER_HTTP_429", "secret should not be here")
    assert error.code == "CHAT_PROVIDER_HTTP_429"
    assert "secret" not in error.safe_message("secret")


def test_provider_catalog_contains_only_public_metadata(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService
    from pipeline.chat.store import ChatStore

    monkeypatch.setattr(
        "pipeline.chat.service.load_app_config",
            lambda: {"cloud": {pid: {"apiKey": "key"} for pid in ("openai", "gemini", "deepseek", "openrouter", "grok", "groq", "nvidia")}},
    )
    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    monkeypatch.setattr(service, "provider_models", lambda pid, **_kwargs: [{"id": "openrouter/free", "label": "Free", "provider": pid, "free": True, "capabilities": ["text"], "available": True, "reason": "free"}] if pid == "openrouter" else [])
    payload = service.providers()
    assert next(item for item in payload if item["id"] == "openrouter")["status"] == "ready"
    assert "key" not in json.dumps(payload)


def test_provider_catalog_keeps_chatgpt_web_login_visible_before_account_exists(tmp_path, monkeypatch):
    from pipeline.chat.store import ChatStore

    monkeypatch.setattr(
        "pipeline.chat.service.load_app_config",
        lambda: {"cloud": {pid: {"apiKey": ""} for pid in ("openai", "gemini", "deepseek", "openrouter", "grok", "groq", "nvidia")}},
    )
    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    web = service.providers()[0]
    assert web["id"] == "chatgpt_web"
    assert web["configured"] is False
    assert web["status"] == "signed_out"
    assert web["loginRequired"] is True


def test_openrouter_free_router_survives_model_list_network_failure(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService
    from pipeline.chat.store import ChatStore

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))

    class OfflineProvider:
        def model_records(self, **_kwargs):
            raise ProviderError("CHAT_PROVIDER_MODELS_UNAVAILABLE", "temporary network failure")

    monkeypatch.setattr(service, "_api_provider", lambda _provider: OfflineProvider())
    models = service.provider_models("openrouter")

    assert models[0]["id"] == "openrouter/free"


def test_gemini_stream_accepts_text_attachment_in_history():
    provider = GeminiProvider("gemini", "secret", "https://example.test/v1beta")
    parts = provider._parts("[captions.srt]\n00:00:00,000 --> 00:00:01,000")
    assert parts == [{"text": "[captions.srt]\n00:00:00,000 --> 00:00:01,000"}]


def test_openai_compatible_attachments_keep_audio_parts():
    content = OpenAICompatibleProvider._append_openai_attachments(
        "listen",
        [{"content_type": "audio/wav", "data": "AQI="}],
    )
    assert content == [
        {"type": "text", "text": "listen"},
        {"type": "input_audio", "input_audio": {"data": "AQI=", "format": "wav"}},
    ]


def test_stream_starts_with_selected_provider_and_model(tmp_path, monkeypatch):
    from pipeline.chat.service import ChatService
    from pipeline.chat.store import ChatStore

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    conversation = service.store.create_conversation("Provider", "openrouter", "openrouter/free")

    class FakeProvider:
        def stream(self, _model, _messages, _cancel, attachments=None):
            assert attachments == []
            yield "ok"

    monkeypatch.setattr(service, "resolve_provider", lambda provider, model: (provider, model, {"id": model, "capabilities": ["text"]}))
    monkeypatch.setattr(service, "_api_provider", lambda _provider: FakeProvider())
    first = next(service.stream_message(conversation["id"], {"content": "hello", "provider": "openrouter", "model": "openrouter/free"}))
    assert 'event: message.started' in first
    assert '"provider": "openrouter"' in first
    assert '"model": "openrouter/free"' in first


def test_chat_providers_route_returns_catalog(monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.chat as route
    from pipeline.core import license as license_module

    class FakeService:
        def providers(self, **_kwargs):
            return [{"id": "openrouter", "label": "OpenRouter", "kind": "api", "configured": True, "status": "ready", "models": [{"id": "openrouter/free", "free": True, "capabilities": ["text"]}]}]

    monkeypatch.setattr(route, "service", FakeService())
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)
    response = TestClient(create_app()).get("/api/chat/providers")
    assert response.status_code == 200
    assert response.json()["providers"][0]["models"][0]["free"] is True


def test_chat_models_route_without_provider_returns_all_provider_models(monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.chat as route
    from pipeline.core import license as license_module

    class FakeService:
        def providers(self, **_kwargs):
            return [
                {"id": "chatgpt_web", "models": []},
                {"id": "gemini", "models": [{"id": "gemini-3-flash", "provider": "gemini", "free": True}]},
                {"id": "nvidia", "models": [{"id": "meta/llama", "provider": "nvidia", "free": True}]},
            ]

    monkeypatch.setattr(route, "service", FakeService())
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)
    response = TestClient(create_app()).get("/api/chat/models")
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["models"]] == ["gemini", "nvidia"]


def test_provider_model_cache_can_be_cleared_after_credentials_change():
    service = ChatService()
    service._model_cache["openrouter"] = (0.0, [{"id": "stale"}])
    service.clear_model_cache()
    assert service._model_cache == {}


def test_groq_and_nvidia_keep_selectable_fallback_when_model_catalog_is_temporarily_unavailable(tmp_path, monkeypatch):
    from pipeline.chat.store import ChatStore

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))

    class OfflineProvider:
        def model_records(self, **_kwargs):
            raise ProviderError("CHAT_PROVIDER_MODELS_UNAVAILABLE", "temporary outage")

    monkeypatch.setattr(service, "_api_provider", lambda _provider: OfflineProvider())
    assert service.provider_models("groq")[0]["free"] is True
    assert service.provider_models("nvidia")[0]["free"] is True


def test_groq_and_nvidia_keep_selectable_fallback_when_catalog_has_no_free_metadata(tmp_path, monkeypatch):
    from pipeline.chat.store import ChatStore

    service = ChatService(store=ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments"))
    monkeypatch.setattr(service, "_api_provider", lambda _provider: type("Provider", (), {"model_records": lambda _self, **_kwargs: [{"id": "catalog-model", "free": False}]})())
    assert service.provider_models("groq")[0]["id"] == "llama-3.3-70b-versatile"
    assert service.provider_models("nvidia")[0]["id"] == "meta/llama-3.1-8b-instruct"
