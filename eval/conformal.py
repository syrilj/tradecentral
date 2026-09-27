"""
Split-conformal prediction-interval calibration and ensemble path sanitization.
Ported from Kronos/conformal.py — pure functions, no I/O, behavior unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "realized_daily_sigma",
    "sanitize_terminal_closes",
    "SanitizeInfo",
    "regime_bucket",
    "conformal_abs_quantile",
    "CalibratedInterval",
    "calibrate_interval",
    "clamp_point_return",
]


def realized_daily_sigma(closes: Sequence[float], window: int = 20) -> Optional[float]:
    """Trailing daily close-to-close sigma (fractional). None on junk input."""
    c = np.asarray(closes, dtype=float).ravel()
    c = c[np.isfinite(c)]
    if c.size < 3:
        return None
    rets = np.diff(c) / c[:-1]
    rets = rets[np.isfinite(rets)]
    if rets.size < 2:
        return None
    tail = rets[-int(window):] if rets.size > window else rets
    s = float(np.std(tail, ddof=1))
    return s if (np.isfinite(s) and s > 0.0) else None


@dataclass
class SanitizeInfo:
    n_in: int
    n_finite: int
    n_clipped: int
    n_dropped: int
    cap_pct: float
    changed: bool

    def to_dict(self) -> dict:
        return asdict(self)


def sanitize_terminal_closes(
    closes: Sequence[float],
    last_close: float,
    daily_sigma: Optional[float],
    h_days: int = 1,
    *,
    abs_floor: float = 0.12,
    vol_mult: float = 6.0,
    hard_cap: float = 0.80,
) -> Tuple[np.ndarray, SanitizeInfo]:
    """Drop degenerate closes and winsorize blow-up terminal returns to
    cap = min(hard_cap, max(abs_floor, vol_mult * daily_sigma * sqrt(h_days))),
    so only egregious outliers are touched and healthy dispersion survives."""
    c = np.asarray(closes, dtype=float).ravel()
    n_in = int(c.size)
    finite = c[np.isfinite(c) & (c > 0.0)]
    n_finite = int(finite.size)
    if n_finite < 2 or not np.isfinite(last_close) or last_close <= 0.0:
        info = SanitizeInfo(n_in, n_finite, 0, n_in - n_finite, 0.0, n_in != n_finite)
        return finite, info

    sig = float(daily_sigma) if (daily_sigma is not None and np.isfinite(daily_sigma) and daily_sigma > 0) else 0.0
    h = max(int(h_days), 1)
    cap = min(float(hard_cap), max(float(abs_floor), float(vol_mult) * sig * float(np.sqrt(h))))

    rets = finite / float(last_close) - 1.0
    clipped_mask = np.abs(rets) > cap
    n_clipped = int(np.count_nonzero(clipped_mask))
    rets_clipped = np.clip(rets, -cap, cap)
    clean = float(last_close) * (1.0 + rets_clipped)

    info = SanitizeInfo(
        n_in=n_in,
        n_finite=n_finite,
        n_clipped=n_clipped,
        n_dropped=n_in - n_finite,
        cap_pct=round(cap * 100.0, 3),
        changed=bool(n_clipped > 0 or n_in != n_finite),
    )
    return clean, info


def regime_bucket(
    closes: Optional[Sequence[float]] = None,
    volumes: Optional[Sequence[float]] = None,
    *,
    ret_1d: Optional[float] = None,
    regime_score: Optional[float] = None,
) -> str:
    """Coarse per-day regime label: 'STRONG_MOMENTUM' or 'MIXED', so calibration
    residuals can be conditioned on regime inside a leak-free walk-forward."""
    if regime_score is not None and np.isfinite(regime_score):
        return "STRONG_MOMENTUM" if abs(float(regime_score)) >= 0.45 else "MIXED"

    c = np.asarray(closes, dtype=float).ravel() if closes is not None else None
    if c is not None and c.size >= 6:
        r1 = float(c[-1] / c[-2] - 1.0) if ret_1d is None else float(ret_1d)
        r3 = float(c[-1] / c[-4] - 1.0)
        vr = 1.0
        if volumes is not None:
            v = np.asarray(volumes, dtype=float).ravel()
            if v.size >= 20 and float(np.mean(v[-20:])) > 0:
                vr = float(v[-1] / np.mean(v[-20:]))
        if abs(r1) >= 0.05 or (abs(r1) >= 0.03 and abs(r3) >= 0.05 and vr >= 1.3):
            return "STRONG_MOMENTUM"
        return "MIXED"

    if ret_1d is not None and np.isfinite(ret_1d):
        return "STRONG_MOMENTUM" if abs(float(ret_1d)) >= 0.05 else "MIXED"
    return "MIXED"


def conformal_abs_quantile(abs_residuals: Sequence[float], coverage: float) -> Optional[float]:
    """Finite-sample split-conformal quantile of |residual|: level =
    ceil((n+1)*coverage)/n, clipped to 1. None if too few residuals."""
    r = np.asarray(abs_residuals, dtype=float).ravel()
    r = r[np.isfinite(r)]
    n = r.size
    if n < 2 or not (0.0 < coverage < 1.0):
        return None
    level = float(np.ceil((n + 1) * coverage) / n)
    level = min(level, 1.0)
    return float(np.quantile(r, level))


@dataclass
class CalibratedInterval:
    applied: bool
    p50_adj: float
    pi80_lo: float
    pi80_hi: float
    pi50_lo: float
    pi50_hi: float
    half80_pct: float
    half50_pct: float
    bias_pct: float
    n_used: int
    bucket: str
    pooled_fallback: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _select_residuals(
    signed_residuals: Sequence[float],
    buckets: Optional[Sequence[str]],
    bucket: Optional[str],
    min_bucket: int,
) -> Tuple[np.ndarray, bool]:
    """Prefer bucket-matched residuals; fall back to pooled history if the
    bucket is too thin. Returns (residuals, pooled_fallback)."""
    sr = np.asarray(signed_residuals, dtype=float).ravel()
    if bucket is None or buckets is None:
        return sr[np.isfinite(sr)], False
    bk = np.asarray(list(buckets), dtype=object)
    if bk.size != sr.size:
        return sr[np.isfinite(sr)], False
    sel = sr[bk == bucket]
    sel = sel[np.isfinite(sel)]
    if sel.size >= min_bucket:
        return sel, False
    return sr[np.isfinite(sr)], True


def calibrate_interval(
    p50: float,
    last_close: float,
    signed_residuals: Sequence[float],
    *,
    buckets: Optional[Sequence[str]] = None,
    bucket: Optional[str] = None,
    coverage80: float = 0.80,
    coverage50: float = 0.50,
    warmup: int = 20,
    min_bucket: int = 30,
    bias_correct: bool = True,
) -> Optional[CalibratedInterval]:
    """Bias-corrected split-conformal interval from prior signed residuals.

    `signed_residuals` must be a STRICTLY-prior expanding-window history —
    the caller guarantees no leakage. Returns None below `warmup` residuals,
    so early days keep the raw band instead of a fabricated one.
    """
    if not np.isfinite(p50) or not np.isfinite(last_close) or last_close <= 0.0:
        return None
    res, pooled = _select_residuals(signed_residuals, buckets, bucket, min_bucket)
    if res.size < warmup:
        return None

    bias = float(np.median(res)) if bias_correct else 0.0
    dev = np.abs(res - bias)
    h80 = conformal_abs_quantile(dev, coverage80)
    h50 = conformal_abs_quantile(dev, coverage50)
    if h80 is None or h50 is None:
        return None

    center = float(p50) + bias * float(last_close)
    half80 = h80 * float(last_close)
    half50 = h50 * float(last_close)
    return CalibratedInterval(
        applied=True,
        p50_adj=center,
        pi80_lo=center - half80,
        pi80_hi=center + half80,
        pi50_lo=center - half50,
        pi50_hi=center + half50,
        half80_pct=round(h80 * 100.0, 4),
        half50_pct=round(h50 * 100.0, 4),
        bias_pct=round(bias * 100.0, 4),
        n_used=int(res.size),
        bucket=bucket or "pooled",
        pooled_fallback=bool(pooled),
    )


def clamp_point_return(
    point: float,
    last_close: float,
    daily_sigma: Optional[float],
    h_days: int = 1,
    *,
    abs_floor: float = 0.04,
    vol_mult: float = 1.5,
    hard_cap: float = 0.25,
) -> Tuple[float, bool]:
    """Clamp an actionable point forecast to a plausible move band (tighter
    than the ensemble tails). Returns (clamped_point, was_clamped)."""
    if not np.isfinite(point) or not np.isfinite(last_close) or last_close <= 0.0:
        return point, False
    sig = float(daily_sigma) if (daily_sigma is not None and np.isfinite(daily_sigma) and daily_sigma > 0) else 0.0
    h = max(int(h_days), 1)
    cap = min(float(hard_cap), max(float(abs_floor), float(vol_mult) * sig * float(np.sqrt(h))))
    r = float(point) / float(last_close) - 1.0
    if abs(r) <= cap:
        return float(point), False
    r_clamped = float(np.clip(r, -cap, cap))
    return float(last_close) * (1.0 + r_clamped), True
