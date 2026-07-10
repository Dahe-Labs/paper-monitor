import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_monitor.dashboard import (
    _keyword_analysis_script,
    _matched_papers_script,
    render_dashboard,
)
from paper_monitor.journal_metrics import load_journal_metrics
from paper_monitor.keyword_analysis import AnalysisScope


def _run_node_script(node: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [node],
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )


class DashboardAndMetricsTests(unittest.TestCase):
    def test_loads_metrics_by_journal_name_and_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metrics.json"
            path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": ["Nat Energy"],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": 68.9,
                                "level": "Nature Portfolio top journal",
                                "source_url": "https://www.nature.com/nenergy/journal-impact",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            metrics = load_journal_metrics(path)

            self.assertEqual(metrics.lookup("Nature Energy").impact_factor, 60.1)
            self.assertEqual(metrics.lookup("Nat Energy").journal, "Nature Energy")
            self.assertIsNone(metrics.lookup("Unknown Journal"))

    def test_loads_ranked_journal_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal_metrics.json"
            path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "rank": 1,
                                "journal": "Nature Energy",
                                "aliases": ["Nat Energy"],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": 68.9,
                                "level": "Nature Portfolio top energy journal",
                                "source_url": "https://www.nature.com/nenergy/journal-impact",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            metrics = load_journal_metrics(path)
            metric = metrics.lookup("Nat Energy")

            self.assertEqual(metric.rank, 1)
            self.assertEqual(metric.journal, "Nature Energy")

    def test_renders_dashboard_with_article_links_metrics_and_reasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": 68.9,
                                "level": "Nature Portfolio top journal",
                                "source_url": "https://www.nature.com/nenergy/journal-impact",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            metrics = load_journal_metrics(metrics_path)
            run = {
                "id": 7,
                "started_at": "2026-06-22 10:00:00",
                "finished_at": "2026-06-22 10:00:05",
                "fetched": 2,
                "matched": 1,
                "new_matches": 1,
                "skipped": 1,
            }
            candidates = [
                {
                    "title": "Solid electrolyte design",
                    "journal": "Nature Energy",
                    "url": "https://example.org/article",
                    "doi": "10.1000/example",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
                {
                    "title": "Laser paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/laser",
                    "doi": "",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": False,
                    "reason": "excluded-term",
                    "matched_terms": [],
                    "journal_match": "Nature Energy",
                },
            ]

            html = render_dashboard(run, candidates, metrics)

            self.assertIn("Paper Monitor", html)
            self.assertIn("Solid electrolyte design", html)
            self.assertIn('href="https://example.org/article"', html)
            self.assertIn("Impact factor: 60.1", html)
            self.assertIn("5-year: 68.9", html)
            self.assertNotIn("year: 2024", html)
            self.assertIn('<strong class="journal-name">Nature Energy</strong>', html)
            self.assertIn("excluded-term", html)
            self.assertIn('<details class="rejected-candidates">', html)
            self.assertIn("<summary>Show rejected candidates", html)

    def test_dashboard_summary_shows_selected_journal_count(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-24", "fetched": 5, "matched": 2, "new_matches": 1, "skipped": 3},
            [],
            load_journal_metrics(Path("/does/not/exist.json")),
            AnalysisScope(selected_journals=("Nature Energy", "Joule", "arXiv"), top_n=15),
        )

        self.assertIn('<div class="pill">Selected journals: 3</div>', html)

    def test_dashboard_uses_journal_match_for_metrics_when_raw_journal_is_noisy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Journal of Power Sources",
                                "aliases": [],
                                "impact_factor": 7.9,
                                "impact_factor_year": 2025,
                                "five_year_impact_factor": None,
                                "level": "specialist journal",
                                "source_url": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            html = render_dashboard(
                {"id": 1, "started_at": "2026-06-24", "matched": 1},
                [
                    {
                        "title": "Crossref matched paper",
                        "journal": "Elsevier feed item",
                        "url": "https://example.org/power",
                        "doi": "10.1016/example",
                        "published": "2026-10-15",
                        "detected": "2026-06-21",
                        "source": "Crossref",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "Journal of Power Sources",
                    }
                ],
                load_journal_metrics(metrics_path),
            )

        self.assertIn('<strong class="journal-name">Journal of Power Sources</strong>', html)
        self.assertIn("Impact factor: 7.9", html)

    def test_dashboard_shows_article_date_without_metric_update_year(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": None,
                                "level": "Nature Portfolio top journal",
                                "source_url": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            html = render_dashboard(
                {"id": 1, "started_at": "run-start", "matched": 1},
                [
                    {
                        "title": "Solid electrolyte design",
                        "journal": "Nature Energy",
                        "url": "https://example.org/article",
                        "doi": "10.1000/example",
                        "published": "2026-06-22",
                        "detected": "2026-06-22",
                        "source": "fixture",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "Nature Energy",
                    }
                ],
                load_journal_metrics(metrics_path),
            )

            self.assertIn("<strong class=\"journal-name\">Nature Energy</strong> · Detected: Jun 22, 2026 · fixture", html)
            self.assertNotIn("2024", html)

    def test_dashboard_marks_different_published_date_without_using_it_for_grouping(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-24", "matched": 1},
            [
                {
                    "title": "Future issue paper",
                    "journal": "Journal of Power Sources",
                    "url": "https://example.org/future",
                    "doi": "10.1016/example",
                    "published": "2026-10-15",
                    "detected": "2026-06-17",
                    "source": "Crossref",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Journal of Power Sources",
                }
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        self.assertIn('<h3 class="date-heading">June 17, 2026</h3>', html)
        self.assertNotIn('<h3 class="date-heading">October 15, 2026</h3>', html)
        self.assertIn("Detected: Jun 17, 2026 · Published: Oct 15, 2026 · Crossref", html)

    def test_dashboard_date_groups_use_sticky_timeline_headers_and_counts(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-24", "matched": 2},
            [
                {
                    "title": "First paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/first",
                    "doi": "10.1000/first",
                    "published": "2026-06-20",
                    "detected": "2026-06-20",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
                {
                    "title": "Second paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/second",
                    "doi": "10.1000/second",
                    "published": "2026-06-20",
                    "detected": "2026-06-20",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        self.assertIn("position: sticky", html)
        self.assertIn(".date-group::before", html)
        self.assertIn('class="date-heading-bar"', html)
        self.assertIn('<span class="date-marker" aria-hidden="true"></span>', html)
        self.assertIn('<span class="date-short-label">Jun 20</span>', html)
        self.assertIn('<span class="date-count">2 papers</span>', html)
        self.assertIn('<h3 class="date-heading">June 20, 2026</h3>', html)
        self.assertIn(".paper { border: 1px solid #d8dee4; border-radius: 6px; padding: 8px 10px; margin: 5px 0; }", html)

    def test_dashboard_groups_matched_papers_by_date_in_descending_order(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-24", "matched": 4},
            [
                {
                    "title": "June 22 paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/june-22",
                    "doi": "10.1000/june-22",
                    "published": "2026-06-22",
                    "detected": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
                {
                    "title": "June 23 first paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/june-23-a",
                    "doi": "10.1000/june-23-a",
                    "published": "2026-06-23",
                    "detected": "2026-06-23",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
                {
                    "title": "August paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/august",
                    "doi": "10.1000/august",
                    "published": "2026-08-01",
                    "detected": "2026-06-21",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
                {
                    "title": "June 23 second paper",
                    "journal": "Nature Energy",
                    "url": "https://example.org/june-23-b",
                    "doi": "10.1000/june-23-b",
                    "published": "2026-06-23",
                    "detected": "2026-06-23",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                },
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        august_group = html.index('<h3 class="date-heading">June 21, 2026</h3>')
        june_23_group = html.index('<h3 class="date-heading">June 23, 2026</h3>')
        june_22_group = html.index('<h3 class="date-heading">June 22, 2026</h3>')
        june_23_first = html.index("June 23 first paper", june_23_group)
        june_23_second = html.index("June 23 second paper", june_23_first)

        self.assertLess(june_23_group, june_22_group)
        self.assertLess(june_22_group, august_group)
        self.assertLess(june_23_group, june_23_first)
        self.assertLess(june_23_first, june_23_second)
        self.assertLess(june_23_second, june_22_group)
        self.assertLess(june_22_group, august_group)

    def test_dashboard_exposes_matched_paper_sort_control_and_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2025,
                                "five_year_impact_factor": None,
                                "level": "top journal",
                                "source_url": "",
                            },
                            {
                                "journal": "Journal of Power Sources",
                                "aliases": [],
                                "impact_factor": 8.1,
                                "impact_factor_year": 2025,
                                "five_year_impact_factor": None,
                                "level": "specialist journal",
                                "source_url": "",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            html = render_dashboard(
                {"id": 1, "started_at": "2026-06-24", "matched": 2},
                [
                    {
                        "title": "Lower impact paper",
                        "journal": "Journal of Power Sources",
                        "url": "https://example.org/lower",
                        "doi": "10.1000/lower",
                        "published": "2026-06-24",
                        "detected": "2026-06-24",
                        "source": "fixture",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "Journal of Power Sources",
                    },
                    {
                        "title": "Higher impact paper",
                        "journal": "Nature Energy",
                        "url": "https://example.org/higher",
                        "doi": "10.1000/higher",
                        "published": "2026-06-23",
                        "detected": "2026-06-23",
                        "source": "fixture",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte", "lithium metal"],
                        "journal_match": "Nature Energy",
                    },
                ],
                load_journal_metrics(metrics_path),
            )

        self.assertIn('id="matched-papers-sort"', html)
        self.assertIn('id="matched-papers-list"', html)
        self.assertIn('id="matched-papers-data"', html)
        self.assertIn('value="impact_factor"', html)
        json_text = html.split('<script type="application/json" id="matched-papers-data">', 1)[1].split("</script>", 1)[0]
        payload = json.loads(json_text)
        by_title = {item["title"]: item for item in payload["items"]}

        self.assertEqual(by_title["Higher impact paper"]["impact_factor"], 60.1)
        self.assertEqual(by_title["Lower impact paper"]["impact_factor"], 8.1)
        self.assertIn('<h3 class="date-heading">June 24, 2026</h3>', html)

    def test_matched_papers_script_sorts_by_impact_factor_without_date_groups(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        script = _matched_papers_script()[len("<script>") : -len("</script>")]
        harness = f"""
global.document = {{
  addEventListener() {{}},
  getElementById() {{ return null; }}
}};
{script}
const items = [
  {{ title: "Low", html: "<article>Low</article>", detected: "2026-06-24", detected_label: "2026-06-24", impact_factor: 8.1, relevance: 1, index: 0 }},
  {{ title: "High", html: "<article>High</article>", detected: "2026-06-23", detected_label: "2026-06-23", impact_factor: 60.1, relevance: 2, index: 1 }}
];
const impactHtml = renderMatchedPapers(items, "impact_factor", "<p>empty</p>");
if (impactHtml.includes("date-group") || impactHtml.includes("date-heading")) {{
  throw new Error("impact factor mode should not render date groups");
}}
if (impactHtml.indexOf("High") > impactHtml.indexOf("Low")) {{
  throw new Error("impact factor mode did not sort high impact first: " + impactHtml);
}}
const timeHtml = renderMatchedPapers(items, "time", "<p>empty</p>");
if (!timeHtml.includes("date-group") || !timeHtml.includes("date-heading")) {{
  throw new Error("time mode should render date groups");
}}
if (!timeHtml.includes("date-heading-bar") || !timeHtml.includes("date-count")) {{
  throw new Error("time mode should render prominent date headers with paper counts: " + timeHtml);
}}
if (timeHtml.indexOf("Low") > timeHtml.indexOf("High")) {{
  throw new Error("time mode did not sort by detected date: " + timeHtml);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escapes_metric_level_text_in_dashboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": None,
                                "level": "<script>alert('xss')</script>",
                                "source_url": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            metrics = load_journal_metrics(metrics_path)
            html = render_dashboard(
                {"id": 1, "started_at": "2026-06-22", "matched": 1},
                [
                    {
                        "title": "Solid electrolyte design",
                        "journal": "Nature Energy",
                        "url": "https://example.org/article",
                        "doi": "10.1000/example",
                        "published": "2026-06-22",
                        "source": "fixture",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "Nature Energy",
                    }
                ],
                metrics,
            )

            self.assertNotIn("<script>alert('xss')</script>", html)
            self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html)

    def test_dashboard_metric_source_links_allow_only_web_urls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2024,
                                "five_year_impact_factor": 68.9,
                                "level": "Nature Portfolio top journal",
                                "source_url": "javascript:alert(1)",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            metrics = load_journal_metrics(metrics_path)

            html = render_dashboard(
                {"id": 1, "started_at": "2026-06-22", "matched": 1},
                [
                    {
                        "title": "Solid electrolyte design",
                        "journal": "Nature Energy",
                        "url": "https://example.org/article",
                        "doi": "10.1000/example",
                        "published": "2026-06-22",
                        "source": "fixture",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "Nature Energy",
                    }
                ],
                metrics,
            )

            self.assertNotIn('href="javascript:alert(1)"', html)
            self.assertNotIn("metric source", html)
            self.assertIn("Impact factor: 60.1", html)
            self.assertIn("5-year: 68.9", html)
            self.assertIn("Nature Portfolio top journal", html)

    def test_dashboard_article_links_allow_only_web_urls_and_doi_fallbacks(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-22", "matched": 1},
            [
                {
                    "title": "Solid electrolyte design",
                    "journal": "Nature Energy",
                    "url": "javascript:alert(1)",
                    "doi": "10.1000/example",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                }
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        self.assertNotIn('href="javascript:alert(1)"', html)
        self.assertIn('href="https://doi.org/10.1000/example"', html)

    def test_dashboard_uses_clean_source_journal_when_feed_title_is_noisy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Advanced Energy Materials",
                                "aliases": [],
                                "impact_factor": 25.5,
                                "impact_factor_year": 2025,
                                "five_year_impact_factor": None,
                                "level": "Wiley flagship energy materials journal",
                                "source_url": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            html = render_dashboard(
                {"id": 1, "started_at": "2026-06-22", "matched": 1},
                [
                    {
                        "title": "Solid electrolyte design",
                        "journal": "Wiley: Advanced Energy Materials: Table of Contents",
                        "url": "https://example.org/article",
                        "doi": "10.1000/example",
                        "published": "2026-06-22",
                        "source": "Advanced Energy Materials",
                        "matched": True,
                        "reason": "matched",
                        "matched_terms": ["solid electrolyte"],
                        "journal_match": "",
                    }
                ],
                load_journal_metrics(metrics_path),
            )

            self.assertIn('<strong class="journal-name">Advanced Energy Materials</strong>', html)
            self.assertIn("Impact factor: 25.5", html)

    def test_dashboard_includes_keyword_analysis_entry_and_payload(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-22", "matched": 1},
            [
                {
                    "title": "Solid electrolyte <script>alert(1)</script>",
                    "journal": "Nature Energy",
                    "url": "https://example.org/article",
                    "doi": "10.1000/example",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                }
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        self.assertIn('id="keyword-analysis"', html)
        self.assertIn('id="keyword-analysis-data"', html)
        self.assertIn('class="header-main"', html)
        self.assertIn('id="keyword-analysis-nav"', html)
        self.assertIn('id="dashboard-view"', html)
        self.assertNotIn('id="analysis-back"', html)
        self.assertIn('id="analysis-panel"', html)
        self.assertIn('id="analysis-controls"', html)
        self.assertIn('id="analysis-chart-tabs"', html)
        self.assertIn('id="analysis-chart"', html)
        self.assertIn('id="analysis-candidates"', html)
        self.assertIn('id="analysis-taxonomy"', html)
        self.assertIn('id="analysis-papers"', html)
        self.assertIn('id="analysis-run-button"', html)
        self.assertIn('id="analysis-progress"', html)
        self.assertIn('id="analysis-progress-bar"', html)
        self.assertIn('id="analysis-progress-label"', html)
        self.assertIn('class="analysis-progress-fill"', html)
        self.assertIn(">Keyword Analysis</button>", html)
        self.assertIn(".analysis-journal-list { max-height: 280px; }", html)
        self.assertIn("Back to Dashboard", html)
        self.assertNotIn("Analyze Keywords", html)
        self.assertIn('data-chart-view="bars"', html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_dashboard_keyword_payload_is_valid_json(self):
        adversarial_title = "Solid electrolyte </SCRIPT><script>alert(1)</script>"
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-22", "matched": 1},
            [
                {
                    "title": adversarial_title,
                    "journal": "Nature Energy",
                    "url": "https://example.org/article",
                    "doi": "10.1000/example",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                }
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        start = '<script type="application/json" id="keyword-analysis-data">'
        self.assertIn(start, html)
        json_text = html.split(start, 1)[1].split("</script>", 1)[0]
        payload = json.loads(json_text)

        self.assertEqual(payload["papers"][0]["title"], adversarial_title)
        self.assertNotIn("</SCRIPT><script>alert(1)</script>", json_text)
        self.assertNotIn(adversarial_title, html)
        self.assertIn("solid electrolyte", [item["name"] for item in payload["taxonomy"]])
        self.assertIn("battery", payload["blocklist"])

    def test_dashboard_keyword_analysis_has_required_interaction_hooks(self):
        html = render_dashboard(
            {"id": 1, "started_at": "2026-06-22", "matched": 1},
            [
                {
                    "title": "Solid electrolyte design",
                    "journal": "Nature Energy",
                    "url": "https://example.org/article",
                    "doi": "10.1000/example",
                    "published": "2026-06-22",
                    "source": "fixture",
                    "matched": True,
                    "reason": "matched",
                    "matched_terms": ["solid electrolyte"],
                    "journal_match": "Nature Energy",
                }
            ],
            load_journal_metrics(Path("/does/not/exist.json")),
        )

        for hook in [
            "keywordAnalysisState",
            "renderBars",
            "renderDonut",
            "renderTrend",
            "renderTable",
            "renderAnalysisPaperList",
            "formatPaperAuthors",
            "blockedTerms",
            "customTaxonomy",
            "toggleKeywordAnalysisView",
            "showKeywordAnalysisView",
            "showDashboardView",
            "addSearchTerm",
            "showCopyFallback",
            "requestKeywordAnalysis",
            "receiveKeywordAnalysisPayload",
            "updateAnalysisHeaderAction",
            "startAnalysisProgress",
            "setAnalysisProgress",
            "finishAnalysisProgress",
            "renderAnalysisDepthControl",
            "normalizeAnalysisDepth",
            "renderDateRangeControl",
            "resolveDateBoundaryFromControls",
            "baseFilteredAnalysisPapers",
            "coercePositiveInt",
            "localStorage",
            "analyzeKeywords",
        ]:
            self.assertIn(hook, html)

    def test_keyword_analysis_script_is_valid_javascript(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        script = _keyword_analysis_script()
        self.assertTrue(script.startswith("<script>"))
        self.assertTrue(script.endswith("</script>"))

        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as script_file:
            script_file.write(script[len("<script>") : -len("</script>")])
            script_file.flush()

            result = subprocess.run(
                [node, "--check", script_file.name],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_analyze_button_posts_scope_to_native_bridge(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Solid electrolyte design",
                    "journal": "Nature Energy",
                    "published": "2026-06-24",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 1,
                }
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
let posted = null;
function makeElement() {{
  return {{
    hidden: true,
    textContent: "",
    style: {{}},
    attributes: {{}},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    removeAttribute(name) {{ delete this.attributes[name]; }}
  }};
}}
const progress = makeElement();
const progressBar = makeElement();
const progressLabel = makeElement();
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    if (id === "analysis-progress") return progress;
    if (id === "analysis-progress-bar") return progressBar;
    if (id === "analysis-progress-label") return progressLabel;
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{
  webkit: {{
    messageHandlers: {{
      paperMonitor: {{
        postMessage(message) {{ posted = message; }}
      }}
    }}
  }}
}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
keywordAnalysisState.dateFrom = "2026-06-01";
keywordAnalysisState.dateTo = "2026-06-24";
keywordAnalysisState.sortMode = "impact_factor";
keywordAnalysisState.topN = 12;
keywordAnalysisState.selectedJournals = ["Nature Energy"];
const controls = renderAnalysisControls();
if (controls.includes('data-scope-action="run-keyword-analysis"') || controls.includes(">Analyze<")) {{
  throw new Error("Analyze button should not render inside Scope controls: " + controls);
}}
requestKeywordAnalysis();
if (!posted) {{
  throw new Error("Analyze did not post to native bridge");
}}
if (posted.type !== "analyzeKeywords") {{
  throw new Error("unexpected message type " + posted.type);
}}
if (posted.date_from !== "2026-06-01" || posted.date_to !== "2026-06-24") {{
  throw new Error("date range not posted correctly: " + JSON.stringify(posted));
}}
if (posted.sort_mode !== "impact_factor" || posted.top_n !== 12) {{
  throw new Error("sort/topN not posted correctly: " + JSON.stringify(posted));
}}
if (posted.analysis_depth !== "fast") {{
  throw new Error("analysis depth should default to fast: " + JSON.stringify(posted));
}}
if (posted.journals.join(",") !== "Nature Energy") {{
  throw new Error("journals not posted correctly: " + JSON.stringify(posted));
}}
if (keywordAnalysisState.analysisStatus !== "loading") {{
  throw new Error("analysis status should be loading after bridge request");
}}
if (progress.hidden) {{
  throw new Error("analysis progress bar should become visible while loading");
}}
if (progressBar.style.width !== "8%") {{
  throw new Error("analysis progress should start at 8%, got " + progressBar.style.width);
}}
if (!progressLabel.textContent.includes("Preparing")) {{
  throw new Error("analysis progress label should describe the current stage: " + progressLabel.textContent);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_defaults_to_fast_depth(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {},
            "taxonomy": [],
            "blocklist": [],
            "papers": [],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
if (keywordAnalysisState.analysisDepth !== "fast") {{
  throw new Error("default analysis depth should be fast, got " + keywordAnalysisState.analysisDepth);
}}
const controls = renderAnalysisControls();
if (!controls.includes("Analysis Depth") || !controls.includes("Fast") || !controls.includes("Exhaustive")) {{
  throw new Error("analysis depth control should render Fast and Exhaustive options: " + controls);
}}
if (!controls.includes('data-analysis-depth')) {{
  throw new Error("analysis depth control should be wired for autosave: " + controls);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_defaults_date_range_from_payload_papers(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {"title": "New paper", "detected": "2026-06-24", "journal": "Nature Energy"},
                {"title": "Old paper", "published": "2026-06-01T10:30:00-07:00", "journal": "Nature Energy"},
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
if (keywordAnalysisState.dateFrom !== "2026-06-01") {{
  throw new Error("expected default Date from from payload papers, got " + keywordAnalysisState.dateFrom);
}}
if (keywordAnalysisState.dateTo !== "2026-06-24") {{
  throw new Error("expected default Date to from payload papers, got " + keywordAnalysisState.dateTo);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_header_contains_analyze_button_and_scope_uses_custom_date_controls(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30},
            "taxonomy": [],
            "blocklist": [],
            "papers": [],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
const button = {{
  textContent: "",
  disabled: false,
  attributes: {{}},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }}
}};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    if (id === "analysis-run-button") return button;
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
keywordAnalysisState.dateFrom = "2026-06-01";
keywordAnalysisState.dateTo = "2026-06-24";
const controls = renderAnalysisControls();
if (controls.includes('type="date"')) {{
  throw new Error("native date input should not render: " + controls);
}}
["analysis-date-from-year", "analysis-date-from-month", "analysis-date-from-day", "analysis-date-to-year", "analysis-date-to-month", "analysis-date-to-day"].forEach((id) => {{
  if (!controls.includes('id="' + id + '"')) {{
    throw new Error("missing custom date control " + id + ": " + controls);
  }}
}});
["analysis-date-from-year-options", "analysis-date-from-month-options", "analysis-date-from-day-options", "analysis-date-to-year-options", "analysis-date-to-month-options", "analysis-date-to-day-options"].forEach((id) => {{
  if (!controls.includes('id="' + id + '"')) {{
    throw new Error("missing date option list " + id + ": " + controls);
  }}
}});
if (controls.includes("analysis-date-from-iso") || controls.includes("analysis-date-to-iso") || controls.includes("date-iso-input")) {{
  throw new Error("separate ISO date input should not render: " + controls);
}}
if (!controls.includes('inputmode="numeric"') || !controls.includes('maxlength="4"')) {{
  throw new Error("year should be directly editable as numeric text: " + controls);
}}
if (!controls.includes('list="analysis-date-from-year-options"') || !controls.includes('list="analysis-date-to-day-options"')) {{
  throw new Error("date fields should support typed input with dropdown suggestions: " + controls);
}}
updateAnalysisHeaderAction();
if (button.textContent !== "Analyze" || button.disabled) {{
  throw new Error("header Analyze button should be idle");
}}
keywordAnalysisState.analysisStatus = "loading";
updateAnalysisHeaderAction();
if (button.textContent !== "Analyzing..." || !button.disabled) {{
  throw new Error("header Analyze button should show loading state");
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_custom_date_controls_expand_partial_dates(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {"scope": {"top_n": 30}, "taxonomy": [], "blocklist": [], "papers": []}
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
function makeElement(value) {{
  return {{
    value: value || "",
    textContent: "",
    hidden: false,
    attributes: {{}},
    classes: new Set(),
    classList: {{
      add(name) {{ this.owner.classes.add(name); }},
      remove(name) {{ this.owner.classes.delete(name); }},
      contains(name) {{ return this.owner.classes.has(name); }},
      owner: null
    }},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    removeAttribute(name) {{ delete this.attributes[name]; }}
  }};
}}
function withOwner(element) {{ element.classList.owner = element; return element; }}
const elements = {{
  "keyword-analysis-data": {{ textContent: JSON.stringify(payload) }},
  "analysis-date-from-control": withOwner(makeElement()),
  "analysis-date-from-error": withOwner(makeElement()),
  "analysis-date-from-year": withOwner(makeElement("2025")),
  "analysis-date-from-month": withOwner(makeElement("")),
  "analysis-date-from-day": withOwner(makeElement("")),
  "analysis-date-to-control": withOwner(makeElement()),
  "analysis-date-to-error": withOwner(makeElement()),
  "analysis-date-to-year": withOwner(makeElement("2026")),
  "analysis-date-to-month": withOwner(makeElement("")),
  "analysis-date-to-day": withOwner(makeElement(""))
}};
global.document = {{
  getElementById(id) {{ return elements[id] || null; }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
syncDateFromParts("from");
if (keywordAnalysisState.dateFrom !== "2025-01-01") {{
  throw new Error("year-only From should expand to first day of year: " + keywordAnalysisState.dateFrom);
}}
elements["analysis-date-from-month"].value = "12";
syncDateFromParts("from");
if (keywordAnalysisState.dateFrom !== "2025-12-01") {{
  throw new Error("month-only From should expand to first day of month: " + keywordAnalysisState.dateFrom);
}}
elements["analysis-date-from-day"].value = "31";
syncDateFromParts("from");
if (keywordAnalysisState.dateFrom !== "2025-12-31") {{
  throw new Error("full From date should use selected day: " + keywordAnalysisState.dateFrom);
}}
syncDateFromParts("to");
if (keywordAnalysisState.dateTo !== "2026-12-31") {{
  throw new Error("year-only To should expand to last day of year: " + keywordAnalysisState.dateTo);
}}
elements["analysis-date-to-month"].value = "06";
syncDateFromParts("to");
if (keywordAnalysisState.dateTo !== "2026-06-30") {{
  throw new Error("month-only To should expand to last day of month: " + keywordAnalysisState.dateTo);
}}
elements["analysis-date-to-day"].value = "24";
syncDateFromParts("to");
if (keywordAnalysisState.dateTo !== "2026-06-24") {{
  throw new Error("full To date should use selected day: " + keywordAnalysisState.dateTo);
}}
elements["analysis-date-to-year"].value = "2024";
elements["analysis-date-to-month"].value = "02";
elements["analysis-date-to-day"].value = "";
syncDateFromParts("to");
if (keywordAnalysisState.dateTo !== "2024-02-29") {{
  throw new Error("month-only To should use leap-year month end: " + keywordAnalysisState.dateTo);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_invalid_date_marks_fields_and_blocks_analyze(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {"scope": {"top_n": 30}, "taxonomy": [], "blocklist": [], "papers": []}
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
let posted = null;
function makeElement(value) {{
  const element = {{
    value: value || "",
    textContent: "",
    hidden: false,
    attributes: {{}},
    classes: new Set(),
    classList: {{
      add(name) {{ element.classes.add(name); }},
      remove(name) {{ element.classes.delete(name); }},
      contains(name) {{ return element.classes.has(name); }}
    }},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    removeAttribute(name) {{ delete this.attributes[name]; }}
  }};
  return element;
}}
const controls = {{ querySelectorAll() {{ return []; }} }};
const elements = {{
  "keyword-analysis-data": {{ textContent: JSON.stringify(payload) }},
  "analysis-controls": controls,
  "analysis-date-from-control": makeElement(),
  "analysis-date-from-error": makeElement(),
  "analysis-date-from-year": makeElement("2026"),
  "analysis-date-from-month": makeElement("02"),
  "analysis-date-from-day": makeElement("30"),
  "analysis-date-to-control": makeElement(),
  "analysis-date-to-error": makeElement(),
  "analysis-date-to-year": makeElement("2026"),
  "analysis-date-to-month": makeElement("06"),
  "analysis-date-to-day": makeElement("")
}};
global.document = {{
  getElementById(id) {{ return elements[id] || null; }},
  addEventListener() {{}},
  createElement() {{ return makeElement(); }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{
  webkit: {{
    messageHandlers: {{
      paperMonitor: {{
        postMessage(message) {{ posted = message; }}
      }}
    }}
  }}
}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
syncDateFromParts("from");
if (!elements["analysis-date-from-control"].classList.contains("has-error")) {{
  throw new Error("invalid date should mark date control as error");
}}
if (!elements["analysis-date-from-error"].textContent.includes("Invalid date")) {{
  throw new Error("invalid date should display error message, got " + elements["analysis-date-from-error"].textContent);
}}
if (elements["analysis-date-from-year"].attributes["aria-invalid"] !== "true") {{
  throw new Error("invalid date should mark fields aria-invalid");
}}
requestKeywordAnalysis();
if (posted) {{
  throw new Error("invalid date should block analyze post");
}}
if (keywordAnalysisState.analysisStatus !== "error") {{
  throw new Error("invalid date should set analysis error status");
}}
elements["analysis-date-from-day"].value = "29";
syncDateFromParts("from");
if (!elements["analysis-date-from-control"].classList.contains("has-error")) {{
  throw new Error("non-leap-year February 29 should stay marked as invalid");
}}
if (keywordAnalysisState.dateFrom !== "") {{
  throw new Error("2026-02-29 should not be accepted as valid non-leap date");
}}
elements["analysis-date-from-year"].value = "2024";
syncDateFromParts("from");
if (elements["analysis-date-from-control"].classList.contains("has-error")) {{
  throw new Error("valid leap day should clear error state");
}}
if (keywordAnalysisState.dateFrom !== "2024-02-29") {{
  throw new Error("leap day should be accepted for 2024, got " + keywordAnalysisState.dateFrom);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_analyze_expands_mismatched_date_precision(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {"scope": {"top_n": 30}, "taxonomy": [], "blocklist": [], "papers": []}
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
let posted = null;
function makeElement(value) {{
  const element = {{
    value: value || "",
    textContent: "",
    hidden: false,
    attributes: {{}},
    classes: new Set(),
    classList: {{
      add(name) {{ element.classes.add(name); }},
      remove(name) {{ element.classes.delete(name); }},
      contains(name) {{ return element.classes.has(name); }}
    }},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    removeAttribute(name) {{ delete this.attributes[name]; }}
  }};
  return element;
}}
const elements = {{
  "keyword-analysis-data": {{ textContent: JSON.stringify(payload) }},
  "analysis-date-from-control": makeElement(),
  "analysis-date-from-error": makeElement(),
  "analysis-date-from-year": makeElement("2026"),
  "analysis-date-from-month": makeElement(""),
  "analysis-date-from-day": makeElement(""),
  "analysis-date-to-control": makeElement(),
  "analysis-date-to-error": makeElement(),
  "analysis-date-to-year": makeElement("2026"),
  "analysis-date-to-month": makeElement("06"),
  "analysis-date-to-day": makeElement("")
}};
global.document = {{
  getElementById(id) {{ return elements[id] || null; }},
  addEventListener() {{}},
  createElement() {{ return makeElement(); }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{
  webkit: {{
    messageHandlers: {{
      paperMonitor: {{
        postMessage(message) {{ posted = message; }}
      }}
    }}
  }}
}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
requestKeywordAnalysis();
if (!posted) {{
  throw new Error("expanded partial date range should post to native bridge");
}}
if (posted.date_from !== "2026-01-01" || posted.date_to !== "2026-06-30") {{
  throw new Error("partial precision range was not expanded correctly: " + JSON.stringify(posted));
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_partial_date_edits_do_not_rerender_and_keep_inputs(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {"scope": {"top_n": 30}, "taxonomy": [], "blocklist": [], "papers": []}
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
let rendered = 0;
function makeElement(value) {{
  const element = {{
    value: value || "",
    textContent: "",
    hidden: false,
    attributes: {{}},
    classes: new Set(),
    classList: {{
      add(name) {{ element.classes.add(name); }},
      remove(name) {{ element.classes.delete(name); }},
      contains(name) {{ return element.classes.has(name); }}
    }},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    removeAttribute(name) {{ delete this.attributes[name]; }}
  }};
  return element;
}}
const controls = {{
  querySelectorAll() {{ return []; }}
}};
const yearTarget = makeElement("2026");
yearTarget.matches = function (selector) {{ return selector === "[data-date-part]"; }};
yearTarget.getAttribute = function (name) {{ return name === "data-date-boundary" ? "from" : ""; }};
const elements = {{
  "keyword-analysis-data": {{ textContent: JSON.stringify(payload) }},
  "analysis-controls": controls,
  "analysis-date-from-control": makeElement(),
  "analysis-date-from-error": makeElement(),
  "analysis-date-from-year": yearTarget,
  "analysis-date-from-month": makeElement(""),
  "analysis-date-from-day": makeElement("")
}};
global.document = {{
  getElementById(id) {{ return elements[id] || null; }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
renderKeywordAnalysis = function () {{ rendered += 1; }};
handleAnalysisControlChange({{ target: yearTarget }}, true);
if (rendered !== 0) {{
  throw new Error("partial date edits should not rerender and clear input, rendered " + rendered);
}}
if (yearTarget.value !== "2026") {{
  throw new Error("partial year was unexpectedly changed: " + yearTarget.value);
}}
if (keywordAnalysisState.dateFrom !== "2026-01-01") {{
  throw new Error("year-only date should expand without rerendering: " + keywordAnalysisState.dateFrom);
}}
elements["analysis-date-from-month"].value = "06";
elements["analysis-date-from-day"].value = "24";
handleAnalysisControlChange({{ target: yearTarget }}, true);
if (rendered !== 0) {{
  throw new Error("completed date edit should still avoid rerender, rendered " + rendered);
}}
if (keywordAnalysisState.dateFrom !== "2026-06-24") {{
  throw new Error("completed date parts did not update state: " + keywordAnalysisState.dateFrom);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_receives_native_payload_and_refreshes_state(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {"scope": {"top_n": 30}, "taxonomy": [], "blocklist": [], "papers": []}
        refreshed = {
            "scope": {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "selected_journals": ["Journal of Power Sources"],
                "sort_mode": "time",
                "top_n": 5,
                "source": "crossref",
            },
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Crossref paper",
                    "journal": "Journal of Power Sources",
                    "published": "2026-10-15",
                    "detected": "2026-06-21",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 7.9,
                }
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
const refreshed = {json.dumps(refreshed)};
let rendered = 0;
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  saved: "",
  getItem() {{ return null; }},
  setItem(_key, value) {{ this.saved = value; }}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
const originalRender = renderKeywordAnalysis;
renderKeywordAnalysis = function () {{ rendered += 1; }};
receiveKeywordAnalysisPayload(refreshed);
if (keywordAnalysisState.payload.papers[0].title !== "Crossref paper") {{
  throw new Error("payload was not replaced");
}}
if (keywordAnalysisState.dateFrom !== "2026-06-01" || keywordAnalysisState.dateTo !== "2026-06-24") {{
  throw new Error("date scope not refreshed");
}}
if (keywordAnalysisState.selectedJournals.join(",") !== "Journal of Power Sources") {{
  throw new Error("journals not refreshed: " + keywordAnalysisState.selectedJournals.join(","));
}}
if (keywordAnalysisState.analysisStatus !== "idle" || keywordAnalysisState.analysisError) {{
  throw new Error("analysis status not reset");
}}
if (rendered !== 1) {{
  throw new Error("expected one rerender, got " + rendered);
}}
if (!global.window.paperMonitorReceiveKeywordAnalysis) {{
  throw new Error("native callback should be exposed on window");
}}
renderKeywordAnalysis = originalRender;
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_status_preserves_zero_counts(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30, "source": "crossref"},
            "taxonomy": [],
            "blocklist": [],
            "papers": [],
            "fetched": 0,
            "matched": 0,
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
const status = renderAnalysisStatus();
if (!status.includes("0 fetched") || !status.includes("0 matched")) {{
  throw new Error("zero counts should be preserved: " + status);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_nav_button_toggles_between_dashboard_and_analysis(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30},
            "taxonomy": [],
            "blocklist": [],
            "papers": [],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
function makeElement(id) {{
  return {{
    id,
    hidden: false,
    textContent: "",
    innerHTML: "",
    attributes: {{}},
    addEventListener() {{}},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || ""; }}
  }};
}}
const elements = {{
  "keyword-analysis-data": {{ textContent: JSON.stringify(payload) }},
  "keyword-analysis-nav": makeElement("keyword-analysis-nav"),
  "dashboard-view": makeElement("dashboard-view"),
  "keyword-analysis": makeElement("keyword-analysis"),
  "analysis-panel": makeElement("analysis-panel"),
  "analysis-controls": makeElement("analysis-controls"),
  "analysis-chart-tabs": makeElement("analysis-chart-tabs"),
  "analysis-chart": makeElement("analysis-chart"),
  "analysis-candidates": makeElement("analysis-candidates"),
  "analysis-taxonomy": makeElement("analysis-taxonomy")
}};
elements["keyword-analysis-nav"].textContent = "Keyword Analysis";
elements["keyword-analysis"].hidden = true;
global.document = {{
  getElementById(id) {{ return elements[id] || null; }},
  addEventListener() {{}},
  createElement() {{ return makeElement(""); }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{ scrollTo() {{}} }};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
showKeywordAnalysisView();
if (!elements["dashboard-view"].hidden || elements["keyword-analysis"].hidden) {{
  throw new Error("keyword analysis view did not replace dashboard view");
}}
if (elements["keyword-analysis-nav"].textContent !== "Back to Dashboard") {{
  throw new Error("nav button should become Back to Dashboard, got " + elements["keyword-analysis-nav"].textContent);
}}
showDashboardView();
if (elements["dashboard-view"].hidden || !elements["keyword-analysis"].hidden) {{
  throw new Error("dashboard view was not restored");
}}
if (elements["keyword-analysis-nav"].textContent !== "Keyword Analysis") {{
  throw new Error("nav button should return to Keyword Analysis, got " + elements["keyword-analysis-nav"].textContent);
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_script_omits_paper_scope_and_ignores_stale_paper_selection(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 2},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Recent paper",
                    "journal": "Nature Energy",
                    "published": "2026-06-24",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 1,
                },
                {
                    "id": "paper-2",
                    "title": "Middle paper",
                    "journal": "Nature Energy",
                    "published": "2026-06-23",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 1,
                },
                {
                    "id": "paper-3",
                    "title": "Older paper",
                    "journal": "Nature Energy",
                    "published": "2026-06-22",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 1,
                },
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") {{
      return {{ textContent: JSON.stringify(payload) }};
    }}
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
keywordAnalysisState.topN = 2;
keywordAnalysisState.selectedTerms = ["term that no longer has a visible filter"];
let selectedIds = selectedAnalysisPapers().map((paper) => paper.id);
if (selectedIds.join(",") !== "paper-1,paper-2,paper-3") {{
  throw new Error("expected article selection to ignore stale matched-term filters and not apply Top Journals as an article cap, got " + selectedIds.join(","));
}}
keywordAnalysisState.hasPaperSelection = true;
keywordAnalysisState.selectedPaperIds = ["paper-3"];
selectedIds = selectedAnalysisPapers().map((paper) => paper.id);
if (selectedIds.join(",") !== "paper-1,paper-2,paper-3") {{
  throw new Error("expected stale paper selection to be ignored, got " + selectedIds.join(","));
}}
const controls = renderAnalysisControls();
if (controls.includes("data-paper-option") || controls.includes("<h3>Papers</h3>")) {{
  throw new Error("paper scope controls should not be rendered");
}}
if (controls.includes("data-term-option") || controls.includes("<h3>Matched Terms</h3>")) {{
  throw new Error("matched term controls should not be rendered");
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_script_supports_bulk_scope_phrase_length_and_blocklist_controls(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Argyrodite interface",
                    "journal": "Nature Energy",
                    "url": "https://example.org/paper-1",
                    "doi": "10.1000/paper-1",
                    "authors": ["Ada Lovelace", "Grace Hopper", "Katherine Johnson", "Dorothy Vaughan", "Mary Jackson"],
                    "published": "2026-06-24",
                    "abstract": "Argyrodite interfacial resistance improves lithium deposition.",
                    "matched_terms": ["argyrodite", "interfacial resistance"],
                    "impact_factor": 1,
                },
                {
                    "id": "paper-2",
                    "title": "Argyrodite followup",
                    "journal": "Advanced Energy Materials",
                    "url": "https://example.org/paper-2",
                    "doi": "10.1000/paper-2",
                    "authors": ["Alan Turing"],
                    "published": "2026-06-23",
                    "abstract": "Argyrodite interfacial resistance improves lithium deposition.",
                    "matched_terms": ["lithium deposition"],
                    "impact_factor": 1,
                },
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") {{
      return {{ textContent: JSON.stringify(payload) }};
    }}
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  saved: "",
  getItem() {{ return null; }},
  setItem(_key, value) {{ this.saved = value; }}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
let controls = renderAnalysisControls();
["select-all-journals", "clear-journals"].forEach((action) => {{
  if (!controls.includes('data-scope-action="' + action + '"')) {{
    throw new Error("missing scope action " + action);
  }}
}});
["select-all-terms", "clear-terms"].forEach((action) => {{
  if (controls.includes('data-scope-action="' + action + '"')) {{
    throw new Error("matched term action should not render " + action);
  }}
}});
["Matched Terms", "data-term-option", "Minimum article count", "analysis-minimum-article-count", "data-phrase-length-option", "analysis-blocked-terms"].forEach((fragment) => {{
  if (controls.includes(fragment)) {{
    throw new Error("left controls should not include " + fragment);
  }}
}});
["analysis-sort-prev", "analysis-sort-next", "analysis-top-n-decrement", "analysis-top-n-increment"].forEach((action) => {{
  if (!controls.includes('data-stepper-action="' + action + '"')) {{
    throw new Error("missing stepper action " + action);
  }}
}});
if (!controls.includes('data-stepper-action="analysis-sort-prev" aria-label="Previous sort mode">&lt;</button>') ||
    !controls.includes('data-stepper-action="analysis-sort-next" aria-label="Next sort mode">&gt;</button>')) {{
  throw new Error("sort stepper should use left/right angle controls: " + controls);
}}
if (!controls.includes('data-stepper-action="analysis-top-n-decrement" aria-label="Decrease top journals">-</button>') ||
    !controls.includes('data-stepper-action="analysis-top-n-increment" aria-label="Increase top journals">+</button>')) {{
  throw new Error("Top Journals stepper should keep minus/plus controls: " + controls);
}}
if (!controls.includes('class="analysis-dual-listbox analysis-journal-list"')) {{
  throw new Error("journal list should use taller analysis-specific class");
}}
let candidateHtml = renderCandidateTerms(discoveredTerms(selectedAnalysisPapers()));
["1", "2", "3", "4"].forEach((length) => {{
  if (!candidateHtml.includes('data-phrase-length-option value="' + length + '"')) {{
    throw new Error("missing candidate phrase length " + length);
  }}
}});
if (!candidateHtml.includes('data-candidate-filter-action="toggle-candidate-terms"')) {{
  throw new Error("missing candidate terms toggle");
}}
if (!candidateHtml.includes('data-candidate-filter-action="toggle-block-terms"')) {{
  throw new Error("missing block terms toggle");
}}
if (candidateHtml.includes('class="candidate-row"')) {{
  throw new Error("candidate rows should be collapsed by default");
}}
if (candidateHtml.includes("analysis-blocked-terms")) {{
  throw new Error("blocked terms editor should be hidden until opened");
}}
keywordAnalysisState.candidateTermsOpen = true;
candidateHtml = renderCandidateTerms(discoveredTerms(selectedAnalysisPapers()));
if (!candidateHtml.includes('class="candidate-row"')) {{
  throw new Error("candidate rows should render after opening");
}}
keywordAnalysisState.blockTermsOpen = true;
candidateHtml = renderCandidateTerms(discoveredTerms(selectedAnalysisPapers()));
if (!candidateHtml.includes("analysis-blocked-terms")) {{
  throw new Error("blocked terms editor should render after opening");
}}
if (candidateHtml.includes('class="candidate-row"')) {{
  throw new Error("candidate rows and blocked terms editor should be mutually exclusive");
}}
keywordAnalysisState.candidateTermsOpen = false;
keywordAnalysisState.blockTermsOpen = false;
applyCandidateFilterAction("toggle-candidate-terms");
if (!keywordAnalysisState.candidateTermsOpen || keywordAnalysisState.blockTermsOpen) {{
  throw new Error("show terms should open by itself");
}}
applyCandidateFilterAction("toggle-block-terms");
if (!keywordAnalysisState.blockTermsOpen || keywordAnalysisState.candidateTermsOpen) {{
  throw new Error("block terms should close show terms");
}}
let rendered = 0;
renderKeywordAnalysis = function () {{ rendered += 1; }};
handleAnalysisCandidateFilterChange({{ target: {{ id: "analysis-blocked-terms", value: "oxygen release", matches() {{ return false; }} }} }}, false);
if (rendered !== 0) {{
  throw new Error("blocked terms input should not rerender while typing");
}}
if (!keywordAnalysisState.blockedTerms.includes("oxygen release")) {{
  throw new Error("blocked terms input did not update state");
}}
let taxonomyHtml = renderTaxonomyEditor(classifySelectedPapers(selectedAnalysisPapers()));
if (!taxonomyHtml.includes('data-taxonomy-action="toggle-taxonomy-editor"')) {{
  throw new Error("missing taxonomy toggle");
}}
if (taxonomyHtml.includes('class="taxonomy-list"')) {{
  throw new Error("taxonomy list should be collapsed by default");
}}
keywordAnalysisState.taxonomyEditorOpen = true;
taxonomyHtml = renderTaxonomyEditor(classifySelectedPapers(selectedAnalysisPapers()));
if (!taxonomyHtml.includes('class="taxonomy-list"')) {{
  throw new Error("taxonomy list should render after opening");
}}
if (keywordAnalysisState.selectedPhraseLengths.join(",") !== "2,3") {{
  throw new Error("unexpected default phrase lengths " + keywordAnalysisState.selectedPhraseLengths.join(","));
}}
const barsHtml = renderBars([
  {{ name: "argyrodite", count: 2, percentage: 100, paperIds: ["paper-1", "paper-2"] }}
], selectedAnalysisPapers().length);
if (!barsHtml.includes("Total papers: 2")) {{
  throw new Error("Category Share should show total paper count: " + barsHtml);
}}
if (!barsHtml.includes("100.0% · 2 papers")) {{
  throw new Error("Category Share should show percentage and article count together: " + barsHtml);
}}
let paperListHtml = renderAnalysisPaperList(selectedAnalysisPapers());
if (!paperListHtml.includes("Show Papers") || paperListHtml.includes("analysis-paper-table")) {{
  throw new Error("paper list should be collapsed by default: " + paperListHtml);
}}
keywordAnalysisState.paperListOpen = true;
paperListHtml = renderAnalysisPaperList(selectedAnalysisPapers());
["analysis-paper-table", "Argyrodite interface", "10.1000/paper-1", "Nature Energy", "Ada Lovelace, Grace Hopper, Katherine Johnson, Dorothy Vaughan, et al."].forEach((fragment) => {{
  if (!paperListHtml.includes(fragment)) {{
    throw new Error("paper list missing " + fragment + ": " + paperListHtml);
  }}
}});
keywordAnalysisState.sortMode = "time";
applyAnalysisStepperAction("analysis-sort-next");
if (keywordAnalysisState.sortMode !== "impact_factor") {{
  throw new Error("sort stepper should advance to impact factor, got " + keywordAnalysisState.sortMode);
}}
keywordAnalysisState.topN = 2;
applyAnalysisStepperAction("analysis-top-n-increment");
if (keywordAnalysisState.topN !== 3) {{
  throw new Error("Top N increment failed, got " + keywordAnalysisState.topN);
}}
applyAnalysisStepperAction("analysis-top-n-decrement");
if (keywordAnalysisState.topN !== 2) {{
  throw new Error("Top N decrement failed, got " + keywordAnalysisState.topN);
}}
applyAnalysisControlAction("clear-journals");
if (selectedAnalysisPapers().length !== 0) {{
  throw new Error("clearing journals should empty selected papers");
}}
applyAnalysisControlAction("select-all-journals");
if (selectedAnalysisPapers().length !== 2) {{
  throw new Error("selecting all journals should restore selected papers");
}}
keywordAnalysisState.selectedPhraseLengths = [1];
let terms = discoveredTerms(selectedAnalysisPapers()).map((item) => item.term);
if (!terms.includes("argyrodite") || terms.includes("interfacial resistance")) {{
  throw new Error("length 1 filtering failed: " + terms.join(","));
}}
keywordAnalysisState.selectedPhraseLengths = [2];
terms = discoveredTerms(selectedAnalysisPapers()).map((item) => item.term);
if (!terms.includes("interfacial resistance") || terms.includes("argyrodite")) {{
  throw new Error("length 2 filtering failed: " + terms.join(","));
}}
keywordAnalysisState.blockedTerms = parseEditableTerms("interfacial resistance\\nlithium deposition");
terms = discoveredTerms(selectedAnalysisPapers()).map((item) => item.term);
if (terms.includes("interfacial resistance") || terms.includes("lithium deposition")) {{
  throw new Error("blocked terms editor did not remove blocked candidates: " + terms.join(","));
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_defaults_to_configured_scope_journals(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30, "selected_journals": ["Nature Energy", "Joule"]},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Solid electrolyte paper",
                    "journal": "Nature Energy",
                    "published": "2026-06-24",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 64.8,
                }
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
let posted = null;
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{
  webkit: {{
    messageHandlers: {{
      paperMonitor: {{
        postMessage(message) {{ posted = message; }}
      }}
    }}
  }}
}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
if (keywordAnalysisState.selectedJournals.join(",") !== "Nature Energy,Joule") {{
  throw new Error("default journals should come from scope: " + keywordAnalysisState.selectedJournals.join(","));
}}
const controls = renderAnalysisControls();
if (!controls.includes('data-journal="Joule"') || !controls.includes("2 / 2 selected")) {{
  throw new Error("scope journals should render in controls: " + controls);
}}
applyAnalysisJournalAction("remove", " nature energy ");
if (keywordAnalysisState.selectedJournals.join(",") !== "Joule") {{
  throw new Error("removed analysis journal should stay unselected: " + keywordAnalysisState.selectedJournals.join(","));
}}
const removedControls = renderAnalysisControls();
if (!removedControls.includes('data-analysis-journal-action="add" data-journal="Nature Energy"')) {{
  throw new Error("removed journal should return to the candidate list: " + removedControls);
}}
applyAnalysisJournalAction("add", "Nature Energy");
keywordAnalysisState.selectedJournals = ["Nature Energy", "Joule"];
keywordAnalysisState.dateFrom = "2026-06-01";
keywordAnalysisState.dateTo = "2026-06-24";
requestKeywordAnalysis();
if (!posted || posted.journals.join(",") !== "Nature Energy,Joule") {{
  throw new Error("Analyze request should post scope journals: " + JSON.stringify(posted));
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_refreshes_stale_saved_journals_when_scope_changes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30, "selected_journals": ["Nature Energy", "Joule"]},
            "taxonomy": [],
            "blocklist": [],
            "papers": [],
        }
        saved = {
            "hasJournalSelection": True,
            "selectedJournals": ["Nature Energy"],
            "journalScopeSignature": "old-scope",
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
const saved = {json.dumps(saved)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return JSON.stringify(saved); }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
loadSavedAnalysisState();
initializeAnalysisDefaults();
if (keywordAnalysisState.selectedJournals.join(",") !== "Nature Energy,Joule") {{
  throw new Error("stale saved journals should refresh from current scope: " + keywordAnalysisState.selectedJournals.join(","));
}}
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_analysis_script_filters_publication_metadata_candidate_terms(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not available")

        payload = {
            "scope": {"top_n": 30},
            "taxonomy": [],
            "blocklist": [],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "June 2026 EarlyView solid electrolyte interface",
                    "journal": "Nature Energy",
                    "published": "2026-06-24",
                    "abstract": "Interfacial resistance improves oxide electrolyte.",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 64.8,
                },
                {
                    "id": "paper-2",
                    "title": "June 2026 EarlyView solid electrolyte interface followup",
                    "journal": "Nature Energy",
                    "published": "2026-06-23",
                    "abstract": "Interfacial resistance improves oxide electrolyte.",
                    "matched_terms": ["solid electrolyte"],
                    "impact_factor": 64.8,
                },
            ],
        }
        script = _keyword_analysis_script()[len("<script>") : -len("</script>")]
        harness = f"""
const payload = {json.dumps(payload)};
global.document = {{
  getElementById(id) {{
    if (id === "keyword-analysis-data") return {{ textContent: JSON.stringify(payload) }};
    return null;
  }},
  addEventListener() {{}},
  createElement() {{ return {{ id: "", className: "", textContent: "" }}; }}
}};
global.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}}
}};
global.window = {{}};
global.navigator = {{}};
{script}
initializeAnalysisDefaults();
const terms = discoveredTerms(selectedAnalysisPapers()).map((item) => item.term);
if (!terms.includes("interfacial resistance")) {{
  throw new Error("expected domain term, got " + terms.join(","));
}}
["june 2026", "2026 earlyview", "earlyview solid", "2026 earlyview solid"].forEach((term) => {{
  if (terms.includes(term)) {{
    throw new Error("metadata term should be filtered: " + terms.join(","));
  }}
}});
"""

        result = _run_node_script(node, harness)

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
