#!/usr/bin/env python3
"""Daily reliability summary from edge/runs/shadow_decisions.jsonl (Step 7).

Buckets predicted calibrated probability vs realized win rate.
Prints a table and writes edge/runs/reliability_latest.json.

Usage:
  python3 edge/tools/shadow_reliability.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "runs" / "shadow_decisions.jsonl"
OUT = Path(__file__).resolve().parents[1] / "runs" / "reliability_latest.json"


def wilson_low(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return float("nan")
    p = k / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (centre - margin) / denom


def main() -> int:
    if not LOG.exists():
        print(f"No log at {LOG}. Run edge/tools/shadow_v90.py first.")
        return 2
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    realized = [r for r in rows if r.get("realized") and r.get("calibrated_probability") is not None]
    print(f"total rows={len(rows)}  realized_signals={len(realized)}")
    if not realized:
        print("No realized SIGNAL rows yet — keep shadowing / pass --realize after horizon.")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(
                {
                    "generated_utc": datetime.now(timezone.utc).isoformat(),
                    "n_total": len(rows),
                    "n_realized": 0,
                    "buckets": [],
                    "note": "insufficient data",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    # fixed buckets
    edges = [0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 1.01]
    buckets = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        grp = [r for r in realized if lo <= float(r["calibrated_probability"]) < hi]
        if not grp:
            continue
        wins = sum(1 for r in grp if r["realized"]["win"])
        n = len(grp)
        avg_p = sum(float(r["calibrated_probability"]) for r in grp) / n
        avg_net = sum(float(r["realized"]["net_return"]) for r in grp) / n
        buckets.append(
            {
                "p_lo": lo,
                "p_hi": hi,
                "n": n,
                "avg_predicted_p": avg_p,
                "realized_wr": wins / n,
                "wilson95_low": wilson_low(wins, n),
                "avg_net_return": avg_net,
                "ece_contrib": abs(avg_p - wins / n) * (n / len(realized)),
            }
        )
        print(
            f"[{lo:.2f},{hi:.2f}) n={n:4d}  pred={avg_p:.3f}  wr={wins/n:.3f}  "
            f"wilson_lo={wilson_low(wins,n):.3f}  avg_net={avg_net:+.4f}"
        )

    ece = sum(b["ece_contrib"] for b in buckets)
    print(f"\nApproximate ECE (bucketed): {ece:.4f}   (gate wants ≤ 0.05 on holdout, not shadow)")
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_total": len(rows),
        "n_realized": len(realized),
        "ece_bucketed": ece,
        "buckets": buckets,
        "sessions_hint": "Accumulate ≥60 sessions before any live-capital decision (PLAN Step 7).",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
