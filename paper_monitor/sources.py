import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .models import Article, normalize_doi


USER_AGENT = "paper-monitor/0.1 (local personal research monitor)"


def fetch_url(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()

    if _looks_like_client_challenge(data):
        curl_data = _fetch_url_with_curl(url, timeout)
        if not _looks_like_client_challenge(curl_data):
            return curl_data
        raise RuntimeError("received client challenge HTML instead of feed/API response")

    return data


def fetch_all_sources(source_config: Dict[str, object]) -> List[Article]:
    articles: List[Article] = []
    for feed in source_config.get("rss", []):
        if not isinstance(feed, dict):
            continue
        url = str(feed.get("url", ""))
        if not url:
            continue
        try:
            articles.extend(parse_rss_feed(fetch_url(url), str(feed.get("name") or url)))
        except Exception as error:
            _warn("RSS source failed: %s (%s)" % (url, error))

    crossref = source_config.get("crossref", {})
    if isinstance(crossref, dict) and crossref.get("enabled", True):
        try:
            articles.extend(fetch_crossref(crossref))
        except Exception as error:
            _warn("Crossref source failed: %s" % error)

    openalex = source_config.get("openalex", {})
    if isinstance(openalex, dict) and openalex.get("enabled", False):
        api_key = str(openalex.get("api_key", "")).strip()
        if api_key:
            try:
                articles.extend(fetch_openalex(openalex))
            except Exception as error:
                _warn("OpenAlex source failed: %s" % error)

    arxiv = source_config.get("arxiv", {})
    if isinstance(arxiv, dict) and arxiv.get("enabled", False):
        try:
            articles.extend(fetch_arxiv(arxiv))
        except Exception as error:
            _warn("arXiv source failed: %s" % error)

    return articles


def fetch_crossref(config: Dict[str, object], fetch: Optional[Callable[[str], bytes]] = None) -> List[Article]:
    articles: List[Article] = []
    urls = build_crossref_urls(config)
    timeout = int(config.get("timeout_seconds", 10))
    max_workers = max(1, int(config.get("max_workers", 6)))
    cursor_pagination = bool(config.get("cursor_pagination"))
    max_cursor_pages = max(1, int(config.get("max_cursor_pages", 100)))
    retry_count = max(0, int(config.get("retry_count", 0)))
    retry_base_seconds = max(0.0, float(config.get("retry_base_seconds", 0.75)))
    retry_max_seconds = max(retry_base_seconds, float(config.get("retry_max_seconds", 8.0)))
    fetch_one = fetch or (lambda url: fetch_url(url, timeout=timeout))
    if retry_count > 0:
        network_fetch = fetch_one
        fetch_one = lambda url, network_fetch=network_fetch: _fetch_url_with_retries(
            url,
            network_fetch,
            retry_count,
            retry_base_seconds,
            retry_max_seconds,
        )
    cache_dir = str(config.get("cache_dir") or "").strip()
    cache_ttl_seconds = int(config.get("cache_ttl_seconds") or 0)
    if cache_dir and cache_ttl_seconds > 0:
        network_fetch = fetch_one
        fetch_one = lambda url, network_fetch=network_fetch: _fetch_url_with_cache(
            url,
            Path(cache_dir),
            cache_ttl_seconds,
            network_fetch,
        )

    if max_workers == 1 or len(urls) <= 1:
        for url in urls:
            if cursor_pagination:
                articles.extend(_fetch_crossref_url_pages(url, fetch_one, max_cursor_pages))
            else:
                articles.extend(_fetch_crossref_url(url, fetch_one))
        return articles

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
        if cursor_pagination:
            future_to_url = {
                executor.submit(_fetch_crossref_url_pages, url, fetch_one, max_cursor_pages): url
                for url in urls
            }
        else:
            future_to_url = {executor.submit(fetch_one, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result = future.result()
                if cursor_pagination:
                    articles.extend(result)
                else:
                    articles.extend(parse_crossref_response(result, source_name="Crossref"))
            except Exception as error:
                _warn("Crossref query failed: %s (%s)" % (_redact_query_url(url), error))
    return articles


def _fetch_crossref_url(url: str, fetch: Callable[[str], bytes]) -> List[Article]:
    try:
        return parse_crossref_response(fetch(url), source_name="Crossref")
    except Exception as error:
        _warn("Crossref query failed: %s (%s)" % (_redact_query_url(url), error))
        return []


def _fetch_crossref_url_pages(url: str, fetch: Callable[[str], bytes], max_pages: int) -> List[Article]:
    articles: List[Article] = []
    current_url = url
    rows = _rows_from_url(url)
    seen_cursors = set()

    for _page in range(max_pages):
        try:
            payload = _crossref_payload(fetch(current_url))
        except Exception as error:
            _warn("Crossref query failed: %s (%s)" % (_redact_query_url(current_url), error))
            return articles

        message = payload.get("message", {})
        items = message.get("items", []) if isinstance(message, dict) else []
        articles.extend(_crossref_articles_from_payload(payload, source_name="Crossref"))
        if len(items) < rows:
            return articles

        next_cursor = str(message.get("next-cursor") or "") if isinstance(message, dict) else ""
        if not next_cursor or next_cursor in seen_cursors:
            return articles
        seen_cursors.add(next_cursor)
        current_url = _replace_query_param(current_url, "cursor", next_cursor)

    return articles


def _fetch_url_with_cache(url: str, cache_dir: Path, ttl_seconds: int, fetch: Callable[[str], bytes]) -> bytes:
    cached = _read_cached_url_response(url, cache_dir, ttl_seconds)
    if cached is not None:
        return cached

    data = fetch(url)
    _write_cached_url_response(url, cache_dir, data)
    return data


def _read_cached_url_response(url: str, cache_dir: Path, ttl_seconds: int) -> Optional[bytes]:
    cache_path = _crossref_cache_path(url, cache_dir)
    try:
        if not cache_path.exists():
            return None
        if time.time() - cache_path.stat().st_mtime > ttl_seconds:
            return None
        return cache_path.read_bytes()
    except OSError:
        return None


def _write_cached_url_response(url: str, cache_dir: Path, data: bytes) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = _crossref_cache_path(url, cache_dir)
        temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temp_path.write_bytes(data)
        temp_path.replace(cache_path)
    except OSError:
        return


def _fetch_url_with_retries(
    url: str,
    fetch: Callable[[str], bytes],
    retry_count: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
) -> bytes:
    for attempt in range(retry_count + 1):
        try:
            return fetch(url)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt >= retry_count:
                _close_http_error(error)
                raise
            _close_http_error(error)
            time.sleep(_retry_delay_seconds(error, attempt, retry_base_seconds, retry_max_seconds))
    return fetch(url)


def _close_http_error(error: urllib.error.HTTPError) -> None:
    close = getattr(error, "close", None)
    if callable(close):
        close()
    fp = getattr(error, "fp", None)
    if fp is not None:
        fp_close = getattr(fp, "close", None)
        if callable(fp_close):
            fp_close()
        error.fp = None


def _retry_delay_seconds(
    error: urllib.error.HTTPError,
    attempt: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after:
        try:
            return min(retry_max_seconds, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(retry_max_seconds, retry_base_seconds * (2 ** attempt))


def _crossref_cache_path(url: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / ("%s.json" % digest)


def build_crossref_urls(config: Dict[str, object]) -> List[str]:
    days_back = int(config.get("days_back", 3))
    query = str(config.get("query", "solid electrolyte OR all-solid-state battery"))
    query_field = _crossref_query_field(config.get("query_field"))
    select_fields = _crossref_select_fields(config.get("select_fields"))
    mailto = str(config.get("mailto", "")).strip()
    from_date = str(config.get("date_from") or "").strip() or (date.today() - timedelta(days=days_back)).isoformat()
    until_date = str(config.get("date_to") or "").strip()
    journal_titles = [str(title) for title in config.get("journal_titles", []) if str(title).strip()]
    cursor_pagination = bool(config.get("cursor_pagination"))
    date_ranges = _crossref_date_ranges(from_date, until_date, int(config.get("date_chunk_days") or 0))
    urls = []
    if journal_titles:
        for journal_title in journal_titles:
            for range_from, range_until in date_ranges:
                params = _crossref_params(
                    query=query,
                    query_field=query_field,
                    from_date=range_from,
                    until_date=range_until,
                    rows=_bounded_crossref_rows(config.get("rows_per_journal", 25)),
                    mailto=mailto,
                    select_fields=select_fields,
                )
                if cursor_pagination:
                    params["cursor"] = "*"
                params["query.container-title"] = journal_title
                urls.append("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
        return urls

    for range_from, range_until in date_ranges:
        params = _crossref_params(
            query=query,
            query_field=query_field,
            from_date=range_from,
            until_date=range_until,
            rows=_bounded_crossref_rows(config.get("rows", 100)),
            mailto=mailto,
            select_fields=select_fields,
        )
        if cursor_pagination:
            params["cursor"] = "*"
        urls.append("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
    return urls


def fetch_arxiv(config: Dict[str, object], fetch: Optional[Callable[[str], bytes]] = None) -> List[Article]:
    timeout = int(config.get("timeout_seconds", 20))
    fetch_one = fetch or (lambda url: fetch_url(url, timeout=timeout))
    return parse_arxiv_response(fetch_one(build_arxiv_url(config)))


def build_arxiv_url(config: Dict[str, object]) -> str:
    query = str(config.get("query") or "solid electrolyte").strip()
    search_field = str(config.get("search_field") or "title").strip().lower()
    if search_field in {"title", "ti"}:
        search_query = "ti:(%s)" % query
    elif search_field in {"abstract", "abs"}:
        search_query = "abs:(%s)" % query
    else:
        search_query = "all:(%s)" % query
    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": str(_bounded_arxiv_results(config.get("max_results", 100))),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)


def _bounded_arxiv_results(value: object) -> int:
    try:
        rows = int(value)
    except (TypeError, ValueError):
        rows = 100
    return min(2000, max(1, rows))


def _crossref_params(
    query: str,
    query_field: str,
    from_date: str,
    until_date: str,
    rows: int,
    mailto: str,
    select_fields: Optional[List[str]] = None,
) -> Dict[str, str]:
    filters = ["from-created-date:%s" % from_date]
    if until_date:
        filters.append("until-created-date:%s" % until_date)
    filters.append("type:journal-article")
    params = {
        "query.%s" % query_field: query,
        "filter": ",".join(filters),
        "rows": str(rows),
        "sort": "created",
        "order": "desc",
    }
    if select_fields:
        params["select"] = ",".join(select_fields)
    if mailto:
        params["mailto"] = mailto
    return params


def _crossref_query_field(value: object) -> str:
    clean = str(value or "bibliographic").strip().lower()
    if clean == "title":
        return "title"
    return "bibliographic"


def _crossref_select_fields(value: object) -> Optional[List[str]]:
    if not isinstance(value, list):
        return None
    fields = []
    seen = set()
    for item in value:
        field = str(item or "").strip()
        if not field or field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return fields or None


def _crossref_date_ranges(from_date: str, until_date: str, chunk_days: int) -> List[tuple]:
    if chunk_days <= 0 or not until_date:
        return [(from_date, until_date)]
    try:
        current = date.fromisoformat(from_date)
        final = date.fromisoformat(until_date)
    except ValueError:
        return [(from_date, until_date)]
    if final < current:
        return [(from_date, until_date)]

    ranges = []
    while current <= final:
        range_end = min(current + timedelta(days=chunk_days - 1), final)
        ranges.append((current.isoformat(), range_end.isoformat()))
        current = range_end + timedelta(days=1)
    return ranges


def _bounded_crossref_rows(value: object) -> int:
    try:
        rows = int(value)
    except (TypeError, ValueError):
        rows = 100
    return min(1000, max(1, rows))


def fetch_openalex(config: Dict[str, object]) -> List[Article]:
    days_back = int(config.get("days_back", 3))
    query = str(config.get("query", "solid electrolyte all-solid-state battery"))
    api_key = str(config.get("api_key", "")).strip()
    from_date = (date.today() - timedelta(days=days_back)).isoformat()
    filters = "from_publication_date:%s,type:article" % from_date
    params = {
        "search": query,
        "filter": filters,
        "per_page": str(int(config.get("per_page", 100))),
        "sort": "publication_date:desc",
        "select": "display_name,doi,publication_date,primary_location,abstract_inverted_index",
        "api_key": api_key,
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    return parse_openalex_response(fetch_url(url), source_name="OpenAlex")


def parse_rss_feed(data: bytes, source_name: str) -> List[Article]:
    root = ET.fromstring(data)
    channel = _first_child(root, "channel")
    channel_title = _rss_journal_title(
        _child_text(channel, "title") if channel is not None else "",
        source_name,
    )
    articles: List[Article] = []

    for item in _children_by_name(root, "item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link") or _child_text(item, "guid")
        description = _strip_markup(_child_text(item, "description") or _child_text(item, "summary"))
        detected = _child_text(item, "pubDate") or _child_text(item, "published") or _child_text(item, "updated")
        published = (
            _child_text(item, "publicationDate")
            or _child_text(item, "date")
            or _child_text(item, "published")
            or detected
        )
        doi = _extract_doi(" ".join(_all_text(item)))
        articles.append(
            Article(
                title=title,
                journal=channel_title,
                url=link,
                doi=doi,
                published=_normalize_publication_date(published),
                abstract=description,
                source=source_name,
                detected=_normalize_publication_date(detected or published),
            )
        )

    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = _child_text(entry, "title")
        link = _atom_link(entry)
        summary = _strip_markup(_child_text(entry, "summary"))
        published = _child_text(entry, "published") or _child_text(entry, "updated")
        doi = _extract_doi(" ".join(_all_text(entry)))
        articles.append(
            Article(
                title=title,
                journal=channel_title,
                url=link,
                doi=doi,
                published=_normalize_publication_date(published),
                abstract=summary,
                source=source_name,
                detected=_normalize_publication_date(published),
            )
        )

    return [article for article in articles if article.title and article.url]


def _rss_journal_title(channel_title: str, source_name: str) -> str:
    if channel_title and source_name and _normalize_feed_label(source_name) in _normalize_feed_label(channel_title):
        return source_name
    return channel_title or source_name


def parse_crossref_response(data: bytes, source_name: str = "Crossref") -> List[Article]:
    return _crossref_articles_from_payload(_crossref_payload(data), source_name=source_name)


def _crossref_payload(data: bytes) -> Dict[str, object]:
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _crossref_articles_from_payload(payload: Dict[str, object], source_name: str = "Crossref") -> List[Article]:
    items = payload.get("message", {}).get("items", [])
    articles: List[Article] = []
    for item in items:
        title = _strip_markup(_first_list_value(item.get("title")))
        journal = _strip_markup(_first_list_value(item.get("container-title")))
        doi = normalize_doi(str(item.get("DOI", "")))
        articles.append(
            Article(
                title=title,
                journal=journal,
                url=str(item.get("URL", "")) or ("https://doi.org/" + doi if doi else ""),
                doi=doi,
                published=_crossref_published_date(item),
                abstract=_strip_markup(str(item.get("abstract", ""))),
                source=source_name,
                detected=_crossref_detected_date(item),
                authors=_crossref_authors(item),
            )
        )
    return [article for article in articles if article.title]


def _rows_from_url(url: str) -> int:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    rows = (query.get("rows") or ["100"])[0]
    return _bounded_crossref_rows(rows)


def _replace_query_param(url: str, name: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    updated = []
    for key, current_value in query:
        if key == name:
            updated.append((key, value))
            replaced = True
        else:
            updated.append((key, current_value))
    if not replaced:
        updated.append((name, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(updated), parsed.fragment)
    )


def parse_openalex_response(data: bytes, source_name: str = "OpenAlex") -> List[Article]:
    payload = json.loads(data.decode("utf-8"))
    articles: List[Article] = []
    for item in payload.get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        doi = normalize_doi(str(item.get("doi") or ""))
        published = str(item.get("publication_date") or "")
        articles.append(
            Article(
                title=str(item.get("display_name") or ""),
                journal=str(source.get("display_name") or ""),
                url=str(location.get("landing_page_url") or ("https://doi.org/" + doi if doi else "")),
                doi=doi,
                published=published,
                abstract=_uninvert_abstract(item.get("abstract_inverted_index") or {}),
                source=source_name,
                detected=published,
            )
        )
    return [article for article in articles if article.title]


def parse_arxiv_response(data: bytes, source_name: str = "arXiv") -> List[Article]:
    root = ET.fromstring(data)
    articles: List[Article] = []
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        published = _child_text(entry, "published")
        updated = _child_text(entry, "updated")
        url = _atom_link(entry) or _child_text(entry, "id")
        doi = normalize_doi(_child_text(entry, "doi") or _extract_doi(" ".join(_all_text(entry))))
        articles.append(
            Article(
                title=_strip_markup(_child_text(entry, "title")),
                journal="arXiv",
                url=url,
                doi=doi,
                published=_normalize_publication_date(published),
                abstract=_strip_markup(_child_text(entry, "summary")),
                source=source_name,
                detected=_normalize_publication_date(updated or published),
                authors=_atom_authors(entry),
            )
        )
    return [article for article in articles if article.title and article.url]


def _atom_authors(entry: ET.Element) -> tuple:
    names = []
    for author in entry.findall("{http://www.w3.org/2005/Atom}author"):
        name = _strip_markup(_child_text(author, "name"))
        if name:
            names.append(name)
    return tuple(names)


def _first_list_value(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _crossref_published_date(item: Dict[str, object]) -> str:
    return (
        _crossref_date_value(item.get("published-online"))
        or _crossref_date_value(item.get("published-print"))
        or _crossref_date_value(item.get("published"))
        or _crossref_date_value(item.get("issued"))
        or ""
    )


def _crossref_detected_date(item: Dict[str, object]) -> str:
    return (
        _crossref_date_value(item.get("created"))
        or _crossref_date_value(item.get("deposited"))
        or _crossref_date_value(item.get("indexed"))
        or _crossref_published_date(item)
    )


def _crossref_authors(item: Dict[str, object]) -> tuple:
    authors = item.get("author")
    if not isinstance(authors, list):
        return ()
    names = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = _crossref_author_name(author)
        if name:
            names.append(name)
    return tuple(names)


def _crossref_author_name(author: Dict[str, object]) -> str:
    literal = _strip_markup(str(author.get("name") or ""))
    if literal:
        return literal
    given = _strip_markup(str(author.get("given") or ""))
    family = _strip_markup(str(author.get("family") or ""))
    return " ".join(part for part in (given, family) if part).strip()


def _crossref_date_value(raw: object) -> str:
    if isinstance(raw, dict):
        parts = raw.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            values = parts[0]
            if not values:
                return ""
            year = _crossref_date_part_int(values[0])
            if year is None or not 1 <= year <= 9999:
                return ""
            if len(values) <= 1:
                return "%04d" % year

            month = _crossref_date_part_int(values[1])
            if month is None or not 1 <= month <= 12:
                return "%04d" % year
            if len(values) <= 2:
                return "%04d-%02d" % (year, month)

            day = _crossref_date_part_int(values[2])
            if day is None:
                return "%04d-%02d" % (year, month)
            try:
                date(year, month, day)
            except ValueError:
                return "%04d-%02d" % (year, month)
            return "%04d-%02d-%02d" % (year, month, day)
    return ""


def _crossref_date_part_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_publication_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\b\d{4}-\d{2}-\d{2}(?=\D|$)", text)
    if match is not None:
        return match.group(0)
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return text
    return parsed.date().isoformat()


def _uninvert_abstract(index: Dict[str, Iterable[int]]) -> str:
    words: Dict[int, str] = {}
    for word, positions in index.items():
        for position in positions:
            words[int(position)] = word
    return " ".join(words[position] for position in sorted(words))


def _first_child(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in element.iter():
        if _local_name(child.tag) == name:
            return child
    return None


def _children_by_name(element: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in element.iter() if _local_name(child.tag) == name]


def _child_text(element: Optional[ET.Element], name: str) -> str:
    if element is None:
        return ""
    for child in list(element):
        if _local_name(child.tag) == name and child.text:
            return unescape(child.text.strip())
    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _all_text(element: ET.Element) -> List[str]:
    return [text.strip() for text in element.itertext() if text and text.strip()]


def _atom_link(entry: ET.Element) -> str:
    for child in entry.findall("{http://www.w3.org/2005/Atom}link"):
        href = child.attrib.get("href")
        if href:
            return href
    return ""


def _strip_markup(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _normalize_feed_label(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _extract_doi(value: str) -> str:
    match = re.search(r"(?:doi:\s*|https?://doi\.org/)?(10\.\d{4,9}/[^\s<>\"]+)", value, re.I)
    if not match:
        return ""
    return normalize_doi(match.group(1).rstrip(".,;)"))


def _warn(message: str) -> None:
    print("warning: " + message, file=sys.stderr)


def _redact_query_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    journal = (query.get("query.container-title") or [""])[0]
    if journal:
        return "journal=%s" % journal
    return parsed.netloc + parsed.path


def _looks_like_client_challenge(data: bytes) -> bool:
    head = data[:4096].decode("utf-8", errors="ignore").casefold()
    return (
        ("<!doctype html" in head or "<html" in head)
        and ("client challenge" in head or "_fs-ch" in head)
    )


def _fetch_url_with_curl(url: str, timeout: int) -> bytes:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("received client challenge HTML and curl is not available")
    return subprocess.check_output(
        [
            curl,
            "-L",
            "-sS",
            "--max-time",
            str(timeout),
            "-A",
            USER_AGENT,
            url,
        ]
    )
