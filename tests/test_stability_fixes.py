import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from paper_monitor import (
    app_refresh,
    sources,
    windows_app_window,
    windows_tray,
    windows_window_control,
)
from paper_monitor.config import DEFAULT_CONFIG, load_app_config
from paper_monitor.config_store import update_config_atomic
from paper_monitor.dashboard import render_dashboard
from paper_monitor.filtering import FilterConfig, match_article
from paper_monitor.journal_metrics import JournalMetrics
from paper_monitor.models import Article
from paper_monitor.monitor import MonitorConfig, run_once
from paper_monitor.sources import fetch_all_sources
from paper_monitor.storage import ArticleStore
from paper_monitor.windows_dashboard_server import (
    WindowsDashboardServer,
    add_include_term,
)
from paper_monitor.windows_settings import (
    default_settings_payload,
    render_settings_page,
    save_settings,
    settings_payload,
)
from scripts.generate_windows_version_info import numeric_version, render_version_info


class StabilityFixTests(unittest.TestCase):
    def test_refresh_reason_values_are_stable(self):
        self.assertEqual(windows_tray.RefreshReason.PROCESS_LAUNCH.value, "process_launch")
        self.assertEqual(windows_tray.RefreshReason.LOGIN_STARTUP.value, "login_startup")
        self.assertEqual(windows_tray.RefreshReason.MANUAL_REFRESH.value, "manual_refresh")
        self.assertEqual(windows_tray.RefreshReason.SCHEDULED_REFRESH.value, "scheduled_refresh")

    def test_install_script_starts_tray_quiet(self):
        script = Path("scripts/install_windows_app.ps1").read_text(encoding="utf-8")
        release_script = Path("windows/Install-PaperMonitor.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$EnableStartup", script)
        self.assertIn("[switch]$LaunchAfterInstall", script)
        self.assertIn("[switch]$EnableStartup", release_script)
        self.assertIn("[switch]$LaunchAfterInstall", release_script)
        self.assertIn("if ($EnableStartup)", script)
        self.assertIn("if ($EnableStartup)", release_script)
        self.assertIn("if ($LaunchAfterInstall)", script)
        self.assertIn("if ($LaunchAfterInstall)", release_script)
        self.assertIn('Start-Process -FilePath $InstalledExe -ArgumentList "tray --quiet"', script)
        self.assertNotIn('Start-Process -FilePath $InstalledExe -ArgumentList "--quiet"', script)
        self.assertIn('Start-Process -FilePath $InstalledExe -ArgumentList @("tray", "--quiet")', release_script)
        self.assertIn("& $InstalledExe install-startup", release_script)
        self.assertIn("function Stop-InstalledPaperMonitor", script)
        self.assertIn("function Stop-InstalledPaperMonitor", release_script)
        self.assertIn("Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe", script)
        self.assertIn("Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe", release_script)

    def test_startup_registry_value_is_quiet_tray_command(self):
        self.assertEqual(
            windows_tray.build_startup_registry_value(r"C:\Apps\PaperMonitor.exe"),
            r'"C:\Apps\PaperMonitor.exe" tray --quiet',
        )

    def test_config_readers_accept_utf8_bom_without_preserving_it_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8-sig")

            app_config = load_app_config(config_path)
            update_config_atomic(config_path, lambda payload: payload)
            saved = config_path.read_bytes()

        self.assertEqual(app_config.interval_seconds, DEFAULT_CONFIG["interval_seconds"])
        self.assertFalse(saved.startswith(b"\xef\xbb\xbf"))

    def test_tray_quiet_command_does_not_open_dashboard_window(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                self.assertEqual(windows_tray.main(["tray", "--quiet", "--config", str(config_path)]), 0)

        tray_app_class.assert_called_once_with(config_path=config_path)
        tray_app_class.return_value.run.assert_called_once_with(refresh_on_start=True, quiet=True)

    def test_tray_quiet_can_skip_launch_refresh_for_window_helper_start(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                self.assertEqual(
                    windows_tray.main([
                        "tray",
                        "--quiet",
                        "--no-launch-refresh",
                        "--config",
                        str(config_path),
                    ]),
                    0,
                )

        tray_app_class.assert_called_once_with(config_path=config_path)
        tray_app_class.return_value.run.assert_called_once_with(refresh_on_start=False, quiet=True)

    def test_tray_start_failure_is_logged_without_unhandled_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                tray_app_class.return_value.run.side_effect = RuntimeError("tray backend failed")
                with patch("paper_monitor.windows_tray._log_app_error") as log_error:
                    with patch("paper_monitor.windows_tray.show_tray_message") as show_message:
                        status = windows_tray.main(["tray", "--config", str(config_path)])

        self.assertEqual(status, 1)
        log_error.assert_called_once()
        show_message.assert_called_once()

    def test_manual_window_helper_marks_quiet_tray_as_process_launch(self):
        command = windows_tray.tray_process_command(
            Path("config.json"),
            refresh_on_launch=True,
            launch_reason=windows_tray.RefreshReason.PROCESS_LAUNCH,
        )

        self.assertIn("--quiet", command)
        self.assertNotIn("--no-launch-refresh", command)
        reason_index = command.index("--launch-reason")
        self.assertEqual(command[reason_index + 1], "process_launch")

    def test_explicit_process_launch_reason_overrides_quiet_login_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                status = windows_tray.main([
                    "tray",
                    "--quiet",
                    "--launch-reason",
                    "process_launch",
                    "--config",
                    str(config_path),
                ])

        self.assertEqual(status, 0)
        tray_app_class.return_value.run.assert_called_once_with(
            refresh_on_start=True,
            quiet=True,
            launch_reason=windows_tray.RefreshReason.PROCESS_LAUNCH,
        )

    def test_tray_visibility_updates_while_coordinator_is_running(self):
        class FakeIcon:
            def __init__(self):
                self.changes = []
                self.changed = threading.Event()

            @property
            def visible(self):
                return self.changes[-1] if self.changes else False

            @visible.setter
            def visible(self, value):
                self.changes.append(bool(value))
                self.changed.set()

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            app = windows_tray.WindowsTrayApp(config_path)
            icon = FakeIcon()
            watcher = threading.Thread(
                target=lambda: app._watch_tray_visibility(icon, initial_visible=True),
                daemon=True,
            )
            watcher.start()
            self.assertTrue(icon.changed.wait(1.0))

            def hide_tray(payload):
                payload["app_settings"]["show_tray_icon"] = False
                return payload

            update_config_atomic(config_path, hide_tray)
            deadline = time.monotonic() + 3.0
            while False not in icon.changes and time.monotonic() < deadline:
                time.sleep(0.05)

            app._stop_event.set()
            watcher.join(timeout=1.0)

        self.assertEqual(icon.changes, [True, False])
        self.assertFalse(watcher.is_alive())


    def test_window_command_ensures_tray_process(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.ensure_tray_process") as ensure_tray:
                with patch("paper_monitor.windows_app_window.open_dashboard_window", return_value=0) as open_window:
                    self.assertEqual(windows_tray.main(["window", "--config", str(config_path)]), 0)

            ensure_tray.assert_called_once_with(
                config_path,
                refresh_on_launch=True,
                launch_reason=windows_tray.RefreshReason.PROCESS_LAUNCH,
            )
            open_window.assert_called_once()

    def test_window_command_routes_existing_window_without_starting_another(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=True):
                    with patch("paper_monitor.windows_tray.activate_existing_app_window", return_value=True) as activate:
                        with patch("paper_monitor.windows_tray.ensure_tray_process") as ensure_tray:
                            status = windows_tray.main(["settings", "--config", str(config_path)])

        self.assertEqual(status, 0)
        activate.assert_called_once_with(config_path, path="/settings")
        ensure_tray.assert_not_called()

    def test_window_command_launched_by_tray_does_not_spawn_second_tray(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch.dict(os.environ, {windows_tray.LAUNCHED_BY_TRAY_ENV: "1"}):
                with patch("paper_monitor.windows_tray.ensure_tray_process") as ensure_tray:
                    with patch("paper_monitor.windows_app_window.open_dashboard_window", return_value=0) as open_window:
                        self.assertEqual(windows_tray.main(["settings", "--config", str(config_path)]), 0)

            ensure_tray.assert_not_called()
            open_window.assert_called_once()

    def test_launch_app_window_uses_utf8_child_environment(self):
        with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
            with patch("paper_monitor.windows_tray.subprocess.Popen") as popen:
                windows_tray.launch_app_window(Path("config.json"))

        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["stdin"], windows_tray.subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], windows_tray.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], windows_tray.subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(kwargs["env"][windows_tray.LAUNCHED_BY_TRAY_ENV], "1")

    def test_frozen_launch_app_window_resets_pyinstaller_child_environment(self):
        with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
            with patch.object(sys, "frozen", True, create=True):
                with patch("paper_monitor.windows_tray.subprocess.Popen") as popen:
                    windows_tray.launch_app_window(Path("config.json"))

        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_window_closed_callback_never_raises_into_dotnet(self):
        def fail():
            raise UnicodeEncodeError("charmap", "Paper Monitor", 0, 1, "character maps to <undefined>")

        callback = windows_app_window._safe_closed_callback(fail)
        callback()

    def test_dashboard_window_uses_persistent_webview_storage(self):
        class FakeClosedEvent:
            def __init__(self):
                self.callback = None

            def __iadd__(self, callback):
                self.callback = callback
                return self

        class FakeWindow:
            def __init__(self):
                self.events = types.SimpleNamespace(closed=FakeClosedEvent())

        class FakeWebview:
            def __init__(self):
                self.window = FakeWindow()
                self.start_kwargs = None

            def create_window(self, *_args, **_kwargs):
                return self.window

            def start(self, **kwargs):
                self.start_kwargs = kwargs

        class FakeServer:
            def __init__(self):
                self.stop_count = 0

            def start(self):
                return "http://127.0.0.1:12345/"

            def stop(self):
                self.stop_count += 1

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            fake_webview = FakeWebview()
            fake_server = FakeServer()
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                with patch("paper_monitor.windows_app_window._load_webview", return_value=fake_webview):
                    status = windows_app_window.open_dashboard_window(
                        config_path,
                        dashboard_server_factory=lambda _path: fake_server,
                    )

            self.assertEqual(status, 0)
            self.assertEqual(fake_webview.start_kwargs["private_mode"], False)
            self.assertEqual(
                fake_webview.start_kwargs["storage_path"],
                str(Path(directory) / "PaperMonitor" / "WebView2"),
            )
            self.assertEqual(fake_server.stop_count, 1)
            fake_webview.window.events.closed.callback()
            self.assertEqual(fake_server.stop_count, 1)

    def test_dashboard_window_registers_local_control_endpoint(self):
        class FakeServer:
            token = "secret-token"

            def __init__(self):
                self.controller = None

            def set_window_controller(self, controller):
                self.controller = controller

        class FakeWindow:
            def __init__(self):
                self.urls = []
                self.destroyed = False

            def load_url(self, url):
                self.urls.append(url)

            def destroy(self):
                self.destroyed = True

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            server = FakeServer()
            window = FakeWindow()

            windows_app_window._register_window_control(
                config_path,
                server,
                "http://127.0.0.1:12345/",
                window,
            )
            state = windows_window_control.read_window_control(config_path)
            self.assertIsNotNone(state)
            self.assertEqual(state.base_url, "http://127.0.0.1:12345")
            self.assertEqual(state.token, "secret-token")
            self.assertEqual(list(config_path.parent.glob(".window-control.json.*.tmp")), [])

            self.assertEqual(server.controller({"action": "ping"}), {"ok": True})
            self.assertEqual(server.controller({"action": "show", "route": "/settings"}), {"ok": True})
            self.assertEqual(server.controller({"action": "close"}), {"ok": True})
            time.sleep(0.2)

            windows_window_control.clear_window_control(config_path)

        self.assertEqual(window.urls, ["http://127.0.0.1:12345/settings"])
        self.assertTrue(window.destroyed)

    def test_dashboard_window_returns_when_window_mutex_already_exists(self):
        class FakeServer:
            def start(self):
                raise AssertionError("server must not start when a dashboard window is already open")

            def stop(self):
                raise AssertionError("server must not stop when it never started")

        with patch("paper_monitor.windows_app_window._acquire_window_mutex", return_value=None):
            with patch("paper_monitor.windows_app_window.send_window_control") as send_control:
                with patch("paper_monitor.windows_app_window._load_webview") as load_webview:
                    status = windows_app_window.open_dashboard_window(
                        Path("config.json"),
                        dashboard_server_factory=lambda _path: FakeServer(),
                        path="/settings",
                    )

        self.assertEqual(status, 0)
        send_control.assert_called_once_with(Path("config.json"), "show", route="/settings")
        load_webview.assert_not_called()

    def test_dashboard_window_releases_mutex_when_webview_load_fails(self):
        handle = object()

        with patch("paper_monitor.windows_app_window._acquire_window_mutex", return_value=handle):
            with patch("paper_monitor.windows_app_window._load_webview", side_effect=RuntimeError("missing webview")):
                with patch("paper_monitor.windows_app_window.clear_window_control") as clear_control:
                    with patch("paper_monitor.windows_app_window.close_handle") as close_handle:
                        with self.assertRaises(RuntimeError):
                            windows_app_window.open_dashboard_window(Path("config.json"))

        clear_control.assert_called_once_with(Path("config.json"))
        close_handle.assert_called_once_with(handle)

    def test_tray_opens_app_window_instead_of_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []

            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)),
            )
            app.open_dashboard()
            app.open_settings()

        self.assertEqual(opened, [(config_path, "/"), (config_path, "/settings")])

    def test_tray_open_actions_dispatch_window_and_settings_commands(self):
        class FinishedProcess:
            def poll(self):
                return 0

        executable = str((Path.cwd() / "PaperMonitor.exe").resolve())

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            app = windows_tray.WindowsTrayApp(
                config_path,
                focus_window=lambda: False,
                launch_error_handler=lambda _error, _path: None,
            )

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=False):
                    with patch.object(sys, "executable", executable):
                        with patch.object(sys, "frozen", True, create=True):
                            with patch("paper_monitor.windows_tray.subprocess.Popen", side_effect=[FinishedProcess(), FinishedProcess()]) as popen:
                                app.open_dashboard()
                                app.open_settings()

        commands = [call.args[0] for call in popen.call_args_list]
        self.assertEqual(commands[0], [executable, "window", "--config", str(config_path)])
        self.assertEqual(commands[1], [executable, "settings", "--config", str(config_path)])
        self.assertNotIn("paper_monitor.cli", commands[0] + commands[1])
        self.assertNotIn("open-dashboard", commands[0] + commands[1])

    def test_opening_dashboard_does_not_run_launch_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []

            def fail_refresh(_config_path):
                raise AssertionError("dashboard opening must not refresh")

            app = windows_tray.WindowsTrayApp(
                config_path,
                refresh_function=fail_refresh,
                open_window=lambda path, route: opened.append((Path(path), route)),
            )

            app.open_dashboard()

        self.assertEqual(opened, [(config_path, "/")])

    def test_tray_focuses_existing_window_when_window_mutex_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            focused = []
            opened = []
            controls = []

            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)),
                focus_window=lambda: focused.append(True) or True,
                control_window=lambda path, action, route=None: controls.append((Path(path), action, route)) or True,
            )

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=True):
                    app.open_settings()

        self.assertEqual(opened, [])
        self.assertEqual(focused, [True])
        self.assertEqual(controls, [(config_path, "show", "/settings")])

    def test_tray_window_launch_failure_is_logged_and_handled(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            handled = []

            def fail_open(_path, _route):
                raise OSError("cannot launch child process")

            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=fail_open,
                focus_window=lambda: False,
                launch_error_handler=lambda error, path: handled.append((type(error), path, str(error))),
            )

            with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=False):
                app.open_dashboard()

            log_path = config_path.parent / "PaperMonitor.log"
            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(handled, [(OSError, "/", "cannot launch child process")])
        self.assertEqual(app.status.last_result, "Last Result: Could not open window")
        self.assertIn("cannot launch child process", log_text)

    def test_window_child_exit_before_control_ready_is_reported(self):
        class FinishedProcess:
            pid = 123

            def poll(self):
                return 1

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            handled = []
            process = FinishedProcess()
            app = windows_tray.WindowsTrayApp(
                config_path,
                control_window=lambda *_args, **_kwargs: False,
                launch_error_handler=lambda error, path: handled.append((str(error), path)),
            )
            app._window_process = process
            app._pending_window_route = "/settings"

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=False):
                    app._monitor_window_launch(process, "/settings")

        self.assertEqual(
            handled,
            [("The Paper Monitor window process exited before becoming ready.", "/settings")],
        )
        self.assertEqual(app.status.last_result, "Last Result: Could not open window")

    def test_running_child_without_window_mutex_is_not_duplicated_during_startup(self):
        class RunningProcess:
            pid = 123

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)) or RunningProcess(),
                focus_window=lambda: True,
                control_window=lambda _path, _action, route=None: (_ for _ in ()).throw(RuntimeError("no endpoint")),
            )
            running_process = RunningProcess()
            app._window_process = running_process

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=False):
                    with patch.object(app, "_start_window_launch_monitor") as monitor:
                        app.open_settings()

        self.assertEqual(opened, [])
        monitor.assert_called_once_with(running_process, "/settings")

    def test_tray_open_menu_item_uses_native_window_launcher_without_default_click(self):
        class FakeMenu:
            SEPARATOR = object()

            def __init__(self, *items):
                self.items = list(items)

            def __call__(self, icon):
                return None

        class FakeMenuItem:
            def __init__(self, text, action, **kwargs):
                self.text = text
                self.action = action
                self.default = kwargs.get("default", False)

            def __call__(self, icon):
                return self.action(icon, self)

        class FakeIcon:
            def __init__(self, name, image, title, menu):
                self.name = name
                self.image = image
                self.title = title
                self.menu = menu

            def __call__(self):
                return self.menu(self)

        fake_pystray = types.SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)),
            )

            with patch.dict(sys.modules, {"pystray": fake_pystray}):
                with patch("paper_monitor.windows_tray._build_tray_image", return_value=object()):
                    icon = app._build_icon()

            default_items = [item for item in icon.menu.items if getattr(item, "default", False)]
            self.assertEqual(default_items, [])

            icon()
            open_items = [item for item in icon.menu.items if getattr(item, "text", "") == "Open Paper Monitor"]
            self.assertEqual(len(open_items), 1)
            open_items[0](icon)

        self.assertEqual(opened, [(config_path, "/")])

    def test_windows_tray_double_click_opens_dashboard_but_single_click_does_not(self):
        fake_pystray = types.ModuleType("pystray")
        fake_pystray.__path__ = []
        fake_pystray.Icon = object
        fake_win32 = types.SimpleNamespace(
            WM_LBUTTONUP=0x0202,
            WM_LBUTTONDBLCLK=0x0203,
            WM_RBUTTONUP=0x0205,
        )
        fake_util = types.ModuleType("pystray._util")
        fake_util.win32 = fake_win32
        calls = []

        class FakeWin32Icon:
            def _on_notify(self, _wparam, lparam):
                calls.append(("base", lparam))
                return 17

        fake_win32_module = types.ModuleType("pystray._win32")
        fake_win32_module.Icon = FakeWin32Icon

        with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
            with patch.dict(
                sys.modules,
                {
                    "pystray": fake_pystray,
                    "pystray._win32": fake_win32_module,
                    "pystray._util": fake_util,
                },
            ):
                icon_class = windows_tray._tray_icon_class(
                    types.SimpleNamespace(Icon=object),
                    lambda: calls.append("open"),
                )

        icon = icon_class()
        self.assertEqual(icon._on_notify(0, 0x0202), 17)
        self.assertEqual(calls, [("base", 0x0202)])
        self.assertEqual(icon._on_notify(0, 0x0203), 0)
        self.assertEqual(calls, [("base", 0x0202), "open"])
        self.assertEqual(icon._on_notify(0, 0x0205), 17)
        self.assertEqual(calls, [("base", 0x0202), "open", ("base", 0x0205)])

    def test_open_dashboard_is_single_flight_while_window_process_runs(self):
        class RunningProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)) or RunningProcess(),
            )
            app.open_dashboard()
            app.open_dashboard()
            app.open_settings()

        self.assertEqual(opened, [(config_path, "/")])

    def test_existing_window_receives_route_control_instead_of_new_process(self):
        class RunningProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            opened = []
            controls = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda path, route: opened.append((Path(path), route)) or RunningProcess(),
                control_window=lambda path, action, route=None: controls.append((Path(path), action, route)) or True,
            )
            app.open_dashboard()
            app.open_settings()

        self.assertEqual(opened, [(config_path, "/")])
        self.assertEqual(controls, [(config_path, "show", "/settings")])

    def test_window_control_monitor_restarts_for_route_clicked_during_delivery(self):
        class RunningProcess:
            pid = 123

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            process = RunningProcess()
            app = None

            def control(_path, action, route=None):
                if action == "show" and route == "/":
                    app._pending_window_route = "/settings"
                return True

            app = windows_tray.WindowsTrayApp(config_path, control_window=control)
            app._window_process = process
            app._pending_window_route = "/"

            with patch.object(app, "_start_window_launch_monitor") as restart:
                app._monitor_window_launch(process, "/")

        restart.assert_called_once_with(process, "/settings")

    def test_tray_refresh_reloads_existing_dashboard_window(self):
        class RunningProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            controls = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                refresh_function=lambda _path: {"fetched": 1, "matched": 1, "new_matches": 0, "articles": []},
                control_window=lambda path, action, route=None: controls.append((Path(path), action, route)) or True,
            )
            app._window_process = RunningProcess()
            app.refresh_now()

        self.assertEqual(controls, [(config_path, "reload", "/")])

    def test_tray_quit_closes_existing_dashboard_window(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            controls = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                control_window=lambda path, action, route=None: controls.append((Path(path), action, route)) or True,
            )
            app.quit()

        self.assertEqual(controls, [(config_path, "close", None)])

    def test_test_notification_reports_failure(self):
        class FailingNotifier:
            def notify_article(self, _article, _dashboard_path):
                return False

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            messages = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                notifier=FailingNotifier(),
                message_handler=messages.append,
            )
            app.post_test_notification()

        self.assertEqual(app.status.last_result, "Last Result: Test notification failed")
        self.assertEqual(len(messages), 1)

    def test_windows_notification_runtime_failure_returns_false(self):
        fake_module = types.SimpleNamespace(
            notify=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("toast unavailable"))
        )
        notifier = windows_tray.WindowsToastNotifier()

        with patch.dict(sys.modules, {"win11toast": fake_module}):
            sent = notifier.notify_article(
                {"title": "Paper", "journal": "Journal", "url": "https://example.org"},
                Path("dashboard.html"),
            )

        self.assertFalse(sent)

    def test_no_console_stderr_fallback_never_raises(self):
        with patch.object(sys, "stderr", None):
            windows_tray._write_stderr("background error")

    def test_open_dashboard_focuses_running_window_process(self):
        class RunningProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            focused = []
            app = windows_tray.WindowsTrayApp(
                config_path,
                open_window=lambda _path, _route: RunningProcess(),
                focus_window=lambda: focused.append(True) or True,
            )
            app.open_dashboard()
            app.open_dashboard()

        self.assertEqual(focused, [True])

    def test_launch_app_window_skips_when_window_mutex_exists(self):
        with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
            with patch("paper_monitor.windows_tray._is_window_mutex_running", return_value=True):
                with patch("paper_monitor.windows_tray.subprocess.Popen") as popen:
                    self.assertIsNone(windows_tray.launch_app_window(Path("config.json")))

        popen.assert_not_called()

    def test_app_window_command_uses_internal_window_entrypoint(self):
        command = windows_tray.app_window_command(Path("config.json"), path="/")
        settings_command = windows_tray.app_window_command(Path("config.json"), path="/settings")

        self.assertIn("window", command)
        self.assertIn("settings", settings_command)
        self.assertIn("--config", command)
        self.assertIn("paper_monitor.windows_tray", command)
        self.assertNotIn("paper_monitor.cli", command)
        self.assertNotIn("open-dashboard", command)
        self.assertNotIn("http://", " ".join(command))

    def test_frozen_app_window_command_uses_papermonitor_exe_entrypoint(self):
        executable = str((Path.cwd() / "PaperMonitor.exe").resolve())

        with patch.object(sys, "executable", executable):
            with patch.object(sys, "frozen", True, create=True):
                command = windows_tray.app_window_command(Path("config.json"), path="/")
                settings_command = windows_tray.app_window_command(Path("config.json"), path="/settings")

        self.assertEqual(command, [executable, "window", "--config", "config.json"])
        self.assertEqual(settings_command, [executable, "settings", "--config", "config.json"])
        self.assertNotIn("paper_monitor.cli", command)
        self.assertNotIn("open-dashboard", command)

    def test_frozen_ensure_tray_process_uses_papermonitor_exe_tray_entrypoint(self):
        executable = str((Path.cwd() / "PaperMonitor.exe").resolve())

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_tray_mutex_running", return_value=False):
                    with patch.object(sys, "executable", executable):
                        with patch.object(sys, "frozen", True, create=True):
                            with patch("paper_monitor.windows_tray.subprocess.Popen") as popen:
                                self.assertTrue(windows_tray.ensure_tray_process(config_path))

        tray_command = popen.call_args.args[0]
        self.assertEqual(tray_command[:2], [executable, "tray"])
        self.assertIn("--quiet", tray_command)
        self.assertNotIn("--no-launch-refresh", tray_command)
        self.assertIn("--launch-reason", tray_command)
        reason_index = tray_command.index("--launch-reason")
        self.assertEqual(tray_command[reason_index + 1], "process_launch")
        self.assertIn("--config", tray_command)
        self.assertIn(str(config_path), tray_command)
        self.assertNotIn("paper_monitor.cli", tray_command)
        self.assertNotIn("open-dashboard", tray_command)
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_hidden_tray_icon_does_not_disable_background_coordinator(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["app_settings"]["show_tray_icon"] = False
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with patch("paper_monitor.windows_tray._is_windows_platform", return_value=True):
                with patch("paper_monitor.windows_tray._is_tray_mutex_running", return_value=False):
                    with patch("paper_monitor.windows_tray.subprocess.Popen") as popen:
                        started = windows_tray.ensure_tray_process(config_path)

        self.assertTrue(started)
        popen.assert_called_once()

    def test_window_command_handles_launch_failure_without_unhandled_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            with patch("paper_monitor.windows_tray.ensure_tray_process"):
                with patch(
                    "paper_monitor.windows_app_window.open_dashboard_window",
                    side_effect=RuntimeError("missing pywebview runtime"),
                ):
                    with patch("paper_monitor.windows_tray._log_window_launch_error") as log_error:
                        with patch("paper_monitor.windows_tray.show_window_launch_error") as show_error:
                            status = windows_tray.main(["settings", "--config", str(config_path)])

        self.assertEqual(status, 1)
        log_error.assert_called_once()
        show_error.assert_called_once()

    def test_launch_refresh_runs_once_on_process_start_even_with_scheduled_start_time(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["refresh_start_time"] = "23:59"
            payload["interval_seconds"] = 86400
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            refreshed = threading.Event()
            calls = []

            def refresh_runner(path):
                calls.append(Path(path))
                refreshed.set()
                return {"fetched": 0, "matched": 0, "new_matches": 0, "articles": []}

            app = windows_tray.WindowsTrayApp(config_path, refresh_function=refresh_runner)
            thread = app._start_refresh_thread(refresh_on_start=True)

            self.assertTrue(refreshed.wait(timeout=2))
            app.quit()
            thread.join(timeout=2)

        self.assertEqual(calls, [config_path])
        self.assertFalse(thread.is_alive())

    def test_launch_refresh_disabled_does_not_run_on_process_start(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["interval_seconds"] = 86400
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls = []

            app = windows_tray.WindowsTrayApp(
                config_path,
                refresh_function=lambda path: calls.append(Path(path)),
            )
            thread = app._start_refresh_thread(refresh_on_start=False)
            time.sleep(0.1)
            app.quit()
            thread.join(timeout=2)

        self.assertEqual(calls, [])
        self.assertFalse(thread.is_alive())

    def test_login_startup_refresh_can_suppress_notifications_without_muting_manual_refresh(self):
        class RecordingNotifier:
            def __init__(self):
                self.articles = []

            def notify_article(self, article, dashboard_path):
                self.articles.append((article, dashboard_path))
                return True

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["app_settings"]["notifications_enabled"] = True
            payload["app_settings"]["silent_startup_notifications"] = True
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            notifier = RecordingNotifier()
            app = windows_tray.WindowsTrayApp(
                config_path,
                notifier=notifier,
                refresh_function=lambda _path: {
                    "fetched": 1,
                    "matched": 1,
                    "new_matches": 1,
                    "articles": [{"title": "Launch paper", "url": "https://example.org/paper"}],
                },
            )

            app.refresh_now(reason=windows_tray.RefreshReason.LOGIN_STARTUP)
            self.assertEqual(notifier.articles, [])

            app.refresh_now(reason=windows_tray.RefreshReason.MANUAL_REFRESH)

        self.assertEqual(len(notifier.articles), 1)

    def test_module_tray_process_command_uses_windows_tray_entrypoint(self):
        executable = str((Path.cwd() / ".venv" / "Scripts" / "python.exe").resolve())

        with patch.object(sys, "executable", executable):
            with patch.object(sys, "frozen", False, create=True):
                command = windows_tray.tray_process_command(Path("config.json"))
                helper_command = windows_tray.tray_process_command(Path("config.json"), refresh_on_launch=False)

        self.assertEqual(
            command,
            [
                executable,
                "-m",
                "paper_monitor.windows_tray",
                "tray",
                "--quiet",
                "--config",
                "config.json",
            ],
        )
        self.assertEqual(
            helper_command,
            [
                executable,
                "-m",
                "paper_monitor.windows_tray",
                "tray",
                "--quiet",
                "--no-launch-refresh",
                "--config",
                "config.json",
            ],
        )
        self.assertNotIn("paper_monitor.cli", command)
        self.assertNotIn("open-dashboard", command)

    def test_windows_tray_module_has_no_browser_dashboard_launcher(self):
        source = Path("paper_monitor/windows_tray.py").read_text(encoding="utf-8")

        self.assertNotIn("open-dashboard", source)
        self.assertNotIn("webbrowser.open", source)
        self.assertNotIn("os.startfile", source)

    def test_settings_save_and_add_search_term_share_atomic_update(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            def save():
                return save_settings(config_path, {"max_notifications": 9})

            def add_term():
                add_include_term(config_path, "stack pressure")

            with ThreadPoolExecutor(max_workers=2) as executor:
                save_future = executor.submit(save)
                add_future = executor.submit(add_term)

            self.assertEqual(save_future.result(), {"ok": True})
            add_future.result()

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["max_notifications"], 9)
            self.assertIn("stack pressure", payload["include_terms"])
            self.assertTrue(config_path.with_name("config.json.bak").exists())

    def test_failed_run_is_marked_failed_instead_of_left_running(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArticleStore(Path(directory) / "articles.sqlite3")
            config = MonitorConfig(
                filter_config=FilterConfig(include_terms=["solid electrolyte"], exclude_terms=[], journals=[]),
                max_notifications=5,
            )

            def fail_fetch():
                raise RuntimeError("network boom")

            with self.assertRaises(RuntimeError):
                run_once(config, store, fail_fetch, lambda _article, _match: None)

            latest = store.latest_run()
            self.assertIsNotNone(latest)
            self.assertEqual(latest["status"], "failed")
            self.assertIn("network boom", latest["error_message"])

    def test_keyword_analysis_requests_are_single_flight(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            started = threading.Event()
            release = threading.Event()
            run_count = 0
            run_lock = threading.Lock()

            def runner(*_args, **_kwargs):
                nonlocal run_count
                with run_lock:
                    run_count += 1
                started.set()
                release.wait(timeout=5)
                return {"ok": True, "papers": []}

            server = WindowsDashboardServer(config_path, keyword_analysis_runner=runner)
            payload = {
                "date_from": "2026-06-01",
                "date_to": "2026-06-02",
                "sort_mode": "time",
                "analysis_depth": "fast",
                "top_n": 10,
                "journals": ["Nature Energy"],
            }

            first_status = {}

            def first_request():
                first_status["value"] = server.handle_api_request("/api/analyze-keywords", payload)

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(timeout=2))

            status, body = server.handle_api_request("/api/analyze-keywords", payload)

            release.set()
            thread.join(timeout=5)
            self.assertEqual(status, 409)
            self.assertEqual(body, {"ok": False, "error": "analysis_already_running"})
            self.assertEqual(first_status["value"][0], 200)
            self.assertEqual(run_count, 1)

    def test_dashboard_manual_refresh_button_and_endpoint(self):
        html = render_dashboard({}, [], JournalMetrics([]))
        self.assertIn('id="paper-monitor-refresh-button"', html)
        self.assertNotIn('id="paper-monitor-refresh-button" class="header-action-button" hidden', html)
        self.assertIn("Refresh Now", html)
        self.assertIn('type: "refreshNow"', html)

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            started = threading.Event()
            release = threading.Event()
            run_count = 0

            def refresh_runner(_config_path):
                nonlocal run_count
                run_count += 1
                started.set()
                release.wait(timeout=5)
                return {"run_id": 1, "fetched": 0, "matched": 0, "new_matches": 0, "skipped": 0, "articles": []}

            server = WindowsDashboardServer(config_path, refresh_runner=refresh_runner)
            app_config = DEFAULT_CONFIG.copy()
            stale_dashboard = Path(directory) / app_config["dashboard_path"]
            stale_dashboard.parent.mkdir(parents=True, exist_ok=True)
            stale_dashboard.write_text("<html><body>Old dashboard</body></html>", encoding="utf-8")
            dashboard_html = server.dashboard_html()
            self.assertIn("/api/refresh-now", dashboard_html)
            self.assertNotIn("paperMonitorAppInfo", dashboard_html)
            self.assertNotIn("paper-monitor-build-badge", dashboard_html)
            self.assertIn('id="paper-monitor-refresh-button"', stale_dashboard.read_text(encoding="utf-8"))
            first_status = {}

            def first_request():
                first_status["value"] = server.handle_api_request("/api/refresh-now", {})

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(timeout=2))

            status, body = server.handle_api_request("/api/refresh-now", {})

            release.set()
            thread.join(timeout=5)
            self.assertEqual(status, 409)
            self.assertEqual(body, {"ok": False, "error": "refresh_already_running"})
            self.assertEqual(first_status["value"][0], 200)
            self.assertEqual(run_count, 1)

    def test_app_refresh_uses_named_cross_process_guard(self):
        with patch("paper_monitor.app_refresh.acquire_mutex", return_value=None):
            with self.assertRaises(app_refresh.RefreshAlreadyRunning):
                app_refresh.run_app_refresh(Path("config.json"))

        self.assertTrue(app_refresh._APP_REFRESH_LOCK.acquire(blocking=False))
        app_refresh._APP_REFRESH_LOCK.release()

    def test_dashboard_maps_shared_refresh_guard_to_conflict(self):
        def already_running(_config_path):
            raise app_refresh.RefreshAlreadyRunning("busy")

        server = WindowsDashboardServer(Path("config.json"), refresh_runner=already_running)
        status, body = server.handle_api_request("/api/refresh-now", {})

        self.assertEqual(status, 409)
        self.assertEqual(body, {"ok": False, "error": "refresh_already_running"})

    def test_tray_maps_shared_refresh_guard_to_status(self):
        def already_running(_config_path):
            raise app_refresh.RefreshAlreadyRunning("busy")

        app = windows_tray.WindowsTrayApp(Path("config.json"), refresh_function=already_running)
        app.refresh_now()

        self.assertEqual(app.status.last_result, "Last Result: Refresh already running")
        self.assertFalse(app.status.refreshing)

    def test_settings_page_uses_top_left_back_link_and_restore_defaults(self):
        html = render_settings_page(Path("config.json"), "http://127.0.0.1:1", "token")

        self.assertIn('class="back-link" id="dashboard-link"', html)
        self.assertIn("&larr; Main Window", html)
        self.assertIn('data-testid="tab-app-settings"', html)
        self.assertIn('data-testid="journal-picker"', html)
        self.assertIn('data-testid="selected-journal-list"', html)
        self.assertIn('data-testid="candidate-journal-list"', html)
        self.assertIn('data-testid="journal-sort-mode"', html)
        self.assertIn('data-testid="manual-journal-name"', html)
        self.assertIn('id="openalex_max_pages"', html)
        self.assertIn("Launch at Startup", html)
        self.assertIn("Tray Icon", html)
        self.assertIn("Notifications", html)
        self.assertIn("Quiet Startup", html)
        self.assertNotIn('data-testid="build-identity"', html)
        self.assertIn('id="defaults-button"', html)
        self.assertIn("Restore Defaults", html)
        self.assertNotIn('id="reload-button"', html)
        self.assertIn("/api/settings/defaults", html)

        defaults = default_settings_payload()
        self.assertNotIn("app_info", defaults)
        self.assertEqual(defaults["refresh_start_time"], DEFAULT_CONFIG["refresh_start_time"])
        self.assertEqual(defaults["search_direction"]["preset"], DEFAULT_CONFIG["search_direction"]["preset"])
        self.assertEqual(defaults["app_settings"], DEFAULT_CONFIG["app_settings"])
        formal_candidates = [
            entry for entry in defaults["journal_catalog"]
            if str(entry["journal"]).casefold() != "arxiv"
        ]
        self.assertEqual(len(formal_candidates), 300)
        self.assertTrue(all(entry["category"] for entry in formal_candidates))
        self.assertEqual(
            float(defaults["journal_catalog"][0]["impact_factor"]),
            max(float(entry["impact_factor"]) for entry in formal_candidates),
        )
        self.assertGreaterEqual(
            float(defaults["journal_catalog"][0]["impact_factor"]),
            float(defaults["journal_catalog"][1]["impact_factor"]),
        )

    def test_settings_page_resources_do_not_depend_on_current_working_directory(self):
        current = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                import os

                os.chdir(directory)
                html = render_settings_page(Path("config.json"), "http://127.0.0.1:1", "token")
            finally:
                os.chdir(current)

        self.assertNotIn("__SETTINGS_CONTEXT__", html)
        self.assertNotIn("__SETTINGS_CSS__", html)
        self.assertNotIn("__SETTINGS_JS__", html)
        self.assertIn("/api/settings/defaults", html)
        self.assertIn("X-Paper-Monitor-Token", html)
        self.assertIn('data-testid="journal-picker"', html)

    def test_settings_payload_falls_back_to_legacy_root_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload.pop("journal_scope")
            payload["journals"] = ["Nature Energy", "Advanced Materials"]
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            settings = settings_payload(config_path)

            self.assertEqual(
                settings["journal_scope"]["selected_journals"],
                ["Nature Energy", "Advanced Materials"],
            )

    def test_app_settings_are_saved_to_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            response = save_settings(
                config_path,
                {
                    "app_settings": {
                        "startup_enabled": True,
                        "show_tray_icon": False,
                        "notifications_enabled": False,
                        "silent_startup_notifications": True,
                        "refresh_on_launch": False,
                    }
                },
            )

            self.assertEqual(response, {"ok": True})
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["app_settings"],
                {
                    "startup_enabled": True,
                    "show_tray_icon": False,
                    "notifications_enabled": False,
                    "silent_startup_notifications": True,
                    "refresh_on_launch": False,
                },
            )

    def test_app_settings_save_preserves_unknown_future_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["app_settings"]["future_app_option"] = "keep me"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            response = save_settings(config_path, {"app_settings": {"startup_enabled": True}})

            self.assertEqual(response, {"ok": True})
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["app_settings"]["future_app_option"], "keep me")
            self.assertTrue(saved["app_settings"]["startup_enabled"])

    def test_settings_save_preserves_unknown_source_limit_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["sources"]["crossref"]["min_request_interval_seconds"] = 0.5
            payload["sources"]["crossref"]["future_crossref_option"] = "keep me"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            response = save_settings(config_path, {"max_notifications": 8})

            self.assertEqual(response, {"ok": True})
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["max_notifications"], 8)
            self.assertEqual(saved["sources"]["crossref"]["min_request_interval_seconds"], 0.5)
            self.assertEqual(saved["sources"]["crossref"]["future_crossref_option"], "keep me")

    def test_settings_save_requires_openalex_api_key_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["sources"]["openalex"]["enabled"] = True
            payload["sources"]["openalex"]["api_key"] = ""

            response = save_settings(config_path, payload)

        self.assertIn("error", response)
        self.assertIn("sources.openalex.api_key", response["error"])

    def test_openalex_settings_roundtrip_preserves_api_options(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["sources"]["openalex"].update(
                {
                    "enabled": True,
                    "days_back": 21,
                    "per_page": 50,
                    "max_pages": 4,
                    "api_key": "openalex-key",
                }
            )

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertEqual(saved["sources"]["openalex"]["days_back"], 21)
        self.assertEqual(saved["sources"]["openalex"]["per_page"], 50)
        self.assertEqual(saved["sources"]["openalex"]["max_pages"], 4)
        self.assertEqual(saved["sources"]["openalex"]["api_key"], "openalex-key")

    def test_custom_crossref_direction_can_leave_openalex_query_empty_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["search_direction"] = {
                "preset": "custom",
                "label": "Crossref only",
                "crossref_query": "solid electrolyte",
                "openalex_query": "",
                "query_manually_edited": True,
            }
            payload["sources"]["openalex"]["enabled"] = False
            payload["sources"]["openalex"]["query"] = ""

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertEqual(saved["search_direction"]["openalex_query"], "")
        self.assertEqual(saved["sources"]["openalex"]["query"], "")

    def test_crossref_pool_limits_follow_mailto_configuration(self):
        public_config = {"max_workers": 3, "mailto": ""}
        polite_config = {"max_workers": 6, "mailto": "alerts@example.org"}

        self.assertEqual(sources._crossref_effective_max_workers(public_config, 3), 1)
        self.assertEqual(sources._crossref_effective_max_workers(polite_config, 6), 3)
        self.assertEqual(sources._crossref_min_request_interval_seconds({"mailto": "", "min_request_interval_seconds": 0}), 0.0)
        self.assertGreaterEqual(sources._crossref_min_request_interval_seconds(public_config), 1.0)
        self.assertLess(sources._crossref_min_request_interval_seconds(polite_config), 1.0)

    def test_config_example_tracks_crossref_rate_limit_contract(self):
        example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

        self.assertIn("retry_count", DEFAULT_CONFIG["sources"]["crossref"])
        self.assertIn("retry_count", example["sources"]["crossref"])
        self.assertIn("min_request_interval_seconds", DEFAULT_CONFIG["sources"]["crossref"])
        self.assertIn("min_request_interval_seconds", example["sources"]["crossref"])
        self.assertIn("max_pages", DEFAULT_CONFIG["sources"]["openalex"])
        self.assertIn("max_pages", example["sources"]["openalex"])

    def test_config_schema_covers_crossref_rate_limit_contract(self):
        schema = json.loads(Path("docs/config.schema.json").read_text(encoding="utf-8"))
        crossref = schema["properties"]["sources"]["properties"]["crossref"]["properties"]
        openalex = schema["properties"]["sources"]["properties"]["openalex"]["properties"]

        self.assertIn("retry_count", crossref)
        self.assertIn("min_request_interval_seconds", crossref)
        self.assertEqual(crossref["retry_count"]["minimum"], 0)
        self.assertEqual(crossref["min_request_interval_seconds"]["minimum"], 0)
        self.assertIn("max_pages", openalex)
        self.assertEqual(openalex["max_pages"]["maximum"], 50)

    def test_windows_packaging_includes_runtime_resource_directories(self):
        script = Path("scripts/build_windows_app.ps1").read_text(encoding="utf-8")

        for resource in ("paper_monitor\\templates", "paper_monitor\\static", "paper_monitor\\resources"):
            self.assertIn(resource, script)

        self.assertIn('"_sqlite3"', script)
        self.assertIn('"unicodedata"', script)
        self.assertIn('"--collect-data"', script)
        self.assertIn('"--collect-binaries"', script)
        self.assertIn('"--collect-submodules"', script)
        self.assertIn('($WebViewLib + ";webview\\lib")', script)
        self.assertIn("Test-OnedirWebViewRuntime", script)
        self.assertIn("Test-OnefileWebViewRuntime", script)
        self.assertIn("win-arm64\\native\\WebView2Loader.dll", script)
        self.assertIn("win-x64\\native\\WebView2Loader.dll", script)
        self.assertIn("win-x86\\native\\WebView2Loader.dll", script)
        self.assertIn("generate_windows_version_info.py", script)
        self.assertIn('"--version-file"', script)
        self.assertIn('".venv\\Scripts\\python.exe"', script)
        self.assertLess(script.index('@("python")'), script.index('@("py", "-3")'))

    def test_windows_version_info_supports_timestamp_release_versions(self):
        self.assertEqual(numeric_version("20260710-055055"), (2026, 7, 10, 550))
        with self.assertRaises(ValueError):
            numeric_version("../unsafe-version")
        rendered = render_version_info("20260710-055055")
        self.assertIn("filevers=(2026, 7, 10, 550)", rendered)
        self.assertIn("ProductVersion', '20260710-055055'", rendered)
        self.assertIn("OriginalFilename', 'PaperMonitor.exe'", rendered)

    def test_arxiv_days_back_filters_old_entries_with_clear_dates(self):
        new_date = (date.today() - timedelta(days=1)).isoformat()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>New solid electrolyte paper</title>
    <id>https://arxiv.org/abs/2607.00001</id>
    <link href="https://arxiv.org/abs/2607.00001" />
    <published>{new_date}T00:00:00Z</published>
    <updated>{new_date}T00:00:00Z</updated>
    <summary>Fresh result.</summary>
    <author><name>A. Researcher</name></author>
  </entry>
  <entry>
    <title>Old solid electrolyte paper</title>
    <id>https://arxiv.org/abs/2606.00001</id>
    <link href="https://arxiv.org/abs/2606.00001" />
    <published>{old_date}T00:00:00Z</published>
    <updated>{old_date}T00:00:00Z</updated>
    <summary>Old result.</summary>
    <author><name>B. Researcher</name></author>
  </entry>
</feed>"""

        articles = sources.fetch_arxiv(
            {"query": "solid electrolyte", "days_back": 7, "max_results": 10},
            fetch=lambda _url: feed.encode("utf-8"),
        )

        self.assertEqual([article.title for article in articles], ["New solid electrolyte paper"])

    def test_openalex_enabled_without_api_key_is_skipped_before_request(self):
        config = {
            "rss": [],
            "crossref": {"enabled": False},
            "openalex": {
                "enabled": True,
                "days_back": 1,
                "per_page": 1,
                "query": "solid electrolyte",
                "api_key": "",
            },
            "arxiv": {"enabled": False},
        }

        with patch("paper_monitor.sources.fetch_url") as fetch_url, patch("paper_monitor.sources._warn") as warn:
            self.assertEqual(fetch_all_sources(config), [])

        fetch_url.assert_not_called()
        self.assertIn("sources.openalex.api_key", warn.call_args[0][0])

    def test_openalex_url_caps_per_page_and_supports_date_to(self):
        url = sources.build_openalex_url(
            {
                "query": "solid electrolyte",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
                "per_page": 999,
                "api_key": "openalex-test-key",
            }
        )

        self.assertIn("per_page=200", url)
        self.assertIn("from_publication_date%3A2026-06-01", url)
        self.assertIn("to_publication_date%3A2026-06-30", url)
        self.assertIn("api_key=openalex-test-key", url)
        self.assertIn("select=id%2Cdisplay_name", url)
        self.assertIn("authorships", url)

    def test_openalex_fetch_supports_cursor_pages(self):
        seen_urls = []
        responses = [
            {
                "meta": {"next_cursor": "cursor-2"},
                "results": [{"id": "https://openalex.org/W1", "display_name": "First paper"}],
            },
            {
                "meta": {"next_cursor": None},
                "results": [{"id": "https://openalex.org/W2", "display_name": "Second paper"}],
            },
        ]

        def fake_fetch(url):
            seen_urls.append(url)
            return json.dumps(responses.pop(0)).encode("utf-8")

        articles = sources.fetch_openalex(
            {
                "query": "solid electrolyte OR LLZO",
                "api_key": "openalex-key",
                "per_page": 1,
                "max_pages": 2,
            },
            fetch=fake_fetch,
        )

        self.assertEqual([article.title for article in articles], ["First paper", "Second paper"])
        self.assertIn("cursor=%2A", seen_urls[0])
        self.assertIn("cursor=cursor-2", seen_urls[1])

    def test_openalex_parser_maps_authors_and_abstract(self):
        payload = {
            "results": [
                {
                    "display_name": "Solid electrolyte interfaces",
                    "doi": "https://doi.org/10.1234/example",
                    "publication_date": "2026-07-01",
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "Nature Energy"},
                    },
                    "abstract_inverted_index": {"Solid": [0], "electrolyte": [1], "interfaces": [2]},
                    "authorships": [
                        {"author": {"display_name": "Ada Lovelace"}},
                        {"author": {"display_name": "Ada Lovelace"}},
                        {"author": {"display_name": "Grace Hopper"}},
                    ],
                },
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "OpenAlex-only paper",
                    "publication_date": "2026-07-02",
                }
            ]
        }

        articles = sources.parse_openalex_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].journal, "Nature Energy")
        self.assertEqual(articles[0].doi, "10.1234/example")
        self.assertEqual(articles[0].abstract, "Solid electrolyte interfaces")
        self.assertEqual(articles[0].authors, ("Ada Lovelace", "Grace Hopper"))
        self.assertEqual(articles[1].url, "https://openalex.org/W123")

    def test_date_window_prefers_explicit_dates(self):
        window = sources._date_window_from_config(
            {"days_back": 30, "date_from": "2026-06-01", "date_to": "2026-06-10"},
            default_days_back=3,
            today=date(2026, 7, 8),
        )
        fallback = sources._date_window_from_config({}, default_days_back=7, today=date(2026, 7, 8))

        self.assertEqual(window.date_from, "2026-06-01")
        self.assertEqual(window.date_to, "2026-06-10")
        self.assertEqual(fallback.date_from, "2026-07-01")
        self.assertEqual(fallback.date_to, "")

    def test_journal_alias_and_keyword_boundaries(self):
        config = FilterConfig(
            include_terms=["solid electrolyte"],
            exclude_terms=[],
            journals=["Nature Energy"],
            journal_aliases={"Nature Energy": ["Nat Energy"]},
        )
        article = Article(
            title="A solid electrolyte paper",
            journal="Nat Energy",
            url="https://example.org",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )

        self.assertTrue(match_article(article, config).matched)

        short_term_config = FilterConfig(include_terms=["ion"], exclude_terms=[], journals=[])
        false_positive = Article(
            title="Interfacial polarization in batteries",
            journal="Nature Energy",
            url="https://example.org/2",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )
        phrase_match = Article(
            title="Solid electrolyte enables fast cycling",
            journal="Nature Energy",
            url="https://example.org/3",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )

        self.assertFalse(match_article(false_positive, short_term_config).matched)
        self.assertTrue(match_article(phrase_match, FilterConfig(["solid electrolyte"], [], [])).matched)


if __name__ == "__main__":
    unittest.main()
