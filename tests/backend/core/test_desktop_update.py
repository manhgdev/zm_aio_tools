import io
from api.routes import system


def _release(*assets):
    return {"tag_name": "v3.5.7", "assets": list(assets)}


def test_update_selects_only_matching_macos_architecture():
    release = _release(
        {"name": "ZM_AIO_TOOL_v3.5.7-macos-arm64.pkg"},
        {"name": "ZM_AIO_TOOL_v3.5.7-macos-x64.pkg"},
    )
    assert system._desktop_platform_asset_suffix("darwin", "arm64") == "-macos-arm64.pkg"
    assert system._desktop_platform_asset_suffix("darwin", "x86_64") == "-macos-x64.pkg"


def test_windows_asset_is_selected_for_windows(monkeypatch):
    release = _release(
        {"name": "ZM_AIO_TOOL_v3.5.7-windows-x64.zip"},
    )
    monkeypatch.setattr(system.sys, "platform", "win32")
    asset = system._release_asset(release)
    assert asset and asset["name"].endswith("-windows-x64.zip")


def test_update_rejects_asset_with_a_different_version(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "win32")
    release = _release({"name": "ZM_AIO_TOOL_v3.5.6-windows-x64.zip"})
    assert system._release_asset(release) is None


def test_update_rejects_asset_with_a_version_prefix_collision(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "win32")
    release = _release({"name": "ZM_AIO_TOOL_v3.5.70-windows-x64.zip"})
    assert system._release_asset(release) is None


def test_update_check_accepts_matching_platform_asset_without_checksum(monkeypatch):
    monkeypatch.setenv("VIDEO_CLONE_DESKTOP", "1")
    monkeypatch.setattr(system.sys, "frozen", True, raising=False)
    monkeypatch.setattr(system.sys, "platform", "win32")
    monkeypatch.setattr(system, "_desktop_version", lambda: "3.5.6")
    monkeypatch.setattr(system, "_latest_release", lambda: _release({"name": "ZM_AIO_TOOL_v3.5.7-windows-x64.zip"}))
    result = system.api_update_check()
    assert result["assetAvailable"] is True
    assert result["releaseAvailable"] is True
    assert result["updateAvailable"] is True


def test_download_update_writes_the_release_asset(monkeypatch, tmp_path):
    payload = b"desktop-package"

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(system.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(payload))
    asset = {"name": "app.zip", "browser_download_url": "https://example.invalid/app.zip"}
    target = system._download_update(asset, tmp_path, "3.5.9")
    assert target.read_bytes() == payload
    assert not (tmp_path / "app.zip.part").exists()


def test_download_update_allows_slow_large_downloads_and_cleans_partial(monkeypatch, tmp_path):
    calls = []

    class BrokenResponse(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            raise TimeoutError("connection stalled")

    def open_url(_url, **kwargs):
        calls.append(kwargs)
        return BrokenResponse()

    monkeypatch.setattr(system.urllib.request, "urlopen", open_url)
    try:
        system._download_update(
            {"name": "app.zip", "browser_download_url": "https://example.invalid/app.zip"},
            tmp_path,
            "5.0.1",
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected download failure")
    assert calls and calls[0]["timeout"] == system._UPDATE_DOWNLOAD_TIMEOUT_SECONDS
    assert not (tmp_path / "app.zip.part").exists()


def test_download_update_rejects_path_traversal_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(system.urllib.request, "urlopen", lambda *_a, **_k: None)
    try:
        system._download_update(
            {"name": "../app.zip", "browser_download_url": "https://example.invalid/app.zip"},
            tmp_path,
            "5.0.1",
        )
    except RuntimeError as exc:
        assert "không hợp lệ" in str(exc)
    else:
        raise AssertionError("expected invalid asset name")


def test_update_module_has_time_for_background_update_lifecycle():
    """The packaged updater must not fail with NameError while waiting/polling."""
    assert hasattr(system, "time")


def test_windows_update_script_uses_staged_replace_and_rollback(tmp_path):
    script = system._windows_update_script(tmp_path)
    text = script.read_text(encoding="utf-8")
    assert "param([string]$ParamsFile)" in text
    assert "$AppPid    = [int]$p.AppPid" in text
    assert "Wait-Process -Id $AppPid" in text
    assert "[int]$Pid" not in text
    assert "Expand-Archive" in text
    assert "Move-Item -LiteralPath $Target -Destination $backup" in text
    assert "Move-Item -LiteralPath $backup -Destination $Target" in text
    assert "Start-Process -FilePath \"$newExe\"" in text
    assert "Start-Process explorer.exe" in text


def test_windows_updater_writes_params_and_starts_detached(monkeypatch, tmp_path):
    package = tmp_path / "ZM_AIO_TOOL_v4.9.8-windows-x64.zip"
    package.write_bytes(b"zip")
    old = tmp_path / "ZM_AIO_TOOL_v4.9.7-windows-x64"
    old.mkdir()
    exe = old / "ZM AIO TOOL.exe"
    exe.write_bytes(b"exe")
    calls = []
    monkeypatch.setattr(system.sys, "executable", str(exe))
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)))

    system._launch_windows_updater(package)

    params = (tmp_path / "update-params.json").read_text(encoding="utf-8")
    assert '"Target":' in params and "v4.9.8" in params
    assert '"OldTarget":' in params and "v4.9.7" in params
    assert calls and calls[0][0][0].lower().endswith("powershell.exe")
    assert calls[0][1]["creationflags"] & 0x00000008
