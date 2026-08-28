import importlib
from pathlib import Path

from fastapi.testclient import TestClient

series = importlib.import_module("pipeline.flow.series")
store = importlib.import_module("pipeline.flow.store")
service_module = importlib.import_module("pipeline.flow.service")
flow_routes = importlib.import_module("api.routes.flow")
series_runner = importlib.import_module("pipeline.flow.series_runner")


def _script(episodes=2, scenes=2):
    rows = ["# SERIES: Bí ẩn cánh cổng tím"]
    for episode in range(1, episodes + 1):
        rows.append(f"# TẬP {episode:02d} — Tập {episode}")
        for scene in range(1, scenes + 1):
            rows.append(f"{scene:03d}_[00.00_{scene:02d}.00-00.00_{scene + 1:02d}.00] Cảnh {scene} tập {episode}")
    return "\n".join(rows)


def test_import_series_script_keeps_ten_episodes_and_scenes():
    parsed = series.import_script(_script(10, 10))
    assert parsed["ok"] is True
    assert len(parsed["episodes"]) == 10
    assert all(len(episode["scenes"]) == 10 for episode in parsed["episodes"])
    assert parsed["episodes"][0]["scenes"][0]["timecode"].startswith("00.00")


def test_invalid_series_script_returns_line_errors():
    result = series.import_script("# SERIES: X\nnot a scene")
    assert result["ok"] is False
    assert any(error["line"] == 2 for error in result["errors"])


def test_completed_series_anchor_job_becomes_locked_anchor_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    item = series.create_series("Anchor series")
    output = tmp_path / "anchor.png"; output.write_bytes(b"image")
    series.mark_job_complete({"seriesContext": {"artifact": "anchor", "seriesId": item["id"], "anchorLabel": "Hero"}}, [str(output)])
    updated = series.get_series(item["id"])
    assert len(updated["assets"]) == 1
    assert updated["assets"][0]["locked"] is True
    assert updated["anchorAssets"] == [updated["assets"][0]["id"]]


def test_series_cloud_draft_uses_configured_provider_without_exposing_key(monkeypatch):
    series_ai = importlib.import_module("pipeline.flow.series_ai")
    captured = {}
    monkeypatch.setattr(series_ai, "provider_credentials", lambda _provider: {"baseUrl": "https://example.test/v1", "model": "test-model"})
    monkeypatch.setattr(series_ai, "provider_api_keys", lambda _provider: ["secret-key"])
    monkeypatch.setattr(series_ai, "_openai_compatible_chat", lambda **kwargs: captured.update(kwargs) or "# SERIES: Test\n# TẬP 01 — One\n001_[00.00_00.00-00.00_08.00] Scene")
    text = series_ai.draft_script(provider="openrouter", idea="A purple gate", episodes=1, scenes_per_episode=1)
    assert text.startswith("# SERIES: Test")
    assert captured["model"] == "test-model"
    assert "secret-key" not in text


def test_series_cloud_draft_endpoint_returns_reviewable_txt(monkeypatch):
    from api.app import create_app
    series_ai = importlib.import_module("pipeline.flow.series_ai")
    monkeypatch.setattr(series_ai, "draft_script", lambda **_kwargs: "# SERIES: Draft\n# TẬP 01 — One\n001_[00.00_00.00-00.00_08.00] Scene")
    client = TestClient(create_app())
    response = client.post("/api/flow/series/draft", json={"provider": "openrouter", "idea": "A portal", "episodes": 1, "scenesPerEpisode": 1})
    assert response.status_code == 200
    assert response.json()["text"].startswith("# SERIES: Draft")


def test_series_rows_created_before_anchor_assets_still_load(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    store.put_row("series", {"id": "legacy-series", "title": "Legacy", "episodes": []})
    item = series.get_series("legacy-series")
    assert item is not None
    assert item["assets"] == []
    assert item["anchorAssets"] == []


def test_series_context_uses_previous_actual_end_frame_before_locked_anchors(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    created = series.create_from_script(_script())
    item = created["series"]
    first, second = item["episodes"][0]["scenes"]
    anchor_one = series.add_asset(item["id"], "character.png", b"one")
    anchor_two = series.add_asset(item["id"], "prop.png", b"two")
    anchor_three = series.add_asset(item["id"], "extra.png", b"three")
    series.update_series(item["id"], {"anchorAssets": [anchor_one["id"], anchor_two["id"], anchor_three["id"]]})
    end = tmp_path / "last.png"; end.write_bytes(b"end")
    series.update_scene(item["id"], item["episodes"][0]["id"], first["id"], {"endFrame": str(end)})
    context = series.generation_context(item["id"], item["episodes"][0]["id"], second["id"], "keyframe")
    assert context["sourceFiles"] == [str(end), anchor_one["path"], anchor_two["path"]]
    assert context["outputDir"].endswith("/tap-01")


def test_series_video_uses_previous_actual_end_frame_before_approved_keyframe(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    item = series.create_from_script(_script(1, 2))["series"]
    episode, first, scene = item["episodes"][0], *item["episodes"][0]["scenes"]
    keyframe = tmp_path / "keyframe.png"; keyframe.write_bytes(b"image")
    series.approve_keyframe(item["id"], episode["id"], scene["id"], str(keyframe))
    end = tmp_path / "end.png"; end.write_bytes(b"image")
    series.update_scene(item["id"], episode["id"], first["id"], {"endFrame": str(end)})
    context = series.generation_context(item["id"], episode["id"], scene["id"], "video")
    assert len(context["sourceFiles"]) == 1
    assert context["sourceFiles"] == [str(end)]


def test_series_runner_completes_each_scene_before_starting_the_next(monkeypatch):
    runner = series_runner.SeriesRunner()
    run = series_runner._Run("run-test", 2)
    phases: list[str] = []

    def record_phase(*_args, mode, count_progress=True, **_kwargs):
        phases.append(mode)
        if count_progress:
            run.mark_done()

    monkeypatch.setattr(runner, "_process_scene", record_phase)
    scenes = [({"id": "episode"}, {"id": "scene-1"}), ({"id": "episode"}, {"id": "scene-2"})]
    runner._orchestrate(run, "series", scenes, "account", {}, "Nano Banana 2", True, "full")

    assert phases == ["full", "full"]
    assert run.snapshot()["done"] == 2


def test_series_output_is_isolated_by_kind_episode_and_scene(monkeypatch, tmp_path):
    output_root = tmp_path / "downloads" / "ZM_AIO_TOOL" / "flow"
    monkeypatch.setattr(service_module, "selected_or_default", lambda _tab, _selected: output_root)
    flow = service_module.FlowService()
    folder = flow._output_folder({"kind": "image", "seriesContext": {"seriesSlug": "purple-gate", "episodeIndex": 1, "sceneIndex": 2}})
    assert folder == output_root / "series" / "purple-gate" / "image" / "tap-01"

    anchor = flow._output_folder({"kind": "image", "seriesContext": {"artifact": "anchor", "seriesSlug": "purple-gate"}})
    video = flow._output_folder({"kind": "video", "seriesContext": {"seriesSlug": "purple-gate", "episodeIndex": 1, "sceneIndex": 2}})
    assert anchor == output_root / "series" / "purple-gate" / "image" / "anchors"
    assert video == output_root / "series" / "purple-gate" / "video" / "tap-01"


def test_deleting_a_series_removes_only_its_dedicated_assets_and_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    monkeypatch.setattr(series, "downloads_folder", lambda _feature: tmp_path / "downloads" / "flow")
    monkeypatch.setattr(series, "PUBLIC_DATA", tmp_path / "public")
    first = series.create_series("First series")
    second = series.create_series("Second series")
    first_output = tmp_path / "public" / "flow" / "series" / first["slug"] / "image" / "tap-01"
    second_output = tmp_path / "public" / "flow" / "series" / second["slug"] / "image" / "tap-01"
    first_output.mkdir(parents=True); second_output.mkdir(parents=True)
    (first_output / "one.png").write_bytes(b"one")
    (second_output / "two.png").write_bytes(b"two")
    assert series.delete_series(first["id"]) is True
    assert not first_output.exists()
    assert second_output.exists()


def test_one_series_runs_keyframe_video_and_continuity_through_the_api(monkeypatch, tmp_path):
    """Representative offline run: no cloud account/browser is invoked."""
    from api.app import create_app

    monkeypatch.setattr(store, "ROOT", tmp_path / "flow-store")
    captured: list[dict] = []

    def fake_enqueue(payload):
        captured.append(payload)
        context = payload["seriesContext"]
        job = {
            "id": f"job-{len(captured)}", "kind": payload["kind"], "outputs": [],
            "seriesContext": context, "settings": payload["settings"], "inputIndex": 1,
        }
        store.put_row("jobs", job)
        series.register_job(job)
        return [job]

    # Patch the object imported by the API route, rather than the service
    # implementation module.  This keeps the test fully offline.
    monkeypatch.setattr(flow_routes.service, "enqueue", fake_enqueue)
    client = TestClient(create_app())
    script = "\n".join([
        "# SERIES: Purple Gate", "# TẬP 01 — Pilot",
        "001_[00.00_00.00-00.00_08.00] Hero enters the gate",
        "002_[00.00_08.00-00.00_16.00] Hero sees the other world",
    ])
    created = client.post("/api/flow/series/import", json={"text": script, "bible": "Hero keeps purple armor."})
    assert created.status_code == 200
    item = created.json()["series"]
    episode = item["episodes"][0]
    first, second = episode["scenes"]
    asset = client.post(
        f"/api/flow/series/{item['id']}/assets", files={"file": ("hero.png", b"anchor", "image/png")},
    )
    assert asset.status_code == 200
    anchor_id = asset.json()["id"]
    assert client.put(f"/api/flow/series/{item['id']}", json={"title": item["title"], "bible": "Hero keeps purple armor.", "description": "", "anchorAssets": [anchor_id]}).status_code == 200

    keyframe = client.post(
        f"/api/flow/series/{item['id']}/episodes/{episode['id']}/scenes/{first['id']}/generate",
        json={"artifact": "keyframe", "accountId": "offline", "settings": {}},
    )
    assert keyframe.status_code == 200
    assert captured[-1]["kind"] == "image"
    assert captured[-1]["seriesContext"]["outputDir"].endswith("tap-01")
    assert captured[-1]["sourceFiles"] and captured[-1]["sourceFiles"][0].endswith(".png")

    keyframe_file = tmp_path / "keyframe.png"; keyframe_file.write_bytes(b"keyframe")
    keyframe_job = store.get_row("jobs", "job-1") or {}
    keyframe_job["outputs"] = [str(keyframe_file)]; store.put_row("jobs", keyframe_job)
    assert client.post(f"/api/flow/series/{item['id']}/episodes/{episode['id']}/scenes/{first['id']}/approve-keyframe?job_id=job-1").status_code == 200

    video = client.post(
        f"/api/flow/series/{item['id']}/episodes/{episode['id']}/scenes/{first['id']}/generate",
        json={"artifact": "video", "accountId": "offline", "settings": {}},
    )
    assert video.status_code == 200
    assert captured[-1]["kind"] == "video"
    assert len(captured[-1]["sourceFiles"]) == 1
    video_file = tmp_path / "scene-1.mp4"; video_file.write_bytes(b"video")
    # The FFmpeg adapter normally writes this file. Recreate that side effect
    # here to keep the integration test independent from machine FFmpeg.
    def fake_frame(command, **_kwargs):
        Path(command[-1]).write_bytes(b"end-frame")
    monkeypatch.setattr(series.subprocess, "run", fake_frame)
    series.mark_job_complete(store.get_row("jobs", "job-2") or {}, [str(video_file)])

    next_keyframe = client.post(
        f"/api/flow/series/{item['id']}/episodes/{episode['id']}/scenes/{second['id']}/generate",
        json={"artifact": "keyframe", "accountId": "offline", "settings": {}},
    )
    assert next_keyframe.status_code == 200
    assert captured[-1]["sourceFiles"][0].endswith("_end.png")
    assert captured[-1]["sourceFiles"][1].endswith(".png")
