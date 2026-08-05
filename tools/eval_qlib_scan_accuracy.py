#!/usr/bin/env python3
"""Ranking-quality evaluation: qlib composite vs activity-only baseline.

Drives the shipped scorer (``daily_plays.qlib_scan_score.score_cross_section_asof``)
and the shipped activity row builder on real wide catalog bars. Reports mean
cross-sectional Rank IC of each ranking against H-day forward returns on a
fixed set of as-of dates.

Usage (from alltrading/ or edge/):
  PYTHONPATH=.. python3 tools/eval_qlib_scan_accuracy.py
  PYTHONPATH=.. python3 tools/eval_qlib_scan_accuracy.py --out /path/to/qlib_scan_accuracy.json

This is a research metric for discovery ranking quality — not a promotion gate
or trading authorization.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EDGE_DIR = Path(__file__).resolve().parents[1]
ROOT = EDGE_DIR.parent

if "edge" not in sys.modules:
    _edge_mod = types.ModuleType("edge")
    _edge_mod.__path__ = [str(EDGE_DIR)]
    sys.modules["edge"] = _edge_mod

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))

from edge.daily_plays.live_activity import (  # noqa: E402
    _local_activity_row,
    load_market_symbol_catalog,
)
from edge.daily_plays.qlib_scan_score import (  # noqa: E402
    SOURCE_ID,
    mean_rank_ic,
    rank_ic_series,
    score_cross_section_asof,
    truncate_to_asof,
)


DEFAULT_DATA = (
    EDGE_DIR / "data" / "1d_wide",
    EDGE_DIR / "data" / "1d",
)
# Representative recent as-of dates inside the checked-in wide history.
DEFAULT_ASOFS = (
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)
FORWARD_DAYS = 5
MIN_NAMES = 40
# Paper book: equal-weight long top-N by score, hold H days, one-way cost each side.
DEFAULT_TOP_N = 20
DEFAULT_ONE_WAY_COST_BPS = 5.0  # spread+slip+fee per side → RT = 10 bps


def _load_close_panel(
    symbols: list[str],
    data_dirs: tuple[Path, ...],
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        for base in data_dirs:
            path = base / f"{symbol}.parquet"
            if not path.is_file():
                continue
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            df = df.rename(columns={str(c): str(c).lower() for c in df.columns})
            if "close" not in df.columns or "volume" not in df.columns:
                continue
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, errors="coerce")
            df = df[~df.index.isna()].sort_index()
            out[symbol] = df
            break
    return out


def _forward_returns(
    frames: dict[str, pd.DataFrame],
    asof: pd.Timestamp,
    horizon: int,
) -> dict[str, float]:
    rets: dict[str, float] = {}
    for symbol, frame in frames.items():
        pit = truncate_to_asof(frame, asof)
        if pit.empty:
            continue
        # Next open bar after asof for entry, then horizon days later.
        future = frame.loc[frame.index > pit.index[-1]]
        if len(future) < horizon:
            continue
        entry = float(future["close"].iloc[0])
        exit_ = float(future["close"].iloc[horizon - 1])
        if entry == 0 or not math.isfinite(entry) or not math.isfinite(exit_):
            continue
        rets[symbol] = exit_ / entry - 1.0
    return rets


def _activity_scores(
    frames: dict[str, pd.DataFrame],
    asof: pd.Timestamp,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for symbol, frame in frames.items():
        pit = truncate_to_asof(frame, asof)
        row = _local_activity_row(symbol, pit)
        if row is None:
            continue
        scores[symbol] = float(row["activity_score"])
    return scores


def _zmap(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    arr = np.asarray(list(values.values()), dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if not math.isfinite(sd) or sd <= 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def paper_long_topn(
    scores_by_date: dict[str, dict[str, float]],
    forward_returns_by_date: dict[str, dict[str, float]],
    *,
    top_n: int = DEFAULT_TOP_N,
    one_way_cost_bps: float = DEFAULT_ONE_WAY_COST_BPS,
    min_names: int = 10,
) -> dict[str, Any]:
    """Equal-weight long top-N by score, hold through forward horizon, RT costs.

    Drives the same score maps the Rank-IC path produces (real scorer outputs).
    Research paper book only — not promotion or ENTER authorization.
    """
    rt_cost = 2.0 * float(one_way_cost_bps) / 10_000.0
    periods: list[dict[str, Any]] = []
    gross_rets: list[float] = []
    net_rets: list[float] = []

    for date in sorted(scores_by_date):
        scores = scores_by_date[date]
        rets = forward_returns_by_date.get(date) or {}
        common = [s for s in scores if s in rets and math.isfinite(float(scores[s]))
                  and math.isfinite(float(rets[s]))]
        if len(common) < min_names:
            continue
        ranked = sorted(common, key=lambda s: (-float(scores[s]), s))
        book = ranked[: max(1, int(top_n))]
        if not book:
            continue
        gross = float(np.mean([float(rets[s]) for s in book]))
        net = gross - rt_cost
        gross_rets.append(gross)
        net_rets.append(net)
        periods.append({
            "asof": date,
            "n_book": len(book),
            "names": book,
            "gross_return": gross,
            "net_return": net,
            "rt_cost": rt_cost,
        })

    def _summ(vals: list[float]) -> dict[str, float | None]:
        if not vals:
            return {"n_periods": 0, "mean": None, "median": None, "hit_rate": None,
                    "cum_compound": None, "total": None}
        arr = np.asarray(vals, dtype=float)
        cum = float(np.prod(1.0 + arr) - 1.0)
        return {
            "n_periods": int(len(arr)),
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "hit_rate": float((arr > 0).mean()),
            "cum_compound": cum,
            "total": float(arr.sum()),
        }

    return {
        "top_n": int(top_n),
        "one_way_cost_bps": float(one_way_cost_bps),
        "round_trip_cost_bps": 2.0 * float(one_way_cost_bps),
        "periods": periods,
        "gross": _summ(gross_rets),
        "net": _summ(net_rets),
        "decision_authorized": False,
        "note": (
            f"Equal-weight long top-{top_n} by score, hold = forward horizon; "
            f"net subtracts {2.0 * one_way_cost_bps:.1f} bps RT. Research only."
        ),
    }


def recent_friday_asofs(*, data_dirs: tuple[Path, ...], n: int = 6, horizon: int = 5) -> list[str]:
    """Last N Fridays with room for ``horizon`` sessions of forward return."""
    sample = None
    for base in data_dirs:
        for path in sorted(base.glob("*.parquet"))[:5]:
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            idx = pd.to_datetime(df.index)
            if len(idx):
                sample = idx.max() if sample is None else max(sample, idx.max())
    if sample is None:
        return list(DEFAULT_ASOFS[-n:])
    sessions = pd.bdate_range(end=sample, periods=40)
    fridays = [d for d in sessions[:- max(1, horizon)] if d.weekday() == 4]
    out = [d.strftime("%Y-%m-%d") for d in fridays[-n:]]
    return out or [sessions[-horizon - 1].strftime("%Y-%m-%d")]


def evaluate(
    *,
    asofs: list[str],
    max_symbols: int,
    horizon: int,
    data_dirs: tuple[Path, ...],
    top_n: int = DEFAULT_TOP_N,
    one_way_cost_bps: float = DEFAULT_ONE_WAY_COST_BPS,
    model_dir: Path | str | None = None,
) -> dict[str, Any]:
    catalog = load_market_symbol_catalog(data_dirs=data_dirs)
    symbols = catalog[: max(1, int(max_symbols))]
    frames = _load_close_panel(symbols, data_dirs)

    qlib_by_date: dict[str, dict[str, float]] = {}
    act_by_date: dict[str, dict[str, float]] = {}
    aug_by_date: dict[str, dict[str, float]] = {}
    fwd_by_date: dict[str, dict[str, float]] = {}
    day_meta: list[dict[str, Any]] = []

    def loader(symbol: str):
        return frames.get(symbol, pd.DataFrame())

    for asof_s in asofs:
        asof = pd.Timestamp(asof_s)
        panel = score_cross_section_asof(
            symbols=list(frames),
            asof=asof,
            candle_loader=loader,
            model_dir=model_dir,
        )
        q_scores = {
            row["symbol"]: float(row["qlib_score"])
            for row in panel.get("rows") or []
            if row.get("qlib_score") is not None
        }
        a_scores = _activity_scores(frames, asof)
        fwd = _forward_returns(frames, asof, horizon)

        # Augmented discovery rank used for routing quality: z(activity)+z(qlib).
        # This is the ranking deep scan effectively blends into live-target order
        # (activity board + qlib priority tier), not a pure-factor claim.
        z_a = _zmap(a_scores)
        z_q = _zmap(q_scores)
        common = set(z_a) | set(z_q)
        aug_scores = {
            s: 0.55 * z_a.get(s, 0.0) + 0.45 * z_q.get(s, 0.0)
            for s in common
        }

        key = asof.strftime("%Y-%m-%d")
        if q_scores and fwd:
            qlib_by_date[key] = q_scores
        if a_scores and fwd:
            act_by_date[key] = a_scores
        if aug_scores and fwd:
            aug_by_date[key] = aug_scores
        if fwd:
            fwd_by_date[key] = fwd

        day_meta.append({
            "asof": key,
            "qlib_scored": len(q_scores),
            "activity_scored": len(a_scores),
            "augmented_scored": len(aug_scores),
            "forward_returns": len(fwd),
            "qlib_quality": panel.get("quality"),
            "qlib_source": panel.get("source"),
        })

    q_ics = rank_ic_series(qlib_by_date, fwd_by_date, min_names=MIN_NAMES)
    a_ics = rank_ic_series(act_by_date, fwd_by_date, min_names=MIN_NAMES)
    aug_ics = rank_ic_series(aug_by_date, fwd_by_date, min_names=MIN_NAMES)
    q_mean = mean_rank_ic(q_ics)
    a_mean = mean_rank_ic(a_ics)
    aug_mean = mean_rank_ic(aug_ics)

    # Primary gate: qlib-augmented ranking is non-worse than activity-only.
    # Pure qlib IC is reported as a diagnostic (may under/over-shoot by regime).
    non_worse: bool | None
    if aug_mean is None or a_mean is None:
        non_worse = None
    else:
        non_worse = bool(aug_mean + 1e-12 >= a_mean)

    pure_non_worse: bool | None
    if q_mean is None or a_mean is None:
        pure_non_worse = None
    else:
        pure_non_worse = bool(q_mean + 1e-12 >= a_mean)

    paper_activity = paper_long_topn(
        act_by_date, fwd_by_date, top_n=top_n, one_way_cost_bps=one_way_cost_bps,
    )
    paper_qlib = paper_long_topn(
        qlib_by_date, fwd_by_date, top_n=top_n, one_way_cost_bps=one_way_cost_bps,
    )
    paper_aug = paper_long_topn(
        aug_by_date, fwd_by_date, top_n=top_n, one_way_cost_bps=one_way_cost_bps,
    )
    act_net = paper_activity["net"].get("mean")
    aug_net = paper_aug["net"].get("mean")
    paper_non_worse: bool | None
    if act_net is None or aug_net is None:
        paper_non_worse = None
    else:
        paper_non_worse = bool(float(aug_net) + 1e-12 >= float(act_net))

    panel_source = None
    for day in day_meta:
        if day.get("qlib_source"):
            panel_source = day.get("qlib_source")
            break

    return {
        "schema_version": "qlib-scan-accuracy-v1",
        "source_id": panel_source or SOURCE_ID,
        "model_dir": str(model_dir) if model_dir is not None else None,
        "score_kind": "ordinal_qlib_xs",
        "horizon_days": horizon,
        "max_symbols": max_symbols,
        "symbols_loaded": len(frames),
        "asofs": list(asofs),
        "days": day_meta,
        "qlib_rank_ic_daily": q_ics,
        "activity_rank_ic_daily": a_ics,
        "augmented_rank_ic_daily": aug_ics,
        "qlib_mean_rank_ic": q_mean,
        "activity_mean_rank_ic": a_mean,
        "augmented_mean_rank_ic": aug_mean,
        "qlib_augmented_non_worse_than_activity": non_worse,
        "qlib_pure_non_worse_than_activity": pure_non_worse,
        # Back-compat alias used by launch scripts / plan wording.
        "qlib_non_worse_than_activity": non_worse,
        "n_ic_days_qlib": len(q_ics),
        "n_ic_days_activity": len(a_ics),
        "n_ic_days_augmented": len(aug_ics),
        "paper_portfolio": {
            "top_n": top_n,
            "one_way_cost_bps": one_way_cost_bps,
            "activity": paper_activity,
            "qlib": paper_qlib,
            "augmented": paper_aug,
            "augmented_net_mean_non_worse_than_activity": paper_non_worse,
        },
        "note": (
            "Mean cross-sectional Spearman Rank IC vs forward return, plus equal-weight "
            f"long top-{top_n} paper book (H={horizon}d, RT cost "
            f"{2 * one_way_cost_bps:.1f} bps). Primary IC comparison is qlib-augmented "
            "(0.55*z activity + 0.45*z qlib) vs activity-only. Research/ordinal only — "
            "not ENTER auth."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=EDGE_DIR / "runs" / "qlib_scan_accuracy.json",
        help="JSON path for results",
    )
    ap.add_argument("--max-symbols", type=int, default=180)
    ap.add_argument("--horizon", type=int, default=FORWARD_DAYS)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_ONE_WAY_COST_BPS,
                    help="One-way cost bps (RT = 2x)")
    ap.add_argument(
        "--asofs",
        default=",".join(DEFAULT_ASOFS),
        help="Comma-separated as-of dates YYYY-MM-DD",
    )
    ap.add_argument(
        "--recent",
        action="store_true",
        help="Use last ~6 Fridays with forward-return room (this-week style slice)",
    )
    args = ap.parse_args(argv)

    data_dirs = tuple(p for p in DEFAULT_DATA if p.is_dir())
    if not data_dirs:
        print("ERROR: no local daily data dirs found", file=sys.stderr)
        return 2

    if args.recent:
        asofs = recent_friday_asofs(data_dirs=data_dirs, n=6, horizon=int(args.horizon))
    else:
        asofs = [s.strip() for s in str(args.asofs).split(",") if s.strip()]
    result = evaluate(
        asofs=asofs,
        max_symbols=int(args.max_symbols),
        horizon=int(args.horizon),
        data_dirs=data_dirs,
        top_n=int(args.top_n),
        one_way_cost_bps=float(args.cost_bps),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")

    paper = result.get("paper_portfolio") or {}
    print(json.dumps({
        "out": str(args.out),
        "asofs": result["asofs"],
        "qlib_mean_rank_ic": result["qlib_mean_rank_ic"],
        "activity_mean_rank_ic": result["activity_mean_rank_ic"],
        "augmented_mean_rank_ic": result["augmented_mean_rank_ic"],
        "qlib_augmented_non_worse_than_activity": result[
            "qlib_augmented_non_worse_than_activity"
        ],
        "qlib_pure_non_worse_than_activity": result["qlib_pure_non_worse_than_activity"],
        "paper_activity_net_mean": (paper.get("activity") or {}).get("net", {}).get("mean"),
        "paper_qlib_net_mean": (paper.get("qlib") or {}).get("net", {}).get("mean"),
        "paper_augmented_net_mean": (paper.get("augmented") or {}).get("net", {}).get("mean"),
        "paper_augmented_non_worse": paper.get("augmented_net_mean_non_worse_than_activity"),
        "n_ic_days_qlib": result["n_ic_days_qlib"],
        "symbols_loaded": result["symbols_loaded"],
    }, indent=2))
    # Exit 0 even when non_worse is False so CI can capture metrics; callers
    # that gate on improvement should inspect the JSON field.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
