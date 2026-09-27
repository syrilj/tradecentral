#!/usr/bin/env python3
"""Re-fit v90_meta_confidence on the Step 5 widened 1h universe (same hyperparams).

Wraps TradingAlgoWork/tools/train_v90_meta_confidence.py without changing model
capacity, folds, barriers, or costs — only the symbol list, data root, and
output bundle.

Usage (from alltrading/):
  python3 edge/tools/train_v90_wide.py --dry-run
  python3 edge/tools/train_v90_wide.py

Writes boosters + calibration + thresholds + results into edge/models/v90_wide/.
Does NOT update edge/models/v90/ (baseline champion stays frozen until gate).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
TAW = ROOT / "TradingAlgoWork"
SRC_TRAIN = TAW / "tools" / "train_v90_meta_confidence.py"
BASELINE = TAW / "models" / "poc_va_macdha" / "v90_meta_confidence"
CFG = EDGE / "config" / "universe_wide.json"
DATA_1H = EDGE / "data" / "1h"
OUT_BUNDLE = EDGE / "models" / "v90_wide"


def _symbols_with_data(cfg_path: Path) -> List[str]:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    have = []
    for s in cfg["symbols"]:
        if (DATA_1H / f"{s}.parquet").exists():
            have.append(s)
    return have


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-symbols", type=int, default=40)
    ap.add_argument("--out", type=Path, default=OUT_BUNDLE)
    args = ap.parse_args(argv)

    if not DATA_1H.exists():
        print(f"Missing {DATA_1H}. Run: python3 edge/tools/fetch_universe.py", file=sys.stderr)
        return 2

    symbols = _symbols_with_data(CFG)
    print(f"1h symbols with data: {len(symbols)}")
    for s in symbols[:12]:
        df = pd.read_parquet(DATA_1H / f"{s}.parquet")
        df.index = pd.to_datetime(df.index)
        print(f"  {s}: n={len(df)} {df.index.min().date()}→{df.index.max().date()}")
    if len(symbols) > 12:
        print(f"  ... +{len(symbols) - 12} more")

    if args.dry_run:
        return 0 if len(symbols) >= args.min_symbols else 2

    if len(symbols) < args.min_symbols:
        print(
            f"Need ≥{args.min_symbols} 1h symbols; have {len(symbols)}. Fetch more first.",
            file=sys.stderr,
        )
        return 2

    if not SRC_TRAIN.exists():
        print(f"Missing source train script: {SRC_TRAIN}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # features.py must sit next to boosters for SignalEngine-style loaders
    shutil.copy2(BASELINE / "features.py", out / "features.py")

    # Import source train module with its features path on sys.path
    sys.path.insert(0, str(BASELINE))
    spec = importlib.util.spec_from_file_location("train_v90_src", SRC_TRAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    codes = [f"{s}.US" for s in symbols]

    def load_symbol(code: str) -> pd.DataFrame:
        sym = code.replace(".US", "")
        path = DATA_1H / f"{sym}.parquet"
        df = pd.read_parquet(path).sort_index()
        df.index = pd.to_datetime(df.index)
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        return df[["open", "high", "low", "close", "volume"]].astype(float)

    mod.UNIVERSE = codes
    mod.load_symbol = load_symbol  # type: ignore[attr-defined]
    mod.BUNDLE = out
    # Keep TRAIN/HOLDOUT identical to source (1h practical window)

    print(f"Training {len(codes)} symbols → {out}")
    print(f"  TRAIN={mod.TRAIN}  HOLDOUT={mod.HOLDOUT}")
    rc = int(mod.main() or 0)

    # Provenance stamp
    prov = {
        "trained_by": "edge/tools/train_v90_wide.py",
        "source_script": str(SRC_TRAIN.relative_to(ROOT)),
        "universe_config": str(CFG.relative_to(ROOT)),
        "n_symbols": len(codes),
        "symbols": codes,
        "data_root": str(DATA_1H.relative_to(ROOT)),
        "hyperparams_unchanged_from": "TradingAlgoWork/tools/train_v90_meta_confidence.py",
        "baseline_champion_untouched": "edge/models/v90",
        "gate": "Evaluate once via edge/docs/GATE.md; write edge/docs/GATE_RESULT.md. No re-tune.",
    }
    (out / "PROVENANCE.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
    # Runtime knobs from baseline so a SignalEngine can load this bundle
    for name in ("hunt_config.json", "config.json", "signal_engine.py"):
        src = EDGE / "models" / "v90" / name
        if src.exists() and not (out / name).exists():
            shutil.copy2(src, out / name)
    print(f"Done rc={rc}; provenance → {out / 'PROVENANCE.json'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
