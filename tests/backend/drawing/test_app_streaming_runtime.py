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
