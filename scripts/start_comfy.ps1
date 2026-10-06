$ErrorActionPreference = "Continue"
Write-Host "== ComfyUI helper =="
Write-Host "ALTRON expects ComfyUI at http://127.0.0.1:8188"
Write-Host "Install/start ComfyUI yourself, then chat: comfy a red robot"
Write-Host ""
try {
  $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 2
  Write-Host "ComfyUI: UP ($($r.StatusCode))"
} catch {
  Write-Host "ComfyUI: down (optional - skip if you do not use image gen)"
}
