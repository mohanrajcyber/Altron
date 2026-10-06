from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "ida": "ida64.exe",
    "ida pro": "ida64.exe",
    "ida free": "ida64.exe",
    "ida64": "ida64.exe",
    "ida64 pro": "ida64.exe",
}

APP_CANDIDATES = {
    "chrome.exe": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "msedge.exe": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "ida64.exe": [
        r"C:\Program Files\IDA Pro\ida64.exe",
        r"C:\Program Files\IDA Free\ida64.exe",
        r"C:\Program Files (x86)\IDA Pro\ida64.exe",
        r"C:\Program Files (x86)\IDA Free\ida64.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Free\ida64.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Pro\ida64.exe"),
    ],
    "ida.exe": [
        r"C:\Program Files\IDA Pro\ida.exe",
        r"C:\Program Files\IDA Free\ida.exe",
        r"C:\Program Files (x86)\IDA Pro\ida.exe",
        r"C:\Program Files (x86)\IDA Free\ida.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Free\ida.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Pro\ida.exe"),
    ],
    "idat.exe": [
        r"C:\Program Files\IDA Pro\idat.exe",
        r"C:\Program Files (x86)\IDA Pro\idat.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Pro\idat.exe"),
    ],
    "idag.exe": [
        r"C:\Program Files\IDA Pro\idag.exe",
        r"C:\Program Files (x86)\IDA Pro\idag.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Pro\idag.exe"),
    ],
    "idafree.exe": [
        r"C:\Program Files\IDA Free\idafree.exe",
        r"C:\Program Files (x86)\IDA Free\idafree.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\IDA Free\idafree.exe"),
    ],
}

DEFAULT_TAB = "https://www.google.com"


def start_file(path: str) -> None:
    os.startfile(path)


def launch_process(args: list[str]) -> bool:
    try:
        subprocess.Popen(args, shell=False)
        return True
    except OSError as exc:
        raise RuntimeError(f"Failed to launch {' '.join(args)}: {exc}") from exc


def resolve_app(exe: str) -> str | None:
    found = shutil.which(exe)
    if found:
        return found
    for candidate in APP_CANDIDATES.get(exe, []):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def open_url(url: str) -> str:
    target = _safe_http_url(url) or DEFAULT_TAB
    # Prefer Chrome so the tab stays in the user's normal browser (not a Playwright temp window).
    chrome = resolve_app("chrome.exe")
    if chrome:
        try:
            launch_process([chrome, target])
            return f"Opened {target} in Chrome (stays open)."
        except RuntimeError as exc:
            return f"Could not launch Chrome for {target}: {exc}"
    try:
        start_file(target)
        return f"Opened {target} in your default browser."
    except OSError as exc:
        return f"Could not open {target} in the default browser: {exc}"


def open_new_tab(user_text: str = "") -> str:
    url = extract_url(user_text) or DEFAULT_TAB
    return open_url(url)


def open_ida(app_name: str | None = None) -> str:
    key = (app_name or "ida").strip().lower().replace("_", " ")
    if key in {"ida pro", "ida free", "ida", "ida64", "ida64 pro"}:
        for candidate in ("ida64.exe", "idat.exe", "ida.exe", "idafree.exe", "idag.exe"):
            path = resolve_app(candidate)
            if path:
                display_path = os.path.normpath(path)
                try:
                    launch_process([path])
                    return f"Launched {display_path}."
                except RuntimeError as exc:
                    return f"Could not launch {display_path}: {exc}"
        return "IDA is not installed or not in the configured app paths on this PC. Install IDA Pro or IDA Free, or point ALTRON at the executable path."
    return open_app(key)


def open_app(name: str) -> str:
    key = name.strip().lower().replace("_", " ")
    normalized = re.sub(r"\s+", " ", key).strip()
    if normalized in {"ida", "ida pro", "ida free", "ida64", "ida64 pro"}:
        return open_ida(normalized)
    exe = ALLOWED_APPS.get(normalized)
    if not exe:
        allowed = ", ".join(sorted(set(ALLOWED_APPS)))
        return f"I can open: {allowed}."
    path = resolve_app(exe)
    if not path:
        if normalized in {"chrome", "edge"}:
            # Still open a page in the default browser.
            open_url(DEFAULT_TAB)
            return f"{exe} not found on PATH — opened default browser instead."
        return f"Could not find {exe} on this PC."
    display_path = os.path.normpath(path)
    try:
        launch_process([path])
        return f"Launched {display_path}."
    except RuntimeError as exc:
        return f"Could not launch {display_path}: {exc}"


def open_explorer(path: str | None = None) -> str:
    target = path or os.path.expanduser("~")
    try:
        launch_process(["explorer.exe", target])
        return f"Opened Explorer at {target}."
    except RuntimeError as exc:
        return f"Could not open Explorer at {target}: {exc}"


def shutdown_request(confirmed: bool) -> str:
    if not confirmed:
        return (
            "I can shut this Windows PC down, but not on a casual ask. "
            "Type CONFIRM SHUTDOWN for a 30-second shutdown. Cancel with: shutdown /a"
        )
    try:
        launch_process(["shutdown", "/s", "/t", "30"])
        return "Shutdown scheduled in 30 seconds. Cancel with: shutdown /a"
    except RuntimeError as exc:
        return f"Could not schedule shutdown: {exc}"


def extract_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s]+", text, flags=re.I)
    if match:
        return match.group(0).rstrip(".,)")
    lowered = text.lower()
    if "youtube" in lowered:
        return "https://www.youtube.com"
    if "google" in lowered:
        return "https://www.google.com"
    return None


def _safe_http_url(url: str) -> str | None:
    raw = url.strip()
    if not raw:
        return None
    if not re.match(r"^https?://", raw, flags=re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw
