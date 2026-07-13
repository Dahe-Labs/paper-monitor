# Paper Monitor Release Notes

## 0.1.8

### Zero-Resident Windows Monitoring

- Windows Task Scheduler now wakes a short-lived worker for each due refresh. The worker retrieves, stores, notifies, records diagnostics, and exits instead of keeping the tray, Python runtime, or WebView resident between scans.
- Closing the main window ends the UI session and releases the WebView and local bridge immediately. Reopening Paper Monitor creates a fresh Dashboard session.
- `startup_enabled` remains the compatible configuration key but now means **Background Monitoring**. Saving Settings synchronizes the scheduled task, while disabling it removes the task.
- Upgrades clean the legacy current-user Run entry so older `tray --quiet` startup commands do not survive migration; uninstall also removes the scheduled refresh task.
- Windows shortcuts now use a single `Paper Monitor` entry. The separate Settings shortcut was removed, and Settings remains available as an in-app view.

### Refresh Status And Process Launch

- `Refresh Now` starts asynchronously and reports the actual running, succeeded, partial, or failed state instead of waiting for the request to finish.
- The Dashboard reflects refreshes running in another process, preserves Settings and Keyword Analysis context, and exposes per-source and notification failures.
- Window and tray child processes launch without a console window, avoiding black console flashes.

### Data, Security, And Reliability

- Candidate rows are stored in one SQLite transaction with WAL, query indexes, schema versioning, and recovery of interrupted runs.
- Crossref responses have bounded cache retention, and generated Dashboard files use atomic replacement.
- The loopback Dashboard service validates Host headers, authenticates before reading a body capped at 1 MiB, applies browser security headers, and bounds analysis work.
- External analysis links accept only absolute HTTP(S) destinations.

### Windows Packaging

- The installer and portable ZIP now package the onedir application layout to reduce startup delay.
- The standalone `Paper-Monitor-Windows-0.1.8.exe` remains a onefile build for single-file portability.
- Local/manual artifacts can be unsigned, but public tag builds require a trusted Authenticode certificate and are uploaded to a draft release for review before publication.

## 0.1.7

### Interdisciplinary Journal Catalog

- The bundled catalog now contains 300 formal journals across AI and computer science, engineering, medicine, life sciences, physics, chemistry, materials and energy, environmental science, mathematics, social science, economics, and multidisciplinary research.
- Every formal journal includes a frozen OpenAlex two-year mean citedness value, category, source record, catalog rank, and display label.
- The catalog generator retains the original battery and materials titles, balances subject coverage, rejects implausible merged source records, and normalizes display names.

### Compact Journal Selection

- Windows Settings and Keyword Analysis now support category filtering and journal name/alias search.
- Selected and candidate journals use compact single-line rows with the journal name and `2Y Impact` value.
- Long catalogs scroll inside a bounded pane instead of expanding the entire page.
- Matched-paper cards use tighter spacing, and desktop/narrow layouts were verified without horizontal overflow.

### Selection Reliability

- Removing a journal no longer triggers candidate synchronization during redraw, preventing it from being silently re-selected.
- Explicit empty journal selections are retained instead of falling back to the legacy `journals` field.
- Behavior tests cover add/remove round trips, save/reload persistence, and Dashboard analysis selection.

## 0.1.6

### Windows Window And Background Reliability

- Dashboard and Settings requests now route to one existing native window instead of creating competing window processes.
- Re-launching the executable focuses and routes the existing window, including when it is currently showing Settings.
- Window-control metadata is written atomically, startup route requests are retried, and child-process startup failures are logged instead of silently disappearing.
- Closing the native window now destroys the WebView and local bridge and exits the process instead of hiding a resident window.
- Windows Task Scheduler starts a short-lived `scheduled-refresh` worker only when a scan is due, and a missed run is started when Windows becomes available again.
- Refresh execution uses a process-local lock plus a Windows named guard, preventing scheduled, Dashboard, and CLI refreshes from running concurrently.
- Background refresh and notification failures no longer escape through the no-console runtime and are recorded in `PaperMonitor.log`.

### Windows Installer And Portable Builds

- Windows releases now have an Inno Setup installer artifact named `Paper-Monitor-Windows-<version>-Setup.exe`.
- The installer installs per user under `%LOCALAPPDATA%\Programs\PaperMonitor`, creates Start Menu entries, registers Paper Monitor in Windows installed apps, and provides an uninstaller.
- Desktop shortcut creation remains optional. Background Monitoring is enabled in App Settings and registers a per-user scheduled task instead of a login process.
- Upgrade removes the legacy `PaperMonitor.exe tray --quiet` Run entry; uninstall removes the scheduled task and old Run entry while preserving user data.
- The installer preserves `%APPDATA%\PaperMonitor\config.json` during upgrades and uninstall. It does not install over user configuration.
- Portable release artifacts remain available as `Paper-Monitor-Windows-<version>.zip` and `Paper-Monitor-Windows-<version>.exe`. Portable builds are directly runnable and must not register uninstall entries or installer registry keys.
- Windows executables now include FileVersion/ProductVersion metadata. Release packaging supports trusted Authenticode signing and a `-RequireSignature` release gate when a code-signing certificate is available.
- GitHub Actions now builds and uploads the installer, portable ZIP, standalone EXE, and SHA256 manifest together.

### Source And Network Hardening

- Restored the original cross-platform regression tests and reconciled them with the current behavior, bringing the Python suite to 248 tests.
- Source URLs are restricted to HTTP(S), responses are size-limited, and XML feeds reject DTD/entity declarations.
- Ruff, Bandit, dependency auditing, line-ending rules, and local archive/build exclusions are enforced by repository configuration and CI.

### Refresh Lifecycle

- A scheduled Windows worker performs one retrieval, storage, notification, and diagnostics cycle, then exits.
- Normal window launch does not start a tray coordinator or an automatic refresh.
- `Refresh Now` remains the manual refresh path and reports running, succeeded, partial, or failed state.
- Between scheduled scans, there is no Paper Monitor process or hidden WebView consuming memory.
