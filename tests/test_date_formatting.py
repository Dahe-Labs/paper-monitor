import unittest
from datetime import date

from paper_monitor.article_lifecycle import DashboardArticle, DashboardSnapshot
from paper_monitor.dashboard import render_dashboard
from paper_monitor.date_utils import display_article_date, format_display_date
from paper_monitor.journal_metrics import JournalMetrics
from paper_monitor.lifecycle_dashboard import _snapshot_candidates


class DateFormattingTests(unittest.TestCase):
    def test_display_date_formatter_uses_fixed_english_month_names(self):
        self.assertEqual(format_display_date("2026-07-09"), "Jul 9, 2026")
        self.assertEqual(format_display_date("2026-07-09T13:45:00", style="long"), "July 9, 2026")
        self.assertEqual(format_display_date(date(2026, 7, 9), style="short"), "Jul 9")
        self.assertEqual(display_article_date("Published online 2026-07-09"), "Jul 9, 2026")

    def test_display_date_formatter_does_not_emit_chinese_date_markers(self):
        for style in ("compact", "long", "short"):
            formatted = format_display_date("2026-07-09", style=style)
            self.assertNotIn("\u5e74", formatted)
            self.assertNotIn("\u6708", formatted)
            self.assertNotIn("\u65e5", formatted)

    def test_dashboard_renders_visible_dates_in_english(self):
        html = render_dashboard(
            {"finished_at": "2026-07-09T13:45:00", "id": 7, "fetched": 1, "matched": 1},
            [
                {
                    "matched": True,
                    "title": "Solid electrolyte breakthrough",
                    "journal": "Nature Energy",
                    "source": "Crossref",
                    "doi": "10.1000/example",
                    "url": "https://example.org/article",
                    "detected": "2026-07-07T08:00:00",
                    "published": "2026-07-06",
                    "matched_terms": ["solid electrolyte"],
                    "reason": "Matched search term",
                }
            ],
            JournalMetrics([]),
        )

        self.assertIn("Last run: Jul 9, 2026", html)
        self.assertIn("<h3 class=\"date-heading\">July 7, 2026</h3>", html)
        self.assertIn("Detected: Jul 7, 2026", html)
        self.assertIn("Published: Jul 6, 2026", html)
        self.assertIn('"detected_label": "July 7, 2026"', html)
        self.assertNotIn("2026\u5e74", html)
        self.assertNotIn("7\u6708", html)
        self.assertNotIn("9\u65e5", html)

    def test_lifecycle_dashboard_uses_publication_date_not_detection_timestamp(self):
        snapshot = DashboardSnapshot(
            presentation_token="test-token",
            articles=(
                DashboardArticle(
                    article_id="article-1",
                    title="Publication date test",
                    authors=("A. Author",),
                    journal="Nature Energy",
                    impact_reference=20.0,
                    url="https://example.org/article",
                    published="2026-07-12",
                    first_detected_at="2026-07-14T08:30:00Z",
                ),
            ),
        )

        candidates = _snapshot_candidates(snapshot)
        html = render_dashboard(
            {},
            candidates,
            JournalMetrics([]),
            lifecycle_listing=True,
        )

        self.assertEqual(candidates[0]["detected"], "2026-07-12")
        self.assertEqual(candidates[0]["first_detected_at"], "2026-07-14T08:30:00Z")
        self.assertIn('<h3 class="date-heading">July 12, 2026</h3>', html)
        self.assertNotIn('<h3 class="date-heading">July 14, 2026</h3>', html)

    def test_lifecycle_dashboard_groups_month_precision_without_inventing_a_day(self):
        html = render_dashboard(
            {},
            [
                {
                    "title": "Month precision paper",
                    "journal": "Energy Storage Materials",
                    "url": "https://example.org/month",
                    "published": "2026-07",
                    "detected": "2026-07",
                    "matched": True,
                    "_lifecycle_listing": True,
                }
            ],
            JournalMetrics([]),
            lifecycle_listing=True,
        )

        self.assertIn('<h3 class="date-heading">July 2026</h3>', html)
        self.assertIn('"detected_label": "July 2026"', html)
        self.assertNotIn('"detected_label": "Unknown date"', html)


if __name__ == "__main__":
    unittest.main()
