import unittest

from paper_monitor.filtering import FilterConfig, match_article
from paper_monitor.models import Article


class FilteringTests(unittest.TestCase):
    def test_matches_solid_state_battery_article_in_allowed_journal(self):
        article = Article(
            title="Stable sulfide solid electrolyte for all-solid-state lithium batteries",
            journal="Nature Energy",
            url="https://example.org/article",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="An argyrodite electrolyte lowers interfacial impedance.",
            source="fixture",
        )
        config = FilterConfig(
            include_terms=["solid-state battery", "solid electrolyte", "argyrodite"],
            exclude_terms=["solid-state laser"],
            journals=["Nature Energy", "Advanced Energy Materials"],
        )

        result = match_article(article, config)

        self.assertTrue(result.matched)
        self.assertIn("solid electrolyte", result.matched_terms)
        self.assertEqual(result.journal_match, "Nature Energy")

    def test_rejects_excluded_non_battery_solid_state_article(self):
        article = Article(
            title="Solid-state laser emission in crystalline materials",
            journal="Nature",
            url="https://example.org/laser",
            doi="10.1000/laser",
            published="2026-06-20",
            abstract="A photonics paper unrelated to batteries.",
            source="fixture",
        )
        config = FilterConfig(
            include_terms=["solid-state", "solid electrolyte"],
            exclude_terms=["solid-state laser"],
            journals=["Nature"],
        )

        result = match_article(article, config)

        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "excluded-term")

    def test_rejects_article_outside_journal_allowlist(self):
        article = Article(
            title="Solid electrolyte interface engineering for lithium metal cells",
            journal="Low Impact Battery Letters",
            url="https://example.org/article",
            doi="10.1000/outside",
            published="2026-06-20",
            abstract="A solid electrolyte paper.",
            source="fixture",
        )
        config = FilterConfig(
            include_terms=["solid electrolyte"],
            exclude_terms=[],
            journals=["Nature Energy"],
        )

        result = match_article(article, config)

        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "journal-not-allowed")

    def test_matches_terms_across_hyphen_variants(self):
        article = Article(
            title="Interfaces in all solid state batteries",
            journal="Nature Energy",
            url="https://example.org/article",
            doi="10.1000/hyphen",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )
        config = FilterConfig(
            include_terms=["all-solid-state batteries"],
            exclude_terms=[],
            journals=["Nature Energy"],
        )

        result = match_article(article, config)

        self.assertTrue(result.matched)


if __name__ == "__main__":
    unittest.main()
