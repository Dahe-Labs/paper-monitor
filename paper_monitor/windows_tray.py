import argparse
import os
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from .app_refresh import run_app_refresh
from .app_identity import DISPLAY_NAME
from .config import load_app_config, write_default_config
from .windows_dashboard_server import WindowsDashboardServer


APP_NAME = DISPLAY_NAME
APP_DIR_NAME = "PaperMonitor"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def bundled_source_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def default_windows_app_dir(env: Optional[Mapping[str, str]] = None):
    env = env or os.environ
    appdata = env.get("APPDATA")
    if appdata:
        return PureWindowsPath(appdata) / APP_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME


def build_refresh_command(python_executable, config_path) -> List[str]:
    return [
        str(python_executable),
        "-m",
        "paper_monitor.cli",
        "app-refresh",
        "--config",
        str(config_path),
    ]


def notification_target(article: Dict[str, object], dashboard_path: Path) -> str:
    url = str(article.get("url") or "")
    doi = str(article.get("doi") or "")
    if url.startswith(("http://", "https://")):
        return url
    if doi:
        return "https://doi.org/" + doi
    return Path(dashboard_path).resolve().as_uri()


def build_startup_registry_value(executable_path) -> str:
    return f'"{executable_path}" --quiet'


def open_path_with_default_app(path: Path) -> object:
    resolved = Path(path).resolve()
    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        return startfile(str(resolved))
    return webbrowser.open(resolved.as_uri())


def set_startup_enabled(enabled: bool, executable_path, registry_module=None) -> None:
    if registry_module is None:
        import winreg as registry_module

    key = registry_module.OpenKey(
        registry_module.HKEY_CURRENT_USER,
        RUN_KEY_PATH,
        0,
        registry_module.KEY_SET_VALUE,
    )
    try:
        if enabled:
            registry_module.SetValueEx(
                key,
                APP_NAME,
                0,
                registry_module.REG_SZ,
                build_startup_registry_value(executable_path),
            )
        else:
            try:
                registry_module.DeleteValue(key, APP_NAME)
            except (FileNotFoundError, OSError):
                pass
    finally:
        registry_module.CloseKey(key)


def ensure_windows_app_files(app_dir=None, source_root: Optional[Path] = None) -> Path:
    app_dir = Path(app_dir or default_windows_app_dir())
    source_root = source_root or bundled_source_root()
    app_dir.mkdir(parents=True, exist_ok=True)

    config_path = app_dir / "config.json"
    if not config_path.exists():
        example_config = source_root / "config.example.json"
        if example_config.exists():
            shutil.copy2(example_config, config_path)
        else:
            write_default_config(config_path)

    for name in ("config.example.json", "journal_metrics.json"):
        src = source_root / name
        if src.exists():
            shutil.copy2(src, app_dir / name)

    return config_path


@dataclass
class TrayStatus:
    last_run: str = "Last Run: never"
    last_result: str = "Last Result: none"
    refreshing: bool = False


class WindowsToastNotifier:
    def __init__(self, app_id: str = APP_NAME, icon_path: Optional[Path] = None):
        self.app_id = app_id
        self.icon_path = icon_path

    def notify_article(self, article: Dict[str, object], dashboard_path: Path) -> bool:
        target = notification_target(article, dashboard_path)
        title = _truncate(str(article.get("title") or APP_NAME), 120)
        journal = _truncate(str(article.get("journal") or article.get("source") or ""), 80)
        message = str(article.get("doi") or article.get("url") or "Open dashboard")
        try:
            from win11toast import notify
        except ImportError:
            return False

        kwargs = {"on_click": target}
        if self.icon_path is not None:
            kwargs["icon"] = str(self.icon_path)
        notify(title, f"{journal}\n{message}".strip(), **kwargs)
        return True


class WindowsTrayApp:
    def __init__(
        self,
        config_path: Path,
        notifier: Optional[WindowsToastNotifier] = None,
        refresh_function=run_app_refresh,
        dashboard_server_factory: Callable[[Path], object] = WindowsDashboardServer,
        open_url: Callable[[str], object] = webbrowser.open,
        open_file: Callable[[Path], object] = open_path_with_default_app,
    ):
        self.config_path = Path(config_path)
        self.notifier = notifier or WindowsToastNotifier(icon_path=windows_icon_path())
        self.refresh_function = refresh_function
        self.dashboard_server_factory = dashboard_server_factory
        self.open_url = open_url
        self.open_file = open_file
        self.status = TrayStatus()
        self._stop_event = threading.Event()
        self._refresh_lock = threading.Lock()
        self._icon = None
        self._dashboard_server = None

    def run(self, refresh_on_start: bool = True) -> None:
        self._start_refresh_thread(refresh_on_start=refresh_on_start)
        self._icon = self._build_icon()
        self._icon.run()

    def refresh_now(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self.status.refreshing = True
            self.status.last_result = "Last Result: Refreshing..."
            result = self.refresh_function(self.config_path)
            app_config = load_app_config(self.config_path)
            self.status.last_run = "Last Run: " + time.strftime("%Y-%m-%d %H:%M")
            self.status.last_result = _format_result(result)
            for article in result.get("articles", []):
                if isinstance(article, dict):
                    self.notifier.notify_article(article, app_config.dashboard_path)
        except Exception as exc:
            self.status.last_result = "Last Result: Refresh failed"
            print(f"{APP_NAME} refresh failed: {exc}", file=sys.stderr)
        finally:
            self.status.refreshing = False
            self._refresh_lock.release()

    def open_dashboard(self) -> None:
        if self._dashboard_server is None:
            self._dashboard_server = self.dashboard_server_factory(self.config_path)
        self.open_url(self._dashboard_server.start())

    def open_settings(self) -> None:
        self.open_file(self.config_path.resolve())

    def post_test_notification(self) -> None:
        app_config = load_app_config(self.config_path)
        self.notifier.notify_article(
            {
                "title": f"{APP_NAME} test",
                "journal": "Notification Test",
                "url": "https://example.org/paper-monitor-test",
                "doi": "",
                "source": "local",
            },
            app_config.dashboard_path,
        )

    def quit(self) -> None:
        self._stop_event.set()
        if self._dashboard_server is not None and hasattr(self._dashboard_server, "stop"):
            self._dashboard_server.stop()
        if self._icon is not None:
            self._icon.stop()

    def _start_refresh_thread(self, refresh_on_start: bool) -> None:
        app_config = load_app_config(self.config_path)

        def worker() -> None:
            if refresh_on_start:
                self.refresh_now()
            while not self._stop_event.wait(app_config.interval_seconds):
                self.refresh_now()

        thread = threading.Thread(target=worker, name="PaperMonitorRefresh", daemon=True)
        thread.start()

    def _build_icon(self):
        try:
            import pystray
        except ImportError as exc:
            raise RuntimeError("Install Windows tray dependencies from requirements-windows.txt") from exc

        image = _build_tray_image()
        return pystray.Icon(
            APP_DIR_NAME,
            image,
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem(APP_NAME, None, enabled=False),
                pystray.MenuItem(lambda _: self.status.last_run, None, enabled=False),
                pystray.MenuItem(lambda _: self.status.last_result, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open Dashboard", lambda *_: self.open_dashboard()),
                pystray.MenuItem("Settings...", lambda *_: self.open_settings()),
                pystray.MenuItem("Refresh Now", lambda *_: threading.Thread(target=self.refresh_now, daemon=True).start()),
                pystray.MenuItem("Test Notification", lambda *_: self.post_test_notification()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: self.quit()),
            ),
        )


def tray_menu_labels() -> List[str]:
    return [
        APP_NAME,
        "Last Run: never",
        "Last Result: none",
        "Open Dashboard",
        "Settings...",
        "Refresh Now",
        "Test Notification",
        "Quit",
    ]


def windows_icon_path() -> Optional[Path]:
    candidates = (
        bundled_source_root() / "windows" / "assets" / "PaperMonitor.ico",
        Path(sys.executable).resolve().parent / "PaperMonitor.ico",
        Path(__file__).resolve().parents[1] / "windows" / "assets" / "PaperMonitor.ico",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="PaperMonitor")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "install-startup", "uninstall-startup", "test-notification"),
        default="run",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--app-dir", type=Path)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--title", default=f"{APP_NAME} test")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "install-startup":
        set_startup_enabled(True, Path(sys.executable).resolve())
        return 0
    if args.command == "uninstall-startup":
        set_startup_enabled(False, Path(sys.executable).resolve())
        return 0
    if args.command == "test-notification":
        config_path = args.config or ensure_windows_app_files(args.app_dir)
        app_config = load_app_config(config_path)
        sent = WindowsToastNotifier(icon_path=windows_icon_path()).notify_article(
            {
                "title": args.title,
                "journal": "Notification Test",
                "url": "https://example.org/paper-monitor-test",
                "doi": "",
                "source": "local",
            },
            app_config.dashboard_path,
        )
        return 0 if sent else 1

    config_path = args.config or ensure_windows_app_files(args.app_dir)
    app = WindowsTrayApp(config_path=config_path)
    app.run(refresh_on_start=True)
    return 0


def _build_tray_image():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Install Pillow from requirements-windows.txt") from exc

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(21, 101, 192, 255))
    draw.line((22, 19, 43, 19, 22, 30, 42, 30, 42, 43, 21, 43), fill=(255, 255, 255, 255), width=7)
    return image


def _format_result(result: Dict[str, object]) -> str:
    return "Last Result: Fetched {fetched} · Matched {matched} · New {new_matches}".format(
        fetched=result.get("fetched", 0),
        matched=result.get("matched", 0),
        new_matches=result.get("new_matches", 0),
    )


def _truncate(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
