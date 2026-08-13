#!/usr/bin/env python3
"""CLI entry for gamma-squeeze theory validation (local or Vertex worker)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from edge.research.squeeze_validation import SqueezeValidationConfig, run_and_save  # noqa: E402


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[1] / "runs" / "squeeze_validation"))
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--threshold", type=float, default=15.0)
    args = p.parse_args()
    cfg = SqueezeValidationConfig(
        out_dir=args.out_dir,
        fetch_missing_forward=not args.no_fetch,
        score_threshold=args.threshold,
    )
    payload = run_and_save(cfg)
    summary = payload.get("summary") or {}
    print("=== GAMMA SQUEEZE THEORY VALIDATION ===")
    print(f"records={payload.get('n_records')} errors={payload.get('n_errors')}")
    print(f"fire_rate={summary.get('fire_rate')}")
    print(f"max_abs_theory_score={summary.get('max_abs_theory_score')}")
    for h, block in (summary.get("horizons") or {}).items():
        th = block.get("theory_hit") or {}
        mh = block.get("momentum_baseline_hit") or {}
        tb = block.get("top_bottom_quartile") or {}
        amp = block.get("amplification") or {}
        print(
            f"  {h}: theory_hit={th.get('hit_rate')} (n={th.get('n')}) | "
            f"mom_hit={mh.get('hit_rate')} (n={mh.get('n')}) | "
            f"IC_theory={block.get('rank_ic_theory')} IC_mom={block.get('rank_ic_mom')}"
        )
        print(
            f"       top/bottom Q: top_up={tb.get('top_hit_rate_up')} bot_dn={tb.get('bottom_hit_rate_down')} "
            f"LS={tb.get('long_short_mean_return')} | "
            f"amp IC(SR,|r|)={amp.get('rank_ic_sr_vs_abs_ret')}"
        )
    print("threshold_sweep:", json.dumps(summary.get("threshold_sweep"), indent=2, default=str))
    for name in ("train", "oos"):
        block = summary.get(name) or (payload.get("train_oos") or {}).get(name) or {}
        if block:
            print(
                f"  {name.upper()}: n={block.get('n')} hit_rate={block.get('hit_rate')} "
                f"rank_ic={block.get('rank_ic')} threshold={block.get('threshold')}"
            )
    print(f"artifacts → {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
