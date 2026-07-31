# Paper Monitor

[中文说明](README.zh-CN.md)

Paper Monitor is a local-first desktop app for tracking newly published research. It periodically searches Crossref, RSS, and optional arXiv sources, filters papers against your journals and research terms, stores the results in a shared local SQLite lifecycle, and notifies you only when genuinely new content has not already been presented in the app.

The default configuration focuses on solid-state batteries, while the bundled 300-journal catalog spans AI, computing, engineering, health, life science, physical science, and social science. Search terms, journal scope, and research directions are fully configurable. Paper Monitor needs no cloud backend or LLM service, and it does not upload your reading history.

## Architecture

1. A scheduled or manual refresh starts a bounded worker that retrieves and filters papers, commits the result to the local lifecycle database, sends any eligible notification, and exits.
2. Scheduled refreshes, tray actions, and visible refreshes all use the same SQLite-backed article state instead of maintaining separate caches.
3. The Dashboard reads that local state directly, so opening the app immediately shows the latest stored results without starting another network scan.
4. First-detected timestamps drive the visible timeline so newly found papers appear immediately; publication dates are shown separately when available.
5. Papers older than 30 days are hard-deleted from the active store. The home timeline uses compact metadata and does not display abstracts.

On Windows, Task Scheduler wakes the refresh worker only when a scan is due. The main Python/WebView UI exits when its window closes. An optional small native C tray can remain available, and a separate sign-in task can start only that tray silently without opening the app or running a scan.

## Features

- Native Windows Dashboard/Settings window.
- Non-resident Windows background monitoring through account-scoped Task Scheduler tasks.
- Independent silent sign-in startup for the lightweight native tray, with no window or immediate network scan.
- Crossref, RSS, and optional arXiv retrieval with configurable journal and keyword scope.
- One local SQLite lifecycle for scheduled, tray, and visible refreshes.
- Deduplicated notifications that are suppressed once a paper has already been presented.
- Compact Windows article notifications grouped by local delivery date; clicking an item opens its paper URL.
- A 30-day active result window with permanent deletion after expiry.
- Settings Apply workflow with visible unsaved/saved state.
- Ready-to-use search directions for sulfide and halide solid electrolytes, LATP, LLZO/LLZTO, silicon anodes, and sodium batteries.
- Custom search directions with editable names and keyword-derived queries.
- Refresh schedules with 1 day / 2 days intervals and an optional daily start time.
- Local Dashboard grouped by source publication date, showing title, authors, journal, local impact reference, and URL without displaying abstracts.
- Keyword analysis with date range, journal scope, full journal names, candidate-term filtering, block terms, taxonomy editing, and a compact paper list.
- Configurable search terms, excluded terms, explicit journal selection, and refresh interval.
- Searchable and category-filtered metadata for 300 formal journals from `journal_metrics.json`.
- A frozen local OpenAlex two-year mean citedness snapshot used as a reference, not as a hard filtering rule or Clarivate JIF.
- Windows-only installer, portable ZIP, and standalone EXE release assets.

## Download

Download the latest build from the GitHub Releases page.

For Windows, use `Paper-Monitor-Windows-x.y.z-Setup.exe` for a normal per-user installation. A portable ZIP and standalone EXE are also published. See [README_WINDOWS.md](README_WINDOWS.md) for details.

Each release contains only the Windows assets:

```text
Paper-Monitor-Windows-x.y.z-Setup.exe
Paper-Monitor-Windows-x.y.z.zip
Paper-Monitor-Windows-x.y.z.exe
SHA256SUMS-x.y.z.txt
```

## Build From Source

Requirements:

- Python 3.12
- Windows with PowerShell and Inno Setup for Windows packaging

Run the Python test suite:

```bash
python -m unittest discover -s tests
```

Build the complete Windows release:

`requirements-windows.txt` contains the human-maintained top-level dependency ranges. CI, releases, and reproducible local Windows packaging install from `requirements-windows.lock.txt`.

```powershell
python -m pip install -r requirements-windows.lock.txt
.\scripts\package_windows_release.ps1 -Version 0.1.16
```

## Configuration

The app bundles `config.example.json` and creates a user-writable runtime copy on first launch. Runtime files are stored under:

```text
%APPDATA%\PaperMonitor
```

Useful settings include:

- `interval_seconds`: background refresh interval, defaulting to `86400` seconds (once per day); on Windows, saving Settings updates the non-resident scheduled task.
- `refresh_start_time`: exact local start time in `HH:MM` format for background monitoring, defaulting to `09:00`.
- `max_notifications`: maximum article notifications shown per refresh (up to 20 on Windows).
- `journal_scope.selected_journals`: the authoritative retrieval scope, including `arXiv` when the optional preprint source is enabled.
- `include_terms`: search and matching terms.
- `exclude_terms`: terms used to suppress irrelevant matches.
- `sources.crossref`: Crossref retrieval settings.
- `sources.arxiv`: optional arXiv preprint retrieval settings.

The legacy root-level `journals` list remains a read fallback for older configurations. Crossref `journal_titles` is derived from `journal_scope.selected_journals`, so a stale source-level list cannot override the journals selected in Settings.

Keyword Analysis starts from that same configured formal-journal scope and may narrow it for one run; it cannot add a journal that is not selected in Settings. All 300 formal catalog journals are supported without a separate Top N cap.

The personal `config.json`, runtime database, logs, and Crossref cache are intentionally excluded from this repository.

## Repository Layout

```text
paper_monitor/           Python retrieval, filtering, storage, dashboard, and app logic
windows/                 Windows entry point, installer, and icon
tests/                   Python regression tests
scripts/                 Build, install, and release helpers
journal_metrics.json     Journal metadata used by filters and dashboard
config.example.json      Public default configuration template
```

## Privacy

Paper Monitor stores runtime data locally. It does not upload your reading history or matched papers to a server. Crossref/RSS requests are made directly from your machine to the configured data sources.
