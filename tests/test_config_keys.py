from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from api.deps import AppConfigIn, ElevenLabsBlock
from api.app import create_app
import pipeline.core.app_config as app_config

app = create_app()


@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    cfg_file = tmp_path / "app_config.json"
    monkeypatch.setattr(app_config, "_CONFIG_PATH", cfg_file)
    monkeypatch.delenv("ELEVENLABS_API_KEYS", raising=False)
    return cfg_file


def test_delete_elevenlabs_single_saved_key(temp_config_path):
    # 1. Start with 1 saved key
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_test_12345"}}})
    cfg = app_config.public_app_config()
    assert cfg["tts"]["elevenlabs"]["apiKeySet"] is True
    assert cfg["tts"]["elevenlabs"]["keyCount"] == 1

    # 2. Delete the key by passing empty keys list (user clicked × on the only slot)
    app_config.save_app_config({"tts": {"elevenlabs": {"keys": []}}})
    cfg = app_config.public_app_config()
    assert cfg["tts"]["elevenlabs"]["apiKeySet"] is False
    assert cfg["tts"]["elevenlabs"]["keyCount"] == 0
    assert cfg["tts"]["elevenlabs"]["apiKeys"] == ""


def test_preserve_and_delete_specific_elevenlabs_slot(temp_config_path):
    # 1. Start with 2 saved keys
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_key_A, sk_key_B"}}})
    raw_cfg = app_config.load_app_config()
    assert raw_cfg["tts"]["elevenlabs"]["apiKeys"] == "sk_key_A, sk_key_B"

    # 2. User removes slot 0 (sk_key_A), keeping slot 1 (sk_key_B)
    app_config.save_app_config({"tts": {"elevenlabs": {"keys": ["__keep:1__"]}}})
    raw_cfg = app_config.load_app_config()
    assert raw_cfg["tts"]["elevenlabs"]["apiKeys"] == "sk_key_B"
    cfg = app_config.public_app_config()
    assert cfg["tts"]["elevenlabs"]["keyCount"] == 1
    assert cfg["tts"]["elevenlabs"]["apiKeySet"] is True


def test_replace_slot_and_keep_other_slot(temp_config_path):
    # 1. Start with 2 saved keys
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_key_A, sk_key_B"}}})

    # 2. Replace slot 0 with new key, keep slot 1
    app_config.save_app_config({"tts": {"elevenlabs": {"keys": ["sk_new_A", "__keep:1__"]}}})
    raw_cfg = app_config.load_app_config()
    assert raw_cfg["tts"]["elevenlabs"]["apiKeys"] == "sk_new_A, sk_key_B"


def test_api_save_config_endpoint_deletes_key(temp_config_path):
    # 1. Setup existing key
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_existing_key"}}})
    client = TestClient(app)

    # 2. Call /api/config with empty keys array
    res = client.post(
        "/api/config",
        json={"tts": {"elevenlabs": {"keys": []}}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["tts"]["elevenlabs"]["apiKeySet"] is False
    assert data["tts"]["elevenlabs"]["keyCount"] == 0
    assert data["tts"]["elevenlabs"]["apiKeys"] == ""


def test_clear_via_empty_apikeys_string(temp_config_path):
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_test_legacy"}}})
    assert app_config.public_app_config()["tts"]["elevenlabs"]["apiKeySet"] is True

    # Empty string via legacy apiKeys field clears it
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": ""}}})
    cfg = app_config.public_app_config()
    assert cfg["tts"]["elevenlabs"]["apiKeySet"] is False
    assert cfg["tts"]["elevenlabs"]["keyCount"] == 0


def test_omitted_tts_preserves_elevenlabs_keys(temp_config_path):
    app_config.save_app_config({"tts": {"elevenlabs": {"apiKeys": "sk_persisted_key"}}})
    client = TestClient(app)

    # Calling save without tts field (e.g. only saving cloud settings)
    res = client.post(
        "/api/config",
        json={"cloud": {"openai": {"model": "gpt-4o"}}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["tts"]["elevenlabs"]["apiKeySet"] is True
    assert data["tts"]["elevenlabs"]["keyCount"] == 1


def test_cloud_keys_slot_preservation_and_deletion(temp_config_path):
    # 1. Start with 2 saved keys for gemini
    app_config.save_app_config({"cloud": {"gemini": {"apiKeys": "AQ_key_1, AQ_key_2"}}})
    raw_cfg = app_config.load_app_config()
    assert raw_cfg["cloud"]["gemini"]["apiKeys"] == "AQ_key_1, AQ_key_2"

    # 2. Remove slot 0, keeping slot 1
    app_config.save_app_config({"cloud": {"gemini": {"keys": ["__keep:1__"]}}})
    raw_cfg = app_config.load_app_config()
    assert raw_cfg["cloud"]["gemini"]["apiKeys"] == "AQ_key_2"
    assert raw_cfg["cloud"]["gemini"]["apiKey"] == "AQ_key_2"

    # 3. Clear all keys
    app_config.save_app_config({"cloud": {"gemini": {"keys": []}}})
    cfg = app_config.public_app_config()
    assert cfg["cloud"]["gemini"]["apiKeySet"] is False
    assert cfg["cloud"]["gemini"]["keyCount"] == 0
    assert cfg["cloud"]["gemini"]["apiKey"] == ""


def test_public_app_config_exposes_raw_keys(temp_config_path):
    app_config.save_app_config({
        "cloud": {"openai": {"apiKeys": "sk-real-secret-1, sk-real-secret-2"}},
        "tts": {"elevenlabs": {"apiKeys": "el-raw-key-1"}},
    })
    cfg = app_config.public_app_config()
    # Masked string for legacy/safe display
    assert "sk-real-secret-1" not in cfg["cloud"]["openai"]["apiKeys"]
    # rawKeys list for eye visibility reveal
    assert cfg["cloud"]["openai"]["rawKeys"] == ["sk-real-secret-1", "sk-real-secret-2"]
    assert cfg["tts"]["elevenlabs"]["rawKeys"] == ["el-raw-key-1"]

