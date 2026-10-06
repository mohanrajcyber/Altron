from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from altron.adapters.mcp_fetch import is_public_http_url, web_fetch

MAX_TEXT = 5000
MAX_STEPS = 8

# Safer allowlist: exact hosts or *.suffix patterns. Empty = any public http(s).
DEFAULT_ALLOW = [
    "example.com",
    "*.example.com",
    "google.com",
    "*.google.com",
    "wikipedia.org",
    "*.wikipedia.org",
    "github.com",
    "*.github.com",
    "youtube.com",
    "*.youtube.com",
    "news.google.com",
    "mail.google.com",
    "reddit.com",
    "*.reddit.com",
    "stackoverflow.com",
    "*.stackoverflow.com",
    "microsoft.com",
    "*.microsoft.com",
    "web.whatsapp.com",
    "whatsapp.com",
    "*.whatsapp.com",
    "open.spotify.com",
    "spotify.com",
    "*.spotify.com",
    "maps.google.com",
    "outlook.live.com",
    "outlook.office.com",
    "*.office.com",
]


def host_allowed(url: str, allowlist: list[str] | None = None) -> bool:
    if not is_public_http_url(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    rules = allowlist if allowlist is not None else DEFAULT_ALLOW
    if not rules:
        return True
    for rule in rules:
        rule = rule.lower().strip()
        if not rule:
            continue
        if rule.startswith("*."):
            suffix = rule[1:]  # .example.com
            if host.endswith(suffix) or host == rule[2:]:
                return True
        elif host == rule or host.endswith("." + rule):
            return True
    return False


def browse(
    url: str,
    action: str = "read",
    selector: str = "",
    text: str = "",
    steps: list[dict] | None = None,
    headless: bool = False,
    allowlist: list[str] | None = None,
) -> str:
    if not host_allowed(url, allowlist):
        return (
            "Blocked: URL not on browser allowlist (or not public http/s). "
            f"Allowed samples: {', '.join(DEFAULT_ALLOW[:6])}…"
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        body = web_fetch(url)
        return f"Playwright not installed — fetched text instead.\n{body}"

    notes: list[str] = []
    try:
        with sync_playwright() as p:
            browser = _launch(p, headless=headless)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            notes.append(f"Opened {url} ({'headless' if headless else 'visible'}).")

            plan = list(steps or [])
            if not plan:
                plan = [{"action": action or "read", "selector": selector, "text": text}]

            for i, step in enumerate(plan[:MAX_STEPS], start=1):
                note = _run_step(page, step, index=i)
                notes.append(note)
                if step.get("action") in {"goto", "open"} and step.get("url"):
                    next_url = str(step.get("url") or "")
                    if next_url and not host_allowed(next_url, allowlist):
                        browser.close()
                        return "Blocked mid-flow: next URL not allowlisted.\n" + "\n".join(notes)

            title = page.title()
            content = page.inner_text("body")[:MAX_TEXT]
            # Keep visible window briefly so the user can see it.
            if not headless:
                page.wait_for_timeout(1200)
            browser.close()
            return "\n".join(notes) + f"\nTitle: {title}\n{content}"
    except Exception as exc:  # noqa: BLE001
        body = web_fetch(url)
        return f"Browser control fallback (Playwright: {exc}).\n{body}"


def parse_steps(raw: str | list | None) -> list[dict]:
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)][:MAX_STEPS]
    if not raw:
        return []
    text = str(raw).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)][:MAX_STEPS]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    # Natural language mini-DSL: click "Sign in" | type "#q" hello | wait 1
    steps: list[dict] = []
    for part in re.split(r"\s*\|\s*", text):
        part = part.strip()
        if not part:
            continue
        low = part.lower()
        if low.startswith("click "):
            target = part[6:].strip().strip("\"'")
            if target.startswith("#") or target.startswith(".") or " " not in target and ("[" in target or "/" in target):
                steps.append({"action": "click", "selector": target})
            else:
                steps.append({"action": "click_text", "text": target})
        elif low.startswith("type "):
            rest = part[5:].strip()
            m = re.match(r"(\S+)\s+(.+)$", rest)
            if m:
                steps.append({"action": "type", "selector": m.group(1), "text": m.group(2).strip("\"'")})
        elif low.startswith("wait "):
            try:
                sec = float(low.split()[1])
            except (IndexError, ValueError):
                sec = 1.0
            steps.append({"action": "wait", "ms": int(sec * 1000)})
        elif low.startswith("goto ") or low.startswith("open "):
            steps.append({"action": "goto", "url": part.split(None, 1)[1].strip()})
        elif low == "read":
            steps.append({"action": "read"})
    return steps[:MAX_STEPS]


def _run_step(page, step: dict, index: int) -> str:
    action = str(step.get("action") or "read").lower()
    selector = str(step.get("selector") or "")
    text = str(step.get("text") or "")
    if action in {"goto", "open"}:
        url = str(step.get("url") or "")
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        return f"{index}. Went to {url}."
    if action == "click" and selector:
        page.click(selector, timeout=10000)
        return f"{index}. Clicked `{selector}`."
    if action == "type" and selector:
        page.fill(selector, text, timeout=10000)
        return f"{index}. Typed into `{selector}`."
    if action == "press" and text:
        page.keyboard.press(text)
        return f"{index}. Pressed {text}."
    if action == "click_text" and text:
        page.get_by_text(text, exact=False).first.click(timeout=10000)
        return f"{index}. Clicked text '{text}'."
    if action == "wait":
        ms = int(step.get("ms") or 1000)
        page.wait_for_timeout(max(100, min(ms, 10000)))
        return f"{index}. Waited {ms}ms."
    if action == "read":
        return f"{index}. Read page."
    return f"{index}. Skipped unknown action `{action}`."


def _launch(p, headless: bool = False):
    for channel in ("chrome", "msedge"):
        try:
            return p.chromium.launch(channel=channel, headless=headless)
        except Exception:
            continue
    return p.chromium.launch(headless=headless)
