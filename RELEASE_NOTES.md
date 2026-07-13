# Paper Monitor 0.1.8

Windows zero-resident monitoring, refresh feedback, and startup performance update.

## Included

- Background monitoring now uses Windows Task Scheduler instead of a resident login/tray process. Each due task performs one refresh and exits, leaving no Paper Monitor process in memory between scans.
- Closing the main window ends the UI session and releases its WebView, Python runtime, and local bridge resources.
- The existing `startup_enabled` setting now controls non-resident background monitoring; upgrades remove the legacy `HKCU` Run entry automatically.
- Uninstall removes the scheduled refresh task and legacy Run entry while preserving user configuration and history.
- Scheduled tasks are isolated per Windows account, detect operational drift, and retry failed runs twice at 15-minute intervals.
- Scheduled notifications use a persistent SQLite outbox, and headless refreshes defer Dashboard rendering until the UI is opened.
- `Refresh Now` runs asynchronously and reports the actual running, succeeded, partial, or failed state, including per-source diagnostics and refreshes already running in another process.
- Dashboard refreshes preserve the current Settings or Keyword Analysis view and scroll position.
- Candidate history uses batched SQLite writes, WAL, indexes, versioned migrations, and interrupted-run recovery.
- Local Dashboard requests validate loopback Host headers, authenticate before reading bounded bodies, and return browser security headers.
- Crossref cache retention is bounded, and Dashboard files are replaced atomically.
- Window and tray child processes launch without a console window, avoiding black console flashes.
- Consolidated Windows launch shortcuts under one `Paper Monitor` entry and removed the separate Settings shortcut; Settings remains available in the app.
- The installer and portable ZIP now use the onedir layout for faster startup, while the standalone EXE remains a onefile build.

## Notes

- Local/manual builds can remain unsigned, but the public `v0.1.8` release workflow requires a trusted Authenticode certificate and prepares a draft release before publication.

# Paper Monitor 0.1.7

Interdisciplinary journal catalog and compact selection update.

## Included

- Expanded the bundled catalog from 50 to 300 formal journals across 12 interdisciplinary categories.
- Added a frozen OpenAlex two-year mean citedness snapshot with a `2Y Impact` label and source metadata for every formal journal.
- Added journal category filters and name/alias search to Windows Settings and Keyword Analysis.
- Replaced large journal cards with compact single-line name and impact rows using bounded, internally scrolling lists.
- Reduced matched-paper card spacing and improved responsive layouts for desktop and narrow Windows app viewports.
- Fixed selected journals reappearing after removal by separating catalog synchronization from rendering and preserving explicit empty selections.
- Added behavior tests for removal, candidate return, empty-selection save/reload, catalog coverage, and responsive UI contracts.

## Notes

- `2Y Impact` is OpenAlex two-year mean citedness, not Clarivate Journal Impact Factor.
- Windows `v0.1.7` artifacts are unsigned until a trusted Authenticode certificate is configured.

# Paper Monitor 0.1.6

Windows reliability and release hardening update.

## Included

- Added a single-instance native Windows Dashboard/Settings window controlled by tray and relaunch actions.
- Added reliable startup route delivery, atomic control metadata, and visible error logging for failed window launches.
- Added process-local and Windows named refresh guards to prevent overlapping tray, Dashboard, and CLI refreshes.
- Added runtime tray visibility updates without stopping background scheduling.
- Added an Inno Setup per-user installer, portable ZIP, standalone EXE, SHA256 manifests, and embedded version metadata.
- Added optional Authenticode signing support to local and GitHub release builds.
- Hardened network source handling with HTTP(S)-only URLs, response-size limits, and DTD/entity rejection for XML feeds.
- Restored the full historical regression suite and expanded it to 248 passing Python tests.

## Notes

- Windows `v0.1.6` artifacts are currently unsigned until a trusted Authenticode certificate is configured.
- Runtime configuration, databases, logs, caches, local build output, and archived releases are excluded from source control.

# Paper Monitor 0.1.5

Settings workflow release.

## Included

- Added a `Custom...` search direction option in Search Settings.
- Custom directions support editable direction names and keyword lists.
- Custom keywords generate Crossref queries with `OR` and OpenAlex queries with spaces.
- Added `1 day` and `2 days` refresh frequency options.
- Replaced the old `24h` label with `1 day`.
- Added optional `Start Time` scheduling in `HH:mm` format. Scheduled refreshes wait until the next matching start time, then continue by the selected interval.
- GitHub Release assets now list macOS `.pkg` and Windows `.exe` downloads under the same version when both builds are available.
- Added a Windows GitHub Actions build workflow so Windows release assets can be generated with the same visible version number as macOS assets.

## Notes

- This release is ad-hoc signed and not notarized.
- Manual `Refresh Now` remains available and is not delayed by `Start Time`.

# Paper Monitor 0.1.3

macOS lifecycle and cleanup release.

## Included

- Paper Monitor now runs as a regular macOS Dock app with a normal application menu.
- Settings, Dashboard, Refresh Now, and Test Notification are available from the left-side macOS app menu.
- Background monitoring continues after closing the Dashboard or Settings windows.
- Reopening the app from the Dock no longer reloads the same Dashboard file, so the current Keyword Analysis view is preserved.
- Menu bar status item code and menu bar-only icon assets were removed.

## Changed

- Removed the `LSUIElement` hidden-agent configuration.
- Removed the right-side menu bar status item path.
- Kept refresh status and notification permission status in the application menu.

## Notes

- This release is ad-hoc signed and not notarized.
- macOS may require right-click Open or approval from System Settings on first launch.
- Runtime data, logs, caches, and personal configuration are not included in the source repository.

# Paper Monitor 0.1.2

Journal source and settings workflow release.

## Included

- Optional arXiv preprint retrieval, disabled by default.
- Separate Preprint Sources section in Journal Filter for arXiv.
- Dashboard summary now reports the actual selected journal/source count.
- Settings window now has an Apply button with unsaved and saved state feedback.
- More stable macOS notification dispatch with a local fallback path.
- Native macOS menu bar app remains hidden from the Dock and runs as a status item.

## Changed

- Top N only applies to formal journals; manually selected arXiv is preserved.
- Crossref journal title filters exclude arXiv while the arXiv source handles preprints.
- The public default journal scope remains Top 15 to keep routine scans smaller.
- Chinese and English documentation now describe the optional arXiv source and Apply workflow.

## Notes

- This release is ad-hoc signed and not notarized.
- macOS may require right-click Open or approval from System Settings on first launch.
- Runtime data, logs, caches, and personal configuration are not included in the source repository.

# Paper Monitor 0.1.1

Internal naming cleanup release.

## Included

- Native macOS menu bar app.
- Local notifications for new matched papers.
- Dashboard with matched papers, date grouping, sorting, and keyword analysis.
- Settings for journal scope, refresh frequency, search terms, and journal filtering.
- Crossref/RSS retrieval and local SQLite deduplication.

## Changed

- Renamed source folders, Swift targets, Python package, Windows entrypoint, app support paths, and launch labels to Paper Monitor naming.

## Notes

- This release is ad-hoc signed and not notarized.
- macOS may require right-click Open or approval from System Settings on first launch.
- Runtime data, logs, caches, and personal configuration are not included in the source repository.
