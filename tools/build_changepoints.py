#!/usr/bin/env python3
"""Bayesian Online Changepoint Detection cross-section: offline artifact producer.

Implements the dashboard-facing half of Adams & MacKay (2007), "Bayesian
Online Changepoint Detection" (arXiv:0710.3742): run `edge.research.bocpd`'s
`changepoints_from_prices` -- which owns every bit of the actual recursion
(eq. 3), hazard (eq. 5), and truncation (Sec 2.4) math -- over each symbol's
daily close series, and reduce the per-bar `BocpdResult` arrays to the single
cross-sectional row shape `tools/api_server.py`'s `/api/changepoints`
endpoint (no `?symbol=`) reads from `runs/changepoints/latest.json`.

This tool intentionally re-derives nothing about the model itself. `a=1.0`,
`b=1e-4`, `lambda_gap=250.0` are the paper's own Sec 3.2 DJIA-daily-returns
numbers, echoed here only as CLI defaults so a caller can override them for
an experiment without touching `research/bocpd.py`.

Shared JSON contract
---------------------
The exact field names, nesting, and units emitted here are pinned by
`BOCPD_CONTRACT.md` (payload A) so that a second, independently-built worker
(`dashboard/src/views/ChangepointsView.vue`) can be written against the same
contract in parallel without waiting on this file. Do not rename or reshape
fields without updating that contract first.

Modeled on `tools/factor_tearsheet.py`: argparse CLI, per-symbol robustness
(one bad symbol must not kill the run -- it is logged, skipped, and counted,
never allowed to raise out of `main`), a dated JSON artifact plus a
`latest.json` the API server reads unconditionally.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.bocpd import BocpdResult, changepoints_from_prices  # noqa: E402

# --------------------------------------------------------------------------- #
# Model defaults -- the paper's own Sec 3.2 numbers, and the single source of
# truth for the `regime` label rule. Mirrors "Model defaults (single source
# of truth)" in BOCPD_CONTRACT.md verbatim; keep in sync with that file and
# with tools/api_server.py's copy of the same constants for `?symbol=`.
# --------------------------------------------------------------------------- #
DEFAULT_LAMBDA_GAP = 250.0
DEFAULT_PRIOR_A = 1.0
DEFAULT_PRIOR_B = 1e-4
TRUNCATION_MASS = 1e-4
# AMENDMENT 1 (BOCPD_CONTRACT.md): P(r_t=0|x_1:t) is provably constant (= the
# hazard rate) under a constant hazard -- see research/bocpd.py's module
# docstring for the eq. 3-4 derivation -- so it carries zero detection
# information and cannot be a threshold target. `break_prob` = P(r_t<=5|x_1:t)
# replaces it; 0.50 is the contract's measured midpoint between a stable
# regime (~0.015) and an actual break (~1.0).
BREAK_THRESHOLD = 0.50
SETTLING_RUNS = 10
MIN_USABLE_BARS = 60
DEFAULT_LOOKBACK_DAYS = 750
REFERENCE = "Adams & MacKay 2007, arXiv:0710.3742"

DATA_WIDE_DIR = EDGE_ROOT / "data" / "1d_wide"
DATA_CORE_DIR = EDGE_ROOT / "data" / "1d"
DEFAULT_UNIVERSE_PATH = EDGE_ROOT / "config" / "universe_wide.json"
OUTPUT_ROOT = EDGE_ROOT / "runs" / "changepoints"


# --------------------------------------------------------------------------- #
# Numeric helpers -- NaN/Inf-safe by construction, matching the discipline
# `tools/api_server.py`'s `_safe_round` documents: never let a non-finite
# float reach `json.dumps(..., allow_nan=False)`.
# --------------------------------------------------------------------------- #
def _safe_round(x: Any, dp: int) -> float | None:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, dp)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Universe resolution.
# --------------------------------------------------------------------------- #
def _load_universe(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"{path} has no non-empty 'symbols' list")
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


# --------------------------------------------------------------------------- #
# Per-symbol bars -- prefers 1d_wide, falls back to 1d, per the data layout
# documented in BOCPD_CONTRACT.md and tools/build_changepoints.py's task
# brief. Both directories share the same schema: DatetimeIndex named "Date",
# columns open/high/low/close/volume (verified against edge/data/1d_wide
# parquet files at inspection time -- no yfinance-style column normalization
# is needed here, unlike tools/api_server.py's `_normalize_ohlcv_df`, which
# also has to cope with ad-hoc live pulls).
# --------------------------------------------------------------------------- #
def _load_close(symbol: str) -> tuple[pd.Series | None, str | None]:
    path = DATA_WIDE_DIR / f"{symbol}.parquet"
    if not path.is_file():
        path = DATA_CORE_DIR / f"{symbol}.parquet"
    if not path.is_file():
        return None, f"no parquet for {symbol} under data/1d_wide or data/1d"
    try:
        df = pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001
        return None, f"unreadable parquet: {type(e).__name__}: {e}"
    if df is None or df.empty or "close" not in df.columns:
        return None, "empty frame or missing 'close' column"
    if not isinstance(df.index, pd.DatetimeIndex):
        return None, "index is not a DatetimeIndex"
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    if close.empty:
        return None, "no usable close values after coercion"
    return close, None


# --------------------------------------------------------------------------- #
# Run-length array <-> date alignment. `BocpdResult`'s arrays are documented
# as "per bar" but the brief does not pin whether that means aligned to
# `close` (length T) or to the derived returns series R_t = p_t/p_{t-1} - 1
# (length T-1, since the first bar has no prior close to form a return
# against). Handle both without guessing silently -- an unrecognized length
# is a real contract mismatch with research/bocpd.py and must be surfaced,
# not papered over.
# --------------------------------------------------------------------------- #
def _align_dates(index: pd.DatetimeIndex, arr_len: int) -> pd.DatetimeIndex:
    if arr_len == len(index):
        return index
    if arr_len == len(index) - 1:
        return index[1:]
    raise ValueError(
        f"BocpdResult array length {arr_len} does not align with close index "
        f"length {len(index)} (expected {len(index)} or {len(index) - 1})"
    )


# --------------------------------------------------------------------------- #
# Per-symbol row.
# --------------------------------------------------------------------------- #
def _process_symbol(
    symbol: str, *, lookback_days: int, lambda_gap: float, prior_a: float, prior_b: float,
) -> tuple[dict | None, str | None]:
    """Returns (row, None) on success or (None, skip_reason) on failure.

    Never raises -- every failure mode here is a per-symbol skip so one bad
    parquet file or one degenerate series cannot kill a 175-symbol run.
    """
    close, err = _load_close(symbol)
    if close is None:
        return None, err or "no usable close series"

    if len(close) > lookback_days:
        close = close.tail(lookback_days)
    if len(close) < MIN_USABLE_BARS:
        return None, f"only {len(close)} usable bars (< {MIN_USABLE_BARS})"

    try:
        result: BocpdResult = changepoints_from_prices(
            close, lambda_gap=lambda_gap, a=prior_a, b=prior_b, truncation_mass=TRUNCATION_MASS,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"changepoints_from_prices failed: {type(e).__name__}: {e}"

    try:
        # `cp_prob_raw` is deliberately NOT read here (AMENDMENT 1): it is
        # constant by construction and never emitted in any payload.
        # `break_prob`/`break_prob_20` are the real, data-responsive
        # detection statistics, computed by research/bocpd.py itself --
        # never re-derived here.
        break_prob_arr = np.asarray(result.break_prob, dtype=float)
        break_prob_20_arr = np.asarray(result.break_prob_20, dtype=float)
        map_run_arr = np.asarray(result.map_run_length)
        exp_run_arr = np.asarray(result.expected_run_length, dtype=float)
        pred_std_arr = np.asarray(result.pred_std, dtype=float)
        defined_mass_arr = np.asarray(result.pred_var_defined_mass, dtype=float)
        aligned_index = _align_dates(close.index, len(break_prob_arr))
    except Exception as e:  # noqa: BLE001
        return None, f"malformed BocpdResult: {type(e).__name__}: {e}"

    if len(break_prob_arr) == 0:
        return None, "BocpdResult arrays are empty"

    last_break_prob = float(break_prob_arr[-1])
    last_break_prob_20 = float(break_prob_20_arr[-1])
    last_map_run = map_run_arr[-1]
    last_exp_run = float(exp_run_arr[-1])
    # These four are sums/argmax over a normalized probability distribution
    # and should be finite by construction whenever `changepoints_from_prices`
    # didn't already raise -- if one isn't, treat it as a genuinely broken
    # computation for this symbol, not a per-field null.
    if not all(math.isfinite(v) for v in (last_break_prob, last_break_prob_20, float(last_map_run), last_exp_run)):
        return None, "model produced a non-finite core statistic on the last bar"

    map_run_last = int(last_map_run)

    # `pred_std`/`pred_var_defined_mass`, unlike the four checked above, CAN
    # legitimately be undefined at a bar where every live hypothesis has
    # dof<=2 (see research/bocpd.py's pred_var docstring) -- that is real
    # information ("no defined-variance mass left"), not a broken run, so it
    # becomes a `null` field rather than dropping the whole symbol.
    last_pred_std = float(pred_std_arr[-1])
    predictive_vol = last_pred_std if math.isfinite(last_pred_std) else None
    last_defined_mass = float(defined_mass_arr[-1])
    predictive_vol_defined_mass = last_defined_mass if math.isfinite(last_defined_mass) else None

    # Realized returns/vol are computed directly from price, independent of
    # whatever internal alignment BocpdResult uses -- these are diagnostic
    # cross-checks against the model's own predictive_vol, not part of the
    # BOCPD recursion itself.
    rets = close.pct_change().dropna()
    last_return = float(rets.iloc[-1]) if len(rets) else None
    trailing_vol_20d = None
    if len(rets) >= 2:
        v = float(rets.tail(20).std(ddof=1))
        trailing_vol_20d = v if math.isfinite(v) else None
    vol_ratio = None
    if predictive_vol is not None and trailing_vol_20d not in (None, 0.0):
        vol_ratio = predictive_vol / trailing_vol_20d

    break_mask = break_prob_arr >= BREAK_THRESHOLD
    if break_mask.any():
        break_idx = int(np.nonzero(break_mask)[0][-1])
        last_break_date = aligned_index[break_idx].strftime("%Y-%m-%d")
        days_since_break = int(len(aligned_index) - 1 - break_idx)
    else:
        last_break_date = None
        days_since_break = None

    if last_break_prob >= BREAK_THRESHOLD:
        regime = "BREAK"
    elif map_run_last <= SETTLING_RUNS:
        regime = "SETTLING"
    else:
        regime = "STABLE"

    row = {
        "symbol": symbol,
        "n_bars": int(len(close)),
        "last_date": close.index[-1].strftime("%Y-%m-%d"),
        "break_prob": _safe_round(last_break_prob, 6),
        "break_prob_20": _safe_round(last_break_prob_20, 6),
        "map_run_length": map_run_last,
        "expected_run_length": _safe_round(last_exp_run, 6),
        "last_break_date": last_break_date,
        "days_since_break": days_since_break,
        "predictive_vol": _safe_round(predictive_vol, 6),
        "predictive_vol_defined_mass": _safe_round(predictive_vol_defined_mass, 6),
        "trailing_vol_20d": _safe_round(trailing_vol_20d, 6),
        "vol_ratio": _safe_round(vol_ratio, 6),
        "last_return": _safe_round(last_return, 6),
        "regime": regime,
    }
    return row, None


# --------------------------------------------------------------------------- #
# Envelope assembly -- exactly payload A from BOCPD_CONTRACT.md.
# --------------------------------------------------------------------------- #
def build_payload(
    symbols: list[str],
    *,
    lookback_days: int,
    lambda_gap: float,
    prior_a: float,
    prior_b: float,
    workers: int,
) -> tuple[dict, list[tuple[str, str]]]:
    """Returns (payload, skipped) where skipped is [(symbol, reason), ...]."""
    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []

    n_workers = max(1, min(workers, len(symbols) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(
                _process_symbol,
                sym,
                lookback_days=lookback_days,
                lambda_gap=lambda_gap,
                prior_a=prior_a,
                prior_b=prior_b,
            ): sym
            for sym in symbols
        }
        for fut in concurrent.futures.as_completed(futures):
            sym = futures[fut]
            try:
                row, err = fut.result()
            except Exception as e:  # noqa: BLE001 - a worker must never kill the run
                row, err = None, f"unhandled exception: {type(e).__name__}: {e}"
            if row is None:
                reason = err or "unknown failure"
                skipped.append((sym, reason))
                print(f"[skip] {sym}: {reason}", file=sys.stderr)
            else:
                rows.append(row)

    rows.sort(key=lambda r: (-float(r["break_prob"] or 0.0), r["symbol"]))

    asof = max((r["last_date"] for r in rows), default=None)
    if asof is None:
        asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "available": True,
        "reason": None,
        "generated_at": _utc_now_iso(),
        "source": f"runs/changepoints/{asof}.json",
        "asof": asof,
        "model": {
            "observation": "gaussian_variance",
            "hazard": "constant",
            "lambda_gap": lambda_gap,
            "prior": {"a": prior_a, "b": prior_b},
            "truncation_mass": TRUNCATION_MASS,
            "reference": REFERENCE,
        },
        "thresholds": {"break": BREAK_THRESHOLD, "settling": SETTLING_RUNS},
        "n_symbols": len(rows),
        "lookback_days": lookback_days,
        "symbols": rows,
        # Additive bookkeeping beyond BOCPD_CONTRACT.md's minimum payload A
        # shape (that file's schema is not marked closed/exhaustive and the
        # task brief instructs recording the skip count -- these are extra
        # keys, not renames or removals of anything the contract specifies,
        # so a strict reader of the pinned fields is unaffected).
        "n_requested": len(symbols),
        "n_skipped": len(skipped),
        "skipped": [{"symbol": s, "reason": r} for s, r in skipped],
    }
    return payload, skipped


# --------------------------------------------------------------------------- #
# stdout summary.
# --------------------------------------------------------------------------- #
def _print_summary(payload: dict, skipped: list[tuple[str, str]]) -> None:
    rows = payload["symbols"]
    print(f"asof          : {payload['asof']}")
    print(f"n_symbols     : {payload['n_symbols']}  (requested {payload['n_requested']}, skipped {len(skipped)})")
    print(f"lookback_days : {payload['lookback_days']}")
    print(f"model         : lambda_gap={payload['model']['lambda_gap']} "
          f"a={payload['model']['prior']['a']} b={payload['model']['prior']['b']}")
    if skipped:
        print("skipped:")
        for sym, reason in skipped[:20]:
            print(f"  {sym}: {reason}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["regime"]] = counts.get(r["regime"], 0) + 1
    print(f"regimes       : {counts}")
    print("top by break_prob:")
    print("  symbol   break_prob  break_prob_20  pred_vol   map_run   regime     last_date")
    for r in rows[:10]:
        pv = r["predictive_vol"]
        pv_str = f"{pv:.4f}" if pv is not None else "null  "
        print(
            f"  {r['symbol']:<8} {r['break_prob']:.4f}      {r['break_prob_20']:.4f}         "
            f"{pv_str}    {r['map_run_length']:<8} {r['regime']:<9}  {r['last_date']}"
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", type=str, default=None, help="comma-separated symbol list (overrides --universe)")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH, help="universe JSON with a 'symbols' key")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="most recent N bars fed into BOCPD per symbol")
    parser.add_argument("--lambda-gap", type=float, default=DEFAULT_LAMBDA_GAP, help="hazard geometric gap prior (H = 1/lambda_gap)")
    parser.add_argument("--prior-a", type=float, default=DEFAULT_PRIOR_A, help="Gamma prior shape on the inverse variance")
    parser.add_argument("--prior-b", type=float, default=DEFAULT_PRIOR_B, help="Gamma prior rate on the inverse variance")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of symbols processed (smoke testing)")
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_ROOT, help="output root (default: edge/runs/changepoints)")
    parser.add_argument("--workers", type=int, default=8, help="thread pool size for per-symbol BOCPD runs")
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = _load_universe(args.universe)
    # De-dupe while preserving first-seen order.
    seen: set[str] = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]
    if args.limit is not None:
        symbols = symbols[: max(0, args.limit)]
    if not symbols:
        print("no symbols to process", file=sys.stderr)
        return 1

    t0 = time.time()
    payload, skipped = build_payload(
        symbols,
        lookback_days=args.lookback_days,
        lambda_gap=args.lambda_gap,
        prior_a=args.prior_a,
        prior_b=args.prior_b,
        workers=args.workers,
    )
    elapsed = time.time() - t0

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dated_path = out_dir / f"{payload['asof']}.json"
    latest_path = out_dir / "latest.json"
    body = json.dumps(payload, indent=2, allow_nan=False)
    dated_path.write_text(body, encoding="utf-8")
    latest_path.write_text(body, encoding="utf-8")

    print(f"processed {len(symbols)} symbols in {elapsed:.1f}s "
          f"({len(payload['symbols'])} ok, {len(skipped)} skipped)")
    print()
    _print_summary(payload, skipped)
    print(f"\nwrote {dated_path}")
    print(f"wrote {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
