# ALTRON IDE

Full-page original IDE — **not** VS Code / code-server / Copilot.

## Open (new tab)

- Chat: `open ide` → opens **http://127.0.0.1:8088/ide** in Chrome/new tab  
- Face: click **IDE** → same `/ide` page in a new tab  

## Stack

| Layer | Implementation |
|-------|----------------|
| Page | `/ide` (`ide.html` + `ide-page.css` + `ide.js` + `ide-features.js`) |
| Editor | Monaco + DiffEditor + split (Ctrl+\\) |
| Terminal | xterm.js ↔ `/api/ide/terminal/*` |
| Preview | `/api/ide/preview-page` + raw assets |
| Agent | SSE `/api/ide/agent/stream` + AGI tools + history undo |
| Git | status/stage/commit/pull/push/branches/checkout |
| Extras | autosave, layout prefs, drag-drop move, diagnostics markers |

## Features checklist

- Explorer create/rename/delete/move (drag-drop)
- Tabs, quick open, command palette
- Autosave + layout persist (`data/ide/prefs.json`)
- Split editor
- HTML live preview
- Problems diagnostics (Python syntax + TODOs)
- Agent streaming + Apply/Reject diffs + undo history
- Run / Debug run / Stop
- Git panel + branch switch

## Sticky commands

See `docs/CONTROL_GUIDE.md` → ALTRON IDE.
