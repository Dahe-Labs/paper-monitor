"""Per-user Windows Task Scheduler integration for non-resident refreshes.

The task runs with the signed-in user's interactive token so desktop
notifications keep working without a permanently resident tray process.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET  # nosec B405
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any

# Exported task XML is size-bounded and rejects DTD/entity declarations before parsing.

TASK_XML_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
LEGACY_TASK_NAME = r"\PaperMonitor Scheduled Refresh"
DEFAULT_TASK_NAME = LEGACY_TASK_NAME
TASK_NAME_PREFIX = r"\PaperMonitor\Scheduled Refresh - "
DEFAULT_EXECUTION_TIME_LIMIT = "PT2H"
DEFAULT_RESTART_INTERVAL = "PT15M"
DEFAULT_RESTART_COUNT = 2
TASK_DEFINITION_REVISION = 2
FINGERPRINT_PREFIX = "PaperMonitor schedule fingerprint: "
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 24 * 30
MAX_EXPORTED_TASK_XML_BYTES = 1024 * 1024
_FILE_NOT_FOUND_HRESULTS = {2, 3, 0x80070002, 0x80070003}

Runner = Callable[..., subprocess.CompletedProcess[str]]


def build_scheduled_refresh_command(
    config_path: Path,
    *,
    executable: Path | str | None = None,
    frozen: bool | None = None,
) -> list[str]:
    """Return a one-shot refresh command for source or frozen execution."""

    executable_path = _absolute_path(executable or sys.executable, "executable")
    config = _absolute_path(config_path, "config path")
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        return [executable_path, "scheduled-refresh", "--config", config]
    return [
        executable_path,
        "-m",
        "paper_monitor.windows_tray",
        "scheduled-refresh",
        "--config",
        config,
    ]


def current_windows_user(env: Mapping[str, str] | None = None) -> str:
    """Return the current account in a Task Scheduler-compatible form."""

    values = os.environ if env is None else env
    username = str(values.get("USERNAME") or getpass.getuser()).strip()
    domain = str(values.get("USERDOMAIN") or "").strip()
    _validate_text(username, "user name")
    _validate_text(domain, "user domain", allow_empty=True)
    if "\\" in username or "@" in username or not domain:
        return username
    return f"{domain}\\{username}"


def default_task_name(user_name: str | None = None) -> str:
    """Return a stable, account-specific task name without exposing the account name."""

    principal = str(user_name or current_windows_user()).strip()
    _validate_text(principal, "user name")
    account_key = hashlib.sha256(principal.casefold().encode("utf-8")).hexdigest()[:16]
    return TASK_NAME_PREFIX + account_key


def next_start_boundary(
    interval_hours: int,
    start_time: str = "",
    *,
    now: dt.datetime | None = None,
) -> dt.datetime:
    """Calculate the first future boundary while preserving a configured anchor."""

    interval = _validated_interval(interval_hours)
    current = (now or dt.datetime.now().astimezone()).replace(microsecond=0)
    start_text = str(start_time or "").strip()
    if not start_text:
        return current + dt.timedelta(hours=interval)

    hour, minute = _parse_start_time(start_text)
    anchor = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if anchor >= current:
        return anchor
    interval_delta = dt.timedelta(hours=interval)
    elapsed_intervals = int((current - anchor) // interval_delta) + 1
    return anchor + (interval_delta * elapsed_intervals)


def build_scheduled_task_xml(
    command: Sequence[str],
    *,
    interval_hours: int,
    start_time: str = "",
    user_name: str | None = None,
    now: dt.datetime | None = None,
    working_directory: Path | str | None = None,
    fingerprint: str | None = None,
) -> bytes:
    """Build a Task Scheduler 2.0 XML definition for a repeating refresh."""

    command_parts = [_validated_command_part(part) for part in command]
    if not command_parts:
        raise ValueError("scheduled task command must not be empty")
    interval = _validated_interval(interval_hours)
    principal = str(user_name or current_windows_user()).strip()
    _validate_text(principal, "user name")
    boundary = next_start_boundary(interval, start_time, now=now)
    work_dir = _absolute_path(
        working_directory or Path(command_parts[0]).parent,
        "working directory",
    )
    schedule_fingerprint = fingerprint or scheduled_refresh_fingerprint(
        command_parts,
        interval_hours=interval,
        start_time=start_time,
        user_name=principal,
        working_directory=work_dir,
    )
    _validate_fingerprint(schedule_fingerprint)

    ET.register_namespace("", TASK_XML_NAMESPACE)
    task = ET.Element(_tag("Task"), {"version": "1.3"})

    registration = ET.SubElement(task, _tag("RegistrationInfo"))
    ET.SubElement(registration, _tag("Author")).text = principal
    ET.SubElement(registration, _tag("Description")).text = (
        "Checks configured paper sources and sends notifications, then exits.\n"
        f"{FINGERPRINT_PREFIX}{schedule_fingerprint}"
    )

    triggers = ET.SubElement(task, _tag("Triggers"))
    trigger = ET.SubElement(triggers, _tag("TimeTrigger"))
    ET.SubElement(trigger, _tag("StartBoundary")).text = boundary.isoformat(timespec="seconds")
    repetition = ET.SubElement(trigger, _tag("Repetition"))
    ET.SubElement(repetition, _tag("Interval")).text = _interval_duration(interval)
    ET.SubElement(repetition, _tag("StopAtDurationEnd")).text = "false"
    ET.SubElement(trigger, _tag("Enabled")).text = "true"

    principals = ET.SubElement(task, _tag("Principals"))
    task_principal = ET.SubElement(principals, _tag("Principal"), {"id": "CurrentUser"})
    ET.SubElement(task_principal, _tag("UserId")).text = principal
    ET.SubElement(task_principal, _tag("LogonType")).text = "InteractiveToken"
    ET.SubElement(task_principal, _tag("RunLevel")).text = "LeastPrivilege"

    settings = ET.SubElement(task, _tag("Settings"))
    ET.SubElement(settings, _tag("MultipleInstancesPolicy")).text = "IgnoreNew"
    ET.SubElement(settings, _tag("DisallowStartIfOnBatteries")).text = "false"
    ET.SubElement(settings, _tag("StopIfGoingOnBatteries")).text = "false"
    ET.SubElement(settings, _tag("StartWhenAvailable")).text = "true"
    ET.SubElement(settings, _tag("RunOnlyIfNetworkAvailable")).text = "true"
    ET.SubElement(settings, _tag("AllowStartOnDemand")).text = "true"
    ET.SubElement(settings, _tag("Enabled")).text = "true"
    ET.SubElement(settings, _tag("WakeToRun")).text = "false"
    ET.SubElement(settings, _tag("ExecutionTimeLimit")).text = DEFAULT_EXECUTION_TIME_LIMIT
    restart = ET.SubElement(settings, _tag("RestartOnFailure"))
    ET.SubElement(restart, _tag("Interval")).text = DEFAULT_RESTART_INTERVAL
    ET.SubElement(restart, _tag("Count")).text = str(DEFAULT_RESTART_COUNT)

    actions = ET.SubElement(task, _tag("Actions"), {"Context": "CurrentUser"})
    execute = ET.SubElement(actions, _tag("Exec"))
    ET.SubElement(execute, _tag("Command")).text = command_parts[0]
    if len(command_parts) > 1:
        ET.SubElement(execute, _tag("Arguments")).text = subprocess.list2cmdline(command_parts[1:])
    ET.SubElement(execute, _tag("WorkingDirectory")).text = work_dir

    # Task Scheduler's XML-file importer expects its native UTF-16 task
    # encoding.  UTF-8 is valid XML in general, but schtasks.exe rejects it
    # with SCHED_E_MALFORMEDXML ("cannot switch encoding") on Windows.
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def scheduled_refresh_fingerprint(
    command: Sequence[str],
    *,
    interval_hours: int,
    start_time: str = "",
    user_name: str | None = None,
    working_directory: Path | str | None = None,
) -> str:
    """Hash only stable task inputs, never the moving first-run boundary."""

    command_parts = [_validated_command_part(part) for part in command]
    if not command_parts:
        raise ValueError("scheduled task command must not be empty")
    interval = _validated_interval(interval_hours)
    normalized_start_time = str(start_time or "").strip()
    if normalized_start_time:
        hour, minute = _parse_start_time(normalized_start_time)
        normalized_start_time = f"{hour:02d}:{minute:02d}"
    principal = str(user_name or current_windows_user()).strip()
    _validate_text(principal, "user name")
    work_dir = _absolute_path(
        working_directory or Path(command_parts[0]).parent,
        "working directory",
    )
    payload = {
        "revision": TASK_DEFINITION_REVISION,
        "command": command_parts,
        "interval_hours": interval,
        "start_time": normalized_start_time,
        "user_name": principal,
        "working_directory": work_dir,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def scheduled_task_xml_matches(
    xml_payload: str | bytes,
    fingerprint: str,
    *,
    command: Sequence[str] | None = None,
    interval_hours: int | None = None,
    working_directory: Path | str | None = None,
) -> bool:
    """Return whether exported task XML has the requested hash and semantics."""

    _validate_fingerprint(fingerprint)
    if isinstance(xml_payload, bytes):
        if len(xml_payload) > MAX_EXPORTED_TASK_XML_BYTES:
            return False
        try:
            if xml_payload.startswith((b"\xff\xfe", b"\xfe\xff")):
                encoding = "utf-16"
            else:
                encoding = "utf-8-sig"
            payload_text = xml_payload.decode(encoding)
        except UnicodeDecodeError:
            return False
    elif isinstance(xml_payload, str):
        payload_text = xml_payload
    else:
        return False
    if len(payload_text.encode("utf-8", errors="ignore")) > MAX_EXPORTED_TASK_XML_BYTES:
        return False
    marker = f"{FINGERPRINT_PREFIX}{fingerprint}"
    if marker not in payload_text:
        return False
    if command is None:
        return True
    if interval_hours is None or working_directory is None:
        raise ValueError("semantic task matching requires interval_hours and working_directory")
    if "<!doctype" in payload_text.casefold() or "<!entity" in payload_text.casefold():
        return False
    try:
        # Input is bounded and DTD/entity declarations were rejected above.
        root = ET.fromstring(payload_text)  # nosec B314
    except ET.ParseError:
        return False

    command_parts = [_validated_command_part(part) for part in command]
    if not command_parts:
        raise ValueError("scheduled task command must not be empty")
    expected_arguments = (
        subprocess.list2cmdline(command_parts[1:]) if len(command_parts) > 1 else ""
    )
    expected_values = {
        "./t:Triggers/t:TimeTrigger/t:Repetition/t:Interval": _interval_duration(
            _validated_interval(interval_hours)
        ),
        "./t:Triggers/t:TimeTrigger/t:Enabled": "true",
        "./t:Principals/t:Principal/t:LogonType": "InteractiveToken",
        "./t:Principals/t:Principal/t:RunLevel": "LeastPrivilege",
        "./t:Settings/t:MultipleInstancesPolicy": "IgnoreNew",
        "./t:Settings/t:StartWhenAvailable": "true",
        "./t:Settings/t:RunOnlyIfNetworkAvailable": "true",
        "./t:Settings/t:AllowStartOnDemand": "true",
        "./t:Settings/t:Enabled": "true",
        "./t:Settings/t:WakeToRun": "false",
        "./t:Settings/t:ExecutionTimeLimit": DEFAULT_EXECUTION_TIME_LIMIT,
        "./t:Settings/t:RestartOnFailure/t:Interval": DEFAULT_RESTART_INTERVAL,
        "./t:Settings/t:RestartOnFailure/t:Count": str(DEFAULT_RESTART_COUNT),
        "./t:Actions/t:Exec/t:Arguments": expected_arguments,
    }
    namespaces = {"t": TASK_XML_NAMESPACE}
    for path, expected in expected_values.items():
        node = root.find(path, namespaces)
        actual = "" if node is None or node.text is None else node.text.strip()
        if actual != expected:
            return False

    command_node = root.find("./t:Actions/t:Exec/t:Command", namespaces)
    working_directory_node = root.find("./t:Actions/t:Exec/t:WorkingDirectory", namespaces)
    actual_command = "" if command_node is None or command_node.text is None else command_node.text
    actual_working_directory = (
        ""
        if working_directory_node is None or working_directory_node.text is None
        else working_directory_node.text
    )
    return _windows_path_equal(actual_command, command_parts[0]) and _windows_path_equal(
        actual_working_directory,
        _absolute_path(working_directory, "working directory"),
    )


def build_schtasks_create_args(
    xml_path: Path | str,
    *,
    task_name: str | None = None,
    schtasks_executable: Path | str | None = None,
) -> list[str]:
    """Build an injection-safe argument vector for task creation/update."""

    executable = str(schtasks_executable or default_schtasks_executable())
    _validate_text(executable, "schtasks executable")
    name = _validated_task_name(task_name or default_task_name())
    xml_file = _absolute_path(xml_path, "task XML path")
    return [executable, "/Create", "/TN", name, "/XML", xml_file, "/F", "/HResult"]


def build_schtasks_delete_args(
    *,
    task_name: str | None = None,
    schtasks_executable: Path | str | None = None,
) -> list[str]:
    """Build an injection-safe argument vector for task deletion."""

    executable = str(schtasks_executable or default_schtasks_executable())
    _validate_text(executable, "schtasks executable")
    return [
        executable,
        "/Delete",
        "/TN",
        _validated_task_name(task_name or default_task_name()),
        "/F",
        "/HResult",
    ]


def build_schtasks_query_args(
    *,
    task_name: str | None = None,
    schtasks_executable: Path | str | None = None,
) -> list[str]:
    """Build an argument vector that exports one existing task as XML."""

    executable = str(schtasks_executable or default_schtasks_executable())
    _validate_text(executable, "schtasks executable")
    return [
        executable,
        "/Query",
        "/TN",
        _validated_task_name(task_name or default_task_name()),
        "/XML",
        "/HResult",
    ]


def install_or_update_scheduled_refresh(
    config_path: Path,
    interval_hours: int,
    start_time: str = "",
    *,
    task_name: str | None = None,
    executable: Path | str | None = None,
    frozen: bool | None = None,
    user_name: str | None = None,
    now: dt.datetime | None = None,
    working_directory: Path | str | None = None,
    runner: Runner | None = None,
    schtasks_executable: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Create/update the task only when its stable definition has changed."""

    command = build_scheduled_refresh_command(config_path, executable=executable, frozen=frozen)
    if working_directory is None:
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        working_directory = Path(command[0]).parent if is_frozen else Path(__file__).resolve().parents[1]
    principal = str(user_name or current_windows_user()).strip()
    resolved_task_name = task_name or default_task_name(principal)
    fingerprint = scheduled_refresh_fingerprint(
        command,
        interval_hours=interval_hours,
        start_time=start_time,
        user_name=principal,
        working_directory=working_directory,
    )
    query_args = build_schtasks_query_args(
        task_name=resolved_task_name,
        schtasks_executable=schtasks_executable,
    )
    existing = _run_schtasks(query_args, runner=runner, check=False)
    if existing.returncode == 0:
        if scheduled_task_xml_matches(
            existing.stdout or "",
            fingerprint,
            command=command,
            interval_hours=interval_hours,
            working_directory=working_directory,
        ):
            return existing
    elif not _is_task_not_found(existing):
        raise subprocess.CalledProcessError(
            existing.returncode,
            query_args,
            output=existing.stdout,
            stderr=existing.stderr,
        )

    xml_payload = build_scheduled_task_xml(
        command,
        interval_hours=interval_hours,
        start_time=start_time,
        user_name=principal,
        now=now,
        working_directory=working_directory,
        fingerprint=fingerprint,
    )

    descriptor, temporary_name = tempfile.mkstemp(prefix="PaperMonitor-task-", suffix=".xml")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(xml_payload)
            stream.flush()
        args = build_schtasks_create_args(
            temporary_path,
            task_name=resolved_task_name,
            schtasks_executable=schtasks_executable,
        )
        return _run_schtasks(args, runner=runner, check=True)
    finally:
        temporary_path.unlink(missing_ok=True)


def remove_scheduled_refresh(
    *,
    task_name: str | None = None,
    runner: Runner | None = None,
    schtasks_executable: Path | str | None = None,
    missing_ok: bool = True,
) -> bool:
    """Delete the scheduled refresh, returning False when it was already absent."""

    args = build_schtasks_delete_args(task_name=task_name, schtasks_executable=schtasks_executable)
    completed = _run_schtasks(args, runner=runner, check=False)
    if completed.returncode == 0:
        return True
    if missing_ok and _is_task_not_found(completed):
        return False
    raise subprocess.CalledProcessError(
        completed.returncode,
        args,
        output=completed.stdout,
        stderr=completed.stderr,
    )


def sync_scheduled_refresh(
    config_path: Path,
    enabled: bool,
    interval_hours: int,
    start_time: str = "",
    *,
    task_name: str | None = None,
    executable: Path | str | None = None,
    frozen: bool | None = None,
    user_name: str | None = None,
    now: dt.datetime | None = None,
    working_directory: Path | str | None = None,
    runner: Runner | None = None,
    schtasks_executable: Path | str | None = None,
) -> bool:
    """Create/update the task when enabled, or remove it when disabled."""

    if not enabled:
        remove_scheduled_refresh(
            task_name=task_name,
            runner=runner,
            schtasks_executable=schtasks_executable,
            missing_ok=True,
        )
        resolved_name = task_name or default_task_name(user_name)
        if resolved_name != LEGACY_TASK_NAME:
            remove_scheduled_refresh(
                task_name=LEGACY_TASK_NAME,
                runner=runner,
                schtasks_executable=schtasks_executable,
                missing_ok=True,
            )
        return True
    install_or_update_scheduled_refresh(
        config_path,
        interval_hours,
        start_time,
        task_name=task_name,
        executable=executable,
        frozen=frozen,
        user_name=user_name,
        now=now,
        working_directory=working_directory,
        runner=runner,
        schtasks_executable=schtasks_executable,
    )
    resolved_name = task_name or default_task_name(user_name)
    if resolved_name != LEGACY_TASK_NAME:
        remove_scheduled_refresh(
            task_name=LEGACY_TASK_NAME,
            runner=runner,
            schtasks_executable=schtasks_executable,
            missing_ok=True,
        )
    return True


def default_schtasks_executable(env: Mapping[str, str] | None = None) -> str:
    """Resolve the system copy instead of trusting the process search path."""

    values = os.environ if env is None else env
    system_root = str(values.get("SystemRoot") or values.get("WINDIR") or r"C:\Windows")
    _validate_text(system_root, "Windows system root")
    return str(PureWindowsPath(system_root) / "System32" / "schtasks.exe")


def _run_schtasks(
    args: Sequence[str],
    *,
    runner: Runner | None,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    run = runner or subprocess.run
    kwargs: dict[str, Any] = {
        "check": check,
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "stdin": subprocess.DEVNULL,
        "timeout": 30,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return run(list(args), **kwargs)


def _tag(name: str) -> str:
    return f"{{{TASK_XML_NAMESPACE}}}{name}"


def _interval_duration(interval_hours: int) -> str:
    days, hours = divmod(interval_hours, 24)
    if days and hours:
        return f"P{days}DT{hours}H"
    if days:
        return f"P{days}D"
    return f"PT{hours}H"


def _validated_interval(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("interval_hours must be an integer")
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("interval_hours must be an integer") from exc
    if interval != value or interval < MIN_INTERVAL_HOURS or interval > MAX_INTERVAL_HOURS:
        raise ValueError(
            f"interval_hours must be between {MIN_INTERVAL_HOURS} and {MAX_INTERVAL_HOURS}"
        )
    return interval


def _parse_start_time(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError("start_time must use HH:MM in 24-hour time")
    try:
        hour, minute = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError("start_time must use HH:MM in 24-hour time") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("start_time must use HH:MM in 24-hour time")
    return hour, minute


def _absolute_path(value: Path | str, label: str) -> str:
    text = str(value)
    _validate_text(text, label)
    return str(Path(text).expanduser().resolve(strict=False))


def _windows_path_equal(left: str, right: str) -> bool:
    """Compare task paths using Windows' case-insensitive path semantics."""

    return str(PureWindowsPath(left)).casefold() == str(PureWindowsPath(right)).casefold()


def _validated_command_part(value: object) -> str:
    text = str(value)
    _validate_text(text, "command argument")
    return text


def _validated_task_name(value: str) -> str:
    name = str(value)
    _validate_text(name, "task name")
    if name != name.strip() or len(name) > 238:
        raise ValueError("task name must not have surrounding spaces and must be at most 238 characters")
    path_parts = [part for part in name.split("\\") if part]
    if any(part in {".", ".."} for part in path_parts):
        raise ValueError("task name must not contain relative path segments")
    return name


def _validate_text(value: str, label: str, *, allow_empty: bool = False) -> None:
    if not value and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains an unsupported control character")


def _validate_fingerprint(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("schedule fingerprint must be a lowercase SHA-256 hexadecimal digest")


def _is_task_not_found(completed: subprocess.CompletedProcess[str]) -> bool:
    normalized_code = int(completed.returncode) & 0xFFFFFFFF
    if normalized_code in _FILE_NOT_FOUND_HRESULTS:
        return True
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}".casefold()
    return "cannot find" in output or "does not exist" in output
