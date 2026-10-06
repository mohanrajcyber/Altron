from __future__ import annotations

"""Google Maps sticky — search place → directions → start."""

import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from altron.adapters import browser_session

MAPS_URL = "https://www.google.com/maps"


def open_maps(intent_path: Path) -> str:
    try:
        browser_session.run(_goto, MAPS_URL, reset_on_closed=True)
        _set_intent(intent_path, "maps_control")
        return (
            "Maps under ALTRON control.\n"
            "Say: search Marina Beach · directions to Airport · start · "
            "zoom in · close maps"
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open Maps: {exc}"


def act(user_text: str, intent_path: Path) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Maps listening — search … · directions to … · start · close maps"
    lowered = text.lower().strip().rstrip(".!?")

    if _wants_close(lowered):
        return close_maps(intent_path)
    if lowered in {"start", "start navigation", "go", "navigate", "begin"}:
        return start_nav(intent_path)
    if re.search(r"\bzoom in\b", lowered) or lowered == "zoom in":
        return _key(intent_path, "+", "Zoomed in.")
    if re.search(r"\bzoom out\b", lowered) or lowered == "zoom out":
        return _key(intent_path, "-", "Zoomed out.")

    m = re.match(
        r"^(directions?(?:\s+to)?|navigate to|route to|go to)\s+(.+)$",
        text,
        flags=re.I,
    )
    if m:
        return directions(intent_path, m.group(2).strip())

    m = re.match(r"^(search|find|locate|show)\s+(.+)$", text, flags=re.I)
    if m:
        return search(intent_path, m.group(2).strip())

    # bare place name
    if len(lowered) >= 2:
        return search(intent_path, text.strip())
    return "Try: search … · directions to … · start · close maps"


def search(intent_path: Path, query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "Where should I search?"
    try:
        url = f"{MAPS_URL}/search/{quote_plus(q)}"
        browser_session.run(_goto, url, reset_on_closed=True)
        _set_intent(intent_path, "maps_control", place=q)
        return f"Maps search: {q}\nSay directions to … · start · close maps"
    except Exception as exc:  # noqa: BLE001
        return f"Maps search failed: {exc}"


def directions(intent_path: Path, dest: str) -> str:
    dest = (dest or "").strip()
    if not dest:
        return "Directions to where?"
    data = _read_intent(intent_path)
    origin = (data.get("place") or "").strip()
    try:
        if origin:
            url = f"{MAPS_URL}/dir/{quote_plus(origin)}/{quote_plus(dest)}"
        else:
            url = f"{MAPS_URL}/dir//{quote_plus(dest)}"
        browser_session.run(_goto, url, reset_on_closed=True)
        _set_intent(intent_path, "maps_control", place=dest)
        return f"Directions to: {dest}\nSay start to begin navigation."
    except Exception as exc:  # noqa: BLE001
        return f"Directions failed: {exc}"


def start_nav(intent_path: Path) -> str:
    try:
        browser_session.run(_click_start, reset_on_closed=True)
        _set_intent(intent_path, "maps_control")
        return "Started navigation (if Start was available)."
    except Exception as exc:  # noqa: BLE001
        return f"Start failed: {exc}. Open directions first."


def close_maps(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared Maps mode ({exc})."
    return "Closed Maps control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "maps_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _key(intent_path: Path, key: str, ok: str) -> str:
    try:
        browser_session.run(_press, key, reset_on_closed=True)
        _set_intent(intent_path, "maps_control")
        return ok
    except Exception as exc:  # noqa: BLE001
        return f"Zoom failed: {exc}"


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1000)


def _click_start(page) -> None:
    for lab in ("Start", "Start navigation", "Preview"):
        try:
            loc = page.get_by_role("button", name=re.compile(rf"^{lab}$", re.I))
            if loc.count():
                loc.first.click(timeout=5000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue
    for sel in (
        'button[aria-label*="Start" i]',
        'button[jsaction*="navigation"]',
        'button[data-value="Directions"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=5000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue
    raise RuntimeError("Start button not found — say directions to … first")


def _press(page, key: str) -> None:
    page.keyboard.press(key)
    page.wait_for_timeout(200)


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bmaps?\b", lowered)
        or lowered in {"close maps", "close map", "exit maps", "stop maps"}
    )


def _set_intent(path: Path, expect: str, place: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"expect": expect}
    if place:
        data["place"] = place
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
