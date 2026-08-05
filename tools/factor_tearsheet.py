#!/usr/bin/env python3
"""Factor tearsheet CLI: does a signal survive long enough to be rebalanced cheaply?

`edge/research/factor_diagnostics.py` answers a structural question about a
cross-sectional signal (is the edge a real ranking or a lucky tail?) once it
is handed a `(scores, close)` panel. This tool is the thing that hands it a
real one: it loads real daily bars from `edge/data/1d_wide`, derives a
cross-sectional score from them (or from the frozen `qlib_xs4` cross-sectional
model), and writes the resulting `FactorTearsheet` to disk in the envelope
shape `tools/api_server.py`'s dashboard endpoint expects.

Per `edge/README.md`, the binding constraints on turning a signal into a live
book are turnover and universe construction, not raw predictive power -- a
signal with a respectable mean IC that is not monotone across quantiles, or
that is monotone but churns its top/bottom bucket every bar, is not tradeable
at the costs this repo assumes (`DEFAULT_COST_PER_SIDE` /
`round_trip_cost_bps` throughout `research/`). This tool exists to make that
distinction visible from real data on the command line, not just as an
abstract property of `factor_diagnostics.py`'s unit tests.

What this tool must NOT touch
------------------------------
`edge/research/directional_bakeoff.py` defines `terminal_holdout_start =
"2026-07-13"` as a sealed prospective holdout: no research artifact in this
repo is allowed to read data at or after that date until a separate
promotion process says otherwise. `--end` defaults to the day before that
seal and `_resolve_window` raises (does not clamp) if `--start`/`--end` would
cross it -- the same "raise, don't silently degrade" contract
`edge/tools/data_sources.py`'s module docstring documents for data loaders in
general. The effective date range actually used is always printed to stdout.

Data layout note
-----------------
`edge/research/daily_data.py::DEFAULT_DAILY_DATA_DIR` points at
`edge/data/1d`, a 60-symbol curated universe matching
`config/universe_directional_v2.json`. This tool instead points the same
loader (`load_daily_universe`, reused verbatim -- no new loader is written
here) at `edge/data/1d_wide`, a 557-symbol per-symbol-parquet directory (the
"wide" in the name refers to universe breadth, not file shape: it is still
one parquet per symbol, identical schema to `data/1d`, not a single
date-by-symbol matrix). `1d_wide` is the directory that actually contains
every instrument scored by the frozen `qlib_xs4` cross-sectional experiment,
which is what makes `--signal qlib_xs` possible at all; `data/1d` does not
cover that universe. See the module docstring's REPORT section (this file's
author's report to the calling agent) for the exact symbol/date counts found
at inspection time.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.daily_data import load_daily_universe  # noqa: E402
from edge.research.directional_bakeoff import BakeoffProtocol  # noqa: E402
from edge.research.factor_diagnostics import FactorTearsheet, factor_tearsheet  # noqa: E402
from edge.research.features import causal_daily_features  # noqa: E402

DATA_DIR = EDGE_ROOT / "data" / "1d_wide"
OUTPUT_ROOT = EDGE_ROOT / "runs" / "factor_diagnostics"

# The sealed prospective holdout. Read from directional_bakeoff.py's own
# protocol rather than re-declared here, so this tool cannot silently drift
# out of sync with the one place in the repo that owns this date.
_PROTOCOL = BakeoffProtocol()
TERMINAL_HOLDOUT_START = pd.Timestamp(_PROTOCOL.terminal_holdout_start)
DEFAULT_END = TERMINAL_HOLDOUT_START - pd.Timedelta(days=1)

# The frozen qlib cross-sectional experiment this tool will try to load for
# `--signal qlib_xs`. `lgb158` is explicitly labelled "GATE_XS3 frozen
# baseline, reproduced. The number to beat." in its own summary JSON, and of
# the arms recorded across dev_pitwide_{lgb,h1,h2}.json it has the strongest
# (least negative / most positive) mean Rank IC -- see this file's REPORT.
QLIB_XS_RUN_DIR = EDGE_ROOT / "qlib_xs4"
QLIB_XS_SUMMARY = EDGE_ROOT / "runs" / "qlib_xs4" / "dev_pitwide_lgb.json"
QLIB_XS_ARM = "lgb158"

# Cross-sectional signals derived purely from price, all read off
# `causal_daily_features` (never recomputed by hand -- that function is the
# one place in the repo licensed to say "this momentum column is causal").
# Each entry maps a CLI-facing name to (source column, negate).
# `mean_reversion_5d` is literally `-momentum_5d`: a short lookback whose
# *low* raw momentum should, under a reversal hypothesis, rank *high* on
# forward return, which is exactly what negating the column encodes without
# adding any new feature-computation code path.
PRICE_SIGNALS: dict[str, tuple[str, bool]] = {
    "momentum_5d": ("momentum_5d", False),
    "momentum_10d": ("momentum_10d", False),
    "momentum_20d": ("momentum_20d", False),
    "volatility_scaled_momentum_5d": ("volatility_scaled_momentum_5d", False),
    "volatility_scaled_momentum_10d": ("volatility_scaled_momentum_10d", False),
    "volatility_scaled_momentum_20d": ("volatility_scaled_momentum_20d", False),
    "mean_reversion_5d": ("momentum_5d", True),
}
QLIB_SIGNAL = "qlib_xs"
ALL_SIGNALS: tuple[str, ...] = tuple(PRICE_SIGNALS) + (QLIB_SIGNAL,)
DEFAULT_SIGNAL = "momentum_20d"
DEFAULT_QUANTILES = 5
DEFAULT_HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 20)
DEFAULT_EXECUTION_LAG = 1


# --------------------------------------------------------------------------- #
# Window resolution -- the sealed-holdout guard.
# --------------------------------------------------------------------------- #
def _resolve_window(start: str | None, end: str | None) -> tuple[pd.Timestamp | None, pd.Timestamp]:
    """Validate `--start`/`--end` against the sealed terminal holdout.

    Raises rather than clamps: a silently-shortened window is exactly the
    kind of "degrade instead of fail" behaviour `edge/tools/data_sources.py`
    forbids for loaders, and the same discipline applies here to the
    boundary that protects the sealed holdout.
    """
    end_ts = pd.Timestamp(end) if end else DEFAULT_END
    if end_ts >= TERMINAL_HOLDOUT_START:
        raise ValueError(
            f"--end {end_ts.date()} is at or after the sealed terminal holdout "
            f"({TERMINAL_HOLDOUT_START.date()}, "
            "edge.research.directional_bakeoff.BakeoffProtocol.terminal_holdout_start). "
            "This tool must not read data at or after that date -- pass an earlier --end."
        )
    start_ts = pd.Timestamp(start) if start else None
    if start_ts is not None:
        if start_ts >= TERMINAL_HOLDOUT_START:
            raise ValueError(
                f"--start {start_ts.date()} is at or after the sealed terminal holdout "
                f"({TERMINAL_HOLDOUT_START.date()})."
            )
        if start_ts >= end_ts:
            raise ValueError(f"--start {start_ts.date()} must be before --end {end_ts.date()}")
    return start_ts, end_ts


# --------------------------------------------------------------------------- #
# Data loading -- price panel.
# --------------------------------------------------------------------------- #
def _list_symbols(data_dir: Path) -> list[str]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data directory not found: {data_dir}")
    files = sorted(data_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files found under {data_dir}")
    return [f.stem for f in files]


def _load_close(
    symbols: list[str], data_dir: Path, end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(close, bars): wide close panel and the underlying (timestamp, symbol) bars.

    `load_daily_universe` (reused verbatim from `edge/research/daily_data.py`)
    raises on any missing symbol file rather than skipping it -- the house
    rule documented in `edge/tools/data_sources.py`'s module docstring.
    """
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data directory not found: {data_dir}")
    bars = load_daily_universe(symbols, asof=end_ts, data_dir=data_dir)
    close = bars["close"].unstack("symbol").sort_index()
    return close, bars


def _price_scores(signal: str, bars: pd.DataFrame) -> pd.DataFrame:
    column, negate = PRICE_SIGNALS[signal]
    feats = causal_daily_features(bars)
    series = feats[column]
    if negate:
        series = -series
    return series.unstack("symbol").sort_index()


# --------------------------------------------------------------------------- #
# Data loading -- frozen qlib_xs4 cross-sectional signal.
# --------------------------------------------------------------------------- #
def _load_qlib_xs_scores() -> tuple[pd.DataFrame, str]:
    """Load the frozen `qlib_xs4` `lgb158` prediction as a wide (date x symbol) frame.

    Raises with the exact path/reason on any miss. This tool does not
    fabricate a fallback score if the qlib artifact cannot be resolved --
    per the task this file was written to satisfy, an unloadable qlib_xs
    signal must be reported as unloadable, not silently substituted with
    something else under the same `--signal qlib_xs` name.
    """
    if not QLIB_XS_SUMMARY.is_file():
        raise FileNotFoundError(
            f"qlib_xs summary not found at {QLIB_XS_SUMMARY} -- cannot resolve "
            "--signal qlib_xs without it (need the arm's recorder_id)"
        )
    summary = json.loads(QLIB_XS_SUMMARY.read_text(encoding="utf-8"))
    arm = next((r for r in summary.get("results", []) if r.get("arm") == QLIB_XS_ARM), None)
    if arm is None:
        raise ValueError(f"{QLIB_XS_SUMMARY} has no {QLIB_XS_ARM!r} arm result")
    recorder_id = arm.get("recorder_id")
    if not recorder_id:
        raise ValueError(f"{QLIB_XS_SUMMARY} arm {QLIB_XS_ARM!r} has no recorder_id")
    matches = sorted(QLIB_XS_RUN_DIR.glob(f"mlruns/*/{recorder_id}/artifacts/pred.pkl"))
    if not matches:
        raise FileNotFoundError(
            f"no pred.pkl found for recorder_id={recorder_id} under "
            f"{QLIB_XS_RUN_DIR}/mlruns/*/  -- the qlib_xs4 mlflow tracking "
            "directory may have been pruned or moved since dev_pitwide_lgb.json "
            "was generated"
        )
    pred_path = matches[0]
    pred = pd.read_pickle(pred_path)
    if "score" not in pred.columns:
        raise ValueError(f"{pred_path} has no 'score' column: {list(pred.columns)}")
    wide = pred["score"].unstack("instrument").sort_index()
    desc = f"qlib_xs4/{QLIB_XS_ARM} recorder={recorder_id[:8]}"
    return wide, desc


# --------------------------------------------------------------------------- #
# Signal assembly: (scores, close) aligned exactly per factor_diagnostics's contract.
# --------------------------------------------------------------------------- #
def build_signal(
    signal: str, *, start: pd.Timestamp | None, end: pd.Timestamp, data_dir: Path = DATA_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Return `(scores, close, source_description)` for `signal` over `[start, end]`.

    `scores.index` is made to equal `close.index` exactly by construction --
    both are sliced from a single shared date index with the same boolean
    mask -- rather than reconciled after the fact with `.reindex`, which is
    the exact anti-pattern `factor_diagnostics._validate_frames` exists to
    catch (see that function's docstring).
    """
    if signal == QLIB_SIGNAL:
        raw_scores, qlib_desc = _load_qlib_xs_scores()
        mask = raw_scores.index <= end
        if start is not None:
            mask &= raw_scores.index >= start
        raw_scores = raw_scores.loc[mask]
        if raw_scores.empty:
            raise ValueError(
                f"qlib_xs scores are empty after clipping to "
                f"[{start.date() if start is not None else '(none)'}, {end.date()}]"
            )
        symbols = list(raw_scores.columns)
        close_full, _ = _load_close(symbols, data_dir, end)
        missing_dates = raw_scores.index.difference(close_full.index)
        if len(missing_dates):
            raise ValueError(
                f"{len(missing_dates)} qlib_xs score dates have no matching close-price "
                f"row in {data_dir}, e.g. {[str(d.date()) for d in missing_dates[:5]]}"
            )
        close = close_full.loc[raw_scores.index, symbols]
        source = f"{qlib_desc} · {raw_scores.shape[1]} symbols · data/1d_wide"
        return raw_scores, close, source

    if signal not in PRICE_SIGNALS:
        raise ValueError(f"unknown --signal {signal!r}; choose from {', '.join(ALL_SIGNALS)}")

    symbols = _list_symbols(data_dir)
    close_full, bars_full = _load_close(symbols, data_dir, end)
    scores_full = _price_scores(signal, bars_full)
    if start is not None:
        row_mask = close_full.index >= start
        close = close_full.loc[row_mask]
        scores = scores_full.loc[row_mask]
    else:
        close, scores = close_full, scores_full

    if not scores.index.equals(close.index) or not scores.columns.equals(close.columns):
        raise ValueError(
            "internal alignment error: scores and close diverged after slicing "
            "-- this indicates a bug in build_signal, not a data problem"
        )
    source = f"{signal} · {scores.shape[1]} symbols · data/1d_wide"
    return scores, close, source


# --------------------------------------------------------------------------- #
# JSON output -- dashboard envelope + richer per-signal artifact.
# --------------------------------------------------------------------------- #
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def envelope_dict(tearsheet: FactorTearsheet, *, source: str) -> dict[str, Any]:
    """The exact `latest.json` schema `tools/api_server.py`'s dashboard endpoint expects.

    Built entirely from `FactorTearsheet.as_dict()` -- no diagnostic logic is
    duplicated here, only relabelled (`quantile_returns` -> `quantiles`) and
    wrapped with run metadata. `as_dict()` already turns every non-finite
    float into `None`; `json.dumps(..., allow_nan=False)` at the write site
    below is a second, independent guarantee that no `NaN` token can reach
    the file even if that invariant is ever broken upstream.
    """
    d = tearsheet.as_dict()
    return {
        "available": True,
        "reason": None,
        "generated_at": _utc_now_iso(),
        "source": source,
        "n_dates": d["n_dates"],
        "n_symbols": d["n_symbols"],
        "execution_lag": d["execution_lag"],
        "monotonicity": d["monotonicity"],
        "ic_decay": d["ic_decay"],
        "quantiles": d["quantile_returns"],
        "quantile_turnover": d["quantile_turnover"],
    }


def _write_outputs(
    tearsheet: FactorTearsheet,
    *,
    signal: str,
    source: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp,
    out_root: Path,
) -> tuple[Path, Path]:
    envelope = envelope_dict(tearsheet, source=source)
    d = tearsheet.as_dict()
    tearsheet_payload = dict(envelope)
    tearsheet_payload.update(
        {
            "signal": signal,
            "n_quantiles": d["n_quantiles"],
            "horizons": d["horizons"],
            "start": None if start is None else str(start.date()),
            "end": str(end.date()),
        }
    )

    signal_dir = out_root / signal
    signal_dir.mkdir(parents=True, exist_ok=True)
    tearsheet_path = signal_dir / "tearsheet.json"
    tearsheet_path.write_text(
        json.dumps(tearsheet_payload, indent=2, allow_nan=False), encoding="utf-8",
    )

    latest_path = out_root / "latest.json"
    latest_path.write_text(json.dumps(envelope, indent=2, allow_nan=False), encoding="utf-8")
    return tearsheet_path, latest_path


# --------------------------------------------------------------------------- #
# Human-readable stdout summary.
# --------------------------------------------------------------------------- #
def _fmt_pct(value: float | None) -> str:
    return f"{value:+.4%}" if value is not None else "n/a"


def _print_summary(
    tearsheet: FactorTearsheet, *, signal: str, source: str, start: pd.Timestamp | None, end: pd.Timestamp,
) -> None:
    d = tearsheet.as_dict()
    print(f"signal        : {signal}")
    print(f"source        : {source}")
    range_start = start.date() if start is not None else "(full available history)"
    print(f"date range    : {range_start} -> {end.date()}  (sealed holdout starts {TERMINAL_HOLDOUT_START.date()})")
    print(f"n_dates       : {d['n_dates']}   n_symbols: {d['n_symbols']}   n_quantiles: {d['n_quantiles']}")

    ic1 = next((r for r in d["ic_decay"] if r["horizon"] == 1), None)
    if ic1 is not None and ic1["mean_ic"] is not None:
        t = ic1["ic_t_stat"]
        t_str = f"{t:+.2f}" if t is not None else "n/a"
        print(f"mean IC (1d)  : {ic1['mean_ic']:+.4f}  (Newey-West t={t_str}, n={ic1['n_periods']})")
    else:
        print("mean IC (1d)  : n/a")

    longest = None
    for row in d["ic_decay"]:
        t = row["ic_t_stat"]
        if t is not None and abs(t) >= 2.0 and (longest is None or row["horizon"] > longest["horizon"]):
            longest = row
    if longest is not None:
        print(
            f"longest |t|>=2: horizon={longest['horizon']}d "
            f"(mean_ic={longest['mean_ic']:+.4f}, t={longest['ic_t_stat']:+.2f})"
        )
    else:
        print("longest |t|>=2: none of the requested horizons clear |t| >= 2")

    mono = d["monotonicity"]
    print(f"monotonicity  : {mono:+.3f}" if mono is not None else "monotonicity  : n/a")

    print("quantile   mean_return   turnover     n_obs")
    turnover_by_q = {row["quantile"]: row["mean_turnover"] for row in d["quantile_turnover"]}
    for row in d["quantile_returns"]:
        q = row["quantile"]
        label = "spread" if q == -1 else f"Q{q}"
        turn = turnover_by_q.get(q)
        turn_str = f"{turn:.1%}" if turn is not None else "n/a"
        print(f"  {label:>6}   {_fmt_pct(row['mean_return']):>11}   {turn_str:>8}   {row['n_obs']}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--signal", default=DEFAULT_SIGNAL, choices=ALL_SIGNALS, help="cross-sectional score to test")
    parser.add_argument("--quantiles", type=int, default=DEFAULT_QUANTILES, help="number of cross-sectional buckets")
    parser.add_argument("--out", type=Path, default=OUTPUT_ROOT, help="output root (default: edge/runs/factor_diagnostics)")
    parser.add_argument("--start", type=str, default=None, help="window start, e.g. 2020-01-01 (default: full history)")
    parser.add_argument("--end", type=str, default=None, help=f"window end (default: {DEFAULT_END.date()}, the day before the sealed holdout)")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="per-symbol OHLCV parquet directory")
    parser.add_argument("--list", action="store_true", help="print available --signal values and exit; touches no data")
    args = parser.parse_args(argv)

    if args.list:
        print("available --signal values:")
        for name in ALL_SIGNALS:
            marker = " (default)" if name == DEFAULT_SIGNAL else ""
            print(f"  {name}{marker}")
        return 0

    start_ts, end_ts = _resolve_window(args.start, args.end)
    scores, close, source = build_signal(args.signal, start=start_ts, end=end_ts, data_dir=args.data_dir)

    range_start = start_ts.date() if start_ts is not None else close.index.min().date()
    print(
        f"date range used: {range_start} -> {end_ts.date()}  "
        f"(sealed terminal holdout starts {TERMINAL_HOLDOUT_START.date()} and is never read)"
    )

    tearsheet = factor_tearsheet(
        scores=scores, close=close, n_quantiles=args.quantiles,
        horizons=DEFAULT_HORIZONS, execution_lag=DEFAULT_EXECUTION_LAG,
    )

    tearsheet_path, latest_path = _write_outputs(
        tearsheet, signal=args.signal, source=source, start=start_ts, end=end_ts, out_root=args.out,
    )

    print()
    _print_summary(tearsheet, signal=args.signal, source=source, start=start_ts, end=end_ts)
    print(f"\nwrote {tearsheet_path}")
    print(f"wrote {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
