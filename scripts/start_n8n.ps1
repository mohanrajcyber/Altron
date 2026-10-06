$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..
Write-Host "== Start n8n for ALTRON =="

$webhookPath = "altron-jobs"
$dataDir = Join-Path $PWD "data\n8n"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$dockerOk = $false
try {
  docker info 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch {
  $dockerOk = $false
}

if ($dockerOk) {
  $existing = docker ps -a --filter "name=altron-n8n" --format "{{.Names}}"
  if ($existing -eq "altron-n8n") {
    docker start altron-n8n | Out-Null
  } else {
    docker run -d --name altron-n8n -p 5678:5678 `
      -e N8N_HOST=127.0.0.1 `
      -e N8N_PORT=5678 `
      -e N8N_PROTOCOL=http `
      -e WEBHOOK_URL=http://127.0.0.1:5678/ `
      -v "${dataDir}:/home/node/.n8n" `
      n8nio/n8n
  }
  Write-Host "n8n Docker on http://127.0.0.1:5678"
} else {
  Write-Host "Docker unavailable - starting npx n8n (first run may take a while)..."
  Start-Process -FilePath "npx" -ArgumentList "--yes","n8n" -WorkingDirectory $PWD -WindowStyle Minimized
  Write-Host "n8n process started (minimized)."
}

$webhook = "http://127.0.0.1:5678/webhook/$webhookPath"
Write-Host ""
Write-Host "Next steps:"
Write-Host " - Open http://127.0.0.1:5678"
Write-Host " - Create Webhook node with path: $webhookPath"
Write-Host " - Add to ALTRON/.env : N8N_WEBHOOK_URL=$webhook"
Write-Host " - Restart: python -m altron serve"
Write-Host " - Chat: enqueue backup"
