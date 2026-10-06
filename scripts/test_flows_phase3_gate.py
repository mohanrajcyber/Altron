from __future__ import annotations

"""Phase 3 GATE — regression + Phase 3 acceptance.

Honest PASS/FAIL. Does not print PHASE 3 COMPLETE unless all gates pass.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run_script(rel: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [PY, str(ROOT / rel)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode == 0, out


def main() -> int:
    suite = [
        ("Phase1", "scripts/test_flows_phase1.py"),
        ("Phase1 final", "scripts/test_flows_phase1_final.py"),
        ("Phase2 gate", "scripts/test_flows_phase2_gate.py"),
        ("Phase2 final", "scripts/test_flows_phase2_final_gate.py"),
        ("Phase3", "scripts/test_flows_phase3.py"),
    ]
    results: list[tuple[str, bool]] = []
    for name, rel in suite:
        print(f"\n===== RUNNING {name}: {rel} =====")
        ok, out = run_script(rel)
        # keep output readable
        tail = "\n".join(out.strip().splitlines()[-40:])
        print(tail)
        results.append((name, ok))
        print(f"===== {name}: {'PASS' if ok else 'FAIL'} =====")

    print("\n===== PHASE 3 GATE MATRIX =====")
    all_ok = True
    for name, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        all_ok = all_ok and ok

    if all_ok:
        print("\nPHASE 3 = COMPLETE")
        return 0
    print("\nPHASE 3 = NOT COMPLETE")
    print("Remaining failures:")
    for name, ok in results:
        if not ok:
            print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
