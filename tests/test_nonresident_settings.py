import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_monitor import windows_runtime_settings

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class NonResidentSettingsContractTests(unittest.TestCase):
    def test_settings_describe_short_lived_background_monitoring(self):
        html = read_text("paper_monitor/templates/windows/settings.html")
        css = read_text("paper_monitor/static/windows/settings.css")

        self.assertIn("Background Monitoring", html)
        self.assertIn("Run short scheduled refresh tasks without keeping Paper Monitor in memory", html)
        self.assertIn('id="startup_enabled"', html)
        self.assertEqual(html.count("hidden data-legacy-resident-setting"), 3)
        self.assertIn("[hidden]", css)
        self.assertIn("display: none !important", css)

    def test_hidden_resident_values_are_preserved_by_settings_javascript(self):
        javascript = read_text("paper_monitor/static/windows/settings.js")

        self.assertIn("let legacyResidentSettings = {", javascript)
        self.assertIn("fillForm(payload, true)", javascript)
        self.assertIn("show_tray_icon: legacyResidentSettings.show_tray_icon", javascript)
        self.assertIn(
            "silent_startup_notifications: legacyResidentSettings.silent_startup_notifications",
            javascript,
        )
        self.assertIn("refresh_on_launch: legacyResidentSettings.refresh_on_launch", javascript)

    def test_installer_removes_legacy_login_startup(self):
        installer = read_text("windows/PaperMonitor.iss")

        self.assertNotIn('Name: "startup"', installer)
        self.assertNotIn("ValueData:", installer)
        self.assertNotIn("if CurStep = ssInstall", installer)
        self.assertEqual(installer.count("RegDeleteValue(HKCU"), 1)
        self.assertIn("[UninstallRun]", installer)
        self.assertIn('Parameters: "uninstall-startup"', installer)
        self.assertIn("RemoveScheduledRefreshTask", installer)
        self.assertIn('\\PaperMonitor Scheduled Refresh" /F', installer)

    def test_documentation_promises_no_resident_windows_process(self):
        windows_readme = read_text("README_WINDOWS.md")
        chinese_readme = read_text("README.zh-CN.md")

        self.assertIn("consumes no background memory between scans", windows_readme)
        self.assertIn("两次检索之间没有 Paper Monitor 进程常驻内存", chinese_readme)


class RuntimeScheduleSettingsTests(unittest.TestCase):
    def test_runtime_settings_replace_login_startup_with_scheduled_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            executable = Path(directory) / "PaperMonitor.exe"
            config_path.write_text(
                json.dumps(
                    {
                        "interval_seconds": 12 * 60 * 60,
                        "refresh_start_time": "09:30",
                        "app_settings": {"startup_enabled": True},
                    }
                ),
                encoding="utf-8-sig",
            )
            scheduler = types.ModuleType("paper_monitor.windows_scheduled_task")
            scheduler.sync_scheduled_refresh = Mock()

            with (
                patch.dict(sys.modules, {scheduler.__name__: scheduler}),
                patch("paper_monitor.windows_tray.set_startup_enabled") as legacy_startup,
                patch.object(windows_runtime_settings, "os", types.SimpleNamespace(name="nt")),
            ):
                windows_runtime_settings.sync_windows_runtime_settings(config_path, executable)

            legacy_startup.assert_called_once_with(False, executable.resolve())
            scheduler.sync_scheduled_refresh.assert_called_once_with(
                config_path.resolve(),
                True,
                12,
                "09:30",
                executable=executable.resolve(),
            )

    def test_interval_rounds_up_to_supported_whole_hours(self):
        self.assertEqual(windows_runtime_settings._interval_hours({"interval_seconds": 60}), 1)
        self.assertEqual(windows_runtime_settings._interval_hours({"interval_seconds": 9001}), 3)
        self.assertEqual(
            windows_runtime_settings._interval_hours({"interval_seconds": 10**12}),
            24 * 30,
        )

    def test_unreadable_or_malformed_config_never_removes_existing_task(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            scheduler = types.ModuleType("paper_monitor.windows_scheduled_task")
            scheduler.sync_scheduled_refresh = Mock()

            with (
                patch.dict(sys.modules, {scheduler.__name__: scheduler}),
                patch("paper_monitor.windows_tray.set_startup_enabled") as legacy_startup,
                patch.object(windows_runtime_settings, "os", types.SimpleNamespace(name="nt")),
            ):
                with self.assertRaises(RuntimeError):
                    windows_runtime_settings.sync_windows_runtime_settings(config_path)

                config_path.write_text("{broken", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    windows_runtime_settings.sync_windows_runtime_settings(config_path)

            scheduler.sync_scheduled_refresh.assert_not_called()
            legacy_startup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
