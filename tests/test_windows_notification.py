import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from paper_monitor import refresh_execution
from paper_monitor.article_lifecycle import (
    NotificationArticle,
    NotificationDelivery,
    RefreshNotification,
)
from paper_monitor.windows_notification import (
    WindowsArticleNotificationAdapter,
    WindowsSummaryNotificationAdapter,
)


def article(suffix: str, *, title: str = "", journal: str = "Journal of Batteries"):
    return NotificationArticle(
        article_id=f"article-{suffix}",
        title=title or f"Article {suffix}",
        journal=journal,
        url=f"https://example.org/articles/{suffix.lower()}",
        doi=f"10.1/{suffix.lower()}",
        published="2026-07-29",
        source="Crossref",
    )


def notification(
    *,
    heading="3 new articles detected",
    body="Article A; Article B; Article C",
    articles=None,
):
    selected = (
        (article("A"), article("B"), article("C"))
        if articles is None
        else tuple(articles)
    )
    return RefreshNotification(
        run_id="run-1",
        heading=heading,
        body=body,
        article_count=3,
        preview_titles=("Article A", "Article B", "Article C"),
        articles=selected,
    )


def parsed_toast(call):
    return ElementTree.fromstring(call.kwargs["xml"])


class WindowsNotificationTests(unittest.TestCase):
    def test_article_adapter_prefers_url_then_doi_then_dashboard_target(self):
        sender = Mock()
        adapter = WindowsArticleNotificationAdapter(
            sender=sender,
            today=lambda: date(2026, 7, 29),
        )
        dashboard = Path("work/dashboard/latest.html")

        cases = (
            (
                {"title": "A", "journal": "Journal A", "url": "https://example.org/a", "doi": "10.1/a"},
                "https://example.org/a",
            ),
            (
                {"title": "B", "journal": "Journal B", "url": "", "doi": "10.1/b"},
                "https://doi.org/10.1/b",
            ),
            (
                {"title": "C", "journal": "Journal C", "url": "", "doi": ""},
                dashboard.resolve().as_uri(),
            ),
        )
        for article, target in cases:
            with self.subTest(target=target):
                self.assertTrue(adapter.deliver(article, dashboard))
                self.assertEqual(sender.call_args.kwargs["on_click"], target)
                self.assertEqual(parsed_toast(sender.call_args).attrib["launch"], target)

    def test_article_adapter_contains_runtime_delivery_failures(self):
        adapter = WindowsArticleNotificationAdapter(
            sender=Mock(side_effect=RuntimeError("toast failed")),
        )

        self.assertFalse(adapter.deliver({"title": "Paper"}, Path("dashboard.html")))

    def test_article_adapter_uses_compact_two_line_layout_and_escapes_metadata(self):
        sender = Mock()
        title = "A {study} & <trial> " + ("long " * 40)
        adapter = WindowsArticleNotificationAdapter(
            sender=sender,
            today=lambda: date(2026, 7, 29),
        )

        self.assertTrue(
            adapter.deliver(
                {
                    "identity": "special-article",
                    "title": title,
                    "journal": 'Journal "One" & Two',
                    "url": "https://example.org/paper?query={value}&mode=full",
                    "doi": "",
                },
                Path("dashboard.html"),
            )
        )

        call = sender.call_args
        root = parsed_toast(call)
        texts = root.findall("./visual/binding/group/subgroup/text")
        self.assertEqual(call.args, (None, None))
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[0].attrib["hint-maxLines"], "2")
        self.assertEqual(texts[0].attrib["hint-wrap"], "true")
        self.assertEqual(texts[0].attrib["hint-style"], "base")
        self.assertLessEqual(len(texts[0].text), 120)
        self.assertIn("{study}", texts[0].text)
        self.assertTrue(texts[0].text.endswith("..."))
        self.assertEqual(texts[1].text, 'Journal "One" & Two')
        self.assertEqual(texts[1].attrib["hint-style"], "captionSubtle")
        self.assertEqual(texts[1].attrib["hint-maxLines"], "1")
        self.assertIsNone(root.find("actions"))
        self.assertIsNone(root.find(".//image"))
        self.assertNotIn("icon", call.kwargs)

    def test_summary_adapter_submits_bounded_same_day_article_group(self):
        sender = Mock()
        with tempfile.TemporaryDirectory() as directory:
            icon_path = Path(directory) / "PaperMonitor.ico"
            icon_path.write_bytes(b"icon")
            adapter = WindowsSummaryNotificationAdapter(
                sender=sender,
                icon_path=icon_path,
                max_notifications=2,
                today=lambda: date(2026, 7, 29),
            )

            delivery = adapter.deliver(notification())

        self.assertEqual(delivery, NotificationDelivery.ACCEPTED)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(
            [call.kwargs["on_click"] for call in sender.call_args_list],
            ["https://example.org/articles/b", "https://example.org/articles/a"],
        )
        self.assertEqual(
            {call.kwargs["group"] for call in sender.call_args_list},
            {"pm20260729"},
        )
        self.assertEqual(
            len({call.kwargs["tag"] for call in sender.call_args_list}),
            2,
        )
        for call in sender.call_args_list:
            root = parsed_toast(call)
            header = root.find("header")
            texts = root.findall("./visual/binding/group/subgroup/text")
            self.assertEqual(header.attrib["id"], "pm20260729")
            self.assertEqual(header.attrib["title"], "2026-07-29")
            self.assertEqual(header.attrib["activationType"], "protocol")
            self.assertEqual(header.attrib["arguments"], call.kwargs["on_click"])
            self.assertEqual([text.text for text in texts[1:]], ["Journal of Batteries"])
            self.assertNotIn("10.1/", "".join(text.text or "" for text in texts))
            self.assertNotIn("actions", call.kwargs)
            self.assertNotIn("icon", call.kwargs)

    def test_group_changes_with_local_delivery_date(self):
        sender = Mock()
        current_day = [date(2026, 7, 29)]
        adapter = WindowsSummaryNotificationAdapter(
            sender=sender,
            icon_path=Path("missing.ico"),
            max_notifications=1,
            today=lambda: current_day[0],
        )

        adapter.deliver(notification(articles=(article("A"),)))
        current_day[0] = date(2026, 7, 30)
        adapter.deliver(notification(articles=(article("A"),)))

        self.assertEqual(
            [call.kwargs["group"] for call in sender.call_args_list],
            ["pm20260729", "pm20260730"],
        )

    def test_zero_notification_limit_consumes_batch_without_calling_sender(self):
        sender = Mock()
        adapter = WindowsSummaryNotificationAdapter(
            sender=sender,
            icon_path=Path("missing.ico"),
            max_notifications=0,
        )

        delivery = adapter.deliver(notification())

        self.assertEqual(delivery, NotificationDelivery.ACCEPTED)
        sender.assert_not_called()

    def test_notification_limit_is_capped_to_windows_history_capacity(self):
        adapter = WindowsSummaryNotificationAdapter(
            sender=Mock(),
            icon_path=Path("missing.ico"),
            max_notifications=100,
        )

        self.assertEqual(adapter.max_notifications, 20)

    def test_legacy_summary_without_article_payload_remains_bounded(self):
        sender = Mock()
        adapter = WindowsSummaryNotificationAdapter(
            sender=sender,
            icon_path=Path("missing.ico"),
        )

        delivery = adapter.deliver(
            notification(heading="H" * 200, body="B" * 500, articles=())
        )

        self.assertEqual(delivery, NotificationDelivery.ACCEPTED)
        sender.assert_called_once()
        heading, body = sender.call_args.args
        self.assertLessEqual(len(heading), 120)
        self.assertLessEqual(len(body), 350)

    def test_missing_winrt_sender_is_a_clear_rejection_that_can_retry(self):
        adapter = WindowsSummaryNotificationAdapter(icon_path=Path("missing.ico"))

        with patch(
            "paper_monitor.windows_notification._load_windows_notifier",
            side_effect=ImportError("WinRT notifications missing"),
        ):
            delivery = adapter.deliver(notification())

        self.assertEqual(delivery, NotificationDelivery.REJECTED)

    def test_sender_exception_propagates_for_lifecycle_to_classify_as_ambiguous(self):
        adapter = WindowsSummaryNotificationAdapter(
            sender=Mock(side_effect=[None, RuntimeError("delivery state unknown")]),
            icon_path=Path("missing.ico"),
        )

        with self.assertRaisesRegex(RuntimeError, "delivery state unknown"):
            adapter.deliver(notification())

    def test_refresh_execution_selects_windows_adapter_only_on_windows(self):
        config = SimpleNamespace(
            dashboard_path=Path("dashboard.html"),
            monitor_config=SimpleNamespace(max_notifications=2),
        )
        with patch.object(refresh_execution.sys, "platform", "win32"):
            windows_adapter = refresh_execution._production_notification_adapter(config)
        with patch.object(refresh_execution.sys, "platform", "linux"):
            other_adapter = refresh_execution._production_notification_adapter(config)

        self.assertIsInstance(windows_adapter, WindowsSummaryNotificationAdapter)
        self.assertEqual(windows_adapter.max_notifications, 2)
        self.assertEqual(windows_adapter.dashboard_path, Path("dashboard.html"))
        self.assertIsNone(other_adapter)


if __name__ == "__main__":
    unittest.main()
