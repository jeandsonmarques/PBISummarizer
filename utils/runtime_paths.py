from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


APP_NAME = "PowerBISummarizer"


def _candidate_state_roots() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata))
        else:
            candidates.append(home / "AppData" / "Local")
    elif sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support")
    else:
        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_state_home:
            candidates.append(Path(xdg_state_home))
        if xdg_data_home:
            candidates.append(Path(xdg_data_home))
        candidates.append(home / ".local" / "state")
        candidates.append(home / ".local" / "share")

    candidates.append(Path(tempfile.gettempdir()))
    return candidates


def runtime_state_dir(app_name: str = APP_NAME) -> Path:
    for root in _candidate_state_roots():
        target = root / app_name
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            continue

    fallback = Path(tempfile.gettempdir()) / app_name
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def runtime_state_file(filename: str, app_name: str = APP_NAME) -> Path:
    return runtime_state_dir(app_name) / filename


__all__ = ["APP_NAME", "runtime_state_dir", "runtime_state_file"]
