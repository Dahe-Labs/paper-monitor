"""Resolve the one Paper Monitor icon used by Windows UI surfaces."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def default_windows_icon_path() -> Optional[Path]:
    frozen_root = getattr(sys, "_MEIPASS", None)
    candidates = (
        Path(frozen_root) / "windows" / "assets" / "PaperMonitor.ico"
        if frozen_root
        else None,
        Path(sys.executable).resolve().parent / "PaperMonitor.ico",
        Path(__file__).resolve().parents[1] / "windows" / "assets" / "PaperMonitor.ico",
    )
    return next((path for path in candidates if path is not None and path.is_file()), None)
