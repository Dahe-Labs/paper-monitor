$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PaperMonitor"
$AppData = Join-Path $env:APPDATA "PaperMonitor"
$BuiltExe = Join-Path $Root "dist\windows\PaperMonitor.exe"
$InstalledExe = Join-Path $InstallDir "PaperMonitor.exe"

& "$Root\scripts\build_windows_app.ps1"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

Copy-Item $BuiltExe $InstalledExe -Force
Copy-Item (Join-Path $Root "journal_metrics.json") (Join-Path $AppData "journal_metrics.json") -Force
Copy-Item (Join-Path $Root "config.example.json") (Join-Path $AppData "config.example.json") -Force

$Config = Join-Path $AppData "config.json"
if (-not (Test-Path $Config)) {
  Copy-Item (Join-Path $Root "config.example.json") $Config
}

& $InstalledExe install-startup
Start-Process -FilePath $InstalledExe -ArgumentList "--quiet"

Write-Host "Installed $InstalledExe"
Write-Host "Configured startup under $env:APPDATA"
