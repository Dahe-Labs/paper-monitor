# Paper Monitor

[中文说明](README.zh-CN.md)

Paper Monitor is a local-first desktop app for tracking newly published research. It periodically searches Crossref, RSS, and optional arXiv sources, filters papers against your journals and research terms, stores the results in a shared local SQLite lifecycle, and notifies you only when genuinely new content has not already been presented in the app.

The default configuration focuses on solid-state batteries, while the bundled 300-journal catalog spans AI, computing, engineering, health, life science, physical science, and social science. Search terms, journal scope, and research directions are fully configurable. Paper Monitor needs no cloud backend or LLM service, and it does not upload your reading history.

## Architecture

1. A scheduled or manual refresh starts a bounded worker that retrieves and filters papers, commits the result to the local lifecycle database, sends any eligible notification, and exits.
2. Scheduled refreshes, tray actions, and visible refreshes all use the same SQLite-backed article state instead of maintaining separate caches.
3. The Dashboard reads that local state directly, so opening the app immediately shows the latest stored results without starting another network scan.
4. Publication dates drive the visible timeline; first-detected timestamps remain internal to retention and notification decisions.
5. Papers older than 30 days are hard-deleted from the active store. The home timeline uses compact metadata and does not display abstracts.

On Windows, Task Scheduler wakes the refresh worker only when a scan is due. The main Python/WebView UI exits when its window closes. An optional small native C tray can remain available, and a separate sign-in task can start only that tray silently without opening the app or running a scan.

## Features

- Native macOS Dock app and a native Windows Dashboard/Settings window.
- Non-resident Windows background monitoring through account-scoped Task Scheduler tasks.
- Independent silent sign-in startup for the lightweight native tray, with no window or immediate network scan.
- Crossref, RSS, and optional arXiv retrieval with configurable journal and keyword scope.
- One local SQLite lifecycle for scheduled, tray, and visible refreshes.
- Deduplicated notifications that are suppressed once a paper has already been presented.
- A 30-day active result window with permanent deletion after expiry.
- Settings Apply workflow with visible unsaved/saved state.
- Custom search directions with editable names and keyword-derived queries.
- Refresh schedules with 1 day / 2 days intervals and an optional daily start time.
- Local Dashboard grouped by source publication date, showing title, authors, journal, local impact reference, and URL without displaying abstracts.
- Keyword analysis with date range, journal scope, full journal names, candidate-term filtering, block terms, taxonomy editing, and a compact paper list.
- Configurable search terms, excluded terms, journal scope, refresh interval, and Top N journal selection.
- Searchable and category-filtered metadata for 300 formal journals from `journal_metrics.json`.
- A frozen local OpenAlex two-year mean citedness snapshot used as a reference, not as a hard filtering rule or Clarivate JIF.
- Latest Releases list macOS and Windows assets under the same version number when both builds are available.

## Download

Download the latest build from the GitHub Releases page.

For macOS, download the `.pkg` installer, run it, and open `Paper Monitor.app` from `/Applications`. The build is ad-hoc signed for local distribution, so macOS may ask you to confirm the first launch from System Settings or by right-clicking the app and choosing Open.

For Windows, use `Paper-Monitor-Windows-x.y.z-Setup.exe` for a normal per-user installation. A portable ZIP and standalone EXE are also published. See [README_WINDOWS.md](README_WINDOWS.md) for details.

When publishing a new release, keep the visible macOS and Windows asset versions aligned:

```text
Paper-Monitor-macOS-x.y.z.pkg
Paper-Monitor-Windows-x.y.z-Setup.exe
Paper-Monitor-Windows-x.y.z.zip
Paper-Monitor-Windows-x.y.z.exe
```

## Build From Source

Requirements:

- Python 3.12
- Windows with PowerShell and Inno Setup for Windows packaging
- macOS with Xcode command line tools and Swift Package Manager for the macOS app

Run the Python test suite:

```bash
python -m unittest discover -s tests
```

Build the complete Windows release:

`requirements-windows.txt` contains the human-maintained top-level dependency ranges. CI, releases, and reproducible local Windows packaging install from `requirements-windows.lock.txt`.

```powershell
python -m pip install -r requirements-windows.lock.txt
.\scripts\package_windows_release.ps1 -Version 0.1.13
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
%APPDATA%\PaperMonitor
```

Useful settings include:

- `interval_seconds`: background refresh interval; on Windows, saving Settings updates the non-resident scheduled task.
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
paper_monitor/           Python retrieval, filtering, storage, dashboard, and app logic
macos/PaperMonitorApp/   Native macOS app
windows/                 Windows entry point, installer, and icon
tests/                   Python regression tests
scripts/                 Build, install, and release helpers
journal_metrics.json     Journal metadata used by filters and dashboard
config.example.json      Public default configuration template
```

## Privacy

Paper Monitor stores runtime data locally. It does not upload your reading history or matched papers to a server. Crossref/RSS requests are made directly from your machine to the configured data sources.

## License

MIT License. See `LICENSE`.
