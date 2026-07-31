import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import windows_app_window, windows_taskbar
from paper_monitor.app_identity import WINDOWS_APP_USER_MODEL_ID


class _Handle:
    def __init__(self, value):
        self.value = value

    def ToInt64(self):
        return self.value


class _Event:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self


class WindowsTaskbarTests(unittest.TestCase):
    def test_window_configures_taskbar_before_show_and_loaded_only_once(self):
        before_show = _Event()
        loaded = _Event()
        window = SimpleNamespace(
            events=SimpleNamespace(before_show=before_show, loaded=loaded)
        )
        icon_path = Path("PaperMonitor.ico")

        with patch(
            "paper_monitor.windows_taskbar.configure_window_taskbar",
            return_value=True,
        ) as configure:
            windows_app_window._attach_loaded_handler(window, icon_path)
            self.assertIs(before_show.callbacks[0], loaded.callbacks[0])

            before_show.callbacks[0]()
            loaded.callbacks[0]()

        configure.assert_called_once_with(window, icon_path)

    def test_configures_explicit_aumid_and_relaunch_icon_resource(self):
        window = SimpleNamespace(native=SimpleNamespace(Handle=_Handle(1234)))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(windows_taskbar, "_is_windows", return_value=True),
            patch.object(
                windows_taskbar,
                "_set_window_string_properties",
            ) as set_properties,
        ):
            icon_path = Path(directory) / "PaperMonitor.ico"
            icon_path.write_bytes(b"icon")

            configured = windows_taskbar.configure_window_taskbar(
                window,
                icon_path,
            )

        self.assertTrue(configured)
        handle, properties = set_properties.call_args.args
        self.assertEqual(handle, 1234)
        self.assertEqual(
            [(key.pid, value) for key, value in properties],
            [
                (5, WINDOWS_APP_USER_MODEL_ID),
                (3, f"{icon_path.resolve()},0"),
            ],
        )

    def test_onefile_uses_persistent_executable_instead_of_temporary_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen_root = Path(directory) / "_MEI"
            frozen_root.mkdir()
            icon_path = frozen_root / "windows" / "assets" / "PaperMonitor.ico"
            executable = Path(directory) / "PaperMonitor.exe"
            executable.write_bytes(b"exe")
            with (
                patch.object(sys, "_MEIPASS", str(frozen_root), create=True),
                patch.object(sys, "executable", str(executable)),
            ):
                resource = windows_taskbar._taskbar_icon_resource(icon_path)

        self.assertEqual(resource, f"{executable.resolve()},0")

    def test_non_windows_and_missing_native_handle_are_noops(self):
        with patch.object(windows_taskbar, "_is_windows", return_value=False):
            self.assertFalse(
                windows_taskbar.configure_window_taskbar(
                    SimpleNamespace(),
                    Path("PaperMonitor.ico"),
                )
            )

        with patch.object(windows_taskbar, "_is_windows", return_value=True):
            self.assertFalse(
                windows_taskbar.configure_window_taskbar(
                    SimpleNamespace(native=SimpleNamespace()),
                    Path("PaperMonitor.ico"),
                )
            )


if __name__ == "__main__":
    unittest.main()
