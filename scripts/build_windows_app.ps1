$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $Root "dist\windows"
$Launcher = Join-Path $Root "windows\PaperMonitor.pyw"
$Icon = Join-Path $Root "windows\assets\PaperMonitor.ico"

Set-Location $Root
python "$Root\scripts\generate_windows_icon.py" | Out-Null

# PyInstaller is provided by requirements-windows.txt.
python -m PyInstaller `
  --noconsole `
  --onefile `
  --name PaperMonitor `
  --icon "$Icon" `
  --hidden-import pystray `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageDraw `
  --hidden-import win11toast `
  --distpath "$DistDir" `
  --workpath "$Root\build\windows" `
  --specpath "$Root\build\windows" `
  "$Launcher"

Write-Host "Built $DistDir\PaperMonitor.exe"
