param(
  [switch]$EnableStartup,
  [switch]$LaunchAfterInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PaperMonitor"
$AppData = Join-Path $env:APPDATA "PaperMonitor"
$BuiltExe = Join-Path $Root "dist\windows\PaperMonitor.exe"
$InstalledExe = Join-Path $InstallDir "PaperMonitor.exe"

function Format-NativeCommand {
  param(
    [string]$FilePath,
    [string[]]$Arguments = @()
  )

  return (@($FilePath) + @($Arguments)) -join " "
}

function Invoke-Native {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @()
  )

  $global:LASTEXITCODE = 0
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    $CommandLine = Format-NativeCommand -FilePath $FilePath -Arguments $Arguments
    throw "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
  }
}

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

& "$Root\scripts\build_windows_app.ps1"

if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
  throw "Build completed but expected exe was not found: $BuiltExe"
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe
Copy-Item -LiteralPath $BuiltExe -Destination $InstalledExe -Force
Copy-Item -LiteralPath (Join-Path $Root "journal_metrics.json") -Destination (Join-Path $AppData "journal_metrics.json") -Force
Copy-Item -LiteralPath (Join-Path $Root "config.example.json") -Destination (Join-Path $AppData "config.example.json") -Force

if (-not (Test-Path -LiteralPath $InstalledExe -PathType Leaf)) {
  throw "Install copy completed but expected exe was not found: $InstalledExe"
}

$Config = Join-Path $AppData "config.json"
if (-not (Test-Path -LiteralPath $Config)) {
  Copy-Item -LiteralPath (Join-Path $Root "config.example.json") -Destination $Config
}

if ($EnableStartup) {
  Invoke-Native -FilePath $InstalledExe -Arguments @("install-startup", "--config", $Config)
}

if ($LaunchAfterInstall) {
  Start-Process -FilePath $InstalledExe
}

Write-Host "Installed $InstalledExe"
if ($EnableStartup) {
  Write-Host "Configured non-resident background monitoring with Windows Task Scheduler"
}
