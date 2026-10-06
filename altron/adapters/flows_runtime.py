from __future__ import annotations

"""ALTRON FLOWS Phase-1 trigger runtime: schedule, file-created, webhook, app-started.

Runs inside the ALTRON server process. All paths must pass Trusted Roots.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from altron.adapters import flows_engine, pc_roots

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_state_path_name = "trigger_runtime.json"
_started_once = False


def _state_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / _state_path_name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_state(settings) -> dict:
    path = _state_path(settings)
    if not path.is_file():
        return {"schedules": {}, "watches": {}, "app_started_done": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schedules": {}, "watches": {}, "app_started_done": []}


def _save_state(settings, state: dict) -> None:
    _state_path(settings).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _cron_match(cron: str, now: datetime | None = None) -> bool:
    """Minimal 5-field cron: min hour dom month dow. Supports *, N, */N, lists."""
    cron = (cron or "").strip()
    if not cron:
        return False
    parts = cron.split()
    if len(parts) != 5:
        return False
    now = now or datetime.now()
    fields = [now.minute, now.hour, now.day, now.month, (now.weekday() + 1) % 7]  # Sun=0

    def match(field: str, value: int, lo: int, hi: int) -> bool:
        if field == "*":
            return True
        for piece in field.split(","):
            piece = piece.strip()
            if piece.startswith("*/"):
                try:
                    step = max(1, int(piece[2:]))
                except ValueError:
                    return False
                return value % step == 0
            if "-" in piece:
                a, b = piece.split("-", 1)
                try:
                    return int(a) <= value <= int(b)
                except ValueError:
                    return False
            try:
                if int(piece) == value:
                    return True
            except ValueError:
                return False
        return False

    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    return all(match(parts[i], fields[i], *ranges[i]) for i in range(5))


def _flows_with_trigger(settings, prefix: str) -> list[tuple[dict, dict]]:
    out: list[tuple[dict, dict]] = []
    for meta in flows_engine.list_flows(settings):
        flow = flows_engine.get_flow(settings, meta["id"])
        if not flow:
            continue
        for node in flow.get("nodes") or []:
            if str(node.get("type", "")).startswith(prefix) and not node.get("disabled"):
                out.append((flow, node))
                break
    return out


def fire_flow(settings, flow_id: str, trigger_payload: dict) -> dict:
    """Run a flow with trigger context injected into runtime via a temp marker in settings dict."""
    # Stash trigger payload for engine to pick up
    with _lock:
        stash = getattr(fire_flow, "_stash", {})
        stash[flow_id] = trigger_payload
        fire_flow._stash = stash  # type: ignore[attr-defined]
    try:
        return flows_engine.run_flow(settings, flow_id)
    finally:
        with _lock:
            stash = getattr(fire_flow, "_stash", {})
            stash.pop(flow_id, None)


def take_trigger_stash(flow_id: str) -> dict | None:
    with _lock:
        stash = getattr(fire_flow, "_stash", {})
        return stash.pop(flow_id, None)


def tick(settings) -> list[str]:
    """One scheduler/watcher tick. Returns log lines of actions taken."""
    lines: list[str] = []
    state = _load_state(settings)
    now = datetime.now()
    minute_key = now.strftime("%Y%m%d%H%M")

    # Schedule triggers
    for flow, node in _flows_with_trigger(settings, "trigger.schedule"):
        cron = str((node.get("config") or {}).get("cron") or "").strip()
        if not _cron_match(cron, now):
            continue
        fid = flow["id"]
        last = (state.get("schedules") or {}).get(fid)
        if last == minute_key:
            continue
        state.setdefault("schedules", {})[fid] = minute_key
        _save_state(settings, state)
        run = fire_flow(settings, fid, {"source": "trigger.schedule", "cron": cron, "at": time.time()})
        lines.append(f"schedule fired {fid} → {run.get('status')}")

    # File created watches
    for flow, node in _flows_with_trigger(settings, "trigger.file_created"):
        cfg = node.get("config") or {}
        folder = str(cfg.get("path") or "").strip()
        resolved = pc_roots.resolve_in_roots(settings, folder) if folder else None
        if resolved is None or not resolved.is_dir():
            continue
        fid = flow["id"]
        key = f"{fid}:{resolved}"
        watches = state.setdefault("watches", {})
        current: dict[str, float] = {}
        try:
            for child in resolved.iterdir():
                if child.name.startswith("."):
                    continue
                try:
                    current[child.name] = child.stat().st_mtime
                except OSError:
                    continue
        except OSError:
            continue
        names = set(current.keys())
        if key not in watches:
            # first sight — seed without firing (even if folder is empty)
            watches[key] = sorted(names)
            _save_state(settings, state)
            continue
        known = set(watches.get(key) or [])
        created = names - known
        if created:
            watches[key] = sorted(names)
            _save_state(settings, state)
            for name in sorted(created)[:5]:
                path = str(resolved / name)
                run = fire_flow(
                    settings,
                    fid,
                    {
                        "source": "trigger.file_created",
                        "path": path,
                        "name": name,
                        "folder": str(resolved),
                        "at": time.time(),
                    },
                )
                lines.append(f"file_created {name} → {fid} → {run.get('status')}")
        else:
            watches[key] = sorted(names)
            _save_state(settings, state)

    return lines


def run_app_started(settings) -> list[str]:
    """Fire each app-started flow once per server process (tracked in state)."""
    global _started_once
    lines: list[str] = []
    if _started_once:
        return lines
    _started_once = True
    state = _load_state(settings)
    done = set(state.get("app_started_done") or [])
    session = str(int(time.time()))
    for flow, node in _flows_with_trigger(settings, "trigger.app_started"):
        fid = flow["id"]
        marker = f"{fid}:{session}"
        # once per process; also avoid re-fire same second spam
        run = fire_flow(settings, fid, {"source": "trigger.app_started", "at": time.time(), "node": node.get("id")})
        lines.append(f"app_started {fid} → {run.get('status')}")
        done.add(fid)
    state["app_started_done"] = sorted(done)[-50:]
    _save_state(settings, state)
    return lines


def find_webhook_flow(settings, slug: str) -> dict | None:
    slug = (slug or "").strip().strip("/")
    if not slug:
        return None
    for flow, node in _flows_with_trigger(settings, "trigger.webhook"):
        cfg = node.get("config") or {}
        path = str(cfg.get("path") or "").strip().strip("/")
        # accept path, id, or name slug
        if path == slug or flow.get("id") == slug or str(flow.get("name", "")).lower().replace(" ", "-") == slug.lower():
            return flow
    return None


def handle_webhook(settings, slug: str, payload: dict | None = None) -> dict:
    flow = find_webhook_flow(settings, slug)
    if not flow:
        return {"ok": False, "message": f"No webhook flow for '{slug}'"}
    run = fire_flow(
        settings,
        flow["id"],
        {"source": "trigger.webhook", "slug": slug, "payload": payload or {}, "at": time.time()},
    )
    return {"ok": bool(run.get("ok")), "flow_id": flow["id"], "run": {"id": run.get("id"), "status": run.get("status")}}


def _loop(settings_factory) -> None:
    while not _stop.is_set():
        try:
            settings = settings_factory()
            tick(settings)
        except Exception:
            pass
        _stop.wait(20)


def start(settings_factory) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    settings = settings_factory()
    try:
        run_app_started(settings)
    except Exception:
        pass
    _thread = threading.Thread(target=_loop, args=(settings_factory,), daemon=True, name="altron-flows-runtime")
    _thread.start()


def stop() -> None:
    _stop.set()
