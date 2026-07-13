# Paper Monitor

[中文说明](README.zh-CN.md)

Paper Monitor is a local desktop monitor for newly published research papers. Its default query focuses on solid-state battery literature, while its 300-journal interdisciplinary catalog covers AI, computing, engineering, health, life science, physical science, and social science fields.

The app runs locally. It does not require an LLM service, and OpenAlex is disabled by default. arXiv is available as an optional preprint source, but it is not selected by default.

## Features

- Native macOS Dock app with an application menu for manual refresh, settings, dashboard access, and notification testing.
- Native Windows app with a single Dashboard/Settings window, a lightweight native tray, non-resident scheduled refresh, and toast notifications.
- Local notifications for newly matched papers.
- In normal Windows background-monitoring mode, Task Scheduler starts a short-lived refresh worker only when a scan is due; Python, the local HTTP bridge, and WebView do not remain resident between scans. The optional native C tray stays available after the window closes without loading the search engine or UI runtime.
- Crossref, RSS, and optional arXiv retrieval with journal scope controls.
- Local SQLite deduplication so repeated papers are not notified again.
- Settings Apply workflow with visible unsaved/saved state.
- Custom search directions with editable names and keyword-derived queries.
- Refresh schedules with 1 day / 2 days intervals and an optional daily start time.
- HTML dashboard grouped by detected date, with sorting by time, two-year impact, and relevance.
- Keyword analysis with date range, journal scope, candidate term filtering, block terms, taxonomy editing, and compact analysis paper list.
- Configurable search terms, excluded terms, journal scope, refresh interval, and Top N journal selection.
- Searchable and category-filtered metadata for 300 formal journals from `journal_metrics.json`.
- A frozen OpenAlex two-year mean citedness snapshot labeled `2Y Impact`; it is not Clarivate JIF.
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
.\scripts\package_windows_release.ps1 -Version 0.1.8
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
