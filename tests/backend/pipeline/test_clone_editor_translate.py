from pipeline.clone_run import headless


def test_existing_editor_translate_does_not_render(monkeypatch):
    """Clone Video's Translate queue job must leave publishing to the editor."""
    meta = {"settings": {"engine": "whisper"}, "previewSec": 0}
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(headless, "load_meta", lambda _project_id: meta)
    monkeypatch.setattr(headless, "arm_job", lambda _project_id: 1)
    monkeypatch.setattr(headless, "share_cancel", lambda *_args: None)
    monkeypatch.setattr(headless, "save_meta", lambda *_args: calls.append(("save", None)))
    monkeypatch.setattr(headless, "check_cancel", lambda *_args: None)
    monkeypatch.setattr(headless, "set_status", lambda *_args, **_kwargs: calls.append(("status", None)))
    monkeypatch.setattr(headless, "run_pipeline", lambda project_id, settings: calls.append(("translate", (project_id, settings))))
    monkeypatch.setattr(headless, "run_export", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Translate must not export")))

    result = headless.run_existing_project_clone_job({
        "id": "queue-1",
        "projectId": "project-1",
        "settings_snapshot": {"targetLang": "vi", "previewSec": 0},
    })

    assert result["output"] == ""
    assert result["stage"] == "translated"
    assert any(kind == "translate" for kind, _value in calls)
