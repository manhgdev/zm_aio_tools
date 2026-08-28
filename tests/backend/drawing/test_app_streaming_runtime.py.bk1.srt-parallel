from pathlib import Path

from pipeline.drawing import jobs
from pipeline.drawing import stream_runner


def test_frozen_drawing_uses_managed_python(monkeypatch, tmp_path):
    python = tmp_path / ".venv-runtime" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(jobs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(jobs.sys, "platform", "darwin")
    monkeypatch.setenv("VIDEO_CLONE_HOME", str(tmp_path))

    assert jobs._drawing_python() == python


def test_streaming_reference_can_be_resolved_from_bundle(monkeypatch, tmp_path):
    source = tmp_path / "references" / "whiteboard-stream-animation" / "scripts" / "stream_render.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("VIDEO_CLONE_BUNDLE", str(tmp_path))

    module, hand = stream_runner._load_reference()

    assert module.VALUE == 1
    assert hand == tmp_path / "references" / "whiteboard-stream-animation" / "assets" / "drawing-hand.png"


def test_batch_uses_two_workers_on_a_typical_machine(monkeypatch):
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 8)
    assert jobs._drawing_batch_workers(100) == 2
    assert jobs._drawing_batch_workers(1) == 1


def test_batch_stays_sequential_on_small_machines(monkeypatch):
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 2)
    assert jobs._drawing_batch_workers(100) == 1


def test_internal_render_profile_limits_cpu_work_without_changing_export_settings():
    assert jobs._drawing_render_profile(1920, 1080, 30, "1080p") == (960, 15)
    assert jobs._drawing_render_profile(3840, 2160, 60, "4k") == (1280, 15)
    assert jobs._drawing_render_profile(1280, 720, 24, "720p") == (960, 15)


def test_stream_runner_can_skip_redundant_intermediate_h264(monkeypatch, tmp_path):
    raw = tmp_path / "drawing.mp4"
    raw.touch()
    called = False

    def transcode(*_args):
        nonlocal called
        called = True

    result = stream_runner._finish_render(raw, tmp_path / "drawing_h264.mp4", 30, object(), transcode=False)

    assert result == raw
    assert called is False
