import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch


class FakeWinReg:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1

    def __init__(self):
        self.values = []
        self.deleted = []
        self.opened = []

    def OpenKey(self, root, path, reserved, access):
        self.opened.append((root, path, reserved, access))
        return self

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values.append((name, reserved, value_type, value))

    def DeleteValue(self, key, name):
        self.deleted.append(name)

    def CloseKey(self, key):
        pass


class WindowsTrayTests(unittest.TestCase):
    def test_default_windows_app_dir_uses_appdata(self):
        from paper_monitor.windows_tray import default_windows_app_dir

        env = {"APPDATA": r"C:\Users\Example\AppData\Roaming"}

        self.assertEqual(
            default_windows_app_dir(env=env),
            PureWindowsPath(r"C:\Users\Example\AppData\Roaming\PaperMonitor"),
        )

    def test_builds_refresh_command_for_existing_app_refresh_entrypoint(self):
        from paper_monitor.windows_tray import build_refresh_command

        command = build_refresh_command(
            python_executable=PureWindowsPath(r"C:\Python313\python.exe"),
            config_path=PureWindowsPath(r"C:\Users\Example\AppData\Roaming\PaperMonitor\config.json"),
        )

        self.assertEqual(
            command,
            [
                r"C:\Python313\python.exe",
                "-m",
                "paper_monitor.cli",
                "app-refresh",
                "--config",
                r"C:\Users\Example\AppData\Roaming\PaperMonitor\config.json",
            ],
        )

    def test_notification_target_prefers_article_url_then_doi_then_dashboard(self):
        from paper_monitor.windows_tray import notification_target

        dashboard = Path("/tmp/paper-monitor/latest.html")

        self.assertEqual(
            notification_target({"url": "https://example.org/article", "doi": "10.1000/example"}, dashboard),
            "https://example.org/article",
        )
        self.assertEqual(
            notification_target({"url": "", "doi": "10.1000/example"}, dashboard),
            "https://doi.org/10.1000/example",
        )
        self.assertTrue(notification_target({"url": "", "doi": ""}, dashboard).startswith("file://"))

    def test_windows_toast_notifier_passes_click_target_to_win11toast(self):
        from paper_monitor.windows_tray import WindowsToastNotifier

        calls = []
        fake_module = types.SimpleNamespace(
            notify=lambda title, body, **kwargs: calls.append((title, body, kwargs))
        )
        original = sys.modules.get("win11toast")
        sys.modules["win11toast"] = fake_module
        try:
            delivered = WindowsToastNotifier().notify_article(
                {"title": "Solid electrolyte breakthrough", "journal": "Nature Energy", "url": "https://example.org/a"},
                Path("/tmp/latest.html"),
            )
        finally:
            if original is None:
                sys.modules.pop("win11toast", None)
            else:
                sys.modules["win11toast"] = original

        self.assertTrue(delivered)
        self.assertEqual(calls[0][2]["on_click"], "https://example.org/a")
        self.assertNotIn("app_id", calls[0][2])

    def test_startup_registry_value_quotes_executable_and_uses_quiet_flag(self):
        from paper_monitor.windows_tray import build_startup_registry_value

        self.assertEqual(
            build_startup_registry_value(PureWindowsPath(r"C:\Program Files\PaperMonitor\PaperMonitor.exe")),
            r'"C:\Program Files\PaperMonitor\PaperMonitor.exe" tray --quiet',
        )

    def test_set_startup_enabled_writes_current_user_run_key(self):
        from paper_monitor.windows_tray import set_startup_enabled

        fake = FakeWinReg()

        set_startup_enabled(
            True,
            PureWindowsPath(r"C:\Apps\PaperMonitor.exe"),
            registry_module=fake,
        )

        self.assertEqual(
            fake.opened[0][1],
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        self.assertEqual(
            fake.values,
            [
                (
                    "Paper Monitor",
                    0,
                    fake.REG_SZ,
                    r'"C:\Apps\PaperMonitor.exe" tray --quiet',
                )
            ],
        )

    def test_set_startup_disabled_deletes_current_user_run_key(self):
        from paper_monitor.windows_tray import set_startup_enabled

        fake = FakeWinReg()

        set_startup_enabled(False, PureWindowsPath(r"C:\Apps\PaperMonitor.exe"), registry_module=fake)

        self.assertEqual(fake.deleted, ["Paper Monitor"])

    def test_windows_launcher_is_quiet_entrypoint(self):
        launcher = Path("windows/PaperMonitor.pyw").read_text(encoding="utf-8")

        self.assertIn("windows_background", launcher)
        self.assertIn("windows_tray", launcher)
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
                "paper_monitor/windows_tray.py",
                "paper_monitor/cli.py",
                "windows/PaperMonitor.pyw",
                "windows/assets/PaperMonitor.ico",
                "scripts/build_windows_app.ps1",
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
        windows_project = Path("windows_project/PaperMonitorWindows").resolve()
        original_path = list(sys.path)
        removed_modules = {
            name: module
            for name, module in list(sys.modules.items())
            if name == "paper_monitor" or name.startswith("paper_monitor.")
        }
        for name in removed_modules:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(windows_project))
        try:
            cli = importlib.import_module("paper_monitor.cli")
            config_module = importlib.import_module("paper_monitor.config")
            storage_module = importlib.import_module("paper_monitor.storage")
            models_module = importlib.import_module("paper_monitor.models")

            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.json"
                config_module.write_default_config(config_path)
                app_config = config_module.load_app_config(config_path)
                store = storage_module.ArticleStore(app_config.database_path)
                run_id = store.start_run()
                store.record_candidate(
                    run_id,
                    models_module.Article(
                        title="Solid electrolyte dashboard article",
                        journal="Nature Energy",
                        url="https://example.org/dashboard-article",
                        doi="10.1000/dashboard",
                        published="2026-06-24",
                        abstract="Halide electrolyte interface.",
                        source="fixture",
                    ),
                    matched=True,
                    reason="matched",
                    matched_terms=["solid electrolyte"],
                    journal_match="Nature Energy",
                )
                store.finish_run(run_id, fetched=1, matched=1, new_matches=1, skipped=0)

                with patch.object(cli.webbrowser, "open") as open_dashboard:
                    result = cli._open_dashboard(config_path)

                self.assertEqual(result, 0)
                open_dashboard.assert_called_once()
                self.assertTrue(open_dashboard.call_args.args[0].startswith("file://"))
                dashboard_html = app_config.dashboard_path.read_text(encoding="utf-8")
                self.assertIn('id="keyword-analysis-nav"', dashboard_html)
                self.assertIn(">Keyword Analysis</button>", dashboard_html)
        finally:
            sys.path[:] = original_path
            for name in list(sys.modules):
                if name == "paper_monitor" or name.startswith("paper_monitor."):
                    sys.modules.pop(name, None)
            sys.modules.update(removed_modules)


if __name__ == "__main__":
    unittest.main()
