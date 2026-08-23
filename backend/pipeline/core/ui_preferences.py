"""Persistent, non-sensitive desktop UI preferences."""
from __future__ import annotations

import json
from pathlib import Path

from .config import DATA

_PREFERENCES_PATH = DATA / "ui_preferences.json"
_SUPPORTED_LOCALES = {"vi", "en"}
_MAX_STORAGE_ITEM_BYTES = 512_000
_MAX_STORAGE_BYTES = 2_000_000


def load_ui_preferences() -> dict[str, object]:
    try:
        saved = json.loads(_PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    locale = saved.get("locale")
    storage = saved.get("storage")
    return {
        "locale": locale if locale in _SUPPORTED_LOCALES else None,
        "storage": storage if isinstance(storage, dict) else {},
    }


def save_ui_preferences(
    *, locale: str | None = None, storage: dict[str, str] | None = None
) -> dict[str, object]:
    current = load_ui_preferences()
    if locale is not None:
        if locale not in _SUPPORTED_LOCALES:
            raise ValueError("Unsupported locale")
        current["locale"] = locale
    if storage is not None:
        clean: dict[str, str] = {}
        total = 0
        for key, value in storage.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            size = len(value.encode("utf-8"))
            if size > _MAX_STORAGE_ITEM_BYTES:
                continue
            total += len(key.encode("utf-8")) + size
            if total > _MAX_STORAGE_BYTES:
                break
            clean[key] = value
        current["storage"] = clean
    _PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFERENCES_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return current
