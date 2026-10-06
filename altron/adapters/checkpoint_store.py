from __future__ import annotations

"""Durable SQLite checkpoint store for Flows runs.

Keeps a small row per in-flight run so a server crash/restart mid-run is
visible (status flips to INTERRUPTED) instead of silently vanishing — the
in-memory `_active_runs`/`_active_meta` dicts in flows_engine.py do not
survive a restart, this does.
"""

import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id TEXT PRIMARY KEY,
    flow_id TEXT,
    flow_name TEXT,
    status TEXT NOT NULL,
    started REAL NOT NULL,
    updated REAL NOT NULL,
    current_label TEXT,
    completed_nodes INTEGER DEFAULT 0,
    total_nodes INTEGER DEFAULT 0
)
"""


def _db_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / "checkpoints.sqlite3"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect(settings) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(settings)), timeout=5.0)
    conn.execute(_SCHEMA)
    return conn


def start_run(settings, run_id: str, flow_id: str, flow_name: str, total_nodes: int) -> None:
    with _lock, _connect(settings) as conn:
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO run_checkpoints "
            "(run_id, flow_id, flow_name, status, started, updated, current_label, completed_nodes, total_nodes) "
            "VALUES (?, ?, ?, 'RUNNING', ?, ?, '', 0, ?)",
            (run_id, flow_id, flow_name, now, now, total_nodes),
        )


def update_run(settings, run_id: str, completed_nodes: int, current_label: str) -> None:
    with _lock, _connect(settings) as conn:
        conn.execute(
            "UPDATE run_checkpoints SET completed_nodes = ?, current_label = ?, updated = ? WHERE run_id = ?",
            (completed_nodes, current_label, time.time(), run_id),
        )


def finish_run(settings, run_id: str, status: str) -> None:
    with _lock, _connect(settings) as conn:
        conn.execute(
            "UPDATE run_checkpoints SET status = ?, updated = ? WHERE run_id = ?",
            (status, time.time(), run_id),
        )


def reconcile_on_boot(settings) -> int:
    """Call once at server startup: any run still marked RUNNING was orphaned by a
    crash/restart. Flip it to INTERRUPTED so it is not mistaken for a live run."""
    with _lock, _connect(settings) as conn:
        cur = conn.execute("UPDATE run_checkpoints SET status = 'INTERRUPTED', updated = ? WHERE status = 'RUNNING'", (time.time(),))
        return cur.rowcount


def list_recent(settings, limit: int = 50) -> list[dict]:
    with _lock, _connect(settings) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM run_checkpoints ORDER BY updated DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_interrupted(settings) -> list[dict]:
    with _lock, _connect(settings) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM run_checkpoints WHERE status = 'INTERRUPTED' ORDER BY updated DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
