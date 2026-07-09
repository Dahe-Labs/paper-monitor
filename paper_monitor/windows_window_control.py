"""Local control channel between the Windows tray and window processes."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib import error, request

CONTROL_FILE_NAME = "window-control.json"
CONTROL_TIMEOUT_SECONDS = 1.5


class WindowControlError(RuntimeError):
    """Raised when the running dashboard window cannot receive a control command."""


@dataclass(frozen=True)
class WindowControlState:
    base_url: str
    token: str
    pid: int


def window_control_path(config_path: Path) -> Path:
    return Path(config_path).expanduser().resolve().parent / CONTROL_FILE_NAME


def write_window_control(config_path: Path, base_url: str, token: str, pid: Optional[int] = None) -> Path:
    path = window_control_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": str(base_url).rstrip("/"),
        "token": str(token),
        "pid": int(pid if pid is not None else os.getpid()),
    }
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return path


def clear_window_control(config_path: Path) -> None:
    try:
        window_control_path(config_path).unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def read_window_control(config_path: Path) -> Optional[WindowControlState]:
    path = window_control_path(config_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    base_url = str(payload.get("base_url") or "").rstrip("/")
    token = str(payload.get("token") or "")
    if not _is_loopback_url(base_url) or not token:
        return None
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return WindowControlState(base_url=base_url, token=token, pid=pid)


def send_window_control(
    config_path: Path,
    action: str,
    route: Optional[str] = None,
    timeout: float = CONTROL_TIMEOUT_SECONDS,
) -> Dict[str, object]:
    state = read_window_control(config_path)
    if state is None:
        raise WindowControlError("No running Paper Monitor window control endpoint was found.")

    payload: Dict[str, object] = {"action": str(action)}
    if route is not None:
        payload["route"] = str(route)

    api_request = request.Request(
        state.base_url + "/api/window-control",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Paper-Monitor-Token": state.token,
        },
        method="POST",
    )
    try:
        # read_window_control accepts only a loopback HTTP endpoint with a session token.
        with request.urlopen(api_request, timeout=timeout) as response:  # nosec B310
            body = response.read()
            if response.status < 200 or response.status >= 300:
                raise WindowControlError(f"Window control returned HTTP {response.status}.")
    except (OSError, error.URLError) as exc:
        raise WindowControlError(str(exc)) from exc

    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WindowControlError("Window control returned an invalid response.") from exc
    if not isinstance(decoded, dict):
        raise WindowControlError("Window control returned an invalid response.")
    if decoded.get("ok") is False:
        raise WindowControlError(str(decoded.get("error") or "Window control failed."))
    return decoded


def send_window_control_with_retry(
    config_path: Path,
    action: str,
    route: Optional[str] = None,
    timeout: float = CONTROL_TIMEOUT_SECONDS,
    ready_timeout: float = 5.0,
    retry_interval: float = 0.1,
) -> Dict[str, object]:
    deadline = time.monotonic() + max(0.0, float(ready_timeout))
    while True:
        try:
            return send_window_control(config_path, action, route=route, timeout=timeout)
        except WindowControlError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(max(0.01, float(retry_interval)))


def _is_loopback_url(value: str) -> bool:
    return value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")
