"""
Microstructure feature calculation engine.

Computes observable order-flow, spread, volume, and liquidity shock features
without assuming prior alpha status.
"""

from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd


def _require_ascending(series: pd.Series, name: str) -> None:
    """Reject an out-of-order index before any ``.rolling()`` call.

    ``.rolling()`` walks positional order, not time order, so an unsorted input
    silently stops being trailing and starts mixing future bars into a
    "historical" median -- a look-ahead that produces plausible numbers and no
    error. ``research/regimes.py`` guards its inputs the same way.
    """
    index = series.index
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError(f"{name} must have a unique ascending index")


def compute_signed_trade_imbalance(
    buy_volume: np.ndarray,
    sell_volume: np.ndarray,
    eps: float = 1e-6,
) -> np.ndarray:
    """
    TI_t = (V_t^buy - V_t^sell) / (V_t^buy + V_t^sell + eps)
    """
    buy = np.asarray(buy_volume, dtype=float)
    sell = np.asarray(sell_volume, dtype=float)
    denom = buy + sell + eps
    return (buy - sell) / denom


def compute_quote_imbalance(
    bid_size: np.ndarray,
    ask_size: np.ndarray,
    eps: float = 1e-6,
) -> np.ndarray:
    """
    QI_t = (Size_t^bid - Size_t^ask) / (Size_t^bid + Size_t^ask + eps)
    """
    bid = np.asarray(bid_size, dtype=float)
    ask = np.asarray(ask_size, dtype=float)
    denom = bid + ask + eps
    return (bid - ask) / denom


def compute_relative_spread(
    bid_price: np.ndarray,
    ask_price: np.ndarray,
    eps: float = 1e-6,
) -> np.ndarray:
    """
    Spread_t = (Ask_t - Bid_t) / Mid_t
    """
    bid = np.asarray(bid_price, dtype=float)
    ask = np.asarray(ask_price, dtype=float)
    mid = 0.5 * (bid + ask)
    mid = np.where(mid <= 0, eps, mid)
    return (ask - bid) / mid


def compute_relative_volume(
    volume: pd.Series,
    time_of_day: Optional[pd.Series] = None,
    window: int = 20,
) -> pd.Series:
    """
    RVOL_t = Volume_t / Median volume at the same time of day (or trailing rolling median)
    """
    _require_ascending(volume, "volume")
    vol = volume.astype(float)
    if time_of_day is not None and len(time_of_day) == len(volume):
        df = pd.DataFrame({"vol": vol, "tod": time_of_day})
        median_tod = df.groupby("tod")["vol"].transform(lambda s: s.rolling(window, min_periods=5).median())
        median_tod = median_tod.fillna(vol.rolling(window, min_periods=5).median())
        return vol / np.maximum(median_tod, 1e-5)
    else:
        rolling_median = vol.rolling(window, min_periods=5).median()
        return vol / np.maximum(rolling_median, 1e-5)


def compute_short_term_price_impact(
    signed_flow: np.ndarray,
    close_price: np.ndarray,
    horizon: int = 5,
) -> np.ndarray:
    """
    Impact_{t,h} = SignFlow_t * (log P_{t+h} - log P_t)
    """
    flow = np.asarray(signed_flow, dtype=float)
    prices = np.asarray(close_price, dtype=float)
    prices = np.where(prices <= 0, 1e-5, prices)
    log_p = np.log(prices)

    log_p_future = np.roll(log_p, -horizon)
    log_p_future[-horizon:] = np.nan

    return flow * (log_p_future - log_p)


def compute_liquidity_shock(
    spread: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> pd.Series:
    """
    Liquidity shock = (Spread / Rolling_Median_Spread) - (Volume / Rolling_Median_Volume)
    High positive value indicates widening spread with collapsing volume (liquidity shock).
    """
    _require_ascending(spread, "spread")
    _require_ascending(volume, "volume")
    med_spread = spread.rolling(window, min_periods=5).median()
    med_vol = volume.rolling(window, min_periods=5).median()

    rel_spread = spread / np.maximum(med_spread, 1e-5)
    rel_vol = volume / np.maximum(med_vol, 1e-5)

    return rel_spread - rel_vol
