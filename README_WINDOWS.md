# Paper Monitor Windows

This folder is the Windows project for Paper Monitor.

## What It Contains

- `paper_monitor/`: literature search, filtering, storage, dashboard, keyword analysis, and Windows tray code.
- `windows/PaperMonitor.pyw`: quiet Windows tray entrypoint.
- `windows/assets/PaperMonitor.ico`: Windows tray/app icon.
- `windows/PaperMonitor.iss`: Inno Setup installer script.
- `scripts/build_windows_app.ps1`: builds a no-console `.exe` with PyInstaller.
- `scripts/package_windows_release.ps1`: creates release artifacts.
- `requirements-windows.txt`: human-maintained top-level Windows dependency ranges.
- `requirements-windows.lock.txt`: installation entry point for CI, releases, and reproducible local packaging.
- `config.example.json` and `journal_metrics.json`: default runtime data.

## Build On Windows

Open PowerShell inside this folder:

```powershell
python -m pip install -r requirements-windows.lock.txt
.\scripts\build_windows_app.ps1
```

By default the build creates both an inspectable onedir app and the standalone onefile executable. You can limit this with `-Mode OneDir` or `-Mode OneFile`.
Pass `-Version <version>` to embed Windows FileVersion/ProductVersion metadata in the executables.

The built executables are created under:

```powershell
.\dist\windows\PaperMonitor\PaperMonitor.exe
.\dist\windows\PaperMonitor.exe
```

## Package A Release

Install Inno Setup 6 or 7 so `ISCC.exe` is available, then run:

```powershell
.\scripts\package_windows_release.ps1 -Version <version>
```

For a signed public release, install the Windows SDK, make a trusted code-signing certificate available in the current user's certificate store, and run:

```powershell
.\scripts\package_windows_release.ps1 -Version <version> `
  -CodeSigningCertificateThumbprint <thumbprint> `
  -TimestampUrl <rfc3161-url> `
  -RequireSignature
```

`-RequireSignature` prevents an unsigned public release from being produced accidentally.

The `Build Windows release` GitHub Actions workflow produces the same complete artifact set. A pushed `v<version>` tag runs tests, requires signing, and uploads the verified assets to a draft GitHub Release; publish that draft only after all platform assets are ready. Configure repository secrets named `WINDOWS_SIGNING_CERTIFICATE_BASE64` and `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`. Unsigned workflow artifacts remain available only for non-uploading manual builds.

The release output contains:

- `Paper-Monitor-Windows-<version>-Setup.exe`: installer.
- `Paper-Monitor-Windows-<version>.zip`: portable zip.
- `Paper-Monitor-Windows-<version>.exe`: standalone executable.
- `SHA256SUMS-<version>.txt`: SHA256 checksums for the installer, zip, and standalone exe.
- `CURRENT_WINDOWS_RELEASE.txt`: the version of the last fully completed package run.

## Installer

Use `Paper-Monitor-Windows-<version>-Setup.exe` for a normal Windows install. It installs for the current user by default:

```text
%LOCALAPPDATA%\Programs\PaperMonitor
```

The installer registers Paper Monitor in Windows installed apps and provides an uninstaller. It creates one Paper Monitor Start Menu shortcut; Settings remains an in-app view. The desktop shortcut is optional.

The installer no longer adds a login process. Upgrading also removes the legacy `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PaperMonitor` entry so an older tray coordinator cannot remain resident. The installer can launch Paper Monitor after install only when the final-page launch option is selected.

Enable **Background Monitoring** in App Settings to register a per-user Windows scheduled task. Windows then starts a short-lived Paper Monitor refresh worker only when the configured scan is due. The worker retrieves papers, updates local data, sends any notifications, and exits; Paper Monitor consumes no background memory between scans. The task runs with the signed-in user's session so notifications remain available. It does not wake a sleeping PC, but a missed scan starts when Windows is available again.

The task ignores overlapping starts and retries a failed run twice at 15-minute intervals. Notification payloads are stored before delivery and remain pending after a toast failure. Dashboard HTML is regenerated when the window is opened rather than during a headless scheduled scan.

User config is stored under:

```text
%APPDATA%\PaperMonitor\config.json
```

The uninstaller removes the scheduled refresh task and legacy Run entry. Upgrades and uninstall preserve the user config by default.

## Portable

Use `Paper-Monitor-Windows-<version>.zip` or the standalone `.exe` when you do not want an installed app. The portable artifacts are directly runnable and do not register uninstall entries or installer registry keys. The extracted zip uses the faster onedir layout; the standalone executable is a onefile build and may take longer to unpack at startup.

For the zip, extract it and run:

```powershell
.\PaperMonitor.exe
```

## Source Checkout Install Helper

For local development, this script builds and copies the app to the same per-user Programs folder:

```powershell
.\scripts\install_windows_app.ps1
```

It does not enable background monitoring or launch the app unless requested. The compatibility switch `-EnableStartup` now enables the non-resident scheduled task; it does not create a login process:

```powershell
.\scripts\install_windows_app.ps1 -EnableStartup -LaunchAfterInstall
```

## Runtime Behavior

Opening Paper Monitor starts the Dashboard/Settings window and its local loopback bridge. Closing the window stops that UI session and releases the WebView and Python processes. Reopen the app from the Start Menu or desktop shortcut when you need the Dashboard; this is independent of background monitoring.

The scheduled worker has no window or tray icon. It exits after one refresh, even when a source fails; refresh diagnostics are retained for the next Dashboard session. `Refresh Now` remains available while the app window is open.

The legacy resident tray command remains available for compatibility during migration, but it is no longer used for normal startup or background scheduling. Its menu contains:

```text
Open Paper Monitor
Settings...
Refresh Now
Test Notification
Quit
```

`Open Paper Monitor` and `Settings...` reuse the same native app window and switch its in-app route. Re-launching the executable also routes and focuses the existing window. The local bridge only listens on `127.0.0.1` and uses a per-session token for in-app actions.

`Test Notification` sends a Windows toast notification without running a literature search.

## Disable Background Monitoring

Clear **Background Monitoring** in App Settings and save. Paper Monitor removes its scheduled task immediately; disabling it does not delete your configuration, database, or Dashboard history.
