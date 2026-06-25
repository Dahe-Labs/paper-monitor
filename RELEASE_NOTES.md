# Paper Monitor 0.1.4

Windows tray release.

## Included

- Windows system tray app with Open Dashboard, Settings, Refresh Now, Test Notification, and Quit actions.
- Local Windows dashboard bridge for keyword-analysis actions, bound to `127.0.0.1` with a per-session token.
- PowerShell build and install scripts for creating a no-console PyInstaller executable and enabling startup for the current user.
- Windows release package documentation in `README_WINDOWS.md`.

## Changed

- Windows builds now embed `config.example.json`, `journal_metrics.json`, and the application icon so a downloaded executable has the default runtime resources available on first launch.
- Windows build scripts detect real Python installations and avoid the Microsoft Store Python alias.
- Documentation now describes both macOS and Windows downloads.

## Notes

- This release is not code-signed.
- Windows may show a SmartScreen warning the first time the executable is downloaded or opened.
- Runtime data, logs, caches, and personal configuration are not included in the source repository.

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
