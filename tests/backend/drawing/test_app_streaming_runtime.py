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


def test_batch_workers_follow_live_resources_with_a_machine_safe_cap(monkeypatch):
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(jobs, "adaptive_workers", lambda _requested, **kwargs: kwargs["cap"])
    assert jobs._drawing_batch_workers(100) == 7
    assert jobs._drawing_batch_workers(1) == 1


def test_batch_can_use_twelve_workers_on_a_high_core_machine(monkeypatch):
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 18)
    monkeypatch.setattr(jobs, "adaptive_workers", lambda _requested, **kwargs: kwargs["cap"])
    assert jobs._drawing_batch_workers(100) == 12


def test_batch_stays_sequential_on_small_machines(monkeypatch):
    monkeypatch.setattr(jobs.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(jobs, "adaptive_workers", lambda _requested, **kwargs: kwargs["cap"])
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


def test_rendering_optimizations_produce_correct_output():
    """Smoke-test: bbox ROI paint must write ink pixels, not leave canvas blank."""
    import numpy as np

    renderer_module, _ = stream_runner._load_reference()

    h, w = 64, 64
    _canvas    = np.full((h, w, 3), 240.0, dtype=np.float32)   # light grey background
    _ink_paint = np.full((h, w, 3), 10.0,  dtype=np.float32)   # dark ink

    # Minimal renderer stand-in with the attributes the optimizer reads
    class FakeRenderer:
        out_h, out_w = h, w
        drawn      = _canvas.copy()
        ink_paint  = _ink_paint
        color_img  = _canvas.copy()
        ink_pixels = np.zeros((h, w), dtype=bool)
        tip        = None

        class cfg:
            ink_reveal_radius = 2
            brush_radius = 16

    renderer = FakeRenderer()
    # Mark the centre row as valid ink pixels
    renderer.ink_pixels[h // 2, :] = True

    stream_runner._apply_rendering_optimizations(renderer, renderer_module)

    # Draw a horizontal segment across the canvas centre
    renderer._reveal_ink_segment((0, h // 2), (w - 1, h // 2))

    # drawn must differ from the original canvas in the ink region
    changed = not np.allclose(renderer.drawn, _canvas)
    assert changed, "bbox ROI paint wrote nothing — optimized renderer is broken"
    # Pixels outside the ink_pixels mask must be untouched
    assert np.allclose(renderer.drawn[0, 0], _canvas[0, 0]), \
        "pixels outside ink_pixels mask were modified"
