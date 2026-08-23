from __future__ import annotations


def test_h264_encoder_prefers_nvidia_on_windows(monkeypatch) -> None:
    from pipeline.core import media

    monkeypatch.setattr(media.sys, "platform", "win32")
    monkeypatch.setattr(media, "nvenc_available", lambda: True)

    assert media.h264_hardware_encoder() == "h264_nvenc"
    assert "h264_nvenc" in media.h264_encoder_args(fast=True, throughput=True)


def test_h264_encoder_uses_intel_or_amd_on_windows(monkeypatch) -> None:
    from pipeline.core import media

    monkeypatch.setattr(media.sys, "platform", "win32")
    monkeypatch.setattr(media, "nvenc_available", lambda: False)
    monkeypatch.setattr(media, "_h264_encoder_available", lambda codec: codec == "h264_qsv")
    monkeypatch.setattr(media, "detect_device", lambda: {"gpuKind": "intel", "gpus": [{"kind": "intel"}]})

    assert media.h264_hardware_encoder() == "h264_qsv"
    assert "h264_qsv" in media.h264_encoder_args(fast=True, throughput=True)


def test_h264_encoder_uses_videotoolbox_on_macos(monkeypatch) -> None:
    from pipeline.core import media

    monkeypatch.setattr(media.sys, "platform", "darwin")
    monkeypatch.setattr(media, "nvenc_available", lambda: False)
    monkeypatch.setattr(media, "_h264_encoder_available", lambda codec: codec == "h264_videotoolbox")

    assert media.h264_hardware_encoder() == "h264_videotoolbox"
    assert "h264_videotoolbox" in media.h264_encoder_args(fast=True, throughput=True)
