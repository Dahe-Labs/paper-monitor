$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $Root "dist\windows"
$BuildDir = Join-Path $Root "build\windows"
$Launcher = Join-Path $Root "windows\PaperMonitor.pyw"
$Icon = Join-Path $Root "windows\assets\PaperMonitor.ico"
$IconScript = Join-Path $Root "scripts\generate_windows_icon.py"
$BuiltExe = Join-Path $DistDir "PaperMonitor.exe"

function Get-ArrayTail {
  param([string[]]$Values)

  if ($Values.Count -le 1) {
    return @()
  }

  return @($Values[1..($Values.Count - 1)])
}

function Test-WindowsAppsAlias {
  param([System.Management.Automation.CommandInfo]$Command)

  if ($null -eq $Command) {
    return $false
  }

  $Source = $Command.Source
  if ([string]::IsNullOrWhiteSpace($Source)) {
    $Source = $Command.Definition
  }
  if ([string]::IsNullOrWhiteSpace($Source)) {
    return $false
  }

  $LocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
  if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
    return $false
  }

  $WindowsApps = Join-Path $LocalAppData "Microsoft\WindowsApps"
  try {
    $SourcePath = [System.IO.Path]::GetFullPath($Source)
    $WindowsAppsPath = [System.IO.Path]::GetFullPath($WindowsApps)
    return $SourcePath.StartsWith($WindowsAppsPath, [System.StringComparison]::OrdinalIgnoreCase)
  } catch {
    return $false
  }
}

function Test-PythonCandidate {
  param([string[]]$Candidate)

  $CommandName = $Candidate[0]
  $CommandInfo = Get-Command -Name $CommandName -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $CommandInfo) {
    return $null
  }
  if (Test-WindowsAppsAlias -Command $CommandInfo) {
    return $null
  }

  $BaseArgs = @(Get-ArrayTail -Values $Candidate)
  $ProbeArgs = @($BaseArgs + @("-c", "import sys; print(sys.executable)"))
  $global:LASTEXITCODE = 0
  $Output = & $CommandName @ProbeArgs 2>$null
  if ($LASTEXITCODE -ne 0) {
    return $null
  }

  return [pscustomobject]@{
    FilePath = $CommandName
    BaseArgs = @($BaseArgs)
    DisplayName = ($Candidate -join " ")
    Executable = (($Output | Select-Object -First 1) -as [string])
  }
}

function Get-PythonCommand {
  $Candidates = @()
  $PythonEnv = [Environment]::GetEnvironmentVariable("PYTHON")
  if (-not [string]::IsNullOrWhiteSpace($PythonEnv)) {
    $Candidates += ,@($PythonEnv.Trim('"'))
  }
  $Candidates += ,@("py", "-3")
  $Candidates += ,@("python3")
  $Candidates += ,@("python")

  foreach ($Candidate in $Candidates) {
    $Python = Test-PythonCandidate -Candidate $Candidate
    if ($null -ne $Python) {
      return $Python
    }
  }

  throw "Could not find a real Python interpreter. Install Python 3 or the py launcher, and disable the Microsoft Store python alias if it is first on PATH."
}

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

function Invoke-Python {
  param(
    [Parameter(Mandatory=$true)]$Python,
    [string[]]$Arguments = @()
  )

  Invoke-Native -FilePath $Python.FilePath -Arguments @(@($Python.BaseArgs) + $Arguments)
}

Set-Location -LiteralPath $Root

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
  throw "Missing Windows launcher: $Launcher"
}

$Python = Get-PythonCommand
Write-Host "Using Python: $($Python.DisplayName) ($($Python.Executable))"

Invoke-Python -Python $Python -Arguments @($IconScript)
if (-not (Test-Path -LiteralPath $Icon -PathType Leaf)) {
  throw "Icon generation completed but expected icon was not found: $Icon"
}

# PyInstaller is provided by requirements-windows.txt.
Invoke-Python -Python $Python -Arguments @(
  "-m",
  "PyInstaller",
  "--noconsole",
  "--onefile",
  "--name",
  "PaperMonitor",
  "--icon",
  $Icon,
  "--add-data",
  ((Join-Path $Root "config.example.json") + ";."),
  "--add-data",
  ((Join-Path $Root "journal_metrics.json") + ";."),
  "--add-data",
  ($Icon + ";windows\assets"),
  "--hidden-import",
  "pystray",
  "--hidden-import",
  "PIL.Image",
  "--hidden-import",
  "PIL.ImageDraw",
  "--hidden-import",
  "win11toast",
  "--distpath",
  $DistDir,
  "--workpath",
  $BuildDir,
  "--specpath",
  $BuildDir,
  $Launcher
)

if (-not (Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
  throw "PyInstaller completed but expected exe was not found: $BuiltExe"
}

Write-Host "Built $BuiltExe"
