from copy import deepcopy

import pytest

from pipeline.export.burn_parts import pipeline as burn
from pipeline.orchestrate.export_job import _burn_cache_key


def snapshot():
    return {
        "id": "caption", "start": 0, "end": 1,
        "translation": "Xin chào", "source": "你好", "layout": "horizontal",
        "bboxInherited": True, "bboxDetected": True,
        "bbox": {"x": 80, "y": 240, "w": 400, "h": 32},
        "captionLayout": {
            "x": 20, "y": 210, "w": 600, "h": 80,
            "lines": ["Xin", "chào"], "fontSize": 24, "previewVersion": 1,
            "mask": {"x": 0, "y": 230, "w": 640, "h": 78},
        },
    }


@pytest.mark.parametrize("blur_mode", ["off", "auto", "manual"])
def test_export_uses_exact_preview_boxes_without_ocr(monkeypatch, tmp_path, blur_mode):
    monkeypatch.setattr(burn, "video_size", lambda _: (640, 360))
    monkeypatch.setattr(burn, "ffprobe_duration", lambda _: 1)
    def no_ocr(*args, **kwargs):
        pytest.fail("A committed live-preview snapshot must not invoke OCR")
    monkeypatch.setattr(burn, "_rapidocr_labels", no_ocr)
    overlays, rendered = [], {}
    monkeypatch.setattr(burn, "_caption_overlay", lambda layout: overlays.append(layout) or None)
    def capture(*args, **kwargs):
        rendered.update(kwargs)
        return True
    monkeypatch.setattr("pipeline.export.burn_parts.ffgraph.try_render_ffmpeg", capture)
    monkeypatch.setattr(burn, "render_burned_video", capture)
    seg = snapshot()
    if blur_mode != "off":
        seg["captionLayout"]["mask"] = None
    region = {"x": 0.1, "y": 0.55, "w": 0.8, "h": 0.3}
    burn.cover_and_burn(
        tmp_path / "source.mp4", [seg], tmp_path / "output.mp4",
        cover=True, burn=True, workers=1,
        blur_band_mode=blur_mode, blur_band_region=region,
        blur_band_auto_region=region,
    )
    assert overlays[0]["box"] == (20, 210, 620, 290)
    assert overlays[0]["lines"] == ["Xin", "chào"]
    assert overlays[0]["fontsize"] == 24
    assert rendered["cue_fits"][0] == ([(0, 230, 640, 308)] if blur_mode == "off" else [])
    if blur_mode != "off":
        assert rendered["cue_fits"][1] == [(64, 198, 576, 306)]


@pytest.mark.parametrize("field,value", [
    ("coverHardsubs", False), ("burnSubs", False),
    ("coverMaskOpacity", 70), ("captionTextColor", "#ff0000"),
    ("blurBandAutoRegion", {"x": 0, "y": .6, "w": 1, "h": .2}),
])
def test_burn_cache_tracks_render_settings(field, value):
    settings = {"coverHardsubs": True, "burnSubs": True}
    before = _burn_cache_key("video", settings, [snapshot()], [], "none", 1)
    assert before != _burn_cache_key("video", {**settings, field: value}, [snapshot()], [], "none", 1)


def test_burn_cache_tracks_caption_snapshot_and_style():
    seg = snapshot()
    before = _burn_cache_key("video", {}, [seg], [], "none", 1)
    for key, value in [("y", 200), ("lines", ["Xin chào"]), ("mask", None)]:
        changed = deepcopy(seg)
        changed["captionLayout"][key] = value
        assert before != _burn_cache_key("video", {}, [changed], [], "none", 1)
    assert before != _burn_cache_key("video", {}, [{**seg, "textColor": "#ff0000"}], [], "none", 1)
