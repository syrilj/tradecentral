#!/usr/bin/env python3
"""CLI for train vs OOS squeeze + flow-shift evaluation."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from edge.research.squeeze_flow_eval import (  # noqa: E402
    DEFAULT_FIXTURE,
    SqueezeFlowEvalConfig,
    run_and_save,
    write_fixture,
)


def _print_block(name: str, block: dict) -> None:
    print(f"=== {name} ===")
    print(
        f"n={block.get('n')} hits={block.get('hits')} "
        f"hit_rate={block.get('hit_rate')} rank_ic={block.get('rank_ic')} "
        f"threshold={block.get('threshold')}"
    )
    bands = block.get("by_confidence") or {}
    for band in ("high", "low"):
        stats = bands.get(band) or {}
        print(
            f"  {band}: n={stats.get('n')} hit_rate={stats.get('hit_rate')} "
            f"rank_ic={stats.get('rank_ic')}"
        )


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Squeeze + flow-shift train/OOS eval")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[1] / "runs" / "squeeze_flow_eval"))
    p.add_argument("--panel", default="", help="Existing panel parquet/json")
    p.add_argument("--local-bars", action="store_true", help="Build panel from local 1d/1h bars")
    p.add_argument("--write-fixture", action="store_true", help="Refresh the checked-in fixture and exit")
    args = p.parse_args()
    if args.write_fixture:
        dest = write_fixture()
        print(f"wrote fixture → {dest}")
        return 0
    use_fixture = not args.local_bars and not args.panel
    panel_path = args.panel or (str(DEFAULT_FIXTURE) if use_fixture and DEFAULT_FIXTURE.exists() else None)
    cfg = SqueezeFlowEvalConfig(
        panel_path=panel_path,
        out_dir=args.out_dir,
        use_fixture=use_fixture and not args.panel,
    )
    payload = run_and_save(cfg)
    print("=== SQUEEZE + FLOW-SHIFT TRAIN/OOS ===")
    print(f"rows={payload.get('n_rows')} folds={payload.get('n_folds')} split={payload.get('split')}")
    print(f"chosen_threshold={payload.get('chosen_threshold')}")
    _print_block("TRAIN", payload.get("train") or {})
    _print_block("OOS", payload.get("oos") or {})
    print(f"artifacts → {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
