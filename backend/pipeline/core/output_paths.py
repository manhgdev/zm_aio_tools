"""Stable user-visible output folders, grouped by application tab."""
from __future__ import annotations

import re
from pathlib import Path


APP_OUTPUT_ROOT_NAME = "ZM_AIO_TOOL"
_OUTPUT_SUBFOLDERS: dict[str, tuple[str, ...]] = {
    "video-clone": ("clone",),
    "clone": ("clone",),
    "film": ("review",),
    "review": ("review",),
    "flow": ("flow",),
    "download-video": ("download-video",),
    "tts": ("text-to-speech",),
    "subtitle-export": ("subtitles", "export"),
    "subtitle-image": ("subtitles", "image-video"),
    "drawing": ("drawing",),
    "cleaner": ("cleaner",),
    "batch": ("batch",),
}


def safe_output_part(value: object, fallback: str = "output", *, max_length: int = 96) -> str:
    """Return one filesystem-safe name component for generated outputs."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or fallback)).strip(" .-")
    return (safe or fallback)[:max_length]


def nested_output_folder(
    root: Path,
    group: object,
    item_id: object,
    *,
    create: bool = True,
) -> Path:
    """Build ``root/group/item-id`` consistently for generated artifacts."""
    folder = root / safe_output_part(group, "results") / safe_output_part(item_id, "item")
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def item_output_folder(root: Path, item_id: object, *, create: bool = True) -> Path:
    """Build ``root/item-id`` for an explicitly selected output root."""
    folder = root / safe_output_part(item_id, "item")
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def app_output_root() -> Path:
    """Return the single APP output root shared by every feature."""
    folder = Path.home() / "Downloads" / APP_OUTPUT_ROOT_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def downloads_folder(tab: str) -> Path:
    """Return one feature subfolder inside the shared APP output root."""
    key = str(tab or "video-clone").strip().lower()
    parts = _OUTPUT_SUBFOLDERS.get(key, (safe_output_part(key, "video-clone"),))
    folder = app_output_root().joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def selected_or_default(tab: str, selected: str = "") -> Path:
    """Honor an explicit desktop choice; otherwise use the shared Downloads tree."""
    raw = selected.strip()
    folder = Path(raw).expanduser() if raw else downloads_folder(tab)
    if raw and not folder.is_absolute():
        safe_parts = [safe_output_part(part) for part in folder.parts if part not in {"", ".", ".."}]
        folder = downloads_folder(tab).joinpath(*safe_parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder
