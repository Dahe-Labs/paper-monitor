import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor.article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    NotificationDelivery,
    RefreshCommit,
    RefreshRunStatus,
)
from paper_monitor.config import DEFAULT_CONFIG, load_app_config
from paper_monitor.refresh_execution import RefreshIntent
from paper_monitor.windows_background import main, run_background_refresh
from paper_monitor.windows_dashboard_server import WindowsDashboardServer
from paper_monitor.windows_window_control import (
    clear_window_control,
    write_window_control,
)


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

        with patch(
            "paper_monitor.windows_background._notify_open_dashboard"
        ) as notify_dashboard:
            status = run_background_refresh(config_path, execution_factory=factory)

        self.assertEqual(status, 0)
        factory.assert_called_once_with(config_path)
        execution.execute.assert_called_once_with(RefreshIntent.BACKGROUND)
        notify_dashboard.assert_called_once_with(config_path)

    def test_successful_refresh_requests_an_open_dashboard_reload(self):
        factory, _execution = self.execution_factory(outcome())
        config_path = Path("config.json")

        with patch(
            "paper_monitor.windows_window_control.send_window_control"
        ) as send_control:
            status = run_background_refresh(config_path, execution_factory=factory)

        self.assertEqual(status, 0)
        send_control.assert_called_once_with(config_path, "refresh-complete")

    def test_missing_dashboard_window_does_not_fail_a_successful_refresh(self):
        from paper_monitor.windows_window_control import WindowControlError

        factory, _execution = self.execution_factory(outcome())
        with patch(
            "paper_monitor.windows_window_control.send_window_control",
            side_effect=WindowControlError("stale control file"),
        ):
            status = run_background_refresh(
                Path("config.json"),
                execution_factory=factory,
            )

        self.assertEqual(status, 0)

    def test_successful_refresh_reaches_the_authenticated_window_control_channel(self):
        factory, _execution = self.execution_factory(outcome())
        controller = Mock(return_value={"ok": True})
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            server = WindowsDashboardServer(config_path, token="background-sync-token")
            server.set_window_controller(controller)
            server.start()
            write_window_control(
                config_path,
                server.url,
                server.token,
                pid=12345,
            )
            try:
                status = run_background_refresh(
                    config_path,
                    execution_factory=factory,
                )
            finally:
                clear_window_control(config_path)
                server.stop()

        self.assertEqual(status, 0)
        controller.assert_called_once_with({"action": "refresh-complete"})

    def test_notified_background_article_is_on_the_dashboard_first_page(self):
        """Exercise the shared lifecycle seam from background commit through UI render."""

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                json.dumps(DEFAULT_CONFIG, ensure_ascii=False),
                encoding="utf-8",
            )
            app_config = load_app_config(config_path)
            now = [dt.datetime(2026, 7, 30, 12, tzinfo=dt.timezone.utc)]
            lifecycle = ArticleLifecycle(
                app_config.database_path,
                _clock=lambda: now[0],
            )
            lifecycle.commit_refresh(
                RefreshCommit(
                    run_id="older-run",
                    status=RefreshRunStatus.SUCCEEDED,
                    detections=tuple(
                        ArticleDetection(
                            title=f"Older paper {index}",
                            authors=("A. Author",),
                            journal="Nature Energy",
                            impact_reference=20.0,
                            url=f"https://example.org/older/{index}",
                            doi=f"10.1000/older-{index}",
                            source="fixture",
                            source_id=f"older-{index}",
                            published="2026-12-31",
                        )
                        for index in range(60)
                    ),
                    fetched=60,
                    matched=60,
                )
            )
            now[0] = dt.datetime(2026, 7, 31, 3, 48, 27, tzinfo=dt.timezone.utc)
            notified_title = "Background notification paper"
            delivered = []

            class Notifier:
                def deliver(self, notification):
                    delivered.append(notification)
                    return NotificationDelivery.ACCEPTED

            class BackgroundExecution:
                def execute(self, intent):
                    self.intent = intent
                    commit = lifecycle.commit_refresh(
                        RefreshCommit(
                            run_id="background-run",
                            status=RefreshRunStatus.SUCCEEDED,
                            detections=(
                                ArticleDetection(
                                    title=notified_title,
                                    authors=("B. Author",),
                                    journal="Nano Energy",
                                    impact_reference=18.0,
                                    url="https://example.org/notified",
                                    doi="10.1000/notified",
                                    source="fixture",
                                    source_id="notified",
                                    published="2026-07",
                                ),
                            ),
                            fetched=1,
                            matched=1,
                        )
                    )
                    notification = lifecycle.deliver_notification(
                        "background-run",
                        Notifier(),
                    )
                    return SimpleNamespace(
                        status=commit.status,
                        notification=notification,
                        error="",
                    )

            execution = BackgroundExecution()
            controller = Mock(return_value={"ok": True})
            server = WindowsDashboardServer(
                config_path,
                token="shared-lifecycle-token",
                lifecycle_factory=lambda path: ArticleLifecycle(
                    path,
                    _clock=lambda: now[0],
                ),
            )
            server.set_window_controller(controller)
            server.start()
            stale_html = server.dashboard_html()
            self.assertNotIn(notified_title, stale_html)
            write_window_control(
                config_path,
                server.url,
                server.token,
                pid=12345,
            )
            try:
                status = run_background_refresh(
                    config_path,
                    execution_factory=lambda _path: execution,
                )
                html = server.dashboard_html()
            finally:
                clear_window_control(config_path)
                server.stop()

        first_page = html.split(
            '<script type="application/json" id="matched-papers-data">',
            1,
        )[0]
        self.assertEqual(status, 0)
        self.assertEqual(execution.intent, RefreshIntent.BACKGROUND)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].articles[0].title, notified_title)
        self.assertIn(notified_title, first_page)
        self.assertIn("Detected: Jul 31, 2026", first_page)
        self.assertIn("Published: Jul 2026", first_page)
        controller.assert_called_once_with({"action": "refresh-complete"})

    def test_failed_refresh_returns_nonzero_and_is_logged(self):
        factory, _execution = self.execution_factory(
            outcome(RefreshRunStatus.FAILED, error="all sources offline")
        )
        config_path = Path("config.json")

        with (
            patch("paper_monitor.windows_background._log_background_error") as log_error,
            patch("paper_monitor.windows_background._write_stderr"),
            patch(
                "paper_monitor.windows_background._notify_open_dashboard"
            ) as notify_dashboard,
        ):
            status = run_background_refresh(config_path, execution_factory=factory)

        self.assertEqual(status, 1)
        self.assertIn("all sources offline", str(log_error.call_args.args[1]))
        notify_dashboard.assert_not_called()

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
                    patch(
                        "paper_monitor.windows_background._notify_open_dashboard"
                    ) as notify_dashboard,
                ):
                    status = run_background_refresh(
                        Path("config.json"),
                        execution_factory=factory,
                    )

                self.assertEqual(status, 1)
                notify_dashboard.assert_called_once_with(Path("config.json"))

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
