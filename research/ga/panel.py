"""Precomputed OHLCV matrices for fast multi-genome evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from edge.research.daily_data import load_daily_universe


@dataclass(frozen=True)
class MarketPanel:
    """Dense date × symbol arrays for vectorized strategy scoring."""

    dates: pd.DatetimeIndex
    symbols: tuple[str, ...]
    close: np.ndarray  # (T, S)
    volume: np.ndarray  # (T, S)
    high: np.ndarray
    low: np.ndarray
    ret_1d: np.ndarray
    dollar_volume: np.ndarray
    # Optional Qlib-style cross-section score (higher = more attractive long).
    # Shape (T, S) or None when hybrid CS genes are disabled.
    cs_score: np.ndarray | None = None

    @property
    def n_dates(self) -> int:
        return int(self.close.shape[0])

    @property
    def n_symbols(self) -> int:
        return int(self.close.shape[1])

    def slice_dates(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> "MarketPanel":
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (self.dates >= start_ts) & (self.dates <= end_ts)
        if not bool(mask.any()):
            raise ValueError(f"no dates in panel for [{start}, {end}]")
        idx = np.where(mask)[0]
        cs = None if self.cs_score is None else self.cs_score[idx]
        return MarketPanel(
            dates=self.dates[idx],
            symbols=self.symbols,
            close=self.close[idx],
            volume=self.volume[idx],
            high=self.high[idx],
            low=self.low[idx],
            ret_1d=self.ret_1d[idx],
            dollar_volume=self.dollar_volume[idx],
            cs_score=cs,
        )

    def with_cs_score(self, cs_score: np.ndarray) -> "MarketPanel":
        if cs_score.shape != self.close.shape:
            raise ValueError(f"cs_score shape {cs_score.shape} != close {self.close.shape}")
        return MarketPanel(
            dates=self.dates,
            symbols=self.symbols,
            close=self.close,
            volume=self.volume,
            high=self.high,
            low=self.low,
            ret_1d=self.ret_1d,
            dollar_volume=self.dollar_volume,
            cs_score=np.asarray(cs_score, dtype=float),
        )


def build_market_panel(
    symbols: Iterable[str],
    *,
    asof: str | pd.Timestamp,
    data_dir: str | Path,
) -> MarketPanel:
    """Load local daily parquets into aligned matrices (missing → NaN)."""
    bars = load_daily_universe(symbols, asof=asof, data_dir=data_dir)
    if bars.empty:
        raise ValueError("market panel is empty")
    wide_close = bars["close"].unstack("symbol").sort_index()
    wide_volume = bars["volume"].unstack("symbol").reindex(index=wide_close.index, columns=wide_close.columns)
    wide_high = bars["high"].unstack("symbol").reindex(index=wide_close.index, columns=wide_close.columns)
    wide_low = bars["low"].unstack("symbol").reindex(index=wide_close.index, columns=wide_close.columns)

    close = wide_close.to_numpy(dtype=float)
    volume = wide_volume.to_numpy(dtype=float)
    high = wide_high.to_numpy(dtype=float)
    low = wide_low.to_numpy(dtype=float)
    ret_1d = np.full_like(close, np.nan)
    ret_1d[1:] = close[1:] / close[:-1] - 1.0
    dollar_volume = close * volume

    symbols_t = tuple(str(c) for c in wide_close.columns)
    return MarketPanel(
        dates=pd.DatetimeIndex(wide_close.index),
        symbols=symbols_t,
        close=close,
        volume=volume,
        high=high,
        low=low,
        ret_1d=ret_1d,
        dollar_volume=dollar_volume,
        cs_score=None,
    )


def attach_factor_probe_cs_score(panel: MarketPanel) -> MarketPanel:
    """Build a Qlib-scan-style ordinal score from panel bars (no qlib import).

    Mirrors desk ``qlib_scan_score`` factor blend weights:
    rev5 0.40, rev1 0.25, mom12_1 0.15, lowvol 0.12, liq 0.08.
    Higher = more attractive for longs. Cross-section ranks are applied in fitness.
    """
    close = panel.close
    ret = panel.ret_1d
    t, s = close.shape
    score = np.full((t, s), np.nan, dtype=float)

    # rev1 = -ret_1d (short-term reversal)
    rev1 = -ret
    # rev5 = -(close/close_lag5 - 1)
    rev5 = np.full_like(close, np.nan)
    if t > 5:
        with np.errstate(invalid="ignore", divide="ignore"):
            rev5[5:] = -(close[5:] / close[:-5] - 1.0)
    # mom12_1 ≈ close/close_252 - close/close_21 (skip last month)
    mom = np.full_like(close, np.nan)
    if t > 252:
        with np.errstate(invalid="ignore", divide="ignore"):
            r12 = close[252:] / close[:-252] - 1.0
            r1m = close[252:] / close[252 - 21 : t - 21] - 1.0
            mom[252:] = r12 - r1m
    # lowvol = -rolling std of ret (20)
    vol20 = rolling_std(ret, 20)
    lowvol = -vol20
    # liq = log dollar volume
    with np.errstate(invalid="ignore", divide="ignore"):
        liq = np.log(np.maximum(panel.dollar_volume, 1.0))

    weights = (
        (0.40, rev5),
        (0.25, rev1),
        (0.15, mom),
        (0.12, lowvol),
        (0.08, liq),
    )
    for i in range(t):
        parts = []
        wsum = 0.0
        for w, arr in weights:
            row = arr[i]
            if not np.isfinite(row).any():
                continue
            # Z-score within day so factors are commensurable
            mu = np.nanmean(row)
            sd = np.nanstd(row)
            if not np.isfinite(sd) or sd < 1e-12:
                z = np.zeros(s, dtype=float)
                z[~np.isfinite(row)] = np.nan
            else:
                with np.errstate(invalid="ignore"):
                    z = (row - mu) / sd
            parts.append(w * np.nan_to_num(z, nan=0.0))
            wsum += w
        if wsum <= 0:
            continue
        blended = sum(parts) / wsum
        # Restore NaN where close missing
        blended = np.where(np.isfinite(close[i]), blended, np.nan)
        score[i] = blended
    return panel.with_cs_score(score)


def rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """NaN-aware trailing mean along axis 0."""
    if window < 1:
        raise ValueError("window must be >= 1")
    t, s = arr.shape
    out = np.full((t, s), np.nan, dtype=float)
    if t < window:
        return out
    csum = np.nancumsum(np.where(np.isfinite(arr), arr, 0.0), axis=0)
    ccount = np.cumsum(np.isfinite(arr).astype(float), axis=0)
    total = csum[window - 1 :] - np.vstack([np.zeros((1, s)), csum[: t - window]])
    count = ccount[window - 1 :] - np.vstack([np.zeros((1, s)), ccount[: t - window]])
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count >= window, total / count, np.nan)
    out[window - 1 :] = mean
    return out


def rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    """Population trailing std (ddof=0), NaN-aware."""
    mean = rolling_mean(arr, window)
    mean_sq = rolling_mean(np.square(arr), window)
    with np.errstate(invalid="ignore"):
        var = mean_sq - np.square(mean)
        std = np.sqrt(np.maximum(var, 0.0))
    std[~np.isfinite(mean)] = np.nan
    return std


def rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    t, s = arr.shape
    out = np.full((t, s), np.nan, dtype=float)
    for i in range(window - 1, t):
        block = arr[i - window + 1 : i + 1]
        finite = np.isfinite(block)
        # nanmax warns on all-NaN columns; keep NaN there instead.
        with np.errstate(all="ignore"):
            col_ok = finite.any(axis=0)
            if col_ok.any():
                out[i, col_ok] = np.nanmax(np.where(finite, block, -np.inf), axis=0)[col_ok]
    return out


def rolling_min(arr: np.ndarray, window: int) -> np.ndarray:
    t, s = arr.shape
    out = np.full((t, s), np.nan, dtype=float)
    for i in range(window - 1, t):
        block = arr[i - window + 1 : i + 1]
        finite = np.isfinite(block)
        with np.errstate(all="ignore"):
            col_ok = finite.any(axis=0)
            if col_ok.any():
                out[i, col_ok] = np.nanmin(np.where(finite, block, np.inf), axis=0)[col_ok]
    return out


def cross_sectional_rank(values: np.ndarray) -> np.ndarray:
    """Average rank in [0, 1] per row; NaNs stay NaN."""
    t, s = values.shape
    out = np.full((t, s), np.nan, dtype=float)
    for i in range(t):
        row = values[i]
        valid = np.isfinite(row)
        n = int(valid.sum())
        if n < 2:
            continue
        order = np.argsort(row[valid], kind="mergesort")
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(n, dtype=float)
        out[i, valid] = ranks / max(n - 1, 1)
    return out
