import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .analysis_refresh import run_crossref_keyword_analysis
from .app_identity import DISPLAY_NAME
from .article_lifecycle import ArticleLifecycle, RefreshRunStatus
from .config import load_app_config, write_default_config
from .dashboard_writer import write_latest_dashboard
from .refresh_execution import RefreshExecution, RefreshIntent


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
    analyze_parser.add_argument("--journal", action="append", default=[])

    recent_parser = subparsers.add_parser("recent", help="List recently stored matching papers.")
    recent_parser.add_argument("--config", required=True, type=Path)
    recent_parser.add_argument("--limit", type=int, default=20)

    dashboard_parser = subparsers.add_parser("open-dashboard", help="Open the latest local dashboard.")
    dashboard_parser.add_argument("--config", required=True, type=Path)

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

    if args.command == "test-notification":
        return _test_notification(args.title)

    parser.error("Unknown command")
    return 2


def _run(config_path: Path, dry_run: bool) -> int:
    intent = RefreshIntent.VISIBLE if dry_run else RefreshIntent.BACKGROUND
    outcome = RefreshExecution(config_path).execute(intent)
    if outcome.status is RefreshRunStatus.FAILED:
        print(f"Refresh failed: {outcome.error}", file=sys.stderr)
        return 1
    if dry_run:
        print("[DRY RUN] Desktop notifications were skipped.")
    print(
        "Fetched {fetched}, matched {matched}, new {new}, skipped {skipped}".format(
            fetched=outcome.fetched,
            matched=outcome.matched,
            new=outcome.new_matches,
            skipped=outcome.skipped,
        )
    )
    return 0


def _recent(config_path: Path, limit: int) -> int:
    app_config = load_app_config(config_path)
    lifecycle = ArticleLifecycle(app_config.database_path)
    for article in lifecycle.list_articles(limit):
        print("%s | %s | %s" % (article.first_detected_at, article.journal, article.title))
        print("  %s" % article.url)
    return 0


def _open_dashboard(config_path: Path) -> int:
    app_config = load_app_config(config_path)
    write_latest_dashboard(app_config, confirm_presentation=True)
    webbrowser.open(app_config.dashboard_path.resolve().as_uri())
    print("Opened dashboard: %s" % app_config.dashboard_path)
    return 0


def _render_dashboard(config_path: Path) -> int:
    app_config = load_app_config(config_path)
    dashboard_path = write_latest_dashboard(app_config, confirm_presentation=True)
    print(json.dumps({"dashboard_path": str(dashboard_path)}, ensure_ascii=False))
    return 0


def _test_notification(title: str) -> int:
    from .windows_notification import WindowsArticleNotificationAdapter

    try:
        sent = WindowsArticleNotificationAdapter().deliver(
            {
                "title": title,
                "journal": DISPLAY_NAME,
                "url": "https://example.org",
                "doi": "",
                "source": "local",
            },
            Path.cwd() / "latest.html",
        )
    except Exception as exc:
        print("Failed to send test notification: %s" % exc, file=sys.stderr)
        return 1

    if not sent:
        print(_notification_failure_hint(), file=sys.stderr)
        return 1

    print("Sent test notification.")
    return 0


def _notification_failure_hint() -> str:
    return (
        "Failed to send test notification. Install the Windows dependencies "
        "and make sure Windows notifications are enabled."
    )


if __name__ == "__main__":
    raise SystemExit(main())
