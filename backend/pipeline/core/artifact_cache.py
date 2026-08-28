"""Persistent artifact cache shared by deterministic app pipelines."""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from pipeline.core.config import DATA

_LOCK = threading.Lock()


class ArtifactCache:
    def __init__(self, namespace: str, *, version: int = 1, root: Path | None = None) -> None:
        self.namespace = namespace
        self.version = version
        self.root = (root or DATA / "artifact_cache") / namespace

    @staticmethod
    def _signature(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {"path": str(path.resolve()), "size": stat.st_size, "mtimeNs": stat.st_mtime_ns}

    def key(
        self, *, inputs: list[Path] | tuple[Path, ...] = (),
        settings: dict[str, Any] | None = None, values: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "namespace": self.namespace, "version": self.version,
            "inputs": [self._signature(path) for path in inputs if path.is_file()],
            "settings": settings or {}, "values": values or {},
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def files(self, key: str) -> dict[str, Path]:
        folder = self.root / key
        manifest = folder / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            names = data.get("files") if isinstance(data, dict) else None
            if not isinstance(names, list):
                return {}
            result = {str(name): folder / str(name) for name in names}
            return result if result and all(path.is_file() for path in result.values()) else {}
        except (OSError, ValueError):
            return {}

    def restore(self, key: str, targets: dict[str, Path]) -> bool:
        sources = self.files(key)
        if not targets or any(name not in sources for name in targets):
            return False
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sources[name], target)
        return True

    def store(self, key: str, artifacts: dict[str, Path]) -> None:
        valid = {name: source for name, source in artifacts.items() if source.is_file()}
        if not valid:
            return
        folder = self.root / key
        temporary = self.root / f".{key}.tmp"
        with _LOCK:
            shutil.rmtree(temporary, ignore_errors=True)
            temporary.mkdir(parents=True, exist_ok=True)
            for name, source in valid.items():
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            (temporary / "manifest.json").write_text(
                json.dumps({"files": list(valid), "createdAt": int(time.time())}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            shutil.rmtree(folder, ignore_errors=True)
            temporary.replace(folder)
