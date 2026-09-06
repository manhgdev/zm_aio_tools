"""Chốt các lỗi phát hiện trong đợt audit toàn bộ src — không cho tái phát."""
from pathlib import Path

from pipeline.core.cleanup import _is_purgeable, cleanup_public_files
from pipeline.core.config import safe_child
from pipeline.export.srt import write_subtitle


def test_safe_child_blocks_traversal(tmp_path: Path):
    base = tmp_path / "tts"
    base.mkdir()
    assert safe_child(base, "a.wav") == base / "a.wav"
    for bad in ("..", "../x", r"..\..\secret.env", "/etc/passwd", r"C:\Windows\x", "", "."):
        assert safe_child(base, bad) is None, bad


def test_cleanup_never_deletes_user_data(tmp_path: Path):
    project = tmp_path / "p1"
    (project / "cache").mkdir(parents=True)
    source = project / "source.mp4"
    meta = project / "meta.json"
    tts = project / "tts"
    tts.mkdir()
    voice = tts / "seg1.wav"
    cache_file = project / "cache" / "preview_5.mp4"
    for f in (source, meta, voice, cache_file):
        f.write_bytes(b"x")
        # quá hạn (mtime rất cũ)
        import os

        os.utime(f, (0, 0))
    assert _is_purgeable(cache_file, tmp_path)
    assert not _is_purgeable(source, tmp_path)
    assert not _is_purgeable(meta, tmp_path)
    assert not _is_purgeable(voice, tmp_path)
    deleted, _skipped = cleanup_public_files(tmp_path, retention_days=1)
    assert deleted == 1
    assert source.is_file() and meta.is_file() and voice.is_file()
    assert not cache_file.exists()


def test_subtitle_formats_are_real(tmp_path: Path):
    cues = [{"start": 0, "end": 1.5, "text": "Xin chao"}, {"start": 2, "end": 3, "text": "The gioi"}]
    vtt = tmp_path / "a.vtt"
    write_subtitle(vtt, cues, "vtt", capcut=False)
    body = vtt.read_text(encoding="utf-8")
    assert body.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in body  # dấu chấm, không phải phẩy
    txt = tmp_path / "a.txt"
    write_subtitle(txt, cues, "txt", capcut=False)
    assert txt.read_text(encoding="utf-8").splitlines() == ["Xin chao", "The gioi"]
    srt = tmp_path / "a.srt"
    write_subtitle(srt, cues, "srt", capcut=False)
    assert "00:00:00,000 --> 00:00:01,500" in srt.read_text(encoding="utf-8-sig")


def test_write_ass_and_cover_box_over_do_not_raise(tmp_path: Path):
    """Hai NameError chắc chắn (thiếu import / hằng) — gọi thật để chốt."""
    from pipeline.export.burn_parts.ass_util import write_ass
    from pipeline.export.burn_parts.layout_geo import _cover_box_over

    out = tmp_path / "a.ass"
    write_ass(out, [{"start": 0, "end": 1, "translation": "xin chao"}], 1280, 720)
    assert out.stat().st_size > 0
    box = _cover_box_over(None, (10, 10, 200, 60), 40, 1280, 720)
    assert box[2] > box[0] and box[3] > box[1]


def test_tts_fit_never_stretches_video():
    """Contract 2026-07-27: thước bất khả xâm phạm — không bao giờ gán
    videoSpeed; miền auto (<1) còn sót phải bị dọn, speed user (≥1) giữ."""
    from pipeline.orchestrate.tts_fit import assign_tts_fit_speeds

    segs = [{"id": "a", "start": 0, "end": 2.1, "audioDuration": 3.0}]
    assign_tts_fit_speeds(segs, match="preferVideo")
    assert "videoSpeed" not in segs[0]
    # videoSpeed auto cũ (<1) → dọn; user đặt 1.5× → giữ
    segs2 = [
        {"id": "a", "start": 0, "end": 2, "videoSpeed": 0.82},
        {"id": "b", "start": 3, "end": 5, "videoSpeed": 1.5},
    ]
    assign_tts_fit_speeds(segs2, match="preferVideo")
    assert "videoSpeed" not in segs2[0]
    assert segs2[1]["videoSpeed"] == 1.5


def test_fit_tts_audio_compresses_to_slot(tmp_path):
    """Wav dài hơn khe tới câu sau → atempo nén, audioDuration cập nhật."""
    import subprocess

    from pipeline.orchestrate.tts_fit import fit_tts_audio_to_slots

    (tmp_path / "tts").mkdir()
    wav = tmp_path / "tts" / "a.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=4", str(wav)],
        check=True, capture_output=True,
    )
    segs = [
        {"id": "a", "start": 0.0, "end": 2.0, "audioFile": "a.wav", "audioDuration": 4.0},
        {"id": "b", "start": 2.5, "end": 4.0},
    ]
    n = fit_tts_audio_to_slots(segs, tmp_path, match="preferVideo")
    assert n == 1
    # Tổng tăng tốc tự động bị chặn 1.15×: wav 4s còn khoảng 3.48s.
    assert 3.4 < segs[0]["audioDuration"] < 3.6


def test_translate_parent_does_not_probe_cv2_or_ort():
    """Sau ASR/dịch, parent không import OpenCV/ORT — native crash tắt app."""
    import pipeline.orchestrate.asr_translate as asr_translate

    src = Path(asr_translate.__file__).read_text(encoding="utf-8")
    assert "ensure_cv2" not in src
    assert "_rapidocr_gpu_kwargs" not in src
    assert "generate_inpaint_preview" not in src


def test_translate_only_detects_logo_when_logo_cover_is_enabled():
    """Logo OCR must not add a costly detection step to ordinary jobs."""
    import pipeline.orchestrate.asr_translate as asr_translate

    src = Path(asr_translate.__file__).read_text(encoding="utf-8")
    assert 'if bool(settings.get("coverLogo", False)) and logo_stale:' in src


def test_job_python_frozen_is_not_the_exe(monkeypatch, tmp_path) -> None:
    import importlib.util

    path = Path("backend/api/job_spawn.py")
    spec = importlib.util.spec_from_file_location("vc_job_spawn", path)
    assert spec and spec.loader
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)

    runtime = tmp_path / "python.exe"
    runtime.write_text("", encoding="utf-8")
    monkeypatch.setattr(js.sys, "frozen", True, raising=False)
    monkeypatch.setattr("pipeline.core.accel._runtime_python", lambda: str(runtime))
    assert js._job_python() == str(runtime)


def test_win_jobs_stay_out_of_uvicorn() -> None:
    spawn = Path("backend/api/job_spawn.py").read_text(encoding="utf-8")
    assert "_run_in_subprocess" in spawn
    locate = Path("backend/pipeline/ocr/locate.py").read_text(encoding="utf-8")
    assert "không chạy OCR trong process API" in locate


def test_job_worker_does_not_require_utf8_sig_codec_alias() -> None:
    source = Path("backend/api/job_spawn.py").read_text(encoding="utf-8")
    assert 'read_text(encoding="utf-8-sig")' not in source
    assert 'removeprefix(b"\\\\xef\\\\xbb\\\\xbf").decode("utf-8")' in source


def test_windows_job_environment_sanitizes_inherited_path(monkeypatch) -> None:
    import importlib.util

    path = Path("backend/api/job_spawn.py")
    spec = importlib.util.spec_from_file_location("vc_job_spawn_env", path)
    assert spec and spec.loader
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)
    monkeypatch.setattr(js.sys, "platform", "win32")
    monkeypatch.setenv("PATH", r"C:\\Tools;c:/tools;C:\\Windows")

    env = js._worker_environment(Path("C:/backend"))

    assert env["PATH"] == r"C:\\Tools;C:\\Windows"


def test_windows_job_spawn_error_updates_project_status(monkeypatch, tmp_path) -> None:
    import importlib.util

    path = Path("backend/api/job_spawn.py")
    spec = importlib.util.spec_from_file_location("vc_job_spawn_error", path)
    assert spec and spec.loader
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)
    errors: list[tuple[object, str, str]] = []
    monkeypatch.setattr(js.time if hasattr(js, "time") else __import__("time"), "sleep", lambda _n: None)
    monkeypatch.setattr(js, "_job_python", lambda: "python.exe")
    monkeypatch.setattr(js.subprocess, "Popen", lambda *_a, **_k: (_ for _ in ()).throw(OSError(206, "The filename or extension is too long")))
    monkeypatch.setattr(js, "_mark_job_error", lambda project, job, msg: errors.append((project, job, msg)))

    def fake_job(_project_id):
        return None

    js._run_in_subprocess(fake_job, ("project-1",))

    assert errors and errors[0][:2] == ("project-1", "fake_job")
    assert "WinError 206" in errors[0][2]


def test_windows_job_worker_timeout_updates_project_status(monkeypatch) -> None:
    import importlib.util
    import subprocess

    path = Path("backend/api/job_spawn.py")
    spec = importlib.util.spec_from_file_location("vc_job_spawn_timeout", path)
    assert spec and spec.loader
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)
    errors: list[tuple[object, str, str]] = []

    class HangingProcess:
        returncode = 124

        def poll(self):
            return None

        def communicate(self, **_kwargs):
            if not getattr(self, "killed", False):
                raise subprocess.TimeoutExpired("python", 1)
            return b"", b""

        def kill(self):
            self.killed = True

    monkeypatch.setattr(js.sys, "platform", "win32")
    monkeypatch.setattr(js, "_job_python", lambda: "python.exe")
    monkeypatch.setattr(js.subprocess, "Popen", lambda *_a, **_k: HangingProcess())
    monkeypatch.setattr(js, "_mark_job_error", lambda project, job, msg: errors.append((project, job, msg)))
    js._run_in_subprocess(lambda _project_id: None, ("project-1",))

    assert errors and errors[0][:2] == ("project-1", "<lambda>")
    assert "timeout" in errors[0][2].lower()


def test_ai_subprocesses_use_the_shared_sanitized_environment() -> None:
    for path in (
        "backend/api/job_spawn.py",
        "backend/pipeline/asr/whisper.py",
        "backend/pipeline/tts/engines/vieneu.py",
        "backend/pipeline/tts/engines/vieneu_frozen.py",
        "backend/pipeline/ocr/extract_parts/api.py",
        "backend/pipeline/ocr/locate_worker.py",
        "backend/pipeline/export/stem.py",
        "backend/pipeline/drawing/jobs.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "subprocess_environment" in source, path


def test_desktop_launcher_sanitizes_windows_path_before_bundle_append() -> None:
    launcher = Path("build_app/launcher.py").read_text(encoding="utf-8")
    assert "sanitize_process_environment" in launcher
    assert launcher.index("sanitize_process_environment") < launcher.index("os.environ[\"PATH\"] = os.pathsep.join")


def test_frozen_vieneu_does_not_import_native_runtime_in_api_process() -> None:
    source = Path("backend/pipeline/tts/engines/vieneu.py").read_text(encoding="utf-8")
    frozen_branch = source.split("if getattr(sys, \"frozen\", False):", 1)[1].split("return None", 1)[0]
    assert "ensure_runtime_torch" not in frozen_branch
    assert "ensure_runtime_transformers" not in frozen_branch


def test_ollama_detector_covers_gui_app_paths_on_macos() -> None:
    source = Path("backend/pipeline/core/system_check/checks.py").read_text(encoding="utf-8")
    assert "/Applications/Ollama.app/Contents/Resources/ollama" in source
    assert "/opt/homebrew/bin/ollama" in source
    assert "/usr/local/bin/ollama" in source
    assert "os.access(path, os.X_OK)" in source


def test_ytdlp_detector_covers_gui_app_and_bundle_paths() -> None:
    source = Path("backend/pipeline/core/executables.py").read_text(encoding="utf-8")
    assert "/opt/homebrew/bin/yt-dlp" in source
    assert ".pyenv/shims/yt-dlp" in source
    assert 'root.parent / "Frameworks"' in source
    for consumer in (
        "backend/pipeline/download/ytdlp_jobs.py",
        "backend/pipeline/srt_export.py",
    ):
        text = Path(consumer).read_text(encoding="utf-8")
        assert "ytdlp_command()" in text


def test_desktop_bundle_exposes_embedded_ytdlp_cli() -> None:
    launcher = Path("build_app/launcher.py").read_text(encoding="utf-8")
    build = Path("build_app/build.mjs").read_text(encoding="utf-8")
    check = Path("build_app/check_build.mjs").read_text(encoding="utf-8")
    assert 'sys.argv[1] == "--yt-dlp-cli"' in launcher
    assert "from yt_dlp import main as ytdlp_main" in launcher
    assert "'--collect-all', 'yt_dlp'" in build
    assert "yt-dlp embedded CLI" in check


def test_desktop_build_uses_the_ci_release_version_file() -> None:
    """Tag builds must name artifacts with the version written by their workflow."""
    build = Path("build_app/build.mjs").read_text(encoding="utf-8")
    assert "releaseVersionFilePath" in build
    assert "readFileSync(releaseVersionFilePath, \"utf8\")" in build


def test_windows_bundle_keeps_pdb_for_external_transformers() -> None:
    """Transformers loaded from the runtime venv still imports stdlib pdb."""
    build = Path("build_app/build.mjs").read_text(encoding="utf-8")
    assert "'--hidden-import', 'pdb'" in build
    excludes = build.split("for (const mod of [", 1)[1].split("]) args.push", 1)[0]
    assert "'pdb'" not in excludes


def test_macos_installer_replaces_legacy_versioned_app_bundles() -> None:
    """A stable payload prevents every update from adding another .app."""
    workflow = Path(".github/workflows/release-macos.yml").read_text(encoding="utf-8")
    assert "matrix:" in workflow
    assert "runner: macos-14" in workflow
    assert "arch: arm64" in workflow
    assert "runner: macos-15-intel" in workflow
    assert "arch: x64" in workflow
    assert "runs-on: ${{ matrix.runner }}" in workflow
    assert 'payload="$stage/ZM AIO TOOL.app"' in workflow
    assert 'pkgbuild --component "$payload" --scripts "$scripts" --install-location /Applications "$pkg"' in workflow
    assert 'close_running_bundle "/Applications/ZM AIO TOOL.app"' in workflow
    assert 'local executable="$1/Contents/MacOS/ZM AIO TOOL"' in workflow
    assert '/bin/kill -TERM $pids || true' in workflow
    assert 'cat > "$scripts/postinstall"' in workflow
    assert '/bin/launchctl asuser "$user_id" /usr/bin/open "$app"' in workflow
    assert 'for legacy in /Applications/ZM_AIO_TOOL_v*.app; do' in workflow
    assert 'if [ -d "$legacy" ]; then' in workflow
    assert '/bin/rm -rf "$legacy" || true' in workflow
    assert 'exit 0' in workflow


def test_macos_release_assets_are_architecture_specific_without_checksum_sidecars() -> None:
    workflow = Path(".github/workflows/release-macos.yml").read_text(encoding="utf-8")
    assert "macos-${ARCH}.pkg" in workflow
    assert ".sha256" not in workflow
    assert "macos-13" not in workflow


def test_desktop_launcher_never_inherits_installer_temp_directory() -> None:
    """Playwright must not write artifacts into a deleted PKInstallSandbox."""
    launcher = Path("build_app/launcher.py").read_text(encoding="utf-8")
    assert "configure_stable_temp_directory" in launcher
    assert 'temp_dir = app_data / "tmp"' in launcher
    assert 'for name in ("TMPDIR", "TMP", "TEMP")' in launcher
    assert "os.environ[name] = str(temp_dir)" in launcher


def test_desktop_launcher_uses_an_os_assigned_loopback_port() -> None:
    """The packaged app must not reserve or scan a user-visible fixed port."""
    launcher = Path("build_app/launcher.py").read_text(encoding="utf-8")
    assert "api_socket.bind((API_HOST, 0))" in launcher
    assert 'kwargs={"sockets": [api_socket]}' in launcher
    assert "API_PORT_PREFERRED" not in launcher
    assert "API_PORT_SCAN" not in launcher


def test_desktop_launcher_starts_maximized() -> None:
    launcher = Path("build_app/launcher.py").read_text(encoding="utf-8")
    assert "maximized=True" in launcher
    assert "fullscreen=True" not in launcher


def test_render_delete_is_safe_when_the_output_disappears() -> None:
    source = Path("backend/api/routes/rendered.py").read_text(encoding="utf-8")
    assert "path.unlink(missing_ok=True)" in source


def test_desktop_supervisor_shows_copyable_crash() -> None:
    src = Path("build_app/launcher.py").read_text(encoding="utf-8")
    assert "VIDEO_CLONE_SUPERVISOR_CHILD" in src
    assert "show_copyable_crash" in src
    assert "Chép lỗi" in src
    assert "last_crash.txt" in src
    assert "Zone.Identifier" in src
    assert "Python.Runtime.dll" in src
    assert "webview/lib" in src
    assert "*.pyd" in src
    assert "prepare_pythonnet" in src
