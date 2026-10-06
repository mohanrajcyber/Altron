from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from altron.adapters import browser_session

YOUTUBE_HOME = "https://www.youtube.com"
SEARCH_SELECTORS = [
    "input#search",
    "input[name='search_query']",
    "input[aria-label*='Search']",
]


def open_youtube(intent_path: Path, headless: bool = False) -> str:
    del headless
    try:
        browser_session.run(_open_on_page, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return (
            "YouTube is open and under ALTRON control.\n"
            "Say a search (e.g. tamil news), then say: play first video"
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not open YouTube under control: {exc}"


def search_youtube(query: str, intent_path: Path, headless: bool = False) -> str:
    del headless
    q = (query or "").strip()
    if not q:
        return "Tell me what to search on YouTube."
    cleaned = _clean_query(q)
    try:
        browser_session.run(_search_on_page, cleaned, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return (
            f"Searched YouTube for: {cleaned}\n"
            "Say: play first video · or another search · or: close youtube"
        )
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"YouTube search failed: {exc}"


def play_youtube_result(intent_path: Path, index: int = 1, headless: bool = False) -> str:
    del headless
    idx = max(1, min(int(index or 1), 10))
    try:
        title = browser_session.run(_play_result_on_page, idx, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        base = (
            f"Playing result #{idx}: {title or '(video)'}\n"
            "Controls: pause · next · volume up/down · mute · fullscreen · theater · like · subscribe · save song"
        )
        # Auto-show lyrics after play starts
        lyrics_block = _lyrics_text_for_title(title or "")
        if lyrics_block:
            return f"{base}\n\n{lyrics_block}"
        return f"{base}\n(No lyrics found automatically — say: show lyrics)"
    except ImportError:
        return "Playwright not installed. Run: pip install -e \".[browser]\""
    except Exception as exc:  # noqa: BLE001
        return f"Could not play YouTube result: {exc}"


def lyrics_youtube(intent_path: Path, headless: bool = False, translate_to: str = "") -> str:
    """Pull lyrics into ALTRON chat from current video title (+ captions if any)."""
    del headless
    try:
        info = browser_session.run(_current_video_info, reset_on_closed=True)
    except Exception as exc:  # noqa: BLE001
        return f"Need an open YouTube video first: {exc}"
    title = (info.get("title") or "").strip()
    if not title:
        return "No video title found — play a video first, then say: show lyrics"
    chunks: list[str] = [f"Now playing: {title}"]
    caps = (info.get("captions") or "").strip()
    if caps:
        chunks.append("On-screen captions (sample):\n" + caps[:1200])
    lyrics_block = _lyrics_text_for_title(title)
    if lyrics_block:
        text = lyrics_block
        if translate_to:
            translated = _translate_text(_strip_lyrics_header(text), translate_to)
            if translated:
                lang = "Tamil" if translate_to.startswith("ta") else "English"
                chunks.append(f"Lyrics ({lang}):\n{translated[:3500]}")
            else:
                chunks.append(text)
                chunks.append(f"(Translate to {translate_to} failed — showing original.)")
        else:
            chunks.append(text)
        _set_intent(intent_path, "youtube_control")
        return "\n\n".join(chunks)
    if caps:
        _set_intent(intent_path, "youtube_control")
        return "\n\n".join(chunks) + "\n\n(Full lyrics API miss — captions sample only.)"
    _set_intent(intent_path, "youtube_control")
    artist, song = _parse_artist_title(title)
    return (
        f"Now playing: {title}\n"
        f"Could not find full lyrics for “{artist} – {song}”. "
        "Try a lyrics video, or search: … lyrics"
    )


def pause_youtube(intent_path: Path) -> str:
    try:
        browser_session.run(_press_key, "k", reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return "Toggled pause/play on YouTube."
    except Exception as exc:  # noqa: BLE001
        return f"Pause failed: {exc}"


def next_youtube(intent_path: Path) -> str:
    try:
        browser_session.run(_press_key, "Shift+N", reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return "Skipped to next video (YouTube)."
    except Exception as exc:  # noqa: BLE001
        return f"Next video failed: {exc}"


def seek_youtube(
    intent_path: Path,
    *,
    absolute_sec: float | None = None,
    delta_sec: float | None = None,
) -> str:
    """Jump to a timestamp or skip forward/back by seconds."""
    try:
        if absolute_sec is not None:
            t = max(0.0, float(absolute_sec))
            browser_session.run(_seek_absolute, t, reset_on_closed=True)
            _set_intent(intent_path, "youtube_control")
            return f"Jumped to { _fmt_time(t) }."
        delta = float(delta_sec if delta_sec is not None else 10.0)
        browser_session.run(_seek_delta, delta, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        sign = "+" if delta >= 0 else ""
        return f"Seeked {sign}{int(delta)}s ({'forward' if delta >= 0 else 'back'})."
    except Exception as exc:  # noqa: BLE001
        return f"Seek failed: {exc}"


def nav_back_youtube(intent_path: Path) -> str:
    """Browser history back while staying in YouTube sticky mode."""
    try:
        browser_session.run(_nav_back, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return "Went back (YouTube page history)."
    except Exception as exc:  # noqa: BLE001
        return f"Go back failed: {exc}"


def volume_youtube(intent_path: Path, direction: str = "up", steps: int = 5) -> str:
    direction = (direction or "up").lower()
    steps = max(1, min(int(steps or 5), 20))
    try:
        if direction in {"mute", "unmute", "toggle"}:
            browser_session.run(_press_key, "m", reset_on_closed=True)
            _set_intent(intent_path, "youtube_control")
            return "Toggled mute on YouTube."
        key = "ArrowUp" if direction == "up" else "ArrowDown"
        browser_session.run(_press_keys, key, steps, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return f"Volume {'up' if direction == 'up' else 'down'} ×{steps}."
    except Exception as exc:  # noqa: BLE001
        return f"Volume control failed: {exc}"


def fullscreen_youtube(intent_path: Path) -> str:
    try:
        browser_session.run(_press_key, "f", reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return "Toggled fullscreen on YouTube."
    except Exception as exc:  # noqa: BLE001
        return f"Fullscreen failed: {exc}"


def theater_youtube(intent_path: Path) -> str:
    try:
        browser_session.run(_press_key, "t", reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return "Toggled theater mode on YouTube."
    except Exception as exc:  # noqa: BLE001
        return f"Theater mode failed: {exc}"


def like_youtube(intent_path: Path) -> str:
    try:
        msg = browser_session.run(_click_like, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return msg
    except Exception as exc:  # noqa: BLE001
        return f"Like failed: {exc} (YouTube login may be required in the controlled Chrome.)"


def subscribe_youtube(intent_path: Path) -> str:
    try:
        msg = browser_session.run(_click_subscribe, reset_on_closed=True)
        _set_intent(intent_path, "youtube_control")
        return msg
    except Exception as exc:  # noqa: BLE001
        return f"Subscribe failed: {exc} (YouTube login may be required in the controlled Chrome.)"


def save_song_memory(intent_path: Path, memory, vectors=None) -> str:
    try:
        info = browser_session.run(_current_video_info, reset_on_closed=True)
    except Exception as exc:  # noqa: BLE001
        return f"No video to save: {exc}"
    title = (info.get("title") or "").strip()
    url = (info.get("url") or "").strip()
    if not title:
        return "No song title found to save."
    payload = f"Liked/saved YouTube song: {title}" + (f" ({url})" if url else "")
    memory.write(payload, kind="user")
    if vectors is not None:
        try:
            vectors.add(payload, kind="user")
        except Exception:
            pass
    _set_intent(intent_path, "youtube_control")
    return f"Saved to ALTRON memory: {title}"


def close_youtube(intent_path: Path) -> str:
    clear_expect(intent_path)
    try:
        browser_session.close_session()
    except Exception as exc:  # noqa: BLE001
        return f"Cleared YouTube mode (browser close note: {exc})."
    return "Closed YouTube control."


def expecting_control(intent_path: Path) -> bool:
    data = _read_intent(intent_path)
    if data.get("expect") not in {"youtube_search", "youtube_control"}:
        return False
    if not browser_session.is_live():
        clear_expect(intent_path)
        return False
    return True


def expecting_search(intent_path: Path) -> bool:
    # Back-compat alias
    return expecting_control(intent_path)


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _open_on_page(page) -> None:
    page.goto(YOUTUBE_HOME, wait_until="domcontentloaded", timeout=45000)
    _dismiss_consent(page)


def _search_on_page(page, cleaned: str) -> None:
    if "youtube.com" not in (page.url or ""):
        page.goto(YOUTUBE_HOME, wait_until="domcontentloaded", timeout=45000)
    _dismiss_consent(page)
    box = None
    for sel in SEARCH_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                box = loc
                break
        except Exception:
            continue
    if box is None:
        page.goto(
            f"https://www.youtube.com/results?search_query={quote_plus(cleaned)}",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        page.wait_for_timeout(600)
        return
    box.click(timeout=8000)
    box.fill("")
    box.fill(cleaned)
    box.press("Enter")
    page.wait_for_timeout(900)


def _play_result_on_page(page, index: int) -> str:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("Open/search YouTube first.")
    _dismiss_consent(page)
    # Prefer normal video results, not Shorts shelf.
    selectors = [
        "ytd-video-renderer a#video-title",
        "ytd-video-renderer #video-title",
        "a#video-title",
    ]
    link = None
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() >= index:
                link = loc.nth(index - 1)
                break
        except Exception:
            continue
    if link is None:
        raise RuntimeError("No video results found — search first.")
    title = ""
    try:
        title = (link.inner_text(timeout=2000) or "").strip()[:120]
    except Exception:
        title = ""
    link.click(timeout=10000)
    page.wait_for_timeout(800)
    return title


def _current_video_info(page) -> dict:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    title = ""
    for sel in ("h1.ytd-watch-metadata yt-formatted-string", "h1.title", "#title h1"):
        try:
            loc = page.locator(sel).first
            if loc.count():
                title = (loc.inner_text(timeout=2000) or "").strip()
                if title:
                    break
        except Exception:
            continue
    if not title:
        try:
            title = (page.title() or "").replace(" - YouTube", "").strip()
        except Exception:
            title = ""
    # Try enable captions and sample visible caption text
    try:
        page.keyboard.press("c")
        page.wait_for_timeout(400)
    except Exception:
        pass
    captions = ""
    try:
        parts = page.locator(".ytp-caption-segment").all_inner_texts()
        captions = " ".join(p.strip() for p in parts if p.strip())[:1500]
    except Exception:
        captions = ""
    return {"title": title, "captions": captions, "url": page.url}


def _press_key(page, key: str) -> None:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    page.keyboard.press(key)
    page.wait_for_timeout(200)


def _press_keys(page, key: str, times: int) -> None:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    for _ in range(max(1, times)):
        page.keyboard.press(key)
        page.wait_for_timeout(60)


def _nav_back(page) -> None:
    page.go_back(wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(300)


def _seek_absolute(page, seconds: float) -> None:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    page.evaluate(
        """(sec) => {
          const v = document.querySelector('video');
          if (!v) throw new Error('no video element');
          v.currentTime = Math.min(Math.max(0, sec), v.duration || sec);
        }""",
        seconds,
    )
    page.wait_for_timeout(200)


def _seek_delta(page, delta: float) -> None:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    # Prefer HTML5 video for accuracy; fallback to YouTube hotkeys (l=+10, j=-10)
    try:
        page.evaluate(
            """(d) => {
              const v = document.querySelector('video');
              if (!v) throw new Error('no video');
              v.currentTime = Math.min(Math.max(0, (v.currentTime || 0) + d), v.duration || 1e9);
            }""",
            delta,
        )
        page.wait_for_timeout(150)
        return
    except Exception:
        pass
    steps = max(1, int(round(abs(delta) / 10.0)))
    key = "l" if delta >= 0 else "j"
    for _ in range(steps):
        page.keyboard.press(key)
        page.wait_for_timeout(80)


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _click_like(page) -> str:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    # Focus player area then try like button
    candidates = [
        "button[aria-label*='like this video' i]",
        "button[aria-label*='Like' i]",
        "#top-level-buttons-computed button",
        "like-button-view-model button",
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.count():
                btn.click(timeout=4000)
                page.wait_for_timeout(400)
                return "Liked the video (or toggled like). If nothing changed, log into YouTube in this Chrome window."
        except Exception:
            continue
    return "Could not find Like button — log into YouTube in the controlled Chrome, then try again."


def _click_subscribe(page) -> str:
    if "youtube.com" not in (page.url or ""):
        raise RuntimeError("YouTube is not open")
    candidates = [
        "button[aria-label*='Subscribe' i]",
        "#subscribe-button button",
        "ytd-subscribe-button-renderer button",
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.count():
                label = ""
                try:
                    label = (btn.get_attribute("aria-label") or btn.inner_text() or "").strip()
                except Exception:
                    label = ""
                btn.click(timeout=4000)
                page.wait_for_timeout(500)
                return f"Clicked Subscribe ({label or 'button'}). Login required if it did not stick."
        except Exception:
            continue
    return "Could not find Subscribe — log into YouTube in the controlled Chrome, then try again."


def _lyrics_text_for_title(title: str) -> str:
    artist, song = _parse_artist_title(title)
    api_text = _fetch_lyrics_api(artist, song)
    if not api_text:
        return ""
    return f"Lyrics — {artist} / {song}:\n{api_text[:3500]}"


def _strip_lyrics_header(block: str) -> str:
    lines = block.splitlines()
    if lines and lines[0].lower().startswith("lyrics"):
        return "\n".join(lines[1:]).strip()
    return block


def _translate_text(text: str, target: str) -> str:
    """Free MyMemory translate; target like ta|en or ta / en."""
    import httpx

    text = (text or "").strip()
    if not text:
        return ""
    target = (target or "ta").lower().strip()
    if target in {"tamil", "ta", "ta-in"}:
        pair = "en|ta"
    elif target in {"english", "en", "en-us", "en-gb"}:
        pair = "ta|en"
    else:
        pair = target if "|" in target else f"en|{target}"
    # MyMemory limits ~500 chars per request — chunk
    out: list[str] = []
    chunk_size = 450
    pieces = [text[i : i + chunk_size] for i in range(0, min(len(text), 3000), chunk_size)]
    for piece in pieces:
        try:
            r = httpx.get(
                "https://api.mymemory.translated.net/get",
                params={"q": piece, "langpair": pair},
                timeout=12.0,
                verify=False,
            )
            if r.status_code >= 400:
                continue
            data = r.json()
            translated = ((data.get("responseData") or {}).get("translatedText") or "").strip()
            if translated:
                out.append(translated)
        except Exception:
            continue
    return "\n".join(out).strip()


def _parse_artist_title(raw: str) -> tuple[str, str]:
    t = re.sub(
        r"\s*[\(\[][^\)\]]*(lyrics|official|video|audio|mv|hd|4k)[^\)\]]*[\)\]]",
        "",
        raw,
        flags=re.I,
    )
    t = re.sub(r"\s*\|.*$", "", t).strip()
    t = re.sub(r"\s*-\s*topic\s*$", "", t, flags=re.I).strip()
    if " - " in t:
        left, right = t.split(" - ", 1)
        return left.strip() or "Unknown", right.strip() or t
    if " by " in t.lower():
        m = re.split(r"\s+by\s+", t, maxsplit=1, flags=re.I)
        if len(m) == 2:
            return m[1].strip(), m[0].strip()
    return "Unknown", t


def _fetch_lyrics_api(artist: str, song: str) -> str:
    import httpx
    from urllib.parse import quote

    if not song or song.lower() in {"unknown", "youtube"}:
        return ""
    attempts = [(artist, song)]
    if artist.lower() != "unknown":
        attempts.append(("Unknown", song))
    clean_song = re.sub(r"\s*(ft\.|feat\.|featuring).*$", "", song, flags=re.I).strip()
    if clean_song and clean_song != song:
        attempts.append((artist, clean_song))

    # 1) lyrics.ovh (SSL verify off — some Windows Python installs lack CA bundle)
    for a, s in attempts:
        url = f"https://api.lyrics.ovh/v1/{quote(a)}/{quote(s)}"
        try:
            r = httpx.get(url, timeout=10.0, verify=False)
            if r.status_code < 400:
                lyrics = (r.json().get("lyrics") or "").strip()
                if lyrics:
                    return lyrics
        except Exception:
            continue

    # 2) LRCLIB search fallback
    q = f"{artist} {song}".strip()
    try:
        r = httpx.get(
            "https://lrclib.net/api/search",
            params={"q": q},
            timeout=10.0,
            verify=False,
        )
        if r.status_code < 400:
            rows = r.json() if isinstance(r.json(), list) else []
            for row in rows[:5]:
                plain = (row.get("plainLyrics") or row.get("syncedLyrics") or "").strip()
                if plain and len(plain) > 40:
                    return plain
    except Exception:
        pass
    return ""


def _clean_query(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"^(please\s+)?(search(\s+for)?|find|play|youtube(\s+la)?|on\s+youtube)\s*",
        "",
        t,
        flags=re.I,
    )
    # Keep "play first video" out of search cleaner path — handled separately.
    t = re.sub(r"\s*(on\s+youtube|youtube\s*laa?|nu\s*search)\s*$", "", t, flags=re.I)
    return t.strip() or text.strip()


def _dismiss_consent(page) -> None:
    for label in ("Accept all", "Accept", "I agree", "Reject all"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


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
