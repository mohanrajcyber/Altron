$ErrorActionPreference = "Continue"
Write-Host "== Start Qdrant (Docker) =="

$dockerOk = $false
try {
  docker info 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch {
  $dockerOk = $false
}

if (-not $dockerOk) {
  Write-Host "Docker Desktop engine is not running."
  Write-Host "Start Docker Desktop, wait until it is green, then re-run:"
  Write-Host "  .\\scripts\\start_qdrant.ps1"
  Write-Host "Until then ALTRON keeps using local_vector memory (already works)."
  exit 1
}

$existing = docker ps -a --filter "name=altron-qdrant" --format "{{.Names}}"
if ($existing -eq "altron-qdrant") {
  docker start altron-qdrant | Out-Null
  Write-Host "Started existing container altron-qdrant"
} else {
  docker run -d --name altron-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
  Write-Host "Created altron-qdrant on :6333"
}

Start-Sleep -Seconds 3
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\ensure_qdrant.py"
Write-Host "Qdrant ready. Restart ALTRON so status shows memory=qdrant."
