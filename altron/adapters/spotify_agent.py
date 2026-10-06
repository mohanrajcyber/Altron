from __future__ import annotations

"""Spotify sticky control — open.spotify.com (same idea as YouTube). Desktop app: media keys."""

import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from altron.adapters import browser_session, computer

SPOTIFY_URL = "https://open.spotify.com"


def open_spotify(intent_path: Path) -> str:
    try:
        browser_session.run(_goto, SPOTIFY_URL, reset_on_closed=True)
        _set_intent(intent_path, "spotify_control")
        return (
            "Spotify Web under ALTRON control (log in if asked).\n"
            "Say: search … · play · pause · next · previous · volume up/down · mute\n"
            "Or: open spotify app (desktop) then play/pause/next via media keys.\n"
            "close spotify when done."
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open Spotify: {exc}"


def open_spotify_app(intent_path: Path) -> str:
    """Launch desktop Spotify if installed; sticky still accepts media-key commands."""
    candidates = [
        os_path_spotify(),
    ]
    launched = False
    for path in candidates:
        if path:
            try:
                computer.launch_process([path])
                launched = True
                break
            except Exception:
                continue
    if not launched:
        # Protocol / Start Menu
        try:
            computer.start_file("spotify:")
            launched = True
        except Exception:
            pass
    _set_intent(intent_path, "spotify_control", mode="app")
    if launched:
        return (
            "Opened Spotify app. Say: play · pause · next · previous · volume up/down\n"
            "(Uses Windows media keys.) close spotify when done."
        )
    return (
        "Spotify app not found — opening Spotify Web instead.\n" + open_spotify(intent_path)
    )


def act(user_text: str, intent_path: Path) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Spotify listening — search … · play · pause · next · close spotify"
    lowered = text.lower().strip().rstrip(".!?")
    data = _read_intent(intent_path)
    app_mode = (data.get("mode") or "") == "app"

    if _wants_close(lowered):
        return close_spotify(intent_path)
    if re.search(r"\b(open\s+)?spotify\s+app\b", lowered) or lowered == "spotify app":
        return open_spotify_app(intent_path)

    if lowered in {"play", "resume", "unpause"} or re.match(r"^play\s*$", lowered):
        return _media(intent_path, "play", app_mode)
    if lowered in {"pause", "stop"}:
        return _media(intent_path, "pause", app_mode)
    if lowered in {"next", "next song", "skip", "skip song"}:
        return _media(intent_path, "next", app_mode)
    if lowered in {"previous", "prev", "back", "last song", "previous song"}:
        return _media(intent_path, "previous", app_mode)
    if re.search(r"\b(volume|louder|quieter|mute|unmute|soft)\b", lowered):
        return _volume(intent_path, lowered, app_mode)

    m = re.match(r"^(search|find|play)\s+(.+)$", text, flags=re.I)
    if m and m.group(1).lower() in {"search", "find"}:
        return search_spotify(intent_path, m.group(2).strip())
    if m and m.group(1).lower() == "play" and len(m.group(2).strip()) > 1:
        # play <song>
        return search_spotify(intent_path, m.group(2).strip(), autoplay=True)

    if app_mode:
        return "Spotify app mode: play · pause · next · previous · volume up · close spotify"
    # bare query → search
    if len(lowered) >= 2 and not lowered.startswith("close"):
        return search_spotify(intent_path, text.strip())
    return "Try: search … · play · pause · next · close spotify"


def search_spotify(intent_path: Path, query: str, autoplay: bool = False) -> str:
    q = (query or "").strip()
    if not q:
        return "What should I search on Spotify?"
    try:
        browser_session.run(_search, q, autoplay, reset_on_closed=True)
        _set_intent(intent_path, "spotify_control")
        return f"Spotify search: {q}" + (" (play)" if autoplay else "") + "\nSay play · pause · next · close spotify"
    except Exception as exc:  # noqa: BLE001
        return f"Spotify search failed: {exc}"


def close_spotify(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared Spotify mode ({exc})."
    return "Closed Spotify control."


def expecting_control(intent_path: Path) -> bool:
    if _read_intent(intent_path).get("expect") != "spotify_control":
        return False
    if not browser_session.is_live():
        clear_expect(intent_path)
        return False
    return True


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _media(intent_path: Path, action: str, app_mode: bool) -> str:
    try:
        if app_mode:
            _send_media_key(action)
        else:
            browser_session.run(_press_media, action, reset_on_closed=True)
        _set_intent(intent_path, "spotify_control", mode="app" if app_mode else "")
        return f"Spotify: {action}."
    except Exception as exc:  # noqa: BLE001
        return f"Spotify {action} failed: {exc}"


def _volume(intent_path: Path, lowered: str, app_mode: bool) -> str:
    if "mute" in lowered or "unmute" in lowered:
        action = "mute"
    elif any(k in lowered for k in ("down", "quieter", "soft")):
        action = "vol_down"
    else:
        action = "vol_up"
    try:
        if app_mode:
            _send_media_key(action)
        else:
            browser_session.run(_press_media, action, reset_on_closed=True)
        _set_intent(intent_path, "spotify_control", mode="app" if app_mode else "")
        return f"Spotify volume: {action}."
    except Exception as exc:  # noqa: BLE001
        return f"Volume failed: {exc}"


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)


def _search(page, query: str, autoplay: bool) -> None:
    if "spotify.com" not in (page.url or ""):
        page.goto(SPOTIFY_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
    url = f"https://open.spotify.com/search/{quote_plus(query)}"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    if autoplay:
        # Click first Play / result row
        for sel in (
            'button[data-testid="play-button"]',
            'button[aria-label^="Play" i]',
            '[data-testid="top-result-card"] button',
            'div[data-testid="tracklist-row"] button[aria-label^="Play" i]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count():
                    loc.click(timeout=5000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue


def _press_media(page, action: str) -> None:
    if "spotify.com" not in (page.url or ""):
        raise RuntimeError("Spotify Web is not open — say open spotify")
    # Prefer UI buttons; fallback keys
    mapping = {
        "play": ('button[data-testid="control-button-playpause"]', " "),
        "pause": ('button[data-testid="control-button-playpause"]', " "),
        "next": ('button[data-testid="control-button-skip-forward"]', "ArrowRight"),
        "previous": ('button[data-testid="control-button-skip-back"]', "ArrowLeft"),
        "mute": (None, "m"),
        "vol_up": (None, "ArrowUp"),
        "vol_down": (None, "ArrowDown"),
    }
    sel, key = mapping.get(action, (None, None))
    if sel:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=3000)
                page.wait_for_timeout(200)
                return
        except Exception:
            pass
    if key:
        page.keyboard.press(key)
        page.wait_for_timeout(150)
        return
    raise RuntimeError(f"Unknown action {action}")


def _send_media_key(action: str) -> None:
    """Windows virtual-key media controls for desktop Spotify."""
    import ctypes

    VK = {
        "play": 0xB3,  # VK_MEDIA_PLAY_PAUSE
        "pause": 0xB3,
        "next": 0xB0,  # VK_MEDIA_NEXT_TRACK
        "previous": 0xB1,  # VK_MEDIA_PREV_TRACK
        "mute": 0xAD,  # VK_VOLUME_MUTE
        "vol_up": 0xAF,
        "vol_down": 0xAE,
    }
    code = VK.get(action)
    if code is None:
        raise RuntimeError(f"No media key for {action}")
    # key down + up
    ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(code, 0, 2, 0)


def os_path_spotify() -> str | None:
    import os

    candidates = [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
        r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_*\Spotify.exe",
    ]
    for c in candidates[:2]:
        if c and Path(c).is_file():
            return c
    return computer.resolve_app("Spotify.exe")


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bspotify\b", lowered)
        or lowered in {"close spotify", "exit spotify", "stop spotify"}
    )


def _set_intent(path: Path, expect: str, mode: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"expect": expect}
    if mode:
        data["mode"] = mode
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
