import json
import threading
import time
from pathlib import Path

import pytest

from pipeline.automation.store import AutomationStore
from pipeline.automation.service import AutomationService


def test_automation_store_keeps_independent_jobs_and_logs(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    first = store.create_job("topic", "First", {"chatModel": "GPT-5.6 Sol"})
    second = store.create_job("script", "Second", {})

    store.update_job(first["id"], status="running", stage="tts", progress=35)
    store.append_log(first["id"], "info", "TTS started", stage="tts")
    store.append_log(second["id"], "error", "Flow failed", stage="flow_images")

    assert store.get_job(first["id"])["stage"] == "tts"
    assert store.get_job(first["id"])["progress"] == 35
    assert {row["id"] for row in store.list_jobs()} == {first["id"], second["id"]}
    assert store.list_logs(first["id"])[0]["message"] == "TTS started"
    assert store.list_logs(second["id"])[0]["stage"] == "flow_images"
    assert store.workspace(first["id"]).is_dir()


def test_automation_store_recovers_running_jobs_as_interrupted(tmp_path):
    db = tmp_path / "automation.sqlite3"
    store = AutomationStore(db, tmp_path / "jobs")
    job = store.create_job("topic", "Recover", {})
    store.update_job(job["id"], status="running", stage="chat")
    store.close()

    reopened = AutomationStore(db, tmp_path / "jobs")
    recovered = reopened.get_job(job["id"])
    assert recovered["status"] == "interrupted"
    assert recovered["stage"] == "chat"
    assert recovered["error"]["code"] == "AUTOMATION_INTERRUPTED"


def test_automation_store_keeps_queued_jobs_runnable_after_restart(tmp_path):
    db = tmp_path / "automation.sqlite3"
    store = AutomationStore(db, tmp_path / "jobs")
    job = store.create_job("topic", "Queued", {})
    store.close()
    reopened = AutomationStore(db, tmp_path / "jobs")
    assert reopened.get_job(job["id"])["status"] == "queued"


def test_automation_service_can_queue_multiple_jobs_and_resume_one(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    gate = threading.Event()
    started: list[str] = []

    def runner(job_id: str):
        started.append(job_id)
        gate.wait(2)
        store.update_job(job_id, status="completed", stage="done", progress=100)

    service = AutomationService(store=store, runner=runner, max_workers=2)
    first = service.create_job("topic", "One", {})
    second = service.create_job("topic", "Two", {})
    service.start_job(first["id"])
    service.start_job(second["id"])
    assert service.wait_for_idle(timeout=0.2) is False
    assert set(started) == {first["id"], second["id"]}
    gate.set()
    assert service.wait_for_idle(timeout=2) is True
    assert {store.get_job(first["id"])["status"], store.get_job(second["id"])["status"]} == {"completed"}


def test_automation_service_pauses_failed_job_without_touching_other_job(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    gate = threading.Event()

    def runner(job_id: str):
        if job_id == bad["id"]:
            raise RuntimeError("CHATGPT_LOGIN_REQUIRED")
        gate.wait(2)
        store.update_job(job_id, status="completed", stage="done", progress=100)

    service = AutomationService(store=store, runner=runner, max_workers=2)
    bad = service.create_job("topic", "Bad", {})
    good = service.create_job("topic", "Good", {})
    service.start_job(bad["id"])
    service.start_job(good["id"])
    deadline = time.time() + 2
    while time.time() < deadline and store.get_job(bad["id"])["status"] not in {"paused", "failed"}:
        time.sleep(0.01)
    assert store.get_job(bad["id"])["status"] == "paused"
    assert store.get_job(bad["id"])["error"]["code"] == "CHATGPT_LOGIN_REQUIRED"
    assert store.get_job(good["id"])["status"] == "running"
    gate.set()
    assert service.wait_for_idle(timeout=2) is True
    assert store.get_job(good["id"])["status"] == "completed"


def test_automation_job_settings_and_artifacts_are_json_safe(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    job = store.create_job("bundle", "Files", {"allowMissingMedia": False})
    store.update_job(job["id"], artifacts={"script": "script.txt"}, child_job_ids=["flow-1"])
    raw = json.dumps(store.get_job(job["id"]), ensure_ascii=False)
    assert "allowMissingMedia" in raw
    assert "flow-1" in raw


def test_chat_store_accepts_audio_input_for_automation(tmp_path):
    from pipeline.chat.store import ChatStore

    chat = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
    conversation = chat.create_conversation("Audio")
    saved = chat.save_attachment(
        conversation["id"], "narration.wav", b"RIFF" + b"\x00" * 8,
        max_size=100 * 1024 * 1024, content_type="audio/wav",
    )
    assert saved["content_type"] == "audio/wav"


def test_public_job_redacts_local_paths_and_secret_settings(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)
    job = service.create_job("bundle", "Private", {"chatModel": "GPT-5.6 Sol", "apiKey": "do-not-return"}, {"audio": "/private/audio.wav"})
    artifact = store.workspace(job["id"]) / "audio.wav"
    artifact.write_bytes(b"RIFF")
    image_dir = store.workspace(job["id"]) / "images"
    image_dir.mkdir()
    store.update_job(job["id"], artifacts={"audio": str(artifact), "images": str(image_dir)})
    public = service.public_job(job["id"])
    assert public["input"]["audio"] == "audio.wav"
    assert "do-not-return" not in json.dumps(public)
    assert public["artifacts"]["audio"]["available"] is True
    assert public["artifacts"]["images"]["available"] is True


def test_automation_http_queue_and_artifact_download(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.automation as route
    from pipeline.core import license as license_module

    local_service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None, max_workers=1)
    monkeypatch.setattr(route, "service", local_service)
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)
    client = TestClient(create_app())
    response = client.post("/api/automation/jobs", data={"inputMode": "topic", "topic": "Test queue", "startNow": "false", "settings": "{}"})
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "queued"
    raw = local_service.store.workspace(job["id"]) / "script.txt"
    raw.write_text("hello", encoding="utf-8")
    local_service.store.update_job(job["id"], artifacts={"script": str(raw)})
    download = client.get(f"/api/automation/jobs/{job['id']}/artifacts/script")
    assert download.status_code == 200
    assert download.content == b"hello"


def test_empty_topic_starts_ai_topic_suggestions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    import api.routes.automation as route
    from pipeline.core import license as license_module

    local_service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None, max_workers=1)
    monkeypatch.setattr(route, "service", local_service)
    monkeypatch.setattr(license_module, "license_cached_valid", lambda: True)
    response = TestClient(create_app()).post("/api/automation/jobs", data={"inputMode": "topic", "topic": "", "startNow": "false", "settings": "{}"})
    assert response.status_code == 200
    assert response.json()["input_mode"] == "ai_topic"


def test_job_setting_change_invalidates_generated_downstream_checkpoints(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)
    job = service.create_job("topic", "Checkpoint", {"chatModel": "GPT-5.6 Sol"}, {"script": "script.txt", "generatedScript": True, "audio": "audio.wav", "generatedAudio": True})
    store.update_job(job["id"], artifacts={"script": "script.txt", "audio": "audio.wav", "video": "video.mp4", "images": "images"})
    service.update_job_settings(job["id"], settings={"chatModel": "GPT-5.6 Sol", "compose": {"fps": 60}})
    current = store.get_job(job["id"])
    assert current["input"] == {}
    assert set(current["artifacts"]) == set()


def test_flow_image_invalid_argument_is_retryable_but_login_is_not():
    assert AutomationService.flow_failure_retryable("failed", "batchGenerateImages failed [400]: Request contains an invalid argument.") is True
    assert AutomationService.flow_failure_retryable("action_required", "FLOW_LOGIN_REQUIRED") is False


def test_automation_service_delete_job_removes_logs_and_workspace(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)
    job = service.create_job("bundle", "Delete me", {})
    marker = store.workspace(job["id"]) / "generated.txt"
    marker.write_text("temporary", encoding="utf-8")

    result = service.delete_job(job["id"])

    assert result["deleted"] is True
    assert store.get_job(job["id"]) is None
    assert store.list_logs(job["id"]) == []
    assert not marker.exists()
    assert not marker.parent.exists()


def test_ai_topic_job_waits_with_exactly_five_choices(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=None, max_workers=1)
    job = service.create_job("ai_topic", "Ideas", {}, {"topic": "prehistoric life"})
    monkeypatch.setattr(service, "_request_chat", lambda *_args: ("\n".join(f"{i}. Topic {i}" for i in range(1, 6)), None))

    service._execute(job["id"])

    current = store.get_job(job["id"])
    assert current["status"] == "awaiting_topic"
    assert current["stage"] == "topic"
    assert len(current["input"]["topicCandidates"]) == 5
    assert not current["input"].get("selectedTopic")


def test_ai_topic_job_rejects_incomplete_choices(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=None, max_workers=1)
    job = service.create_job("ai_topic", "Ideas", {}, {"topic": "prehistoric life"})
    monkeypatch.setattr(service, "_request_chat", lambda *_args: ("1. Topic 1\n2. Topic 2\n3. Topic 3\n4. Topic 4", None))

    service._execute(job["id"])

    current = store.get_job(job["id"])
    assert current["status"] == "paused"
    assert current["error"]["code"] == "AUTOMATION_TOPIC_INCOMPLETE"


def test_ai_topic_job_does_not_reuse_legacy_topic_prompt_cache(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=None, max_workers=1)
    job = service.create_job("ai_topic", "Ideas", {}, {"topic": "prehistoric life"})
    store.workspace(job["id"]).joinpath("topic_candidates.json").write_text(
        json.dumps([f"Old topic {i}" for i in range(1, 6)]), encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        service,
        "_request_chat",
        lambda *_args: (calls.append(True) or "\n".join(f"{i}. New topic {i}" for i in range(1, 6)), None),
    )

    service._execute(job["id"])

    current = store.get_job(job["id"])
    assert calls == [True]
    assert current["input"]["topicCandidates"] == [f"New topic {i}" for i in range(1, 6)]


def test_automation_language_changes_chat_instructions(tmp_path):
    service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None)
    settings = {"language": "en"}

    assert "exactly 5" in service._topic_prompt("space", settings)
    assert "English" in service._script_prompt("space", settings)
    assert "Format: 001_[" in service._image_prompt_request(settings)


def test_automation_accepts_one_plain_image_prompt_per_line(tmp_path):
    service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None)
    prompt_file = tmp_path / "image_prompt.txt"
    prompt_file.write_text("A red fox in a snowy forest\nA warm cabin at dusk\n", encoding="utf-8")

    assert service._plain_prompt_lines(prompt_file.read_text(encoding="utf-8")) == [
        "A red fox in a snowy forest",
        "A warm cabin at dusk",
    ]
    service._validate_prompt_file(prompt_file)
    assert not service._has_timed_prompts(prompt_file)


def test_audio_first_topic_prompt_uses_the_full_engine_contract(tmp_path):
    service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None)

    prompt = service._topic_prompt("prehistoric life", {"language": "vi", "flow": {"promptEngine": "vi"}})

    assert "ZMTOOL AUDIO-FIRST VIDEO PRODUCTION ENGINE V1.0" in prompt
    assert "GIAI ĐOẠN 1: CHỌN CHỦ ĐỀ" in prompt
    assert "Audio là nguồn chính" in prompt
    assert "Chọn số 1-5 để bắt đầu" in prompt


def test_audio_first_prompt_reads_the_preview_source_of_truth():
    from pipeline.automation.prompts import audio_first_prompt

    root = Path(__file__).resolve().parents[1] / "previews"
    assert audio_first_prompt("vi") == (root / "v1.0-base-vietnam-2D-image.txt").read_text(encoding="utf-8")
    assert audio_first_prompt("en") == (root / "v1.0-base-english-2D-image.txt").read_text(encoding="utf-8")


def test_audio_first_prompt_loads_future_languages_by_filename(monkeypatch, tmp_path):
    from pipeline.automation import prompts

    (tmp_path / "v1.0-base-korean-2D-image.txt").write_text("한국어 base", encoding="utf-8")
    monkeypatch.setattr(prompts, "_PREVIEW_ROOT", tmp_path)
    prompts.audio_first_prompt.cache_clear()
    assert prompts.audio_first_prompt("korean") == "한국어 base"
    prompts.audio_first_prompt.cache_clear()


def test_audio_first_topic_candidates_accept_markdown_table_without_headers():
    content = """# Chủ đề video
| # | Chủ đề video |
|---|---|
| 1 | Điều gì xảy ra nếu bạn thức dậy 300.000 năm trước? |
| 2 | Bạn sống sót được bao lâu trong kỷ băng hà? |
| 3 | Một ngày của người cổ đại nguy hiểm đến mức nào? |
| 4 | Vì sao con người vẫn sống sót khi không có bệnh viện? |
| 5 | Điều gì xảy ra nếu bạn sống 30 ngày như người tiền sử? |

Chọn số 1-5 để bắt đầu."""

    assert AutomationService._topic_candidates(content) == [
        "Điều gì xảy ra nếu bạn thức dậy 300.000 năm trước?",
        "Bạn sống sót được bao lâu trong kỷ băng hà?",
        "Một ngày của người cổ đại nguy hiểm đến mức nào?",
        "Vì sao con người vẫn sống sót khi không có bệnh viện?",
        "Điều gì xảy ra nếu bạn sống 30 ngày như người tiền sử?",
    ]


def test_automation_settings_have_provider_and_model_for_text_ai(tmp_path):
    service = AutomationService(store=AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs"), runner=lambda _job_id: None)
    settings = service.get_settings()
    assert settings["textProvider"] == "openrouter"
    assert settings["textModel"] == "openrouter/free"
    assert settings["compose"]["resolution"] == "auto"
    assert settings["compose"]["encoder"] == "auto"
    assert settings["compose"]["subtitleEnabled"] is True


def test_created_job_persists_one_text_provider_and_model(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)

    job = service.create_job("topic", "Provider", {})

    assert job["settings"]["textProvider"] == "openrouter"
    assert job["settings"]["textModel"] == "openrouter/free"


def test_automation_chat_uses_selected_api_provider_without_chatgpt_session(tmp_path, monkeypatch):
    from pipeline.chat.store import ChatStore
    import api.routes.chat as chat_route

    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None)
    job = service.create_job("topic", "API provider", {"textProvider": "openrouter", "textModel": "openrouter/free"})
    calls = {}

    class FakeChat:
        def __init__(self):
            self.store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
            self.DEFAULT_API_PROVIDER = "openrouter"
            self.DEFAULT_API_MODEL = "openrouter/free"
            self.DEFAULT_MODEL = "GPT-5.6 Sol"

        def primary_account(self):
            return None

        def resolve_provider(self, provider, model):
            assert (provider, model) == ("openrouter", "openrouter/free")
            return provider, model, {"id": model, "capabilities": ["text"]}

        def stream_message(self, _conversation_id, payload):
            calls.update(payload)
            yield 'event: content.delta\ndata: {"delta":"answer"}\n\n'
            yield 'event: message.completed\ndata: {"content":"answer"}\n\n'

    monkeypatch.setattr(chat_route, "service", FakeChat())
    content, artifact = service._request_chat(job["id"], "hello", [])
    assert content == "answer"
    assert artifact is None
    assert calls["provider"] == "openrouter"
    assert calls["model"] == "openrouter/free"


def test_automation_sends_the_canonical_audio_first_prompt_unchanged(tmp_path, monkeypatch):
    import api.routes.chat as chat_route

    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None)
    job = service.create_job("ai_topic", "Canonical prompt", {"textProvider": "openrouter", "textModel": "openrouter/free"})
    calls = {}

    class FakeChat:
        def __init__(self):
            from pipeline.chat.store import ChatStore
            self.store = ChatStore(tmp_path / "chat.sqlite3", tmp_path / "attachments")
            self.DEFAULT_API_PROVIDER = "openrouter"
            self.DEFAULT_API_MODEL = "openrouter/free"
            self.DEFAULT_MODEL = "GPT-5.6 Sol"

        def primary_account(self):
            return None

        def resolve_provider(self, provider, model):
            return provider, model, {"id": model, "capabilities": ["text"]}

        def stream_message(self, _conversation_id, payload):
            calls.update(payload)
            yield 'event: content.delta\ndata: {"delta":"1. Topic"}\n\n'
            yield 'event: message.completed\ndata: {"content":"1. Topic"}\n\n'

    monkeypatch.setattr(chat_route, "service", FakeChat())
    prompt = service._topic_prompt("", {"language": "vi", "flow": {"promptEngine": "vi"}})
    service._request_chat(job["id"], prompt, [])

    assert calls["content"] == prompt
    assert len(calls["content"]) > 15_000
    assert "GIAI ĐOẠN 1: CHỌN CHỦ ĐỀ" in calls["content"]


def test_automation_provider_preflight_does_not_leak_api_key(tmp_path, monkeypatch):
    from pipeline.chat.providers import ProviderError
    import api.routes.chat as chat_route

    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None)
    job = service.create_job("topic", "Redacted", {"textProvider": "gemini", "textModel": "gemini-2.5-flash-lite"})

    class FakeChat:
        DEFAULT_API_PROVIDER = "openrouter"
        DEFAULT_API_MODEL = "openrouter/free"
        DEFAULT_MODEL = "GPT-5.6 Sol"

        def primary_account(self):
            return None

        def resolve_provider(self, _provider, _model):
            raise ProviderError("CHAT_PROVIDER_MODELS_UNAVAILABLE", "https://example.test/?key=gemini-secret")

    monkeypatch.setattr(chat_route, "service", FakeChat())
    import importlib
    automation_module = importlib.import_module("pipeline.automation.service")
    monkeypatch.setattr(automation_module, "load_app_config", lambda: {"cloud": {"gemini": {"apiKey": "gemini-secret"}}})
    with pytest.raises(RuntimeError) as failure:
        service._request_chat(job["id"], "hello", [])
    assert "gemini-secret" not in str(failure.value)


def test_compose_creates_render_work_directory_before_renderer(tmp_path, monkeypatch):
    from pipeline import srt_image

    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)
    job = service.create_job("bundle", "Render work", {})
    workspace = store.workspace(job["id"])
    image = workspace / "image.png"
    audio = workspace / "audio.wav"
    srt = workspace / "subtitles.srt"
    prompts = workspace / "prompts.txt"
    for path in (image, audio, srt, prompts):
        path.write_bytes(b"test")
    output = tmp_path / "output.mp4"
    output.write_bytes(b"video")
    captured: dict[str, object] = {}

    def fake_create_job(_name, work, *_args, **_kwargs):
        captured["work"] = work
        assert work.is_dir()
        return {"id": "render-1"}

    monkeypatch.setattr(srt_image, "create_job", fake_create_job)
    monkeypatch.setattr(srt_image, "start", lambda _job_id: None)
    monkeypatch.setattr(srt_image, "get_job", lambda _job_id: {"status": "done", "output": str(output)})

    service._compose(
        job["id"], [image], audio, srt, prompts,
        {"outputDir": str(tmp_path / "out"), "compose": {}}, workspace,
    )

    assert captured["work"] == workspace / "render-work"
    assert store.get_job(job["id"])["artifacts"]["video"] == str(output)


def test_compose_forwards_video_settings_and_can_disable_subtitles(tmp_path, monkeypatch):
    from pipeline import srt_image

    store = AutomationStore(tmp_path / "automation.sqlite3", tmp_path / "jobs")
    service = AutomationService(store=store, runner=lambda _job_id: None, max_workers=1)
    job = service.create_job("bundle", "Render options", {})
    workspace = store.workspace(job["id"])
    image = workspace / "image.png"
    audio = workspace / "audio.wav"
    srt = workspace / "subtitles.srt"
    image.write_bytes(b"test")
    audio.write_bytes(b"test")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello", encoding="utf-8")
    output = tmp_path / "output.mp4"
    output.write_bytes(b"video")
    captured: dict[str, object] = {}

    def fake_create_job(_name, _work, _images, _audio, _prompts, timeline, options, _watermark, _output):
        captured["timeline"] = timeline
        captured["options"] = options
        return {"id": "render-1"}

    monkeypatch.setattr(srt_image, "create_job", fake_create_job)
    monkeypatch.setattr(srt_image, "start", lambda _job_id: None)
    monkeypatch.setattr(srt_image, "get_job", lambda _job_id: {"status": "done", "output": str(output)})

    service._compose(
        job["id"], [image], audio, srt, None,
        {
            "outputDir": str(tmp_path / "out"),
            "compose": {
                "resolution": "1920x1080", "fps": 60, "crf": 18,
                "encoder": "cpu", "speed": 125, "volume": 80,
                "previewSeconds": 12, "removeMetadata": True,
                "allowMissingMedia": True, "subtitleEnabled": False,
            },
        }, workspace,
    )

    assert captured["timeline"] is None
    assert captured["options"] == {
        "resolution": "1920x1080", "fps": 60, "crf": 18,
        "encoder": "cpu", "speed": 125, "volume": 80,
        "previewSeconds": 12, "removeMetadata": True,
        "allowMissingMedia": True,
    }


def test_audio_first_engine_rules_are_included_for_script_and_image_prompts(tmp_path):
    service = AutomationService(store=AutomationStore(tmp_path / 'automation.sqlite3', tmp_path / 'jobs'), runner=lambda _job_id: None)
    settings = {"language": "vi", "flow": {"promptEngine": "vi"}}
    script = service._script_prompt("Chủ đề thử nghiệm", settings)
    image = service._image_prompt_request(settings)
    for prompt in (script, image):
        assert "ZMTOOL AUDIO-FIRST VIDEO PRODUCTION ENGINE V1.0" in prompt
        assert "Audio là nguồn chính" in prompt
    assert "đúng 5 ý tưởng video YouTube giáo dục" in service._topic_prompt("", settings)
    assert "lời thuyết minh thuần văn bản" in script
    assert "chia visual beat theo ý nghĩa" in image
