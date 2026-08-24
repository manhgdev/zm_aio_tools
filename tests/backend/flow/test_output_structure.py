import importlib

from pipeline.core.output_paths import nested_output_folder

service_module = importlib.import_module("pipeline.flow.service")


def test_shared_nested_output_folder_sanitizes_every_component(tmp_path):
    folder = nested_output_folder(tmp_path, "Campaign August", "job / 123")

    assert folder == tmp_path / "Campaign-August" / "job-123"
    assert folder.is_dir()


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

    assert output == tmp_path / "public" / "flow" / "Campaign-August" / "job-123" / "001__job-123__launch-video_01.mp4"

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

    assert output.parent == tmp_path / "My complete output" / "job-full-path"
    assert output.parent.is_dir()
