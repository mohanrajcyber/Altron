from __future__ import annotations

"""Single-thread Playwright owner — sync API cannot hop FastAPI worker threads."""

import queue
import threading
from collections.abc import Callable
from typing import Any

_JOBS: queue.Queue = queue.Queue()
_WORKER: threading.Thread | None = None
_READY = threading.Event()
_LOCK = threading.Lock()


def run(fn: Callable[..., Any], *args: Any, timeout: float = 90.0, reset_on_closed: bool = False, **kwargs: Any) -> Any:
    """Run fn(page, *args, **kwargs) on the Playwright owner thread."""
    _ensure_worker()
    try:
        return _submit(fn, args, kwargs, timeout=timeout)
    except Exception as exc:
        if reset_on_closed and _should_reset_on_closed_error(exc):
            close_session()
            _ensure_worker()
            return _submit(fn, args, kwargs, timeout=timeout)
        raise


def _should_reset_on_closed_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "closed" not in msg:
        return False
    return any(token in msg for token in ("page", "browser", "target", "context"))


def _submit(fn: Callable[..., Any], args: tuple, kwargs: dict, timeout: float) -> Any:
    done = threading.Event()
    box: dict[str, Any] = {}

    def job(page: Any) -> None:
        box["value"] = fn(page, *args, **kwargs)

    _JOBS.put((job, done, box))
    if not done.wait(timeout=timeout):
        raise TimeoutError("Browser action timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def close_session() -> str:
    done = threading.Event()
    box: dict[str, Any] = {}

    def job(_page: Any) -> None:
        box["value"] = "closed"
        raise _Shutdown()

    _ensure_worker()
    _JOBS.put((job, done, box))
    done.wait(timeout=15)
    return "Closed ALTRON browser session."


def is_live() -> bool:
    """True when the Playwright owner thread still has a usable browser page."""
    if _WORKER is None or not _WORKER.is_alive():
        return False
    try:
        value = run(lambda page: not page.is_closed(), timeout=5.0, reset_on_closed=True)
        return bool(value)
    except Exception:
        return False


def _ensure_worker() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _READY.clear()
        _WORKER = threading.Thread(target=_worker_main, name="altron-browser", daemon=True)
        _WORKER.start()
        if not _READY.wait(timeout=30):
            raise RuntimeError("Browser worker failed to start")


def _worker_main() -> None:
    global _WORKER
    page = None
    context = None
    browser = None
    pw = None
    try:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = _launch(pw, headless=False)
        context = _new_context(browser)
        page = context.new_page()
        _maximize(page)
        _READY.set()
        while True:
            item = _JOBS.get()
            if item is None:
                break
            job, done, box = item
            try:
                if page is None or page.is_closed():
                    if browser is None or not browser.is_connected():
                        browser = _launch(pw, headless=False)
                        context = _new_context(browser)
                    elif context is None:
                        context = _new_context(browser)
                    page = context.new_page()
                    _maximize(page)
                job(page)
            except _Shutdown:
                box["value"] = "closed"
                done.set()
                break
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                if not done.is_set():
                    done.set()
    except Exception as exc:  # noqa: BLE001
        _READY.set()
        while True:
            try:
                item = _JOBS.get_nowait()
            except queue.Empty:
                break
            if item is None:
                break
            _job, done, box = item
            box["error"] = exc
            done.set()
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass
        with _LOCK:
            _WORKER = None


def _launch(pw: Any, headless: bool = False) -> Any:
    args = [
        "--start-maximized",
        "--window-position=0,0",
        "--disable-blink-features=AutomationControlled",
    ]
    for channel in ("chrome", "msedge"):
        try:
            return pw.chromium.launch(channel=channel, headless=headless, args=args)
        except Exception:
            continue
    return pw.chromium.launch(headless=headless, args=args)


def _new_context(browser: Any) -> Any:
    # no_viewport=True → page fills the real maximized Chrome window (fixes white side gap).
    return browser.new_context(no_viewport=True)


def _maximize(page: Any) -> None:
    try:
        page.evaluate(
            """() => {
              try { window.moveTo(0, 0); } catch (e) {}
              try { window.resizeTo(screen.availWidth, screen.availHeight); } catch (e) {}
            }"""
        )
    except Exception:
        pass


class _Shutdown(Exception):
    pass
