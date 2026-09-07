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


def test_dynamic_blur_band_expansion_when_caption_exceeds_band(monkeypatch, tmp_path):
    monkeypatch.setattr(burn, "video_size", lambda _: (1080, 1920))
    monkeypatch.setattr(burn, "ffprobe_duration", lambda _: 10)
    monkeypatch.setattr(burn, "_rapidocr_labels", lambda *a, **k: [])
    overlays, rendered = [], {}
    monkeypatch.setattr(burn, "_caption_overlay", lambda layout: overlays.append(layout) or None)
    def capture(*args, **kwargs):
        rendered.update(kwargs)
        return True
    monkeypatch.setattr("pipeline.export.burn_parts.ffgraph.try_render_ffmpeg", capture)
    monkeypatch.setattr(burn, "render_burned_video", capture)

    # 3-line tall caption exceeding the base band (1236 to 1340)
    tall_seg = {
        "id": "tall_caption", "start": 8.0, "end": 12.0,
        "translation": "Chúng tôi đặt mục tiêu vào một hòn đảo nguyên thủy có đường kính khoảng 3.000 mét",
        "source": "原始岛屿", "layout": "mid",
        "bbox": {"x": 152, "y": 1236, "w": 776, "h": 82},
        "captionLayout": {
            "x": 159, "y": 1200, "w": 762, "h": 176,
            "lines": ["Line 1", "Line 2", "Line 3"], "fontSize": 48, "previewVersion": 1,
            # Expanded mask covers 1200 to 1376 full width
            "mask": {"x": 0, "y": 1200, "w": 1080, "h": 176},
        },
    }
    band_region = {"x": 0.0, "y": 1236 / 1920, "w": 1.0, "h": 104 / 1920}
    burn.cover_and_burn(
        tmp_path / "source.mp4", [tall_seg], tmp_path / "output.mp4",
        cover=True, burn=True, workers=1,
        blur_band_mode="auto", blur_band_auto_region=band_region,
    )
    # Cue 0 is tall_caption: gets expanded full-width mask (0, 1200, 1080, 1376)
    assert rendered["cue_fits"][0] == [(0, 1200, 1080, 1376)]
    assert rendered["cue_need_mask"][0] is True
    # Cue 1 is base band: covers full duration at base height (0, 1236, 1080, 1340)
    assert rendered["cue_fits"][1] == [(0, 1236, 1080, 1340)]


def test_export_independent_bbox_and_caption_box(monkeypatch, tmp_path):
    """captionBox and bbox/coverBox render independently: cover at bbox, text at captionBox."""
    monkeypatch.setattr(burn, "video_size", lambda _: (1080, 1920))
    monkeypatch.setattr(burn, "ffprobe_duration", lambda _: 4)
    monkeypatch.setattr(burn, "_rapidocr_labels", lambda *a, **k: [])
    overlays, rendered = [], {}
    monkeypatch.setattr(burn, "_caption_overlay", lambda layout: overlays.append(layout) or None)
    def capture(*args, **kwargs):
        rendered.update(kwargs)
        return True
    monkeypatch.setattr("pipeline.export.burn_parts.ffgraph.try_render_ffmpeg", capture)
    monkeypatch.setattr(burn, "render_burned_video", capture)

    seg = {
        "id": "decoupled_seg", "start": 1.0, "end": 3.0,
        "translation": "Tìm một hòn đảo lớn",
        "source": "寻找一座面积庞大的岛屿", "layout": "mid",
        "bbox": {"x": 212, "y": 1246, "w": 659, "h": 65},
        "captionBox": {"x": 286, "y": 1145, "w": 509, "h": 82},
        "captionLayout": {
            "x": 286, "y": 1145, "w": 509, "h": 82,
            "lines": ["Tìm một hòn đảo lớn"], "fontSize": 48, "previewVersion": 1,
            # No mask inside captionLayout — clean decoupled schema
        },
    }
    burn.cover_and_burn(
        tmp_path / "source.mp4", [seg], tmp_path / "output.mp4",
        cover=True, burn=True, workers=1, blur_band_mode="off",
    )
    # Caption overlay renders at captionBox (y=1145)
    assert overlays[0]["box"] == (286, 1145, 795, 1227)
    assert overlays[0]["lines"] == ["Tìm một hòn đảo lớn"]
    # Cover mask renders at bbox (y=1246)
    assert rendered["cue_fits"][0] == [(212, 1246, 871, 1311)]
    assert rendered["cue_need_mask"][0] is True


def test_export_above_mode_with_blur_band_renders_caption_above_not_in_band(monkeypatch, tmp_path):
    """When placement is 'above', caption is placed above the blur band, never inside it."""
    monkeypatch.setattr(burn, "video_size", lambda _: (1080, 1920))
    monkeypatch.setattr(burn, "ffprobe_duration", lambda _: 4)
    monkeypatch.setattr(burn, "_rapidocr_labels", lambda *a, **k: [])
    overlays, rendered = [], {}
    monkeypatch.setattr(burn, "_caption_overlay", lambda layout: overlays.append(layout) or None)
    def capture(*args, **kwargs):
        rendered.update(kwargs)
        return True
    monkeypatch.setattr("pipeline.export.burn_parts.ffgraph.try_render_ffmpeg", capture)
    monkeypatch.setattr(burn, "render_burned_video", capture)

    band_box = {"x": 0.0, "y": 1238 / 1920, "w": 1.0, "h": 122 / 1920}
    seg = {
        "id": "above_seg", "start": 0.0, "end": 2.08,
        "translation": "Chúng tôi đang ở trên biển Hamahele ở Papua",
        "source": "我们正在巴布亚的哈马黑莱海", "layout": "mid",
        "bbox": {"x": 224, "y": 1238, "w": 632, "h": 122},
        "captionLayout": {
            "x": 224, "y": 1145, "w": 632, "h": 82,
            "lines": ["Chúng tôi đang ở trên", "biển Hamahele ở Papua"],
            "fontSize": 48, "previewVersion": 1,
        },
    }
    burn.cover_and_burn(
        tmp_path / "source.mp4", [seg], tmp_path / "output.mp4",
        cover=False, burn=True, workers=1, blur_band_mode="auto",
        blur_band_auto_region=band_box,
    )
    # Exactly 1 overlay for the caption, placed above the blur band at y=1145
    assert len(overlays) == 1
    assert overlays[0]["box"][1] == 1145
    # The blur band covers the base region (0, 1238, 1080, 1360)
    assert rendered["cue_fits"][1] == [(0, 1238, 1080, 1360)]


def test_export_dragged_caption_box_renders_at_coordinates_and_does_not_expand_blur(monkeypatch, tmp_path):
    """When a caption has a custom captionBox (dragged by user), export renders at that exact box without expanding the blur band."""
    monkeypatch.setattr(burn, "video_size", lambda _: (1080, 1920))
    monkeypatch.setattr(burn, "ffprobe_duration", lambda _: 4)
    monkeypatch.setattr(burn, "_rapidocr_labels", lambda *a, **k: [])
    overlays, rendered = [], {}
    monkeypatch.setattr(burn, "_caption_overlay", lambda layout: overlays.append(layout) or None)
    def capture(*args, **kwargs):
        rendered.update(kwargs)
        return True
    monkeypatch.setattr("pipeline.export.burn_parts.ffgraph.try_render_ffmpeg", capture)
    monkeypatch.setattr(burn, "render_burned_video", capture)

    band_box = {"x": 0.0, "y": 1238 / 1920, "w": 1.0, "h": 122 / 1920}
    seg = {
        "id": "dragged_seg", "start": 0.0, "end": 2.08,
        "translation": "Chúng tôi đang ở trên biển Hamahele ở Papua",
        "source": "我们正在巴布亚的哈马黑莱海", "layout": "mid",
        "bbox": {"x": 224, "y": 1238, "w": 632, "h": 122},
        # User dragged caption to top-left (x=20, y=150, w=500, h=100)
        "captionBox": {"x": 20, "y": 150, "w": 500, "h": 100},
    }
    burn.cover_and_burn(
        tmp_path / "source.mp4", [seg], tmp_path / "output.mp4",
        cover=False, burn=True, workers=1, blur_band_mode="auto",
        blur_band_auto_region=band_box,
    )
    assert len(overlays) == 1
    # Caption rendered at dragged coordinates
    assert overlays[0]["box"][0] == 20
    assert overlays[0]["box"][1] == 150
    # Blur band stays at its original coordinates, never expanding to y=150
    assert rendered["cue_fits"][1] == [(0, 1238, 1080, 1360)]


