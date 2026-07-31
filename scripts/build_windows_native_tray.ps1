param(
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceDir = Join-Path $Root "windows\native_tray"
$Source = Join-Path $SourceDir "paper_monitor_tray.c"
$Resources = Join-Path $SourceDir "paper_monitor_tray.rc"
$BuildDir = Join-Path $Root "build\windows\native-tray"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
  $OutputPath = Join-Path $Root "dist\windows\PaperMonitorTray.exe"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

function Resolve-NativeTool {
  param([Parameter(Mandatory=$true)][string]$Name)

  $Command = Get-Command -Name $Name -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -ne $Command) {
    return $Command.Source
  }

  $Packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
  $Candidate = Get-ChildItem -LiteralPath $Packages -Filter $Name -File -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'WinLibs' } |
    Select-Object -First 1
  if ($null -ne $Candidate) {
    return $Candidate.FullName
  }
  throw "Could not find $Name. Install a MinGW-w64 toolchain before building the native tray."
}

function Invoke-Native {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @()
  )

  $global:LASTEXITCODE = 0
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath failed with exit code $LASTEXITCODE."
  }
}

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
  throw "Missing native tray source: $Source"
}
if (-not (Test-Path -LiteralPath $Resources -PathType Leaf)) {
  throw "Missing native tray resources: $Resources"
}

$Gcc = Resolve-NativeTool -Name "gcc.exe"
$Windres = Resolve-NativeTool -Name "windres.exe"
$ResourceObject = Join-Path $BuildDir "paper_monitor_tray_res.o"
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null

Push-Location -LiteralPath $SourceDir
try {
  Invoke-Native -FilePath $Windres -Arguments @(
    "--input", $Resources,
    "--output", $ResourceObject,
    "--output-format=coff"
  )
} finally {
  Pop-Location
}

Invoke-Native -FilePath $Gcc -Arguments @(
  "-std=c17",
  "-Os",
  "-Wall",
  "-Wextra",
  "-Werror",
  "-municode",
  "-mwindows",
  "-static",
  "-s",
  $Source,
  $ResourceObject,
  "-o", $OutputPath,
  "-lshell32",
  "-luser32",
  "-ladvapi32"
)

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
  throw "Native tray build did not create $OutputPath"
}
Write-Host "Built $OutputPath"
