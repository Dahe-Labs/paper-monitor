import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_monitor import windows_app_window, windows_tray


class _FakeEvent:
    def __init__(self):
        self.callback = None

    def __iadd__(self, callback):
        self.callback = callback
        return self


class NonResidentLifecycleTests(unittest.TestCase):
    def test_closed_window_disposes_only_its_private_webview_process_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            dispose = Mock()
            control = types.SimpleNamespace(
                CoreWebView2=types.SimpleNamespace(BrowserProcessId=4321),
                Dispose=dispose,
            )
            browser = types.SimpleNamespace(webview=control, user_data_folder=directory)
            window = types.SimpleNamespace(native=types.SimpleNamespace(browser=browser))

            with (
                patch("paper_monitor.windows_app_window._terminate_webview2_tree") as terminate,
                patch("paper_monitor.windows_app_window._remove_private_webview_data") as remove_data,
            ):
                windows_app_window._release_webview2_resources(window)

            dispose.assert_called_once_with()
            terminate.assert_called_once_with(4321)
            remove_data.assert_called_once_with(directory)

    def test_legacy_startup_commands_toggle_nonresident_scheduler_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            executable = Path(directory) / "PaperMonitor.exe"
            config_path.write_text(
                json.dumps({"app_settings": {"startup_enabled": False, "future": "keep"}}),
                encoding="utf-8",
            )

            with patch(
                "paper_monitor.windows_runtime_settings.sync_windows_runtime_settings"
            ) as sync:
                windows_tray.set_background_monitoring_enabled(
                    config_path,
                    True,
                    executable_path=executable,
                )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["app_settings"]["startup_enabled"])
            self.assertEqual(saved["app_settings"]["future"], "keep")
            sync.assert_called_once_with(
                config_path.resolve(),
                executable_path=executable.resolve(),
                enabled_override=True,
                cleanup_legacy_startup=False,
            )

    def test_scheduler_failure_does_not_persist_enabled_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                json.dumps({"app_settings": {"startup_enabled": False}}),
                encoding="utf-8",
            )

            with patch(
                "paper_monitor.windows_runtime_settings.sync_windows_runtime_settings",
                side_effect=RuntimeError("task registration failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "task registration failed"):
                    windows_tray.set_background_monitoring_enabled(config_path, True)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["app_settings"]["startup_enabled"])

    def test_normal_window_commands_start_only_native_tray_coordinator(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            for command in ("window", "settings", "run"):
                with self.subTest(command=command):
                    with patch("paper_monitor.windows_tray._is_windows_platform", return_value=False):
                        with patch("paper_monitor.windows_tray.ensure_tray_process_delayed") as ensure_tray:
                            with patch("paper_monitor.windows_native_tray.ensure_native_tray") as ensure_native:
                                with patch("paper_monitor.windows_tray._sync_windows_runtime_settings") as sync:
                                    with patch(
                                        "paper_monitor.windows_app_window.open_dashboard_window",
                                        return_value=0,
                                    ) as open_window:
                                        status = windows_tray.main([command, "--config", str(config_path)])

                    self.assertEqual(status, 0)
                    ensure_tray.assert_not_called()
                    ensure_native.assert_called_once_with(config_path)
                    sync.assert_called_once_with(config_path)
                    expected_path = "/settings" if command == "settings" else "/"
                    open_window.assert_called_once_with(config_path, path=expected_path)

    def test_user_close_is_allowed_and_marks_window_process_closing(self):
        close_requested = threading.Event()

        closing = windows_app_window._close_window_process(close_requested)

        self.assertTrue(closing())
        self.assertTrue(close_requested.is_set())

    def test_dashboard_registers_native_close_to_exit_handler(self):
        class FakeWindow:
            def __init__(self):
                self.events = types.SimpleNamespace(
                    closing=_FakeEvent(),
                    closed=_FakeEvent(),
                    loaded=_FakeEvent(),
                )
                self.hide_calls = 0

            def hide(self):
                self.hide_calls += 1

        class FakeWebview:
            def __init__(self):
                self.window = FakeWindow()
                self.close_allowed = None

            def create_window(self, *_args, **_kwargs):
                return self.window

            def start(self, **_kwargs):
                self.close_allowed = self.window.events.closing.callback()
                self.window.events.closed.callback()

        class FakeServer:
            def __init__(self):
                self.stop_count = 0

            def start(self):
                return "http://127.0.0.1:12345/"

            def stop(self):
                self.stop_count += 1

        fake_webview = FakeWebview()
        fake_server = FakeServer()
        with patch("paper_monitor.windows_app_window._acquire_window_mutex", return_value=object()):
            with patch("paper_monitor.windows_app_window.close_handle"):
                with patch("paper_monitor.windows_app_window.clear_window_control"):
                    with patch("paper_monitor.windows_app_window._load_webview", return_value=fake_webview):
                        status = windows_app_window.open_dashboard_window(
                            Path("config.json"),
                            dashboard_server_factory=lambda _path: fake_server,
                        )

        self.assertEqual(status, 0)
        self.assertTrue(fake_webview.close_allowed)
        self.assertEqual(fake_webview.window.hide_calls, 0)
        self.assertEqual(fake_server.stop_count, 1)

    def test_explicit_tray_command_remains_available(self):
        config_path = Path("config.json")
        with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
            status = windows_tray.main(["tray", "--quiet", "--config", str(config_path)])

        self.assertEqual(status, 0)
        tray_app_class.assert_called_once_with(config_path=config_path)
        tray_app_class.return_value.run.assert_called_once_with(refresh_on_start=True, quiet=True)

    def test_scheduled_refresh_command_does_not_construct_tray(self):
        config_path = Path("config.json")
        with patch("paper_monitor.windows_tray.run_scheduled_refresh", return_value=0) as run_once:
            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                status = windows_tray.main(["scheduled-refresh", "--config", str(config_path)])

        self.assertEqual(status, 0)
        run_once.assert_called_once_with(config_path)
        tray_app_class.assert_not_called()

    def test_installer_runtime_sync_command_does_not_open_window_or_tray(self):
        config_path = Path("config.json")
        with patch(
            "paper_monitor.windows_runtime_settings.sync_windows_runtime_settings"
        ) as sync:
            with patch("paper_monitor.windows_tray.WindowsTrayApp") as tray_app_class:
                with patch(
                    "paper_monitor.windows_app_window.open_dashboard_window"
                ) as open_window:
                    status = windows_tray.main(
                        ["sync-runtime", "--config", str(config_path)]
                    )

        self.assertEqual(status, 0)
        sync.assert_called_once_with(
            config_path,
            executable_path=Path(windows_tray.sys.executable).resolve(),
        )
        tray_app_class.assert_not_called()
        open_window.assert_not_called()

    def test_runtime_settings_sync_failure_is_logged_but_not_raised(self):
        error = RuntimeError("task scheduler unavailable")
        config_path = Path("config.json")
        with patch(
            "paper_monitor.windows_runtime_settings.sync_windows_runtime_settings",
            side_effect=error,
        ):
            with patch("paper_monitor.windows_tray._log_app_error") as log_error:
                windows_tray._sync_windows_runtime_settings(config_path)

        log_error.assert_called_once_with(
            config_path,
            "Could not synchronize Paper Monitor runtime settings",
            error,
        )


if __name__ == "__main__":
    unittest.main()
