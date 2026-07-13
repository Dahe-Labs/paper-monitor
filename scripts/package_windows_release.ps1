param(
  [string]$Version = "",
  [string]$OutputDir = "",
  [string]$InnoSetupCompiler = "",
  [string]$SignToolPath = "",
  [string]$CodeSigningCertificateThumbprint = "",
  [string]$TimestampUrl = "",
  [switch]$RequireSignature,
  [switch]$SkipInstaller,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = Get-Date -Format "yyyyMMdd-HHmmss"
}
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$') {
  throw "Version must contain only letters, digits, dot, underscore, plus, or hyphen."
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  $OutputDir = Join-Path $Root "public_release"
}

$ReleaseName = "Paper-Monitor-Windows-$Version"
$DistExe = Join-Path $Root "dist\windows\PaperMonitor.exe"
$DistNativeTray = Join-Path $Root "dist\windows\PaperMonitorTray.exe"
$DistAppDir = Join-Path $Root "dist\windows\PaperMonitor"
$DistAppExe = Join-Path $DistAppDir "PaperMonitor.exe"
$DistAppNativeTray = Join-Path $DistAppDir "PaperMonitorTray.exe"
$InnoScript = Join-Path $Root "windows\PaperMonitor.iss"
$InstallerIcon = Join-Path $Root "windows\assets\PaperMonitor.ico"
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$StagingDir = Join-Path $OutputDir $ReleaseName
$ZipPath = Join-Path $OutputDir "$ReleaseName.zip"
$ExeAssetPath = Join-Path $OutputDir "$ReleaseName.exe"
$InstallerBaseName = "$ReleaseName-Setup"
$InstallerPath = Join-Path $OutputDir "$InstallerBaseName.exe"
$HashPath = Join-Path $OutputDir "SHA256SUMS-$Version.txt"
$CurrentReleasePath = Join-Path $OutputDir "CURRENT_WINDOWS_RELEASE.txt"

function Copy-ReleaseFile {
  param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Destination
  )

  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Missing release input: $Source"
  }
  Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Write-Utf8NoBomLines {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$Lines
  )

  [System.IO.File]::WriteAllLines(
    $Path,
    $Lines,
    [System.Text.UTF8Encoding]::new($false)
  )
}

function Find-InnoSetupCompiler {
  param([string]$Requested)

  if (-not [string]::IsNullOrWhiteSpace($Requested)) {
    $Resolved = [System.IO.Path]::GetFullPath($Requested)
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
      throw "Inno Setup compiler was not found: $Resolved"
    }
    return $Resolved
  }

  $Command = Get-Command -Name "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -ne $Command) {
    return $Command.Source
  }

  $CandidateRoots = @(
    ${env:ProgramFiles(x86)},
    $env:ProgramFiles
  ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $CandidateRoots += (Join-Path $env:LOCALAPPDATA "Programs")
  }
  $Candidates = $CandidateRoots | ForEach-Object {
    Join-Path $_ "Inno Setup 7\ISCC.exe"
    Join-Path $_ "Inno Setup 6\ISCC.exe"
  }
  foreach ($Candidate in $Candidates) {
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
      return $Candidate
    }
  }

  throw "Inno Setup compiler ISCC.exe was not found. Install Inno Setup 6 or 7, or pass -InnoSetupCompiler <path>."
}

function Find-SignTool {
  param([string]$Requested)

  if (-not [string]::IsNullOrWhiteSpace($Requested)) {
    $Resolved = [System.IO.Path]::GetFullPath($Requested)
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
      throw "signtool.exe was not found: $Resolved"
    }
    return $Resolved
  }

  $Command = Get-Command -Name "signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -ne $Command) {
    return $Command.Source
  }

  $KitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
  if (Test-Path -LiteralPath $KitsRoot -PathType Container) {
    $Candidate = Get-ChildItem -LiteralPath $KitsRoot -Directory |
      Sort-Object Name -Descending |
      ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
      Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
      Select-Object -First 1
    if ($null -ne $Candidate) {
      return $Candidate
    }
  }

  throw "signtool.exe was not found. Install the Windows SDK or pass -SignToolPath <path>."
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

function Invoke-CodeSign {
  param(
    [Parameter(Mandatory=$true)][string]$SignTool,
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$Timestamp
  )

  $Arguments = @(
    "sign",
    "/sha1",
    $CertificateThumbprint,
    "/fd",
    "SHA256"
  )
  if (-not [string]::IsNullOrWhiteSpace($Timestamp)) {
    $Arguments += @("/tr", $Timestamp, "/td", "SHA256")
  }
  $Arguments += $Path
  Invoke-Native -FilePath $SignTool -Arguments $Arguments
  Invoke-Native -FilePath $SignTool -Arguments @("verify", "/pa", $Path)
}

function Invoke-CodeVerify {
  param(
    [Parameter(Mandatory=$true)][string]$SignTool,
    [Parameter(Mandatory=$true)][string]$Path
  )

  Invoke-Native -FilePath $SignTool -Arguments @("verify", "/pa", $Path)
}

$SigningEnabled = -not [string]::IsNullOrWhiteSpace($CodeSigningCertificateThumbprint)
if ($RequireSignature -and -not $SigningEnabled) {
  throw "-RequireSignature requires -CodeSigningCertificateThumbprint."
}
$ResolvedSignTool = $null
if ($SigningEnabled) {
  $ResolvedSignTool = Find-SignTool -Requested $SignToolPath
}

if (-not $SkipBuild) {
  if ($SigningEnabled) {
    & (Join-Path $Root "scripts\build_windows_native_tray.ps1") -OutputPath $DistNativeTray
    Invoke-CodeSign `
      -SignTool $ResolvedSignTool `
      -CertificateThumbprint $CodeSigningCertificateThumbprint `
      -Path $DistNativeTray `
      -Timestamp $TimestampUrl
    & (Join-Path $Root "scripts\build_windows_app.ps1") `
      -Version $Version `
      -PrebuiltNativeTrayPath $DistNativeTray
  } else {
    & (Join-Path $Root "scripts\build_windows_app.ps1") -Version $Version
  }
}

if (-not (Test-Path -LiteralPath $DistExe -PathType Leaf)) {
  throw "Missing built executable: $DistExe"
}
if (-not (Test-Path -LiteralPath $DistAppExe -PathType Leaf)) {
  throw "Missing built application: $DistAppExe"
}
if (-not (Test-Path -LiteralPath $DistNativeTray -PathType Leaf)) {
  throw "Missing native tray executable: $DistNativeTray"
}
if (-not (Test-Path -LiteralPath $DistAppNativeTray -PathType Leaf)) {
  throw "Missing onedir native tray executable: $DistAppNativeTray"
}

$BuiltProductVersion = (Get-Item -LiteralPath $DistExe).VersionInfo.ProductVersion
if ([string]::IsNullOrWhiteSpace($BuiltProductVersion) -or $BuiltProductVersion.Trim() -ne $Version) {
  throw "Built executable ProductVersion '$BuiltProductVersion' does not match release version '$Version'. Rebuild without -SkipBuild."
}
$BuiltAppProductVersion = (Get-Item -LiteralPath $DistAppExe).VersionInfo.ProductVersion
if ([string]::IsNullOrWhiteSpace($BuiltAppProductVersion) -or $BuiltAppProductVersion.Trim() -ne $Version) {
  throw "Built application ProductVersion '$BuiltAppProductVersion' does not match release version '$Version'. Rebuild without -SkipBuild."
}
if ($SigningEnabled) {
  Invoke-CodeSign `
    -SignTool $ResolvedSignTool `
    -CertificateThumbprint $CodeSigningCertificateThumbprint `
    -Path $DistExe `
    -Timestamp $TimestampUrl
  Invoke-CodeSign `
    -SignTool $ResolvedSignTool `
    -CertificateThumbprint $CodeSigningCertificateThumbprint `
    -Path $DistAppExe `
    -Timestamp $TimestampUrl
  if ($SkipBuild) {
    Invoke-CodeSign `
      -SignTool $ResolvedSignTool `
      -CertificateThumbprint $CodeSigningCertificateThumbprint `
      -Path $DistNativeTray `
      -Timestamp $TimestampUrl
    Invoke-CodeSign `
      -SignTool $ResolvedSignTool `
      -CertificateThumbprint $CodeSigningCertificateThumbprint `
      -Path $DistAppNativeTray `
      -Timestamp $TimestampUrl
  } else {
    Invoke-CodeVerify -SignTool $ResolvedSignTool -Path $DistNativeTray
    Invoke-CodeVerify -SignTool $ResolvedSignTool -Path $DistAppNativeTray
  }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if (Test-Path -LiteralPath $StagingDir) {
  throw "Release staging directory already exists: $StagingDir"
}
New-Item -ItemType Directory -Path $StagingDir | Out-Null

Copy-Item -Path (Join-Path $DistAppDir "*") -Destination $StagingDir -Recurse -Force
Copy-ReleaseFile -Source (Join-Path $Root "README_WINDOWS.md") -Destination (Join-Path $StagingDir "README_WINDOWS.md")
Copy-ReleaseFile -Source (Join-Path $Root "config.example.json") -Destination (Join-Path $StagingDir "config.example.json")
Copy-ReleaseFile -Source (Join-Path $Root "journal_metrics.json") -Destination (Join-Path $StagingDir "journal_metrics.json")

$PackageHashes = Get-ChildItem -LiteralPath $StagingDir -File -Recurse |
  Sort-Object FullName |
  ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName
    $RelativePath = $_.FullName.Substring($StagingDir.Length).TrimStart('\').Replace('\', '/')
    "$($Hash.Hash.ToLowerInvariant())  $RelativePath"
  }
Write-Utf8NoBomLines -Path (Join-Path $StagingDir "SHA256SUMS.txt") -Lines @($PackageHashes)

if (Test-Path -LiteralPath $ZipPath) {
  throw "Release zip already exists: $ZipPath"
}
Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $ZipPath
Copy-ReleaseFile -Source $DistExe -Destination $ExeAssetPath

if (-not $SkipInstaller) {
  if (-not (Test-Path -LiteralPath $InnoScript -PathType Leaf)) {
    throw "Missing Inno Setup script: $InnoScript"
  }
  if (-not (Test-Path -LiteralPath $InstallerIcon -PathType Leaf)) {
    throw "Missing installer icon: $InstallerIcon"
  }
  if (Test-Path -LiteralPath $InstallerPath) {
    throw "Release installer already exists: $InstallerPath"
  }

  $Iscc = Find-InnoSetupCompiler -Requested $InnoSetupCompiler
  Invoke-Native -FilePath $Iscc -Arguments @(
    "/Qp",
    "/DMyAppVersion=$Version",
    "/DSourceDir=$StagingDir",
    "/DOutputDir=$OutputDir",
    "/DOutputBaseFilename=$InstallerBaseName",
    "/DIconFile=$InstallerIcon",
    $InnoScript
  )
  if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Inno Setup completed but expected installer was not found: $InstallerPath"
  }
  $InstallerVersionInfo = (Get-Item -LiteralPath $InstallerPath).VersionInfo
  $InstallerProductVersion = [string]$InstallerVersionInfo.ProductVersion
  $InstallerFileVersion = [string]$InstallerVersionInfo.FileVersion
  if ($InstallerProductVersion.Trim() -ne $Version) {
    throw "Installer ProductVersion '$InstallerProductVersion' does not match release version '$Version'."
  }
  if ([string]::IsNullOrWhiteSpace($InstallerFileVersion)) {
    throw "Installer FileVersion metadata is missing."
  }
  if ($SigningEnabled) {
    Invoke-CodeSign `
      -SignTool $ResolvedSignTool `
      -CertificateThumbprint $CodeSigningCertificateThumbprint `
      -Path $InstallerPath `
      -Timestamp $TimestampUrl
  }
}

$AssetPaths = @()
if (-not $SkipInstaller) {
  $AssetPaths += $InstallerPath
}
$AssetPaths += @($ZipPath, $ExeAssetPath)

$AssetHashes = $AssetPaths |
  ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
  }
Write-Utf8NoBomLines -Path $HashPath -Lines @($AssetHashes)

$CurrentReleaseTemp = Join-Path $OutputDir ".CURRENT_WINDOWS_RELEASE.$([Guid]::NewGuid().ToString('N')).tmp"
try {
  [System.IO.File]::WriteAllText(
    $CurrentReleaseTemp,
    $Version,
    [System.Text.UTF8Encoding]::new($false)
  )
  Move-Item -LiteralPath $CurrentReleaseTemp -Destination $CurrentReleasePath -Force
} finally {
  if (Test-Path -LiteralPath $CurrentReleaseTemp) {
    Remove-Item -LiteralPath $CurrentReleaseTemp -Force
  }
}

Write-Host "Created $ZipPath"
Write-Host "Created $ExeAssetPath"
if (-not $SkipInstaller) {
  Write-Host "Created $InstallerPath"
}
Write-Host "Created $HashPath"
Write-Host "Updated $CurrentReleasePath"
