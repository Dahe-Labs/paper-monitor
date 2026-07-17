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

The installer does not add a registry login process. Upgrading also removes legacy `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entries so an older tray coordinator cannot remain resident. The installer can launch Paper Monitor after install only when the final-page launch option is selected.

Enable **Background Monitoring** in App Settings to register a per-user Windows scheduled task. Windows then starts a short-lived Paper Monitor refresh worker only when the configured scan is due. The worker retrieves papers, updates local data, sends any notifications, and exits; Python, WebView, and the local HTTP bridge consume no background memory between scans. The task runs with the signed-in user's session so notifications remain available. It does not wake a sleeping PC, but a missed scan starts when Windows is available again.

The task ignores overlapping starts and retries a failed run twice at 15-minute intervals. Notification payloads are stored before delivery and remain pending after a toast failure. Dashboard HTML is regenerated when the window is opened rather than during a headless scheduled scan.

Enable **Start at Windows Sign-in** to register a separate per-user logon task. It starts only the lightweight native tray after sign-in and exits the Python launcher without opening the Dashboard window or running a literature refresh. This option is independent from **Background Monitoring**.

User config is stored under:

```text
%APPDATA%\PaperMonitor\config.json
```

The uninstaller removes both the scheduled refresh task and the optional sign-in tray task, plus legacy Run entries. Upgrades and uninstall preserve the user config by default.

## Portable

Use `Paper-Monitor-Windows-<version>.zip` or the standalone `.exe` when you do not want an installed app. The portable artifacts are directly runnable and do not register uninstall entries or installer registry keys. The extracted zip uses the faster onedir layout; the standalone executable is a onefile build and may take longer to unpack at startup.

Portable builds can also use **Background Monitoring** and **Start at Windows Sign-in** because both are current-user Task Scheduler entries. Each task records the executable's current absolute path. If the portable folder is moved, open Paper Monitor once from the new location to reconcile the tasks; deleting the portable files without disabling these options leaves harmless broken task entries that must be removed manually.

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

Opening Paper Monitor starts the Dashboard/Settings window and its local loopback bridge, plus a separate small native C tray executable. Closing the window stops that UI session and releases WebView, Python, and the bridge while the lightweight tray remains available. The tray contains no network retrieval, database, or rendering implementation; each action starts a bounded Paper Monitor worker and returns immediately.

The scheduled worker has no window or tray icon. It exits after one refresh, even when a source fails; refresh diagnostics are retained for the next Dashboard session. `Refresh Now` remains available while the app window is open.

The native tray menu contains:

```text
Open Paper Monitor
Settings...
Refresh Now
Test Notification
Quit Tray
```

`Open Paper Monitor` and `Settings...` reuse the same app window and switch its in-app route. `Refresh Now` starts the same short-lived background Refresh Execution used by Task Scheduler, so it writes to the canonical lifecycle database and respects notification deduplication. Re-launching the executable also routes and focuses the existing window. The local bridge only listens on `127.0.0.1` and uses a per-session token for in-app actions.

`Test Notification` sends a Windows toast notification without running a literature search.

## Disable Windows Tasks

Clear **Background Monitoring** in App Settings and save. Paper Monitor removes its scheduled task immediately; disabling it does not delete your configuration, database, or Dashboard history.

Clear **Start at Windows Sign-in** to remove the separate login-triggered tray task. The tray that is already running can still be closed with **Quit Tray**.
