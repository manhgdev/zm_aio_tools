import hashlib
import zipfile

import httpx
import pytest

from pipeline.srt_export import _caption_cues, _pick_platform_language, _styled, _translated_cues, _write_outputs, _zip_outputs


def test_capcut_completed_cues_skip_a_second_upload(monkeypatch, tmp_path):
    from pipeline import capcut_stt

    source = tmp_path / "source.mp4"
    source.write_bytes(b"same video")
    monkeypatch.setattr(capcut_stt, "_CAPCUT_CACHE_DIR", tmp_path / "capcut-cache")
    md5 = hashlib.md5(source.read_bytes()).hexdigest()
    rows = [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    translated = [{"start": 0.0, "end": 1.0, "text": "Xin chao"}]
    capcut_stt._write_cached_cues(md5, "en", "vi", rows, translated)
    monkeypatch.setattr(capcut_stt, "_upload", lambda *_args: (_ for _ in ()).throw(AssertionError("must not upload")))

    assert capcut_stt.transcribe_and_translate(source, "en", "vi") == (rows, translated)
    assert capcut_stt._load_cached_cues(md5, "en", "ja") is None
    assert capcut_stt._load_cached_cues(hashlib.md5(b"changed video").hexdigest(), "en", "vi") is None


def test_capcut_vod_transfer_ret_2000_is_success():
    """VOD upload APIs use 2000/Success rather than the editor API's 0."""
    from pipeline.capcut_stt import _json

    class Client:
        def request(self, *_args, **_kwargs):
            return httpx.Response(200, json={"ret": 2000, "errmsg": "Success"})

    assert _json(Client(), "POST", "https://upload.invalid", headers={}) == {
        "ret": 2000,
        "errmsg": "Success",
    }


def test_capcut_large_media_uses_a_small_proxy(monkeypatch, tmp_path):
    from pipeline import capcut_stt

    source = tmp_path / "source.mp4"
    with source.open("wb") as stream:
        stream.truncate(capcut_stt.CAPCUT_MAX_UPLOAD_BYTES + 1)
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"small proxy")
    seen = {}

    def make_proxy(path, check, progress):
        seen["path"] = path
        return proxy

    monkeypatch.setattr(capcut_stt, "_create_media_proxy", make_proxy)
    upload, temporary = capcut_stt._prepare_upload_media(source, None, None)

    assert upload == proxy
    assert temporary == proxy
    assert seen["path"] == source


def test_capcut_rejects_proxy_that_still_exceeds_limit(monkeypatch, tmp_path):
    from pipeline import capcut_stt

    source = tmp_path / "source.mp4"
    with source.open("wb") as stream:
        stream.truncate(capcut_stt.CAPCUT_MAX_UPLOAD_BYTES + 1)
    proxy = tmp_path / "proxy.mp4"
    with proxy.open("wb") as stream:
        stream.truncate(capcut_stt.CAPCUT_MAX_UPLOAD_BYTES + 1)

    monkeypatch.setattr(capcut_stt, "_create_media_proxy", lambda *_args: proxy)
    with pytest.raises(capcut_stt.CapCutSttError, match="CAPCUT_MEDIA_TOO_LARGE"):
        capcut_stt._prepare_upload_media(source, None, None)


def test_capcut_chunked_audio_merges_cues_with_each_chunk_offset(monkeypatch, tmp_path):
    from pipeline import capcut_stt

    first = tmp_path / "chunk-000.m4a"
    second = tmp_path / "chunk-001.m4a"
    first.touch()
    second.touch()
    monkeypatch.setattr(capcut_stt, "_split_audio_chunks", lambda *_args: [(first, 900.06), (second, 12.0)])

    def transcribe(chunk, *_args, **_kwargs):
        if chunk == first:
            return ([{"start": 1.0, "end": 2.0, "text": "one"}], [{"start": 1.0, "end": 2.0, "text": "một"}])
        return ([{"start": 0.5, "end": 1.5, "text": "two"}], [{"start": 0.5, "end": 1.5, "text": "hai"}])

    monkeypatch.setattr(capcut_stt, "transcribe_and_translate", transcribe)
    source, translated = capcut_stt._transcribe_chunked_audio(tmp_path / "large.mp4", "en", "vi")

    assert [(row["start"], row["end"], row["text"]) for row in source] == [
        (1.0, 2.0, "one"), (900.5, 901.5, "two"),
    ]
    assert [row["text"] for row in translated] == ["một", "hai"]


def test_capcut_large_input_uses_chunked_audio_and_caches_merged_result(monkeypatch, tmp_path):
    from pipeline import capcut_stt

    source = tmp_path / "source.mp4"
    source.write_bytes(b"large")
    rows = [{"start": 0.0, "end": 1.0, "text": "one"}]
    translated = [{"start": 0.0, "end": 1.0, "text": "một"}]
    stored = {}
    monkeypatch.setattr(capcut_stt, "CAPCUT_MAX_UPLOAD_BYTES", 1)
    monkeypatch.setattr(capcut_stt, "_file_hashes", lambda *_args: ("source-md5", "crc"))
    monkeypatch.setattr(capcut_stt, "_load_cached_cues", lambda *_args: None)
    monkeypatch.setattr(capcut_stt, "_transcribe_chunked_audio", lambda *_args, **_kwargs: (rows, translated))
    monkeypatch.setattr(capcut_stt, "_write_cached_cues", lambda *args: stored.setdefault("value", args))

    assert capcut_stt.transcribe_and_translate(source, "en", "vi") == (rows, translated)
    assert stored["value"][0] == "source-md5"


def test_capcut_poll_progress_reports_state_elapsed_and_poll_count():
    from pipeline.capcut_stt import _poll_progress_message, _task_progress

    assert _poll_progress_message("queueing", 6.4, 4) == "CapCut: đang xếp hàng trên CapCut · đã chờ 6s · kiểm tra #4"
    assert _poll_progress_message("processing", 6.4, 4, 23) == "CapCut: CapCut đang nhận dạng và dịch · 23% · đã chờ 6s · kiểm tra #4"
    assert _poll_progress_message("success", 6.4, 4, 100) == "CapCut: CapCut đã hoàn tất · 100% · đã chờ 6s · kiểm tra #4"
    assert "đang chờ phản hồi" in _poll_progress_message("", 0, 0)
    assert _task_progress({"progress": "99"}) == 99
    assert _task_progress({"percent": 150}) == 100
    assert _task_progress({"progress": "unknown"}) is None


def test_capcut_task_without_status_is_not_treated_as_running():
    from pipeline.capcut_stt import _task_status

    assert _task_status({"data": {"tasks": [{}]}}) == ({}, "")
    task, status = _task_status({"data": {"tasks": [{"status": "queueing"}]}})
    assert task == {"status": "queueing"}
    assert status == "queueing"
    assert _task_status({"data": {"tasks": [{"task_status": "completed"}]}})[1] == "success"
    assert _task_status({"data": {"tasks": [{"status": "succeed"}]}})[1] == "success"


def test_capcut_text_only_translation_is_not_silently_replaced_by_google():
    from pipeline.mt.api import translate_segments

    with pytest.raises(RuntimeError, match="CapCut cloud"):
        translate_segments(["hello"], "vi", translator="capcut")


def test_capcut_subtitle_payload_keeps_timestamps_and_translation():
    from pipeline.capcut_stt import subtitle_cues

    source, translated = subtitle_cues({"utterances": [{
        "text": "你好", "translation": "Xin chào", "start_time": 1250, "end_time": 3400,
    }]})
    assert source == [{"start": 1.25, "end": 3.4, "text": "你好"}]
    assert translated == [{"start": 1.25, "end": 3.4, "text": "Xin chào"}]


def test_capcut_live_translation_text_alias_is_preserved():
    from pipeline.capcut_stt import subtitle_cues

    source, translated = subtitle_cues({"utterances": [{
        "text": "你好", "translation_text": "Xin chào", "start_time": 0, "end_time": 1000,
    }]})
    assert source[0]["text"] == "你好"
    assert translated[0]["text"] == "Xin chào"


def test_caption_input_keeps_timecodes_and_styles(tmp_path):
    source = tmp_path / "caption.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:05,000\nMột câu phụ đề đủ dài để được tách hợp lý.\n", encoding="utf-8")

    cues = _caption_cues(source)
    styled = _styled(cues, "v916")

    assert cues[0]["start"] == 1.0
    assert cues[0]["end"] == 5.0
    assert styled
    assert styled[0]["start"] == 1.0
    assert styled[-1]["end"] <= 5.0


def test_platform_prefers_creator_caption_and_requested_language():
    info = {"subtitles": {"en-US": [{}]}, "automatic_captions": {"vi": [{}]}}
    assert _pick_platform_language(info, "en") == ("en-US", "phụ đề có sẵn")
    assert _pick_platform_language(info, "vi") == ("vi", "phụ đề tự động")


def test_bilingual_exports_two_separate_sets(tmp_path):
    cues = [{"start": 1.0, "end": 2.0, "text": "Hello"}]
    translated = _translated_cues(cues, ["Xin chào"])
    source_files = _write_outputs(tmp_path, cues, "subtitles-source")
    translated_files = _write_outputs(tmp_path, translated, "subtitles-vi")
    assert "subtitles-source-hard.srt" in source_files
    assert "subtitles-vi-hard.srt" in translated_files
    assert "Hello\nXin chào" not in (tmp_path / "subtitles-vi-hard.srt").read_text(encoding="utf-8-sig")
    _zip_outputs(tmp_path, source_files + translated_files, bilingual=True, target_lang="vi")
    with zipfile.ZipFile(tmp_path / "subtitles-all.zip") as archive:
        assert "phu-de-goc/subtitles-source-hard.srt" in archive.namelist()
        assert "ban-dich-vi/subtitles-vi-hard.srt" in archive.namelist()
