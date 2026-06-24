import unittest
from datetime import date

from paper_monitor.date_utils import display_article_date, first_iso_date


class DateUtilsTests(unittest.TestCase):
    def test_first_iso_date_extracts_only_full_dates(self):
        self.assertEqual(first_iso_date("Detected on 2026-06-24"), date(2026, 6, 24))
        self.assertIsNone(first_iso_date("2026-06"))
        self.assertIsNone(first_iso_date("not a date"))

    def test_display_article_date_normalizes_full_dates_and_preserves_partial_dates(self):
        self.assertEqual(display_article_date("Published: 2026-10-15"), "2026-10-15")
        self.assertEqual(display_article_date("2026-10"), "2026-10")
        self.assertEqual(display_article_date(None), "")


if __name__ == "__main__":
    unittest.main()
