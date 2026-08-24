from pipeline.cleaner import cleaner_ffmpeg
import zlib


def test_logo_filter_uses_icon_only_fallback_when_ocr_finds_nothing(monkeypatch):
    monkeypatch.setattr(
        "pipeline.ocr.logo.detect_logo_bbox_inprocess", lambda _path: None
    )
    monkeypatch.setattr(cleaner_ffmpeg, "video_size", lambda _path: (1080, 1920))

    result = cleaner_ffmpeg._logo_filter("video.mp4")

    assert result == "delogo=x=864:y=1709:w=86:h=115:show=0"


def test_logo_filter_prefers_detected_mask_over_icon_only_fallback(monkeypatch):
    monkeypatch.setattr(
        "pipeline.ocr.logo.detect_logo_bbox_inprocess",
        lambda _path: {"bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}},
    )
    monkeypatch.setattr(cleaner_ffmpeg, "video_size", lambda _path: (1000, 500))

    result = cleaner_ffmpeg._logo_filter("video.mp4")

    assert result == "delogo=x=100:y=100:w=300:h=50:show=0"


def test_logo_filter_retries_transient_runtime_decompression_error(monkeypatch):
    calls = 0

    def detect(_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise zlib.error("Error -3 while decompressing data: incorrect header check")
        return {"bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}}

    monkeypatch.setattr("pipeline.ocr.logo.detect_logo_bbox_inprocess", detect)
    monkeypatch.setattr(cleaner_ffmpeg, "video_size", lambda _path: (1000, 500))
    monkeypatch.setattr(cleaner_ffmpeg.time, "sleep", lambda _seconds: None)

    assert cleaner_ffmpeg._logo_filter("video.mp4") == "delogo=x=100:y=100:w=300:h=50:show=0"
    assert calls == 2
