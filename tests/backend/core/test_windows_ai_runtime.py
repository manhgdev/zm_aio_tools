"""Desktop import/GPU checks must exercise the external interpreter, not the EXE."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.core import runtime_site
from pipeline.core.system_check import probe
from pipeline.tts.engines import vieneu_frozen as vf


def test_frozen_child_does_not_inherit_python_home(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PYTHONHOME", "C:/old-python")
    monkeypatch.setenv("PYTHONUSERBASE", "C:/old-packages")
    monkeypatch.setenv("VIDEO_CLONE_HOME", "C:/app data")
    env = runtime_site.subprocess_environment()
    assert "PYTHONHOME" not in env
    assert "PYTHONUSERBASE" not in env
    assert env["VIDEO_CLONE_HOME"] == "C:/app data"
    assert sys.modules["os"].environ["PYTHONHOME"] == "C:/old-python"


def test_missing_runtime_never_falls_back_to_desktop_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("VIDEO_CLONE_HOME", str(tmp_path))
    assert vf.runtime_python() != Path(sys.executable)
    assert vf.probe()[0] is False


@pytest.mark.parametrize("available", [False, True])
def test_cuda_readiness_is_not_hardware_preference(monkeypatch, available):
    monkeypatch.setattr(vf, "_CUDA_READY", None)
    monkeypatch.setattr("pipeline.core.accel.preferred_torch_device", lambda **_: "cuda")
    seen = []
    def run(code, **_):
        seen.append(code)
        return SimpleNamespace(returncode=0, stdout="1\n" if available else "0\n", stderr="")
    monkeypatch.setattr(vf, "_run_runtime", run)
    assert vf.runtime_torch_cuda_ready(refresh=True) is available
    assert seen and "synchronize" in seen[0]


def test_probe_rejects_lazy_transformers_import_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "_runtime_python", lambda: Path(sys.executable))
    def run(cmd, **_):
        def missing(name):
            raise ModuleNotFoundError("No module named 'pdb'")
        # Run the actual probe script with a package whose top-level import succeeds.
        import types
        package = types.ModuleType("transformers")
        package.__getattr__ = missing
        monkeypatch.setitem(sys.modules, "transformers", package)
        monkeypatch.setattr(sys, "argv", ["-c", '["transformers"]'])
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            exec(cmd[cmd.index("-c") + 1], {})
        return SimpleNamespace(returncode=0, stdout=output.getvalue(), stderr="")
    monkeypatch.setattr(probe.subprocess, "run", run)
    ok, detail = probe._runtime_mod_ok("transformers")
    assert not ok
    assert "pdb" in detail


def test_probe_keeps_result_despite_library_stdout(monkeypatch):
    monkeypatch.setattr(probe, "_runtime_python", lambda: Path(sys.executable))
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='SDK log\n' + json.dumps({"torch": [True, "ok"]}) + '\n', stderr=''))
    assert probe._runtime_mod_ok("torch")[0]


def test_transformers_verification_uses_runtime_in_frozen_parent(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(probe, "_runtime_mod_ok", lambda name: (True, "runtime ok"))
    monkeypatch.setattr(runtime_site, "install_runtime_meta_path", lambda *a, **kw: pytest.fail("native import in EXE"))
    assert runtime_site.verify_transformers_ok() == (True, "runtime ok")


def test_gpu_probe_requires_clean_exit(monkeypatch):
    from pipeline.core import accel
    monkeypatch.setattr(accel.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="cuda\n", stderr="DLL failure"))
    assert accel._probe_torch_device_in(sys.executable) == "cpu"


def test_install_button_does_not_short_circuit_on_dist_info(monkeypatch):
    from api.routes import system
    from pipeline.core import system_check

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(system_check, "_runtime_venv_fast", lambda: pytest.fail("metadata is not an import probe"))
    monkeypatch.setattr(system, "_start_install_job", lambda kind, fn: {"kind": kind, "fn": fn})
    result = system.api_install_ai_runtime()
    assert result == {"kind": "ai_runtime", "fn": system_check.install_ai_runtime}


@pytest.mark.parametrize("bad_import,cuda_ready,expected", [
    (True, True, "AI_RUNTIME_IMPORT_FAILED"),
    (False, False, "AI_RUNTIME_CUDA_UNAVAILABLE"),
])
def test_install_verification_fails_on_broken_runtime(monkeypatch, bad_import, cuda_ready, expected):
    from pipeline.core.system_check import install

    monkeypatch.setattr(install, "_invalidate_checks_cache", lambda: None)
    monkeypatch.setattr(install, "_runtime_modules_batch_ok", lambda names: {
        name: (not (bad_import and name == "transformers"), "pdb missing") for name in names
    })
    monkeypatch.setattr(install, "_nvidia_present", lambda: True)
    monkeypatch.setattr(install, "_torch_cuda_ready", lambda: cuda_ready)
    with pytest.raises(RuntimeError, match=expected):
        install._verify_frozen_runtime_install()


def test_frozen_torch_ensure_never_imports_native_modules(monkeypatch):
    from pipeline.core.system_check import install

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(install, "_torch_warm_done", False)
    monkeypatch.setattr(install, "_runtime_torch_needs_install", lambda: False)
    monkeypatch.setattr(runtime_site, "install_runtime_meta_path", lambda *a, **kw: pytest.fail("native import in EXE"))
    install.ensure_runtime_torch()


def test_missing_stdlib_does_not_trigger_pip_loop(monkeypatch):
    from pipeline.core.system_check import install

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_site, "verify_transformers_ok", lambda: (False, "No module named 'pdb'"))
    monkeypatch.setattr(install, "_runtime_pip_install", lambda *a, **kw: pytest.fail("pdb is not a pip package"))
    with pytest.raises(RuntimeError, match="AI_RUNTIME_STDLIB_MISSING"):
        install.ensure_runtime_transformers()


def test_invalidate_clears_gpu_readiness(monkeypatch):
    from pipeline.core import accel

    monkeypatch.setattr(vf, "_CUDA_READY", False)
    monkeypatch.setattr(accel, "_cache", {"torch_device": "cuda"})
    probe._invalidate_probe_caches()
    assert vf._CUDA_READY is None
    assert not accel._cache


def test_vieneu_rpc_timeout_closes_worker(monkeypatch):
    import io
    import queue
    import threading
    from collections import deque

    worker = vf._Worker.__new__(vf._Worker)
    worker.proc = SimpleNamespace(stdin=io.BytesIO(), stdout=object(), poll=lambda: None)
    worker._lock = threading.Lock()
    worker._responses = queue.Queue()
    worker._stderr = deque(["DLL load blocked"])
    closed = []
    monkeypatch.setattr(worker, "close", lambda: closed.append(True))
    result = worker._rpc({"op": "ping"}, timeout=0.02)
    assert closed
    assert not result["ok"] and "timeout" in result["error"]
    assert "DLL load blocked" in result["error"]


def test_installer_timeout_includes_silent_child():
    import subprocess
    from pipeline.core.system_check import install

    with pytest.raises(subprocess.TimeoutExpired):
        install._pip_stream([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)


def test_packaged_stdlib_check_runs_without_gui(tmp_path):
    import subprocess

    report = tmp_path / "import report.json"
    proc = subprocess.run([sys.executable, "build_app/launcher.py", "--runtime-import-check", str(report)], timeout=15)
    assert proc.returncode == 0
    assert json.loads(report.read_text())["ok"]


@pytest.mark.parametrize("caps,expected", [("8.6\n", "cu124"), ("8.9\n12.0\n", "cu128"), ("N/A\n", "cu124")])
def test_torch_wheel_index_supports_modern_nvidia(monkeypatch, caps, expected):
    from pipeline.core.system_check import install

    monkeypatch.setattr(install.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=caps))
    assert install._runtime_torch_cuda_index().endswith(expected)


def test_external_child_resets_and_restores_bootloader_dll_search(monkeypatch):
    import ctypes

    calls = []
    def get_dir(size, buffer):
        buffer.value = "C:/app/_internal"
        return len(buffer.value)
    kernel = SimpleNamespace(GetDllDirectoryW=get_dir, SetDllDirectoryW=lambda path: calls.append(path) or 1)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError):
        with runtime_site.external_process_dll_search("C:/runtime/python.exe"):
            assert calls == [None]
            raise ValueError("spawn failed")
    assert calls == [None, "C:/app/_internal"]
    with runtime_site.external_process_dll_search(sys.executable):
        pass
    assert len(calls) == 2


def test_uv_uninstall_does_not_use_pip_only_yes_flag(monkeypatch, tmp_path):
    from pipeline.core.system_check import install

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(install, "_find_uv", lambda: "uv.exe")
    monkeypatch.setattr(install, "_video_clone_home", lambda: tmp_path)
    monkeypatch.setattr(install, "_ensure_frozen_runtime_venv", lambda *a: tmp_path / "python.exe")
    cmd = install._runtime_pip_uninstall_cmd("torch", "torchaudio")
    assert cmd[:3] == ["uv.exe", "pip", "uninstall"]
    assert "-y" not in cmd and "torch" in cmd
