"""Atomic cross-process refresh status shared by the Windows app processes."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, Mapping, Optional

REFRESH_STATUS_FILE_NAME = "refresh-status.json"
REFRESH_STATUS_SCHEMA_VERSION = 1
REFRESH_STATES = frozenset({"running", "succeeded", "failed", "partial"})

_STATUS_WRITE_LOCK = threading.RLock()


def refresh_status_path(config_path: Path) -> Path:
    """Return the status file colocated with the application configuration."""

    return Path(config_path).expanduser().resolve().parent / REFRESH_STATUS_FILE_NAME


def new_refresh_request_id() -> str:
    return uuid.uuid4().hex


def new_refresh_owner_id(request_id: str) -> str:
    return f"{os.getpid()}:{request_id}:{uuid.uuid4().hex}"


def read_refresh_status(config_path: Path) -> Optional[Dict[str, object]]:
    """Read a complete status snapshot, returning ``None`` for missing/corrupt data."""

    path = refresh_status_path(config_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    status = str(payload.get("status") or "")
    request_id = str(payload.get("request_id") or "")
    if status not in REFRESH_STATES or not request_id:
        return None
    return payload


def begin_refresh(
    config_path: Path,
    *,
    request_id: str,
    reason: str,
    owner_id: str,
) -> Dict[str, object]:
    """Publish a running state after the caller has acquired the refresh mutex."""

    now = _utc_timestamp()
    payload: Dict[str, object] = {
        "schema_version": REFRESH_STATUS_SCHEMA_VERSION,
        "request_id": str(request_id),
        "reason": str(reason or "app_refresh"),
        "ok": True,
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "finished_at": "",
        "result": None,
        "error": "",
        "owner_id": str(owner_id),
        "owner_pid": os.getpid(),
    }
    _write_status_atomic(config_path, payload)
    return dict(payload)


def finish_refresh(
    config_path: Path,
    *,
    request_id: str,
    owner_id: str,
    status: str,
    result: Optional[Mapping[str, object]] = None,
    error: str = "",
) -> bool:
    """Publish a terminal state if the caller still owns the current request."""

    terminal_status = str(status)
    if terminal_status not in {"succeeded", "failed", "partial"}:
        raise ValueError(f"Invalid terminal refresh status: {terminal_status}")

    with _STATUS_WRITE_LOCK:
        current = read_refresh_status(config_path)
        if not _owned_by(current, request_id=request_id, owner_id=owner_id):
            return False
        now = _utc_timestamp()
        payload = dict(current)
        payload.update(
            ok=terminal_status != "failed",
            status=terminal_status,
            updated_at=now,
            finished_at=now,
            result=_json_safe(result) if result is not None else None,
            error=str(error or ""),
        )
        _write_status_atomic(config_path, payload)
    return True


def _owned_by(
    state: Optional[Mapping[str, object]],
    *,
    request_id: str,
    owner_id: str,
) -> bool:
    return bool(
        state
        and state.get("status") == "running"
        and str(state.get("request_id") or "") == str(request_id)
        and str(state.get("owner_id") or "") == str(owner_id)
    )


def _write_status_atomic(config_path: Path, payload: Mapping[str, object]) -> Path:
    path = refresh_status_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(_json_safe(payload), ensure_ascii=False, separators=(",", ":"))
    with _STATUS_WRITE_LOCK:
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temp_path), str(path))
        finally:
            try:
                temp_path.unlink()
            except (FileNotFoundError, OSError):
                pass
    return path


def _json_safe(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
