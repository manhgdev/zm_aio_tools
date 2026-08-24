"""Stable user-visible output folders, grouped by application tab."""
from __future__ import annotations

import re
from pathlib import Path


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


def downloads_folder(tab: str) -> Path:
    """Return and create the default output folder for one application tab."""
    safe_tab = safe_output_part(tab.lower(), "video-clone")
    folder = Path.home() / "Downloads" / safe_tab
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
