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

& "$Root\scripts\build_windows_app.ps1"

if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
  throw "Build completed but expected exe was not found: $BuiltExe"
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

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

Invoke-Native -FilePath $InstalledExe -Arguments @("install-startup")
Start-Process -FilePath $InstalledExe -ArgumentList "--quiet"

Write-Host "Installed $InstalledExe"
Write-Host "Configured startup under $env:APPDATA"
