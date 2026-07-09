# Paper Monitor Release Notes

## 0.1.6

### Windows Window And Tray Reliability

- Dashboard and Settings requests now route to one existing native window instead of creating competing window processes.
- Re-launching the executable focuses and routes the existing window, including when it is currently showing Settings.
- Window-control metadata is written atomically, startup route requests are retried, and child-process startup failures are logged instead of silently disappearing.
- The Tray Icon setting now applies while the coordinator is running.
- Manual launch is explicitly classified as `process_launch`; quiet login startup remains `login_startup` so notification suppression is applied only to login startup.
- Refresh execution now uses a process-local lock plus a Windows named guard, preventing tray, Dashboard, and CLI refreshes from running concurrently.
- Background refresh and notification failures no longer escape through the no-console runtime and are recorded in `PaperMonitor.log`.

### Windows Installer And Portable Builds

- Windows releases now have an Inno Setup installer artifact named `Paper-Monitor-Windows-<version>-Setup.exe`.
- The installer installs per user under `%LOCALAPPDATA%\Programs\PaperMonitor`, creates Start Menu entries, registers Paper Monitor in Windows installed apps, and provides an uninstaller.
- Desktop shortcut creation and login startup are optional installer tasks. Login startup writes `PaperMonitor.exe tray --quiet` and must not open a dashboard window.
- The installer preserves `%APPDATA%\PaperMonitor\config.json` during upgrades and uninstall. It does not install over user configuration.
- Portable release artifacts remain available as `Paper-Monitor-Windows-<version>.zip` and `Paper-Monitor-Windows-<version>.exe`. Portable builds are directly runnable and must not register uninstall entries or installer registry keys.
- Windows executables now include FileVersion/ProductVersion metadata. Release packaging supports trusted Authenticode signing and a `-RequireSignature` release gate when a code-signing certificate is available.
- GitHub Actions now builds and uploads the installer, portable ZIP, standalone EXE, and SHA256 manifest together.

### Source And Network Hardening

- Restored the original cross-platform regression tests and reconciled them with the current behavior, bringing the Python suite to 248 tests.
- Source URLs are restricted to HTTP(S), responses are size-limited, and XML feeds reject DTD/entity declarations.
- Ruff, Bandit, dependency auditing, line-ending rules, and local archive/build exclusions are enforced by repository configuration and CI.

### Launch Refresh

- `Launch Refresh` runs once when the app process starts.
- Manual app launch and quiet login startup both honor `Launch Refresh` when it is enabled, but login startup stays in background/status mode and does not open a dashboard window.
- Reopening from the Dock or tray/status icon, app activation, window focus, dashboard open, settings open, background wake, and sleep resume do not trigger launch refresh.
- `Refresh Now` remains the manual refresh path.
