# Paper Monitor

[中文说明](README.zh-CN.md)

Paper Monitor is a local desktop monitor for newly published research papers. The current build focuses on solid-state battery literature and combines journal-scoped Crossref/RSS/arXiv retrieval, local deduplication, keyword analysis, and a native macOS app.

The app runs locally. It does not require an LLM service, and OpenAlex is disabled by default. arXiv is available as an optional preprint source, but it is not selected by default.

## Features

- Native macOS Dock app with an application menu for manual refresh, settings, dashboard access, and notification testing.
- Local notifications for newly matched papers.
- Background monitoring continues while windows are closed, until the app is quit.
- Crossref, RSS, and optional arXiv retrieval with journal scope controls.
- Local SQLite deduplication so repeated papers are not notified again.
- Settings Apply workflow with visible unsaved/saved state.
- HTML dashboard grouped by detected date, with sorting by time, impact factor, and relevance.
- Keyword analysis with date range, journal scope, candidate term filtering, block terms, taxonomy editing, and compact analysis paper list.
- Configurable search terms, excluded terms, journal scope, refresh interval, and Top N journal selection.
- Journal metric metadata from `journal_metrics.json`.
- Early Windows tray source is included for contributors, but the published binary release is currently macOS only.

## Download

Download the latest macOS build from the GitHub Releases page.

After extracting the ZIP, move `Paper Monitor.app` to `Applications` or `$HOME/Applications`, then open it. The build is ad-hoc signed for local distribution, so macOS may ask you to confirm the first launch from System Settings or by right-clicking the app and choosing Open.

## Build From Source

Requirements:

- macOS with Xcode command line tools
- Swift Package Manager
- Python 3

Run the Python test suite:

```bash
python3 -m pytest
```

Run the native macOS tests:

```bash
cd macos/PaperMonitorApp
swift test
```

Build the macOS app:

```bash
scripts/build_macos_app.sh
```

The built app is written to:

```text
dist/Paper Monitor.app
```

## Configuration

The app bundles `config.example.json` and creates a user-writable runtime copy on first launch. Runtime files are stored under:

```text
$HOME/Library/Application Support/PaperMonitor
```

Useful settings include:

- `interval_seconds`: refresh interval while the app is running.
- `max_notifications`: maximum notifications sent per refresh.
- `journal_scope.top_n`: default Top N journal scope.
- `journal_scope.selected_journals`: manually selected journals, including `arXiv` when the optional preprint source is enabled.
- `include_terms`: search and matching terms.
- `exclude_terms`: terms used to suppress irrelevant matches.
- `sources.crossref`: Crossref retrieval settings.
- `sources.arxiv`: optional arXiv preprint retrieval settings.

The personal `config.json`, runtime database, logs, and Crossref cache are intentionally excluded from this repository.

## Repository Layout

```text
paper_monitor/          Python retrieval, filtering, storage, dashboard, and analysis logic
macos/PaperMonitorApp/   Native macOS wrapper
tests/                          Python tests
scripts/                        Build and install helpers
windows/                        Early Windows tray entry point
journal_metrics.json            Journal metadata used by filters and dashboard
config.example.json             Public default configuration template
```

## Privacy

Paper Monitor stores runtime data locally. It does not upload your reading history or matched papers to a server. Crossref/RSS requests are made directly from your machine to the configured data sources.

## License

MIT License. See `LICENSE`.
