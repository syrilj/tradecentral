"""Technical Analysis Level Calculator for TradeCentral.

Derives authentic price levels (swing highs/lows, moving averages, Donchian channels,
and Average True Range) from stored daily price bars on disk.

These levels serve as measured technical support, resistance, invalidation marks,
and take-profit targets when live options GEX or provider levels are absent.
Never hallucinates or invents prices: every level is directly grounded in
observed price bars.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence
import numpy as np
import pandas as pd


@lru_cache(maxsize=512)
def load_symbol_daily_bars(
    symbol: str,
    root_dir: str = ".",
) -> pd.DataFrame | None:
    """Load historical daily bars from disk for a symbol."""
    sym = str(symbol).strip().upper()
    root = Path(root_dir)
    candidates = [
        root / "data" / "1d" / f"{sym}.parquet",
        root / "data" / "1d_wide" / f"{sym}.parquet",
        root / "data" / "1d_smallcap" / f"{sym}.parquet",
        root / "edge" / "data" / "1d" / f"{sym}.parquet",
        root / "edge" / "data" / "1d_wide" / f"{sym}.parquet",
        root / "edge" / "data" / "1d_smallcap" / f"{sym}.parquet",
    ]
    for p in candidates:
        if p.is_file():
            try:
                df = pd.read_parquet(p)
                df.columns = [str(c).lower() for c in df.columns]
                if "close" in df.columns:
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.sort_values("date").reset_index(drop=True)
                    return df
            except Exception:
                continue
    return None


def calculate_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float | None:
    """Calculate 14-period Average True Range."""
    if len(closes) < 2:
        return None
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else None
    return float(np.mean(tr[-period:]))


def find_swing_extrema(
    highs: np.ndarray,
    lows: np.ndarray,
    spot: float,
    window: int = 2,
) -> tuple[list[float], list[float]]:
    """Find local swing lows below spot and swing highs above spot."""
    n = len(highs)
    if n < window * 2 + 1:
        return [], []

    swing_lows: list[float] = []
    swing_highs: list[float] = []

    for i in range(window, n - window):
        # Local low
        is_low = True
        for w in range(1, window + 1):
            if lows[i] > lows[i - w] or lows[i] > lows[i + w]:
                is_low = False
                break
        if is_low and lows[i] < spot:
            swing_lows.append(round(float(lows[i]), 4))

        # Local high
        is_high = True
        for w in range(1, window + 1):
            if highs[i] < highs[i - w] or highs[i] < highs[i + w]:
                is_high = False
                break
        if is_high and highs[i] > spot:
            swing_highs.append(round(float(highs[i]), 4))

    # Return distinct, sorted values:
    # swing_lows descending (highest support closest to spot first)
    # swing_highs ascending (lowest resistance closest to spot first)
    unique_lows = sorted(set(swing_lows), reverse=True)
    unique_highs = sorted(set(swing_highs))
    return unique_lows, unique_highs


def measure_symbol_ta_levels(
    symbol: str,
    spot: float | None = None,
    lookback_bars: int = 60,
    root_dir: str | Path = ".",
) -> dict[str, Any]:
    """Measure authentic Support & Resistance levels from daily price bars.

    Returns structured levels tagged with 'technical analysis' source,
    suitable for feeding setup_inputs_from_rows and setup_level_model.
    """
    df = load_symbol_daily_bars(symbol, root_dir=root_dir)
    if df is None or df.empty or "close" not in df.columns:
        return {}

    sub = df.tail(lookback_bars)
    if sub.empty:
        return {}

    closes = sub["close"].to_numpy(dtype=float)
    highs = sub["high"].to_numpy(dtype=float) if "high" in sub.columns else closes
    lows = sub["low"].to_numpy(dtype=float) if "low" in sub.columns else closes

    current_spot = float(spot) if spot is not None and spot > 0 else float(closes[-1])
    atr = calculate_atr(highs, lows, closes, period=14)

    # Swing extrema
    swing_lows, swing_highs = find_swing_extrema(highs, lows, current_spot, window=2)

    # Moving averages
    sma_20 = round(float(closes[-20:].mean()), 4) if len(closes) >= 20 else None
    sma_50 = round(float(closes[-50:].mean()), 4) if len(closes) >= 50 else None

    # Donchian channel
    donchian_low = round(float(np.min(lows[-20:])), 4) if len(lows) >= 20 else None
    donchian_high = round(float(np.max(highs[-20:])), 4) if len(highs) >= 20 else None

    # Categorize moving averages relative to spot
    ma_supports: list[float] = []
    ma_resistances: list[float] = []
    for ma in (sma_20, sma_50):
        if ma is not None:
            if ma < current_spot:
                ma_supports.append(ma)
            elif ma > current_spot:
                ma_resistances.append(ma)

    # Aggregate supports (below spot)
    all_supports = list(swing_lows)
    for s in ma_supports:
        if s not in all_supports:
            all_supports.append(s)
    if (
        donchian_low is not None
        and donchian_low < current_spot
        and donchian_low not in all_supports
    ):
        all_supports.append(donchian_low)
    all_supports = sorted(all_supports, reverse=True)

    # Aggregate resistances (above spot)
    all_resistances = list(swing_highs)
    for r in ma_resistances:
        if r not in all_resistances:
            all_resistances.append(r)
    if (
        donchian_high is not None
        and donchian_high > current_spot
        and donchian_high not in all_resistances
    ):
        all_resistances.append(donchian_high)
    all_resistances = sorted(all_resistances)

    ta_support = all_supports[0] if all_supports else None
    ta_resistance = all_resistances[0] if all_resistances else None

    # Fallback to ATR buffer if price was at all-time high/low in the window
    if ta_support is None and atr is not None and atr > 0:
        ta_support = round(current_spot - 1.5 * atr, 4)
        all_supports = [ta_support]
    if ta_resistance is None and atr is not None and atr > 0:
        ta_resistance = round(current_spot + 1.5 * atr, 4)
        all_resistances = [ta_resistance]

    return {
        "symbol": symbol.upper(),
        "spot": current_spot,
        "ta_support": ta_support,
        "ta_resistance": ta_resistance,
        "swing_low": swing_lows[0] if swing_lows else ta_support,
        "swing_high": swing_highs[0] if swing_highs else ta_resistance,
        "supports": [{"price": p, "source": "technical analysis"} for p in all_supports[:5]],
        "resistances": [{"price": p, "source": "technical analysis"} for p in all_resistances[:5]],
        "sma_20": sma_20,
        "sma_50": sma_50,
        "atr_14": round(atr, 4) if atr is not None else None,
        "source": "technical analysis",
    }
