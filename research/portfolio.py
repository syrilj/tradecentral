"""
Long/short portfolio accounting with mandatory execution lag and cost-aware sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

from .costs import DynamicCostModel

TRADING_DAYS = 252
DEFAULT_COST_PER_SIDE = 0.0010  # 10bp per side, 20bp round-trip
DEFAULT_MAX_ABS_DAILY_RETURN = 0.50


@dataclass(frozen=True)
class PortfolioLimitsConfig:
    """Configurable risk, capacity, and exposure limits."""
    max_position_weight: float = 0.10     # Max weight per single stock
    max_sector_exposure: float = 0.30     # Max sum of weights per sector
    max_gross_exposure: float = 1.00      # Max sum of abs(weights)
    max_daily_turnover: float = 0.25      # Max turnover per day
    max_pct_adv: float = 0.05             # Max trade size as % of ADV
    max_open_positions: int = 20          # Max number of active open positions
    min_liquidity_adv_usd: float = 1_000_000.0  # Minimum 20-day ADV in USD
    safety_margin_k: float = 1.0          # Safety margin multiplier k in alpha - cost > k*sigma


@dataclass(frozen=True)
class PortfolioResult:
    """Accounting for one simulated long/short book."""

    execution_lag: int
    n_bars: int
    gross_annual_return: float
    net_annual_return: float
    annual_volatility: float
    gross_sharpe: float
    sharpe: float
    compounded_annual_return: float
    max_drawdown: float
    annual_turnover: float
    cost_drag: float
    exposure: float
    n_extreme_masked: int
    net_returns: pd.Series = field(repr=False)
    gross_returns: pd.Series = field(repr=False)

    def as_dict(self) -> dict[str, float | int]:
        """Scalar summary, safe to json.dump."""
        return {
            "execution_lag": self.execution_lag,
            "n_bars": self.n_bars,
            "gross_annual_return_pct": self.gross_annual_return * 100.0,
            "net_annual_return_pct": self.net_annual_return * 100.0,
            "compounded_annual_return_pct": self.compounded_annual_return * 100.0,
            "annual_volatility_pct": self.annual_volatility * 100.0,
            "gross_sharpe": self.gross_sharpe,
            "sharpe_ratio": self.sharpe,
            "max_drawdown_pct": self.max_drawdown * 100.0,
            "annual_turnover": self.annual_turnover,
            "cost_drag_pct": self.cost_drag * 100.0,
            "exposure": self.exposure,
            "n_extreme_masked": self.n_extreme_masked,
        }


def compute_expected_net_edge(
    alpha_hat: float,
    estimated_cost_bps: float,
    forecast_std: float = 0.01,
    safety_margin_k: float = 1.0,
) -> float:
    """
    Computes Expected Net Edge:
    Expected Net Edge = |alpha_hat| - estimated_cost_return - k * forecast_std
    """
    cost_return = estimated_cost_bps / 10_000.0
    return abs(alpha_hat) - cost_return - safety_margin_k * forecast_std


def apply_cost_aware_sizing(
    target_weights: Dict[str, float],
    current_weights: Dict[str, float],
    alphas: Dict[str, float],
    forecast_stds: Dict[str, float],
    adv_usd: Dict[str, float],
    sectors: Optional[Dict[str, str]] = None,
    portfolio_value_usd: float = 1_000_000.0,
    cost_model: Optional[DynamicCostModel] = None,
    limits: Optional[PortfolioLimitsConfig] = None,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """
    Applies cost-aware net edge gating, no-trade buffers, and capacity/risk limits.
    Returns (filtered_target_weights, rejection_reasons).
    """
    cm = cost_model or DynamicCostModel()
    lim = limits or PortfolioLimitsConfig()
    sectors = sectors or {}

    filtered: Dict[str, float] = {}
    rejections: Dict[str, str] = {}

    # Sort positions by raw alpha magnitude
    sorted_symbols = sorted(target_weights.keys(), key=lambda s: abs(alphas.get(s, 0.0)), reverse=True)

    active_count = 0
    current_gross = 0.0

    for sym in sorted_symbols:
        desired_w = target_weights[sym]
        curr_w = current_weights.get(sym, 0.0)
        alpha = alphas.get(sym, 0.0)
        sigma = forecast_stds.get(sym, 0.01)
        sym_adv = adv_usd.get(sym, 0.0)

        # 1. Liquidity Threshold
        if sym_adv < lim.min_liquidity_adv_usd:
            filtered[sym] = 0.0
            rejections[sym] = f"ADV ({sym_adv:,.0f}) below min liquidity ({lim.min_liquidity_adv_usd:,.0f})"
            continue

        # 2. Net Edge Calculation
        trade_weight_delta = abs(desired_w - curr_w)
        order_val = trade_weight_delta * portfolio_value_usd
        cost_bps = cm.estimate_order_cost_bps(order_val, sym_adv, daily_volatility=0.02)

        net_edge = compute_expected_net_edge(alpha, cost_bps, forecast_std=sigma, safety_margin_k=lim.safety_margin_k)
        if net_edge <= 0:
            # Alpha does not cover costs + safety margin
            filtered[sym] = curr_w if abs(desired_w) <= abs(curr_w) else 0.0
            rejections[sym] = f"Insufficient net edge ({net_edge:.5f} <= 0)"
            continue

        # 3. Cost-based No-Trade Zone (rebalance buffer)
        rebalance_buffer = (cost_bps / 10_000.0)
        if abs(desired_w - curr_w) < rebalance_buffer:
            filtered[sym] = curr_w  # Retain existing position
            continue

        # 4. Single Position Limit
        w_sign = np.sign(desired_w) if desired_w != 0 else 1.0
        capped_w = w_sign * min(abs(desired_w), lim.max_position_weight)

        # 5. ADV Participation Limit
        max_trade_usd = lim.max_pct_adv * sym_adv
        max_weight_delta = max_trade_usd / portfolio_value_usd
        if abs(capped_w - curr_w) > max_weight_delta:
            capped_w = curr_w + np.sign(capped_w - curr_w) * max_weight_delta

        # 6. Max Open Positions Limit
        if curr_w == 0.0 and active_count >= lim.max_open_positions:
            filtered[sym] = 0.0
            rejections[sym] = f"Max open positions ({lim.max_open_positions}) reached"
            continue

        # 7. Gross Exposure Cap
        if current_gross + abs(capped_w) > lim.max_gross_exposure:
            avail = max(0.0, lim.max_gross_exposure - current_gross)
            capped_w = np.sign(capped_w) * min(abs(capped_w), avail)

        filtered[sym] = capped_w
        if capped_w != 0.0:
            active_count += 1
            current_gross += abs(capped_w)

    # 8. Sector Exposure Check & Capping
    if lim.max_sector_exposure > 0:
        sector_totals: Dict[str, float] = {}
        for sym, w in filtered.items():
            sec = sectors.get(sym, "UNKNOWN")
            sector_totals[sec] = sector_totals.get(sec, 0.0) + abs(w)

        for sec, total in sector_totals.items():
            if total > lim.max_sector_exposure and total > 0:
                scale = lim.max_sector_exposure / total
                for sym, w in filtered.items():
                    if sectors.get(sym, "UNKNOWN") == sec:
                        filtered[sym] = w * scale

    return filtered, rejections


def _check_frame(name: str, frame: pd.DataFrame, close: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a DataFrame")
    if not frame.index.equals(close.index):
        raise ValueError(
            f"{name}.index does not match close.index "
            f"({len(frame.index)} vs {len(close.index)} rows). Align explicitly; "
            "silent reindexing here would shift the return attribution by an "
            "unknown number of bars."
        )
    missing = frame.columns.difference(close.columns)
    if len(missing):
        raise ValueError(f"{name} has {len(missing)} columns absent from close, e.g. {list(missing[:5])}")


def simulate_long_short(
    *,
    long_weights: pd.DataFrame,
    short_weights: pd.DataFrame,
    close: pd.DataFrame,
    execution_lag: int = 1,
    cost_per_side: float = DEFAULT_COST_PER_SIDE,
    max_abs_daily_return: float | None = DEFAULT_MAX_ABS_DAILY_RETURN,
) -> PortfolioResult:
    """Simulate a dollar-weighted long/short book."""
    if not isinstance(execution_lag, (int, np.integer)) or isinstance(execution_lag, bool):
        raise TypeError("execution_lag must be an int")
    if execution_lag < 1:
        raise ValueError(
            f"execution_lag must be >= 1, got {execution_lag}. A weight formed from "
            "bar i's features cannot earn bar i's own return — that is the lookahead "
            "this module exists to prevent."
        )
    if cost_per_side < 0:
        raise ValueError("cost_per_side must be non-negative")

    _check_frame("long_weights", long_weights, close)
    _check_frame("short_weights", short_weights, close)

    columns = long_weights.columns.union(short_weights.columns)
    px = close[columns].astype(float)
    long_w = long_weights.reindex(columns=columns).fillna(0.0).astype(float)
    short_w = short_weights.reindex(columns=columns).fillna(0.0).astype(float)

    daily_ret = px.pct_change(1)
    if max_abs_daily_return is not None:
        extreme = daily_ret.abs() > float(max_abs_daily_return)
        n_extreme_masked = int(extreme.to_numpy().sum())
        daily_ret = daily_ret.mask(extreme, 0.0)
    else:
        n_extreme_masked = 0
    daily_ret = daily_ret.fillna(0.0)

    held_long = long_w.shift(execution_lag).fillna(0.0)
    held_short = short_w.shift(execution_lag).fillna(0.0)

    gross = (held_long * daily_ret).sum(axis=1) - (held_short * daily_ret).sum(axis=1)

    turnover_per_bar = held_long.diff().abs().sum(axis=1) + held_short.diff().abs().sum(axis=1)
    turnover_per_bar.iloc[0] = held_long.iloc[0].abs().sum() + held_short.iloc[0].abs().sum()
    net = gross - turnover_per_bar * cost_per_side

    n_bars = int(len(gross))
    gross_std = float(gross.std())
    net_std = float(net.std())

    annual_volatility = gross_std * np.sqrt(TRADING_DAYS)
    gross_annual = float(gross.mean()) * TRADING_DAYS
    net_annual = float(net.mean()) * TRADING_DAYS

    gross_sharpe = float(gross.mean() / gross_std * np.sqrt(TRADING_DAYS)) if gross_std > 0 else 0.0
    net_sharpe = float(net.mean() / net_std * np.sqrt(TRADING_DAYS)) if net_std > 0 else 0.0

    equity = (1.0 + net.clip(lower=-0.99)).cumprod()
    peak = equity.cummax()
    max_drawdown = float(((peak - equity) / peak).max()) if n_bars else 0.0
    final = float(equity.iloc[-1]) if n_bars else 1.0
    compounded = (final ** (TRADING_DAYS / n_bars) - 1.0) if (n_bars > 0 and final > 0) else -1.0

    return PortfolioResult(
        execution_lag=int(execution_lag),
        n_bars=n_bars,
        gross_annual_return=gross_annual,
        net_annual_return=net_annual,
        annual_volatility=float(annual_volatility),
        gross_sharpe=gross_sharpe,
        sharpe=net_sharpe,
        compounded_annual_return=float(compounded),
        max_drawdown=max_drawdown,
        annual_turnover=float(turnover_per_bar.mean() * TRADING_DAYS),
        cost_drag=float(turnover_per_bar.mean() * TRADING_DAYS * cost_per_side),
        exposure=float((gross != 0).mean()) if n_bars else 0.0,
        n_extreme_masked=n_extreme_masked,
        net_returns=net,
        gross_returns=gross,
    )


def cross_sectional_rank_ic(
    signal: pd.DataFrame,
    forward_return: pd.DataFrame,
    *,
    min_names: int = 20,
    min_abs_signal: float | None = None,
    periods_per_year: float = TRADING_DAYS,
) -> dict[str, float]:
    """Per-bar Spearman IC of `signal` against `forward_return`."""
    if not signal.index.equals(forward_return.index):
        raise ValueError("signal.index does not match forward_return.index")

    ics: list[float] = []
    for i in range(len(signal)):
        a = signal.iloc[i]
        b = forward_return.iloc[i]
        valid = a.notna() & b.notna()
        if min_abs_signal is not None:
            valid &= a.abs() > float(min_abs_signal)
        if int(valid.sum()) < min_names:
            continue
        ic = a[valid].corr(b[valid], method="spearman")
        if not np.isnan(ic):
            ics.append(float(ic))

    if not ics:
        return {"mean_rank_ic": 0.0, "rank_ic_std": 0.0, "rank_icir": 0.0, "n_bars": 0}

    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std())
    return {
        "mean_rank_ic": mean,
        "rank_ic_std": std,
        "rank_icir": float(mean / std * np.sqrt(periods_per_year)) if std > 0 else 0.0,
        "n_bars": len(ics),
    }
