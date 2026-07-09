import plistlib
from pathlib import Path


def build_launch_agent_plist(
    label: str,
    python_path: Path,
    module_name: str,
    working_directory: Path,
    config_path: Path,
    interval_seconds: int,
) -> bytes:
    working_directory_text = _posix_path(working_directory)
    config_path_text = _posix_path(config_path)
    python_path_text = _posix_path(python_path)
    log_directory = working_directory_text + "/work/paper-monitor/logs"
    launch_code = (
        "import sys; "
        "sys.path.insert(0, %r); "
        "from paper_monitor.cli import main; "
        "raise SystemExit(main())"
    ) % working_directory_text
    payload = {
        "Label": label,
        "ProgramArguments": [
            python_path_text,
            "-c",
            launch_code,
            "run",
            "--config",
            config_path_text,
        ],
        "WorkingDirectory": working_directory_text,
        "EnvironmentVariables": {
            "PYTHONPATH": working_directory_text,
        },
        "StartInterval": int(interval_seconds),
        "RunAtLoad": True,
        "StandardOutPath": log_directory + "/paper-monitor.out.log",
        "StandardErrorPath": log_directory + "/paper-monitor.err.log",
    }
    return plistlib.dumps(payload, sort_keys=False)


def _posix_path(path: Path) -> str:
    return str(path).replace("\\", "/")
