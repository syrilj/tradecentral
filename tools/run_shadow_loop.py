#!/usr/bin/env python3
"""Automated Daily Shadow Evidence Collection & Paper Ticket Generator.

Runs daily pre-market & post-market execution loop:
  1. Record today's shadow decisions via shadow_v90.py.
  2. Realize aged signal outcomes via shadow_v90.py --realize.
  3. Compute reliability statistics via shadow_reliability.py.
  4. Generate LAST_TICKET.json paper orders for ready-to-key IBKR paper trades.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "edge" / "runs"
LOG_FILE = RUNS / "shadow_decisions.jsonl"
TICKET_FILE = RUNS / "LAST_TICKET.json"

PYTHON_BIN = str(ROOT / "edge" / ".venv-qlib" / "bin" / "python")


def run_cmd(args: list[str]) -> bool:
    try:
        res = subprocess.run([PYTHON_BIN] + args, cwd=ROOT, capture_output=True, text=True)
        print(res.stdout)
        if res.returncode != 0:
            print(f"Warning running {args}: {res.stderr}")
            return False
        return True
    except Exception as e:
        print(f"Error running {args}: {e}")
        return False


def generate_paper_tickets() -> dict:
    tickets = []
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-10:]:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                prob = rec.get("calibrated_probability", 0.5)
                side = rec.get("side", "LONG").upper()
                sym = rec.get("symbol", "UNKNOWN")
                if prob >= 0.65:
                    tickets.append({
                        "symbol": sym,
                        "action": "BUY" if side == "LONG" else "SELL_SHORT",
                        "order_type": "MKT",
                        "quantity": 100,
                        "calibrated_probability": prob,
                        "horizon": "8h",
                        "reason": f"v90 model score prob={prob:.3f}",
                    })
            except Exception:
                pass

    session_count = 0
    realized_count = 0
    if LOG_FILE.exists():
        rows = [json.loads(l) for l in LOG_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        session_count = len(rows)
        realized_count = len([r for r in rows if r.get("realized")])

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "shadow_only": True,
        "progress": {
            "realized_sessions": realized_count,
            "required_sessions": 60,
            "progress_pct": round(min(1.0, realized_count / 60.0) * 100, 1),
            "status": "ACCUMULATING_EVIDENCE" if realized_count < 60 else "GO_DISCUSSION_AUTHORIZED",
        },
        "tickets": tickets,
    }

    TICKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    TICKET_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Generated paper tickets → {TICKET_FILE}")
    return payload


def main():
    print("=" * 60)
    print("  RUNNING DAILY SHADOW EVIDENCE COLLECTION LOOP")
    print("=" * 60)

    # Step 1: Record new shadow decisions
    print("\n[1/3] Logging daily shadow decisions...")
    run_cmd(["edge/tools/shadow_v90.py"])

    # Step 2: Realize aged outcomes
    print("\n[2/3] Realizing aged signal outcomes...")
    run_cmd(["edge/tools/shadow_v90.py", "--realize"])

    # Step 3: Compute reliability summary
    print("\n[3/3] Updating shadow reliability statistics...")
    run_cmd(["edge/tools/shadow_reliability.py"])

    # Step 4: Generate IBKR paper tickets
    print("\n[4/4] Generating IBKR paper order tickets...")
    payload = generate_paper_tickets()

    print("\n[SHADOW EVIDENCE LOOP COMPLETE]")
    print(f"  Realized Sessions: {payload['progress']['realized_sessions']} / 60")
    print(f"  Progress:          {payload['progress']['progress_pct']}%")
    print(f"  Status:            {payload['progress']['status']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
