"""Launch the tiny native Windows tray without making Python resident."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .config import load_app_config
from .windows_mutex import TRAY_MUTEX_NAME, is_mutex_running

NATIVE_TRAY_FILENAME = "PaperMonitorTray.exe"
LOGGER = logging.getLogger(__name__)


def ensure_native_tray(
    config_path: Path,
    executable_path: Optional[Path] = None,
) -> bool:
    """Start one native tray instance when the configured Windows UI wants it."""

    if os.name != "nt" or is_mutex_running(TRAY_MUTEX_NAME):
        return False

    resolved_config = Path(config_path).expanduser().resolve()
    try:
        tray_visible = load_app_config(resolved_config).app_settings.show_tray_icon
    except (OSError, ValueError) as exc:
        LOGGER.warning("Could not read the native tray setting: %s", exc)
        return False
    if not tray_visible:
        return False

    if executable_path is None and not bool(getattr(sys, "frozen", False)):
        return False
    app_executable = Path(executable_path or sys.executable).expanduser().resolve()
    if not app_executable.is_file():
        return False
    tray_source = _native_tray_source(app_executable)
    if tray_source is None:
        LOGGER.warning("Native Paper Monitor tray executable is not available.")
        return False
    try:
        tray_executable = _stable_tray_executable(tray_source, resolved_config)
    except OSError as exc:
        LOGGER.warning("Could not prepare the native Paper Monitor tray: %s", exc)
        return False
    command = [
        str(tray_executable),
        "--app",
        str(app_executable),
        "--config",
        str(resolved_config),
    ]
    creation_flags = 0
    for flag in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creation_flags |= int(getattr(subprocess, flag, 0))
    environment = os.environ.copy()
    if bool(getattr(sys, "frozen", False)):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        subprocess.Popen(  # nosec B603
            command,
            cwd=str(app_executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        LOGGER.warning("Could not start the native Paper Monitor tray: %s", exc)
        return False
    return True


def _native_tray_source(app_executable: Path) -> Optional[Path]:
    candidates = [app_executable.parent / NATIVE_TRAY_FILENAME]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / NATIVE_TRAY_FILENAME)
    candidates.append(Path(__file__).resolve().parents[1] / "dist" / "windows" / NATIVE_TRAY_FILENAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _stable_tray_executable(source: Path, config_path: Path) -> Path:
    if source.parent == config_path.parent or source.parent == Path(sys.executable).resolve().parent:
        return source
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    native_dir = config_path.parent / "native"
    target = native_dir / f"PaperMonitorTray-{source_digest[:16]}.exe"
    if target.is_file():
        try:
            if hashlib.sha256(target.read_bytes()).hexdigest() == source_digest:
                return target
        except OSError:
            pass

    native_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(native_dir),
        prefix=".PaperMonitorTray-",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        try:
            os.replace(temporary, target)
        except OSError:
            if (
                not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != source_digest
            ):
                raise
        _remove_stale_tray_versions(native_dir, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def _remove_stale_tray_versions(directory: Path, current: Path) -> None:
    for candidate in directory.glob("PaperMonitorTray-*.exe"):
        if candidate == current:
            continue
        try:
            candidate.unlink()
        except OSError:
            continue
