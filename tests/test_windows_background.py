import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor.article_lifecycle import RefreshRunStatus
from paper_monitor.refresh_execution import RefreshIntent
from paper_monitor.windows_background import main, run_background_refresh


def outcome(
    status=RefreshRunStatus.SUCCEEDED,
    *,
    notification=None,
    error="",
):
    return SimpleNamespace(status=status, notification=notification, error=error)


class WindowsBackgroundTests(unittest.TestCase):
    def execution_factory(self, result):
        execution = Mock()
        execution.execute.return_value = result
        return Mock(return_value=execution), execution

    def test_runs_exactly_one_background_refresh_and_accepts_partial_results(self):
        factory, execution = self.execution_factory(outcome(RefreshRunStatus.PARTIAL))
        config_path = Path("config.json")

        status = run_background_refresh(config_path, execution_factory=factory)

        self.assertEqual(status, 0)
        factory.assert_called_once_with(config_path)
        execution.execute.assert_called_once_with(RefreshIntent.BACKGROUND)

    def test_failed_refresh_returns_nonzero_and_is_logged(self):
        factory, _execution = self.execution_factory(
            outcome(RefreshRunStatus.FAILED, error="all sources offline")
        )
        config_path = Path("config.json")

        with (
            patch("paper_monitor.windows_background._log_background_error") as log_error,
            patch("paper_monitor.windows_background._write_stderr"),
        ):
            status = run_background_refresh(config_path, execution_factory=factory)

        self.assertEqual(status, 1)
        self.assertIn("all sources offline", str(log_error.call_args.args[1]))

    def test_clear_notification_rejection_requests_task_scheduler_retry(self):
        for state in ("rejected", "deferred"):
            with self.subTest(state=state):
                notification = SimpleNamespace(state=state, error="notification unavailable")
                factory, _execution = self.execution_factory(
                    outcome(notification=notification)
                )
                with (
                    patch("paper_monitor.windows_background._log_background_error"),
                    patch("paper_monitor.windows_background._write_stderr"),
                ):
                    status = run_background_refresh(
                        Path("config.json"),
                        execution_factory=factory,
                    )

                self.assertEqual(status, 1)

    def test_accepted_or_ambiguous_notification_never_requests_repeat_delivery(self):
        for state in ("accepted", "ambiguous", "not_needed"):
            with self.subTest(state=state):
                factory, _execution = self.execution_factory(
                    outcome(notification=SimpleNamespace(state=state, error=""))
                )

                status = run_background_refresh(
                    Path("config.json"),
                    execution_factory=factory,
                )

                self.assertEqual(status, 0)

    def test_cli_requires_only_config_and_never_imports_tray_or_window(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            with (
                patch(
                    "paper_monitor.windows_background.run_background_refresh",
                    return_value=0,
                ) as run,
                patch("paper_monitor.windows_background._set_windows_app_identity") as identity,
            ):
                status = main(["--config", str(config_path)])

        self.assertEqual(status, 0)
        identity.assert_called_once_with()
        run.assert_called_once_with(config_path)


if __name__ == "__main__":
    unittest.main()
