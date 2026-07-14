import copy
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch


class WindowsAppTests(unittest.TestCase):
    def test_silent_startup_only_launches_tray_when_setting_is_enabled(self):
        from paper_monitor import windows_app, windows_native_tray
        from paper_monitor.config import DEFAULT_CONFIG

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = copy.deepcopy(DEFAULT_CONFIG)
            payload["app_settings"]["launch_at_login"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with patch.object(windows_native_tray, "ensure_native_tray") as ensure_tray:
                status = windows_app.main(
                    ["silent-startup", "--config", str(config_path)]
                )

            self.assertEqual(status, 0)
            ensure_tray.assert_called_once_with(config_path)

            payload["app_settings"]["launch_at_login"] = False
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(windows_native_tray, "ensure_native_tray") as ensure_tray:
                status = windows_app.main(
                    ["silent-startup", "--config", str(config_path)]
                )

            self.assertEqual(status, 0)
            ensure_tray.assert_not_called()

    def test_default_windows_app_dir_uses_appdata(self):
        from paper_monitor.windows_app import default_windows_app_dir

        env = {"APPDATA": r"C:\Users\Example\AppData\Roaming"}

        self.assertEqual(
            default_windows_app_dir(env=env),
            PureWindowsPath(r"C:\Users\Example\AppData\Roaming\PaperMonitor"),
        )

    def test_windows_launcher_is_quiet_entrypoint(self):
        launcher = Path("windows/PaperMonitor.pyw").read_text(encoding="utf-8")

        self.assertIn("windows_background", launcher)
        self.assertIn("windows_app", launcher)
        self.assertIn("main(", launcher)
        self.assertNotIn("open-dashboard", launcher)

    def test_windows_build_and_install_scripts_use_no_console_and_startup_registration(self):
        build_script = Path("scripts/build_windows_app.ps1").read_text(encoding="utf-8")
        install_script = Path("scripts/install_windows_app.ps1").read_text(encoding="utf-8")

        self.assertIn("--noconsole", build_script)
        self.assertIn("PyInstaller", build_script)
        self.assertIn("PaperMonitor.pyw", build_script)
        self.assertIn("install-startup", install_script)
        self.assertIn("$env:APPDATA", install_script)

    def test_prepare_windows_project_creates_copyable_windows_only_folder(self):
        from scripts.prepare_windows_project import prepare_windows_project

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "PaperMonitorWindows"

            prepare_windows_project(target)

            expected_files = [
                "README_WINDOWS.md",
                "requirements-windows.txt",
                "requirements-windows.lock.txt",
                "config.example.json",
                "journal_metrics.json",
                "paper_monitor/windows_app.py",
                "paper_monitor/cli.py",
                "windows/PaperMonitor.pyw",
                "windows/assets/PaperMonitor.ico",
                "scripts/build_windows_app.ps1",
                "scripts/build_windows_native_tray.ps1",
                "scripts/install_windows_app.ps1",
                "scripts/generate_windows_icon.py",
                "scripts/generate_app_icons.py",
                "scripts/generate_windows_version_info.py",
                "scripts/package_windows_release.ps1",
            ]
            for relative_path in expected_files:
                self.assertTrue((target / relative_path).exists(), relative_path)

            copied_paths = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
            self.assertFalse(any(path.startswith("macos/") for path in copied_paths))
            self.assertFalse(any("__pycache__" in path for path in copied_paths))
            self.assertFalse(any(path.endswith(".DS_Store") for path in copied_paths))
            self.assertEqual(
                (target / "README_WINDOWS.md").read_text(encoding="utf-8"),
                Path("README_WINDOWS.md").read_text(encoding="utf-8"),
            )

    def test_prepare_windows_project_rejects_repository_target(self):
        from scripts.prepare_windows_project import ROOT, prepare_windows_project

        with self.assertRaisesRegex(ValueError, "must not be the repository"):
            prepare_windows_project(ROOT)

    def test_windows_cli_open_dashboard_uses_cross_platform_webbrowser(self):
        from paper_monitor import cli
        from paper_monitor.article_lifecycle import (
            ArticleDetection,
            ArticleLifecycle,
            RefreshCommit,
            RefreshRunStatus,
        )
        from paper_monitor.config import load_app_config, write_default_config

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            app_config = load_app_config(config_path)
            ArticleLifecycle(app_config.database_path).commit_refresh(
                RefreshCommit(
                    run_id="windows-dashboard-test",
                    status=RefreshRunStatus.SUCCEEDED,
                    detections=(
                        ArticleDetection(
                            title="Solid electrolyte dashboard article",
                            authors=("Ada Lovelace",),
                            journal="Nature Energy",
                            impact_reference=21.1,
                            url="https://example.org/dashboard-article",
                            doi="10.1000/dashboard",
                            published="2026-06-24",
                            source="fixture",
                        ),
                    ),
                    fetched=1,
                    matched=1,
                )
            )

            with patch.object(cli.webbrowser, "open") as open_dashboard:
                result = cli._open_dashboard(config_path)

            self.assertEqual(result, 0)
            open_dashboard.assert_called_once()
            self.assertTrue(open_dashboard.call_args.args[0].startswith("file://"))
            dashboard_html = app_config.dashboard_path.read_text(encoding="utf-8")
            self.assertIn('id="keyword-analysis-nav"', dashboard_html)
            self.assertIn(">Keyword Analysis</button>", dashboard_html)


if __name__ == "__main__":
    unittest.main()
