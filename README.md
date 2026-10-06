# ALTRON

Original AGI command core. Donor Git repos stay as references. This folder is the product.

Face: `http://127.0.0.1:8088/` — custom command core (threads, inspector, mic, traces).

**Project website:** https://mohanrajcyber.github.io/Altron/ (static project homepage; the interactive command core runs locally).

**Commands:** [docs/CONTROL_GUIDE.md](docs/CONTROL_GUIDE.md) — YouTube · Browser · WhatsApp · desktop (all sticky controls).

## Run

```powershell
cd C:\Users\ADMIN\Desktop\AGI\ALTRON
.\.venv\Scripts\Activate.ps1
copy .env.example .env
python -m altron serve
```

Desktop: `python -m altron app` · EXE: `.\scripts\build_exe.ps1` · Organs: `.\scripts\setup_organs.ps1`

## Organs (v0.7)

| Organ | How |
|---|---|
| Vision | `see screen` / `what's on my screen` → `data/screens/` + describe |
| Desktop | `open whatsapp` · `notepad write …` · `open folder …` |
| Safety | risky acts → `CONFIRM …` / `CANCEL` |
| Voice | Mic latch · wake “hey ALTRON” · hold Space push-to-talk |
| Ollama | `.\scripts\start_ollama.ps1` then ALTRON falls back automatically |
| Vector memory | `.\scripts\start_qdrant.ps1` → status `memory=qdrant` (else local_vector) |
| Browser AGI | `open browser` then voice/type any action · allowlist |
| **IDE** | `open ide` · Face **IDE** tab · Continue/Cline → `/v1` · [docs/ide](docs/ide/README.md) |
| YouTube | `open youtube` → search / play / seek / … |
| Spotify | `open spotify` / `open spotify app` → play/pause/next |
| Gmail / Maps | `open gmail` · `open maps` |
| Explorer / Notepad | `open explorer` · `open notepad` (sticky) |
| Commands guide | [docs/CONTROL_GUIDE.md](docs/CONTROL_GUIDE.md) |
| E2B | set `E2B_API_KEY` + `pip install -e ".[e2b]"` · else local sandbox |
| n8n | `.\scripts\start_n8n.ps1` · webhook `altron-jobs` |
| LiveKit | set `LIVEKIT_*` · browser Mic already works |
| Graphiti | `graph add` / `graph search` |
| ComfyUI | `:8188` · `comfy a red robot` |
| Installer | `.\scripts\install_shortcuts.ps1` |

## Loop

`remember -> plan -> think or act -> judge -> persist`
