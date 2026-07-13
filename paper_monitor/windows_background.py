"""Short-lived Windows Task Scheduler entry for one Background Refresh Run."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from .app_identity import WINDOWS_APP_USER_MODEL_ID
from .article_lifecycle import RefreshRunStatus
from .refresh_execution import RefreshExecution, RefreshIntent

_RETRYABLE_NOTIFICATION_STATES = {"deferred", "rejected"}
ExecutionFactory = Callable[[Path], RefreshExecution]


def run_background_refresh(
    config_path: Path,
    *,
    execution_factory: ExecutionFactory = RefreshExecution,
) -> int:
    """Execute one Background Refresh Run and return a Task Scheduler exit code."""

    config = Path(config_path)
    try:
        outcome = execution_factory(config).execute(RefreshIntent.BACKGROUND)
        status = RefreshRunStatus(outcome.status)
        if status is RefreshRunStatus.FAILED:
            raise RuntimeError(outcome.error or "Every configured article source failed.")
        notification = outcome.notification
        if notification is not None and notification.state in _RETRYABLE_NOTIFICATION_STATES:
            raise RuntimeError(
                notification.error
                or f"Windows notification delivery was {notification.state}."
            )
        return 0
    except Exception as exc:
        _log_background_error(config, exc)
        _write_stderr(f"Paper Monitor background refresh failed: {exc}")
        return 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="PaperMonitor scheduled-refresh")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    _set_windows_app_identity()
    return run_background_refresh(args.config)


def _write_stderr(message: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        print(message, file=stream)
    except Exception:
        return


def _set_windows_app_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return


def _log_background_error(config_path: Path, error: BaseException) -> None:
    try:
        log_path = Path(config_path).expanduser().resolve().parent / "PaperMonitor.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(
                f"{timestamp} Paper Monitor background refresh failed: "
                f"{type(error).__name__}: {error}\n"
            )
    except Exception:
        return


if __name__ == "__main__":
    raise SystemExit(main())
