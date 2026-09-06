import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from api.routes import projects
from api.deps import Settings


def test_settings_default_places_translated_caption_above() -> None:
    assert Settings().captionPlacement == "above"


def test_new_upload_returns_fresh_video_transform_settings(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(projects, "DATA", tmp_path)
    monkeypatch.setattr(projects, "video_fingerprint", lambda _path: "new-video")
    monkeypatch.setattr(projects, "find_project_by_fp", lambda _fp: None)
    monkeypatch.setattr(projects, "ensure_layout", lambda _project_id: root)
    monkeypatch.setattr(projects, "ffprobe_duration", lambda _path: 10.0)
    monkeypatch.setattr(projects, "save_meta", lambda _project_id, _meta: None)
    monkeypatch.setattr(
        "pipeline.core.media.ensure_project_initial_playback_rate",
        lambda _meta, _settings: None,
    )

    result = asyncio.run(
        projects.api_upload(UploadFile(filename="new.mp4", file=BytesIO(b"video")))
    )

    assert result["settings"]["videoScaleX"] == 100.0
    assert result["settings"]["videoScaleY"] == 100.0


def test_project_thumbnail_is_cached_and_uses_a_decoded_frame(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "source.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(projects, "load_meta", lambda _project_id: {"videoPath": str(source)})
    monkeypatch.setattr(projects, "ensure_layout", lambda _project_id: root)
    monkeypatch.setattr(projects, "resolve_project_video", lambda _meta, _project_id: source)
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(projects.subprocess, "run", fake_run)
    response = asyncio.run(projects.api_project_thumbnail("project-1"))
    assert response.media_type == "image/jpeg"
    assert len(calls) == 1
    assert (root / "cache" / "input_thumbnail.jpg").read_bytes() == b"jpg"

    asyncio.run(projects.api_project_thumbnail("project-1"))
    assert len(calls) == 1
