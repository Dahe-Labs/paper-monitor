import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from paper_monitor.models import Article
from paper_monitor.sources import (
    build_arxiv_url,
    build_crossref_urls,
    fetch_all_sources,
    fetch_arxiv,
    fetch_crossref,
    fetch_url,
    parse_arxiv_response,
    parse_crossref_response,
    parse_openalex_response,
    parse_rss_feed,
)


class FakeHTTPResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.data


class SourceParsingTests(unittest.TestCase):
    def test_parses_rss_items_into_articles(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Nature Energy</title>
            <item>
              <title>Fast lithium transport in halide solid electrolytes</title>
              <link>https://www.nature.com/articles/example</link>
              <description>Solid electrolyte discovery for batteries.</description>
              <pubDate>Sat, 20 Jun 2026 09:00:00 GMT</pubDate>
              <dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">doi:10.1038/example</dc:identifier>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss_feed(xml.encode("utf-8"), source_name="Nature Energy RSS")

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].journal, "Nature Energy")
        self.assertEqual(articles[0].doi, "10.1038/example")
        self.assertEqual(articles[0].published, "2026-06-20")
        self.assertEqual(articles[0].detected, "2026-06-20")
        self.assertEqual(articles[0].source, "Nature Energy RSS")

    def test_parses_namespaced_rdf_feed_items(self):
        xml = """<?xml version="1.0"?>
        <rdf:RDF
          xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns="http://purl.org/rss/1.0/"
          xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
          <channel rdf:about="https://feeds.nature.com/nenergy/rss/current">
            <title>Nature Energy</title>
          </channel>
          <item rdf:about="https://www.nature.com/articles/example">
            <title>Solid-state battery interfaces</title>
            <link>https://www.nature.com/articles/example</link>
            <description>doi:10.1038/s41560-026-example</description>
            <prism:publicationDate>2026-06-20</prism:publicationDate>
          </item>
        </rdf:RDF>
        """

        articles = parse_rss_feed(xml.encode("utf-8"), source_name="Nature Energy RSS")

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].journal, "Nature Energy")
        self.assertEqual(articles[0].doi, "10.1038/s41560-026-example")
        self.assertEqual(articles[0].published, "2026-06-20")
        self.assertEqual(articles[0].detected, "2026-06-20")

    def test_prefers_clean_configured_rss_name_when_channel_title_contains_it(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Wiley: Advanced Energy Materials: Table of Contents</title>
            <item>
              <title>Solid-state battery interfaces</title>
              <link>https://advanced.onlinelibrary.wiley.com/doi/example</link>
              <description>Solid electrolyte interface.</description>
              <pubDate>Sat, 20 Jun 2026 09:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss_feed(xml.encode("utf-8"), source_name="Advanced Energy Materials")

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].journal, "Advanced Energy Materials")

    def test_parses_crossref_response_into_articles(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Interface design for all-solid-state batteries"],
                        "container-title": ["Advanced Energy Materials"],
                        "DOI": "10.1002/example",
                        "URL": "https://doi.org/10.1002/example",
                        "abstract": "<jats:p>Solid electrolyte interface.</jats:p>",
                        "published-print": {"date-parts": [[2026, 6, 20]]},
                        "author": [
                            {"given": "Ada", "family": "Lovelace"},
                            {"name": "Battery Research Group"},
                        ],
                    }
                ]
            }
        }

        articles = parse_crossref_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Interface design for all-solid-state batteries")
        self.assertEqual(articles[0].journal, "Advanced Energy Materials")
        self.assertEqual(articles[0].published, "2026-06-20")
        self.assertEqual(articles[0].detected, "2026-06-20")
        self.assertEqual(articles[0].authors, ("Ada Lovelace", "Battery Research Group"))

    def test_parses_crossref_future_issue_date_with_created_detected_date(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Dilatometric analysis in all-solid-state batteries"],
                        "container-title": ["Journal of Power Sources"],
                        "DOI": "10.1016/j.jpowsour.2026.240745",
                        "URL": "https://doi.org/10.1016/j.jpowsour.2026.240745",
                        "published-print": {"date-parts": [[2026, 10]]},
                        "published": {"date-parts": [[2026, 10]]},
                        "issued": {"date-parts": [[2026, 10]]},
                        "created": {"date-parts": [[2026, 6, 21]], "date-time": "2026-06-21T10:00:02Z"},
                        "deposited": {"date-parts": [[2026, 6, 22]], "date-time": "2026-06-22T18:19:02Z"},
                    }
                ]
            }
        }

        articles = parse_crossref_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(articles[0].published, "2026-10")
        self.assertEqual(articles[0].detected, "2026-06-21")

    def test_parses_crossref_future_online_date_with_created_detected_date(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Battery pack integration"],
                        "container-title": ["International Journal for Research in Applied Science and Engineering Technology"],
                        "DOI": "10.22214/ijraset.2026.83506",
                        "URL": "https://doi.org/10.22214/ijraset.2026.83506",
                        "published-online": {"date-parts": [[2026, 6, 30]]},
                        "published": {"date-parts": [[2026, 6, 30]]},
                        "issued": {"date-parts": [[2026, 6, 30]]},
                        "created": {"date-parts": [[2026, 6, 21]], "date-time": "2026-06-21T13:50:37Z"},
                    }
                ]
            }
        }

        articles = parse_crossref_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(articles[0].published, "2026-06-30")
        self.assertEqual(articles[0].detected, "2026-06-21")

    def test_strips_markup_from_crossref_titles(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Cascade H<sub>2</sub>O scavenging for batteries"],
                        "container-title": ["ACS Energy Letters"],
                        "DOI": "10.1021/example",
                        "URL": "https://doi.org/10.1021/example",
                    }
                ]
            }
        }

        articles = parse_crossref_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(articles[0].title, "Cascade H 2 O scavenging for batteries")

    def test_parses_openalex_response_into_articles(self):
        payload = {
            "results": [
                {
                    "display_name": "Lithium metal compatibility in garnet electrolytes",
                    "doi": "https://doi.org/10.1234/openalex",
                    "publication_date": "2026-06-20",
                    "primary_location": {
                        "landing_page_url": "https://example.org/openalex",
                        "source": {"display_name": "Nature Materials"},
                    },
                    "abstract_inverted_index": {
                        "Garnet": [0],
                        "solid": [1],
                        "electrolytes": [2],
                    },
                }
            ]
        }

        articles = parse_openalex_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].doi, "10.1234/openalex")
        self.assertEqual(articles[0].journal, "Nature Materials")
        self.assertEqual(articles[0].abstract, "Garnet solid electrolytes")

    def test_builds_arxiv_url_with_title_query_and_submitted_sort(self):
        url = build_arxiv_url(
            {
                "query": "solid electrolyte OR all-solid-state battery",
                "max_results": 50,
                "search_field": "title",
            }
        )

        query = parse_qs(urlsplit(url).query)
        self.assertEqual(urlsplit(url).netloc, "export.arxiv.org")
        self.assertEqual(query["search_query"], ["ti:(solid electrolyte OR all-solid-state battery)"])
        self.assertEqual(query["max_results"], ["50"])
        self.assertEqual(query["sortBy"], ["submittedDate"])
        self.assertEqual(query["sortOrder"], ["descending"])

    def test_parses_arxiv_atom_response_into_articles(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2606.12345v1</id>
            <updated>2026-06-24T12:00:00Z</updated>
            <published>2026-06-23T08:00:00Z</published>
            <title>Solid electrolyte interfaces for all-solid-state batteries</title>
            <summary>Halide solid electrolyte interphase design.</summary>
            <author><name>Ada Lovelace</name></author>
            <author><name>Grace Hopper</name></author>
            <arxiv:doi>10.48550/arXiv.2606.12345</arxiv:doi>
          </entry>
        </feed>
        """

        articles = parse_arxiv_response(xml.encode("utf-8"))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].journal, "arXiv")
        self.assertEqual(articles[0].source, "arXiv")
        self.assertEqual(articles[0].published, "2026-06-23")
        self.assertEqual(articles[0].detected, "2026-06-24")
        self.assertEqual(articles[0].doi, "10.48550/arxiv.2606.12345")
        self.assertEqual(articles[0].authors, ("Ada Lovelace", "Grace Hopper"))

    def test_fetch_all_sources_queries_arxiv_only_when_enabled(self):
        expected = Article(
            title="Solid electrolyte preprint",
            journal="arXiv",
            url="https://arxiv.org/abs/2606.12345",
            doi="",
            published="2026-06-23",
            abstract="",
            source="arXiv",
        )
        disabled = {"rss": [], "crossref": {"enabled": False}, "openalex": {"enabled": False}}
        enabled = {
            "rss": [],
            "crossref": {"enabled": False},
            "openalex": {"enabled": False},
            "arxiv": {"enabled": True},
        }

        with patch("paper_monitor.sources.fetch_arxiv", return_value=[expected]) as arxiv:
            self.assertEqual(fetch_all_sources(disabled), [])
            self.assertEqual(fetch_all_sources(enabled), [expected])

        self.assertEqual(arxiv.call_count, 1)

    def test_fetch_arxiv_uses_configured_timeout(self):
        xml = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>"""

        with patch("paper_monitor.sources.fetch_url", return_value=xml) as fetch:
            fetch_arxiv({"query": "solid electrolyte", "timeout_seconds": 9})

        self.assertEqual(fetch.call_args.kwargs["timeout"], 9)

    def test_fetch_all_sources_continues_when_one_source_fails(self):
        expected = Article(
            title="Solid electrolyte paper",
            journal="Nature Energy",
            url="https://example.org/paper",
            doi="10.1000/source",
            published="2026-06-20",
            abstract="",
            source="Crossref",
        )
        source_config = {
            "rss": [{"name": "Broken RSS", "url": "https://example.org/broken.rss"}],
            "crossref": {"enabled": True},
            "openalex": {"enabled": False},
        }

        with patch("paper_monitor.sources.fetch_url", side_effect=RuntimeError("network failed")):
            with patch("paper_monitor.sources.fetch_crossref", return_value=[expected]):
                articles = fetch_all_sources(source_config)

        self.assertEqual(articles, [expected])

    def test_fetch_url_retries_with_curl_when_site_returns_client_challenge_html(self):
        challenge = b"""<!DOCTYPE html>
        <html lang="en">
          <head>
            <title>Client Challenge</title>
          </head>
        </html>
        """
        rss = b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"></rdf:RDF>'

        with patch("paper_monitor.sources.urllib.request.urlopen", return_value=FakeHTTPResponse(challenge)):
            with patch("paper_monitor.sources.shutil.which", return_value="/usr/bin/curl"):
                with patch("paper_monitor.sources.subprocess.check_output", return_value=rss) as curl:
                    result = fetch_url("https://feeds.nature.com/nenergy/rss/current")

        self.assertEqual(result, rss)
        self.assertIn("/usr/bin/curl", curl.call_args.args[0])

    def test_builds_crossref_urls_per_allowlisted_journal(self):
        urls = build_crossref_urls(
            {
                "days_back": 15,
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "mailto": "person@example.com",
                "journal_titles": ["Nature Energy", "Advanced Energy Materials"],
            }
        )

        self.assertEqual(len(urls), 2)
        self.assertTrue(all("query.bibliographic=solid+electrolyte" in url for url in urls))
        self.assertTrue(all("from-created-date%3A" in url for url in urls))
        self.assertTrue(all("sort=created" in url for url in urls))
        self.assertTrue(all("from-pub-date" not in url for url in urls))
        self.assertTrue(all("sort=published" not in url for url in urls))
        self.assertTrue(any("query.container-title=Nature+Energy" in url for url in urls))
        self.assertTrue(any("query.container-title=Advanced+Energy+Materials" in url for url in urls))
        self.assertTrue(all("rows=25" in url for url in urls))

    def test_builds_crossref_urls_with_exact_created_date_range(self):
        urls = build_crossref_urls(
            {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
            }
        )

        self.assertEqual(len(urls), 1)
        self.assertIn("from-created-date%3A2026-06-01", urls[0])
        self.assertIn("until-created-date%3A2026-06-24", urls[0])
        self.assertIn("type%3Ajournal-article", urls[0])
        self.assertNotIn("from-pub-date", urls[0])

    def test_builds_crossref_urls_with_cursor_and_date_chunks_for_exhaustive_search(self):
        urls = build_crossref_urls(
            {
                "date_from": "2026-01-01",
                "date_to": "2026-02-15",
                "date_chunk_days": 31,
                "rows_per_journal": 1000,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "cursor_pagination": True,
            }
        )

        self.assertEqual(len(urls), 2)
        first_query = parse_qs(urlsplit(urls[0]).query)
        second_query = parse_qs(urlsplit(urls[1]).query)
        self.assertEqual(first_query["cursor"], ["*"])
        self.assertEqual(first_query["rows"], ["1000"])
        self.assertIn("from-created-date:2026-01-01", first_query["filter"][0])
        self.assertIn("until-created-date:2026-01-31", first_query["filter"][0])
        self.assertIn("from-created-date:2026-02-01", second_query["filter"][0])
        self.assertIn("until-created-date:2026-02-15", second_query["filter"][0])

    def test_builds_crossref_urls_with_title_query_and_select_for_fast_analysis(self):
        urls = build_crossref_urls(
            {
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
                "rows_per_journal": 1000,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "cursor_pagination": True,
                "query_field": "title",
                "select_fields": ["DOI", "title", "container-title", "URL", "published", "published-print", "published-online", "created"],
            }
        )

        query = parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(query["query.title"], ["solid electrolyte"])
        self.assertNotIn("query.bibliographic", query)
        self.assertIn("select", query)
        self.assertIn("title", query["select"][0])
        self.assertIn("created", query["select"][0])

    def test_fetch_crossref_continues_when_one_journal_query_fails(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Garnet electrolyte interface"],
                        "container-title": ["Nature Energy"],
                        "DOI": "10.1038/crossref-ok",
                        "URL": "https://doi.org/10.1038/crossref-ok",
                    }
                ]
            }
        }

        def fake_fetch(url):
            if "Nature+Materials" in url:
                raise RuntimeError("temporary failure")
            return json.dumps(payload).encode("utf-8")

        articles = fetch_crossref(
            {
                "days_back": 15,
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Materials", "Nature Energy"],
            },
            fetch=fake_fetch,
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].doi, "10.1038/crossref-ok")

    def test_fetch_crossref_cursor_paginates_until_short_page(self):
        calls = []

        def payload(items, next_cursor):
            return {
                "message": {
                    "items": items,
                    "next-cursor": next_cursor,
                }
            }

        def fake_item(index):
            return {
                "title": ["Solid electrolyte paper %s" % index],
                "container-title": ["Nature Energy"],
                "DOI": "10.1038/cursor-%s" % index,
                "URL": "https://doi.org/10.1038/cursor-%s" % index,
            }

        def fake_fetch(url):
            calls.append(url)
            query = parse_qs(urlsplit(url).query)
            cursor = query.get("cursor", [""])[0]
            if cursor == "*":
                return json.dumps(payload([fake_item(1), fake_item(2)], "cursor-page-2")).encode("utf-8")
            if cursor == "cursor-page-2":
                return json.dumps(payload([fake_item(3)], "cursor-page-3")).encode("utf-8")
            raise AssertionError("unexpected cursor %s" % cursor)

        articles = fetch_crossref(
            {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 2,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "cursor_pagination": True,
                "max_cursor_pages": 5,
                "max_workers": 1,
            },
            fetch=fake_fetch,
        )

        self.assertEqual([article.doi for article in articles], ["10.1038/cursor-1", "10.1038/cursor-2", "10.1038/cursor-3"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[1]).query)["cursor"], ["cursor-page-2"])

    def test_fetch_crossref_reuses_cache_for_cursor_paginated_urls(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Cached cursor paper"],
                        "container-title": ["Nature Energy"],
                        "DOI": "10.1038/cached-cursor",
                        "URL": "https://doi.org/10.1038/cached-cursor",
                    }
                ]
            }
        }
        calls = []

        def fake_fetch(url):
            calls.append(url)
            return json.dumps(payload).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "cursor_pagination": True,
                "max_workers": 1,
                "cache_dir": str(Path(temp_dir) / "crossref-cache"),
                "cache_ttl_seconds": 3600,
            }

            first = fetch_crossref(config, fetch=fake_fetch)
            second = fetch_crossref(
                config,
                fetch=lambda _url: (_ for _ in ()).throw(AssertionError("cache should avoid cursor fetch")),
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(first[0].doi, "10.1038/cached-cursor")
        self.assertEqual(second[0].doi, "10.1038/cached-cursor")

    def test_fetch_crossref_retries_rate_limited_urls(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Retried solid electrolyte paper"],
                        "container-title": ["Nature Energy"],
                        "DOI": "10.1038/retried",
                        "URL": "https://doi.org/10.1038/retried",
                    }
                ]
            }
        }
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
            return json.dumps(payload).encode("utf-8")

        articles = fetch_crossref(
            {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "max_workers": 1,
                "retry_count": 2,
            },
            fetch=fake_fetch,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(articles[0].doi, "10.1038/retried")

    def test_fetch_crossref_combines_cache_and_retry_without_recursive_fetch(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Cached retried solid electrolyte paper"],
                        "container-title": ["Nature Energy"],
                        "DOI": "10.1038/cached-retry",
                        "URL": "https://doi.org/10.1038/cached-retry",
                    }
                ]
            }
        }
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
            return json.dumps(payload).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "max_workers": 1,
                "retry_count": 2,
                "cache_dir": str(Path(temp_dir) / "crossref-cache"),
                "cache_ttl_seconds": 3600,
            }

            first = fetch_crossref(config, fetch=fake_fetch)
            second = fetch_crossref(
                config,
                fetch=lambda _url: (_ for _ in ()).throw(AssertionError("cache should avoid retried fetch")),
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(first[0].doi, "10.1038/cached-retry")
        self.assertEqual(second[0].doi, "10.1038/cached-retry")

    def test_fetch_crossref_uses_configured_timeout(self):
        payload = {"message": {"items": []}}

        with patch("paper_monitor.sources.fetch_url", return_value=json.dumps(payload).encode("utf-8")) as fetch:
            fetch_crossref(
                {
                    "days_back": 15,
                    "rows_per_journal": 25,
                    "query": "solid electrolyte",
                    "journal_titles": ["Nature Energy"],
                    "timeout_seconds": 7,
                    "max_workers": 1,
                }
            )

        self.assertEqual(fetch.call_args.kwargs["timeout"], 7)

    def test_fetch_crossref_reuses_fresh_cached_url_response(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Cached solid electrolyte paper"],
                        "container-title": ["Nature Energy"],
                        "DOI": "10.1038/cached",
                        "URL": "https://doi.org/10.1038/cached",
                    }
                ]
            }
        }
        calls = []

        def fake_fetch(url):
            calls.append(url)
            return json.dumps(payload).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "rows_per_journal": 25,
                "query": "solid electrolyte",
                "journal_titles": ["Nature Energy"],
                "timeout_seconds": 7,
                "max_workers": 1,
                "cache_dir": str(Path(temp_dir) / "crossref-cache"),
                "cache_ttl_seconds": 3600,
            }

            first = fetch_crossref(config, fetch=fake_fetch)
            second = fetch_crossref(
                config,
                fetch=lambda _url: (_ for _ in ()).throw(AssertionError("cache should avoid network fetch")),
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(first[0].doi, "10.1038/cached")
        self.assertEqual(second[0].doi, "10.1038/cached")


if __name__ == "__main__":
    unittest.main()
