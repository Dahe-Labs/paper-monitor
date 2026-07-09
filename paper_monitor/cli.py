import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .analysis_refresh import run_crossref_keyword_analysis
from .app_identity import DISPLAY_NAME
from .app_refresh import run_app_refresh
from .config import load_app_config, write_default_config
from .dashboard import write_dashboard
from .dashboard_writer import write_latest_dashboard
from .filtering import MatchResult
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope
from .launchd import build_launch_agent_plist
from .models import Article
from .monitor import run_once
from .notify import notify_article
from .sources import fetch_all_sources
from .storage import ArticleStore


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-monitor",
        description="Local desktop monitor for solid-state battery papers.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Write a starter JSON config.")
    init_parser.add_argument("--config", required=True, type=Path)

    run_parser = subparsers.add_parser("run", help="Fetch sources, filter papers, and notify.")
    run_parser.add_argument("--config", required=True, type=Path)
    run_parser.add_argument("--dry-run", action="store_true", help="Print notifications instead of using the system notifier.")

    app_refresh_parser = subparsers.add_parser("app-refresh", help="Run once for the native desktop app and emit JSON.")
    app_refresh_parser.add_argument("--config", required=True, type=Path)

    render_dashboard_parser = subparsers.add_parser(
        "render-dashboard",
        help="Regenerate the local dashboard HTML from the stored latest run and emit JSON.",
    )
    render_dashboard_parser.add_argument("--config", required=True, type=Path)

    analyze_parser = subparsers.add_parser(
        "analyze-keywords",
        help="Fetch Crossref for a date range and emit a keyword-analysis JSON payload.",
    )
    analyze_parser.add_argument("--config", required=True, type=Path)
    analyze_parser.add_argument("--date-from", required=True)
    analyze_parser.add_argument("--date-to", required=True)
    analyze_parser.add_argument("--sort-mode", choices=("time", "impact_factor", "relevance"), default="time")
    analyze_parser.add_argument("--analysis-depth", choices=("fast", "exhaustive"), default="fast")
    analyze_parser.add_argument("--top-n", type=int, default=30)
    analyze_parser.add_argument("--journal", action="append", default=[])

    recent_parser = subparsers.add_parser("recent", help="List recently stored matching papers.")
    recent_parser.add_argument("--config", required=True, type=Path)
    recent_parser.add_argument("--limit", type=int, default=20)

    dashboard_parser = subparsers.add_parser("open-dashboard", help="Open the latest local dashboard.")
    dashboard_parser.add_argument("--config", required=True, type=Path)

    launchd_parser = subparsers.add_parser("write-launch-agent", help="Write a macOS LaunchAgent plist.")
    launchd_parser.add_argument("--config", required=True, type=Path)
    launchd_parser.add_argument("--output", required=True, type=Path)
    launchd_parser.add_argument("--label", default="com.local.paper-monitor")

    test_parser = subparsers.add_parser("test-notification", help="Send one local desktop test notification.")
    test_parser.add_argument("--title", default=f"{DISPLAY_NAME} test")

    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        write_default_config(args.config)
        print("Wrote config: %s" % args.config)
        return 0

    if args.command == "run":
        return _run(args.config, dry_run=args.dry_run)

    if args.command == "app-refresh":
        print(json.dumps(run_app_refresh(args.config), ensure_ascii=False))
        return 0

    if args.command == "render-dashboard":
        return _render_dashboard(args.config)

    if args.command == "analyze-keywords":
        print(
            json.dumps(
                run_crossref_keyword_analysis(
                    args.config,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    sort_mode=args.sort_mode,
                    analysis_depth=args.analysis_depth,
                    top_n=args.top_n,
                    selected_journals=args.journal or None,
                ),
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "recent":
        return _recent(args.config, args.limit)

    if args.command == "open-dashboard":
        return _open_dashboard(args.config)

    if args.command == "write-launch-agent":
        return _write_launch_agent(args.config, args.output, args.label)

    if args.command == "test-notification":
        return _test_notification(args.title)

    parser.error("Unknown command")
    return 2


def _run(config_path: Path, dry_run: bool) -> int:
    app_config = load_app_config(config_path)
    store = ArticleStore(app_config.database_path)
    notifier = _print_notification if dry_run else (
        lambda article, match: notify_article(article, match, dashboard_path=app_config.dashboard_path)
    )
    summary = run_once(
        config=app_config.monitor_config,
        store=store,
        fetch_articles=lambda: fetch_all_sources(app_config.source_config),
        notify=notifier,
    )
    metrics = load_journal_metrics(app_config.journal_metrics_path)
    write_dashboard(
        app_config.dashboard_path,
        store.latest_run(),
        store.candidates_for_run(summary.run_id),
        metrics,
        AnalysisScope(
            selected_journals=tuple(app_config.monitor_config.filter_config.journals),
            top_n=app_config.journal_scope_top_n,
        ),
    )
    print(
        "Fetched {fetched}, matched {matched}, new {new}, skipped {skipped}".format(
            fetched=summary.fetched,
            matched=summary.matched,
            new=summary.new_matches,
            skipped=summary.skipped,
        )
    )
    return 0


def _recent(config_path: Path, limit: int) -> int:
    app_config = load_app_config(config_path)
    store = ArticleStore(app_config.database_path)
    for article in store.recent_articles(limit):
        print("%s | %s | %s" % (article.published, article.journal, article.title))
        print("  %s" % (article.doi or article.url))
    return 0


def _write_launch_agent(config_path: Path, output: Path, label: str) -> int:
    config_path = config_path.resolve()
    app_config = load_app_config(config_path)
    python_path = _python_for_launch_agent()
    working_directory = config_path.parent
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    (working_directory / "work" / "paper-monitor" / "logs").mkdir(parents=True, exist_ok=True)
    plist_bytes = build_launch_agent_plist(
        label=label,
        python_path=python_path,
        module_name="paper_monitor.cli",
        working_directory=working_directory,
        config_path=config_path,
        interval_seconds=app_config.interval_seconds,
    )
    output.write_bytes(plist_bytes)
    print("Wrote LaunchAgent plist: %s" % output)
    return 0


def _open_dashboard(config_path: Path) -> int:
    app_config = load_app_config(config_path)
    write_latest_dashboard(app_config)
    webbrowser.open(app_config.dashboard_path.resolve().as_uri())
    print("Opened dashboard: %s" % app_config.dashboard_path)
    return 0


def _render_dashboard(config_path: Path) -> int:
    app_config = load_app_config(config_path)
    dashboard_path = write_latest_dashboard(app_config)
    print(json.dumps({"dashboard_path": str(dashboard_path)}, ensure_ascii=False))
    return 0


def _python_for_launch_agent() -> Path:
    return Path(sys.executable)


def _print_notification(article: Article, match: MatchResult) -> None:
    terms = ", ".join(match.matched_terms)
    print("[DRY RUN] %s | %s | %s" % (article.journal, article.title, terms))
    print("          %s" % (article.doi or article.url))


def _test_notification(title: str) -> int:
    article = Article(
        title=title,
        journal=DISPLAY_NAME,
        url="https://example.org",
        doi="",
        published="",
        abstract="",
        source="local",
    )
    try:
        sent = notify_article(article, MatchResult(True, "matched", ["test"], DISPLAY_NAME))
    except Exception as exc:
        print("Failed to send test notification: %s" % exc, file=sys.stderr)
        return 1

    if not sent:
        print(_notification_failure_hint(), file=sys.stderr)
        return 1

    print("Sent test notification.")
    return 0


def _notification_failure_hint() -> str:
    if sys.platform == "win32":
        return (
            "Failed to send test notification. On Windows, install win11toast "
            "from requirements-windows.txt and make sure Windows notifications are enabled."
        )
    if sys.platform == "darwin":
        return (
            "Failed to send test notification. On macOS, install terminal-notifier "
            "or make sure osascript is available."
        )
    return "Failed to send test notification on this platform."


if __name__ == "__main__":
    raise SystemExit(main())
