# Paper Monitor Release Checklist

Use this checklist for every Mac or Windows release candidate. Keep the checks boring and repeatable.

## Source And Contract

- Confirm `config.example.json` still matches `paper_monitor.config.DEFAULT_CONFIG`.
- Confirm `docs/config.schema.json` covers every user-facing config field.
- Confirm Windows Settings and Mac `SettingsStore` preserve unknown config keys.
- Confirm `settings_schema_version` is at least `2` after any settings save.

## Python Core

- Run `python -m coverage run -m unittest discover -s tests` from the repository root.
- Run `python -m coverage report --fail-under=70`.
- Run `python -m ruff check paper_monitor scripts tests windows`.
- Run `python -m bandit -q -r paper_monitor scripts windows -x tests -s B105,B404,B603,B607,B608,B110`.
- Run `python -m pip_audit -r requirements-windows.lock.txt --no-deps --disable-pip --progress-spinner off`.
- Run one dry local refresh with Crossref enabled and a short date range.
- Confirm failed refreshes mark the latest run as `failed`, not `running`.
- Confirm dashboard generation does not embed API keys or secrets.

## Data Sources

- Crossref without `mailto` must use public-pool-safe behavior: one list request at a time.
- Crossref with `mailto` may use polite-pool-safe behavior: up to three concurrent list requests.
- OpenAlex must reject enabled saves without an API key and work when a valid API key is provided.
- arXiv must stay opt-in through the source flag or the `arxiv` journal/source selection.

## Windows

- Confirm `requirements-windows.lock.txt` is current with the human-maintained ranges in `requirements-windows.txt`.
- Run `python -m pip install -r requirements-windows.lock.txt` before building.
- Run `.\scripts\build_windows_app.ps1`.
- Run `.\scripts\package_windows_release.ps1 -Version <version>` for release assets.
- For a public release, package with `-CodeSigningCertificateThumbprint`, `-TimestampUrl`, and `-RequireSignature`.
- Confirm the release directory contains the installer, portable zip, standalone exe, and `SHA256SUMS-<version>.txt`.
- Push the signed `v<version>` tag; confirm the Windows workflow passes quality checks, builds signed assets, and creates or updates a draft GitHub Release.
- Confirm the draft Release contains the same four Windows assets and the tag exposes clean source archives; publish it only after all platform assets and checks are complete.
- Confirm the installer and standalone executable have valid Authenticode signatures and matching FileVersion/ProductVersion metadata.
- Install `Paper-Monitor-Windows-<version>-Setup.exe` in a clean user profile or VM.
- Confirm the installer appears in Windows installed apps and provides a working uninstaller.
- Confirm uninstall removes installed files, the Paper Monitor scheduled task, and the legacy Run entry while preserving `%APPDATA%\PaperMonitor\config.json`.
- Confirm the portable zip and standalone exe run directly and do not create uninstall registry entries.
- Confirm `git status --short` contains only the intended release changes and no runtime, build, or archive files are tracked.
- Use `-SkipBuild` only for local packaging checks when the exact built executable has already been verified.
- Run `.\scripts\install_windows_app.ps1` only for source-tree developer install checks.
- Enable **Background Monitoring** and confirm `\PaperMonitor Scheduled Refresh` exists in Windows Task Scheduler with the configured interval.
- Confirm the legacy `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PaperMonitor` value is absent after upgrade or settings synchronization.
- Close the native window and confirm its WebView, local bridge, and `PaperMonitor.exe` process exit instead of hiding.
- Run the scheduled task on demand, confirm one refresh reaches a terminal status, and confirm the worker exits afterward with no Paper Monitor process resident between scans.
- Open Dashboard, Settings, Refresh Now, Keyword Analysis, and Test Notification.
- Verify the local bridge listens only on `127.0.0.1` and requires `X-Paper-Monitor-Token`.
- Reopen Paper Monitor after closing it and confirm a clean new window starts without a hidden predecessor.
- Start a refresh from Dashboard while another refresh owns the named guard and confirm the second request returns HTTP 202 with `status: running` and the same `request_id`.

## macOS

- Run `swift test` from `macos/PaperMonitorApp` on macOS.
- Build the app bundle and launch it from a clean Application Support directory.
- Confirm bundled runtime installation preserves user `config.json`.
- Confirm notification permission, refresh scheduling, dashboard, settings save, and keyword analysis.
- Confirm zip output excludes `._*`, `.DS_Store`, and `__MACOSX`.

## Release Notes

- List user-visible changes.
- List config schema changes.
- List source/API behavior changes.
- Describe installer versus portable behavior.
- Describe launch-refresh behavior.
- Include known manual verification gaps.
