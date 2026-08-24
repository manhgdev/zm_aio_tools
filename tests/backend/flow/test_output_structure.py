import importlib
import asyncio
import threading
import time

from pipeline.core.output_paths import nested_output_folder

service_module = importlib.import_module("pipeline.flow.service")
output_paths_module = importlib.import_module("pipeline.core.output_paths")


def test_shared_nested_output_folder_sanitizes_every_component(tmp_path):
    folder = nested_output_folder(tmp_path, "Campaign August", "job / 123")

    assert folder == tmp_path / "Campaign-August" / "job-123"
    assert folder.is_dir()


def test_app_default_outputs_share_one_root_with_feature_subfolders(monkeypatch, tmp_path):
    monkeypatch.setattr(output_paths_module.Path, "home", lambda: tmp_path)

    assert output_paths_module.downloads_folder("video-clone") == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "clone"
    assert output_paths_module.downloads_folder("film") == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "review"
    assert output_paths_module.downloads_folder("flow") == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "flow"
    assert output_paths_module.downloads_folder("tts") == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "text-to-speech"
    assert output_paths_module.downloads_folder("subtitle-export") == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "subtitles" / "export"


def test_flow_outputs_share_root_and_job_delete_removes_the_right_child(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDEO_CLONE_DESKTOP", raising=False)
    monkeypatch.setattr(service_module, "PUBLIC_DATA", tmp_path / "public")
    flow = service_module.FlowService()
    job = {
        "id": "job-123",
        "inputIndex": 1,
        "kind": "video",
        "settings": {"outputDir": "Campaign August", "filePrefix": "launch video"},
        "status": "done",
    }
    output = flow._output_path(job, 1, "mp4")
    output.touch()
    job["outputs"] = [str(output)]

    assert output == tmp_path / "public" / "flow" / "Campaign-August" / "001__job-123__launch-video_01.mp4"

    monkeypatch.setattr(service_module.store, "get_row", lambda _table, job_id: job if job_id == job["id"] else None)
    monkeypatch.setattr(service_module.store, "delete_row", lambda _table, job_id: job_id == job["id"])

    assert flow.delete_job("job-123") is True
    assert not output.parent.exists()


def test_desktop_flow_uses_full_selected_output_path(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_CLONE_DESKTOP", "1")
    flow = service_module.FlowService()
    job = {
        "id": "job-full-path",
        "inputIndex": 2,
        "kind": "image",
        "createdAt": 1_725_000_000,
        "settings": {
            "outputDir": str(tmp_path / "My complete output"),
            "createTimeFolder": False,
            "filePrefix": "result",
        },
    }

    output = flow._output_path(job, 1, "png")

    assert output.parent == tmp_path / "My complete output"
    assert output.parent.is_dir()


def test_desktop_flow_resolves_relative_result_folder_under_downloads(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_CLONE_DESKTOP", "1")
    monkeypatch.setattr(service_module.Path, "home", lambda: tmp_path)
    flow = service_module.FlowService()
    job = {
        "id": "job-relative-path",
        "inputIndex": 1,
        "kind": "image",
        "createdAt": 1_725_000_000,
        "settings": {
            "outputDir": "campaign-images",
            "createTimeFolder": False,
            "filePrefix": "result",
        },
    }

    output = flow._output_path(job, 1, "png")

    assert output.parent == tmp_path / "Downloads" / "ZM_AIO_TOOL" / "flow" / "campaign-images"
    assert output.parent.is_dir()


def test_flow_delete_active_job_cancels_and_removes_it(monkeypatch):
    flow = service_module.FlowService()
    job = {"id": "active-job", "status": "processing", "kind": "video", "settings": {}}
    deleted = []
    monkeypatch.setattr(service_module.store, "get_row", lambda *_args: dict(job))
    monkeypatch.setattr(service_module.store, "patch_row", lambda *_args: dict(job))
    monkeypatch.setattr(service_module.store, "delete_row", lambda _table, job_id: deleted.append(job_id) or True)
    monkeypatch.setattr(flow, "_output_folder", lambda *_args, **_kwargs: service_module.PUBLIC_DATA / "missing")

    assert flow.delete_job("active-job") is True
    assert "active-job" in flow._cancelled
    assert deleted == ["active-job"]


def test_flow_exposed_models_all_use_the_authenticated_ui_path():
    assert service_module._IMAGE_UI_MODELS == {"Nano Banana Pro", "Nano Banana 2", "Nano Banana 2 Lite"}
    assert "Omni Flash" in service_module._VIDEO_UI_MODELS
    assert "Veo 3.1 - Fast" in service_module._VIDEO_UI_MODELS
    assert "Veo 3.1 - Quality" in service_module._VIDEO_UI_MODELS
    assert "Veo 3.1 - Lite [Lower Priority]" in service_module._VIDEO_UI_MODELS


def test_flow_jobs_persist_the_real_prompt_input_type(monkeypatch):
    flow = service_module.FlowService()
    stored = []
    monkeypatch.setattr(
        service_module.store,
        "get_row",
        lambda table, row_id: {"id": row_id} if table == "accounts" else None,
    )
    monkeypatch.setattr(
        service_module.store,
        "put_row",
        lambda _table, row: stored.append(dict(row)) or row,
    )
    monkeypatch.setattr(flow, "_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(threading.Thread, "start", lambda _thread: None)

    jobs = flow.enqueue({
        "prompts": ["first", "second"],
        "accountId": "account-1",
        "kind": "image",
        "inputType": "txt",
        "settings": {"model": "Nano Banana 2"},
    })

    assert [job["inputType"] for job in jobs] == ["txt", "txt"]
    assert [job["inputType"] for job in stored] == ["txt", "txt"]


def test_flow_runtime_profile_keeps_login_state_and_skips_browser_caches(monkeypatch, tmp_path):
    source = tmp_path / "profiles" / "account-1"
    (source / "Default" / "Cache").mkdir(parents=True)
    (source / "Default" / "Cookies").write_text("session", encoding="utf-8")
    (source / "Default" / "Cache" / "data").write_text("large cache", encoding="utf-8")
    (source / "SingletonLock").write_text("locked", encoding="utf-8")
    monkeypatch.setattr(service_module.store, "profile_dir", lambda _account_id: source)
    monkeypatch.setattr(service_module.store, "root", lambda: tmp_path)

    runtime = service_module.FlowService()._clone_runtime_profile("account-1", "job-1")

    assert (runtime / "Default" / "Cookies").read_text(encoding="utf-8") == "session"
    assert not (runtime / "Default" / "Cache").exists()
    assert not (runtime / "SingletonLock").exists()


def test_flow_runs_up_to_three_jobs_per_account_in_parallel(monkeypatch, tmp_path):
    flow = service_module.FlowService()
    active = 0
    peak = 0
    state_lock = threading.Lock()
    jobs = {f"job-{index}": {"id": f"job-{index}", "accountId": "account-1"} for index in range(6)}
    monkeypatch.setattr(service_module.store, "get_row", lambda table, row_id: jobs.get(row_id) if table == "jobs" else None)

    def clone(_account_id, job_id):
        path = tmp_path / job_id
        path.mkdir()
        return path

    async def run(_job_id, *, profile_dir=None):
        nonlocal active, peak
        assert profile_dir is not None
        with state_lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.08)
        with state_lock:
            active -= 1

    monkeypatch.setattr(flow, "_clone_runtime_profile", clone)
    monkeypatch.setattr(flow, "_run", run)
    threads = [threading.Thread(target=flow._run_sync, args=(job_id,)) for job_id in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert peak == service_module._MAX_CONCURRENT_JOBS_PER_ACCOUNT == 3


def test_flow_credit_sync_updates_account_without_failing_generation(monkeypatch):
    flow = service_module.FlowService()
    patches = []
    monkeypatch.setattr(
        service_module.store,
        "patch_row",
        lambda table, row_id, patch: patches.append((table, row_id, patch)) or patch,
    )

    class CreditInfo:
        credits = 287

    class Api:
        async def get_credits(self):
            return CreditInfo()

    asyncio.run(flow._sync_credits(Api(), "account-1"))

    assert patches[0][0:2] == ("accounts", "account-1")
    assert patches[0][2]["credits"] == 287
    assert patches[0][2]["creditsSyncedAt"] > 0


def test_flow_credit_sync_failure_does_not_fail_the_job(monkeypatch):
    flow = service_module.FlowService()
    monkeypatch.setattr(service_module.store, "patch_row", lambda *_args: None)

    class Api:
        async def get_credits(self):
            raise RuntimeError("temporary credit endpoint failure")

    asyncio.run(flow._sync_credits(Api(), "account-1"))


def test_flow_start_repairs_false_success_without_output(monkeypatch):
    flow = service_module.FlowService()
    stale = {"id": "empty-video", "status": "done", "outputs": []}
    patches = []
    monkeypatch.setattr(flow, "jobs", lambda: [stale])
    monkeypatch.setattr(
        service_module.store,
        "patch_row",
        lambda table, row_id, patch: patches.append((table, row_id, patch)) or patch,
    )

    flow.start()

    assert patches[0][0:2] == ("jobs", "empty-video")
    assert patches[0][2]["status"] == "failed"
    assert patches[0][2]["progress"] == 0
    assert patches[0][2]["error"].startswith("FLOW_EMPTY_OUTPUT")


def test_flow_success_requires_nonempty_output_files(tmp_path):
    output = tmp_path / "video.mp4"

    assert service_module.FlowService._outputs_exist([]) is False
    assert service_module.FlowService._outputs_exist([output]) is False
    output.write_bytes(b"video")
    assert service_module.FlowService._outputs_exist([output]) is True


def test_flow_concurrent_jobs_claim_distinct_project_media(monkeypatch):
    flow = service_module.FlowService()
    monkeypatch.setattr(flow, "jobs", lambda: [])

    first = flow._claim_media_ids(["media-a", "media-b"], 1)
    second = flow._claim_media_ids(["media-a", "media-b"], 1)

    assert first == ["media-a"]
    assert second == ["media-b"]
