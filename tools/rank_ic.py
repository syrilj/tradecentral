#!/usr/bin/env python3
"""Cross-sectional Rank IC / ICIR for a v90-class bundle. Negative control.

Usage (from alltrading/):
  python3 edge/tools/rank_ic.py                              # v90_wide, its own holdout
  python3 edge/tools/rank_ic.py --model edge/models/v90
  python3 edge/tools/rank_ic.py --horizon 8 --min-symbols 20

Why this exists
---------------
`edge/` evaluates models with win-rate / expectancy *at a chosen threshold*. That
is a late, lossy statistic: it collapses the whole prediction distribution to one
bit, and it can only be read after an operating point is picked. Rank IC asks a
cheaper and strictly prior question -- "does this score rank symbols in the order
their forward returns actually arrive?" -- using every sample and no threshold.

This tool is a **negative control**: v90_wide already failed its pre-registered
gate (docs/GATE_RESULT.md, NO-GO). Measuring its Rank IC establishes what "no
cross-sectional signal" reads like on this exact data, so the number produced by
the Qlib cross-sectional experiment (docs/GATE_XS.md) can be compared against a
known-failed baseline rather than against an abstract threshold.

Honest limits
-------------
  - v90 was trained on **triple-barrier** labels (TP/SL = +/-1.0*ATR, 8-bar time
    exit), not on plain H-bar forward return. Rank IC here is measured against
    plain forward return because that is the Qlib-native label the new
    experiment will use. A near-zero result is therefore evidence about
    *cross-sectional ranking power*, not proof the model fails at its own
    objective -- results.json already covers the latter.
  - Scores are read at bar t from features built on data <= close(t); the
    forward return spans close(t) -> close(t+H). No overlap, but consecutive
    bars overlap each other, so the IC series is autocorrelated and the naive
    t-stat below is optimistic. It is reported with a Newey-West correction
    alongside the naive one.
  - Reads bundles read-only. Writes nothing outside edge/runs/.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"

DEFAULT_MODEL = EDGE / "models" / "v90_wide"
DEFAULT_DATA = EDGE / "data" / "1h"
DEFAULT_OUT = EDGE / "runs" / "v90_wide_ic.json"
DEFAULT_PREDS = EDGE / "runs" / "v90_wide_preds.parquet"

N_QUANTILES = 5


# --------------------------------------------------------------------------- #
# bundle loading (mirrors SignalEngine's loader so we score with the bundle's
# own frozen features.py, never edge/models/v90/features.py by accident)
# --------------------------------------------------------------------------- #
def _resolve(p: Path) -> Optional[Path]:
    """Accept a path relative to alltrading/, to edge/, or to cwd.

    ``--model models/v90_wide`` and ``--model edge/models/v90_wide`` both mean
    the same thing to anyone typing them; only one used to work.
    """
    if p.is_absolute():
        return p if p.exists() else None
    for base in (ROOT, EDGE, Path.cwd()):
        cand = base / p
        if cand.exists():
            return cand
    return None


def _rel(p: Path) -> str:
    """Display path, relative to alltrading/ when it lives there."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _load_features_module(model_dir: Path):
    path = model_dir / "features.py"
    if not path.exists():
        raise FileNotFoundError(f"no features.py in {model_dir}")
    name = f"rank_ic_features_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_booster(path: Path):
    import xgboost as xgb

    if not path.exists():
        raise FileNotFoundError(f"missing booster {path}")
    b = xgb.Booster()
    b.load_model(str(path))
    return b


def _predict(booster, feats: pd.DataFrame) -> np.ndarray:
    import xgboost as xgb

    dm = xgb.DMatrix(feats.to_numpy(dtype=float), feature_names=list(feats.columns))
    return np.asarray(booster.predict(dm), dtype=float)


def _contract(model_dir: Path) -> Dict[str, object]:
    """Holdout window + horizon as recorded by the bundle itself."""
    p = model_dir / "results.json"
    if not p.exists():
        return {}
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")).get("contract", {}))
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score_universe(
    model_dir: Path,
    data_dir: Path,
    horizon: int,
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
) -> Tuple[pd.DataFrame, List[str]]:
    """Tidy (timestamp, symbol, raw_long, raw_short, signed, fwd_ret) frame."""
    feat_mod = _load_features_module(model_dir)
    long_b = _load_booster(model_dir / "meta_xgb_long.json")
    short_b = _load_booster(model_dir / "meta_xgb_short.json")

    frames: List[pd.DataFrame] = []
    skipped: List[str] = []

    for path in sorted(data_dir.glob("*.parquet")):
        symbol = path.stem
        df = pd.read_parquet(path)
        if df.empty or len(df) < 250:
            skipped.append(f"{symbol}: only {len(df)} bars")
            continue
        df = df.sort_index()

        # Forward return is computed on the FULL series first, so a bar near the
        # window edge still gets its true forward return instead of a NaN.
        close = df["close"].astype(float)
        fwd = close.shift(-horizon) / close - 1.0

        feats = feat_mod.build_features(df)
        valid = feats.notna().all(axis=1) & fwd.notna()
        if not valid.any():
            skipped.append(f"{symbol}: no valid rows")
            continue

        fv = feats[valid]
        raw_long = _predict(long_b, fv)
        raw_short = _predict(short_b, fv)

        frames.append(
            pd.DataFrame(
                {
                    "timestamp": fv.index,
                    "symbol": symbol,
                    "raw_long": raw_long,
                    "raw_short": raw_short,
                    "signed": raw_long - raw_short,
                    "fwd_ret": fwd[valid].to_numpy(dtype=float),
                }
            )
        )

    if not frames:
        raise RuntimeError(f"no symbols scored from {data_dir}")

    out = pd.concat(frames, ignore_index=True)
    # Window is applied AFTER forward returns exist, so the holdout is exact.
    if start is not None:
        out = out[out["timestamp"] >= start]
    if end is not None:
        out = out[out["timestamp"] <= end]
    return out.reset_index(drop=True), skipped


# --------------------------------------------------------------------------- #
# IC
# --------------------------------------------------------------------------- #
def _spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman == Pearson on ranks. Avoids a scipy dependency."""
    if len(a) < 3:
        return float("nan")
    ra, rb = a.rank(), b.rank()
    sa, sb = ra.std(), rb.std()
    if not np.isfinite(sa) or not np.isfinite(sb) or sa == 0 or sb == 0:
        return float("nan")
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb) * len(a) / (len(a) - 1))


def _newey_west_tstat(x: np.ndarray, lags: int) -> float:
    """t-stat on mean(x) robust to the overlap-induced autocorrelation."""
    n = len(x)
    if n < 3:
        return float("nan")
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for lag in range(1, min(lags, n - 1) + 1):
        cov = (e[lag:] @ e[:-lag]) / n
        var += 2.0 * (1.0 - lag / (lags + 1.0)) * cov
    if var <= 0:
        return float("nan")
    return float(mu / np.sqrt(var / n))


def ic_report(df: pd.DataFrame, score_col: str, min_symbols: int, horizon: int) -> Dict[str, object]:
    ics: List[float] = []
    widths: List[int] = []
    for _, g in df.groupby("timestamp", sort=True):
        if len(g) < min_symbols:
            continue
        ic = _spearman(g[score_col], g["fwd_ret"])
        if np.isfinite(ic):
            ics.append(ic)
            widths.append(len(g))

    if len(ics) < 3:
        return {"score": score_col, "n_bars": len(ics), "error": "too few usable bars"}

    arr = np.asarray(ics, dtype=float)
    mean, std = float(arr.mean()), float(arr.std(ddof=1))
    icir = mean / std if std > 0 else float("nan")
    naive_t = icir * np.sqrt(len(arr)) if np.isfinite(icir) else float("nan")

    # Quantile spread: does the score order forward returns monotonically?
    wide = df.groupby("timestamp").filter(lambda g: len(g) >= max(min_symbols, N_QUANTILES))
    qmeans: Dict[str, float] = {}
    if not wide.empty:
        buckets = wide.groupby("timestamp")[score_col].transform(
            lambda s: pd.qcut(s.rank(method="first"), N_QUANTILES, labels=False)
        )
        for q, sub in wide["fwd_ret"].groupby(buckets):
            qmeans[f"q{int(q) + 1}"] = float(sub.mean())

    return {
        "score": score_col,
        "n_bars": len(arr),
        "avg_symbols_per_bar": float(np.mean(widths)),
        "mean_ic": mean,
        "std_ic": std,
        "icir": icir,
        "t_stat_naive": float(naive_t),
        "t_stat_newey_west": _newey_west_tstat(arr, lags=horizon),
        "pct_bars_positive": float((arr > 0).mean()),
        "quantile_mean_fwd_ret": qmeans,
        "quantile_spread_top_minus_bottom": (
            float(qmeans.get(f"q{N_QUANTILES}", np.nan) - qmeans.get("q1", np.nan)) if qmeans else None
        ),
    }


# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="model bundle dir")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="dir of per-symbol parquet")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON report path")
    ap.add_argument("--preds", type=Path, default=DEFAULT_PREDS, help="tidy predictions parquet")
    ap.add_argument("--horizon", type=int, default=None, help="forward bars (default: bundle contract)")
    ap.add_argument("--start", type=str, default=None, help="window start (default: bundle holdout)")
    ap.add_argument("--end", type=str, default=None, help="window end (default: bundle holdout)")
    ap.add_argument("--min-symbols", type=int, default=10, help="min cross-section width per bar")
    args = ap.parse_args(argv)

    model_dir = _resolve(args.model)
    data_dir = _resolve(args.data)
    if model_dir is None:
        print(f"ERROR: model dir not found: {args.model} (tried {ROOT}, {EDGE}, and cwd)", file=sys.stderr)
        return 2
    if data_dir is None:
        print(f"ERROR: data dir not found: {args.data} (tried {ROOT}, {EDGE}, and cwd)", file=sys.stderr)
        return 2

    out_path = args.out if args.out.is_absolute() else (Path.cwd() / args.out)
    preds_path = args.preds if args.preds.is_absolute() else (Path.cwd() / args.preds)

    contract = _contract(model_dir)
    horizon = args.horizon if args.horizon is not None else int(contract.get("horizon_bars", 8))
    hw = contract.get("holdout_window") or [None, None]
    start = pd.Timestamp(args.start or hw[0]) if (args.start or hw[0]) else None
    end = pd.Timestamp(args.end or hw[1]) if (args.end or hw[1]) else None

    print(f"model    : {_rel(model_dir)}")
    print(f"data     : {_rel(data_dir)}")
    print(f"window   : {start} -> {end}   horizon={horizon} bars")

    df, skipped = score_universe(model_dir, data_dir, horizon, start, end)
    if df.empty:
        print("ERROR: no rows in window", file=sys.stderr)
        return 1

    preds_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(preds_path, index=False)

    n_sym = df["symbol"].nunique()
    n_bars = df["timestamp"].nunique()
    print(f"scored   : {len(df):,} rows / {n_sym} symbols / {n_bars:,} bars")
    if skipped:
        print(f"skipped  : {len(skipped)} -> {'; '.join(skipped[:4])}{' ...' if len(skipped) > 4 else ''}")

    reports = [ic_report(df, c, args.min_symbols, horizon) for c in ("raw_long", "signed")]

    payload = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "model": _rel(model_dir),
        "data": _rel(data_dir),
        "window": [str(start), str(end)],
        "horizon_bars": horizon,
        "label": "plain forward return close(t)->close(t+H); NOT the triple-barrier label v90 trained on",
        "n_symbols": int(n_sym),
        "n_bars": int(n_bars),
        "n_rows": int(len(df)),
        "min_symbols_per_bar": args.min_symbols,
        "skipped_symbols": skipped,
        "reports": reports,
        "note": (
            "Negative control for docs/GATE_XS.md. v90_wide already failed its "
            "pre-registered gate (docs/GATE_RESULT.md). Overlapping horizons make "
            "t_stat_naive optimistic; prefer t_stat_newey_west."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for r in reports:
        print(f"\n--- {r['score']} ---")
        if "error" in r:
            print(f"  {r['error']}")
            continue
        print(f"  mean Rank IC : {r['mean_ic']:+.5f}")
        print(f"  Rank ICIR    : {r['icir']:+.4f}")
        print(f"  t (naive)    : {r['t_stat_naive']:+.2f}")
        print(f"  t (NW)       : {r['t_stat_newey_west']:+.2f}")
        print(f"  bars IC>0    : {r['pct_bars_positive']:.1%}  over {r['n_bars']:,} bars")
        if r["quantile_mean_fwd_ret"]:
            q = "  ".join(f"{k}={v:+.4%}" for k, v in sorted(r["quantile_mean_fwd_ret"].items()))
            print(f"  quintiles    : {q}")
            print(f"  top-bottom   : {r['quantile_spread_top_minus_bottom']:+.4%}")

    print(f"\nwrote {_rel(out_path)}")
    print(f"wrote {_rel(preds_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
