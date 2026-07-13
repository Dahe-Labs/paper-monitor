import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import windows_native_tray
from paper_monitor.config import DEFAULT_CONFIG


class WindowsNativeTrayTests(unittest.TestCase):
    def _config_path(self, directory: str, *, visible: bool = True) -> Path:
        payload = copy.deepcopy(DEFAULT_CONFIG)
        payload["app_settings"]["show_tray_icon"] = visible
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_ensure_native_tray_launches_small_adjacent_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._config_path(directory)
            app_path = Path(directory) / "PaperMonitor.exe"
            tray_path = Path(directory) / "PaperMonitorTray.exe"
            app_path.write_bytes(b"app")
            tray_path.write_bytes(b"tray")

            with (
                patch.object(windows_native_tray.os, "name", "nt"),
                patch.object(windows_native_tray, "is_mutex_running", return_value=False),
                patch.object(windows_native_tray.subprocess, "Popen") as popen,
            ):
                started = windows_native_tray.ensure_native_tray(
                    config_path,
                    executable_path=app_path,
                )

        self.assertTrue(started)
        self.assertEqual(
            popen.call_args.args[0],
            [
                str(tray_path.resolve()),
                "--app",
                str(app_path.resolve()),
                "--config",
                str(config_path.resolve()),
            ],
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], str(app_path.resolve().parent))
        self.assertTrue(popen.call_args.kwargs["close_fds"])

    def test_disabled_or_existing_tray_never_spawns(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._config_path(directory, visible=False)
            app_path = Path(directory) / "PaperMonitor.exe"
            (Path(directory) / "PaperMonitorTray.exe").write_bytes(b"tray")

            with (
                patch.object(windows_native_tray.os, "name", "nt"),
                patch.object(windows_native_tray, "is_mutex_running", return_value=False),
                patch.object(windows_native_tray.subprocess, "Popen") as popen,
            ):
                self.assertFalse(
                    windows_native_tray.ensure_native_tray(config_path, executable_path=app_path)
                )
            popen.assert_not_called()

            config_path = self._config_path(directory, visible=True)
            with (
                patch.object(windows_native_tray.os, "name", "nt"),
                patch.object(windows_native_tray, "is_mutex_running", return_value=True),
                patch.object(windows_native_tray.subprocess, "Popen") as popen,
            ):
                self.assertFalse(
                    windows_native_tray.ensure_native_tray(config_path, executable_path=app_path)
                )
            popen.assert_not_called()

    def test_bundled_onefile_tray_is_materialized_to_stable_versioned_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bundle" / "PaperMonitorTray.exe"
            source.parent.mkdir()
            source.write_bytes(b"native-tray-v1")
            config_path = root / "profile" / "config.json"

            first = windows_native_tray._stable_tray_executable(source, config_path)
            second = windows_native_tray._stable_tray_executable(source, config_path)

            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), b"native-tray-v1")
            self.assertEqual(first.parent, config_path.parent / "native")
            self.assertEqual(list(first.parent.glob("*.tmp")), [])

    def test_materialized_tray_repairs_a_corrupt_cached_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bundle" / "PaperMonitorTray.exe"
            source.parent.mkdir()
            source.write_bytes(b"known-good-native-tray")
            config_path = root / "profile" / "config.json"

            cached = windows_native_tray._stable_tray_executable(source, config_path)
            cached.write_bytes(b"corrupt")
            repaired = windows_native_tray._stable_tray_executable(source, config_path)

            self.assertEqual(repaired, cached)
            self.assertEqual(repaired.read_bytes(), source.read_bytes())
            self.assertEqual(list(repaired.parent.glob("*.tmp")), [])

    def test_native_source_owns_only_tray_and_worker_dispatch(self):
        source = Path("windows/native_tray/paper_monitor_tray.c").read_text(encoding="utf-8")
        build = Path("scripts/build_windows_native_tray.ps1").read_text(encoding="utf-8")

        self.assertIn("Shell_NotifyIconW", source)
        self.assertIn("CreateProcessW", source)
        self.assertIn("Local\\\\PaperMonitorTray", source)
        self.assertIn("TaskbarCreated", source)
        self.assertIn('launch_worker(L"scheduled-refresh")', source)
        self.assertNotIn("sqlite", source.casefold())
        self.assertNotIn("http", source.casefold())
        self.assertIn("-Werror", build)
        self.assertIn("-mwindows", build)


if __name__ == "__main__":
    unittest.main()
