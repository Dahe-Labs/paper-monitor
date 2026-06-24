import json
import unittest

from paper_monitor.journal_metrics import JournalMetric, JournalMetrics
from paper_monitor.keyword_analysis import (
    DEFAULT_BLOCKLIST,
    DEFAULT_TAXONOMY,
    MAX_CANDIDATE_TERMS,
    AnalysisScope,
    build_keyword_analysis_payload,
    classify_papers,
    discover_candidate_terms,
    selected_papers,
)


def _metrics():
    return JournalMetrics(
        [
            JournalMetric(
                journal="Nature Energy",
                aliases=["Nat Energy"],
                impact_factor=64.8,
                impact_factor_year=2025,
                five_year_impact_factor=70.0,
                level="top journal",
                source_url="https://example.org/nature-energy",
            ),
            JournalMetric(
                journal="Advanced Energy Materials",
                aliases=["Adv Energy Mater"],
                impact_factor=24.4,
                impact_factor_year=2025,
                five_year_impact_factor=26.0,
                level="high impact journal",
                source_url="https://example.org/advanced-energy-materials",
            ),
            JournalMetric(
                journal="Journal of Power Sources",
                aliases=[],
                impact_factor=8.1,
                impact_factor_year=2025,
                five_year_impact_factor=8.8,
                level="specialist journal",
                source_url="https://example.org/journal-of-power-sources",
            ),
        ]
    )


def _paper(
    title,
    journal="Nature Energy",
    published="2026-06-24",
    detected=None,
    abstract="",
    matched_terms=None,
    doi="",
    url=None,
    matched=True,
    source="fixture",
    authors=None,
):
    safe_title = title.lower().replace(" ", "-")
    return {
        "title": title,
        "journal": journal,
        "url": url or f"https://example.org/{safe_title}",
        "doi": doi,
        "published": published,
        "detected": detected or published,
        "abstract": abstract,
        "source": source,
        "matched": matched,
        "matched_terms": list(matched_terms or []),
        "journal_match": journal,
        "authors": list(authors or []),
    }


class KeywordAnalysisTests(unittest.TestCase):
    def test_selected_papers_apply_date_journal_sort_and_top_n(self):
        candidates = [
            _paper(
                "Old included journal",
                journal="Nature Energy",
                published="2026-06-20",
                doi="10.1000/old",
            ),
            _paper(
                "New included journal",
                journal="Advanced Energy Materials",
                published="2026-06-23",
                doi="10.1000/new",
            ),
            _paper(
                "Excluded journal",
                journal="Journal of Power Sources",
                published="2026-06-24",
                doi="10.1000/excluded",
            ),
        ]
        scope = AnalysisScope(
            date_from="2026-06-21",
            date_to="2026-06-24",
            selected_journals=("Nature Energy", "Advanced Energy Materials"),
            sort_mode="time",
            top_n=1,
        )

        selected = selected_papers(candidates, _metrics(), scope)

        self.assertEqual([paper["title"] for paper in selected], ["New included journal"])

    def test_selected_papers_use_detected_date_for_time_filters_and_sorting(self):
        candidates = [
            _paper(
                "Detected newer despite future publication",
                journal="Journal of Power Sources",
                published="2026-10-15",
                detected="2026-06-23",
                doi="10.1016/newer",
            ),
            _paper(
                "Detected older despite earlier publication",
                journal="Nature Energy",
                published="2026-06-24",
                detected="2026-06-20",
                doi="10.1038/older",
            ),
        ]
        scope = AnalysisScope(date_from="2026-06-21", date_to="2026-06-24", sort_mode="time", top_n=2)

        selected = selected_papers(candidates, _metrics(), scope)

        self.assertEqual([paper["title"] for paper in selected], ["Detected newer despite future publication"])
        self.assertEqual(selected[0]["published"], "2026-10-15")
        self.assertEqual(selected[0]["detected"], "2026-06-23")

    def test_selected_papers_sort_by_impact_factor_when_requested(self):
        candidates = [
            _paper(
                "Lower IF",
                journal="Advanced Energy Materials",
                published="2026-06-24",
                doi="10.1000/lower",
            ),
            _paper(
                "Higher IF",
                journal="Nature Energy",
                published="2026-06-23",
                doi="10.1000/higher",
            ),
        ]
        scope = AnalysisScope(sort_mode="impact_factor", top_n=2)

        selected = selected_papers(candidates, _metrics(), scope)

        self.assertEqual([paper["title"] for paper in selected], ["Higher IF", "Lower IF"])

    def test_classify_papers_counts_one_hit_per_category_per_paper(self):
        papers = [
            _paper(
                "Halide solid electrolyte interface",
                abstract="A halide solid electrolyte improves solid electrolyte interfaces.",
                matched_terms=["halide", "solid electrolyte"],
                doi="10.1000/halide",
            ),
            _paper(
                "Oxide interfacial solid electrolyte design",
                abstract="Oxide ceramic solid electrolyte for interface control.",
                matched_terms=["oxide", "interface", "solid electrolyte"],
                doi="10.1000/oxide",
            ),
        ]

        categories = classify_papers(papers, DEFAULT_TAXONOMY)
        by_name = {category["name"]: category for category in categories}

        self.assertEqual(by_name["solid electrolyte"]["count"], 2)
        self.assertEqual(by_name["interface"]["count"], 2)
        self.assertEqual(by_name["halide"]["count"], 1)
        self.assertEqual(by_name["oxide"]["count"], 1)
        self.assertEqual(by_name["solid electrolyte"]["percentage"], 100.0)

    def test_discover_candidate_terms_uses_title_abstract_and_matched_terms_with_blocklist(self):
        papers = [
            _paper(
                "Stack pressure for solid-state cells",
                abstract="Why battery researchers tune stack pressure with lithium metal.",
                matched_terms=["stack pressure", "lithium metal"],
                doi="10.1000/stack-a",
            ),
            _paper(
                "Mechanical control",
                abstract="Stack pressure stabilizes interfaces in battery materials.",
                matched_terms=["stack pressure"],
                doi="10.1000/stack-b",
            ),
        ]
        blocklist = DEFAULT_BLOCKLIST | {"lithium metal"}

        candidates = discover_candidate_terms(papers, 2, blocklist, ())
        by_term = {candidate["term"]: candidate for candidate in candidates}

        self.assertEqual(by_term["stack pressure"]["count"], 2)
        self.assertNotIn("why battery", by_term)
        self.assertNotIn("lithium metal", by_term)

    def test_discover_candidate_terms_filters_low_value_ngrams_and_caps_results(self):
        repeated_domain_text = " ".join(f"lithium marker{i}" for i in range(60))
        papers = [
            _paper(
                "Rapid screening method",
                abstract=(
                    "Rapid screening method shows excellent result for general approach. "
                    "Interfacial resistance and lithium deposition are measured. "
                    + repeated_domain_text
                ),
                matched_terms=["solid electrolyte"],
                doi="10.1000/filter-a",
            ),
            _paper(
                "Rapid screening result",
                abstract=(
                    "Rapid screening method shows excellent result for general approach. "
                    "Interfacial resistance and lithium deposition are measured. "
                    + repeated_domain_text
                ),
                matched_terms=["solid electrolyte"],
                doi="10.1000/filter-b",
            ),
        ]

        candidates = discover_candidate_terms(papers, 2, DEFAULT_BLOCKLIST, ())
        terms = [candidate["term"] for candidate in candidates]

        self.assertLessEqual(len(terms), MAX_CANDIDATE_TERMS)
        self.assertIn("interfacial resistance", terms)
        self.assertIn("lithium deposition", terms)
        self.assertNotIn("rapid screening", terms)
        self.assertNotIn("excellent result", terms)
        self.assertNotIn("lithium", terms)

    def test_discover_candidate_terms_rejects_repeated_and_broad_only_phrases(self):
        papers = [
            _paper(
                "Solid state solid patterns",
                abstract=(
                    "Solid state solid state electrolyte electrolyte state solid. "
                    "Lithium deposition and interfacial resistance are measured in argyrodite."
                ),
                matched_terms=["solid electrolyte"],
                doi="10.1000/noise-a",
            ),
            _paper(
                "Repeated electrolyte patterns",
                abstract=(
                    "Solid state solid state electrolyte electrolyte state solid. "
                    "Lithium deposition and interfacial resistance are measured in argyrodite."
                ),
                matched_terms=["solid electrolyte"],
                doi="10.1000/noise-b",
            ),
        ]

        candidates = discover_candidate_terms(
            papers,
            2,
            DEFAULT_BLOCKLIST,
            (),
            phrase_lengths=(1, 2, 3, 4),
        )
        terms = [candidate["term"] for candidate in candidates]

        self.assertIn("argyrodite", terms)
        self.assertIn("lithium deposition", terms)
        self.assertIn("interfacial resistance", terms)
        self.assertNotIn("solid state", terms)
        self.assertNotIn("state solid", terms)
        self.assertNotIn("solid state solid", terms)
        self.assertNotIn("solid state solid state", terms)
        self.assertNotIn("electrolyte electrolyte", terms)

    def test_discover_candidate_terms_filters_publication_metadata_tokens(self):
        papers = [
            _paper(
                "June 2026 EarlyView solid electrolyte interface",
                abstract="Interfacial resistance improves oxide electrolyte.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/metadata-a",
            ),
            _paper(
                "June 2026 EarlyView solid electrolyte interface followup",
                abstract="Interfacial resistance improves oxide electrolyte.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/metadata-b",
            ),
        ]

        candidates = discover_candidate_terms(papers, 2, DEFAULT_BLOCKLIST, DEFAULT_TAXONOMY)
        terms = [candidate["term"] for candidate in candidates]

        self.assertIn("interfacial resistance", terms)
        self.assertNotIn("june 2026", terms)
        self.assertNotIn("2026 earlyview", terms)
        self.assertNotIn("earlyview solid", terms)
        self.assertNotIn("2026 earlyview solid", terms)

    def test_discover_candidate_terms_defaults_to_two_and_three_word_phrases(self):
        papers = [
            _paper(
                "Argyrodite interfacial resistance",
                abstract="Argyrodite interfacial resistance improves lithium deposition interface.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/length-a",
            ),
            _paper(
                "Argyrodite interfacial resistance followup",
                abstract="Argyrodite interfacial resistance improves lithium deposition interface.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/length-b",
            ),
        ]

        default_terms = [candidate["term"] for candidate in discover_candidate_terms(papers, 2, DEFAULT_BLOCKLIST, ())]
        one_word_terms = [
            candidate["term"]
            for candidate in discover_candidate_terms(
                papers,
                2,
                DEFAULT_BLOCKLIST,
                (),
                phrase_lengths=(1,),
            )
        ]

        self.assertIn("interfacial resistance", default_terms)
        self.assertNotIn("argyrodite", default_terms)
        self.assertIn("argyrodite", one_word_terms)

    def test_discover_candidate_terms_ignores_invalid_phrase_lengths(self):
        papers = [
            _paper(
                "Argyrodite interfacial resistance",
                abstract="Argyrodite interfacial resistance improves lithium deposition interface.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/invalid-length-a",
            ),
            _paper(
                "Argyrodite interfacial resistance followup",
                abstract="Argyrodite interfacial resistance improves lithium deposition interface.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/invalid-length-b",
            ),
        ]

        terms = [
            candidate["term"]
            for candidate in discover_candidate_terms(
                papers,
                2,
                DEFAULT_BLOCKLIST,
                (),
                phrase_lengths=("bad", 0, 5, None),
            )
        ]

        self.assertIn("interfacial resistance", terms)
        self.assertNotIn("argyrodite", terms)

    def test_build_keyword_analysis_payload_is_json_serializable(self):
        candidates = [
            _paper(
                "Solid electrolyte design",
                journal="Nature Energy",
                abstract="A solid electrolyte for all-solid-state batteries.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/payload",
                authors=["Ada Lovelace", "Grace Hopper"],
            )
        ]

        payload = build_keyword_analysis_payload(candidates, _metrics())

        json.dumps(payload)
        self.assertEqual(payload["scope"]["top_n"], 30)
        self.assertEqual(payload["papers"][0]["impact_factor"], 64.8)
        self.assertEqual(payload["papers"][0]["detected"], "2026-06-24")
        self.assertEqual(payload["papers"][0]["authors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(payload["journal_catalog"][0]["journal"], "Nature Energy")
        self.assertIn("solid electrolyte", [item["name"] for item in payload["taxonomy"]])

    def test_build_keyword_analysis_payload_does_not_cap_articles_by_top_n(self):
        candidates = [
            _paper(
                "Newer solid electrolyte paper",
                published="2026-06-24",
                abstract="A solid electrolyte design for stable cells.",
                matched_terms=["solid electrolyte"],
                doi="10.1000/newer",
            ),
            _paper(
                "Older cathode process",
                published="2026-06-23",
                abstract="Dry calendaring improves cathode layers.",
                matched_terms=["cathode"],
                doi="10.1000/older-a",
            ),
            _paper(
                "Oldest cathode process",
                published="2026-06-22",
                abstract="Dry calendaring supports cathode films.",
                matched_terms=["cathode"],
                doi="10.1000/older-b",
            ),
        ]

        payload = build_keyword_analysis_payload(candidates, _metrics(), AnalysisScope(top_n=1, sort_mode="time"))

        self.assertEqual(len(payload["papers"]), 3)
        self.assertEqual(
            payload["selected_paper_ids"],
            ["doi:10.1000/newer", "doi:10.1000/older-a", "doi:10.1000/older-b"],
        )
        category_names = [category["name"] for category in payload["categories"]]
        self.assertIn("solid electrolyte", category_names)
        self.assertIn("cathode", category_names)

    def test_explicit_id_takes_precedence_over_identity_doi_and_url(self):
        candidate = _paper("Explicit id paper", doi="10.1000/explicit")
        candidate["id"] = "explicit-id"
        candidate["identity"] = "identity-id"

        selected = selected_papers(
            [candidate],
            _metrics(),
            AnalysisScope(selected_paper_ids=("explicit-id",)),
        )
        payload = build_keyword_analysis_payload([candidate], _metrics())
        selected_by_identity = selected_papers(
            [candidate],
            _metrics(),
            AnalysisScope(selected_paper_ids=("identity-id",)),
        )

        self.assertEqual([paper["id"] for paper in selected], ["explicit-id"])
        self.assertEqual(payload["papers"][0]["id"], "explicit-id")
        self.assertEqual(selected_by_identity, [])

    def test_selected_papers_prefers_existing_identity_for_selection(self):
        candidate = _paper("Explicit identity paper", doi="10.1000/identity")
        candidate["identity"] = "identity-1"

        selected = selected_papers(
            [candidate],
            _metrics(),
            AnalysisScope(selected_paper_ids=("identity-1",)),
        )

        self.assertEqual([paper["id"] for paper in selected], ["identity-1"])

    def test_selected_papers_excludes_falsy_matched_values(self):
        candidates = [
            _paper("Missing matched value", doi="10.1000/missing"),
            _paper("Zero matched value", doi="10.1000/zero", matched=0),
        ]
        candidates[0].pop("matched")

        selected = selected_papers(candidates, _metrics(), AnalysisScope(top_n="invalid"))

        self.assertEqual([paper["title"] for paper in selected], ["Missing matched value"])

    def test_selected_papers_ignores_empty_selected_paper_ids(self):
        candidates = [_paper("Ignored empty selected id", doi="10.1000/ignored-empty")]

        selected = selected_papers(candidates, _metrics(), AnalysisScope(selected_paper_ids=(None, "")))

        self.assertEqual([paper["title"] for paper in selected], ["Ignored empty selected id"])


if __name__ == "__main__":
    unittest.main()
