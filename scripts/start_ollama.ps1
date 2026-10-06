$ErrorActionPreference = "SilentlyContinue"
Set-Location $PSScriptRoot\..

Write-Host "Ensuring Ollama..."
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  Write-Host "Ollama not on PATH. Install from https://ollama.com or winget install Ollama.Ollama"
  exit 1
}

Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 2
& ollama pull llama3.1
Write-Host "Ollama ready. ALTRON Think fallback: NVIDIA -> Ollama -> local stub"
