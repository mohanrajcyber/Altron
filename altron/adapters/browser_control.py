from __future__ import annotations

"""General browser control — same sticky concept as YouTube (voice + type)."""

import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from altron.adapters import browser_session
from altron.adapters.browser_agent import host_allowed

DEFAULT_HOME = "https://www.google.com"


def open_browser(intent_path: Path, url: str = "") -> str:
    target = _normalize_url(url) or DEFAULT_HOME
    if not host_allowed(target):
        return f"Blocked URL (not on allowlist): {target}"
    try:
        browser_session.run(_goto, target, reset_on_closed=True)
        _set_intent(intent_path, "browser_control")
        return (
            f"Browser under ALTRON control — opened {target}\n"
            "Try: search news · open first link · open link 2 · go to wikipedia.org · "
            "click Images · type hello · read page · scroll · back · close browser"
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open browser under control: {exc}"


def close_browser(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared browser mode ({exc})."
    return "Closed browser control."


def act(user_text: str, intent_path: Path) -> str:
    """Interpret a voice/type command while browser_control is sticky."""
    text = (user_text or "").strip()
    if not text:
        return "Tell me what to do in the browser."
    lowered = text.lower().strip().rstrip(".!?")

    if _is_close(lowered):
        return close_browser(intent_path)
    if lowered in {"back", "go back", "previous page"}:
        return _run(intent_path, _back, ok="Went back.")
    if lowered in {"forward", "go forward"}:
        return _run(intent_path, _forward, ok="Went forward.")
    if re.search(r"\bscroll (down|up)\b", lowered) or lowered in {"scroll down", "scroll up", "page down", "page up"}:
        down = "up" not in lowered
        return _run(intent_path, _scroll, down, ok=f"Scrolled {'down' if down else 'up'}.")
    if lowered.startswith("read") or lowered in {"what's on the page", "whats on the page", "page text"}:
        return _run_value(intent_path, _read_page)

    # open first link / open link 2 / click first result
    result_idx = _result_index(lowered)
    if result_idx:
        return _run(
            intent_path,
            _open_search_result,
            result_idx,
            ok=f"Opened result #{result_idx}.",
        )

    # go to / open URL
    m = re.match(r"^(go to|goto|navigate to)\s+(.+)$", text, flags=re.I)
    raw_url = m.group(2).strip() if m else ""
    if not raw_url:
        m2 = re.match(r"^open\s+(.+)$", text, flags=re.I)
        if m2:
            raw_url = m2.group(1).strip()
    if raw_url:
        url = _normalize_url(raw_url)
        if url:
            if not host_allowed(url):
                return f"Blocked URL (not on allowlist): {url}"
            return _run(intent_path, _goto, url, ok=f"Opened {url}")
        if re.match(r"^(go to|goto|navigate to)\b", lowered):
            return f"Could not understand URL: {raw_url}"

    # search …
    m = re.match(
        r"^(search( in google)?( for)?|google|find)\s+(.+)$",
        lowered,
    )
    if m or ("search" in lowered and not result_idx):
        q = re.sub(
            r"^(please\s+)?(search( in google)?( for)?|google|find)\s+",
            "",
            text,
            flags=re.I,
        ).strip()
        q = re.sub(r"\s+in google( news)?$", "", q, flags=re.I).strip()
        if lowered in {"search in google news", "google news", "search google news"}:
            return _run(intent_path, _goto, "https://news.google.com", ok="Opened Google News.")
        if "google news" in lowered:
            return _run(intent_path, _goto, "https://news.google.com", ok="Opened Google News.")
        if not q:
            return "What should I search?"
        return _run(intent_path, _google_search, q, ok=f"Searched Google for: {q}")

    # click …
    m = re.match(r"^(click|press|tap)\s+(.+)$", lowered)
    if m:
        target = re.sub(r"^(click|press|tap)\s+", "", text, flags=re.I).strip().strip("\"'")
        return _run(intent_path, _click_text, target, ok=f"Clicked: {target}")

    # type …
    m = re.match(r"^(type|enter|write)\s+(.+)$", lowered)
    if m:
        typed = re.sub(r"^(type|enter|write)\s+", "", text, flags=re.I).strip().strip("\"'")
        return _run(intent_path, _type_text, typed, ok=f"Typed: {typed}")

    # bare query while controlling → Google search (AGI-style)
    if _looks_like_search_query(text):
        return _run(intent_path, _google_search, text.strip(), ok=f"Searched Google for: {text.strip()}")

    return (
        "Browser is listening. Try: search … · open first link · open link 2 · go to example.com · "
        "click … · type … · read page · scroll down · back · close browser"
    )


def expecting_control(intent_path: Path) -> bool:
    if _read_intent(intent_path).get("expect") != "browser_control":
        return False
    if not browser_session.is_live():
        clear_expect(intent_path)
        return False
    return True


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _run(intent_path: Path, fn, *args, ok: str = "Done.") -> str:
    try:
        browser_session.run(fn, *args, reset_on_closed=True)
        _set_intent(intent_path, "browser_control")
        return ok + "\nBrowser still under ALTRON control — say the next step."
    except Exception as exc:  # noqa: BLE001
        return f"Browser action failed: {exc}"


def _run_value(intent_path: Path, fn, *args) -> str:
    try:
        value = browser_session.run(fn, *args, reset_on_closed=True)
        _set_intent(intent_path, "browser_control")
        return str(value)
    except Exception as exc:  # noqa: BLE001
        return f"Browser action failed: {exc}"


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(400)


def _google_search(page, query: str) -> None:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(500)


def _open_search_result(page, index: int) -> None:
    """Click the Nth organic Google (or generic) result link."""
    idx = max(1, min(int(index), 20))
    # Google SERP: prefer main result headings
    candidates = [
        "#search a:has(h3)",
        "#rso a:has(h3)",
        "#search h3",
        "a:has(h3)",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n < idx:
                continue
            target = loc.nth(idx - 1)
            # If we landed on h3, click parent <a>
            try:
                tag = target.evaluate("el => el.tagName")
                if str(tag).upper() == "H3":
                    parent = target.locator("xpath=ancestor::a[1]")
                    if parent.count():
                        parent.first.click(timeout=8000)
                        page.wait_for_timeout(600)
                        return
            except Exception:
                pass
            target.click(timeout=8000)
            page.wait_for_timeout(600)
            return
        except Exception:
            continue
    # Generic: Nth visible http(s) link in main
    links = page.locator("main a[href^='http'], #search a[href^='http'], a[href^='http']")
    seen: list[str] = []
    total = links.count()
    for i in range(min(total, 40)):
        try:
            a = links.nth(i)
            href = (a.get_attribute("href") or "").strip()
            if not href or href in seen:
                continue
            if "google.com" in href and ("/search" in href or "webcache" in href):
                continue
            seen.append(href)
            if len(seen) == idx:
                a.click(timeout=8000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue
    raise RuntimeError(f"Could not find result #{idx} — search first, then say open first link")


_RESULT_WORDS = {
    "one": 1,
    "first": 1,
    "1st": 1,
    "two": 2,
    "second": 2,
    "2nd": 2,
    "three": 3,
    "third": 3,
    "3rd": 3,
    "four": 4,
    "fourth": 4,
    "4th": 4,
    "five": 5,
    "fifth": 5,
    "5th": 5,
}


def _parse_result_num(lowered: str) -> int | None:
    m = re.search(r"\b(\d+)\b", lowered)
    if m:
        return int(m.group(1))
    for word, num in _RESULT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return num
    return None


def _result_index(lowered: str) -> int | None:
    """Detect 'open first link', 'click 2nd result', 'open link 3', etc."""
    if not re.search(r"\b(link|result|results)\b", lowered) and not re.search(
        r"\b(open|click|select)\s+(first|second|third|one|two|three|\d+)\b",
        lowered,
    ):
        # allow short forms: "first link", "second result"
        if not re.search(r"\b(first|second|third|1st|2nd|3rd)\s+(link|result)\b", lowered):
            return None
    if re.search(r"\b(link|result)\b", lowered) or re.search(
        r"\b(open|click|select)\s+(first|second|third|one|two|three|\d+)\b",
        lowered,
    ):
        n = _parse_result_num(lowered)
        if n:
            return n
        if re.search(r"\b(first|1st)\b", lowered):
            return 1
    return None


def _click_text(page, target: str) -> None:
    # Try role/link/button then text
    for getter in (
        lambda: page.get_by_role("link", name=re.compile(re.escape(target), re.I)),
        lambda: page.get_by_role("button", name=re.compile(re.escape(target), re.I)),
        lambda: page.get_by_text(target, exact=False),
    ):
        loc = getter()
        try:
            if loc.count():
                loc.first.click(timeout=8000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    raise RuntimeError(f"Could not find clickable '{target}'")


def _type_text(page, text: str) -> None:
    # Prefer focused / search inputs
    selectors = [
        "textarea[name='q']",
        "input[name='q']",
        "input[type='search']",
        "textarea",
        "input[type='text']",
        "[contenteditable='true']",
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                loc.fill("")
                loc.fill(text)
                loc.press("Enter")
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    page.keyboard.type(text, delay=20)
    page.keyboard.press("Enter")


def _read_page(page) -> str:
    title = ""
    try:
        title = page.title()
    except Exception:
        pass
    body = ""
    try:
        body = page.inner_text("body")[:4000]
    except Exception:
        body = "(could not read body)"
    return f"Page: {title}\nURL: {page.url}\n\n{body}"


def _back(page) -> None:
    page.go_back(wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(300)


def _forward(page) -> None:
    page.go_forward(wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(300)


def _scroll(page, down: bool = True) -> None:
    delta = 900 if down else -900
    page.mouse.wheel(0, delta)
    page.wait_for_timeout(200)


def _normalize_url(raw: str) -> str:
    text = (raw or "").strip().strip("\"'")
    if not text:
        return ""
    lowered = text.lower()
    shortcuts = {
        "google": "https://www.google.com",
        "google.com": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "youtube": "https://www.youtube.com",
        "news": "https://news.google.com",
        "google news": "https://news.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "github": "https://github.com",
    }
    if lowered in shortcuts:
        return shortcuts[lowered]
    if re.match(r"^https?://", text, flags=re.I):
        return text
    if "." in text and " " not in text:
        return "https://" + text.lstrip("/")
    return ""


def _is_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\b(browser|chrome|tab)\b", lowered)
        or lowered in {"close browser", "close chrome", "exit browser", "stop browser"}
    )


def _looks_like_search_query(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) < 2 or len(lowered) > 120:
        return False
    if "?" in text:
        return False
    if _result_index(lowered):
        return False
    if re.match(
        r"^(hi|hello|hey|who|what|why|how|clear|remember|list|shutdown|"
        r"open first|open link|click first|go back|scroll|read)\b",
        lowered,
    ):
        return False
    return True


def _set_intent(path: Path, expect: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"expect": expect}, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
