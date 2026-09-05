from __future__ import annotations

import numpy as np

from pipeline.ocr.locate import _expand_split_hardsub_groups, _probe_mid_hardsub


class _SingleGlyphEngine:
    def __call__(self, _frame):
        return [
            (
                [[420, 150], [580, 150], [580, 270], [420, 270]],
                "心",
            )
        ], None


def test_latin_caption_locator_rejects_unrelated_single_cjk_glyph():
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    hit = _probe_mid_hardsub(
        frame,
        _SingleGlyphEngine(),
        source="became an award-winning actor",
    )
    assert hit is None


def test_split_asr_cues_expand_one_row_box_to_cover_both_hardsub_rows():
    segments = [
        {
            "bbox": {"x": 220, "y": 1409, "w": 600, "h": 89},
            "bboxInherited": True,
            "bboxDetected": True,
            "words": [{"start": 6.2}, {"end": 7.3}],
        },
        {
            "bbox": {"x": 260, "y": 1409, "w": 500, "h": 89},
            "bboxInherited": True,
            "bboxDetected": True,
            "words": [{"start": 6.2}, {"end": 7.3}],
        },
    ]
    _expand_split_hardsub_groups(segments, 1920, 1080)
    assert segments[0]["bbox"] == segments[1]["bbox"]
    assert segments[0]["bbox"]["y"] < 1409
    assert segments[0]["bbox"]["h"] > 89


def test_inherited_boxes_are_not_expanded_into_an_auto_blur_band():
    segments = [
        {
            "bbox": {"x": 220, "y": 1409, "w": 600, "h": 89},
            "bboxInherited": True,
            "bboxDetected": False,
            "words": [{"start": 6.2}, {"end": 7.3}],
        },
        {
            "bbox": {"x": 260, "y": 1409, "w": 500, "h": 89},
            "bboxInherited": True,
            "bboxDetected": False,
            "words": [{"start": 6.2}, {"end": 7.3}],
        },
    ]
    _expand_split_hardsub_groups(segments, 1920, 1080)
    assert segments[0]["bbox"]["y"] == 1409
    assert segments[0]["bbox"]["h"] == 89
