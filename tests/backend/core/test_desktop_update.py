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
    assert system._release_checksum_asset(release, "missing.pkg") is None


def test_windows_asset_and_checksum_are_paired(monkeypatch):
    release = _release(
        {"name": "ZM_AIO_TOOL_v3.5.7-windows-x64.zip"},
        {"name": "ZM_AIO_TOOL_v3.5.7-windows-x64.zip.sha256"},
    )
    monkeypatch.setattr(system.sys, "platform", "win32")
    asset = system._release_asset(release)
    assert asset and asset["name"].endswith("-windows-x64.zip")
    assert system._release_checksum_asset(release, asset["name"])["name"].endswith(".sha256")


def test_update_rejects_asset_with_a_different_version(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "win32")
    release = _release({"name": "ZM_AIO_TOOL_v3.5.6-windows-x64.zip"})
    assert system._release_asset(release) is None


def test_update_check_needs_a_matching_checksum(monkeypatch):
    monkeypatch.setenv("VIDEO_CLONE_DESKTOP", "1")
    monkeypatch.setattr(system.sys, "frozen", True, raising=False)
    monkeypatch.setattr(system.sys, "platform", "win32")
    monkeypatch.setattr(system, "_desktop_version", lambda: "3.5.6")
    monkeypatch.setattr(system, "_latest_release", lambda: _release({"name": "ZM_AIO_TOOL_v3.5.7-windows-x64.zip"}))
    result = system.api_update_check()
    assert result["assetAvailable"] is True
    assert result["checksumAvailable"] is False
    assert result["releaseAvailable"] is True
    assert result["updateAvailable"] is False


def test_download_update_rejects_bad_checksum(monkeypatch, tmp_path):
    payload = b"desktop-package"

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(system, "_read_checksum", lambda _asset: "0" * 64)
    monkeypatch.setattr(system.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(payload))
    asset = {"name": "app.zip", "browser_download_url": "https://example.invalid/app.zip"}
    try:
        system._download_update(asset, {}, tmp_path, "3.5.7")
    except RuntimeError as exc:
        assert "Checksum" in str(exc)
    else:
        raise AssertionError("bad checksum must fail")
    assert not (tmp_path / "app.zip.part").exists()


def test_windows_update_script_uses_staged_replace_and_rollback(tmp_path):
    script = system._windows_update_script(tmp_path)
    text = script.read_text(encoding="utf-8")
    assert "Expand-Archive" in text
    assert "Move-Item -LiteralPath $Target -Destination $backup" in text
    assert "Move-Item -LiteralPath $backup -Destination $Target" in text
    assert "ZM AIO TOOL.exe" in text
    assert "VERSION" in text
