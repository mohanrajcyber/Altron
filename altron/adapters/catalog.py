from __future__ import annotations

# OpenAI-compatible tool schemas. Harvested shape from MCP servers-main tools.

SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": "List files in the ALTRON workspace (allowlisted).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path, default ."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "Read a text file in the ALTRON workspace. Secrets are blocked.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": "Write a text file under data/sandbox only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a public https page as text. Not localhost.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_use",
            "description": (
                "One-shot scrape/click script. Prefer browser_open + browser_act for ongoing AGI control."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "action": {"type": "string", "description": "read|click|type|click_text"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "steps": {
                        "type": "string",
                        "description": "Pipe steps or JSON list, e.g. click \"More information\" | read",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Open controlled Chrome (stays open). Then use browser_act for voice/type commands.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_act",
            "description": "Do a natural-language browser action while control mode is on (search, go to, click, type, read, scroll, back).",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close controlled browser session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_open",
            "description": "Open YouTube in a controlled Chrome window that stays open, then ask what to search.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_search",
            "description": "Type a query into the YouTube search bar and search. Window stays open.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_play",
            "description": "Click/play the Nth YouTube search result (default first video). Not a text search.",
            "parameters": {
                "type": "object",
                "properties": {"index": {"type": "integer", "description": "1=first result"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_lyrics",
            "description": "Show lyrics for the current YouTube video. Optional translate_to: ta or en.",
            "parameters": {
                "type": "object",
                "properties": {"translate_to": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_pause",
            "description": "Pause or resume the current YouTube video.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_next",
            "description": "Skip to the next YouTube video.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_seek",
            "description": "Seek YouTube: absolute_sec (e.g. 140 for 2:20) or delta_sec (+10 / -10).",
            "parameters": {
                "type": "object",
                "properties": {
                    "absolute_sec": {"type": "number"},
                    "delta_sec": {"type": "number"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_nav_back",
            "description": "Go back in YouTube browser history (not video rewind).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_volume",
            "description": "YouTube volume up/down or mute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "description": "up|down|mute"},
                    "steps": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_fullscreen",
            "description": "Toggle YouTube fullscreen.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_theater",
            "description": "Toggle YouTube theater mode.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_like",
            "description": "Like the current YouTube video (needs login in controlled Chrome).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_subscribe",
            "description": "Subscribe to the current channel (needs login in controlled Chrome).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_save",
            "description": "Save the current YouTube song title into ALTRON memory.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_close",
            "description": "Close the controlled YouTube/Chrome session and stop treating chat as searches.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_see",
            "description": "Capture the Windows screen and describe what is visible (vision).",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_whatsapp",
            "description": "Open WhatsApp Web under ALTRON control (select contact, voice-send messages).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_act",
            "description": "WhatsApp action while control is on: select name, select number N, or send spoken text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whatsapp_close",
            "description": "Close WhatsApp control session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_open",
            "description": "Open ALTRON IDE sticky control (Monaco explorer/editor/agent — not code-server).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_act",
            "description": "IDE action: list, open path, edit, write, run python, status.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_close",
            "description": "Close ALTRON IDE control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flows_open",
            "description": "Open the ALTRON FLOWS visual workflow UI.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flows_act",
            "description": "Control ALTRON FLOWS from chat: create/modify/run/list workflows, show last run, stop flow. Uses Trusted Roots and safety confirmation for risky runs.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "User request about workflows"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_open",
            "description": "Open Spotify Web or app under ALTRON sticky control.",
            "parameters": {
                "type": "object",
                "properties": {"app": {"type": "boolean"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_act",
            "description": "Spotify action: search, play, pause, next, volume.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_close",
            "description": "Close Spotify control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_open",
            "description": "Open Gmail under sticky control (compose/reply/send).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_act",
            "description": "Gmail action while sticky.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_close",
            "description": "Close Gmail control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maps_open",
            "description": "Open Google Maps sticky control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maps_act",
            "description": "Maps action: search, directions, start.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maps_close",
            "description": "Close Maps control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explorer_open",
            "description": "Open File Explorer sticky control (list/select/open/delete).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explorer_act",
            "description": "Explorer sticky action.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explorer_close",
            "description": "Close Explorer control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notepad_open",
            "description": "Open Notepad sticky control (speak=type, save as).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notepad_act",
            "description": "Notepad sticky action.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notepad_close",
            "description": "Close Notepad control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notepad_write",
            "description": "Open Notepad with the given text (one-shot).",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safety_confirm",
            "description": "Execute a previously gated risky action after user confirmation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safety_cancel",
            "description": "Cancel a pending risky action.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_chat",
            "description": "Clear the current chat thread in the UI.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Read-only git status for the ALTRON repo.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Read-only git log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_run",
            "description": "Run short Python in E2B cloud if configured, else local sandbox.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_write",
            "description": "Write a Python/text file into data/sandbox (OpenHands-shaped workspace).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "goal_run",
            "description": (
                "Run ALTRON's autonomous goal engine for the supported goal shape only: "
                "write a small Python program, run it, and verify its output (exit code + "
                "expected text). Not for arbitrary or multi-capability tasks yet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "e.g. 'create a python program that prints Hello ALTRON, run it and verify'",
                    },
                    "max_attempts": {"type": "integer", "description": "Bounded retry limit, default 3"},
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_enqueue",
            "description": "Queue a long job and optionally POST to live n8n webhook.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "payload": {"type": "string"}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_list",
            "description": "List queued jobs.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_add",
            "description": "Add a knowledge-graph triple (Graphiti-shaped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "relation", "object"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_search",
            "description": "Search the local knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comfy_generate",
            "description": "Talk to local ComfyUI if running on :8188.",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
            },
        },
    },
]


def openai_tools() -> list[dict]:
    return SCHEMAS
