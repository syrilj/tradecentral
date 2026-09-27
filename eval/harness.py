"""
Leak-free walk-forward evaluation harness, ported from Kronos/eval_walkforward.py.
Every row for target index t is derived from df.iloc[t-lb:t]; df.iloc[t] is read
exactly once per row, to record the realized label.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .conformal import calibrate_interval, regime_bucket

__all__ = [
    "PredictFn",
    "WalkForwardConfig",
    "DATE_COL",
    "PRICE_COL",
    "VOLUME_COL",
    "eval_indices",
    "resolve_asof_index",
    "resolve_asof_timestamp",
    "run_walkforward",
]

PredictFn = Callable[[pd.DataFrame], Dict[str, float]]

DATE_COL = "timestamps"
PRICE_COL = "close"
VOLUME_COL = "volume"


@dataclass
class WalkForwardConfig:
    lookback: int = 120
    min_lookback: int = 32
    n_days: Optional[int] = None
    date_col: str = DATE_COL
    price_col: str = PRICE_COL
    volume_col: str = VOLUME_COL
    conformal_warmup: int = 20
    conformal_min_bucket: int = 30


def eval_indices(n: int, min_lookback: int, n_days: Optional[int]) -> List[int]:
    last_idx = n - 1
    first_idx = min_lookback if n_days is None else max(min_lookback, last_idx - n_days + 1)
    return list(range(first_idx, last_idx + 1))


def resolve_asof_index(t: int) -> int:
    """Index of the most recent bar known when forecasting target day t."""
    if t <= 0:
        raise ValueError("t must be >= 1: there is no prior bar for t <= 0")
    return t - 1


def resolve_asof_timestamp(df: pd.DataFrame, t: int, date_col: str = DATE_COL) -> pd.Timestamp:
    """The forecast-origin timestamp for target day t: df.iloc[t-1], never df.iloc[t]."""
    return pd.Timestamp(df.iloc[resolve_asof_index(t)][date_col])


def _dir_hit(pred_ret: float, actual_ret: float) -> int:
    if abs(pred_ret) < 1e-8 and abs(actual_ret) < 1e-8:
        return 1
    return int(np.sign(pred_ret) == np.sign(actual_ret))


def run_walkforward(
    predict_fn: PredictFn,
    df: pd.DataFrame,
    config: Optional[WalkForwardConfig] = None,
) -> List[Dict[str, Any]]:
    cfg = config or WalkForwardConfig()
    n = len(df)
    indices = eval_indices(n, cfg.min_lookback, cfg.n_days)

    rows: List[Dict[str, Any]] = []
    signed_resid_hist: List[float] = []
    bucket_hist: List[str] = []

    for t in indices:
        lb = min(cfg.lookback, t)
        if lb < cfg.min_lookback:
            continue

        hist = df.iloc[t - lb: t].reset_index(drop=True)
        if hist.empty:
            continue

        last_close = float(hist[cfg.price_col].iloc[-1])
        asof_ts = resolve_asof_timestamp(df, t, cfg.date_col)

        pred = predict_fn(hist)
        if not {"p10", "p50", "p90"} <= pred.keys():
            raise KeyError("predict_fn must return a dict with keys p10, p50, p90")
        p10, p50, p90 = float(pred["p10"]), float(pred["p50"]), float(pred["p90"])

        hist_closes = hist[cfg.price_col].to_numpy(dtype=float)
        hist_vols = hist[cfg.volume_col].to_numpy(dtype=float) if cfg.volume_col in hist.columns else None
        bucket = regime_bucket(closes=hist_closes, volumes=hist_vols)
        ci = calibrate_interval(
            p50, last_close, signed_resid_hist,
            buckets=bucket_hist, bucket=bucket,
            warmup=cfg.conformal_warmup, min_bucket=cfg.conformal_min_bucket,
        )

        if t >= 2:
            prev_close = float(df.iloc[t - 2][cfg.price_col])
            persist_ret = float(last_close / prev_close - 1.0) if prev_close else 0.0
        else:
            persist_ret = 0.0

        # The only two reads of df at index t in this whole loop: the realized label.
        target_ts = pd.Timestamp(df.iloc[t][cfg.date_col])
        actual_close = float(df.iloc[t][cfg.price_col])

        actual_ret = float(actual_close / last_close - 1.0) if last_close else 0.0
        pred_ret_p50 = float(p50 / last_close - 1.0) if last_close else 0.0
        dir_hit = _dir_hit(pred_ret_p50, actual_ret)
        persist_hit = _dir_hit(persist_ret, actual_ret)
        in_pi80 = int(p10 <= actual_close <= p90)
        abs_err = abs(p50 - actual_close)

        if ci is not None:
            in_pi80_cal = int(ci.pi80_lo <= actual_close <= ci.pi80_hi)
            cal_lo, cal_hi, cal_bias = float(ci.pi80_lo), float(ci.pi80_hi), float(ci.bias_pct)
        else:
            in_pi80_cal = None
            cal_lo = cal_hi = cal_bias = None

        rows.append({
            "t": int(t),
            "date": str(target_ts.date()),
            "asof_date": str(asof_ts.date()),
            "last_close": last_close,
            "actual_close": actual_close,
            "actual_ret": actual_ret,
            "pred_p10": p10,
            "pred_p50": p50,
            "pred_p90": p90,
            "pred_ret_p50": pred_ret_p50,
            "abs_err": abs_err,
            "dir_hit": dir_hit,
            "persist_ret": persist_ret,
            "persist_hit": persist_hit,
            "in_pi80": in_pi80,
            "cal_applied": bool(ci is not None),
            "cal_pi80_lo": cal_lo,
            "cal_pi80_hi": cal_hi,
            "cal_bias_pct": cal_bias,
            "in_pi80_cal": in_pi80_cal,
            "regime_bucket": bucket,
            "lookback_used": int(lb),
        })

        # Expanding, strictly-prior residual history — update AFTER use, no leak.
        signed_resid_hist.append((actual_close - p50) / last_close if last_close else 0.0)
        bucket_hist.append(bucket)

    return rows
