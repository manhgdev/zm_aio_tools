"""EditPlan → existing project timeline/segments so the shared Editor can open it."""
from __future__ import annotations

from statistics import median
from pathlib import Path
from typing import Any

from pipeline.core.project import load_meta, save_meta, set_status
from pipeline.review.match import resolve_build_mode


def caption_export_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Map Review captionMode onto Clone export flags, including no captions."""
    lang = str(settings.get("language") or "vi")
    on = bool(settings.get("subtitle", True))
    # Captions are opt-in for Review. The legacy `subtitle` switch stays
    # supported, but cannot silently turn missing captionMode into cover mode.
    mode = str(settings.get("captionMode") or "off")
    if mode not in {"off", "cover", "below", "above"}:
        mode = "off"
    if not on or mode == "off":
        return {
            "targetLang": "none",
            "burnSubs": False,
            "coverHardsubs": False,
            "captionPlacement": "below",
        }
    return {
        "targetLang": lang,
        # The transcript-led Review script is the localized caption track.
        # Burn it in the detected source-subtitle lane for the cover mode too,
        # so exported video and Live Preview show the same translated caption.
        "burnSubs": True,
        "coverHardsubs": mode == "cover",
        # Cover replaces the original subtitle in its own lane. "below" here
        # placed the translated caption outside the blur band and could push it
        # toward the middle after a clip was resized.
        "captionPlacement": "over" if mode == "cover" else ("above" if mode == "above" else "below"),
    }


def locate_review_captions(
    project_id: str,
    compiled: Path,
    segments: list[dict[str, Any]],
    settings: dict[str, Any],
) -> int:
    """OCR-locate original hardsubs on the compiled review video (same helper as Clone)."""
    flags = caption_export_settings(settings)
    if not segments or not (flags["burnSubs"] or flags["coverHardsubs"]):
        return 0
    from pipeline.ocr.locate import attach_speech_hardsub_boxes

    n = attach_speech_hardsub_boxes(
        compiled,
        segments,
        only_missing=False,
        project_id=project_id,
        stable=bool(settings.get("stableCaptionLocate", False)),
        analysis_region=settings.get("analysisRegion"),
    )
    if flags["coverHardsubs"]:
        # Review narration is translated text, so matching it against the
        # source-language hardsub often returns zero boxes. Do not make export
        # OCR every cue a second time: use one stable lower-third band for
        # missing boxes. Users can still adjust it later in the shared editor.
        from pipeline.core.media import video_size

        width, height = video_size(compiled)
        fallback = _fallback_review_bbox(width, height)
        for segment in segments:
            if not isinstance(segment.get("bbox"), dict):
                segment["bbox"] = dict(fallback)
                segment["bboxInherited"] = True
                segment["layout"] = "horizontal"
    meta = load_meta(project_id) or {}
    meta["segments"] = segments
    meta["bboxLocateVersion"] = 3
    save_meta(project_id, meta)
    return int(n or 0)


def _fallback_review_bbox(width: int, height: int) -> dict[str, int]:
    """Slim, compact horizontal bottom band for Review (lower ~6.5%)."""
    width, height = max(64, int(width or 1920)), max(64, int(height or 1080))
    band_h = max(36, round(height * 0.065))
    return {
        "x": 0,
        "y": max(0, height - band_h - round(height * 0.025)),
        "w": width,
        "h": band_h,
    }


def _is_edge_watermark(box: tuple[int, int, int, int], width: int) -> bool:
    """True if box is a narrow corner element (logo/watermark), not a subtitle."""
    x0, _y0, x1, _y1 = box
    span = x1 - x0
    cx = (x0 + x1) / 2
    return span < width * 0.15 and (cx < width * 0.25 or cx > width * 0.75)


def _review_caption_box_from_boxes(
    boxes: list[tuple[int, int, int, int]], width: int, height: int
) -> "dict[str, int] | None":
    """Build a fixed subtitle band from ALL OCR boxes in the subtitle zone.

    Hardsub captions from audio-driven translation sit in a fixed Y band and
    only vary in horizontal extent (short vs long lines, 1-3 rows).  We take
    the *union* of every detected box, then expand upward by ~1 row height to
    cover any first line that OCR missed (e.g. strikethrough-style subtitles).
    """
    is_portrait = height > width
    # Subtitle zone lower boundary: portrait 50%, landscape 63%.
    zone_top = height * (0.50 if is_portrait else 0.63)
    # Absolute top clamp: never treat top-half UI elements as subtitles.
    min_top = height * (0.45 if is_portrait else 0.60)

    sub = [
        b for b in boxes
        if b[1] >= zone_top and not _is_edge_watermark(b, width)
    ]
    if not sub:
        return None

    y0 = min(b[1] for b in sub)
    y1 = max(b[3] for b in sub)

    # Median individual box height ≈ one subtitle row height.
    heights = sorted(b[3] - b[1] for b in sub)
    row_h = max(round(height * 0.035), heights[len(heights) // 2])

    # Expand up by ~1 row to catch undetected first line (OCR misses on
    # decorative/strikethrough hardsubs are common in portrait clips).
    # Expand down lightly for stroke/shadow below the last detected glyph.
    pad_top = max(round(height * 0.015), row_h)
    pad_bot = max(round(height * 0.012), round(row_h * 0.35))

    top = max(round(min_top), y0 - pad_top)
    bot = min(height, y1 + pad_bot)
    return {"x": 0, "y": top, "w": width, "h": bot - top}




def locate_review_caption_bands(
    video: Path,
) -> list[tuple[float, list[tuple[int, int, int, int]]]]:
    """Return raw OCR subtitle boxes per sampled frame.

    Each entry is (time_fraction, boxes) where boxes are raw pixel rectangles
    (x0, y0, x1, y1) in the subtitle zone.  Frames with no subtitle text are
    omitted.  The caller aggregates across all frames for stability.
    """
    from pipeline.core.media import ffprobe_duration, video_size

    width, height = video_size(video)
    try:
        import cv2
        from pipeline.ocr.extract import _rapidocr_labels

        duration = max(0.1, float(ffprobe_duration(video) or 0))
        ocr = _rapidocr_labels()
        cap = cv2.VideoCapture(str(video))
        frames: list[tuple[float, list[tuple[int, int, int, int]]]] = []
        is_portrait = height > width
        # Scan bottom 60% for portrait (hardsubs at 45-80%), bottom 37% for landscape.
        crop_fraction = 0.40 if is_portrait else 0.63
        zone_top = height * (0.50 if is_portrait else 0.63)
        try:
            # 9 evenly spaced samples → 3 per temporal third for stability.
            for fraction in (0.06, 0.16, 0.28, 0.42, 0.50, 0.58, 0.72, 0.84, 0.94):
                cap.set(cv2.CAP_PROP_POS_MSEC, duration * fraction * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    continue
                h, w = frame.shape[:2]
                y_crop = int(h * crop_fraction)
                results, _ = ocr(frame[y_crop:, :])
                boxes: list[tuple[int, int, int, int]] = []
                if results:
                    for item in results:
                        pts = item[0]
                        bx0 = int(min(p[0] for p in pts))
                        by0 = int(min(p[1] for p in pts)) + y_crop
                        bx1 = int(max(p[0] for p in pts))
                        by1 = int(max(p[1] for p in pts)) + y_crop
                        if by0 >= zone_top and not _is_edge_watermark((bx0, by0, bx1, by1), width):
                            boxes.append((bx0, by0, bx1, by1))
                if boxes:
                    frames.append((fraction, boxes))
        finally:
            cap.release()
        return frames
    except Exception:
        return []


def locate_review_caption_band(video: Path) -> dict[str, int]:
    """Find the fixed subtitle band for the whole video.

    Hardsub captions sit in a stable Y band (1-3 rows, varying left/right
    extent).  We collect *all* OCR detections across the video, take their
    union Y range, then expand upward by ~1 row to catch first lines that
    OCR misses due to decorative hardsub styles (strikethrough, outline, etc.).
    """
    from pipeline.core.media import video_size

    width, height = video_size(video)
    fallback = _fallback_review_bbox(width, height)
    frame_boxes = locate_review_caption_bands(video)
    if not frame_boxes:
        return fallback

    # Require detections in at least 2 different time thirds to reject
    # a transient scene title or animated logo that only appears once.
    thirds = {min(2, int(frac * 3)) for frac, _ in frame_boxes}
    all_boxes = [b for _, boxes in frame_boxes for b in boxes]
    if len(thirds) < 2 and len(all_boxes) < 3:
        return fallback

    result = _review_caption_box_from_boxes(all_boxes, width, height)
    return result or fallback


def apply_edit_plan(
    project_id: str,
    compiled: Path,
    plan: dict[str, Any],
    *,
    settings: dict[str, Any],
    voice: str,
) -> dict[str, Any]:
    meta = load_meta(project_id) or {}
    segments: list[dict[str, Any]] = []
    for i, seg in enumerate(plan.get("segments") or []):
        start = float(seg.get("voice_start") or 0)
        end = float(seg.get("voice_end") or start)
        audio = str(seg.get("audio") or "")
        text = str(seg.get("text") or "")
        item = {
            "id": str(seg.get("voice_id") or f"v{i:03d}"),
            "index": i,
            "start": start,
            "end": end,
            # Review narration has no source-language subtitle counterpart.
            # Keeping the same text in both fields made Editor show a fake
            # “original + translation” duplicate.
            "source": "",
            "translation": text,
            "sourceSubtitle": "",
            "dubSubtitle": text,
            "voice": voice,
            "dub": True,
            "layout": "horizontal",
        }
        if audio:
            item["audioFile"] = Path(audio).name
            item["audioUrl"] = f"/api/projects/{project_id}/tts/{Path(audio).name}"
            item["audioDuration"] = float(seg.get("audio_duration") or max(0.0, end - start))
            item["ttsSpeed"] = float(seg.get("tts_speed") or 1.0)
            item["ttsBake"] = float(seg.get("tts_bake") or 1.0)
        segments.append(item)
    meta["videoPath"] = str(compiled)
    meta["duration"] = float(plan.get("duration") or 0)
    meta["kind"] = "review"
    meta["editPlan"] = plan
    meta["segments"] = segments
    meta["settings"] = {
        **(meta.get("settings") or {}),
        **settings,
        **caption_export_settings(settings),
        "previewSec": 0,
        "exportVideo": True,
        "matchDuration": "preferAudio" if resolve_build_mode(settings) == "stretch" else "preferVideo",
        "processOriginalAudio": True,
        "originalAudioMode": "mute" if float(settings.get("originalAudioPct") or 0) <= 0.5 else "original",
        "originalAudioVolume": int(max(0, min(100, float(settings.get("originalAudioPct") or 0)))),
    }
    save_meta(project_id, meta)
    set_status(project_id, step="export", progress=80, message="Đã dựng timeline Review", running=True)
    return meta
