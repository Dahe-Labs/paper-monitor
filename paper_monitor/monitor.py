from dataclasses import dataclass
from typing import Callable, List

from .filtering import FilterConfig, MatchResult, match_article
from .models import Article
from .storage import ArticleStore


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


def run_once(
    config: MonitorConfig,
    store: ArticleStore,
    fetch_articles: Callable[[], List[Article]],
    notify: Callable[[Article, MatchResult], None],
) -> RunSummary:
    run_id = store.start_run()
    try:
        fetched_articles = fetch_articles()
        matched_pairs = []
        skipped = 0
        seen_identities = set()
        for article in fetched_articles:
            if article.identity in seen_identities:
                skipped += 1
                continue
            seen_identities.add(article.identity)
            result = match_article(article, config.filter_config)
            store.record_candidate(
                run_id=run_id,
                article=article,
                matched=result.matched,
                reason=result.reason,
                matched_terms=result.matched_terms,
                journal_match=result.journal_match,
            )
            if result.matched:
                matched_pairs.append((article, result))
            else:
                skipped += 1

        new_articles = store.add_new_articles(article for article, _ in matched_pairs)
        result_by_identity = {article.identity: result for article, result in matched_pairs}
        for article in new_articles[: config.max_notifications]:
            notify(article, result_by_identity[article.identity])

        store.finish_run(
            run_id,
            fetched=len(fetched_articles),
            matched=len(matched_pairs),
            new_matches=len(new_articles),
            skipped=skipped,
        )

    except Exception as exc:
        store.fail_run(run_id, str(exc))
        raise

    return RunSummary(
        run_id=run_id,
        fetched=len(fetched_articles),
        matched=len(matched_pairs),
        new_matches=len(new_articles),
        skipped=skipped,
    )
