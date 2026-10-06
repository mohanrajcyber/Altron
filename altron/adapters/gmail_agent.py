from __future__ import annotations

"""Gmail sticky — compose / reply / send (mail.google.com)."""

import json
import re
from pathlib import Path

from altron.adapters import browser_session

GMAIL_URL = "https://mail.google.com"


def open_gmail(intent_path: Path) -> str:
    try:
        browser_session.run(_goto, GMAIL_URL, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control")
        return (
            "Gmail under ALTRON control (sign in if needed).\n"
            "Say: compose to name@email.com · subject Meeting · "
            "then speak the body · send · reply · close gmail"
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open Gmail: {exc}"


def act(user_text: str, intent_path: Path) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Gmail listening — compose to … · subject … · speak body · send · close gmail"
    lowered = text.lower().strip().rstrip(".!?")

    if _wants_close(lowered):
        return close_gmail(intent_path)
    if lowered in {"compose", "new mail", "new email", "write email"}:
        return compose(intent_path)
    m = re.match(r"^(compose to|email|mail to|new mail to|write to)\s+(.+)$", text, flags=re.I)
    if m:
        return compose(intent_path, to=m.group(2).strip())
    m = re.match(r"^to\s+(.+)$", text, flags=re.I)
    if m:
        return set_to(intent_path, m.group(1).strip())
    m = re.match(r"^subject\s+(.+)$", text, flags=re.I)
    if m:
        return set_subject(intent_path, m.group(1).strip())
    if lowered in {"send", "send it", "send email", "send mail"}:
        return send(intent_path)
    if lowered in {"reply", "reply all", "replyall"}:
        return reply(intent_path, all_="all" in lowered)
    if lowered in {"inbox", "go inbox", "open inbox"}:
        return _run(intent_path, _goto, GMAIL_URL, ok="Opened Inbox.")

    # sticky body text while composing
    data = _read_intent(intent_path)
    if data.get("composing"):
        return type_body(intent_path, text)
    return (
        "Gmail is listening. Try: compose to you@mail.com · subject Hello · "
        "then your message · send · reply · close gmail"
    )


def compose(intent_path: Path, to: str = "") -> str:
    try:
        browser_session.run(_click_compose, reset_on_closed=True)
        if to:
            browser_session.run(_fill_to, to, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=True)
        extra = f" To: {to}." if to else ""
        return f"Compose open.{extra} Say subject … then speak the body, then send."
    except Exception as exc:  # noqa: BLE001
        return f"Compose failed: {exc}"


def set_to(intent_path: Path, to: str) -> str:
    try:
        browser_session.run(_fill_to, to, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=True)
        return f"To set: {to}"
    except Exception as exc:  # noqa: BLE001
        return f"Could not set To: {exc}"


def set_subject(intent_path: Path, subject: str) -> str:
    try:
        browser_session.run(_fill_subject, subject, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=True)
        return f"Subject set: {subject}\nSpeak the email body now."
    except Exception as exc:  # noqa: BLE001
        return f"Could not set subject: {exc}"


def type_body(intent_path: Path, body: str) -> str:
    try:
        browser_session.run(_type_body, body, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=True)
        return f"Typed body ({len(body)} chars). Say more, or: send"
    except Exception as exc:  # noqa: BLE001
        return f"Body type failed: {exc}"


def send(intent_path: Path) -> str:
    try:
        browser_session.run(_click_send, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=False)
        return "Sent. Say compose … or close gmail"
    except Exception as exc:  # noqa: BLE001
        return f"Send failed: {exc}"


def reply(intent_path: Path, all_: bool = False) -> str:
    try:
        browser_session.run(_click_reply, all_, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control", composing=True)
        return "Reply open — speak your message, then send."
    except Exception as exc:  # noqa: BLE001
        return f"Reply failed: {exc}"


def close_gmail(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared Gmail mode ({exc})."
    return "Closed Gmail control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "gmail_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _run(intent_path: Path, fn, *args, ok: str = "Done.") -> str:
    try:
        browser_session.run(fn, *args, reset_on_closed=True)
        _set_intent(intent_path, "gmail_control")
        return ok
    except Exception as exc:  # noqa: BLE001
        return f"Gmail action failed: {exc}"


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)


def _click_compose(page) -> None:
    if "mail.google" not in (page.url or ""):
        page.goto(GMAIL_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
    for sel in (
        'div[role="button"][gh="cm"]',
        'div[aria-label="Compose"]',
        'div[aria-label*="Compose" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=8000)
                page.wait_for_timeout(700)
                return
        except Exception:
            continue
    raise RuntimeError("Compose button not found — finish Gmail login")


def _fill_to(page, to: str) -> None:
    for sel in (
        'textarea[name="to"]',
        'input[name="to"]',
        'div[aria-label*="To" i] input',
        'div[aria-label="To recipients"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=4000)
                page.keyboard.type(to, delay=25)
                page.keyboard.press("Tab")
                page.wait_for_timeout(300)
                return
        except Exception:
            continue
    page.keyboard.type(to, delay=25)
    page.keyboard.press("Tab")


def _fill_subject(page, subject: str) -> None:
    for sel in ('input[name="subjectbox"]', 'input[aria-label*="Subject" i]'):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=4000)
                loc.fill(subject)
                page.wait_for_timeout(200)
                return
        except Exception:
            continue
    raise RuntimeError("Subject box not found")


def _type_body(page, body: str) -> None:
    for sel in (
        'div[aria-label*="Message Body" i]',
        'div[role="textbox"][aria-label*="Body" i]',
        'div[contenteditable="true"][aria-label*="Message" i]',
        'div[contenteditable="true"][g_editable="true"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=5000)
                page.keyboard.type(body + " ", delay=15)
                page.wait_for_timeout(200)
                return
        except Exception:
            continue
    page.keyboard.type(body + " ", delay=15)


def _click_send(page) -> None:
    for sel in (
        'div[role="button"][aria-label*="Send" i]',
        'div[data-tooltip*="Send" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=5000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(800)


def _click_reply(page, all_: bool) -> None:
    label = "Reply all" if all_ else "Reply"
    try:
        loc = page.get_by_role("button", name=re.compile(label, re.I))
        if loc.count():
            loc.first.click(timeout=5000)
            page.wait_for_timeout(600)
            return
    except Exception:
        pass
    raise RuntimeError(f"{label} button not found — open an email first")


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bgmail\b", lowered)
        or lowered in {"close gmail", "exit gmail", "stop gmail"}
    )


def _set_intent(path: Path, expect: str, composing: bool | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"expect": expect}
    if composing is not None:
        data["composing"] = composing
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
