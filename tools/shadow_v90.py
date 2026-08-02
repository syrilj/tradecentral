#!/usr/bin/env python3
"""Shadow-log one decision per symbol from edge/models/v90 (Step 7).

Appends JSONL rows to edge/runs/shadow_decisions.jsonl. Does not place orders.
Uses the most recent bar available in edge/data/1h or TradingAlgoWork/data_cache/1h.

Usage (from alltrading/):
  python3 edge/tools/shadow_v90.py
  python3 edge/tools/shadow_v90.py --symbols SPY,TSLA,NVDA
  python3 edge/tools/shadow_v90.py --realize   # backfill realized outcomes for aged rows

Each decision row stores calibrated probability + side. Realization is a
separate pass once HORIZON bars have elapsed (default 8 × 1h).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
BUNDLE = EDGE / "models" / "v90"
RUNS = EDGE / "runs"
LOG = RUNS / "shadow_decisions.jsonl"
HORIZON = 8
COST = 0.001


def _load_engine():
    sys.path.insert(0, str(BUNDLE))
    from signal_engine import SignalEngine  # type: ignore

    return SignalEngine()


def _find_parquet(sym: str) -> Optional[Path]:
    candidates = [
        EDGE / "data" / "1h" / f"{sym}.parquet",
        ROOT / "TradingAlgoWork" / "data_cache" / "1h" / f"{sym}.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_ohlcv(sym: str) -> Optional[pd.DataFrame]:
    path = _find_parquet(sym)
    if path is None:
        return None
    df = pd.read_parquet(path).sort_index()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[cols].astype(float)


def _event_id(model: str, symbol: str, asof: str) -> str:
    raw = f"{model}|{symbol}|{asof}".encode()
    return hashlib.sha1(raw).hexdigest()[:20]


def _append(row: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def decide(symbols: List[str]) -> int:
    eng = _load_engine()
    data_map: Dict[str, pd.DataFrame] = {}
    for s in symbols:
        df = _load_ohlcv(s)
        if df is None or len(df) < 50:
            print(f"skip {s}: no/short data")
            continue
        data_map[f"{s}.US"] = df

    if not data_map:
        print("No symbols loaded.", file=sys.stderr)
        return 2

    weights = eng.generate(data_map)
    n_written = 0
    now = datetime.now(timezone.utc).isoformat()
    for code, w in weights.items():
        sym = code.replace(".US", "")
        df = data_map[code]
        asof = df.index[-1]
        side = str(eng.last_side[code].iloc[-1])
        conf = float(eng.last_confidence[code].iloc[-1])
        weight = float(w.iloc[-1])
        state = "SIGNAL" if side != "FLAT" else "ABSTAIN"
        row = {
            "event_id": _event_id("v90_meta_confidence", sym, str(asof)),
            "recorded_at_utc": now,
            "asof_bar": str(asof),
            "model": "v90_meta_confidence",
            "model_path": "edge/models/v90",
            "symbol": sym,
            "state": state,
            "side": side,
            "target_weight": weight,
            "calibrated_probability": conf if state == "SIGNAL" else None,
            "raw_threshold_gate": "enter_hi/balanced_top5",
            "horizon_bars": HORIZON,
            "cost_roundtrip": COST,
            "realized": None,
        }
        _append(row)
        n_written += 1
        print(f"{sym:6s} {state:8s} side={side:12s} w={weight:+.3f} conf={conf:.3f} asof={asof}")
    print(f"Appended {n_written} rows → {LOG}")
    return 0


def realize() -> int:
    """Fill realized outcome for SIGNAL rows whose horizon has elapsed."""
    if not LOG.exists():
        print("No log yet.")
        return 0
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    changed = 0
    for row in rows:
        if row.get("realized") is not None:
            continue
        if row.get("state") != "SIGNAL":
            continue
        sym = row["symbol"]
        df = _load_ohlcv(sym)
        if df is None:
            continue
        asof = pd.Timestamp(row["asof_bar"])
        if asof not in df.index:
            # nearest prior
            prior = df.index[df.index <= asof]
            if len(prior) == 0:
                continue
            asof = prior[-1]
        loc = df.index.get_loc(asof)
        if isinstance(loc, slice):
            loc = loc.stop - 1
        if isinstance(loc, np.ndarray):
            loc = int(loc[-1])
        j = int(loc) + HORIZON
        if j >= len(df):
            continue
        entry = float(df["close"].iloc[int(loc)])
        exit_px = float(df["close"].iloc[j])
        side = row.get("side", "FLAT")
        if side == "BUY":
            gross = exit_px / entry - 1.0
        elif side in ("SELL", "SELL_FLATTEN"):
            gross = entry / exit_px - 1.0
        else:
            continue
        net = gross - COST
        row["realized"] = {
            "exit_bar": str(df.index[j]),
            "gross_return": gross,
            "net_return": net,
            "win": bool(net > 0),
            "predicted_p": row.get("calibrated_probability"),
        }
        changed += 1

    # rewrite full log (small)
    with LOG.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    print(f"Realized outcomes filled: {changed}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="SPY,QQQ,TSLA,MU,NVDA,AAPL,MSFT,XLP,IONQ,APLD")
    ap.add_argument("--realize", action="store_true")
    args = ap.parse_args(argv)
    if args.realize:
        return realize()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    return decide(symbols)


if __name__ == "__main__":
    raise SystemExit(main())
