# Paper Monitor Windows

This folder is the Windows project for Paper Monitor.

## What It Contains

- `paper_monitor/`: literature search, filtering, storage, dashboard, keyword analysis, and Windows tray code.
- `windows/PaperMonitor.pyw`: quiet Windows tray entrypoint.
- `windows/assets/PaperMonitor.ico`: Windows tray/app icon.
- `windows/PaperMonitor.iss`: Inno Setup installer script.
- `scripts/build_windows_app.ps1`: builds a no-console `.exe` with PyInstaller.
- `scripts/package_windows_release.ps1`: creates release artifacts.
- `requirements-windows.txt`: Windows packaging/runtime dependencies.
- `config.example.json` and `journal_metrics.json`: default runtime data.

## Build On Windows

Open PowerShell inside this folder:

```powershell
python -m pip install -r requirements-windows.txt
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

The `Build Windows release` GitHub Actions workflow produces the same complete artifact set. To enable signing in Actions, configure repository secrets named `WINDOWS_SIGNING_CERTIFICATE_BASE64` and `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`; unsigned builds remain supported when those secrets are absent.

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

The installer registers Paper Monitor in Windows installed apps and provides an uninstaller. It creates a Start Menu shortcut. Desktop shortcut and login startup are optional installer tasks.

Login startup is off by default. If enabled, the startup command is:

```text
PaperMonitor.exe tray --quiet
```

That starts the tray app silently and does not open the dashboard at login. The installer can launch Paper Monitor after install only when the final-page launch option is selected.

User config is stored under:

```text
%APPDATA%\PaperMonitor\config.json
```

Upgrades and uninstall preserve that user config by default.

## Portable

Use `Paper-Monitor-Windows-<version>.zip` or the standalone `.exe` when you do not want an installed app. The portable artifacts are directly runnable and do not register uninstall entries or installer registry keys.

For the zip, extract it and run:

```powershell
.\PaperMonitor.exe
```

## Source Checkout Install Helper

For local development, this script builds and copies the app to the same per-user Programs folder:

```powershell
.\scripts\install_windows_app.ps1
```

It does not enable login startup or launch the app unless requested:

```powershell
.\scripts\install_windows_app.ps1 -EnableStartup -LaunchAfterInstall
```

## Tray Usage

Windows may place the tray icon inside the hidden tray overflow. Right-click the tray icon for:

```text
Open Paper Monitor
Settings...
Refresh Now
Test Notification
Quit
```

`Open Paper Monitor` and `Settings...` reuse the same native app window and switch its in-app route. Re-launching the executable also routes and focuses the existing window. The local bridge only listens on `127.0.0.1` and uses a per-session token for in-app actions.

The Tray Icon setting applies while the app is running. Hiding the icon does not stop the background refresh coordinator; re-open Settings from the Start Menu or executable to show it again.

`Test Notification` sends a Windows toast notification without running a literature search.

## Disable Startup

```powershell
& "$env:LOCALAPPDATA\Programs\PaperMonitor\PaperMonitor.exe" uninstall-startup
```
