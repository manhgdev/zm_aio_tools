"""Stable user-visible output folders, grouped by application tab."""
from __future__ import annotations

from pathlib import Path


def downloads_folder(tab: str) -> Path:
    """Return and create the default output folder for one application tab."""
    safe_tab = "".join(char for char in tab.lower() if char.isalnum() or char in "-_") or "video-clone"
    folder = Path.home() / "Downloads" / safe_tab
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def selected_or_default(tab: str, selected: str = "") -> Path:
    """Honor an explicit desktop choice; otherwise use the shared Downloads tree."""
    folder = Path(selected).expanduser() if selected.strip() else downloads_folder(tab)
    folder.mkdir(parents=True, exist_ok=True)
    return folder
