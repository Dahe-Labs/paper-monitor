from dataclasses import dataclass, field
from typing import Callable, Dict, List

from .filtering import FilterConfig, MatchResult, match_article
from .models import Article
from .sources import SourceFetchError
from .storage import ArticleStore, CandidateRecord

_CANDIDATE_BATCH_SIZE = 250


@dataclass(frozen=True)
class MonitorConfig:
    filter_config: FilterConfig
    max_notifications: int


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    fetched: int
    matched: int
    new_matches: int
    skipped: int
    source_statuses: List[Dict[str, object]] = field(default_factory=list)


def run_once(
    config: MonitorConfig,
    store: ArticleStore,
    fetch_articles: Callable[[], List[Article]],
    notify: Callable[[Article, MatchResult], None],
) -> RunSummary:
    run_id = store.start_run()
    try:
        fetched_articles = fetch_articles()
        source_statuses = list(getattr(fetched_articles, "source_statuses", ()) or ())
        if getattr(fetched_articles, "all_failed", False):
            source_error = getattr(fetched_articles, "all_failed_error", None)
            if isinstance(source_error, BaseException):
                setattr(source_error, "source_statuses", source_statuses)
                raise source_error
            failure = SourceFetchError(str(source_error or "Every configured paper source failed."))
            setattr(failure, "source_statuses", source_statuses)
            raise failure

        matched_pairs = []
        candidate_records = []
        fetched_count = len(fetched_articles)
        skipped = 0
        seen_identities = set()
        for article in fetched_articles:
            if article.identity in seen_identities:
                skipped += 1
                continue
            seen_identities.add(article.identity)
            result = match_article(article, config.filter_config)
            candidate_records.append(
                CandidateRecord(
                    article=article,
                    matched=result.matched,
                    reason=result.reason,
                    matched_terms=result.matched_terms,
                    journal_match=result.journal_match,
                )
            )
            if result.matched:
                matched_pairs.append((article, result))
            else:
                skipped += 1

            if len(candidate_records) >= _CANDIDATE_BATCH_SIZE:
                store.record_candidates(run_id, candidate_records)
                candidate_records.clear()

        if candidate_records:
            store.record_candidates(run_id, candidate_records)
        # Source result lists can include large abstracts and API payload-derived
        # metadata. Release unmatched articles before SQLite deduplication/notify.
        del fetched_articles
        new_articles = store.add_new_articles(article for article, _ in matched_pairs)
        result_by_identity = {article.identity: result for article, result in matched_pairs}
        for article in new_articles[: config.max_notifications]:
            notify(article, result_by_identity[article.identity])

        store.finish_run(
            run_id,
            fetched=fetched_count,
            matched=len(matched_pairs),
            new_matches=len(new_articles),
            skipped=skipped,
        )

    except Exception as exc:
        store.fail_run(run_id, str(exc))
        raise

    return RunSummary(
        run_id=run_id,
        fetched=fetched_count,
        matched=len(matched_pairs),
        new_matches=len(new_articles),
        skipped=skipped,
        source_statuses=source_statuses,
    )
