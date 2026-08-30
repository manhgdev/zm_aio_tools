from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="Python hệ thống thiếu fastapi — test API chạy trong venv backend")

from api.routes import rendered


def test_render_list_keeps_versions_and_thumbnail_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rendered, "PUBLIC_DATA", tmp_path)
    monkeypatch.setattr(rendered, "downloads_folder", lambda tab: tmp_path / "downloads" / tab)
    monkeypatch.setattr(rendered, "video_size", lambda _path: (1920, 1080))
    monkeypatch.setattr(rendered, "ffprobe_duration", lambda _path: 12.5)
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "project.mp4").write_bytes(b"latest")
    (exports / "project-100.mp4").write_bytes(b"first")
    (exports / "project-200.mp4").write_bytes(b"second")
    (exports / "project-200.json").write_text('{"name":"Bản đẹp"}', encoding="utf-8")

    rows = rendered.list_rendered_videos()
    assert {row["renderId"] for row in rows} == {"project-100", "project-200"}
    assert all(row["projectId"] == "project" for row in rows)
    assert rows[0]["thumbnailUrl"].startswith("/api/renders/")
    assert rendered.api_renders()["canReveal"] is False
    assert next(row for row in rows if row["renderId"] == "project-200")["name"] == "Bản đẹp"
    saved = rendered.api_rename_render("project-100", rendered.RenderRenameIn(name=" Bản mới "))
    assert saved["name"] == "Bản mới"
    assert '"name": "Bản mới"' in (exports / "project-100.json").read_text(encoding="utf-8")

    calls = []
    def fake_run(args, **_kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(rendered.subprocess, "run", fake_run)
    first = rendered.ensure_thumbnail("project-200")
    second = rendered.ensure_thumbnail("project-200")
    assert first == second
    assert first.read_bytes() == b"jpg"
    assert len(calls) == 1

    assert rendered.api_delete_render("project-200") == {"ok": True}
    assert not (exports / "project-200.mp4").exists()
    assert not (exports / "project-200.json").exists()
    assert not first.exists()
    # còn project-100 nên bản dễ tìm project.mp4 vẫn được giữ (đang bị ẩn)
    assert (exports / "project.mp4").exists()

    # xóa bản lưu trữ cuối cùng phải dọn luôn project.mp4, tránh video "hiện lại"
    assert rendered.api_delete_render("project-100") == {"ok": True}
    assert not (exports / "project-100.mp4").exists()
    assert not (exports / "project.mp4").exists()
    assert rendered.list_rendered_videos() == []


def test_render_list_includes_all_clone_and_review_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(rendered, "PUBLIC_DATA", tmp_path / "public")
    monkeypatch.setattr(rendered, "downloads_folder", lambda tab: tmp_path / "downloads" / tab)
    monkeypatch.setattr(rendered, "video_size", lambda _path: (1080, 1920))
    monkeypatch.setattr(rendered, "ffprobe_duration", lambda _path: 8.0)
    clone = tmp_path / "downloads" / "video-clone" / "Video bản đẹp.mp4"
    review = tmp_path / "downloads" / "film" / "Video bản đẹp.mp4"
    clone.parent.mkdir(parents=True)
    review.parent.mkdir(parents=True)
    clone.write_bytes(b"clone")
    review.write_bytes(b"review")

    rows = rendered.list_rendered_videos()

    assert len(rows) == 2
    assert {row["name"] for row in rows} == {"Video bản đẹp"}
    assert len({row["renderId"] for row in rows}) == 2
    assert all(row["renderId"].startswith("media-") for row in rows)
    assert {rendered._render_path(row["renderId"]) for row in rows} == {clone, review}


def test_render_list_includes_tts_and_subtitle_job_output_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(rendered, "PUBLIC_DATA", tmp_path / "public")
    monkeypatch.setattr(rendered, "downloads_folder", lambda tab: tmp_path / "downloads" / tab)
    monkeypatch.setattr(rendered, "ffprobe_duration", lambda _path: 4.0)

    tts_job = tmp_path / "downloads" / "tts" / "job-voice-01"
    subtitle_job = tmp_path / "downloads" / "subtitle-export" / "job-srt-01"
    tts_job.mkdir(parents=True)
    subtitle_job.mkdir(parents=True)
    (tts_job / "audio.wav").write_bytes(b"audio")
    (tts_job / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello", encoding="utf-8")
    (subtitle_job / "subtitles-vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào", encoding="utf-8")

    rows = rendered.list_rendered_videos()
    by_path = {rendered._render_path(row["renderId"]): row for row in rows}

    assert {row["type"] for row in rows} == {"audio", "srt"}
    assert by_path[tts_job / "audio.wav"]["outputFolder"] == str(tts_job)
    assert by_path[tts_job / "subtitles.srt"]["outputFolder"] == str(tts_job)
    assert by_path[subtitle_job / "subtitles-vi.srt"]["outputFolder"] == str(subtitle_job)
