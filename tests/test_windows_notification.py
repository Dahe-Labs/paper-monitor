import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor import refresh_execution
from paper_monitor.article_lifecycle import (
    NotificationDelivery,
    RefreshNotification,
)
from paper_monitor.windows_notification import (
    WindowsArticleNotificationAdapter,
    WindowsSummaryNotificationAdapter,
)


def notification(*, heading="3 new articles detected", body="Article A; Article B; Article C"):
    return RefreshNotification(
        run_id="run-1",
        heading=heading,
        body=body,
        article_count=3,
        preview_titles=("Article A", "Article B", "Article C"),
    )


class WindowsNotificationTests(unittest.TestCase):
    def test_article_adapter_prefers_url_then_doi_then_dashboard_target(self):
        sender = Mock()
        adapter = WindowsArticleNotificationAdapter(
            sender=sender,
            icon_path=Path("missing.ico"),
        )
        dashboard = Path("work/dashboard/latest.html")

        cases = (
            ({"title": "A", "url": "https://example.org/a", "doi": "10.1/a"}, "https://example.org/a"),
            ({"title": "B", "url": "", "doi": "10.1/b"}, "https://doi.org/10.1/b"),
            ({"title": "C", "url": "", "doi": ""}, dashboard.resolve().as_uri()),
        )
        for article, target in cases:
            with self.subTest(target=target):
                self.assertTrue(adapter.deliver(article, dashboard))
                self.assertEqual(sender.call_args.kwargs["on_click"], target)

    def test_article_adapter_contains_runtime_delivery_failures(self):
        adapter = WindowsArticleNotificationAdapter(
            sender=Mock(side_effect=RuntimeError("toast failed")),
            icon_path=Path("missing.ico"),
        )

        self.assertFalse(adapter.deliver({"title": "Paper"}, Path("dashboard.html")))

    def test_summary_adapter_submits_one_bounded_notification(self):
        sender = Mock()
        with tempfile.TemporaryDirectory() as directory:
            icon_path = Path(directory) / "PaperMonitor.ico"
            icon_path.write_bytes(b"icon")
            adapter = WindowsSummaryNotificationAdapter(
                sender=sender,
                icon_path=icon_path,
            )

            delivery = adapter.deliver(notification(heading="H" * 200, body="B" * 500))

        self.assertEqual(delivery, NotificationDelivery.ACCEPTED)
        sender.assert_called_once()
        heading, body = sender.call_args.args
        self.assertLessEqual(len(heading), 120)
        self.assertLessEqual(len(body), 350)
        self.assertEqual(sender.call_args.kwargs["icon"], str(icon_path))

    def test_missing_win11toast_is_a_clear_rejection_that_can_retry(self):
        adapter = WindowsSummaryNotificationAdapter(icon_path=Path("missing.ico"))

        with patch(
            "paper_monitor.windows_notification._load_windows_notifier",
            side_effect=ImportError("win11toast missing"),
        ):
            delivery = adapter.deliver(notification())

        self.assertEqual(delivery, NotificationDelivery.REJECTED)

    def test_sender_exception_propagates_for_lifecycle_to_classify_as_ambiguous(self):
        adapter = WindowsSummaryNotificationAdapter(
            sender=Mock(side_effect=RuntimeError("delivery state unknown")),
            icon_path=Path("missing.ico"),
        )

        with self.assertRaisesRegex(RuntimeError, "delivery state unknown"):
            adapter.deliver(notification())

    def test_refresh_execution_selects_windows_adapter_only_on_windows(self):
        config = SimpleNamespace()
        with patch.object(refresh_execution.sys, "platform", "win32"):
            windows_adapter = refresh_execution._production_notification_adapter(config)
        with patch.object(refresh_execution.sys, "platform", "darwin"):
            other_adapter = refresh_execution._production_notification_adapter(config)

        self.assertIsInstance(windows_adapter, WindowsSummaryNotificationAdapter)
        self.assertIsNone(other_adapter)


if __name__ == "__main__":
    unittest.main()
