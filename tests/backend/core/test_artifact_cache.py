from pathlib import Path

from pipeline.core.artifact_cache import ArtifactCache


def test_key_changes_with_input_or_any_setting(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"version-one")
    cache = ArtifactCache("drawing", root=tmp_path / "cache")

    first = cache.key(inputs=[source], settings={"fps": 30}, values={"mode": "hand"})
    assert cache.key(inputs=[source], settings={"fps": 30}, values={"mode": "hand"}) == first
    assert cache.key(inputs=[source], settings={"fps": 60}, values={"mode": "hand"}) != first
    source.write_bytes(b"version-two-is-longer")
    assert cache.key(inputs=[source], settings={"fps": 30}, values={"mode": "hand"}) != first


def test_store_and_restore_multiple_artifacts(tmp_path):
    cache = ArtifactCache("srt-export", root=tmp_path / "cache")
    video = tmp_path / "drawing.mp4"
    preview = tmp_path / "line-map.png"
    video.write_bytes(b"video")
    preview.write_bytes(b"preview")

    cache.store("same", {"output.mp4": video, "preview.png": preview})
    restored_video = tmp_path / "new" / "drawing.mp4"
    restored_preview = tmp_path / "new" / "line-map.png"

    assert cache.restore("same", {"output.mp4": restored_video, "preview.png": restored_preview})
    assert restored_video.read_bytes() == b"video"
    assert restored_preview.read_bytes() == b"preview"
