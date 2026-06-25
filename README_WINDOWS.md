# Paper Monitor Windows

This folder is the copyable Windows project for Paper Monitor.

## What It Contains

- `paper_monitor/`: the existing literature search, filtering, storage, dashboard, keyword analysis, and Windows tray code.
- `windows/PaperMonitor.pyw`: quiet Windows tray entrypoint.
- `windows/assets/PaperMonitor.ico`: Windows tray/app icon.
- `scripts/build_windows_app.ps1`: builds a no-console `.exe` with PyInstaller.
- `scripts/install_windows_app.ps1`: installs the app for the current Windows user and enables startup.
- `requirements-windows.txt`: Windows packaging/runtime dependencies.
- `config.example.json` and `journal_metrics.json`: default runtime data.

## Build On Windows

Open PowerShell inside this folder:

```powershell
python -m pip install -r requirements-windows.txt
.\scripts\build_windows_app.ps1
```

The built executable will be created under:

```powershell
.\dist\windows\PaperMonitor.exe
```

## Install On Windows

```powershell
.\scripts\install_windows_app.ps1
```

The installer copies the app to:

```powershell
$env:LOCALAPPDATA\Programs\PaperMonitor\PaperMonitor.exe
```

Runtime files are stored under:

```powershell
$env:APPDATA\PaperMonitor
```

The app starts silently at login and runs in the Windows system tray. Windows may place it inside the hidden tray overflow. Right-click the tray icon for:

```text
Open Dashboard
Settings...
Refresh Now
Test Notification
Quit
```

`Open Dashboard` starts a local `127.0.0.1` dashboard bridge so the browser can add accepted keyword-analysis terms to `config.json` and run Crossref keyword analysis. The local bridge uses a per-session token and only listens on localhost.

`Settings...` opens:

```powershell
$env:APPDATA\PaperMonitor\config.json
```

`Test Notification` sends a Windows toast notification without running a literature search.

## Disable Startup

```powershell
& "$env:LOCALAPPDATA\Programs\PaperMonitor\PaperMonitor.exe" uninstall-startup
```
