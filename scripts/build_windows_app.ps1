param(
  [ValidateSet("OneFile", "OneDir", "Both")]
  [string]$Mode = "Both",
  [string]$Version = "0.0.0",
  [string]$PrebuiltNativeTrayPath = "",
  [switch]$GenerateIconOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$') {
  throw "Version must contain only letters, digits, dot, underscore, plus, or hyphen."
}

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $Root "dist\windows"
$BuildDir = Join-Path $Root "build\windows"
$Launcher = Join-Path $Root "windows\PaperMonitor.pyw"
$Icon = Join-Path $Root "windows\assets\PaperMonitor.ico"
$IconScript = Join-Path $Root "scripts\generate_windows_icon.py"
$VersionInfoScript = Join-Path $Root "scripts\generate_windows_version_info.py"
$NativeTrayBuildScript = Join-Path $Root "scripts\build_windows_native_tray.ps1"
$VersionInfo = Join-Path $BuildDir "PaperMonitor.version.txt"
$OneFileExe = Join-Path $DistDir "PaperMonitor.exe"
$OneDirRoot = Join-Path $DistDir "PaperMonitor"
$OneDirExe = Join-Path $OneDirRoot "PaperMonitor.exe"
$NativeTrayExe = if ([string]::IsNullOrWhiteSpace($PrebuiltNativeTrayPath)) {
  Join-Path $DistDir "PaperMonitorTray.exe"
} else {
  [System.IO.Path]::GetFullPath($PrebuiltNativeTrayPath)
}
$BuildMode = $Mode
$RequiredWebViewRuntimeFiles = @(
  "webview\lib\Microsoft.Web.WebView2.Core.dll",
  "webview\lib\Microsoft.Web.WebView2.WinForms.dll",
  "webview\lib\runtimes\win-x64\native\WebView2Loader.dll"
)
$UnsupportedWebViewRuntimes = @("win-arm64", "win-x86")
$UnusedOnedirFiles = @(
  "pythonnet\runtime\Python.Runtime.xml",
  "clr_loader\ffi\dlls\x86\ClrLoader.dll",
  "webview\lib\WebBrowserInterop.x86.dll",
  "webview\lib\pywebview-android.jar"
)

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
  $WorkspacePython = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $WorkspacePython -PathType Leaf) {
    $Candidates += ,@($WorkspacePython)
  }
  $Candidates += ,@("python")
  $Candidates += ,@("python3")
  $Candidates += ,@("py", "-3")

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

function Invoke-PythonOutput {
  param(
    [Parameter(Mandatory=$true)]$Python,
    [string[]]$Arguments = @()
  )

  $global:LASTEXITCODE = 0
  $Output = & $Python.FilePath @(@($Python.BaseArgs) + $Arguments)
  if ($LASTEXITCODE -ne 0) {
    $CommandLine = Format-NativeCommand -FilePath $Python.FilePath -Arguments @(@($Python.BaseArgs) + $Arguments)
    throw "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
  }
  return @($Output)
}

function Get-WebViewLibPath {
  param([Parameter(Mandatory=$true)]$Python)

  $Output = Invoke-PythonOutput -Python $Python -Arguments @(
    "-c",
    "import pathlib, webview; print(pathlib.Path(webview.__file__).resolve().parent / 'lib')"
  )
  $PathText = (($Output | Select-Object -First 1) -as [string])
  if ([string]::IsNullOrWhiteSpace($PathText)) {
    throw "Could not resolve pywebview lib path."
  }
  $Resolved = [System.IO.Path]::GetFullPath($PathText)
  if (-not (Test-Path -LiteralPath $Resolved -PathType Container)) {
    throw "pywebview lib directory was not found: $Resolved"
  }
  return $Resolved
}

function Test-SourceWebViewRuntime {
  param([Parameter(Mandatory=$true)][string]$WebViewLib)

  foreach ($RelativePath in $RequiredWebViewRuntimeFiles) {
    $RuntimeRelative = $RelativePath.Substring("webview\lib\".Length)
    $Candidate = Join-Path $WebViewLib $RuntimeRelative
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
      throw "The installed pywebview wheel is missing required runtime file: $Candidate"
    }
  }
}

function Test-OnedirWebViewRuntime {
  param([Parameter(Mandatory=$true)][string]$AppRoot)

  $Candidates = @(
    (Join-Path $AppRoot "_internal"),
    $AppRoot
  )
  foreach ($RelativePath in $RequiredWebViewRuntimeFiles) {
    $Found = $false
    foreach ($Base in $Candidates) {
      $Candidate = Join-Path $Base $RelativePath
      if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        $Found = $true
        break
      }
    }
    if (-not $Found) {
      throw "Onedir build is missing pywebview runtime file: $RelativePath"
    }
  }
}

function Remove-UnsupportedOnedirWebViewBinaries {
  param([Parameter(Mandatory=$true)][string]$AppRoot)

  foreach ($Base in @((Join-Path $AppRoot "_internal"), $AppRoot)) {
    foreach ($Runtime in $UnsupportedWebViewRuntimes) {
      # pywebview 6.2 checks all three runtime directories at import time,
      # even though a 64-bit process only loads the x64 binary. Keep the
      # directory and remove just the unused loader.
      $Candidate = Join-Path $Base ("webview\lib\runtimes\" + $Runtime + "\native\WebView2Loader.dll")
      if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        Remove-Item -LiteralPath $Candidate -Force
      }
    }
  }
}

function Remove-UnusedOnedirFiles {
  param([Parameter(Mandatory=$true)][string]$AppRoot)

  foreach ($Base in @((Join-Path $AppRoot "_internal"), $AppRoot)) {
    foreach ($RelativePath in $UnusedOnedirFiles) {
      $Candidate = Join-Path $Base $RelativePath
      if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        Remove-Item -LiteralPath $Candidate -Force
      }
    }
  }
}

function Test-OnefileWebViewRuntime {
  param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)]$Python
  )

  # Invoke the module through the selected Python. Console-script launchers
  # embed their original venv path and stop working when a checkout is moved.
  $ArchiveListing = Invoke-PythonOutput -Python $Python -Arguments @(
    "-m",
    "PyInstaller.utils.cliutils.archive_viewer",
    "--list",
    "--brief",
    $ExePath
  )
  $NormalizedListing = (($ArchiveListing -join "`n") -replace "\\", "/")
  foreach ($RelativePath in $RequiredWebViewRuntimeFiles) {
    $Needle = $RelativePath -replace "\\", "/"
    if (-not $NormalizedListing.Contains($Needle)) {
      throw "Onefile build is missing pywebview runtime file: $RelativePath"
    }
  }
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
if ($GenerateIconOnly) {
  Write-Host "Generated $Icon"
  return
}

if ([string]::IsNullOrWhiteSpace($PrebuiltNativeTrayPath)) {
  if (-not (Test-Path -LiteralPath $NativeTrayBuildScript -PathType Leaf)) {
    throw "Missing native tray build script: $NativeTrayBuildScript"
  }
  & $NativeTrayBuildScript -OutputPath $NativeTrayExe
  if ($LASTEXITCODE -ne 0) {
    throw "Native tray build failed with exit code $LASTEXITCODE."
  }
}
if (-not (Test-Path -LiteralPath $NativeTrayExe -PathType Leaf)) {
  throw "Native tray executable was not found: $NativeTrayExe"
}

Invoke-Python -Python $Python -Arguments @(
  $VersionInfoScript,
  "--version",
  $Version,
  "--output",
  $VersionInfo
)
if (-not (Test-Path -LiteralPath $VersionInfo -PathType Leaf)) {
  throw "Version info generation completed but expected file was not found: $VersionInfo"
}

$WebViewLib = Get-WebViewLibPath -Python $Python
Test-SourceWebViewRuntime -WebViewLib $WebViewLib
Write-Host "Using pywebview lib: $WebViewLib"

$CommonPyInstallerArguments = @(
  "-m",
  "PyInstaller",
  "--noconfirm",
  "--clean",
  "--noconsole",
  "--name",
  "PaperMonitor",
  "--icon",
  $Icon,
  "--version-file",
  $VersionInfo,
  "--add-data",
  ((Join-Path $Root "config.example.json") + ";."),
  "--add-data",
  ((Join-Path $Root "journal_metrics.json") + ";."),
  "--add-data",
  ($Icon + ";windows\assets"),
  "--add-data",
  ((Join-Path $Root "paper_monitor\templates") + ";paper_monitor\templates"),
  "--add-data",
  ((Join-Path $Root "paper_monitor\static") + ";paper_monitor\static"),
  "--add-data",
  ((Join-Path $Root "paper_monitor\resources") + ";paper_monitor\resources"),
  "--add-data",
  ($WebViewLib + ";webview\lib"),
  "--add-binary",
  ($NativeTrayExe + ";."),
  "--collect-data",
  "webview",
  "--collect-binaries",
  "webview",
  "--collect-submodules",
  "webview",
  "--hidden-import",
  "_sqlite3",
  "--hidden-import",
  "unicodedata",
  "--hidden-import",
  "winrt.windows.data.xml.dom",
  "--hidden-import",
  "winrt.windows.ui.notifications",
  "--hidden-import",
  "webview",
  "--hidden-import",
  "webview.platforms.winforms",
  "--hidden-import",
  "webview.platforms.edgechromium",
  "--hidden-import",
  "webview.platforms.mshtml",
  "--exclude-module",
  "webview.platforms.android",
  "--exclude-module",
  "webview.platforms.cef",
  "--exclude-module",
  "webview.platforms.cocoa",
  "--exclude-module",
  "webview.platforms.gtk",
  "--exclude-module",
  "webview.platforms.qt",
  "--exclude-module",
  "win11toast",
  "--exclude-module",
  "winrt.windows.foundation",
  "--exclude-module",
  "winrt.windows.foundation.collections",
  "--exclude-module",
  "winrt.windows.storage",
  "--exclude-module",
  "winrt.windows.storage.streams",
  "--exclude-module",
  "winrt.windows.globalization",
  "--exclude-module",
  "winrt.windows.graphics.imaging",
  "--exclude-module",
  "winrt.windows.media.core",
  "--exclude-module",
  "winrt.windows.media.ocr",
  "--exclude-module",
  "winrt.windows.media.playback",
  "--exclude-module",
  "winrt.windows.media.speechsynthesis",
  "--distpath",
  $DistDir,
  "--workpath",
  $BuildDir,
  "--specpath",
  $BuildDir
)

$BuildOneDir = $BuildMode -in @("OneDir", "Both")
$BuildOneFile = $BuildMode -in @("OneFile", "Both")

# PyInstaller is installed from requirements-windows.lock.txt, compiled from requirements-windows.txt.
if ($BuildOneDir) {
  Invoke-Python -Python $Python -Arguments @($CommonPyInstallerArguments + @("--onedir", $Launcher))
  if (-not (Test-Path -LiteralPath $OneDirExe -PathType Leaf)) {
    throw "PyInstaller completed but expected onedir exe was not found: $OneDirExe"
  }
  Remove-UnsupportedOnedirWebViewBinaries -AppRoot $OneDirRoot
  Remove-UnusedOnedirFiles -AppRoot $OneDirRoot
  Test-OnedirWebViewRuntime -AppRoot $OneDirRoot
  Copy-Item -LiteralPath $NativeTrayExe -Destination (Join-Path $OneDirRoot "PaperMonitorTray.exe") -Force
  $EmbeddedOnedirTray = Join-Path $OneDirRoot "_internal\PaperMonitorTray.exe"
  if (Test-Path -LiteralPath $EmbeddedOnedirTray -PathType Leaf) {
    Remove-Item -LiteralPath $EmbeddedOnedirTray -Force
  }
  Copy-Item -LiteralPath $Icon -Destination (Join-Path $OneDirRoot "PaperMonitor.ico") -Force
  $EmbeddedOnedirIcon = Join-Path $OneDirRoot "_internal\windows\assets\PaperMonitor.ico"
  if (Test-Path -LiteralPath $EmbeddedOnedirIcon -PathType Leaf) {
    Remove-Item -LiteralPath $EmbeddedOnedirIcon -Force
  }
  Write-Host "Built $OneDirExe"
}

if ($BuildOneFile) {
  Invoke-Python -Python $Python -Arguments @($CommonPyInstallerArguments + @("--onefile", $Launcher))
  if (-not (Test-Path -LiteralPath $OneFileExe -PathType Leaf)) {
    throw "PyInstaller completed but expected onefile exe was not found: $OneFileExe"
  }
  Test-OnefileWebViewRuntime -ExePath $OneFileExe -Python $Python
  Write-Host "Built $OneFileExe"
}
