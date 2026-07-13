import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import app_refresh, windows_app, windows_app_window
from paper_monitor.config import write_default_config
from paper_monitor.models import Article
from paper_monitor.refresh_status import begin_refresh, finish_refresh, read_refresh_status, refresh_status_path
from paper_monitor.sources import SourceFetchError, SourceFetchResult


class RefreshStatusTests(unittest.TestCase):
    def test_status_transitions_are_atomic_and_owner_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            begin_refresh(
                config_path,
                request_id="request-one",
                reason="manual_refresh",
                owner_id="owner-one",
            )

            self.assertFalse(
                finish_refresh(
                    config_path,
                    request_id="request-one",
                    owner_id="owner-two",
                    status="failed",
                    error="not the owner",
                )
            )
            running = read_refresh_status(config_path)
            self.assertEqual(running["status"], "running")
            self.assertTrue(
                finish_refresh(
                    config_path,
                    request_id="request-one",
                    owner_id="owner-one",
                    status="partial",
                    result={"fetched": 3, "partial": True},
                    error="one source failed",
                )
            )
            completed = read_refresh_status(config_path)

            self.assertEqual(completed["status"], "partial")
            self.assertEqual(completed["reason"], "manual_refresh")
            self.assertEqual(completed["result"]["fetched"], 3)
            self.assertTrue(completed["started_at"])
            self.assertTrue(completed["finished_at"])
            self.assertEqual(list(Path(directory).glob(".refresh-status.json.*.tmp")), [])

    def test_app_refresh_publishes_success_partial_and_failure(self):
        cases = (
            ({"fetched": 1, "matched": 1, "new_matches": 1, "partial": False}, None, "succeeded"),
            ({"fetched": 1, "matched": 1, "new_matches": 1, "partial": True}, None, "partial"),
            (None, RuntimeError("network unavailable"), "failed"),
        )
        for index, (result, error, expected_status) in enumerate(cases):
            with self.subTest(expected_status=expected_status), tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "config.json"
                effect = error if error is not None else result
                with patch("paper_monitor.app_refresh.acquire_mutex", return_value=object()):
                    with patch("paper_monitor.app_refresh.close_handle"):
                        with patch("paper_monitor.app_refresh._run_app_refresh", side_effect=[effect]):
                            if error is None:
                                returned = app_refresh.run_app_refresh(
                                    config_path,
                                    request_id=f"request-{index}",
                                    reason="test",
                                )
                                self.assertEqual(returned["status"], expected_status)
                            else:
                                with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                                    app_refresh.run_app_refresh(
                                        config_path,
                                        request_id=f"request-{index}",
                                        reason="test",
                                    )
                state = read_refresh_status(config_path)
                self.assertEqual(state["status"], expected_status)
                self.assertEqual(state["request_id"], f"request-{index}")
                self.assertEqual(state["reason"], "test")
                if error is not None:
                    self.assertIn("network unavailable", state["error"])

    def test_concurrent_rejection_does_not_replace_owner_status(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            begin_refresh(config_path, request_id="active", reason="scheduled", owner_id="owner")
            with patch("paper_monitor.app_refresh.acquire_mutex", return_value=None):
                with self.assertRaises(app_refresh.RefreshAlreadyRunning) as raised:
                    app_refresh.run_app_refresh(config_path, request_id="rejected")

            state = read_refresh_status(config_path)
            self.assertEqual(state["request_id"], "active")
            self.assertEqual(raised.exception.state["request_id"], "active")

    def test_source_diagnostics_drive_partial_and_failed_terminal_states(self):
        article = Article(
            title="Solid electrolyte interface",
            journal="Nature Energy",
            url="https://example.org/paper",
            doi="10.1000/refresh-status",
            published="2026-07-12",
            abstract="Solid-state battery electrolyte.",
            source="fixture",
        )
        partial_statuses = [
            {"source": "RSS", "target": "Journal", "status": "succeeded", "count": 1, "error": ""},
            {"source": "Crossref", "target": "", "status": "failed", "count": 0, "error": "timeout"},
        ]
        failed_statuses = [
            {"source": "RSS", "target": "Journal", "status": "failed", "count": 0, "error": "offline"},
            {"source": "Crossref", "target": "", "status": "failed", "count": 0, "error": "timeout"},
        ]

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            write_default_config(config_path)
            partial = app_refresh.run_app_refresh(
                config_path,
                fetch_articles=lambda: SourceFetchResult([article], partial_statuses),
                request_id="partial-request",
            )
            partial_state = read_refresh_status(config_path)

            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial_state["status"], "partial")
            self.assertIn("Crossref: timeout", partial_state["error"])

            with self.assertRaises(SourceFetchError):
                app_refresh.run_app_refresh(
                    config_path,
                    fetch_articles=lambda: SourceFetchResult([], failed_statuses),
                    request_id="failed-request",
                )
            failed_state = read_refresh_status(config_path)

        self.assertEqual(failed_state["status"], "failed")
        self.assertEqual(failed_state["result"]["source_statuses"], failed_statuses)
        self.assertIn("offline", failed_state["error"])


class WindowControlSafetyTests(unittest.TestCase):
    def test_window_keeps_desktop_default_with_smaller_supported_minimum(self):
        self.assertEqual((windows_app_window.DEFAULT_WIDTH, windows_app_window.DEFAULT_HEIGHT), (1180, 760))
        self.assertEqual(windows_app_window.DEFAULT_MIN_SIZE, (720, 520))

    def test_refresh_complete_guards_settings_and_preserves_analysis_view(self):
        scripts = []
        window = type("Window", (), {"evaluate_js": lambda _self, script: scripts.append(script)})()
        handler = windows_app_window._window_control_handler(window, "http://127.0.0.1:1234")

        self.assertEqual(handler({"action": "refresh-complete"}), {"ok": True})
        deadline = time.monotonic() + 1
        while not scripts and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(len(scripts), 1)
        self.assertIn("window.location.pathname", scripts[0])
        self.assertIn("'/settings'", scripts[0])
        self.assertIn("paperMonitor.refreshView.v1", scripts[0])
        self.assertIn("window.location.replace", scripts[0])

    def test_failed_deferred_close_clears_request_and_allows_retry(self):
        class FlakyWindow:
            def __init__(self):
                self.calls = 0

            def destroy(self):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("close failed")

        window = FlakyWindow()
        close_requested = threading.Event()
        handler = windows_app_window._window_control_handler(window, "http://127.0.0.1:1234", close_requested)

        self.assertEqual(handler({"action": "close"}), {"ok": True})
        deadline = time.monotonic() + 1
        while close_requested.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(close_requested.is_set())

        self.assertEqual(handler({"action": "close"}), {"ok": True})
        deadline = time.monotonic() + 1
        while window.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(window.calls, 2)

    def test_deferred_callback_errors_are_contained(self):
        handled = threading.Event()

        def fail():
            raise RuntimeError("timer callback failed")

        self.assertTrue(windows_app_window._defer_window_call(fail, on_error=handled.set))
        self.assertTrue(handled.wait(timeout=1))


class FrozenSmokeTests(unittest.TestCase):
    def test_self_test_reads_bundled_resources_without_user_app_setup(self):
        with patch("paper_monitor.windows_app.ensure_windows_app_files") as ensure_files:
            self.assertEqual(windows_app.main(["self-test"]), 0)
        ensure_files.assert_not_called()
        self.assertFalse(refresh_status_path(Path("config.json")).name.startswith("."))


if __name__ == "__main__":
    unittest.main()
