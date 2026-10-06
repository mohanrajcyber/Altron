$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..
Write-Host "== Start ALTRON real IDE (code-server) =="

$port = 8443
if ($env:ALTRON_IDE_PORT) { $port = [int]$env:ALTRON_IDE_PORT }
$workspace = (Resolve-Path ".").Path
$hostPath = ($workspace -replace '\\','/')
$url = "http://127.0.0.1:$port/?folder=/home/coder/project"

$dockerOk = $false
try {
  docker info 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch { $dockerOk = $false }

if ($dockerOk) {
  docker rm -f altron-ide 1>$null 2>$null
  Write-Host "Creating Docker IDE with ALTRON project folder..."
  docker run -d --name altron-ide `
    -p "127.0.0.1:${port}:8080" `
    -v "${hostPath}:/home/coder/project" `
    -e PASSWORD=altron `
    codercom/code-server:latest `
    --auth none --disable-telemetry --disable-workspace-trust /home/coder/project
  Start-Sleep -Seconds 3
  Write-Host "IDE: $url"
  Start-Process $url
  exit 0
}

Write-Host "Docker unavailable — use Docker Desktop for the real IDE."
exit 1
