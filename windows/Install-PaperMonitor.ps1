param(
  [switch]$EnableStartup,
  [switch]$LaunchAfterInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $SourceDir "PaperMonitor.exe"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PaperMonitor"
$AppData = Join-Path $env:APPDATA "PaperMonitor"
$InstalledExe = Join-Path $InstallDir "PaperMonitor.exe"

function Stop-InstalledPaperMonitor {
  param([Parameter(Mandatory=$true)][string]$ExecutablePath)

  $TargetPath = [System.IO.Path]::GetFullPath($ExecutablePath)
  Get-CimInstance Win32_Process -Filter "Name = 'PaperMonitor.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
      ([System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq $TargetPath)
    } |
    ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      Wait-Process -Id $_.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $SourceExe -PathType Leaf)) {
  throw "PaperMonitor.exe was not found next to this installer script: $SourceExe"
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe
Copy-Item -LiteralPath $SourceExe -Destination $InstalledExe -Force

foreach ($file in @("config.example.json", "journal_metrics.json")) {
  $source = Join-Path $SourceDir $file
  if (Test-Path -LiteralPath $source -PathType Leaf) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $AppData $file) -Force
  }
}

$Config = Join-Path $AppData "config.json"
$ExampleConfig = Join-Path $SourceDir "config.example.json"
if (-not (Test-Path -LiteralPath $Config -PathType Leaf) -and (Test-Path -LiteralPath $ExampleConfig -PathType Leaf)) {
  Copy-Item -LiteralPath $ExampleConfig -Destination $Config
}

if ($EnableStartup) {
  & $InstalledExe install-startup --config $Config
}

if ($LaunchAfterInstall) {
  Start-Process -FilePath $InstalledExe
}

Write-Host "Installed Paper Monitor:"
Write-Host "  $InstalledExe"
Write-Host "Runtime data:"
Write-Host "  $AppData"
Write-Host "Background monitoring uses short Windows scheduled tasks; only the lightweight native tray may remain resident."
