import types
import unittest
from unittest.mock import patch

from paper_monitor import windows_refresh_control


class WindowsRefreshControlTests(unittest.TestCase):
    def test_named_event_token_reports_signal_and_closes_handle(self):
        with (
            patch.object(
                windows_refresh_control,
                "os",
                types.SimpleNamespace(name="nt"),
            ),
            patch.object(
                windows_refresh_control,
                "_wait_for_handle",
                return_value=windows_refresh_control.WAIT_OBJECT_0,
            ) as wait,
            patch.object(windows_refresh_control, "_close_handle") as close,
        ):
            token = windows_refresh_control.WindowsRefreshCancellation(handle=42)
            self.assertTrue(token.is_requested())
            token.close()

        wait.assert_called_once_with(42, 0)
        close.assert_called_once_with(42)

    def test_request_refresh_stop_sets_existing_named_event(self):
        with (
            patch.object(
                windows_refresh_control,
                "os",
                types.SimpleNamespace(name="nt"),
            ),
            patch.object(windows_refresh_control, "_open_stop_event", return_value=91),
            patch.object(windows_refresh_control, "_set_event", return_value=True) as set_event,
            patch.object(windows_refresh_control, "_close_handle") as close,
        ):
            self.assertTrue(windows_refresh_control.request_refresh_stop())

        set_event.assert_called_once_with(91)
        close.assert_called_once_with(91)

    def test_request_refresh_stop_is_a_noop_without_active_event(self):
        with (
            patch.object(
                windows_refresh_control,
                "os",
                types.SimpleNamespace(name="nt"),
            ),
            patch.object(windows_refresh_control, "_open_stop_event", return_value=None),
        ):
            self.assertFalse(windows_refresh_control.request_refresh_stop())


if __name__ == "__main__":
    unittest.main()
