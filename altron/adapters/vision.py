from __future__ import annotations

import base64
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from altron.settings import Settings


def see_screen(settings: Settings, prompt: str = "") -> str:
    """Capture primary monitor and describe it (vision API if available)."""
    path = capture_screen(settings.altron_data_dir / "screens")
    meta = f"Screenshot saved: {path.name} ({path.stat().st_size // 1024} KB)"
    description = _describe(settings, path, prompt=prompt or "Describe what is on this Windows screen. Be concise.")
    if description:
        return f"{meta}\n\n{description}\n\nSay what to click/type next (open browser / open youtube / open notepad …)."
    return (
        f"{meta}\n"
        "Vision model unavailable — image is on disk. "
        "Install Pillow for better capture, or use a vision-capable NIM model.\n"
        f"Path: {path}"
    )


def capture_screen(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"screen_{stamp}.png"
    if _capture_pil(path):
        return path
    if _capture_powershell(path):
        return path
    raise RuntimeError("Could not capture screen (need Pillow or PowerShell Drawing).")


def _capture_pil(path: Path) -> bool:
    try:
        from PIL import ImageGrab
    except ImportError:
        return False
    img = ImageGrab.grab(all_screens=False)
    img.save(path)
    return path.is_file()


def _capture_powershell(path: Path) -> bool:
    # Native Windows screenshot without extra packages
    script = f"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('{str(path).replace("'", "''")}')
$g.Dispose(); $bmp.Dispose()
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.returncode == 0 and path.is_file()
    except Exception:
        return False


def _describe(settings: Settings, path: Path, prompt: str) -> str:
    if not settings.api_keys:
        return _local_hint(path)
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.api_keys[0],
            base_url=settings.nvidia_nim_api_base,
        )
        # Try multimodal message; if model rejects, fall back.
        model = (settings.altron_model or "").strip() or "nvidia/nemotron-3-super-120b-a12b"
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=500,
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or _local_hint(path)
    except Exception:
        return _local_hint(path)


def _local_hint(path: Path) -> str:
    w = h = "?"
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        pass
    return f"Screen capture ready ({w}x{h}). No vision description available from the current model."
