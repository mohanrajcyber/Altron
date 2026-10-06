$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$exe = Join-Path $PWD "dist\ALTRON.exe"
if (-not (Test-Path $exe)) {
  Write-Host "Building ALTRON.exe first..."
  powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
}

$programs = [Environment]::GetFolderPath("Programs")
$altronDir = Join-Path $programs "ALTRON"
New-Item -ItemType Directory -Force -Path $altronDir | Out-Null

$shortcutPath = Join-Path $altronDir "ALTRON.lnk"
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $exe
$sc.WorkingDirectory = (Split-Path $exe)
$sc.WindowStyle = 1
$sc.Description = "ALTRON Command Core"
$sc.Save()

$desktop = [Environment]::GetFolderPath("Desktop")
$deskLink = Join-Path $desktop "ALTRON.lnk"
Copy-Item $shortcutPath $deskLink -Force

# Simple setup launcher (no MSIX signing required)
$setup = Join-Path $PWD "dist\ALTRON-Setup.cmd"
@"
@echo off
echo Installing ALTRON shortcuts...
powershell -ExecutionPolicy Bypass -File "%~dp0..\scripts\install_shortcuts.ps1"
echo Done. Launch ALTRON from Start Menu or Desktop.
pause
"@ | Set-Content -Encoding ascii $setup

Write-Host "Start Menu: $shortcutPath"
Write-Host "Desktop:    $deskLink"
Write-Host "Setup cmd:  $setup"
Write-Host "MSIX store package needs a signing cert - use Setup.cmd + shortcuts for now."
