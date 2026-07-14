import unittest
from datetime import date

from paper_monitor.date_utils import (
    display_article_date,
    first_iso_date,
    first_iso_date_key,
    iso_date_sort_key,
)


class DateUtilsTests(unittest.TestCase):
    def test_first_iso_date_extracts_only_full_dates(self):
        self.assertEqual(first_iso_date("Detected on 2026-06-24"), date(2026, 6, 24))
        self.assertIsNone(first_iso_date("2026-06"))
        self.assertIsNone(first_iso_date("not a date"))

    def test_display_article_date_normalizes_full_and_partial_dates(self):
        self.assertEqual(display_article_date("Published: 2026-10-15"), "Oct 15, 2026")
        self.assertEqual(display_article_date("2026-10"), "Oct 2026")
        self.assertEqual(display_article_date(None), "")

    def test_partial_dates_keep_their_precision_for_grouping_and_sorting(self):
        self.assertEqual(first_iso_date_key("Published 2026-07"), "2026-07")
        self.assertEqual(first_iso_date_key("2026"), "2026")
        self.assertEqual(iso_date_sort_key("2026-07"), (2026, 7, 0, 2))
        self.assertEqual(first_iso_date_key("2026-13-40"), "")


if __name__ == "__main__":
    unittest.main()
