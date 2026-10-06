$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..
Write-Host "== ALTRON IDE setup =="

$dockerOk = $false
try {
  docker info 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch { $dockerOk = $false }

if ($dockerOk) {
  Write-Host "Pulling codercom/code-server (first time may take a few minutes)..."
  docker pull codercom/code-server:latest
  Write-Host "Done. Say in ALTRON chat: open ide"
  Write-Host "Or run: .\\scripts\\start_code_server.ps1"
  exit 0
}

Write-Host "Docker not available — trying npm global code-server..."
$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
  Write-Host "Need Docker Desktop (recommended) OR Node.js+npm."
  exit 1
}
npm install --global code-server
Write-Host "npm install finished. Say: open ide"
