$ErrorActionPreference = "SilentlyContinue"
Write-Host "== LiveKit / ComfyUI helpers =="
Write-Host "LiveKit: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env"
Write-Host "Then: python -m altron voice"
Write-Host ""
Write-Host "ComfyUI: start your ComfyUI server on http://127.0.0.1:8188"
Write-Host "Then in ALTRON chat: comfy a red robot"
Write-Host ""
try {
  $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 1
  Write-Host "ComfyUI: UP ($($r.StatusCode))"
} catch {
  Write-Host "ComfyUI: down"
}
