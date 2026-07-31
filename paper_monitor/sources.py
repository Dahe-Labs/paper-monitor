from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# XML declarations with DTDs or entities are rejected by _parse_xml_payload.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .date_utils import first_iso_date
from .models import Article, normalize_doi
from .refresh_cancellation import RefreshCancellation, RefreshCancelled

USER_AGENT = "paper-monitor/0.1 (local personal research monitor)"
CROSSREF_PUBLIC_LIST_CONCURRENCY_LIMIT = 1
CROSSREF_POLITE_LIST_CONCURRENCY_LIMIT = 3
CROSSREF_PUBLIC_LIST_REQUEST_INTERVAL_SECONDS = 1.0
CROSSREF_POLITE_LIST_REQUEST_INTERVAL_SECONDS = 1.0 / 3.0
SOURCE_ACQUISITION_MAX_WORKERS = 8
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
CROSSREF_CACHE_MAX_FILES = 512
CROSSREF_CACHE_MAX_BYTES = 64 * 1024 * 1024
_CACHE_PRUNE_INTERVAL_SECONDS = 30.0
_CACHE_PRUNE_LOCK = threading.Lock()
_CACHE_LAST_PRUNED: Dict[str, float] = {}


@dataclass(frozen=True)
class DateWindow:
    date_from: str
    date_to: str = ""


class SourceFetchError(RuntimeError):
    """Raised when every configured source attempt fails."""


class SourceFetchResult(list):
    """List-compatible source result carrying structured per-source diagnostics."""

    def __init__(
        self,
        articles: Iterable[Article] = (),
        source_statuses: Optional[Iterable[Dict[str, object]]] = None,
    ):
        super().__init__(articles)
        self.source_statuses = list(source_statuses or ())

    @property
    def all_failed(self) -> bool:
        attempted = [status for status in self.source_statuses if status.get("status") != "skipped"]
        if not attempted:
            return False
        return not any(status.get("status") in {"succeeded", "partial"} for status in attempted)

    @property
    def partial(self) -> bool:
        return bool(self.source_statuses) and not self.all_failed and any(
            status.get("status") in {"failed", "partial"} for status in self.source_statuses
        )

    @property
    def all_failed_error(self) -> SourceFetchError:
        messages = [str(status.get("error") or "").strip() for status in self.source_statuses]
        details = "; ".join(message for message in messages if message)
        if not details:
            details = "Every configured paper source failed."
        return SourceFetchError(details)


def fetch_url(url: str, timeout: int = 30) -> bytes:
    url = _validated_http_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    # _validated_http_url restricts this request to HTTP(S) without embedded credentials.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds the maximum allowed size")

    if _looks_like_client_challenge(data):
        curl_data = _fetch_url_with_curl(url, timeout)
        if not _looks_like_client_challenge(curl_data):
            return curl_data
        raise RuntimeError("received client challenge HTML instead of feed/API response")

    return data


def fetch_all_sources(
    source_config: Dict[str, object],
    *,
    cancellation: Optional[RefreshCancellation] = None,
) -> SourceFetchResult:
    cancellation = cancellation or RefreshCancellation()
    cancellation.checkpoint()
    tasks: List[Callable[[], SourceFetchResult]] = []

    for feed in source_config.get("rss", []):
        if not isinstance(feed, dict):
            continue
        url = str(feed.get("url", ""))
        if not url:
            continue
        source_name = str(feed.get("name") or url)
        tasks.append(
            lambda _url=url, _source_name=source_name: _fetch_source_adapter(
                "RSS",
                _source_name,
                lambda: parse_rss_feed(fetch_url(_url), _source_name),
                cancellation,
            )
        )

    crossref = source_config.get("crossref", {})
    if isinstance(crossref, dict) and crossref.get("enabled", True):
        tasks.append(
            lambda _config=crossref: _fetch_source_adapter(
                "Crossref",
                "",
                lambda: fetch_crossref(_config, cancellation=cancellation),
                cancellation,
            )
        )

    openalex = source_config.get("openalex", {})
    if isinstance(openalex, dict) and openalex.get("enabled", False):
        tasks.append(
            lambda _config=openalex: _fetch_source_adapter(
                "OpenAlex",
                "",
                lambda: fetch_openalex(_config, cancellation=cancellation),
                cancellation,
            )
        )

    arxiv = source_config.get("arxiv", {})
    if isinstance(arxiv, dict) and arxiv.get("enabled", False):
        tasks.append(
            lambda _config=arxiv: _fetch_source_adapter(
                "arXiv",
                "",
                lambda: fetch_arxiv(_config, cancellation=cancellation),
                cancellation,
            )
        )

    if not tasks:
        return SourceFetchResult()
    if len(tasks) == 1:
        return tasks[0]()

    worker_count = min(SOURCE_ACQUISITION_MAX_WORKERS, len(tasks))
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="PaperMonitorSource",
    )
    future_to_index = {
        executor.submit(task): index
        for index, task in enumerate(tasks)
    }
    results: Dict[int, SourceFetchResult] = {}
    try:
        pending = set(future_to_index)
        while pending:
            cancellation.checkpoint()
            completed, pending = concurrent.futures.wait(
                pending,
                timeout=0.1,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in completed:
                results[future_to_index[future]] = future.result()
        cancellation.checkpoint()
    except RefreshCancelled:
        for future in future_to_index:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    except BaseException:
        for future in future_to_index:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    articles: List[Article] = []
    statuses: List[Dict[str, object]] = []
    for index in range(len(tasks)):
        result = results[index]
        articles.extend(result)
        statuses.extend(result.source_statuses)
    return SourceFetchResult(articles, statuses)


def _fetch_source_adapter(
    source: str,
    target: str,
    fetch: Callable[[], Iterable[Article]],
    cancellation: RefreshCancellation,
) -> SourceFetchResult:
    try:
        cancellation.checkpoint()
        fetched = fetch()
        cancellation.checkpoint()
    except RefreshCancelled:
        raise
    except Exception as error:
        detail = " (%s)" % target if target else ""
        _warn("%s source failed%s: %s" % (source, detail, error))
        return SourceFetchResult(
            source_statuses=[
                _source_status(source, "failed", target=target, error=error)
            ]
        )

    articles = list(fetched)
    request_statuses = list(getattr(fetched, "source_statuses", ()))
    request_errors = [
        str(status.get("error") or "").strip()
        for status in request_statuses
        if status.get("status") in {"failed", "partial"}
    ]
    request_had_problem = any(
        status.get("status") in {"failed", "partial"}
        for status in request_statuses
    )
    if getattr(fetched, "all_failed", False):
        status_name = "failed"
    elif request_had_problem:
        status_name = "partial"
    else:
        status_name = "succeeded"
    return SourceFetchResult(
        articles,
        [
            _source_status(
                source,
                status_name,
                target=target,
                count=len(articles),
                error="; ".join(error for error in request_errors[:3] if error),
            )
        ],
    )


def _source_status(
    source: str,
    status: str,
    *,
    target: str = "",
    count: int = 0,
    error: object = "",
) -> Dict[str, object]:
    return {
        "source": str(source),
        "target": str(target),
        "status": str(status),
        "count": max(0, int(count)),
        "error": _compact_error(error),
    }


def _compact_error(error: object, limit: int = 300) -> str:
    text = " ".join(str(error or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."[:limit]


def fetch_crossref(
    config: Dict[str, object],
    fetch: Optional[Callable[[str], bytes]] = None,
    cancellation: Optional[RefreshCancellation] = None,
) -> SourceFetchResult:
    cancellation = cancellation or RefreshCancellation()
    cancellation.checkpoint()
    articles: List[Article] = []
    statuses: List[Dict[str, object]] = []
    urls = build_crossref_urls(config)
    timeout = int(config.get("timeout_seconds", 10))
    requested_max_workers = max(1, int(config.get("max_workers", 6)))
    max_workers = _crossref_effective_max_workers(config, requested_max_workers)
    cursor_pagination = bool(config.get("cursor_pagination"))
    max_cursor_pages = max(1, int(config.get("max_cursor_pages", 100)))
    retry_count = max(0, int(config.get("retry_count", 2)))
    retry_base_seconds = max(0.0, float(config.get("retry_base_seconds", 0.75)))
    retry_max_seconds = max(retry_base_seconds, float(config.get("retry_max_seconds", 8.0)))
    if fetch is None:
        def fetch_one(url: str) -> bytes:
            return fetch_url(url, timeout=timeout)
    else:
        fetch_one = fetch
    request_interval = _crossref_min_request_interval_seconds(config)
    if request_interval > 0:
        fetch_one = _rate_limited_fetch(
            fetch_one,
            request_interval,
            cancellation=cancellation,
        )
    if retry_count > 0:
        network_fetch = fetch_one

        def retrying_fetch(url: str, _network_fetch: Callable[[str], bytes] = network_fetch) -> bytes:
            return _fetch_url_with_retries(
                url,
                _network_fetch,
                retry_count,
                retry_base_seconds,
                retry_max_seconds,
                cancellation=cancellation,
            )

        fetch_one = retrying_fetch
    cache_dir = str(config.get("cache_dir") or "").strip()
    cache_ttl_seconds = int(config.get("cache_ttl_seconds") or 0)
    if cache_dir and cache_ttl_seconds > 0:
        _maybe_prune_crossref_cache(Path(cache_dir), cache_ttl_seconds)
        network_fetch = fetch_one

        def cached_fetch(url: str, _network_fetch: Callable[[str], bytes] = network_fetch) -> bytes:
            return _fetch_url_with_cache(
                url,
                Path(cache_dir),
                cache_ttl_seconds,
                _network_fetch,
            )

        fetch_one = cached_fetch

    uncancelled_fetch = fetch_one

    def cancellable_fetch(
        url: str,
        _fetch: Callable[[str], bytes] = uncancelled_fetch,
    ) -> bytes:
        cancellation.checkpoint()
        data = _fetch(url)
        cancellation.checkpoint()
        return data

    fetch_one = cancellable_fetch

    if max_workers == 1 or len(urls) <= 1:
        for url in urls:
            cancellation.checkpoint()
            if cursor_pagination:
                fetched, error, succeeded = _fetch_crossref_url_pages_result(
                    url,
                    fetch_one,
                    max_cursor_pages,
                    cancellation=cancellation,
                )
            else:
                fetched, error, succeeded = _fetch_crossref_url_result(url, fetch_one)
            articles.extend(fetched)
            statuses.append(
                _source_status(
                    "Crossref request",
                    "partial" if succeeded and error else ("succeeded" if succeeded else "failed"),
                    target=_redact_query_url(url),
                    count=len(fetched),
                    error=error or "",
                )
            )
        return SourceFetchResult(articles, statuses)

    worker_count = min(max_workers, len(urls))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
    remaining_urls = iter(enumerate(urls))
    future_to_request: Dict[concurrent.futures.Future, tuple[int, str]] = {}
    request_results: Dict[int, tuple[List[Article], Dict[str, object]]] = {}

    def submit_next() -> bool:
        cancellation.checkpoint()
        try:
            request_index, url = next(remaining_urls)
        except StopIteration:
            return False
        if cursor_pagination:
            future = executor.submit(
                _fetch_crossref_url_pages_result,
                url,
                fetch_one,
                max_cursor_pages,
                cancellation,
            )
        else:
            future = executor.submit(_fetch_crossref_url_result, url, fetch_one)
        future_to_request[future] = (request_index, url)
        return True

    try:
        for _worker in range(worker_count):
            if not submit_next():
                break
        while future_to_request:
            cancellation.checkpoint()
            completed, _pending = concurrent.futures.wait(
                tuple(future_to_request),
                timeout=0.1,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in completed:
                request_index, url = future_to_request.pop(future)
                fetched, error, succeeded = future.result()
                request_results[request_index] = (
                    fetched,
                    _source_status(
                        "Crossref request",
                        "partial"
                        if succeeded and error
                        else ("succeeded" if succeeded else "failed"),
                        target=_redact_query_url(url),
                        count=len(fetched),
                        error=error or "",
                    ),
                )
                submit_next()
    finally:
        if cancellation.is_requested():
            for future in future_to_request:
                future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
    for request_index in range(len(urls)):
        fetched, status = request_results[request_index]
        articles.extend(fetched)
        statuses.append(status)
    return SourceFetchResult(articles, statuses)


def _crossref_effective_max_workers(config: Dict[str, object], requested_max_workers: int) -> int:
    limit = (
        CROSSREF_POLITE_LIST_CONCURRENCY_LIMIT
        if _crossref_uses_polite_pool(config)
        else CROSSREF_PUBLIC_LIST_CONCURRENCY_LIMIT
    )
    return max(1, min(int(requested_max_workers), limit))


def _crossref_min_request_interval_seconds(config: Dict[str, object]) -> float:
    value = config.get("min_request_interval_seconds")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    if _crossref_uses_polite_pool(config):
        return CROSSREF_POLITE_LIST_REQUEST_INTERVAL_SECONDS
    return CROSSREF_PUBLIC_LIST_REQUEST_INTERVAL_SECONDS


def _crossref_uses_polite_pool(config: Dict[str, object]) -> bool:
    mailto = str(config.get("mailto") or "").strip()
    return bool(mailto)


def _rate_limited_fetch(
    fetch: Callable[[str], bytes],
    min_interval_seconds: float,
    *,
    cancellation: Optional[RefreshCancellation] = None,
) -> Callable[[str], bytes]:
    cancellation = cancellation or RefreshCancellation()
    lock = threading.Lock()
    next_allowed_at = 0.0

    def wrapper(url: str) -> bytes:
        nonlocal next_allowed_at
        with lock:
            now = time.monotonic()
            wait_seconds = next_allowed_at - now
            if wait_seconds > 0:
                cancellation.wait(wait_seconds)
                now = time.monotonic()
            next_allowed_at = now + min_interval_seconds
        return fetch(url)

    return wrapper


def _fetch_crossref_url_result(
    url: str,
    fetch: Callable[[str], bytes],
) -> tuple[List[Article], Optional[BaseException], bool]:
    try:
        return parse_crossref_response(fetch(url), source_name="Crossref"), None, True
    except RefreshCancelled:
        raise
    except Exception as error:
        _warn("Crossref query failed: %s (%s)" % (_redact_query_url(url), error))
        return [], error, False


def _fetch_crossref_url_pages_result(
    url: str,
    fetch: Callable[[str], bytes],
    max_pages: int,
    cancellation: Optional[RefreshCancellation] = None,
) -> tuple[List[Article], Optional[BaseException], bool]:
    cancellation = cancellation or RefreshCancellation()
    articles: List[Article] = []
    current_url = url
    rows = _rows_from_url(url)
    seen_cursors = set()
    fetched_page = False

    for _page in range(max_pages):
        try:
            cancellation.checkpoint()
            payload = _crossref_payload(fetch(current_url))
            cancellation.checkpoint()
        except RefreshCancelled:
            raise
        except Exception as error:
            _warn("Crossref query failed: %s (%s)" % (_redact_query_url(current_url), error))
            return articles, error, fetched_page
        fetched_page = True

        message = payload.get("message", {})
        items = message.get("items", []) if isinstance(message, dict) else []
        articles.extend(_crossref_articles_from_payload(payload, source_name="Crossref"))
        if len(items) < rows:
            return articles, None, True

        next_cursor = str(message.get("next-cursor") or "") if isinstance(message, dict) else ""
        if not next_cursor or next_cursor in seen_cursors:
            return articles, None, True
        seen_cursors.add(next_cursor)
        current_url = _replace_query_param(current_url, "cursor", next_cursor)

    return articles, None, fetched_page


def _fetch_url_with_cache(url: str, cache_dir: Path, ttl_seconds: int, fetch: Callable[[str], bytes]) -> bytes:
    cached = _read_cached_url_response(url, cache_dir, ttl_seconds)
    if cached is not None:
        return cached

    data = fetch(url)
    _write_cached_url_response(url, cache_dir, data, ttl_seconds=ttl_seconds)
    return data


def _read_cached_url_response(url: str, cache_dir: Path, ttl_seconds: int) -> Optional[bytes]:
    cache_path = _crossref_cache_path(url, cache_dir)
    try:
        if not cache_path.exists():
            return None
        if time.time() - cache_path.stat().st_mtime > ttl_seconds:
            cache_path.unlink(missing_ok=True)
            return None
        return cache_path.read_bytes()
    except OSError:
        return None


def _write_cached_url_response(url: str, cache_dir: Path, data: bytes, ttl_seconds: int = 0) -> None:
    temp_path: Optional[Path] = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = _crossref_cache_path(url, cache_dir)
        temp_path = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_bytes(data)
        temp_path.replace(cache_path)
    except OSError:
        return
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    _maybe_prune_crossref_cache(cache_dir, ttl_seconds)


def _maybe_prune_crossref_cache(cache_dir: Path, ttl_seconds: int) -> None:
    now = time.time()
    key = str(cache_dir.expanduser().absolute())
    with _CACHE_PRUNE_LOCK:
        last_pruned = _CACHE_LAST_PRUNED.get(key, 0.0)
        if now - last_pruned < _CACHE_PRUNE_INTERVAL_SECONDS:
            return
        _CACHE_LAST_PRUNED[key] = now
        _prune_crossref_cache(cache_dir, ttl_seconds, now=now)


def _prune_crossref_cache(cache_dir: Path, ttl_seconds: int, *, now: Optional[float] = None) -> None:
    current_time = time.time() if now is None else float(now)
    entries = []
    try:
        candidates = list(cache_dir.glob("*.json"))
    except OSError:
        return

    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        if ttl_seconds > 0 and current_time - stat.st_mtime > ttl_seconds:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        entries.append((stat.st_mtime, stat.st_size, path))

    entries.sort(key=lambda item: item[0], reverse=True)
    kept_bytes = 0
    for index, (_modified, size, path) in enumerate(entries):
        keep = index < CROSSREF_CACHE_MAX_FILES and kept_bytes + size <= CROSSREF_CACHE_MAX_BYTES
        if keep:
            kept_bytes += size
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _fetch_url_with_retries(
    url: str,
    fetch: Callable[[str], bytes],
    retry_count: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
    *,
    cancellation: Optional[RefreshCancellation] = None,
) -> bytes:
    cancellation = cancellation or RefreshCancellation()
    for attempt in range(retry_count + 1):
        cancellation.checkpoint()
        try:
            return fetch(url)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt >= retry_count:
                _close_http_error(error)
                raise
            _close_http_error(error)
            cancellation.wait(
                _retry_delay_seconds(
                    error,
                    attempt,
                    retry_base_seconds,
                    retry_max_seconds,
                )
            )
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
    query = str(config.get("query", "solid electrolyte OR all-solid-state battery"))
    query_field = _crossref_query_field(config.get("query_field"))
    select_fields = _crossref_select_fields(config.get("select_fields"))
    mailto = str(config.get("mailto", "")).strip()
    window = _date_window_from_config(config, default_days_back=3)
    journal_titles = [str(title) for title in config.get("journal_titles", []) if str(title).strip()]
    cursor_pagination = bool(config.get("cursor_pagination"))
    date_ranges = _crossref_date_ranges(window.date_from, window.date_to, int(config.get("date_chunk_days") or 0))
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


def fetch_arxiv(
    config: Dict[str, object],
    fetch: Optional[Callable[[str], bytes]] = None,
    cancellation: Optional[RefreshCancellation] = None,
) -> List[Article]:
    cancellation = cancellation or RefreshCancellation()
    timeout = int(config.get("timeout_seconds", 20))
    fetch_one = fetch or (lambda url: fetch_url(url, timeout=timeout))
    cancellation.checkpoint()
    articles = parse_arxiv_response(fetch_one(build_arxiv_url(config)))
    cancellation.checkpoint()
    return _filter_articles_by_days_back(articles, config.get("days_back", 3))


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


def _filter_articles_by_days_back(articles: List[Article], days_back: object) -> List[Article]:
    try:
        days = max(0, int(days_back))
    except (TypeError, ValueError):
        days = 3
    cutoff = date.today() - timedelta(days=days)
    filtered = []
    for article in articles:
        article_date = first_iso_date(article.detected or article.published)
        if article_date is not None and article_date < cutoff:
            continue
        filtered.append(article)
    return filtered


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


def fetch_openalex(
    config: Dict[str, object],
    fetch: Optional[Callable[[str], bytes]] = None,
    cancellation: Optional[RefreshCancellation] = None,
) -> List[Article]:
    cancellation = cancellation or RefreshCancellation()
    timeout = int(config.get("timeout_seconds", 30))
    fetch_one = fetch or (lambda url: fetch_url(url, timeout=timeout))
    max_pages = _bounded_openalex_pages(config.get("max_pages", 1))
    current_url = build_openalex_url(config, cursor="*" if max_pages > 1 else "")
    articles: List[Article] = []
    seen_cursors = set()

    for _page in range(max_pages):
        cancellation.checkpoint()
        payload = _openalex_payload(fetch_one(current_url))
        cancellation.checkpoint()
        articles.extend(_openalex_articles_from_payload(payload, source_name="OpenAlex"))
        next_cursor = _openalex_next_cursor(payload)
        if max_pages <= 1 or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        current_url = _replace_query_param(current_url, "cursor", next_cursor)
    return articles


def build_openalex_url(config: Dict[str, object], cursor: Optional[str] = None) -> str:
    query = str(config.get("query", "solid electrolyte all-solid-state battery"))
    api_key = str(config.get("api_key", "")).strip()
    if not api_key:
        raise ValueError("sources.openalex.api_key is required when OpenAlex is enabled")
    window = _date_window_from_config(config, default_days_back=3)
    filters = ["from_publication_date:%s" % window.date_from, "type:article"]
    if window.date_to:
        filters.append("to_publication_date:%s" % window.date_to)
    params = {
        "search": query,
        "filter": ",".join(filters),
        "per_page": str(_bounded_openalex_results(config.get("per_page", 100))),
        "sort": "publication_date:desc",
        "select": "id,display_name,doi,publication_date,primary_location,abstract_inverted_index,authorships",
        "api_key": api_key,
    }
    cursor_value = str(config.get("cursor") if cursor is None else cursor).strip()
    if cursor_value:
        params["cursor"] = cursor_value
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _bounded_openalex_results(value: object) -> int:
    try:
        rows = int(value)
    except (TypeError, ValueError):
        rows = 100
    return min(200, max(1, rows))


def _bounded_openalex_pages(value: object) -> int:
    try:
        pages = int(value)
    except (TypeError, ValueError):
        pages = 1
    return min(50, max(1, pages))


def _date_window_from_config(config: Dict[str, object], default_days_back: int, today: Optional[date] = None) -> DateWindow:
    try:
        days_back = max(0, int(config.get("days_back", default_days_back)))
    except (TypeError, ValueError):
        days_back = default_days_back
    current_date = today or date.today()
    date_from = str(config.get("date_from") or "").strip() or (current_date - timedelta(days=days_back)).isoformat()
    date_to = str(config.get("date_to") or "").strip()
    return DateWindow(date_from=date_from, date_to=date_to)


def parse_rss_feed(data: bytes, source_name: str) -> List[Article]:
    root = _parse_xml_payload(data)
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
        source_id = (
            _child_text(item, "guid")
            or _attribute_text(item, "about")
            or doi
            or link
        )
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
                authors=_rss_authors(item),
                source_id=_stable_source_id(source_id),
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
                authors=_atom_authors(entry),
                source_id=_stable_source_id(_child_text(entry, "id") or doi or link),
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
                source_id=_stable_source_id(doi),
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
    return _openalex_articles_from_payload(_openalex_payload(data), source_name=source_name)


def _openalex_payload(data: bytes) -> Dict[str, object]:
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _openalex_articles_from_payload(payload: Dict[str, object], source_name: str = "OpenAlex") -> List[Article]:
    articles: List[Article] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        location = _dict_value(item.get("primary_location"))
        source = _dict_value(location.get("source"))
        doi = normalize_doi(str(item.get("doi") or ""))
        published = str(item.get("publication_date") or "")
        url = str(location.get("landing_page_url") or "")
        if not url and doi:
            url = "https://doi.org/" + doi
        if not url:
            url = str(item.get("id") or "")
        articles.append(
            Article(
                title=str(item.get("display_name") or ""),
                journal=str(source.get("display_name") or ""),
                url=url,
                doi=doi,
                published=published,
                abstract=_uninvert_abstract(item.get("abstract_inverted_index") or {}),
                source=source_name,
                detected=published,
                authors=_openalex_authors(item),
                source_id=_openalex_source_id(item.get("id")),
            )
        )
    return [article for article in articles if article.title and article.url]


def _openalex_next_cursor(payload: Dict[str, object]) -> str:
    meta = _dict_value(payload.get("meta"))
    return str(meta.get("next_cursor") or "").strip()


def _openalex_authors(item: Dict[str, object]) -> tuple:
    authorships = item.get("authorships")
    if not isinstance(authorships, list):
        return ()
    names = []
    seen = set()
    for authorship in authorships:
        author = _dict_value(_dict_value(authorship).get("author"))
        name = _strip_markup(str(author.get("display_name") or ""))
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return tuple(names)


def parse_arxiv_response(data: bytes, source_name: str = "arXiv") -> List[Article]:
    root = _parse_xml_payload(data)
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


def _rss_authors(item: ET.Element) -> tuple:
    names = []
    seen = set()
    for child in list(item):
        if _local_name(child.tag) not in {"author", "creator"}:
            continue
        name = _strip_markup(_child_text(child, "name") or " ".join(child.itertext()))
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return tuple(names)


def _openalex_source_id(value: object) -> str:
    raw = _stable_source_id(value)
    parsed = urllib.parse.urlsplit(raw)
    if parsed.hostname and parsed.hostname.casefold() in {"openalex.org", "www.openalex.org"}:
        work_id = parsed.path.strip("/").split("/")[-1]
        if work_id:
            return _stable_source_id(work_id)
    return raw


def _stable_source_id(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    if not isinstance(index, dict):
        return ""
    words: Dict[int, str] = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            try:
                words[int(position)] = str(word)
            except (TypeError, ValueError):
                continue
    return " ".join(words[position] for position in sorted(words))


def _dict_value(value: object) -> Dict[str, object]:
    return value if isinstance(value, dict) else {}


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


def _attribute_text(element: ET.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local_name(key) == name:
            return unescape(str(value).strip())
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


def _validated_http_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source URL must not contain embedded credentials")
    return value


def _parse_xml_payload(data: bytes) -> ET.Element:
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("XML payload exceeds the maximum allowed size")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, flags=re.IGNORECASE):
        raise ValueError("XML DTD and entity declarations are not allowed")
    # The declaration check above rejects DTD and entity expansion before parsing.
    return ET.fromstring(data)  # nosec B314


def _fetch_url_with_curl(url: str, timeout: int) -> bytes:
    url = _validated_http_url(url)
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("received client challenge HTML and curl is not available")
    data = subprocess.check_output(
        [
            curl,
            "-L",
            "-sS",
            "--proto",
            "=http,https",
            "--proto-redir",
            "=http,https",
            "--max-time",
            str(timeout),
            "-A",
            USER_AGENT,
            url,
        ],
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds the maximum allowed size")
    return data
