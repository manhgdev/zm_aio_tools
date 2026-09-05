from __future__ import annotations

import builtins

from pipeline.asr import whisper


def test_prefers_mlx_before_loading_faster_whisper_cpu(monkeypatch, tmp_path) -> None:
    rows = [{"id": "mlx-1", "index": 0, "start": 0.0, "end": 1.0, "source": "xin chao"}]

    monkeypatch.setattr(whisper, "_mlx_whisper_available", lambda: True, raising=False)
    monkeypatch.setattr(whisper, "_mlx_transcribe", lambda *_args: rows)
    monkeypatch.setattr(
        whisper,
        "get_whisper",
        lambda _workers: (_ for _ in ()).throw(AssertionError("CPU model must not load")),
    )

    assert whisper.asr_whisper_inprocess(tmp_path / "audio.wav", "vi") == rows


def test_falls_back_to_faster_whisper_when_mlx_cannot_transcribe(monkeypatch, tmp_path) -> None:
    class Model:
        def transcribe(self, *_args, **_kwargs):
            return iter(()), object()

    monkeypatch.setattr(whisper, "_mlx_whisper_available", lambda: True, raising=False)
    monkeypatch.setattr(whisper, "_mlx_transcribe", lambda *_args: None)
    monkeypatch.setattr(whisper, "get_whisper", lambda _workers: Model())

    assert whisper.asr_whisper_inprocess(tmp_path / "audio.wav", "vi") == []


def test_warm_whisper_does_not_preload_cpu_model_when_mlx_is_ready(monkeypatch) -> None:
    monkeypatch.setattr(whisper, "_mlx_whisper_available", lambda: True, raising=False)
    monkeypatch.setattr(
        whisper,
        "get_whisper",
        lambda _workers: (_ for _ in ()).throw(AssertionError("CPU model must not load")),
    )

    assert whisper.warm_whisper() == "mlx-ready"


def test_mlx_probe_falls_back_safely_when_the_native_import_fails(monkeypatch) -> None:
    original_import = builtins.__import__

    monkeypatch.setattr(whisper.sys, "platform", "darwin")
    monkeypatch.setattr(whisper.platform, "machine", lambda: "arm64")

    def failing_import(name, *args, **kwargs):
        if name == "mlx_whisper":
            raise OSError("native MLX library unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    assert whisper._mlx_whisper_available() is False
