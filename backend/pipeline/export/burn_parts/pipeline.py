"""Hardsub cover + caption burn — pipeline."""
from __future__ import annotations

"""Cover hardsubs + burn translated captions."""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.ocr.extract import _rapidocr_gpu_kwargs
from pipeline.core.jobs import _job_procs, check_cancel
from pipeline.core.media import ffprobe_duration, h264_encoder_args, nvdec_available, video_size
from pipeline.core.project import ensure_layout, set_status
from pipeline.core.resources import adaptive_workers
from pipeline.ocr.extract import _ocr_join_lines, _rapidocr_labels
from pipeline.ocr.cover_timing import resolve_cover_window
from pipeline.ocr.overlay_cover import mid_bottom_cutoff
from pipeline.ocr.labels import (
    clamp_label_box,
    cover_fit_label,
    is_tall_label,
    is_vertical_cjk_source,
    layout_label_caption,
    pick_label_box,
)
from pipeline.ocr.locate import (
    ocr_mid_hardsub_boxes,
    ocr_mid_labels,
    ocr_mid_vertical,
)
from pipeline.translate import _clean_burn_text

# aliases — giữ tên cũ cho call sites / tests
_clamp_label_box = clamp_label_box
_pick_label_box = pick_label_box
_ocr_mid_labels = ocr_mid_labels
_ocr_mid_vertical = ocr_mid_vertical
_ocr_mid_hardsub_boxes = ocr_mid_hardsub_boxes

from .ass_util import write_ass, _ass_time, _ass_text
from .layout_geo import *  # noqa: F403
from .layout_text import *  # noqa: F403
from .ocr_boxes import *  # noqa: F403
from pipeline.export.fonts import _font_for_preset, _subtitle_font, _subtitle_font_vertical
from pipeline.export.cover_mask import _apply_cover_mask
from pipeline.export.mux_audio import tts_caption_windows

# Render loop tách sang render.py — re-export giữ import cũ (tests)
from .render import (  # noqa: F401
    _burn_frame_count_complete,
    _burn_output_complete,
    render_burned_video,
)


def _persistent_blur_band_segment(
    segments: list[dict[str, Any]],
    *,
    mode: str,
    region: dict[str, float] | None,
    width: int,
    height: int,
    duration: float,
    style: str,
    color: str,
    opacity: int,
) -> dict[str, Any] | None:
    """Make a user-drawn persistent blur band a normal mask-only cue."""
    if mode != "manual" or width < 8 or height < 8 or duration <= 0:
        return None
    fixed_region = region
    if fixed_region is None:
        return None
    try:
        x = round(float(fixed_region.get("x", 0)) * width)
        y = round(float(fixed_region.get("y", 0)) * height)
        w = round(float(fixed_region.get("w", 0)) * width)
        h = round(float(fixed_region.get("h", 0)) * height)
    except (TypeError, ValueError):
        return None
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(0, min(width - x, w))
    h = max(0, min(height - y, h))
    if w < 8 or h < 8:
        return None
    return {
        "id": "__persistent_blur_band__",
        "start": 0.0,
        "end": duration,
        "translation": "",
        "source": "",
        "layout": "mid",
        "maskOnly": True,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "coverMaskStyle": style,
        "coverMaskColor": color,
        "coverMaskOpacity": opacity,
    }


def _auto_blur_band_segments(
    segments: list[dict[str, Any]], *, width: int, height: int, duration: float,
    style: str, color: str, opacity: int,
) -> list[dict[str, Any]]:
    """Build fixed, full-width subtitle lanes from verified OCR hits only."""
    if width < 8 or height < 8 or duration <= 0:
        return []
    boxes: list[tuple[int, int, int, int]] = []
    for segment in segments:
        if segment.get("bboxDetected") is not True:
            continue
        bbox = _segment_bbox_override(segment, width, height, accept_automatic=True)
        if bbox is not None:
            boxes.append(bbox)
    bands: list[dict[str, Any]] = []
    for lower in (False, True):
        lane = [box for box in boxes if ((box[1] + box[3]) * 0.5 >= height * 0.5) == lower]
        if not lane:
            continue
        # Keep every verified subtitle row in the lane, but add no synthetic
        # padding — this is the tightest fixed band that cannot leak a row.
        top = max(0, min(box[1] for box in lane))
        bottom = min(height, max(box[3] for box in lane))
        band_h = max(24, bottom - top)
        y = max(0, min(height - band_h, top))
        bands.append({
            "id": f"__auto_blur_band_{'lower' if lower else 'upper'}__",
            "start": 0.0,
            "end": duration,
            "translation": "",
            "source": "",
            "layout": "mid",
            "maskOnly": True,
            "bbox": {"x": 0, "y": y, "w": width, "h": band_h},
            "coverMaskStyle": style,
            "coverMaskColor": color,
            "coverMaskOpacity": opacity,
        })
    return bands


def _merge_overlapping_caption_cue_boxes(
    cues: list[tuple],
    cue_segment_ids: list[str],
    cue_boxes: list[list[tuple[int, int, int, int]]],
    segments_by_id: dict[str, dict[str, Any]],
    width: int,
    height: int,
) -> list[list[tuple[int, int, int, int]]]:
    """Union simultaneous rows from one visual subtitle block."""
    merged = [list(boxes) for boxes in cue_boxes]
    for i, box_list in enumerate(cue_boxes):
        current = _union_box(box_list) if box_list else None
        if current is None:
            continue
        layout_i = str(segments_by_id.get(cue_segment_ids[i], {}).get("layout") or "horizontal")
        if layout_i not in ("horizontal", "mid"):
            continue
        peer_indices = {i}
        cs0, ce0 = float(cues[i][0]), float(cues[i][1])
        frontier = [i]
        while frontier:
            base_idx = frontier.pop()
            base = _union_box(cue_boxes[base_idx])
            if base is None:
                continue
            for j, other_list in enumerate(cue_boxes):
                if j in peer_indices or not other_list:
                    continue
                layout_j = str(segments_by_id.get(cue_segment_ids[j], {}).get("layout") or "horizontal")
                if layout_j not in ("horizontal", "mid"):
                    continue
                cs1, ce1 = float(cues[j][0]), float(cues[j][1])
                if max(cs0, cs1) >= min(ce0, ce1):
                    continue
                other = _union_box(other_list)
                if other is None:
                    continue
                overlap = max(0, min(base[2], other[2]) - max(base[0], other[0]))
                row_h = max(base[3] - base[1], other[3] - other[1], 1)
                center_gap = abs((base[1] + base[3] - other[1] - other[3]) * 0.5)
                if overlap >= min(base[2] - base[0], other[2] - other[0]) * 0.35 and center_gap <= row_h * 1.55:
                    peer_indices.add(j)
                    frontier.append(j)
        peers = [
            box
            for idx in peer_indices
            for box in [_union_box(cue_boxes[idx])]
            if box is not None
        ]
        union = _union_box(peers)
        if len(peers) == 1 or union is None or union[3] - union[1] > round(height * 0.18):
            continue
        pad_x = max(4, round(width * 0.004))
        pad_y = max(3, round(height * 0.002))
        merged[i] = [(
            max(0, union[0] - pad_x),
            max(0, union[1] - pad_y),
            min(width, union[2] + pad_x),
            min(height, union[3] + pad_y),
        )]
    return merged


def cover_and_burn(
    video: Path,
    segments: list[dict[str, Any]],
    out: Path,
    *,
    cover: bool,
    burn: bool = True,
    subtitle_font_size: int = 0,
    subtitle_font_family: str = "",
    project_id: str | None = None,
    workers: int = 0,
    caption_placement: str = "below",
    cover_mask_style: str = "blur",
    cover_mask_color: str = "#4c1d95",
    cover_mask_opacity: int = 0,
    caption_text_color: str = "#ffffff",
    caption_bg_style: str = "none",
    caption_bg_color: str = "#000000",
    caption_bg_opacity: int = 55,
    caption_stroke: bool = True,
    post_crop: tuple[int, int, int, int] | None = None,
    post_height: int | None = None,
    video_scale_x: float = 100.0,
    video_scale_y: float = 100.0,
    render_info: dict[str, Any] | None = None,
    blur_band_mode: str = "off",
    blur_band_region: dict[str, float] | None = None,
    blur_band_auto_region: dict[str, float] | None = None,
    tts_match: str = "preferVideo",
    tts_bake_speed: float = 1.0,
) -> Path:
    """cover = blur hardsub; burn = đè chữ dịch. placement: below|above khi không cover.

    post_crop/post_height (P1.5): đường ffmpeg gộp luôn crop+scale xuất cuối và
    báo qua render_info["post_applied"] — đường legacy bỏ qua (caller tự encode).
    """
    import cv2
    from PIL import ImageFont

    if not cover and not burn:
        shutil.copy2(video, out)
        return out

    from pipeline.ocr.extract import _drop_mid_in_watermark_column

    segments = _drop_mid_in_watermark_column(list(segments))

    w, h = video_size(video)
    auto_fontsize = int(subtitle_font_size or 0) <= 0
    fontsize = (
        _auto_subtitle_font_size(w, h)
        if auto_fontsize
        else max(16, min(120, int(subtitle_font_size)))
    )
    workers = _resolve_workers(workers)
    place = (caption_placement or "below").lower()
    if place not in ("below", "above"):
        place = "below"
    mask_style = (cover_mask_style or "blur").lower()
    if mask_style not in ("blur", "feather", "solid", "mosaic"):
        mask_style = "blur"
    mask_color = str(cover_mask_color or "#4c1d95")
    mask_opacity = max(0, min(100, int(cover_mask_opacity if cover_mask_opacity is not None else 0)))
    cap_fill_hex = str(caption_text_color or "#ffffff")
    cap_bg_style = str(caption_bg_style or "none").lower()
    if cap_bg_style not in ("none", "solid", "blur", "box"):
        cap_bg_style = "none"
    cap_bg_hex = str(caption_bg_color or "#000000")
    cap_bg_op = max(0, min(100, int(caption_bg_opacity if caption_bg_opacity is not None else 55)))
    cap_stroke = bool(caption_stroke if caption_stroke is not None else True)
    # cover → chữ đè đúng dải OCR; không cover → above/below hardsub (mid cũng below/above)
    layout_place = "over" if cover else place
    font = ImageFont.truetype(_font_for_preset(subtitle_font_family), fontsize)

    # (cover_start, cover_end, burn_start, burn_end, text, source, layout)
    # Cover nới rộng hơn burn: hardsub hay hiện trước/sau ASR; burn vẫn bám timecode.
    cues: list[tuple[float, float, float, float, str, str, str]] = []
    cue_segment_ids: list[str] = []
    _is_mask_only: list[bool] = []
    _caption_uses_dub_timing: list[bool] = []
    dub_windows: dict[str, tuple[float, float]] = {}
    if project_id:
        try:
            dub_windows = tts_caption_windows(
                segments,
                ensure_layout(project_id),
                match=tts_match,
                bake_speed=tts_bake_speed,
            )
        except (OSError, ValueError):
            # Captions still render on their source timeline if a project has
            # no usable TTS file (for example a legacy/import-only project).
            dub_windows = {}
    # vid_dur needed early to set mid hardsub cover to full video span.
    vid_dur = ffprobe_duration(video) or 0.0
    persistent_band = _persistent_blur_band_segment(
        segments,
        mode=str(blur_band_mode or "off").lower(),
        region=blur_band_region,
        width=w,
        height=h,
        duration=vid_dur,
        style=mask_style,
        color=mask_color,
        opacity=mask_opacity,
    )
    if persistent_band is not None:
        segments.append(persistent_band)
    auto_band_segments: list[dict[str, Any]] = []
    if str(blur_band_mode or "off").lower() == "auto":
        auto_band_segments = _auto_blur_band_segments(
            segments, width=w, height=h, duration=vid_dur,
            style=mask_style, color=mask_color, opacity=mask_opacity,
        )
        segments.extend(auto_band_segments)
    for seg in segments:
        raw = (seg.get("translation") or "").strip()
        source = (seg.get("source") or "").strip()
        burn_text = _clean_burn_text(raw)
        mask_only = bool(seg.get("maskOnly"))
        # maskOnly: vùng hiệu ứng tự do (làm mờ) — không cần chữ
        if not burn_text and not mask_only:
            continue
        layout = str(seg.get("layout") or "horizontal")
        if layout not in ("horizontal", "vertical", "label", "mid"):
            layout = "horizontal"
        s0 = float(seg["start"])
        e0 = float(seg["end"])
        # Heuristic: title dọc flash đầu clip (layout bị mất khi UI save cũ)
        if layout == "horizontal":
            src = (seg.get("source") or "").strip()
            cjk = sum(1 for c in src if "\u4e00" <= c <= "\u9fff")
            dur = max(0.0, e0 - s0)
            if (
                s0 < 2.0
                and dur <= 0.55
                and cjk >= 3
                and cjk >= len(re.sub(r"\s+", "", src)) * 0.7
            ):
                layout = "vertical"
        if layout == "vertical":
            # Khớp preview: chữ + mask theo coverWindow
            cover_start, cover_end = resolve_cover_window(seg)
            burn_start, burn_end = cover_start, max(cover_end, cover_start + 0.04)
        elif layout == "label":
            cover_start, cover_end = resolve_cover_window(seg)
            burn_start, burn_end = cover_start, max(cover_end, cover_start + 0.04)
        elif layout == "mid":
            # Auto follows each OCR cue so a subtitle that changes rows stays
            # covered. Only a manually drawn region is full-video persistent.
            if (blur_band_mode or 'off') != 'manual':
                cover_start, cover_end = resolve_cover_window(seg)
                burn_start, burn_end = cover_start, max(cover_end, cover_start + 0.04)
            else:
                cover_start = 0.0
                cover_end = vid_dur if vid_dur > 0 else max(resolve_cover_window(seg)[1], e0 + 0.5)
                burn_start, burn_end = max(0.0, s0), max(e0, s0 + 0.04)
        else:
            # Cover nới để che hardsub; BURN chữ dịch = clip timeline [start,end)
            cover_start, cover_end = resolve_cover_window(seg)
            burn_start = max(0.0, s0)
            burn_end = max(e0, burn_start + 0.04)
        if mask_only:
            # Effect region: che theo [start,end), không burn chữ
            cover_start, cover_end = max(0.0, s0), max(e0, s0 + 0.04)
            burn_start, burn_end = cover_start, cover_start  # zero-length burn
            burn_text = ""
        segment_id = str(seg.get("id") or "")
        dub_window = dub_windows.get(segment_id) if burn_text else None
        if dub_window is not None:
            # Only the translated text follows the spoken TTS clock.  Cover
            # remains at the source OCR time so original hard-subs are hidden.
            burn_start, burn_end = dub_window
        cues.append(
            (cover_start, cover_end, burn_start, burn_end, burn_text, source, layout)
        )
        cue_segment_ids.append(segment_id)
        _is_mask_only.append(mask_only)
        _caption_uses_dub_timing.append(dub_window is not None)
    # Lấp khe cover nhỏ giữa 2 câu hardsub (không đụng tiêu đề dọc / nhãn / maskOnly).
    for i in range(len(cues) - 1):
        if _is_mask_only[i] or _is_mask_only[i + 1]:
            continue
        cs0, ce0, bs0, be0, t0, src0, lay0 = cues[i]
        cs1, ce1, bs1, be1, t1, src1, lay1 = cues[i + 1]
        if lay0 in ("vertical", "label") or lay1 in ("vertical", "label"):
            continue
        if lay0 == "mid" or lay1 == "mid":
            continue  # mid xử lý riêng — không lấp khe kiểu đáy
        gap = cs1 - ce0
        if 0.0 < gap < 0.45:
            mid = (ce0 + cs1) * 0.5
            cues[i] = (cs0, mid, bs0, be0, t0, src0, lay0)
            cues[i + 1] = (mid, ce1, bs1, be1, t1, src1, lay1)
    # Mid-mid: cắt cover/burn tại giữa khe — không đè «hoàn thiện» bằng câu sau
    mid_idx = [i for i, c in enumerate(cues) if (c[6] if len(c) > 6 else "") == "mid"]
    for a, b in zip(mid_idx, mid_idx[1:]):
        cs0, ce0, bs0, be0, t0, src0, lay0 = cues[a]
        cs1, ce1, bs1, be1, t1, src1, lay1 = cues[b]
        # dùng biên burn lõi (gần [start,end) segment) để chia
        core_end = min(be0, ce0)
        core_start = max(bs1, cs1)
        cut = (core_end + core_start) * 0.5
        if ce0 > cut:
            cues[a] = (cs0, min(ce0, cut), bs0, be0 if _caption_uses_dub_timing[a] else min(be0, cut), t0, src0, lay0)
        if cs1 < cut:
            cues[b] = (max(cs1, cut), ce1, bs1 if _caption_uses_dub_timing[b] else max(bs1, cut), be1, t1, src1, lay1)
    # Horizontal-horizontal: cắt COVER chồng (tail câu trước đè bbox sau)
    for i in range(len(cues) - 1):
        if _is_mask_only[i] or _is_mask_only[i + 1]:
            continue
        cs0, ce0, bs0, be0, t0, src0, lay0 = cues[i]
        cs1, ce1, bs1, be1, t1, src1, lay1 = cues[i + 1]
        if lay0 != "horizontal" or lay1 != "horizontal":
            continue
        # cắt tại giữa [end0, start1] (clip timeline), không theo cover pad
        # lấy segment gốc từ ids
        sid0 = cue_segment_ids[i] if i < len(cue_segment_ids) else ""
        sid1 = cue_segment_ids[i + 1] if i + 1 < len(cue_segment_ids) else ""
        seg0 = next((s for s in segments if str(s.get("id") or "") == sid0), None)
        seg1 = next((s for s in segments if str(s.get("id") or "") == sid1), None)
        e0 = float(seg0["end"]) if seg0 else be0
        s1 = float(seg1["start"]) if seg1 else bs1
        cut = (e0 + s1) * 0.5
        if ce0 > cut:
            cues[i] = (cs0, min(ce0, cut), bs0, be0, t0, src0, lay0)
        if cs1 < cut:
            cues[i + 1] = (max(cs1, cut), ce1, bs1, be1, t1, src1, lay1)
    # Không cho cửa sổ burn chữ dịch chồng nhau — chỉ hardsub đáy (ngang).
    # vertical/label/mid khác vị trí → được phép overlap (watermark dọc xuyên clip).
    for i in range(len(cues) - 1):
        if _is_mask_only[i] or _is_mask_only[i + 1]:
            continue
        if _caption_uses_dub_timing[i] or _caption_uses_dub_timing[i + 1]:
            continue
        cs0, ce0, bs0, be0, t0, src0, lay0 = cues[i]
        cs1, ce1, bs1, be1, t1, src1, lay1 = cues[i + 1]
        if lay0 != "horizontal" or lay1 != "horizontal":
            continue
        if be0 > bs1:
            cut = (be0 + bs1) * 0.5
            cues[i] = (cs0, ce0, bs0, max(bs0 + 0.04, cut), t0, src0, lay0)
            cues[i + 1] = (cs1, ce1, min(be1 - 0.04, cut), be1, t1, src1, lay1)

    # Extend cover of the last horizontal cue to video end if there's a small gap
    # — hardsub often lingers after the last ASR segment ends.
    if cues and vid_dur > 0:
        last_horz = -1
        for i in range(len(cues) - 1, -1, -1):
            if not _is_mask_only[i] and cues[i][6] == "horizontal":
                last_horz = i
                break
        if last_horz >= 0:
            cs0, ce0, bs0, be0, t0, src0, lay0 = cues[last_horz]
            gap_to_end = vid_dur - ce0
            if 0.0 < gap_to_end < 1.5:
                cues[last_horz] = (cs0, vid_dur, bs0, be0, t0, src0, lay0)

    ocr = None
    segments_by_id = {str(seg.get("id") or ""): seg for seg in segments}
    auto_band_boxes = [
        box for box in (_segment_bbox_override(seg, w, h, accept_automatic=True) for seg in auto_band_segments)
        if box is not None
    ]
    manual_by_idx: list[tuple[int, int, int, int] | None] = []
    unverified_auto_by_idx: list[bool] = []
    for sid in cue_segment_ids:
        seg = segments_by_id.get(sid, {})
        layout = str(seg.get("layout") or "horizontal")
        # Preview places every normal caption inside its nearest fixed auto
        # band.  Export must use that same box, not the cue's old OCR bbox.
        if (
            auto_band_boxes
            and cover
            and not seg.get("maskOnly")
            and layout in ("horizontal", "mid")
        ):
            raw_box = _segment_bbox_override(seg, w, h, accept_automatic=True)
            center = ((raw_box[1] + raw_box[3]) * 0.5) if raw_box else h * 0.84
            mb = min(
                auto_band_boxes,
                key=lambda box: abs(((box[1] + box[3]) * 0.5) - center),
            )
            unverified_auto_by_idx.append(False)
            manual_by_idx.append(mb)
            continue
        # A borrowed locator bbox is only a hint.  It may be from a different
        # subtitle row/shot, so re-measure this cue instead of rendering a
        # huge or vertically shifted cover from stale cache geometry.
        unverified_auto = (
            seg.get("bboxInherited") is True
            and seg.get("bboxDetected") is not True
        )
        unverified_auto_by_idx.append(unverified_auto)
        mb = _segment_bbox_override(seg, w, h)
        # Bbox đáy bake sẵn + source CJK → bỏ, OCR lại vị trí thật (giữa/đáy)
        manual_by_idx.append(mb)
    cue_segment_map = {str(seg.get("id") or ""): seg for seg in segments}
    cue_boxes: list[list[tuple[int, int, int, int]]] = [[] for _ in cues]
    for i, mb in enumerate(manual_by_idx):
        if mb is not None:
            cue_boxes[i] = [mb]

    need_ocr_idx = [i for i, mb in enumerate(manual_by_idx) if mb is None]
    manual_n = len(cues) - len(need_ocr_idx)
    if need_ocr_idx and (cover or burn) and cues:
        try:
            ocr = _rapidocr_labels()
        except ImportError:
            ocr = None
        if ocr is not None:
            if project_id:
                set_status(
                    project_id,
                    step="export",
                    progress=10,
                    message=(
                        f"Định vị hardsub ({len(need_ocr_idx)} câu)…"
                        if manual_n
                        else "Định vị hardsub…"
                    ),
                    running=True,
                )
            if len(need_ocr_idx) == len(cues):
                from pipeline.core.resources import adaptive_workers, gpu_job_cap

                cuda = bool(_rapidocr_gpu_kwargs()["det_use_cuda"])
                ocr_w = adaptive_workers(
                    workers,
                    kind="gpu" if cuda else "cpu",
                    cap=gpu_job_cap() if cuda else max(1, workers or 8),
                    tasks=len(cues),
                )
                cue_boxes = _precompute_cue_boxes(
                    video,
                    cues,
                    ocr,
                    project_id=project_id,
                    workers=ocr_w,
                )
            else:
                import cv2 as _cv2

                probe = _cv2.VideoCapture(str(video))
                try:
                    fh = int(probe.get(_cv2.CAP_PROP_FRAME_HEIGHT) or h)
                    fw = int(probe.get(_cv2.CAP_PROP_FRAME_WIDTH) or w)
                finally:
                    probe.release()
                from pipeline.core.resources import adaptive_workers, gpu_job_cap

                cuda = bool(_rapidocr_gpu_kwargs()["det_use_cuda"])
                ocr_workers = adaptive_workers(
                    workers,
                    kind="gpu" if cuda else "cpu",
                    cap=gpu_job_cap() if cuda else 16,
                    tasks=len(need_ocr_idx),
                )
                with ThreadPoolExecutor(
                    max_workers=ocr_workers, thread_name_prefix="ocr"
                ) as pool:
                    for i, boxes in pool.map(
                        lambda idx: (idx, _ocr_cue_boxes(video, cues[idx], ocr, fw, fh)),
                        need_ocr_idx,
                    ):
                        cue_boxes[i] = boxes
            ocr = None
    elif manual_n and (cover or burn) and project_id:
        set_status(
            project_id,
            step="export",
            progress=15,
            message=f"Dùng vùng che đã chỉnh trong preview ({manual_n} câu)",
            running=True,
        )

    if cover:
        # Run after missing boxes have been OCR'd; doing this before OCR left
        # newly detected upper/lower rows uncovered when blurBandMode was off.
        cue_boxes = _merge_overlapping_caption_cue_boxes(
            cues, cue_segment_ids, cue_boxes, cue_segment_map, w, h,
        )

    if project_id and (cover or burn) and cues:
        set_status(
            project_id,
            step="export",
            progress=16,
            message=f"Chuẩn bị caption / mask ({len(cues)} câu)…",
            running=True,
        )

    font_cache: dict[int, Any] = {fontsize: font}

    def _font_for_size(size: int):
        fs = max(8, min(120, int(size)))
        cached = font_cache.get(fs)
        if cached is not None:
            return cached
        cached = ImageFont.truetype(_font_for_preset(subtitle_font_family), fs)
        font_cache[fs] = cached
        return cached

    # frame mẫu giữa cue label/dọc — expand cover theo mực chữ thật
    label_probe_frames: dict[int, Any] = {}
    if any(
        _should_paint_cover_mask(cover, (c[6] if len(c) > 6 else ""))
        and (c[6] if len(c) > 6 else "") in ("label", "vertical")
        for c in cues
    ):
        import cv2 as _cv2

        # Mỗi lần seek+decode ~130-150ms (sàn cứng, song song không giúp — đã đo).
        # Watermark/nhãn LẶP LẠI qua các câu (cùng chữ + cùng box) → chỉ dò MỘT
        # khung cho mỗi nhãn khác nhau rồi dùng chung: 100 câu nhãn ≈ 1-2 lần dò.
        import threading as _threading
        import time as _time

        groups: dict[tuple, list[int]] = {}
        for i, c in enumerate(cues):
            if (c[6] if len(c) > 6 else "") not in ("label", "vertical"):
                continue
            box = _union_box(list(cue_boxes[i])) if i < len(cue_boxes) and cue_boxes[i] else None
            key = (
                ((c[5] if len(c) > 5 else "") or "").strip(),
                c[6],
                tuple(v // 8 for v in box) if box else None,  # lượng tử 8px — OCR jitter
            )
            groups.setdefault(key, []).append(i)
        if groups:
            done_n = [0]
            lock = _threading.Lock()
            last_report = [0.0]

            def _probe_group(idxs: list[int]) -> None:
                # dò tại cue giữa nhóm (đại diện), chia sẻ frame cho cả nhóm
                rep = idxs[len(idxs) // 2]
                c = cues[rep]
                mid = (float(c[0]) + float(c[1])) * 0.5
                cap = _cv2.VideoCapture(str(video))
                try:
                    cap.set(_cv2.CAP_PROP_POS_MSEC, mid * 1000.0)
                    ok, fr = cap.read()
                finally:
                    cap.release()
                with lock:
                    if ok:
                        for i in idxs:
                            label_probe_frames[i] = fr
                    done_n[0] += 1
                    now = _time.monotonic()
                    if project_id and now - last_report[0] >= 1.0:
                        last_report[0] = now
                        set_status(
                            project_id,
                            step="export",
                            progress=16,
                            message=(
                                "Chuẩn bị caption / mask · dò khung nhãn "
                                f"{done_n[0]}/{len(groups)}…"
                            ),
                            running=True,
                        )

            n_probe = min(6, max(1, len(groups)))
            with ThreadPoolExecutor(
                max_workers=n_probe, thread_name_prefix="probe"
            ) as pool:
                list(pool.map(_probe_group, list(groups.values())))

    cue_overlays: list[tuple[Any, int, int] | None] = []
    # mỗi cue: 1+ vùng cover (nhãn multi-box)
    cue_fits: list[list[tuple[int, int, int, int]]] = []
    cue_need_mask: list[bool] = []
    import time as _time_prep

    _prep_last = 0.0
    for i, (_cs, _ce, _bs, _be, text, src, lay_mode) in enumerate(cues):
        # Layout + render chữ RGBA từng cue — video nhiều câu tốn chục giây,
        # báo x/y để UI không đứng im một message.
        if project_id and _time_prep.monotonic() - _prep_last >= 1.0:
            _prep_last = _time_prep.monotonic()
            set_status(
                project_id,
                step="export",
                progress=17,
                message=f"Chuẩn bị caption / mask · {i + 1}/{len(cues)} câu…",
                running=True,
            )
        segment_id = cue_segment_ids[i] if i < len(cue_segment_ids) else ""
        # Phải có TRƯỚC mọi nhánh: cue không burn (cover-only, maskOnly) vẫn đọc
        # seg_meta ở phần mask/logo bên dưới — gán trong `if burn and text` gây
        # UnboundLocalError (cue đầu) hoặc dùng meta của cue trước (stale).
        seg_meta = segments_by_id.get(segment_id, {})
        unverified_auto = unverified_auto_by_idx[i] if i < len(unverified_auto_by_idx) else False
        boxes = list(cue_boxes[i] if i < len(cue_boxes) else [])
        paint = _union_box(boxes) if boxes else None
        has_manual_bbox = manual_by_idx[i] is not None
        is_vert = lay_mode == "vertical"
        is_label = lay_mode == "label"
        is_mid = lay_mode == "mid"
        uses_bbox_caption = lay_mode in ("horizontal", "mid")
        src_s = (src or "").strip()
        use_label_style = is_label
        # Fallback paint: coverHardsubs hoặc overlay mid/dọc (preview vẫn mask khi burn)
        if paint is None and not unverified_auto and _should_paint_cover_mask(cover, lay_mode):
            from pipeline.ocr.overlay_cover import default_overlay_paint, is_mid_flash_source

            if is_vert:
                paint = default_overlay_paint("vertical", w, h)
            elif is_label:
                paint = default_overlay_paint("label", w, h)
            elif is_mid or is_mid_flash_source(src_s):
                paint = default_overlay_paint("mid", w, h)
            else:
                paint = (int(w * 0.08), int(h * 0.84), int(w * 0.92), int(h * 0.94))
            boxes = [paint]
        # OCR bbox giữa khung → che/chữ tại đó (không ép đáy dù layout=horizontal)
        paint_mid = False
        if paint is not None and not is_vert and not is_label:
            pcy = (paint[1] + paint[3]) * 0.5
            # Keep identical to FE effectiveOverlayLayout().
            paint_mid = h * 0.18 < pcy < h * mid_bottom_cutoff(w, h)
            if paint_mid:
                is_mid = True
        if is_vert and paint is not None:
            if has_manual_bbox:
                # bbox editor = khung mask/chữ — không expand ink lại
                boxes = [paint]
                layout_paint = paint
                ink = None
            else:
                x0, y0, x1, y1 = paint
                bw = x1 - x0
                if bw > int(w * 0.18):
                    half = max(12, min(int(w * 0.05), bw // 4 + 4))
                    if (x0 + x1) / 2 < w * 0.5:
                        x1 = min(w, x0 + half * 2)
                    else:
                        x0 = max(0, x1 - half * 2)
                cjk_paint = (x0, y0, x1, y1)
                # Cover = mực (CJK+HUAMUZI); caption cao theo cover, ngang bám CJK.
                ink = _expand_vertical_watermark_cover(
                    cjk_paint, w, h, frame_bgr=label_probe_frames.get(i)
                )
                paint = cjk_paint
                boxes = [ink]
                # cho layout: cùng cx CJK, cao đủ tới đáy ink
                layout_paint = (cjk_paint[0], ink[1], cjk_paint[2], ink[3])
        else:
            layout_paint = paint
            ink = None
        # nhãn: xử lý TỪNG box (không union to)
        label_tall = False
        cover_regions: list[tuple[int, int, int, int]] = []
        if use_label_style:
            if has_manual_bbox and paint is not None:
                cover_regions = [paint]
                boxes = [paint]
                label_tall = is_tall_label(paint)
            else:
                probe = label_probe_frames.get(i)
                raw_boxes = boxes if boxes else ([paint] if paint else [])
                refined: list[tuple[int, int, int, int]] = []
                for b in raw_boxes:
                    bb = b
                    if probe is not None:
                        try:
                            from pipeline.ocr.labels import expand_box_to_ink

                            bb = expand_box_to_ink(probe, bb, w, h)
                        except Exception:
                            pass
                    tall_b = is_tall_label(bb)
                    bb = clamp_label_box(bb, w, h, force_tall=tall_b)
                    refined.append(bb)
                boxes = refined or boxes
                # paint = box chính (lớn nhất) để đặt chữ
                if boxes:
                    paint = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                label_tall = bool(paint) and is_tall_label(paint)
                for b in boxes:
                    fit = cover_fit_label(
                        b,
                        None,
                        w,
                        h,
                        frame_bgr=probe,
                        force_tall=is_tall_label(b),
                    )
                    if fit:
                        cover_regions.append(fit)
        cover_box: tuple[int, int, int, int] | None = None
        cue_fs = fontsize
        used_preview_layout = False
        if burn and text:
            cue_font_getter = _font_for_size
            cue_font_family = str(seg_meta.get("fontFamily") or "").strip()
            if cue_font_family:
                cue_font_cache: dict[int, Any] = {}

                def cue_font_getter(size: int):
                    fs = max(8, min(120, int(size)))
                    cached = cue_font_cache.get(fs)
                    if cached is None:
                        try:
                            cached = ImageFont.truetype(_font_for_preset(cue_font_family), fs)
                        except OSError:
                            cached = _font_for_size(fs)
                        cue_font_cache[fs] = cached
                    return cached
            cue_fs = _resolve_segment_font_size(
                seg_meta, w, h,
                project_font_size=subtitle_font_size,
                default_font_size=fontsize,
                auto_fontsize=auto_fontsize,
            )
            cue_font = cue_font_getter(cue_fs)
            cue_font_path = str(
                getattr(cue_font, "path", "")
                or _font_for_preset(cue_font_family or subtitle_font_family)
            )
            # WYSIWYG: captionLayout từ editor (đã bake giống preview lúc Xuất)
            preview_lay = _preview_caption_layout(
                seg_meta, cue_fs, cue_font_getter, layout_mode=lay_mode,
            )
            editor_locked = _editor_layout_locked(seg_meta)
            lay: dict[str, Any] | None = None
            # below/above: không ép mid layout "over" — dùng placement above/below OCR
            force_below_above = ((not cover) or unverified_auto) and place in ("below", "above")
            # Caption + CAP-MID share the same bbox-fitting engine. Their tags
            # and timing lanes remain separate.
            if uses_bbox_caption and paint is not None and not force_below_above:
                if preview_lay is not None and editor_locked:
                    lay = preview_lay
                    cover_box = paint
                    used_preview_layout = True
                else:
                    cl = seg_meta.get("captionLayout") if isinstance(seg_meta.get("captionLayout"), dict) else {}
                    mid_pref = int(
                        seg_meta.get("fontSize")
                        or (cl.get("fontSize") if cl else 0)
                        or 0
                    )
                    lay = _layout_mid_caption(
                        text,
                        cue_font_getter,
                        paint,
                        w,
                        h,
                        preferred_fs=mid_pref,
                    )
                    cover_box = paint if lay else paint
                    used_preview_layout = cover_box is not None
            elif preview_lay is not None:
                use_preview = True
                if not editor_locked:
                    if paint is not None and paint_mid:
                        if _caption_layout_looks_bottom(seg_meta, h) or (
                            has_manual_bbox and _bbox_looks_bottom(paint, h)
                        ):
                            use_preview = False
                        elif _bbox_looks_bottom(preview_lay["box"], h) and paint_mid:
                            use_preview = False
                    if use_preview and not paint_mid:
                        if (
                            _caption_layout_looks_bottom(seg_meta, h)
                            and sum(1 for c in src_s if "\u4e00" <= c <= "\u9fff") >= 2
                            and lay_mode in ("horizontal", "mid")
                        ):
                            use_preview = False
                if use_preview:
                    lay = preview_lay
                    used_preview_layout = True
                    if editor_locked:
                        mb = _segment_bbox_override(seg_meta, w, h)
                        cover_box = mb if mb is not None else (paint if paint is not None else preview_lay["box"])
                    elif has_manual_bbox and paint is not None and not paint_mid:
                        cover_box = paint
                    elif paint_mid and paint is not None:
                        cover_box = paint
                    else:
                        mb = _segment_bbox_override(seg_meta, w, h)
                        if mb is not None and not _stored_cover_should_relocate(seg_meta, mb, h):
                            cover_box = mb
                        else:
                            cover_box = paint
            if lay is None and is_vert:
                lay = _layout_caption_vertical(
                    text, cue_font, cue_fs, layout_paint if layout_paint else paint, w, h
                )
            elif lay is None and uses_bbox_caption and paint is not None and not force_below_above:
                mid_pref = int(seg_meta.get("fontSize") or 0)
                lay = _layout_mid_caption(
                    text,
                    cue_font_getter,
                    paint,
                    w,
                    h,
                    preferred_fs=mid_pref,
                )
                cover_box = lay["box"] if lay else paint
            elif lay is None and use_label_style:
                lab_fs = max(18, int(cue_fs * (0.75 if is_label else 0.85)))
                lay = layout_label_caption(
                    text,
                    cue_font,
                    lab_fs,
                    paint,
                    w,
                    h,
                    font_path=cue_font_path,
                    force_vertical=label_tall,
                    source=src_s,
                )
            elif lay is None and ((layout_place == "over" and not unverified_auto) or has_manual_bbox) and paint is not None:
                # Overlay OCR không có captionLayout → classic / manual / auto-over
                from pipeline.ocr.overlay_cover import (
                    classic_cover_fit,
                    use_classic_overlay_cover,
                )

                if has_manual_bbox:
                    cover_box = paint
                if use_classic_overlay_cover(
                    layout=lay_mode,
                    source=src_s,
                    has_preview_layout=False,
                ):
                    # đường riêng overlay — layout chữ trong OCR box + cover fit c9
                    lay = _layout_caption(
                        text, cue_font, cue_fs, paint, w, h, placement="over"
                    )
                    cover_box = classic_cover_fit(
                        boxes if boxes else ([paint] if paint else []),
                        lay["box"] if lay else None,
                        w,
                        h,
                    )
                elif has_manual_bbox:
                    lay = _layout_caption_in_cover(
                        text, cue_fs, paint, w, cue_font_getter,
                    )
                    cover_box = paint
                else:
                    lay, cover_box = _layout_caption_over(
                        text, cue_fs, paint, w, h,
                        source_text=src_s,
                        font_path=cue_font_path,
                    )
            elif lay is None:
                lay = _layout_caption(
                    text, cue_font, cue_fs, paint, w, h,
                    placement=place if unverified_auto else layout_place,
                )
        else:
            lay = None
        if lay is not None:
            # In cover mode the Editor renders text inside the full mask bbox;
            # captionLayout contributes only its committed lines/font size.
            # css mode = nhánh JSX preview thật: overlay(textarea) / logo text /
            # nhãn / dọc / mid (cover hoặc kéo tay) / caption đáy below-above.
            if used_preview_layout:
                if seg_meta.get("overlayText"):
                    css_mode = "overlay"
                elif seg_meta.get("logoText"):
                    css_mode = "horizontal"
                elif is_label:
                    css_mode = "label"
                elif is_vert:
                    css_mode = "vertical"
                elif cover or seg_meta.get("bboxInherited") is False:
                    css_mode = "mid"
                else:
                    css_mode = "horizontal"
                lay = {**lay, "css_cover_mode": css_mode}
                if cover and cover_box is not None:
                    lay["box"] = cover_box
                elif css_mode in ("mid", "label", "vertical") and not seg_meta.get("overlayText"):
                    # below/above: dọc/nhãn/kéo-tay vẫn vẽ trong cover như preview
                    ov_box = cover_box or _segment_bbox_override(seg_meta, w, h)
                    if ov_box is not None:
                        lay["box"] = ov_box
            lay = {
                **lay,
                "fill_hex": str(seg_meta.get("textColor") or cap_fill_hex),
                "bg_style": cap_bg_style,
                "bg_hex": cap_bg_hex,
                "bg_opacity": cap_bg_op,
                "stroke": cap_stroke,
            }
        logo_asset = str(seg_meta.get("logoAssetPath") or "")
        cue_overlays.append(
            _image_overlay(logo_asset, tuple(map(int, lay["box"])))
            if logo_asset and lay else (_caption_overlay(lay) if lay else None)
        )
        # cover=True: che hardsub; below/above: chỉ dọc/nhãn (không che mid)
        # is_mid khi cover=False không được bật mask (tránh giống «che chữ + chèn»)
        need_mask = _should_paint_cover_mask(
            cover, lay_mode if not (is_mid and not cover) else ("mid" if cover else "horizontal")
        )
        if not cover and is_mid:
            need_mask = False
        if seg_meta.get("skipCoverMask"):
            need_mask = False
        if unverified_auto:
            need_mask = False
        if seg_meta.get("maskOnly"):
            # Effect region: luôn che đúng bbox editor
            need_mask = True
            paint = _segment_bbox_override(seg_meta, w, h) or paint
            cover_box = paint
        cue_need_mask.append(need_mask)
        if need_mask:
            if seg_meta.get("maskOnly") and paint is not None:
                cue_fits.append([paint])
            elif used_preview_layout and cover_box is not None:
                cue_fits.append([cover_box])
            elif used_preview_layout and paint is not None:
                cue_fits.append([paint])
            elif use_label_style:
                # chữ nằm trên paint — nới cover chính nếu cần, vẫn từng box
                if lay and paint is not None and not has_manual_bbox:
                    main = cover_fit_label(
                        paint,
                        lay["box"],
                        w,
                        h,
                        frame_bgr=label_probe_frames.get(i),
                        force_tall=label_tall,
                    )
                    if main:
                        # thay box chính trong regions
                        cover_regions = [
                            main
                            if (
                                abs(r[0] - paint[0]) < 30
                                and abs(r[1] - paint[1]) < 30
                            )
                            else r
                            for r in cover_regions
                        ]
                        if not any(
                            abs(r[0] - main[0]) < 20 and abs(r[1] - main[1]) < 20
                            for r in cover_regions
                        ):
                            cover_regions.append(main)
                cue_fits.append(cover_regions or ([paint] if paint else []))
            elif is_vert and paint is not None:
                # Cover đã tính ink ở boxes[0]
                cov = boxes[0] if boxes else paint
                cue_fits.append([cov])
            elif is_mid and paint is not None:
                cb = cover_box if cover_box is not None else paint
                # nới nhẹ X cho stroke; Y giữ sát (pad locate đã đủ)
                px = max(6, int(round(w * 0.008)))
                py = max(3, int(round(h * 0.002)))
                cue_fits.append(
                    [
                        (
                            max(0, cb[0] - px),
                            max(0, cb[1] - py),
                            min(w, cb[2] + px),
                            min(h, cb[3] + py),
                        )
                    ]
                )
            else:
                if layout_place == "over" and cover_box is not None:
                    # Đúng khung preview — không _cover_box_over (fit/phình lại)
                    cue_fits.append([cover_box])
                elif layout_place == "over" and has_manual_bbox and paint is not None:
                    cue_fits.append([paint])
                elif layout_place == "over" and lay:
                    cue_fits.append([lay["box"]])
                elif has_manual_bbox and paint is not None and layout_place != "over":
                    cue_fits.append([paint])
                else:
                    one = _cover_box_fit(
                        boxes,
                        lay["box"] if lay else None,
                        w,
                        h,
                        tight=layout_place == "over",
                    )
                    cue_fits.append([one] if one else [])
        else:
            cue_fits.append([])

    # P1: thử ffmpeg vẽ trực tiếp (nhanh 6-8×, khung không rời GPU);
    # không khả thi / lỗi → đường Python cũ vẫn nguyên.
    from .ffgraph import try_render_ffmpeg

    has_feathered_blur = mask_style == "feather" or any(
        str(segment.get("coverMaskStyle") or "").lower() == "feather"
        for segment in segments_by_id.values()
    )
    # ponytail: browser preview uses a backdrop-filter glass effect for auto
    # subtitle lanes. FFmpeg's gblur graph is intentionally faster but not
    # visually equivalent, so use the shared pixel mask renderer for these
    # lanes (and feather) until the graph can reproduce that compositing.
    # Ceiling: exports with automatic blur trade throughput for WYSIWYG;
    # upgrade path: implement the same glass blend in ffgraph.py.
    # The FFmpeg fast path has no per-cue timeline object after the graph is
    # assembled.  Keep cascaded TTS captions on the frame renderer, where the
    # exact spoken start/end is applied to each prepared overlay.
    needs_preview_accurate_mask = has_feathered_blur or bool(auto_band_segments) or bool(dub_windows)
    if not needs_preview_accurate_mask and try_render_ffmpeg(
        video,
        out,
        cues=cues,
        cue_need_mask=cue_need_mask,
        cue_fits=cue_fits,
        cue_overlays=cue_overlays,
        cue_segment_ids=cue_segment_ids,
        segments_by_id=segments_by_id,
        mask_style=mask_style,
        mask_color=mask_color,
        mask_opacity=mask_opacity,
        burn=burn,
        w=w,
        h=h,
        project_id=project_id,
        post_crop=post_crop,
        post_height=post_height,
        video_scale_x=video_scale_x,
        video_scale_y=video_scale_y,
        render_info=render_info,
    ):
        if project_id:
            set_status(
                project_id,
                step="export",
                progress=70,
                message="Xuất khung (ffmpeg trực tiếp) xong",
                running=True,
            )
        return out
    return render_burned_video(
        video,
        out,
        cues=cues,
        cue_need_mask=cue_need_mask,
        cue_fits=cue_fits,
        cue_overlays=cue_overlays,
        cue_segment_ids=cue_segment_ids,
        segments_by_id=segments_by_id,
        mask_style=mask_style,
        mask_color=mask_color,
        mask_opacity=mask_opacity,
        burn=burn,
        w=w,
        h=h,
        workers=workers,
        project_id=project_id,
    )
