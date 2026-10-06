from __future__ import annotations

"""WhatsApp Web sticky control — same AGI idea as YouTube (voice → select chat → type/send)."""

import json
import re
from pathlib import Path

from altron.adapters import browser_session

WA_URL = "https://web.whatsapp.com"


def open_whatsapp(intent_path: Path) -> str:
    try:
        browser_session.run(_open_wa, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat="")
        return (
            "WhatsApp Web is under ALTRON control.\n"
            "Scan QR if needed.\n"
            "Then: select Amma · select number 1 / number one / first person\n"
            "Speak a message to send · or: call · video call · hang up\n"
            "Say: close whatsapp when done."
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open WhatsApp: {exc}"


def act(user_text: str, intent_path: Path) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Say a contact name, select number N, or your message to send."
    lowered = text.lower().strip().rstrip(".!?")

    if _wants_close(lowered):
        return close_whatsapp(intent_path)

    # call / video call (never type these as chat text)
    if _wants_call(lowered):
        video = bool(re.search(r"\b(video|facetime)\b", lowered))
        return start_call(intent_path, video=video)
    if _wants_hangup(lowered):
        return hangup_call(intent_path)

    # select number 2 / number one / second person / chat 3
    idx = _select_index(lowered)
    if idx:
        return select_by_index(intent_path, idx)

    # select / open chat / message to NAME
    name = _select_name(text, lowered)
    if name:
        return select_by_name(intent_path, name)

    # explicit send/type
    msg = _explicit_message(text, lowered)
    if msg is not None:
        return send_message(intent_path, msg)

    # sticky: any other line = message to current chat (YouTube-style)
    data = _read_intent(intent_path)
    if data.get("chat"):
        return send_message(intent_path, text)
    return (
        "WhatsApp is listening. First select a chat:\n"
        "· select Amma\n"
        "· select number 1 / number one / first person\n"
        "Then speak the message · or say: call · video call · close whatsapp"
    )


def select_by_name(intent_path: Path, name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "Which contact? Say: select Amma"
    try:
        title = browser_session.run(_select_name_on_page, name, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat=title or name)
        return (
            f"Opened chat: {title or name}\n"
            "Speak your message now (voice or type) — ALTRON will send it.\n"
            "Or say: select … for another person · close whatsapp"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Could not open chat '{name}': {exc}. Is WhatsApp logged in?"


def select_by_index(intent_path: Path, index: int) -> str:
    idx = max(1, min(int(index), 20))
    try:
        title = browser_session.run(_select_index_on_page, idx, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat=title or f"#{idx}")
        return (
            f"Selected person/chat #{idx}: {title or '(chat)'}\n"
            "Speak your message now — ALTRON will type & send."
        )
    except Exception as exc:  # noqa: BLE001
        return f"Could not select chat #{idx}: {exc}"


def send_message(intent_path: Path, message: str) -> str:
    body = (message or "").strip()
    if not body:
        return "Empty message — say what to send."
    try:
        browser_session.run(_type_and_send, body, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat=_read_intent(intent_path).get("chat") or "chat")
        return f"Sent on WhatsApp: {body[:200]}{'…' if len(body) > 200 else ''}"
    except Exception as exc:  # noqa: BLE001
        return f"Send failed: {exc}. Select a chat first, then speak again."


def start_call(intent_path: Path, *, video: bool = False) -> str:
    kind = "video" if video else "voice"
    try:
        browser_session.run(_click_call, video, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat=_read_intent(intent_path).get("chat") or "chat")
        return f"Started {kind} call on WhatsApp. Say hang up to end."
    except Exception as exc:  # noqa: BLE001
        return f"Call failed: {exc}. Open a chat first, then say call / video call."


def hangup_call(intent_path: Path) -> str:
    try:
        browser_session.run(_click_hangup, reset_on_closed=True)
        _set_intent(intent_path, "whatsapp_control", chat=_read_intent(intent_path).get("chat") or "chat")
        return "Ended the WhatsApp call."
    except Exception as exc:  # noqa: BLE001
        return f"Hang up failed: {exc}"


def close_whatsapp(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared WhatsApp mode ({exc})."
    return "Closed WhatsApp control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "whatsapp_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "", chat="")


def _open_wa(page) -> None:
    page.goto(WA_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)


def _select_name_on_page(page, name: str) -> str:
    if "whatsapp" not in (page.url or "").lower():
        page.goto(WA_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
    _focus_search(page)
    box = _search_box(page)
    box.click(timeout=8000)
    box.fill("")
    page.keyboard.type(name, delay=40)
    page.wait_for_timeout(900)
    # Click first matching chat/result
    candidates = [
        f'#pane-side span[title="{name}"]',
        f'span[title="{name}"]',
        f'div[role="listitem"] span[title*="{name}" i]',
        f'span[title*="{name}" i]',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count():
                title = loc.get_attribute("title") or name
                loc.click(timeout=5000)
                page.wait_for_timeout(700)
                return title
        except Exception:
            continue
    # Fallback: click first list item after search
    items = page.locator('#pane-side div[role="listitem"], #pane-side div[role="row"]')
    if items.count() == 0:
        items = page.locator("#pane-side [data-testid='cell-frame-container']")
    if items.count() == 0:
        raise RuntimeError("No chats found — check login / name spelling")
    items.first.click(timeout=5000)
    page.wait_for_timeout(700)
    return name


def _select_index_on_page(page, index: int) -> str:
    if "whatsapp" not in (page.url or "").lower():
        page.goto(WA_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
    # Clear search so list is recent chats
    try:
        box = _search_box(page)
        box.click(timeout=3000)
        box.fill("")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    items = page.locator('#pane-side div[role="listitem"]')
    if items.count() == 0:
        items = page.locator("#pane-side [data-testid='cell-frame-container']")
    if items.count() == 0:
        items = page.locator('#pane-side div[role="row"]')
    if items.count() < index:
        raise RuntimeError(f"Only {items.count()} chats visible — need at least {index}")
    row = items.nth(index - 1)
    title = ""
    try:
        title = (row.locator("span[title]").first.get_attribute("title") or "").strip()
    except Exception:
        title = ""
    row.click(timeout=8000)
    page.wait_for_timeout(700)
    return title or f"chat #{index}"


def _type_and_send(page, message: str) -> None:
    if "whatsapp" not in (page.url or "").lower():
        raise RuntimeError("WhatsApp is not open")
    compose = _compose_box(page)
    compose.click(timeout=8000)
    # clear any leftover
    page.keyboard.press("Control+a")
    page.keyboard.type(message, delay=25)
    page.wait_for_timeout(200)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)


def _click_call(page, video: bool = False) -> None:
    if "whatsapp" not in (page.url or "").lower():
        raise RuntimeError("WhatsApp is not open")
    labels = (
        ("Video call", "video call", "Start video call")
        if video
        else ("Voice call", "voice call", "Call", "Start voice call", "Phone call")
    )
    # Header call buttons (current chat)
    for lab in labels:
        for getter in (
            lambda lab=lab: page.get_by_role("button", name=re.compile(rf"^{re.escape(lab)}$", re.I)),
            lambda lab=lab: page.locator(f'button[aria-label="{lab}" i]'),
            lambda lab=lab: page.locator(f'[aria-label="{lab}" i]'),
            lambda lab=lab: page.locator(f'[title="{lab}" i]'),
        ):
            try:
                loc = getter()
                if loc.count():
                    loc.first.click(timeout=5000)
                    page.wait_for_timeout(800)
                    return
            except Exception:
                continue
    # Icon fallbacks
    icons = ("video-call", "videocall", "video") if video else ("voice-call", "call-menu", "phone", "audio-call", "call")
    for icon in icons:
        try:
            loc = page.locator(f'[data-testid*="{icon}" i], span[data-icon*="{icon}" i]').first
            if loc.count():
                loc.click(timeout=5000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue
    raise RuntimeError("Call button not found — select a chat first")


def _click_hangup(page) -> None:
    for lab in ("Leave call", "End call", "Hang up", "Reject", "Cancel"):
        try:
            loc = page.get_by_role("button", name=re.compile(lab, re.I))
            if loc.count():
                loc.first.click(timeout=5000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    for sel in (
        '[data-testid*="hang" i]',
        '[aria-label*="End call" i]',
        '[aria-label*="Leave call" i]',
        'span[data-icon="call-end"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=5000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    raise RuntimeError("Hang-up button not found")


def _focus_search(page) -> None:
    for sel in (
        'button[aria-label*="Search" i]',
        'div[title*="Search" i]',
        '[data-testid="chat-list-search"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=2500)
                page.wait_for_timeout(200)
                return
        except Exception:
            continue


def _search_box(page):
    selectors = [
        'div[contenteditable="true"][data-tab="3"]',
        '#side div[contenteditable="true"]',
        'div[title="Search input text box"]',
        'div[contenteditable="true"][role="textbox"]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    raise RuntimeError("WhatsApp search box not found — finish QR login first")


def _compose_box(page):
    selectors = [
        'footer div[contenteditable="true"]',
        'div[contenteditable="true"][data-tab="10"]',
        'div[contenteditable="true"][title="Type a message"]',
        'div[contenteditable="true"][data-tab="1"]',
        '#main footer div[contenteditable="true"]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    raise RuntimeError("Message box not found — select a chat first")


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bwhatsapp\b", lowered)
        or lowered in {"close whatsapp", "exit whatsapp", "stop whatsapp"}
    )


def _wants_call(lowered: str) -> bool:
    if re.search(r"\b(hang ?up|end call|leave call)\b", lowered):
        return False
    return bool(
        re.search(r"\b(video\s*call|voice\s*call|audio\s*call|phone\s*call)\b", lowered)
        or lowered in {"call", "call now", "make a call", "ring", "phone"}
    )


def _wants_hangup(lowered: str) -> bool:
    return bool(
        re.search(r"\b(hang ?up|end call|leave call|cut call|disconnect)\b", lowered)
        or lowered in {"hangup", "end call", "cut call"}
    )


_WORD_NUM = {
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
    "six": 6,
    "sixth": 6,
    "6th": 6,
    "seven": 7,
    "seventh": 7,
    "7th": 7,
    "eight": 8,
    "eighth": 8,
    "8th": 8,
    "nine": 9,
    "ninth": 9,
    "9th": 9,
    "ten": 10,
    "tenth": 10,
    "10th": 10,
}


def _parse_spoken_int(text: str) -> int | None:
    m = re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))
    for word, num in _WORD_NUM.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return num
    return None


def _select_index(lowered: str) -> int | None:
    # first/second person · number one · select number 1 · chat three
    if re.search(
        r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|"
        r"sixth|6th|seventh|7th|eighth|8th|ninth|9th|tenth|10th)\s+"
        r"(person|chat|contact)\b",
        lowered,
    ):
        return _parse_spoken_int(lowered)
    if re.search(
        r"\b(select|open|choose)\b.+\b(number|person|chat|contact)\b",
        lowered,
    ) or re.search(r"\b(number|person|chat|contact)\s*#?\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", lowered):
        return _parse_spoken_int(lowered)
    if re.match(
        r"^(chat|person|number)\s*#?\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)$",
        lowered,
    ):
        return _parse_spoken_int(lowered)
    # bare "select one" / "select first"
    m = re.match(
        r"^(select|open|choose)\s+(one|two|three|four|five|six|seven|eight|nine|ten|"
        r"first|second|third|fourth|fifth|\d+)(?:\s+(person|chat|contact))?$",
        lowered,
    )
    if m:
        return _parse_spoken_int(m.group(2))
    return None


def _select_name(text: str, lowered: str) -> str | None:
    patterns = [
        r"^(select|open chat|open|message to|chat with|message|msg)\s+(.+)$",
        r"^(go to chat|find)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, text, flags=re.I)
        if m:
            name = m.group(2).strip().strip("\"'")
            # avoid treating "select number 2 / number one" as a name
            if _select_index(lowered) or _select_index(name.lower()):
                return None
            if re.match(r"^(number|person|chat)\b", name.lower()):
                return None
            if name.lower() in {"whatsapp", "chat", "person", "call"}:
                return None
            return name
    return None


def _explicit_message(text: str, lowered: str) -> str | None:
    m = re.match(r"^(send|type|message|msg|tell them|say)\s+(.+)$", text, flags=re.I)
    if m:
        return m.group(2).strip()
    return None


def _set_intent(path: Path, expect: str, chat: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"expect": expect, "chat": chat}, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
