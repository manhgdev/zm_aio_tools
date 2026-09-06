import pytest

pytest.importorskip("fastapi", reason="Python hệ thống thiếu fastapi — test API chạy trong venv backend")

from api.deps import StudioSynthIn
from api.routes.tts_studio import _tts_job_artifact, api_tts_studio_synth
from pipeline.tts import studio


def test_tts_studio_schema_covers_text_and_srt(monkeypatch):
    monkeypatch.setattr(studio, "synth_text_job", lambda **kwargs: kwargs)
    monkeypatch.setattr(studio, "synth_srt_job", lambda **kwargs: kwargs)

    text = api_tts_studio_synth(StudioSynthIn(
        jobId="frontend01",
        text="Xin chào",
        voice="voice-1",
        autoSplit=True,
        gapMs=300,
    ))
    assert text["id"] == "frontend01"
    assert text["job_id"] == "frontend01"
    assert text["running"] is True

    srt = api_tts_studio_synth(StudioSynthIn(
        srtText="1\n00:00:00,000 --> 00:00:01,000\nXin chào",
        speaker_id="speaker-1",
        keepTimeline=True,
    ))
    assert srt["running"] is True


def test_tts_desktop_reveal_resolves_requested_artifact(monkeypatch, tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"wav")
    monkeypatch.setattr(studio, "ensure_wav", lambda _: wav)
    monkeypatch.setattr(studio, "published_job_output_dir", lambda _: tmp_path)

    assert _tts_job_artifact("job-1", "wav") == wav


def test_tts_progress_keeps_terminal_worker_errors_visible():
    job_id = "progress-error"
    studio.set_job_progress(job_id, 1, 100, "Đang khởi tạo TTS…")
    studio.set_job_error(job_id, RuntimeError("runtime unavailable"))

    progress = studio.get_job_progress(job_id)

    assert progress["done"] is True
    assert progress["error"] == "runtime unavailable"
    assert progress["pct"] == 1
    with studio._jobs_lock:
        studio._job_progress.pop(job_id, None)


def test_tts_progress_completes_the_request_id_after_a_cache_hit():
    job_id = "progress-cache"
    studio.set_job_progress(job_id, 1, 100, "Đang khởi tạo TTS…")
    studio.set_job_complete(job_id, result_job_id="cached-output")

    progress = studio.get_job_progress(job_id)

    assert progress["done"] is True
    assert progress["pct"] == 99
    assert progress["resultJobId"] == "cached-output"
    with studio._jobs_lock:
        studio._job_progress.pop(job_id, None)


def test_publish_tts_keeps_srt_and_bundle_in_selected_output(monkeypatch, tmp_path):
    job_dir = tmp_path / "backend-job"
    job_dir.mkdir()
    (job_dir / "audio.wav").write_bytes(b"wav")
    (job_dir / "audio.mp3").write_bytes(b"mp3")
    (job_dir / "subs.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào\n", encoding="utf-8")
    (job_dir / "meta.json").write_text("{}", encoding="utf-8")
    selected = tmp_path / "selected"
    target = selected / "job-1"
    target.mkdir(parents=True)
    bundle = job_dir / "bundle.zip"
    bundle.write_bytes(b"zip")

    monkeypatch.setattr(studio, "_job_dir", lambda _: job_dir)
    monkeypatch.setattr(studio, "selected_or_default", lambda *_: selected)
    monkeypatch.setattr(studio, "item_output_folder", lambda *_: target)
    monkeypatch.setattr(studio, "ensure_wav", lambda _: job_dir / "audio.wav")
    monkeypatch.setattr(studio, "ensure_mp3", lambda _: job_dir / "audio.mp3")
    monkeypatch.setattr(studio, "ensure_zip", lambda *_args, **_kwargs: bundle)

    assert studio.publish_job_outputs("job-1") == target
    assert (target / "subtitles.srt").is_file()
    assert (target / "bundle.zip").is_file()
    assert studio.published_job_output_dir("job-1") == target
