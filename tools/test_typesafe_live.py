"""Opt-in paid TypeSafe smoke test: python tools/test_typesafe_live.py.

Uses synthetic closed-gate evidence, never orders. Prints no credentials.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daily_plays.config import load_project_environment
from research.typesafe_live_decision import evaluate_live_decision


def main() -> int:
    load_project_environment(paths=[ROOT / ".env"])
    state = {
        "symbol": "SPY",
        "source_status": {},
        "execution_gate": {
            "may_enter": False,
            "reason": "Synthetic connection test: no market evidence supplied.",
        },
    }
    for attempt in range(2):
        started = time.perf_counter()
        result = evaluate_live_decision(state)
        print(
            json.dumps(
                {
                    "attempt": attempt + 1,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "engine": result["engine"],
                    "cache": result["cache"],
                    "action": result["action"],
                    "decision_authorized": result["decision_authorized"],
                }
            )
        )
        if result["engine"]["mode"] != "typesafe" or result["action"] != "wait":
            return 1
        if result["decision_authorized"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
