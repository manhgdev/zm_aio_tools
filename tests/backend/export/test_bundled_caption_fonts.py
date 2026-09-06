from pathlib import Path
import unittest

import pytest

pytest.importorskip("fastapi", reason="Python hệ thống thiếu fastapi — test API chạy trong venv backend")

from PIL import ImageFont
from pydantic import ValidationError

from api.deps import SegmentIn
from pipeline.export import fonts
from pipeline.export.burn_parts.layout_text import (
    _layout_caption,
    _layout_caption_over,
    _layout_mid_caption,
    _layout_caption_vertical,
)
from pipeline.export.burn_parts.ocr_boxes import (
    _expand_mid_box_to_subtitle_band,
    _merge_ocr_samples,
    _segment_bbox_override,
)
from pipeline.export.burn_parts.pipeline import _merge_overlapping_caption_cue_boxes


EXPECTED = {
    "system": "NotoSans-Bold.ttf",
    "segoe": "Inter-Bold.ttf",
    "arial": "Arimo-Bold.ttf",
    "bold": "ArchivoBlack-Regular.ttf",
    "helvetica": "Roboto-Bold.ttf",
    "verdana": "OpenSans-Bold.ttf",
    "tahoma": "Carlito-Bold.ttf",
    "trebuchet": "FiraSans-Bold.ttf",
    "rounded": "Nunito-Bold.ttf",
    "impact": "Anton-Regular.ttf",
    "georgia": "Merriweather-Bold.ttf",
    "times": "Tinos-Bold.ttf",
    "palatino": "Literata-Bold.ttf",
    "garamond": "EBGaramond-Bold.ttf",
    "courier": "CourierPrime-Bold.ttf",
    "mono": "NotoSansMono-Bold.ttf",
    "comic": "ComicNeue-Bold.ttf",
    "cjk": "NotoSansSC-Bold.ttf",
    "meiryo": "NotoSansJP-Bold.ttf",
    "malgun": "NotoSansKR-Bold.ttf",
}


class BundledCaptionFontTest(unittest.TestCase):
    def test_every_caption_preset_resolves_to_its_bundled_font(self) -> None:
        fonts._font_file_index = None
        fonts._font_cache.clear()
        bundled = (Path(__file__).parents[3] / "frontend" / "public" / "fonts").resolve()

        for preset, filename in EXPECTED.items():
            resolved = Path(fonts._font_for_preset(preset))
            self.assertEqual(resolved.name, filename)
            self.assertEqual(resolved.parent, bundled)
            self.assertGreater(
                ImageFont.truetype(resolved, 32).getbbox("Phụ đề 日本 한국 中文")[2],
                0,
            )
            self.assertTrue(
                fonts._font_covers_text(
                    str(resolved),
                    "Hãy đến và đập nát tất cả túi ngô nhỏ này",
                ),
                f"{preset} maps Vietnamese glyphs to a missing/question glyph",
            )

    def test_layout_fallbacks_keep_the_selected_font(self) -> None:
        selected = fonts._font_for_preset("comic")
        font = ImageFont.truetype(selected, 48)
        text = "Hãy đến và đập nát tất cả túi ngô nhỏ này"

        regular = _layout_caption(
            text, font, 48, (80, 900, 1000, 1010), 1080, 1920,
        )
        over, _cover = _layout_caption_over(
            text,
            48,
            (80, 900, 1000, 1010),
            1080,
            1920,
            font_path=selected,
        )
        vertical = _layout_caption_vertical(
            "Hãy đến", font, 48, (20, 200, 180, 800), 1080, 1920,
        )

        for layout in (regular, over, vertical):
            self.assertEqual(Path(layout["font"].path).resolve(), Path(selected).resolve())

    def test_missing_preset_falls_back_to_bundled_noto_not_host_font(self) -> None:
        fonts._font_file_index = None
        fonts._font_cache.clear()
        fallback = Path(fonts._font_for_preset("missing-preset"))

        self.assertEqual(fallback.name, "NotoSans-Bold.ttf")
        self.assertEqual(fallback.parent.name, "fonts")
        self.assertNotEqual(str(fallback), "Arial")

    def test_segment_caption_style_fields_are_validated(self) -> None:
        base = dict(id="s1", index=0, start=0, end=1, source="", translation="", voice="")
        segment = SegmentIn(**base, fontFamily="rounded", textColor="#12aBcF")
        self.assertEqual(segment.model_dump()["fontFamily"], "rounded")
        self.assertEqual(segment.model_dump()["textColor"], "#12aBcF")

        with self.assertRaises(ValidationError):
            SegmentIn(**base, fontFamily="../font.ttf", textColor="red")

    def test_only_user_dragged_bbox_bypasses_export_ocr(self) -> None:
        bbox = {"x": 80, "y": 900, "w": 920, "h": 80}

        # A saved automatic box is an OCR hint, not an editor override.  The
        # export must re-measure it against the encoded source frame.
        self.assertIsNone(
            _segment_bbox_override({"bbox": bbox, "bboxInherited": True}, 1080, 1920)
        )
        # Projects created before bboxInherited existed retain their edited
        # placement until the user runs the current locator again.
        self.assertEqual(
            _segment_bbox_override({"bbox": bbox}, 1080, 1920),
            (80, 900, 1000, 980),
        )
        self.assertEqual(
            _segment_bbox_override(
                {"bbox": bbox, "bboxInherited": True}, 1080, 1920, accept_automatic=True
            ),
            (80, 900, 1000, 980),
        )
        self.assertEqual(
            _segment_bbox_override({"bbox": bbox, "bboxInherited": False}, 1080, 1920),
            (80, 900, 1000, 980),
        )

    def test_outside_caption_flips_when_requested_side_has_no_room(self) -> None:
        font = ImageFont.truetype(fonts._font_for_preset("system"), 48)

        for placement, ocr_box in (
            ("below", (180, 1840, 900, 1900)),
            ("above", (180, 20, 900, 80)),
        ):
            layout = _layout_caption(
                "Bản dịch phải nằm ngoài phụ đề gốc",
                font,
                48,
                ocr_box,
                1080,
                1920,
                placement=placement,
            )
            x0, y0, x1, y1 = layout["box"]
            self.assertGreaterEqual(x0, 0)
            self.assertLessEqual(x1, 1080)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(y1, 1920)
            self.assertTrue(
                y1 <= ocr_box[1] or y0 >= ocr_box[3],
                f"{placement} caption overlaps source bbox: {layout['box']} vs {ocr_box}",
            )

    def test_mid_caption_expands_to_a_nearby_second_hardsub_row(self) -> None:
        # The source-matched OCR can find only the lower row while the
        # lower-band OCR sees the full two-row hard subtitle.
        matched = [(268, 1341, 814, 1491)]
        band = [(247, 1322, 1032, 1499)]

        self.assertEqual(
            _expand_mid_box_to_subtitle_band(matched, band, 1080, 1920),
            [(268, 1322, 814, 1499)],
        )

    def test_simultaneous_three_row_cues_share_one_tight_cover(self) -> None:
        cues = [
            (1.0, 2.0, 1.0, 2.0, "a", "a", "mid"),
            (1.0, 2.0, 1.0, 2.0, "b", "b", "mid"),
            (1.0, 2.0, 1.0, 2.0, "c", "c", "mid"),
        ]
        boxes = [
            [(250, 1200, 820, 1250)],
            [(230, 1255, 840, 1305)],
            [(260, 1310, 810, 1360)],
        ]
        merged = _merge_overlapping_caption_cue_boxes(
            cues,
            ["a", "b", "c"],
            boxes,
            {key: {"layout": "mid"} for key in ("a", "b", "c")},
            1080,
            1920,
        )
        for result in merged:
            self.assertLessEqual(result[0][1], 1200)
            self.assertGreaterEqual(result[0][3], 1360)

    def test_non_overlapping_cues_are_not_merged(self) -> None:
        cues = [
            (1.0, 2.0, 1.0, 2.0, "a", "a", "mid"),
            (2.0, 3.0, 2.0, 3.0, "b", "b", "mid"),
        ]
        boxes = [[(250, 1200, 820, 1250)], [(250, 1260, 820, 1310)]]
        self.assertEqual(
            _merge_overlapping_caption_cue_boxes(
                cues,
                ["a", "b"],
                boxes,
                {"a": {"layout": "mid"}, "b": {"layout": "mid"}},
                1080,
                1920,
            ),
            boxes,
        )

    def test_multiline_translation_fits_inside_and_centres_on_cover(self) -> None:
        font_path = fonts._font_for_preset("system")
        layout = _layout_mid_caption(
            "Bản dịch dài cần tự xuống dòng và nằm giữa vùng che",
            lambda size: ImageFont.truetype(font_path, size),
            (220, 1180, 860, 1380),
            1080,
            1920,
            preferred_fs=40,
        )
        x0, y0, x1, y1 = layout["box"]
        self.assertGreaterEqual(x0, 0)
        self.assertLessEqual(x1, 1080)
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(y1, 1920)
        self.assertLessEqual(layout["text_h"], y1 - y0)
        self.assertAlmostEqual((y0 + y1) / 2, 1280, delta=1)

    def test_ocr_sample_merge_ignores_a_previous_subtitle_lane(self) -> None:
        # The first probe is still on the preceding subtitle; four following
        # probes agree on the current two-row caption.  The merge must choose
        # the repeated lane instead of centring one tall union across both.
        merged = _merge_ocr_samples(
            [(295, 1150, 722, 1389)] + [(268, 1321, 814, 1499)] * 4,
            1080,
            1920,
        )

        self.assertEqual(len(merged), 1)
        self.assertGreaterEqual(merged[0][1], 1310)
        self.assertGreaterEqual(merged[0][3], 1499)
