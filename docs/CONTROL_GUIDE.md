# ALTRON — Control & Commands Guide

One place for all sticky control modes and useful voice/type commands.

**UI:** http://127.0.0.1:8088/  
**Run:** `python -m altron serve` (prefer this over an old EXE)

---

## How sticky control works

1. Open a mode: `open ide` · `open youtube` · `open browser` · `open whatsapp` · `open spotify` · `open gmail` · `open maps` · `open explorer` · `open notepad`
2. ALTRON stays in that mode — your next lines are actions, not normal chat
3. Close when done: `close ide` · `close youtube` · …

**Priority when more than one could apply:** WhatsApp → **IDE** → Spotify → Gmail → Maps → Explorer → Notepad → YouTube → Browser → normal chat.

**Voice tips**
- Mic on · say **hey ALTRON** before a request (or **hey Alron** if speech recognition spells the name that way); if spoken alone, ALTRON waits 8 seconds for the request · or hold **Space** (push-to-talk)
- Chat mic capture uses the browser's built-in speech-recognition service; it does not use the ALTRON `/v1` API key or require LiveKit credentials. A browser speech network error gets two retries, then a clear error; click Mic to retry or type the command.
- Spoken numbers work: `one` = `1`, `first` = `1`, `two` = `2`, …

## ALTRON FORGE

- Open `http://127.0.0.1:8088/forge` or choose **Forge** in Chat.
- Chat/Voice build requests such as `create a Python port scanner with a clean UI` route to the same Forge flow.
- Each build uses the existing IDE agent and creates a new folder under `forge_projects/`; existing project folders are not overwritten.
- **Plan only** runs the IDE agent in Plan mode and writes no project files.
- Generated files are verified on disk and Python syntax is parsed. Generated code and tests are not executed automatically.
- Port-scanner requests are scoped to localhost by the generation instruction. Inspect generated source before running it.
- After a build, `explain what you created` in Chat/Voice uses the current files from that Forge project as ALTRON IDE agent context.

---

## ALTRON IDE (v0.8)

| Command | Action |
|---------|--------|
| `open ide` | Opens **ALTRON IDE** in a **new browser tab** (`/ide`) + sticky control |
| `list` | List workspace files |
| `open PATH` / `read PATH` | Open file |
| `edit PATH ::: old >>> new` | Surgical replace |
| `write name.txt ::: content` | Write file in workspace |
| `run python …` / `run file x.py` | Run Python (timeout) |
| `status` | IDE sticky + workspace status |
| `close ide` | Leave IDE sticky mode |

**UI:** http://127.0.0.1:8088/ide (new browser tab from `open ide` or Face **IDE** button)  
**Engine:** ALTRON Monaco + terminal + Git + Agent — **not** VS Code / Copilot.  
**Agent AI (free AGI):** one ask → diagnose → tools/write → verify (`/api/ide/agent`).  
Streaming replies · Diff View/Apply/Reject · Undo always visible · autosave · split editor · drag-drop move · HTML preview auto-reload · xterm · git Init CTA + branches.  
**Modes:** Plan (steps only) · Edit (writes) · Debug (fail→fix) · Run (execute, no writes).  
**Path discipline:** `create folder hh` → `hh/` only (never random `sites/demo`).  
**Search:** activity Search / ripgrep · **Problems** live on edit · **Hover/Go-to** on Python.  
**Layout:** side + agent column widths persist · multi-root via Settings extra root.  
**Self-check:** Problems panel / `/api/ide/diagnose` · `/api/ide/diagnostics` · `/api/ide/hover` · `/api/ide/symbol`  
**Shortcuts:** Ctrl+P · Ctrl+Shift+P · Ctrl+S · Ctrl+` · Ctrl+\\ split

## ALTRON Flows (separate UI — like IDE)
**URL:** `http://127.0.0.1:8088/flows` · Face button **Flows** · chat `open flows`  
Inspired by `n8n refer git` (n8n / Activepieces / Windmill / Composio) — **native ALTRON product**, not embedded n8n.  
Trusted PC roots · node canvas · Run log · `/api/flows/*`

---

## YouTube

### Start / stop
| Command | Action |
|---------|--------|
| `open youtube` / `youtube` / `yt` | Open YouTube under ALTRON control |
| `close youtube` / `close yt` | Leave YouTube mode |

### Search & play
| Command | Action |
|---------|--------|
| *any song/title* (after open) | Search YouTube |
| `first video` / `play 1` / `play first` | Play 1st result |
| `second video` / `play 2` / `play second` | Play 2nd result |
| `third video` / `play 3` | Play 3rd |

### Playback
| Command | Action |
|---------|--------|
| `pause` / `resume` | Pause or resume |
| `next` / `next video` / `skip` | Next video |
| `forward` | **+10 seconds** |
| `forward 10` / `forward 30` | Jump ahead N seconds |
| `forward 2:20` / `forward 2.20` / `go to 2:20` | Jump **to** that time |
| `backward` / `back` / `rewind` | **−10 seconds** |
| `backward 10` / `back 20` | Jump back N seconds |
| `go back` | Page history back (not rewind) |

### Volume & view
| Command | Action |
|---------|--------|
| `volume up` / `louder` | Louder |
| `volume down` / `quieter` / `soft` | Quieter |
| `mute` / `unmute` | Toggle mute |
| `fullscreen` | Toggle fullscreen |
| `theater` / `theatre` | Theater mode |

### Social / memory
| Command | Action |
|---------|--------|
| `like` / `like video` | Like |
| `subscribe` | Subscribe |
| `lyrics` / `show lyrics` | Lyrics (optional: translate) |
| `save song` / `remember song` | Save current song to memory |

---

## Browser

### Start / stop
| Command | Action |
|---------|--------|
| `open browser` | Controlled Chrome (maximized) |
| `close browser` / `close chrome` | Leave browser mode |

### Search & links
| Command | Action |
|---------|--------|
| `search …` / `google …` | Google search |
| `open first link` / `first link` / `first result` | Open 1st result |
| `open link 2` / `open second link` / `click second result` | Open Nth result |
| *bare words* (while sticky) | Treated as a Google search |

### Navigate
| Command | Action |
|---------|--------|
| `go to wikipedia.org` / `open google` | Open URL / shortcut |
| `back` / `go back` | History back |
| `forward` / `go forward` | History forward |
| `scroll down` / `scroll up` | Scroll |
| `read page` / `what's on the page` | Read page text |

### Page actions
| Command | Action |
|---------|--------|
| `click Images` / `click …` | Click link/button by name |
| `type hello` / `type …` | Type into a field + Enter |

**Shortcuts:** `google` · `gmail` · `youtube` · `news` · `wikipedia` · `github`

---

## WhatsApp

### Start / stop
| Command | Action |
|---------|--------|
| `open whatsapp` | WhatsApp Web (scan QR if needed) |
| `close whatsapp` | Leave WhatsApp mode |

### Select chat
| Command | Action |
|---------|--------|
| `select Amma` / `select Name` | Search & open that contact |
| `select number 1` / `select number one` | Chat #1 in the list |
| `first person` / `second person` | Chat by position |
| `select 2` / `chat 3` | Same idea |

### Message & call
| Command | Action |
|---------|--------|
| *anything after a chat is selected* | **Types and sends** as a message |
| `send vanakkam` / `type hello` | Explicit send |
| `call` | Voice call (does **not** type “call”) |
| `video call` | Video call |
| `hang up` / `end call` | End call |

---

## Desktop & vision

| Command | Action |
|---------|--------|
| `see screen` / `what's on my screen` | Capture + describe |
| `open calculator` | Calculator |
| `open chrome` / `open edge` | Normal OS browser (not sticky AGI) |

---

## Spotify / Music

| Command | Action |
|---------|--------|
| `open spotify` | Spotify **Web** under control (login once) |
| `open spotify app` | Desktop Spotify + media keys |
| `search …` / song name | Search |
| `play` / `pause` | Play / pause |
| `next` / `previous` | Skip tracks |
| `volume up` / `volume down` / `mute` | Volume |
| `close spotify` | Leave mode |

---

## File Explorer

| Command | Action |
|---------|--------|
| `open explorer` / `open folder Downloads` | Sticky Explorer (lists files) |
| `select 1` / `select number one` | Select item |
| `open` | Open selected file/folder |
| `delete` | Ask confirm → then `CONFIRM FS_DELETE` |
| `list` | Refresh list |
| `close explorer` | Leave mode |

---

## Notepad

| Command | Action |
|---------|--------|
| `open notepad` | Sticky note (speak = type) |
| *any text* | Append to the note |
| `save as shopping list` | Save under `Documents/ALTRON/` |
| `clear note` | Empty draft |
| `close notepad` | Leave mode |

---

## Gmail

| Command | Action |
|---------|--------|
| `open gmail` | Gmail Web sticky (sign in if needed) |
| `compose to you@mail.com` | New mail + To |
| `subject Hello` | Set subject |
| *body text* | Type message body |
| `send` | Send |
| `reply` / `reply all` | Reply to open mail |
| `close gmail` | Leave mode |

---

## Maps

| Command | Action |
|---------|--------|
| `open maps` | Google Maps sticky |
| `search Marina Beach` | Search place |
| `directions to Airport` | Directions |
| `start` | Start navigation |
| `zoom in` / `zoom out` | Zoom |
| `close maps` | Leave mode |

---

## Safety

Risky actions (e.g. shutdown, delete file) need confirm:

| Command | Action |
|---------|--------|
| `CONFIRM …` | Confirm pending risky act |
| `CANCEL` | Cancel |

---

## Chat / memory / other

| Command | Action |
|---------|--------|
| `clear chat` | Clear the UI thread |
| `remember …` | Save to memory |
| `list files` / `ls` | List files |
| `graph add A relation B` | Knowledge graph |
| `graph search …` | Search graph |
| `comfy a red robot` | ComfyUI image (if running) |

---

## ALTRON vs n8n (WhatsApp downloads & apps)

| Use | Tool |
|-----|------|
| Voice/type live control (select, call, send, play) | **ALTRON sticky** (current features) |
| Background jobs (every night backup, webhook, multi-step pipeline) | **n8n** |
| WhatsApp “download this photo/file now” while chatting | ALTRON keyword (coming next) — not n8n |
| Spotify **desktop app** | `open spotify app` → play/pause/next via media keys |
| Spotify search + UI | `open spotify` (Web) — richer control |

---

## Quick cheat sheet

```
open ide      →  list  →  open file.py  →  edit …  →  run python …  →  close ide
open youtube  →  song name  →  first video  →  forward / backward  →  pause  →  close youtube
open browser  →  search cats  →  open first link  →  scroll down  →  back  →  close browser
open whatsapp →  select number one  →  vanakkam  →  call  →  hang up  →  close whatsapp
open spotify  →  search …  →  play  →  next  →  close spotify
open explorer →  select 1  →  open  ·  delete → CONFIRM FS_DELETE
open notepad  →  speak notes  →  save as ideas  →  close notepad
open gmail    →  compose to a@b.com  →  subject Hi  →  body  →  send
open maps     →  search place  →  directions to …  →  start
```

---

## Tips

- After code updates, refresh the UI (**Ctrl+F5**) and reopen the mode (`close …` then `open …`) so the controlled window picks up layout/seek fixes.
- If a command is typed into a search box instead of acting, say the **keyword form** from this guide (`call`, `open first link`, `forward`) — those are reserved actions.
- Only one sticky mode should be active; if WhatsApp “eats” YouTube commands, say `close whatsapp` first.
