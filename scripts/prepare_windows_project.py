#!/usr/bin/env python3
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "windows_project" / "PaperMonitorWindows"
README_WINDOWS = r"""# Paper Monitor Windows

This folder is the copyable Windows project for Paper Monitor.

## What It Contains

- `paper_monitor/`: the existing literature search, filtering, storage, dashboard, and Windows tray code.
- `windows/PaperMonitor.pyw`: quiet Windows tray entrypoint.
- `windows/assets/PaperMonitor.ico`: Windows tray/app icon.
- `scripts/build_windows_app.ps1`: builds a no-console `.exe` with PyInstaller.
- `scripts/install_windows_app.ps1`: installs the app for the current Windows user and enables startup.
- `requirements-windows.txt`: Windows packaging/runtime dependencies.
- `config.example.json` and `journal_metrics.json`: default runtime data.

## Build On Windows

Open PowerShell inside this folder:

```powershell
python -m pip install -r requirements-windows.txt
.\scripts\build_windows_app.ps1
```

The built executable will be created under:

```powershell
.\dist\windows\PaperMonitor.exe
```

## Install On Windows

```powershell
.\scripts\install_windows_app.ps1
```

The installer copies the app to:

```powershell
$env:LOCALAPPDATA\Programs\PaperMonitor\PaperMonitor.exe
```

Runtime files are stored under:

```powershell
$env:APPDATA\PaperMonitor
```

The app starts silently at login and runs in the Windows system tray. Windows may place it inside the hidden tray overflow. Right-click the tray icon to open the dashboard, refresh now, or quit.

## Disable Startup

```powershell
& "$env:LOCALAPPDATA\Programs\PaperMonitor\PaperMonitor.exe" uninstall-startup
```
"""


def prepare_windows_project(target: Path = DEFAULT_TARGET) -> Path:
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    _copy_file("requirements-windows.txt", target)
    _copy_file("config.example.json", target)
    _copy_file("journal_metrics.json", target)
    _copy_file("README.md", target)
    (target / "README_WINDOWS.md").write_text(README_WINDOWS, encoding="utf-8")

    _copy_tree(ROOT / "paper_monitor", target / "paper_monitor")
    _copy_tree(ROOT / "windows", target / "windows")

    scripts_target = target / "scripts"
    scripts_target.mkdir()
    for name in (
        "build_windows_app.ps1",
        "install_windows_app.ps1",
        "generate_windows_icon.py",
        "generate_app_icons.py",
    ):
        shutil.copy2(ROOT / "scripts" / name, scripts_target / name)

    return target


def _copy_file(relative_path: str, target: Path) -> None:
    shutil.copy2(ROOT / relative_path, target / Path(relative_path).name)


def _copy_tree(source: Path, target: Path) -> None:
    def ignore(_directory, names):
        return {
            name
            for name in names
            if name == "__pycache__"
            or name == ".DS_Store"
            or name.endswith(".pyc")
        }

    shutil.copytree(source, target, ignore=ignore)


def main() -> int:
    target = prepare_windows_project()
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
