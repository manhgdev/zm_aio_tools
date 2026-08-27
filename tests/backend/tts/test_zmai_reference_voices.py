from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.tts.engines import vieneu
from pipeline.tts import voice_store, zmtss_catalog


class _FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def encode_reference(self, path: Path, denoise: bool = False):
        self.calls += 1
        return f"embedding-{self.calls}", f"codes-{self.calls}"


def test_zmtts_normalization_uses_wav_extension_for_ffmpeg_output(tmp_path, monkeypatch) -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return b""

    output_paths = []

    def run(command, **_kwargs):
        output = Path(command[-1])
        output_paths.append(output)
        output.write_bytes(b"0" * 1024)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(zmtss_catalog.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())
    monkeypatch.setattr(zmtss_catalog.subprocess, "run", run)

    destination = tmp_path / "zmt-demo.wav"
    zmtss_catalog.download_reference({"id": "demo", "audio": "audio/demo.mp3"}, destination)

    assert output_paths[0].suffix == ".wav"
    assert destination.is_file()


def test_reference_voice_list_excludes_missing_audio(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "ready.wav"
    existing.write_bytes(b"wav")
    monkeypatch.setattr(voice_store, "REFERENCE_ROOT", tmp_path)
    monkeypatch.setattr(
        voice_store,
        "_read_reference_raw",
        lambda: [
            {"id": "ready", "engine": "vieneu", "type": "zmAI", "ref_file": "ready.wav"},
            {"id": "missing", "engine": "vieneu", "type": "zmAI", "ref_file": "missing.wav"},
        ],
    )

    assert [item["id"] for item in voice_store.load_reference_voices()] == ["ready"]


def test_reference_encode_cache_refreshes_when_wav_changes(tmp_path, monkeypatch) -> None:
    ref = tmp_path / "voice.wav"
    ref.write_bytes(b"first")
    entry = {"id": "voice", "name": "Voice", "ref_file": ref.name}
    monkeypatch.setattr(vieneu.voice_store, "get_reference_voice", lambda _: entry)
    monkeypatch.setattr(vieneu.voice_store, "reference_path", lambda _: ref)
    vieneu._reference_cache.clear()
    client = _FakeClient()

    assert vieneu._encoded_reference(client, "voice") == vieneu._encoded_reference(client, "voice")
    assert client.calls == 1

    ref.write_bytes(b"changed-reference")
    os.utime(ref, None)
    vieneu._encoded_reference(client, "voice")
    assert client.calls == 2


def test_missing_reference_is_explicit_and_never_falls_back(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing.wav"
    entry = {"id": "voice", "name": "Voice", "ref_file": missing.name}
    monkeypatch.setattr(vieneu.voice_store, "get_reference_voice", lambda _: entry)
    monkeypatch.setattr(vieneu.voice_store, "reference_path", lambda _: missing)

    with pytest.raises(RuntimeError, match="Thiếu file reference"):
        vieneu._encoded_reference(_FakeClient(), "voice")


def test_remote_zmtts_voice_downloads_only_when_synthesized(tmp_path, monkeypatch) -> None:
    item = {"id": "tieng-viet--ngoc-huyen", "name": "Ngọc Huyền", "language": "Tiếng Việt", "audio": "audio/demo.mp3"}
    monkeypatch.setattr(vieneu.zmtss_catalog, "get", lambda _: item)
    monkeypatch.setattr(vieneu.voice_store, "REFERENCE_ROOT", tmp_path)
    monkeypatch.setattr(vieneu.voice_store, "_read_reference_raw", lambda: [])
    saved = []
    monkeypatch.setattr(vieneu.voice_store, "save_reference_voices", lambda entries: saved.extend(entries))

    def download(_item, path):
        path.write_bytes(b"wav")

    monkeypatch.setattr(vieneu.zmtss_catalog, "download_reference", download)
    monkeypatch.setattr(vieneu.zmtss_catalog, "local_filename", lambda _: "zmt-demo.wav")
    remote_id = "zmt:tieng-viet--ngoc-huyen"
    vieneu._ensure_remote_reference(remote_id)

    assert (tmp_path / "zmt-demo.wav").is_file()
    assert saved[0]["id"] == remote_id
    assert saved[0]["name"] == "Ngọc Huyền"


def test_auto_lists_zmtts_catalog_even_before_vieneu_runtime_is_installed(monkeypatch) -> None:
    monkeypatch.setattr(vieneu, "available", lambda: False)
    monkeypatch.setattr(vieneu.voice_store, "load_reference_voices", lambda: [])
    monkeypatch.setattr(vieneu.voice_store, "load_cloned", lambda: [])
    monkeypatch.setattr(vieneu.zmtss_catalog, "voices", lambda: [
        {"id": "tieng-viet--demo", "name": "Demo", "language": "Tiếng Việt", "audio": "audio/demo.mp3"},
    ])

    listed = vieneu.list_voices("auto")

    assert any(voice["id"] == "zmt:tieng-viet--demo" for voice in listed)
