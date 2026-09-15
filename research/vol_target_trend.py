"""Volatility-Targeted Trend following strategy.

The effect: trend following makes its money in the fat right tail, a few
large moves a year, and gives it back in chop. The raw P&L of a fixed-size
trend rule therefore swings with the volatility regime rather than with the
quality of the signal.

The fix: size every entry so its notional targets a CONSTANT annualised
volatility. In calm markets you carry more, in turbulent markets less, and
the risk taken per trade stops depending on when the trade happened. Most
of the Sharpe difference between a naive trend rule and a managed-futures
one lives in this single line of sizing.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_TARGET_VOL = 0.15
DEFAULT_LEV_CAP = 3.0
DEFAULT_FAST_DAYS = 5.0
DEFAULT_SLOW_DAYS = 20.0
DEFAULT_VOL_DAYS = 20.0
DEFAULT_CAPITAL = 100_000.0
MIN_BARS_FLOOR = 3
SECONDS_PER_DAY = 86_400.0
SECONDS_PER_YEAR = 365.25 * SECONDS_PER_DAY


@dataclass(frozen=True)
class VolTargetTrade:
    """One round-trip trade reconstructed from signal and fill bars.

    Signal was generated at bar i, filled at bar entry_i = i + 1.
    Exit signal at bar j, filled at bar exit_i = j + 1.
    """

    entry_i: int
    exit_i: int
    direction: str
    qty: float
    entry_px: float
    exit_px: float
    ret_pct: float
    pnl: float
    notional: float
    leverage_at_entry: float
    vol_at_entry: float
    forced_exit: bool = False


@dataclass(frozen=True)
class VolTargetTrendResult:
    """Result of Volatility-Targeted Trend evaluation over a series of bars."""

    bars_per_day: float
    fast_bars: int
    slow_bars: int
    vol_bars: int
    warmup_bars: int
    ema_fast: np.ndarray
    ema_slow: np.ndarray
    up_trend: np.ndarray
    bar_vol: np.ndarray
    ann_vol: np.ndarray
    leverage: np.ndarray
    position_state: np.ndarray
    trades: list[VolTargetTrade]
    open_at_end: bool
    capital: float
    target_vol: float
    lev_cap: float


def _measure_spacing_seconds(ts: np.ndarray) -> float:
    """Median timestamp spacing in seconds from initial bars."""
    if ts.size < 2:
        return 3600.0
    sub = ts[:20_000]
    diffs = np.diff(sub)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return 3600.0
    med = float(np.median(diffs))
    return med if np.isfinite(med) and med > 0 else 3600.0


def vol_target_trend(
    df: pd.DataFrame,
    *,
    target_vol: float = DEFAULT_TARGET_VOL,
    lev_cap: float = DEFAULT_LEV_CAP,
    fast_days: float = DEFAULT_FAST_DAYS,
    slow_days: float = DEFAULT_SLOW_DAYS,
    vol_days: float = DEFAULT_VOL_DAYS,
    capital: float = DEFAULT_CAPITAL,
) -> VolTargetTrendResult:
    """Evaluate Volatility-Targeted Trend following over historical bars.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'close' column, and either 'ts' column or a pd.DatetimeIndex.
        Optionally contains 'open' column for fill prices.
    target_vol : float
        Annualised volatility target (e.g. 0.15 for 15% vol).
    lev_cap : float
        Maximum leverage ratio (notional / capital).
    fast_days : float
        Fast EMA lookback in days.
    slow_days : float
        Slow EMA lookback in days.
    vol_days : float
        Realised volatility lookback in days.
    capital : float
        Nominal trading capital in currency units.
    """
    if "close" not in df.columns or len(df) == 0:
        raise ValueError("Input DataFrame must contain 'close' column with at least 1 row.")

    # Resolve timestamps
    if "ts" in df.columns:
        _ts = pd.to_numeric(df["ts"], errors="coerce").to_numpy(dtype=float)
    elif isinstance(df.index, pd.DatetimeIndex):
        _ts = df.index.astype("int64").to_numpy(dtype=float) / 1e9
    else:
        _ts = np.arange(len(df), dtype=float) * SECONDS_PER_DAY

    # Spacing and bars per day
    _bar_s = _measure_spacing_seconds(_ts)
    _bpd = max(1.0, SECONDS_PER_DAY / max(_bar_s, 1.0))

    def _bars(days: float, floor: int = MIN_BARS_FLOOR) -> int:
        try:
            d = float(days)
        except (TypeError, ValueError):
            d = 5.0
        if not np.isfinite(d) or d <= 0:
            d = 5.0
        return max(floor, int(round(d * _bpd)))

    fast = _bars(fast_days)
    slow = _bars(slow_days)
    vol_n = _bars(vol_days)

    close_s = pd.to_numeric(df["close"], errors="coerce").astype(float)
    ema_f_s = close_s.ewm(span=fast, adjust=False).mean()
    ema_s_s = close_s.ewm(span=slow, adjust=False).mean()
    ema_f = ema_f_s.to_numpy(dtype=float)
    ema_s = ema_s_s.to_numpy(dtype=float)
    up = (ema_f_s > ema_s_s).to_numpy(dtype=bool)

    # Realised volatility and annualisation
    ret = close_s.pct_change()
    bar_vol = ret.rolling(vol_n).std().to_numpy(dtype=float)
    t0 = _ts[0] if len(_ts) > 0 else 0.0
    elapsed_years = (_ts - t0) / SECONDS_PER_YEAR
    bars_per_year = (np.arange(len(df)) + 1.0) / np.maximum(elapsed_years, 1e-9)
    ann_vol = bar_vol * np.sqrt(bars_per_year)

    with np.errstate(divide="ignore", invalid="ignore"):
        leverage = np.minimum(target_vol / ann_vol, lev_cap)

    px = close_s.to_numpy(dtype=float)
    if "open" in df.columns:
        fill_px = (
            pd.to_numeric(df["open"], errors="coerce")
            .fillna(close_s)
            .to_numpy(dtype=float)
        )
    else:
        fill_px = px

    n = len(df)
    warmup = max(slow, vol_n) + 1
    position_state = np.zeros(n, dtype=int)

    trades: list[VolTargetTrade] = []
    in_pos = False
    entry_i = 0
    qty = 0.0
    entry_lev = 0.0
    entry_vol = 0.0

    for i in range(warmup, n - 1):
        if not in_pos:
            if up[i] and np.isfinite(leverage[i]) and leverage[i] > 0 and px[i] > 0:
                in_pos = True
                entry_i = i + 1  # fill at next bar's open
                entry_lev = float(leverage[i])
                entry_vol = float(ann_vol[i]) if np.isfinite(ann_vol[i]) else 0.0
                qty = float(capital * entry_lev / px[i])
        elif not up[i]:
            exit_i = i + 1
            if entry_i < n and exit_i < n:
                ep = float(fill_px[entry_i])
                xp = float(fill_px[exit_i])
                ret_pct = ((xp / ep - 1.0) * 100.0) if ep > 0 else 0.0
                pnl = qty * (xp - ep)
                notional = qty * ep
                trades.append(
                    VolTargetTrade(
                        entry_i=entry_i,
                        exit_i=exit_i,
                        direction="long",
                        qty=qty,
                        entry_px=ep,
                        exit_px=xp,
                        ret_pct=ret_pct,
                        pnl=pnl,
                        notional=notional,
                        leverage_at_entry=entry_lev,
                        vol_at_entry=entry_vol,
                        forced_exit=False,
                    )
                )
            in_pos = False

    open_at_end = False
    if in_pos and entry_i < n - 1:
        exit_i = n - 1
        ep = float(fill_px[entry_i])
        xp = float(fill_px[exit_i])
        ret_pct = ((xp / ep - 1.0) * 100.0) if ep > 0 else 0.0
        pnl = qty * (xp - ep)
        notional = qty * ep
        trades.append(
            VolTargetTrade(
                entry_i=entry_i,
                exit_i=exit_i,
                direction="long",
                qty=qty,
                entry_px=ep,
                exit_px=xp,
                ret_pct=ret_pct,
                pnl=pnl,
                notional=notional,
                leverage_at_entry=entry_lev,
                vol_at_entry=entry_vol,
                forced_exit=True,
            )
        )
        open_at_end = True

    # Mark position state per bar
    for t in trades:
        position_state[t.entry_i : t.exit_i] = 1

    return VolTargetTrendResult(
        bars_per_day=_bpd,
        fast_bars=fast,
        slow_bars=slow,
        vol_bars=vol_n,
        warmup_bars=warmup,
        ema_fast=ema_f,
        ema_slow=ema_s,
        up_trend=up,
        bar_vol=bar_vol,
        ann_vol=ann_vol,
        leverage=leverage,
        position_state=position_state,
        trades=trades,
        open_at_end=open_at_end,
        capital=capital,
        target_vol=target_vol,
        lev_cap=lev_cap,
    )


def compute_trade_stats(
    trades: Sequence[VolTargetTrade],
    position_state: np.ndarray,
    capital: float,
) -> dict:
    """Calculate descriptive, cost-free backtest statistics."""
    n_bars = int(position_state.size)
    exposure_pct = float((position_state != 0).sum()) / n_bars * 100.0 if n_bars > 0 else 0.0

    if not trades:
        return {
            "n_trades": 0,
            "win_rate_pct": None,
            "avg_ret_pct": None,
            "median_ret_pct": None,
            "best_ret_pct": None,
            "worst_ret_pct": None,
            "compounded_pct": None,
            "total_pnl": 0.0,
            "profit_factor": None,
            "avg_bars": None,
            "max_drawdown_pct": None,
            "sharpe_ratio": None,
            "exposure_pct": round(exposure_pct, 2),
        }

    rets = np.array([t.ret_pct for t in trades], dtype=float)
    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    bars = np.array([t.exit_i - t.entry_i for t in trades], dtype=float)

    total_gain = float(np.sum(wins)) if wins.size > 0 else 0.0
    total_loss = float(abs(np.sum(losses))) if losses.size > 0 else 0.0
    profit_factor = (total_gain / total_loss) if total_loss > 0 else (None if total_gain == 0 else 999.0)

    # Cumulative equity curve from trade P&Ls
    equity_curve = [capital]
    for p in pnls:
        equity_curve.append(equity_curve[-1] + p)
    eq_arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(eq_arr)
    drawdowns = (eq_arr - peak) / np.maximum(peak, 1.0)
    max_dd_pct = float(abs(np.min(drawdowns))) * 100.0

    total_pnl = float(np.sum(pnls))
    compounded_pct = (total_pnl / capital) * 100.0 if capital > 0 else None

    # Trade-level Sharpe
    ret_std = float(np.std(rets)) if len(rets) > 1 else 0.0
    sharpe = float(np.mean(rets) / ret_std) if ret_std > 1e-9 else None

    return {
        "n_trades": len(trades),
        "win_rate_pct": round(float((pnls > 0).sum()) / len(trades) * 100.0, 1),
        "avg_ret_pct": round(float(np.mean(rets)), 2),
        "median_ret_pct": round(float(np.median(rets)), 2),
        "best_ret_pct": round(float(np.max(rets)), 2),
        "worst_ret_pct": round(float(np.min(rets)), 2),
        "compounded_pct": round(compounded_pct, 2) if compounded_pct is not None else None,
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_bars": round(float(np.mean(bars)), 1),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
        "exposure_pct": round(exposure_pct, 2),
    }
