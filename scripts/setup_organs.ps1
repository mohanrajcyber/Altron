$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "== ALTRON organ setup =="

& .\.venv\Scripts\python.exe -m pip install -e ".[organs]" 

Write-Host "Installing Playwright Chromium..."
& .\.venv\Scripts\python.exe -m playwright install chromium

Write-Host "Building desktop .exe (PyInstaller)..."
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean `
  --name ALTRON `
  --onefile `
  --windowed `
  --add-data "altron\web;altron\web" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols `
  --hidden-import uvicorn.protocols.http `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan `
  --hidden-import uvicorn.lifespan.on `
  -m altron app

Write-Host "Done. Dist: .\dist\ALTRON.exe"
Write-Host "Optional: start Ollama, Qdrant (:6333), n8n (:5678), ComfyUI (:8188)"
Write-Host "Optional keys: E2B_API_KEY, N8N_WEBHOOK_URL, LIVEKIT_*"
