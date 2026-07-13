#!/usr/bin/env python3
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "windows_project" / "PaperMonitorWindows"

PROJECT_FILES = (
    "LICENSE",
    "README.md",
    "README_WINDOWS.md",
    "config.example.json",
    "journal_metrics.json",
    "requirements-windows.txt",
    "requirements-windows.lock.txt",
)

SCRIPT_FILES = (
    "build_windows_app.ps1",
    "generate_app_icons.py",
    "generate_windows_icon.py",
    "generate_windows_version_info.py",
    "install_windows_app.ps1",
    "package_windows_release.ps1",
)


def prepare_windows_project(target: Path = DEFAULT_TARGET) -> Path:
    target = Path(target).resolve()
    root = ROOT.resolve()
    if target == root or target in root.parents:
        raise ValueError("Windows project target must not be the repository or one of its parents")

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for relative_path in PROJECT_FILES:
        _copy_file(relative_path, target)

    _copy_tree(ROOT / "paper_monitor", target / "paper_monitor")
    _copy_tree(ROOT / "windows", target / "windows")

    scripts_target = target / "scripts"
    scripts_target.mkdir()
    for name in SCRIPT_FILES:
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
