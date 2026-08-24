from pipeline.cleaner import cleaner_ffmpeg
import zlib
from pipeline.cleaner import cleaner_jobs


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


def test_clear_job_logs_keeps_cleaner_jobs_and_output(monkeypatch):
    jobs = {"job-1": {"id": "job-1", "logs": ["queued", "done"], "output_path": "/tmp/output.mp4"}}
    monkeypatch.setattr(cleaner_jobs, "_JOBS", jobs)

    assert cleaner_jobs.clear_job_logs() == 1
    assert jobs["job-1"]["logs"] == []
    assert jobs["job-1"]["output_path"] == "/tmp/output.mp4"


def test_cleaner_file_uses_attachment_only_for_download(monkeypatch, tmp_path):
    from api.routes import cleaner

    output = tmp_path / "cleaned.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(cleaner, "get_job_output_path", lambda _job_id: output)

    inline = cleaner.api_cleaner_file("job-1")
    downloaded = cleaner.api_cleaner_file("job-1", download=1)

    assert "attachment" not in inline.headers.get("content-disposition", "")
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert "cleaned.mp4" in downloaded.headers["content-disposition"]
