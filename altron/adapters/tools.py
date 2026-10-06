from __future__ import annotations

import json
import re

from altron.adapters import (
    browser_agent,
    browser_control,
    comfy,
    computer,
    desktop_skills,
    e2b_cloud,
    explorer_agent,
    gmail_agent,
    graphiti_local,
    ide_agent,
    jobs,
    maps_agent,
    mcp_fetch,
    mcp_fs,
    mcp_git,
    n8n_live,
    notepad_agent,
    safety,
    spotify_agent,
    vision,
    whatsapp_agent,
    youtube_agent,
)
from altron.adapters.identity_store import IdentityStore, classify_block
from altron.adapters.memory import JsonlMemory
from altron.adapters.vector_memory import VectorMemory
from altron.settings import Settings

TOOL_NAMES = [
    "memory_write",
    "open_tab",
    "open_url",
    "open_notepad",
    "open_ida",
    "open_calculator",
    "open_chrome",
    "open_edge",
    "open_explorer",
    "shutdown_request",
    "shutdown_confirm",
    "fs_list",
    "fs_read",
    "fs_write",
    "web_fetch",
    "browser_use",
    "browser_open",
    "browser_act",
    "browser_close",
    "youtube_open",
    "youtube_search",
    "youtube_play",
    "youtube_lyrics",
    "youtube_pause",
    "youtube_next",
    "youtube_seek",
    "youtube_nav_back",
    "youtube_volume",
    "youtube_fullscreen",
    "youtube_theater",
    "youtube_like",
    "youtube_subscribe",
    "youtube_save",
    "youtube_close",
    "screen_see",
    "open_whatsapp",
    "whatsapp_act",
    "whatsapp_close",
    "spotify_open",
    "spotify_act",
    "spotify_close",
    "gmail_open",
    "gmail_act",
    "gmail_close",
    "maps_open",
    "maps_act",
    "maps_close",
    "explorer_open",
    "explorer_act",
    "explorer_close",
    "notepad_open",
    "notepad_act",
    "notepad_close",
    "ide_open",
    "ide_act",
    "ide_close",
    "flows_open",
    "flows_act",
    "notepad_write",
    "safety_confirm",
    "safety_cancel",
    "clear_chat",
    "git_status",
    "git_log",
    "code_run",
    "code_write",
    "goal_run",
    "job_enqueue",
    "job_list",
    "graph_add",
    "graph_search",
    "comfy_generate",
]

_TOOL_LINE = re.compile(r"TOOL\s+(\{.*\})", re.S)


def pick_tool(user_text: str) -> str | None:
    picked = pick_action(user_text)
    return picked[0] if picked else None


def pick_action(user_text: str, settings: Settings | None = None) -> tuple[str, dict] | None:
    text = user_text.strip()
    lowered = text.lower()
    settings = settings or Settings()
    if _wants_clear_chat(text):
        return "clear_chat", {}
    # Safety confirm / cancel
    if safety.is_cancel(text) and safety.pending(settings.safety_path):
        return "safety_cancel", {}
    confirmed = safety.matches_confirm(text, settings.safety_path)
    if confirmed:
        return "safety_confirm", {"kind": confirmed.get("kind"), "payload": confirmed.get("payload") or {}}
    if lowered.startswith("remember ") or "remember that" in lowered or lowered.startswith("save this"):
        return "memory_write", {}
    if "confirm shutdown" in lowered:
        return "shutdown_confirm", {}
    if any(
        mark in lowered
        for mark in (
            "shutdown",
            "shut down",
            "switch off",
            "switchoff",
            "turn off my pc",
            "turn off pc",
            "turn off the pc",
            "power off",
        )
    ):
        return "shutdown_request", {}
    # Autonomous Goal Engine — narrow, deterministic recognition of the one
    # supported goal shape (Phase 2/3): write + run + verify a Python program.
    if _wants_goal_run(text):
        return "goal_run", {"goal": text}
    # Vision
    if _wants_screen_see(text):
        return "screen_see", {"prompt": text}
    # Desktop skills
    if _wants_whatsapp_close(text):
        return "whatsapp_close", {}
    if _wants_whatsapp(text):
        return "open_whatsapp", {}
    if _wants_ide_close(text):
        return "ide_close", {}
    if _wants_ide(text):
        return "ide_open", {}
    if _wants_flows_act(text):
        return "flows_act", {"text": text}
    if _wants_flows(text):
        return "flows_open", {}
    if _wants_spotify_close(text):
        return "spotify_close", {}
    if _wants_spotify(text):
        return "spotify_open", {"app": _spotify_app_mode(text)}
    if "spotify" in lowered and "altron" in lowered:
        return "spotify_open", {"app": _spotify_app_mode(text)}
    if _wants_gmail_close(text):
        return "gmail_close", {}
    if _wants_gmail(text):
        return "gmail_open", {}
    if _wants_maps_close(text):
        return "maps_close", {}
    if _wants_maps(text):
        return "maps_open", {}
    if _wants_explorer_close(text):
        return "explorer_close", {}
    if _wants_explorer(text):
        return "explorer_open", {"path": _explorer_path(text)}
    if "open notepad" in lowered:
        return "open_notepad", {}
    if "open calculator" in lowered or "open calc" in lowered:
        return "open_calculator", {}
    if "open ida" in lowered or "launch ida" in lowered or "open ida pro" in lowered or "open ida free" in lowered:
        return "open_ida", {"app": "ida"}
    if "open chrome" in lowered:
        return "open_chrome", {}
    if "open edge" in lowered:
        return "open_edge", {}
    if _wants_notepad_close(text):
        return "notepad_close", {}
    if _wants_notepad_write(text):
        return "notepad_write", {"text": text}
    if _wants_notepad(text):
        return "notepad_open", {}
    if "new tab" in lowered or "open tab" in lowered or "open browser" in lowered:
        return "browser_open", {}
    if _wants_browser_close(text):
        return "browser_close", {}
    # Controlled YouTube (stays open + can type search). Beat plain open_url.
    if _wants_youtube_close(text):
        return "youtube_close", {}
    if _wants_youtube_save(text):
        return "youtube_save", {}
    if _wants_youtube_like(text):
        return "youtube_like", {}
    if _wants_youtube_subscribe(text):
        return "youtube_subscribe", {}
    if _wants_youtube_volume(text):
        return "youtube_volume", _youtube_volume_args(text)
    if _wants_youtube_fullscreen(text):
        return "youtube_fullscreen", {}
    if _wants_youtube_theater(text):
        return "youtube_theater", {}
    if _wants_youtube_lyrics(text):
        return "youtube_lyrics", {"translate_to": _lyrics_translate_target(text)}
    if _wants_youtube_pause(text):
        return "youtube_pause", {}
    if _wants_youtube_next(text):
        return "youtube_next", {}
    if _wants_youtube_seek(text):
        return "youtube_seek", _youtube_seek_args(text)
    if _wants_youtube_play(text):
        return "youtube_play", {"index": _youtube_play_index(text)}
    if _wants_youtube_control(text):
        return "youtube_open", {}
    if "youtube search" in lowered or lowered.startswith("search youtube") or lowered.startswith("yt search"):
        q = re.sub(r"^(youtube search|search youtube( for)?|yt search)\s*", "", text, flags=re.I).strip()
        return "youtube_search", {"query": q or text}
    # "search tamil news" while controlling YouTube
    if youtube_agent.expecting_control(settings.intent_path) and re.match(
        r"^(search|find)\s+", lowered
    ):
        q = re.sub(r"^(search|find)\s+(for\s+)?", "", text, flags=re.I).strip()
        if q and not _wants_youtube_play(q):
            return "youtube_search", {"query": q}
    # Persistent OS open (stays open). Must beat browser_use — Playwright closes after a few seconds.
    if _wants_persistent_open(text):
        return "open_url", {}
    if lowered.startswith("browse ") or "browser use" in lowered or (
        "click on" in lowered and computer.extract_url(text)
    ):
        url = computer.extract_url(text) or ""
        action = "read"
        click_text = ""
        steps_raw = ""
        if "|" in text:
            left, _, rest = text.partition("|")
            url = computer.extract_url(left) or url
            steps_raw = rest
        if "click" in lowered and not steps_raw:
            action = "click_text"
            m = re.search(r"click(?:\s+on)?\s+[\"']?([^\"'|]+)[\"']?", text, flags=re.I)
            click_text = (m.group(1).strip() if m else "")[:80]
        return "browser_use", {"url": url, "action": action, "text": click_text, "steps": steps_raw}
    if lowered.startswith("open ") and ("http" in lowered or ".com" in lowered or "google" in lowered):
        return "open_url", {}
    if lowered.startswith("fetch ") or "fetch url" in lowered or "read this page" in lowered or "read this url" in lowered:
        url = computer.extract_url(text) or ""
        return "web_fetch", {"url": url}
    if computer.extract_url(text) and any(mark in lowered for mark in ("what's on", "whats on", "summarize", "scrape")):
        return "web_fetch", {"url": computer.extract_url(text) or ""}
    if "git status" in lowered:
        return "git_status", {"path": "."}
    if "git log" in lowered:
        return "git_log", {"path": "."}
    if lowered.startswith("run python") or lowered.startswith("execute python") or lowered.startswith("run this code"):
        code = re.sub(r"^(please\s+)?(run python|execute python|run this code)[:\s]*", "", text, flags=re.I)
        return "code_run", {"code": code.strip(" `")}
    if "list files" in lowered or lowered in {"ls", "dir"} or lowered.startswith("list files"):
        return "fs_list", {"path": "."}
    if lowered.startswith("read file ") or lowered.startswith("show file "):
        path = re.sub(r"^(read file|show file)\s+", "", text, flags=re.I).strip().strip("\"'")
        return "fs_read", {"path": path}
    if lowered.startswith("queue job") or lowered.startswith("enqueue"):
        title = re.sub(r"^(queue job|enqueue)[:\s]*", "", text, flags=re.I).strip()
        return "job_enqueue", {"title": title or "job"}
    if "list jobs" in lowered or "job queue" in lowered:
        return "job_list", {}
    if lowered.startswith("graph add ") or lowered.startswith("relate "):
        body = re.sub(r"^(graph add|relate)\s+", "", text, flags=re.I)
        m = re.match(r"(.+?)\s+(is|as|related_to|runs_on|-|=)\s+(.+)$", body, flags=re.I)
        if m:
            return "graph_add", {"subject": m.group(1).strip(), "relation": m.group(2).strip(), "object": m.group(3).strip()}
        bits = body.split()
        if len(bits) >= 3:
            return "graph_add", {"subject": bits[0], "relation": bits[1], "object": " ".join(bits[2:])}
    if "graph search" in lowered or lowered.startswith("search graph"):
        q = re.sub(r"^(graph search|search graph)\s*", "", text, flags=re.I).strip()
        return "graph_search", {"query": q}
    if lowered.startswith("comfy ") or "comfyui" in lowered or lowered.startswith("generate image"):
        prompt = re.sub(r"^(comfy(ui)?|generate image)\s*", "", text, flags=re.I).strip()
        return "comfy_generate", {"prompt": prompt or text}
    # Sticky WhatsApp (voice → select chat → send) — before YouTube/browser
    if whatsapp_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            whatsapp_agent.clear_expect(settings.intent_path)
        else:
            return "whatsapp_act", {"text": text}
    if ide_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            ide_agent.clear_expect(settings.intent_path)
        else:
            return "ide_act", {"text": text}
    if spotify_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            spotify_agent.clear_expect(settings.intent_path)
        else:
            return "spotify_act", {"text": text}
    if gmail_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            gmail_agent.clear_expect(settings.intent_path)
        else:
            return "gmail_act", {"text": text}
    if maps_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            maps_agent.clear_expect(settings.intent_path)
        else:
            return "maps_act", {"text": text}
    if explorer_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            explorer_agent.clear_expect(settings.intent_path)
        else:
            return "explorer_act", {"text": text}
    if notepad_agent.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            notepad_agent.clear_expect(settings.intent_path)
        else:
            return "notepad_act", {"text": text}
    # Sticky YouTube control (priority over general browser)
    if youtube_agent.expecting_control(settings.intent_path):
        if _wants_youtube_save(text):
            return "youtube_save", {}
        if _wants_youtube_like(text):
            return "youtube_like", {}
        if _wants_youtube_subscribe(text):
            return "youtube_subscribe", {}
        if _wants_youtube_volume(text):
            return "youtube_volume", _youtube_volume_args(text)
        if _wants_youtube_fullscreen(text):
            return "youtube_fullscreen", {}
        if _wants_youtube_theater(text):
            return "youtube_theater", {}
        if _wants_youtube_lyrics(text):
            return "youtube_lyrics", {"translate_to": _lyrics_translate_target(text)}
        if _wants_youtube_pause(text):
            return "youtube_pause", {}
        if _wants_youtube_next(text):
            return "youtube_next", {}
        if _wants_youtube_nav_back(text):
            return "youtube_nav_back", {}
        if _wants_youtube_seek(text):
            return "youtube_seek", _youtube_seek_args(text)
        if _wants_youtube_play(text):
            return "youtube_play", {"index": _youtube_play_index(text)}
        if _looks_like_youtube_query(text):
            return "youtube_search", {"query": text}
        youtube_agent.clear_expect(settings.intent_path)
    # Sticky general browser control — voice/type anything
    if browser_control.expecting_control(settings.intent_path):
        if _is_altron_meta_command(text):
            browser_control.clear_expect(settings.intent_path)
        else:
            return "browser_act", {"text": text}
    return None


def extract_memory_payload(user_text: str) -> str:
    cleaned = re.sub(r"^(please\s+)?(remember( that)?|save this[:\s]*)\s*", "", user_text, flags=re.I)
    return cleaned.strip() or user_text.strip()


def _wants_browser_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\b(browser|chrome|tab)\b", lowered)
        or lowered in {"close browser", "close chrome", "exit browser", "stop browser"}
    )


def _is_hard_chat_escape(text: str) -> bool:
    return _is_altron_meta_command(text)


def normalize_voice_command(text: str, sticky_mode: bool = False) -> str:
    """Return the command payload after the wake word, or empty if it was not directed at ALTRON."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower().strip().rstrip(".!?")
    if sticky_mode:
        return cleaned.strip()
    if re.search(r"\b(?:hey|hi|hello|ok|okay|vanakkam)\s*(?:altron|ultron)\b", lowered):
        return re.sub(
            r"^(?:hey|hi|hello|ok|okay|vanakkam)\s*(?:altron|ultron)\s*[:,-]?\s*",
            "",
            cleaned,
            flags=re.I,
        ).strip()
    if re.match(r"^(?:altron|ultron)\b", lowered):
        return re.sub(r"^(?:altron|ultron)\s*[:,-]?\s*", "", cleaned, flags=re.I).strip()
    if re.match(r"^(?:who are you|what is your name|clear chat|clear the chat|stop listening|mic off|mike off)\b", lowered):
        return cleaned.strip()
    return ""


def _is_altron_meta_command(text: str) -> bool:
    """Leave sticky control only when talking to ALTRON itself — not chat greetings."""
    lowered = (text or "").lower().strip().rstrip(".!?")
    if re.search(r"\b(altron|ultron)\b", lowered) and re.match(
        r"^(hi|hello|hey|ok|okay|vanakkam)\b", lowered
    ):
        return True
    if re.match(r"^(who are you|what is your name|clear chat|clear the chat|stop listening|mic off|mike off)\b", lowered):
        return True
    if "shutdown" in lowered:
        return True
    return False


def _clear_rival_sticky(settings: Settings) -> None:
    """Only one sticky mode at a time."""
    path = settings.intent_path
    try:
        whatsapp_agent.clear_expect(path)
        ide_agent.clear_expect(path)
        youtube_agent.clear_expect(path)
        browser_control.clear_expect(path)
        spotify_agent.clear_expect(path)
        gmail_agent.clear_expect(path)
        maps_agent.clear_expect(path)
        explorer_agent.clear_expect(path)
        notepad_agent.clear_expect(path)
    except Exception:
        pass


def _wants_youtube_lyrics(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(lyrics|lyric)\b", lowered)
        or lowered in {"show lyrics", "get lyrics", "song lyrics", "lyrics please"}
        or "translate lyrics" in lowered
        or "tamil lyrics" in lowered
        or "english lyrics" in lowered
    )


def _lyrics_translate_target(text: str) -> str:
    lowered = (text or "").lower()
    if "tamil" in lowered or re.search(r"\bto ta\b", lowered) or "தமிழ்" in text:
        return "ta"
    if "english" in lowered or re.search(r"\bto en\b", lowered):
        return "en"
    if "translate" in lowered and "english" not in lowered:
        return "ta"  # default translate → Tamil for this user
    return ""


def _wants_youtube_pause(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return lowered in {"pause", "pause video", "pause youtube", "resume", "play pause", "unpause"}


def _wants_youtube_next(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(next video|skip video|next song)\b", lowered)
        or lowered in {"next", "next youtube", "skip"}
    )


def _wants_youtube_nav_back(text: str) -> bool:
    """Browser history back — not video rewind (use 'rewind' / 'back 10')."""
    lowered = (text or "").lower().strip().rstrip(".!?")
    return lowered in {"go back", "previous page", "browser back", "page back"}


def _wants_youtube_seek(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_youtube_nav_back(text):
        return False
    if re.search(
        r"\b(forward|foward|backward|backwards|rewind|seek|jump|skip ahead|go to|goto)\b",
        lowered,
    ):
        return True
    # "back 10" / "back 20" (not "go back" — excluded above)
    if re.search(r"\bback\b", lowered) and not lowered.startswith("go "):
        return True
    if re.search(r"\b\d+[.:]\d+\b", lowered) and re.search(r"\b(to|at|time|minute|sec)\b", lowered):
        return True
    if lowered in {
        "forward",
        "foward",
        "backward",
        "backwards",
        "rewind",
        "back",
        "back 10",
        "forward 10",
        "backward 10",
    }:
        return True
    return False


def _youtube_seek_args(text: str) -> dict:
    lowered = (text or "").lower().strip()
    # Absolute: 2:20 / 2.20 / 1:05:30 (jump TO that time — not relative)
    m = re.search(r"\b(\d{1,2})[:.](\d{1,2})(?:[:.](\d{1,2}))?\b", lowered)
    if m and re.search(r"\b(forward|foward|go to|goto|seek|jump|at|to)\b", lowered):
        if m.group(3) is not None:
            h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return {"absolute_sec": h * 3600 + mi * 60 + s}
        a, b = int(m.group(1)), int(m.group(2))
        return {"absolute_sec": a * 60 + b}
    # Relative: forward 10 / backward 10 / rewind 30
    m2 = re.search(r"\b(\d+)\s*(s|sec|secs|second|seconds)?\b", lowered)
    if m2 and re.search(r"\b(forward|foward|skip|ahead)\b", lowered):
        return {"delta_sec": float(m2.group(1))}
    if m2 and re.search(r"\b(back|backward|backwards|rewind|behind)\b", lowered):
        return {"delta_sec": -float(m2.group(1))}
    if re.search(r"\b(back|backward|backwards|rewind)\b", lowered):
        return {"delta_sec": -10.0}
    # bare forward
    return {"delta_sec": 10.0}


def _wants_youtube_volume(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(volume|mute|unmute|sound)\b", lowered)
        or lowered in {"volume up", "volume down", "louder", "quieter", "soft"}
    )


def _youtube_volume_args(text: str) -> dict:
    lowered = (text or "").lower()
    if "mute" in lowered or "unmute" in lowered:
        return {"direction": "mute"}
    if any(k in lowered for k in ("down", "quieter", "soft", "decrease", "low")):
        return {"direction": "down", "steps": 8}
    return {"direction": "up", "steps": 8}


def _wants_youtube_fullscreen(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(re.search(r"\b(full ?screen|fullscreen)\b", lowered))


def _wants_youtube_theater(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(re.search(r"\b(theater|theatre|cinema mode)\b", lowered))


def _wants_youtube_like(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if re.search(r"\b(i like|we like|they like|likely)\b", lowered):
        return False
    return lowered in {
        "like",
        "like video",
        "like this",
        "like the song",
        "like the video",
        "thumbs up",
        "like it",
    } or bool(re.match(r"^(please\s+)?(like|thumbs up)\b", lowered))


def _wants_youtube_subscribe(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return lowered in {"subscribe", "subscribe channel", "subscribe please"} or bool(
        re.match(r"^(please\s+)?subscribe\b", lowered)
    )


def _wants_youtube_save(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(save song|save this song|remember (this )?song|save (the )?video|save to memory)\b", lowered)
        or lowered in {"save song", "remember song"}
    )


def _wants_clear_chat(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.match(r"^(clear|clear chat|clear the chat|clear conversation|reset chat|wipe chat)$", lowered)
        or "clear the chat" in lowered
        or "clear chat" in lowered
        or "chat clear" in lowered
    )


def _wants_screen_see(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(
            r"\b(what('?s| is) on (my )?screen|see (my )?screen|screen see|look at (my )?screen|capture screen|screenshot)\b",
            lowered,
        )
        or lowered in {"see screen", "screen", "what's on screen", "whats on screen"}
    )


_GOAL_RUN_CREATE_RE = re.compile(r"\b(create|write|build|make)\b", re.I)
_GOAL_RUN_VERIFY_RE = re.compile(r"\b(run|test|verify)\b", re.I)


def _wants_goal_run(text: str) -> bool:
    """Narrow, deterministic match for the goal shapes the Autonomous Goal
    Engine supports: a Python program/project that gets written, run, and
    verified (sandbox_python/ide_workspace — Phase 2-4), or a Flow that gets
    run/created (flow capability — Phase 5, see autonomous_goal.is_flow_goal).
    Does NOT make every Chat request autonomous — see Phase 3/4/5 scope."""
    from altron.adapters import autonomous_goal

    lowered = (text or "").lower()
    if autonomous_goal.is_flow_goal(text):
        return True
    if "python" not in lowered:
        return False
    if not any(w in lowered for w in ("program", "script", "project", "application", "app")):
        return False
    if not _GOAL_RUN_CREATE_RE.search(lowered):
        return False
    if not _GOAL_RUN_VERIFY_RE.search(lowered):
        return False
    return True



def _wants_whatsapp(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_whatsapp_close(text):
        return False
    return bool(re.search(r"\b(whatsapp|whats app)\b", lowered) and re.search(r"\b(open|launch|start)\b", lowered)) or lowered in {
        "whatsapp",
        "open whatsapp",
        "whatsapp web",
    }


def _wants_whatsapp_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bwhatsapp\b", lowered)
        or lowered in {"close whatsapp", "exit whatsapp", "stop whatsapp"}
    )


def _wants_ide(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_ide_close(text):
        return False
    return bool(
        re.search(r"\b(open|launch|start)\b.+\b(ide|code[- ]?server|altron ide)\b", lowered)
        or lowered in {
            "ide",
            "open ide",
            "altron ide",
            "open altron ide",
            "open code server",
            "code server",
            "start ide",
        }
    )


def _wants_ide_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit|stop)\b.+\b(ide|code[- ]?server)\b", lowered)
        or lowered in {"close ide", "exit ide", "stop ide", "close code server"}
    )


def _wants_flows_act(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_flows(text) and not re.search(
        r"\b(create|make|build|run|list|scan|organize|classify|modify|change|add|remove|stop|last run|why did)\b",
        lowered,
    ):
        return False
    return bool(
        re.search(
            r"\b(list flows|show flows|create (a )?(flow|workflow)|make (a )?(flow|workflow)|"
            r"build (a )?(flow|workflow)|run (the )?(flow|workflow)|stop (the )?(flow|workflow)|"
            r"open flow |show last run|last execution|organize .{0,40}pdf|scan .{0,40}(downloads|desktop|pdf)|"
            r"classify .{0,40}(pdf|invoice)|only process|move them to|add (an )?ai agent|"
            r"change the (folder|filter)|why did .{0,40}fail|altron,.+(scan|organize|pdf))\b",
            lowered,
        )
        or (
            re.search(r"\b(flow|workflow|downloads|pdf|invoice)\b", lowered)
            and re.search(r"\b(create|scan|organize|run|classify|list|filter|move)\b", lowered)
        )
    )


def _wants_flows(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(open|launch|start)\b.+\b(flows?|workflow|n8n|automation)\b", lowered)
        or lowered
        in {
            "flows",
            "open flows",
            "altron flows",
            "open altron flows",
            "open workflow",
            "open workflows",
            "open automation",
            "open n8n",
            "workflow",
            "automation",
        }
    )


def _wants_spotify(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_spotify_close(text):
        return False
    if lowered in {
        "spotify",
        "open spotify",
        "spotify web",
        "spotify app",
        "open spotify app",
        "spotify tab",
        "open spotify tab",
        "open spotify website",
    }:
        return True
    return bool(
        re.search(r"\bspotify\b", lowered)
        and (
            re.search(r"\b(open|launch|start|play|show|go to|tab|website|web)\b", lowered)
            or re.search(r"^spotify\b", lowered)
            or re.search(r"\bspotify\b.*\b(tab|website|web)\b", lowered)
        )
    )


def _spotify_app_mode(text: str) -> bool:
    lowered = (text or "").lower()
    return "app" in lowered and "web" not in lowered


def _wants_spotify_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bspotify\b", lowered)
        or lowered in {"close spotify", "exit spotify", "stop spotify"}
    )


def _wants_gmail(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_gmail_close(text):
        return False
    return bool(
        re.search(r"\b(gmail|outlook mail)\b", lowered) and re.search(r"\b(open|launch|start)\b", lowered)
    ) or lowered in {"gmail", "open gmail", "mail", "open mail"}


def _wants_gmail_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bgmail\b", lowered)
        or lowered in {"close gmail", "exit gmail", "stop gmail"}
    )


def _wants_maps(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_maps_close(text):
        return False
    return bool(
        re.search(r"\b(google\s*)?maps?\b", lowered) and re.search(r"\b(open|launch|start)\b", lowered)
    ) or lowered in {"maps", "open maps", "google maps", "open google maps", "map"}


def _wants_maps_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bmaps?\b", lowered)
        or lowered in {"close maps", "close map", "exit maps", "stop maps"}
    )


def _wants_explorer(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_explorer_close(text):
        return False
    return bool(
        "open explorer" in lowered
        or "open folder" in lowered
        or "open file explorer" in lowered
        or lowered in {"explorer", "file explorer", "open downloads"}
    )


def _wants_explorer_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\b(explorer|folder)\b", lowered)
        or lowered in {"close explorer", "exit explorer", "stop explorer"}
    )


def _wants_notepad(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if _wants_notepad_close(text) or _wants_notepad_write(text):
        return False
    return "open notepad" in lowered or lowered in {"notepad", "open note"}


def _wants_ida(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if not lowered:
        return False
    return bool(re.search(r"\b(ida|ida pro|ida free|ida64)\b", lowered) and re.search(r"\b(open|launch|start)\b", lowered)) or lowered in {
        "ida",
        "open ida",
        "ida pro",
        "open ida pro",
        "ida free",
        "open ida free",
        "launch ida",
    }


def _wants_notepad_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bnotepad\b", lowered)
        or lowered in {"close notepad", "exit notepad", "stop notepad"}
    )


def _wants_notepad_write(text: str) -> bool:
    lowered = (text or "").lower().strip()
    return bool(re.match(r"^(notepad write|write in notepad|type in notepad)\b", lowered) or "notepad write" in lowered)


def _explorer_path(text: str) -> str:
    lowered = (text or "").lower().strip()
    if re.match(r"^open\s+downloads?$", lowered):
        return "Downloads"
    return (
        re.sub(
            r"^(open\s+folder|open\s+explorer|open\s+file\s+explorer|explorer)\s*",
            "",
            text,
            flags=re.I,
        )
        .strip()
        .strip("\"'")
    )


def _wants_youtube_play(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if not lowered:
        return False
    if re.search(
        r"\b(play|open|click|start)\b.+\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|\d+(st|nd|rd|th)?)\b",
        lowered,
    ):
        return True
    if re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\b.+\b(video|result|one|song)\b", lowered):
        return True
    if lowered in {
        "play first",
        "play it",
        "play that",
        "play video",
        "first video",
        "the first video",
        "open first video",
        "click first",
        "play first video",
        "play second video",
        "play third video",
        "second video",
        "third video",
        "the second video",
        "the third video",
    }:
        return True
    return False


def _youtube_play_index(text: str) -> int:
    lowered = (text or "").lower()
    words = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5,
    }
    for word, idx in words.items():
        if re.search(rf"\b{word}\b", lowered):
            return idx
    if re.search(r"\b(two)\b", lowered):
        return 2
    if re.search(r"\b(three)\b", lowered):
        return 3
    m = re.search(r"\b(\d+)(st|nd|rd|th)?\b", lowered)
    if m:
        return max(1, min(int(m.group(1)), 10))
    return 1


def _wants_youtube_close(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!?")
    if not lowered:
        return False
    if re.search(r"\b(close|exit|quit|stop|kill)\b.+\b(youtube|yt)\b", lowered):
        return True
    if re.search(r"\b(youtube|yt)\b.+\b(close|exit|quit|stop)\b", lowered):
        return True
    if lowered in {"close youtube", "close the youtube", "youtube close", "close yt", "exit youtube"}:
        return True
    return False


def _wants_youtube_control(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if "?" in text:
        return False
    if lowered.startswith(("why", "what", "how", "when", "who", "do not", "don't", "dont")):
        return False
    if lowered.startswith("browse ") or "|" in text:
        return False
    if _wants_youtube_close(text):
        return False
    if re.search(r"\bopen\b.+\byoutube\b", lowered) or re.search(r"\byoutube\b.+\bopen\b", lowered):
        return True
    if lowered in {"youtube", "open youtube", "youtube open", "yt", "open yt"}:
        return True
    if "youtube" in lowered and any(k in lowered for k in ("poova", "thorakku", "thorandu", "launch")):
        return True
    return False


def _looks_like_youtube_query(text: str) -> bool:
    """Only treat as a YouTube search when it looks like a title/song — not chat/play."""
    raw = (text or "").strip()
    lowered = raw.lower().strip().rstrip(".!?")
    if len(lowered) < 2 or len(lowered) > 120:
        return False
    if "?" in raw:
        return False
    if _wants_youtube_play(text) or _wants_youtube_close(text) or _wants_clear_chat(text):
        return False
    if _wants_youtube_lyrics(text) or _wants_youtube_pause(text) or _wants_youtube_next(text):
        return False
    if _wants_youtube_seek(text) or _wants_youtube_nav_back(text):
        return False
    if (
        _wants_youtube_volume(text)
        or _wants_youtube_fullscreen(text)
        or _wants_youtube_theater(text)
        or _wants_youtube_like(text)
        or _wants_youtube_subscribe(text)
        or _wants_youtube_save(text)
    ):
        return False
    if re.match(r"^(hi|hello|hey|yo|vanakkam|namaste)\b", lowered):
        return False
    if re.search(r"\b(altron|ultron|assistant)\b", lowered) and not re.search(
        r"\b(song|music|video|trailer|live|news)\b", lowered
    ):
        return False
    if re.match(r"^(stop|cancel|never ?mind|do not|don't|dont|no|nah)\b", lowered):
        return False
    if re.match(r"^(why|what|who|how|when|where|which|can you|could you|please tell)\b", lowered):
        return False
    if any(
        p in lowered
        for p in (
            "who are you",
            "what is your name",
            "your name",
            "remember",
            "list files",
            "shutdown",
            "enqueue",
            "run python",
            "browse ",
            "fetch ",
            "graph ",
            "open notepad",
            "open chrome",
            "clear chat",
        )
    ):
        return False
    if lowered.startswith("open ") and "youtube" not in lowered:
        return False
    if re.search(r"\b(search|song|songs|music|video|videos|trailer|movie|album|news)\b", lowered):
        # "the first video" already blocked by play detector
        return True
    if re.fullmatch(r"[\w\s\-'+&.]+", lowered, flags=re.UNICODE) and not re.search(
        r"\b(you|your|me|my|i|we|am|is|are|the youtube)\b", lowered
    ):
        if lowered in {"ok", "okay", "thanks", "thank you", "bye", "good", "yes", "yep"}:
            return False
        return True
    return False


def _wants_persistent_open(text: str) -> bool:
    """True when the user wants a normal browser tab that stays open (not Playwright scrape)."""
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if "youtube" in lowered or lowered in {"yt", "open yt"}:
        return False  # handled by youtube_open
    if lowered.startswith("browse ") or "browser use" in lowered or "|" in text:
        return False
    if any(k in lowered for k in ("click ", "click on", "type into", "scrape", "summarize page", "what's on")):
        return False
    if computer.extract_url(text) and any(
        k in lowered for k in ("open ", "open", "launch", "poova", "poitu", "thorakku", "thorandu")
    ):
        return True
    if re.search(r"\bopen\b.+\b(google|github|wikipedia)\b", lowered):
        return True
    if re.search(r"\bgoogle\b.+\bopen\b", lowered):
        return True
    if lowered in {"google", "open google"}:
        return True
    if lowered.startswith("open ") and computer.extract_url(text):
        return True
    return False


def parse_tool_directive(text: str) -> dict | None:
    match = _TOOL_LINE.search(text or "")
    if not match:
        fence = re.search(r"```tool\s*(\{.*?\})\s*```", text or "", re.S)
        if not fence:
            return None
        raw = fence.group(1)
    else:
        raw = match.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    name = str(data.get("name") or "")
    if name not in TOOL_NAMES:
        return None
    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    return {"name": name, "arguments": args}


def run_tool(
    name: str,
    user_text: str,
    memory: JsonlMemory,
    identity: IdentityStore | None = None,
    args: dict | None = None,
    settings: Settings | None = None,
    vectors: VectorMemory | None = None,
) -> str:
    args = args or {}
    settings = settings or Settings()
    ctx = _ctx(settings)
    graph = graphiti_local.KnowledgeGraph(ctx["graph"])
    if name == "memory_write":
        payload = extract_memory_payload(user_text)
        memory.write(payload, kind="user")
        if vectors is not None:
            vectors.add(payload, kind="user")
        block = classify_block(payload)
        stored_core = False
        if identity is not None:
            stored_core = identity.add_fact(payload, block=block)
        extra = f" Also wrote core/{block}." if stored_core else ""
        backend = vectors.backend() if vectors is not None else "jsonl"
        return f"Stored in archival memory ({backend}): {payload}{extra}"
    if name == "open_tab":
        return browser_control.open_browser(settings.intent_path)
    if name == "browser_open":
        url = str(args.get("url") or computer.extract_url(user_text) or "")
        return browser_control.open_browser(settings.intent_path, url=url)
    if name == "browser_act":
        return browser_control.act(str(args.get("text") or user_text), settings.intent_path)
    if name == "browser_close":
        return browser_control.close_browser(settings.intent_path)
    if name == "open_url":
        # Prefer controlled browser when user wants lasting AGI control
        url = computer.extract_url(user_text) or str(args.get("url") or "") or computer.DEFAULT_TAB
        if browser_control.expecting_control(settings.intent_path) or "control" in user_text.lower():
            return browser_control.open_browser(settings.intent_path, url=url)
        return computer.open_url(url)
    if name == "open_notepad":
        _clear_rival_sticky(settings)
        return notepad_agent.open_notepad(settings.intent_path, settings.altron_data_dir)
    if name == "notepad_open":
        _clear_rival_sticky(settings)
        return notepad_agent.open_notepad(settings.intent_path, settings.altron_data_dir)
    if name == "notepad_act":
        return notepad_agent.act(
            str(args.get("text") or user_text), settings.intent_path, settings.altron_data_dir
        )
    if name == "notepad_close":
        return notepad_agent.close_notepad(settings.intent_path)
    if name == "notepad_write":
        return desktop_skills.notepad_write(str(args.get("text") or user_text))
    if name == "open_calculator":
        return desktop_skills.calc_open()
    if name == "open_chrome":
        return computer.open_app("chrome")
    if name == "open_ida":
        return computer.open_ida(str(args.get("app") or user_text or "ida"))
    if name == "open_edge":
        return computer.open_app("edge")
    if name == "open_explorer":
        _clear_rival_sticky(settings)
        return explorer_agent.open_explorer(settings.intent_path, str(args.get("path") or ""))
    if name == "explorer_open":
        _clear_rival_sticky(settings)
        return explorer_agent.open_explorer(settings.intent_path, str(args.get("path") or ""))
    if name == "explorer_act":
        return explorer_agent.act(str(args.get("text") or user_text), settings.intent_path, settings)
    if name == "explorer_close":
        return explorer_agent.close_explorer(settings.intent_path)
    if name == "open_whatsapp":
        _clear_rival_sticky(settings)
        return whatsapp_agent.open_whatsapp(settings.intent_path)
    if name == "whatsapp_act":
        return whatsapp_agent.act(str(args.get("text") or user_text), settings.intent_path)
    if name == "whatsapp_close":
        return whatsapp_agent.close_whatsapp(settings.intent_path)
    if name == "ide_open":
        _clear_rival_sticky(settings)
        return ide_agent.open_ide(settings.intent_path, settings)
    if name == "ide_act":
        return ide_agent.act(str(args.get("text") or user_text), settings.intent_path, settings)
    if name == "ide_close":
        return ide_agent.close_ide(settings.intent_path, settings)
    if name == "flows_open":
        from altron.adapters import flows_engine

        return flows_engine.open_flows_ui(settings)
    if name == "flows_act":
        from altron.adapters import flows_agi

        _clear_rival_sticky(settings)
        return flows_agi.handle(settings, str(args.get("text") or user_text), args)
    if name == "spotify_open":
        _clear_rival_sticky(settings)
        if args.get("app"):
            return spotify_agent.open_spotify_app(settings.intent_path)
        return spotify_agent.open_spotify(settings.intent_path)
    if name == "spotify_act":
        return spotify_agent.act(str(args.get("text") or user_text), settings.intent_path)
    if name == "spotify_close":
        return spotify_agent.close_spotify(settings.intent_path)
    if name == "gmail_open":
        _clear_rival_sticky(settings)
        return gmail_agent.open_gmail(settings.intent_path)
    if name == "gmail_act":
        return gmail_agent.act(str(args.get("text") or user_text), settings.intent_path)
    if name == "gmail_close":
        return gmail_agent.close_gmail(settings.intent_path)
    if name == "maps_open":
        _clear_rival_sticky(settings)
        return maps_agent.open_maps(settings.intent_path)
    if name == "maps_act":
        return maps_agent.act(str(args.get("text") or user_text), settings.intent_path)
    if name == "maps_close":
        return maps_agent.close_maps(settings.intent_path)
    if name == "screen_see":
        return vision.see_screen(settings, prompt=str(args.get("prompt") or user_text))
    if name == "safety_cancel":
        safety.clear(settings.safety_path)
        return "Cancelled. No risky action will run."
    if name == "safety_confirm":
        kind = str(args.get("kind") or "")
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        safety.clear(settings.safety_path)
        if kind == "shutdown":
            return computer.shutdown_request(confirmed=True)
        if kind == "fs_delete":
            return explorer_agent.execute_delete(str(payload.get("path") or ""))
        if kind == "flow_run":
            from altron.adapters import flows_agi

            return flows_agi.execute_confirmed_run(settings, str(payload.get("flow_id") or ""))
        return f"Confirmed {kind}."
    if name == "shutdown_request":
        return safety.request(
            settings.safety_path,
            "shutdown",
            {},
            "Shut down this Windows PC in 30 seconds.",
        )
    if name == "shutdown_confirm":
        return computer.shutdown_request(confirmed=True)
    if name == "fs_list":
        return mcp_fs.fs_list(str(args.get("path") or "."), ctx["roots"], ctx["base"])
    if name == "fs_read":
        path = str(args.get("path") or "")
        if not path:
            return "Need a path to read."
        return mcp_fs.fs_read(path, ctx["roots"], ctx["base"])
    if name in {"fs_write", "code_write"}:
        return mcp_fs.fs_write(str(args.get("path") or ""), str(args.get("content") or ""), ctx["roots"], ctx["sandbox"])
    if name == "web_fetch":
        url = str(args.get("url") or computer.extract_url(user_text) or "")
        return mcp_fetch.web_fetch(url)
    if name == "browser_use":
        url = str(args.get("url") or computer.extract_url(user_text) or "")
        allow = settings.browser_allowlist or None
        steps = browser_agent.parse_steps(args.get("steps"))
        action = str(args.get("action") or "read")
        # LLM often picks browser_use for "open youtube" — that Playwright window closes after the tool ends.
        if _wants_youtube_control(user_text):
            return youtube_agent.open_youtube(settings.intent_path, headless=bool(settings.altron_browser_headless))
        if _wants_persistent_open(user_text) or action.lower() in {"open", "launch"}:
            target = url or computer.extract_url(user_text) or computer.DEFAULT_TAB
            return computer.open_url(target)
        return browser_agent.browse(
            url,
            action=action,
            selector=str(args.get("selector") or ""),
            text=str(args.get("text") or ""),
            steps=steps or None,
            headless=bool(settings.altron_browser_headless),
            allowlist=allow,
        )
    if name == "youtube_open":
        return youtube_agent.open_youtube(settings.intent_path, headless=bool(settings.altron_browser_headless))
    if name == "youtube_search":
        q = str(args.get("query") or user_text or "")
        return youtube_agent.search_youtube(q, settings.intent_path, headless=bool(settings.altron_browser_headless))
    if name == "youtube_play":
        return youtube_agent.play_youtube_result(
            settings.intent_path,
            index=int(args.get("index") or 1),
            headless=bool(settings.altron_browser_headless),
        )
    if name == "youtube_lyrics":
        return youtube_agent.lyrics_youtube(
            settings.intent_path,
            translate_to=str(args.get("translate_to") or ""),
        )
    if name == "youtube_pause":
        return youtube_agent.pause_youtube(settings.intent_path)
    if name == "youtube_next":
        return youtube_agent.next_youtube(settings.intent_path)
    if name == "youtube_seek":
        abs_sec = args.get("absolute_sec")
        delta = args.get("delta_sec")
        return youtube_agent.seek_youtube(
            settings.intent_path,
            absolute_sec=float(abs_sec) if abs_sec is not None else None,
            delta_sec=float(delta) if delta is not None else None,
        )
    if name == "youtube_nav_back":
        return youtube_agent.nav_back_youtube(settings.intent_path)
    if name == "youtube_volume":
        return youtube_agent.volume_youtube(
            settings.intent_path,
            direction=str(args.get("direction") or "up"),
            steps=int(args.get("steps") or 5),
        )
    if name == "youtube_fullscreen":
        return youtube_agent.fullscreen_youtube(settings.intent_path)
    if name == "youtube_theater":
        return youtube_agent.theater_youtube(settings.intent_path)
    if name == "youtube_like":
        return youtube_agent.like_youtube(settings.intent_path)
    if name == "youtube_subscribe":
        return youtube_agent.subscribe_youtube(settings.intent_path)
    if name == "youtube_save":
        return youtube_agent.save_song_memory(settings.intent_path, memory, vectors=vectors)
    if name == "youtube_close":
        return youtube_agent.close_youtube(settings.intent_path)
    if name == "clear_chat":
        return "Chat cleared. (UI clears this thread instantly.)"
    if name == "git_status":
        return mcp_git.git_status(str(args.get("path") or "."), ctx["roots"], ctx["base"])
    if name == "git_log":
        return mcp_git.git_log(str(args.get("path") or "."), ctx["roots"], ctx["base"], count=int(args.get("count") or 8))
    if name == "code_run":
        return e2b_cloud.run_python(
            str(args.get("code") or user_text),
            ctx["sandbox"],
            e2b_api_key=settings.e2b_api_key,
        )
    if name == "goal_run":
        from altron.adapters import autonomous_goal

        goal_text = str(args.get("goal") or user_text)
        max_attempts = int(args.get("max_attempts") or 3)
        state = autonomous_goal.run_goal(settings, goal_text, max_attempts=max_attempts)
        return _format_goal_result(state)
    if name == "job_enqueue":
        title = str(args.get("title") or user_text)
        return n8n_live.enqueue(
            ctx["jobs"],
            title,
            str(args.get("payload") or ""),
            webhook_url=settings.n8n_webhook_url,
        )
    if name == "job_list":
        return jobs.format_recent(ctx["jobs"])
    if name == "graph_add":
        return graph.add(str(args.get("subject") or ""), str(args.get("relation") or ""), str(args.get("object") or ""))
    if name == "graph_search":
        return graph.search(str(args.get("query") or user_text))
    if name == "comfy_generate":
        return comfy.generate(str(args.get("prompt") or user_text), base_url=settings.comfyui_url)
    return f"Unknown tool: {name}"


def _format_goal_result(state: dict) -> str:
    """Render the Autonomous Goal Engine's GoalState honestly — never turn a
    FAILED/CANCELLED status into a fake success message."""
    lines = [
        f"Goal: {state.get('goal')}",
        f"Capability: {state.get('capability') or 'sandbox_python'}",
        f"Status: {state.get('status')}",
        f"Attempts: {state.get('attempt')}/{state.get('max_attempts')}",
    ]
    if state.get("flow_id"):
        lines.append(f"Flow: {state.get('flow_id')} (run {state.get('flow_run_id') or 'n/a'})")
    verification = state.get("verification") or {}
    if verification:
        detail = verification.get("detail") or f"{sum(1 for c in verification.get('checks') or [] if c.get('ok'))}/{len(verification.get('checks') or []) or 1} checks passed"
        lines.append(f"Verification: {'PASS' if verification.get('ok') else 'FAIL'} — {detail}")
    errors = state.get("errors") or []
    if errors:
        lines.append(f"Errors encountered: {len(errors)}")
    lines.append(f"Result: {state.get('result')}")
    return "\n".join(lines)


def _ctx(settings: Settings | None) -> dict:
    settings = settings or Settings()
    base = settings.altron_workspace.resolve()
    data = settings.altron_data_dir.resolve()
    return {
        "roots": [base],
        "base": base,
        "sandbox": data / "sandbox",
        "jobs": data / "jobs.jsonl",
        "graph": data / "graph.json",
    }
