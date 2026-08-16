"""
Causal, conservative underlying-return accounting for frozen research horizons
and dynamic cost-aware execution models.

Includes nonlinear market impact approximation:
Impact_{i,t} = eta * sigma_{i,t} * (|Q_{i,t}| / ADV_{i,t})^1.5
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
import pandas as pd

from .labels import FROZEN_HORIZONS


@dataclass(frozen=True)
class DynamicCostModel:
    """Configurable transaction cost model including market impact."""
    commission_bps: float = 2.5
    half_spread_bps: float = 2.5
    slippage_bps: float = 2.5
    impact_multiplier_eta: float = 0.5

    def estimate_order_cost_bps(
        self,
        order_value_usd: float,
        adv_usd: float,
        daily_volatility: float = 0.02,
    ) -> float:
        """
        Calculates total round-trip estimated cost in bps:
        estimated_cost_bps = commission_bps + half_spread_bps + slippage_bps + impact_bps
        where impact_bps = eta * volatility_bps * (order_value / ADV)^1.5
        """
        fixed_bps = self.commission_bps + self.half_spread_bps + self.slippage_bps
        if adv_usd <= 0 or order_value_usd <= 0:
            impact_bps = 0.0
        else:
            vol_bps = daily_volatility * 10_000.0
            participation = min(order_value_usd / adv_usd, 1.0)
            impact_bps = self.impact_multiplier_eta * vol_bps * (participation ** 1.5)

        return fixed_bps + impact_bps


@dataclass(frozen=True)
class UnderlyingCostModel:
    """One-way implementation costs in basis points, applied on both sides."""

    one_way_spread_bps: float = 0.0
    one_way_slippage_bps: float = 0.0
    one_way_fee_bps: float = 0.0

    def __post_init__(self) -> None:
        for name in ("one_way_spread_bps", "one_way_slippage_bps", "one_way_fee_bps"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")

    @property
    def one_way_cost_bps(self) -> float:
        return self.one_way_spread_bps + self.one_way_slippage_bps + self.one_way_fee_bps

    @property
    def round_trip_cost_bps(self) -> float:
        """A deliberately conservative two-sided charge, even on zero movement."""
        return 2.0 * self.one_way_cost_bps

    @property
    def round_trip_cost_return(self) -> float:
        return self.round_trip_cost_bps / 10_000.0


@dataclass(frozen=True)
class DirectionalUnderlyingReturn:
    position: int
    gross_return: float
    net_return: float
    round_trip_cost_bps: float


def normalize_position(value: Any) -> int:
    """Map an explicit directional signal to {-1, 0, +1}; reject ambiguity."""
    if isinstance(value, bool) or value is None or (isinstance(value, float) and math.isnan(value)):
        raise ValueError("position or signal is missing or invalid")
    if isinstance(value, str):
        normalized = value.strip().lower()
        mapping = {"long": 1, "buy": 1, "bullish": 1, "short": -1, "sell": -1, "bearish": -1,
                   "flat": 0, "neutral": 0, "abstain": 0, "": 0}
        if normalized in mapping:
            return mapping[normalized]
        raise ValueError("position or signal is invalid")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("position or signal is invalid") from exc
    if not math.isfinite(numeric) or numeric not in (-1.0, 0.0, 1.0):
        raise ValueError("position must be exactly -1, 0, or 1")
    return int(numeric)


def directional_underlying_return(*, entry_close: float, exit_close: float, position: Any,
                                  costs: UnderlyingCostModel = UnderlyingCostModel()) -> DirectionalUnderlyingReturn:
    """Return underlying directional P&L after pessimistic round-trip costs."""
    entry = float(entry_close); exit_ = float(exit_close)
    if not math.isfinite(entry) or not math.isfinite(exit_) or entry <= 0 or exit_ <= 0:
        raise ValueError("entry_close and exit_close must be finite positive prices")
    side = normalize_position(position)
    gross = side * (exit_ / entry - 1.0)
    net = gross - costs.round_trip_cost_return if side else 0.0
    return DirectionalUnderlyingReturn(side, gross, net, costs.round_trip_cost_bps if side else 0.0)


def directional_underlying_returns(
    rows: pd.DataFrame,
    *,
    horizon_days: int,
    costs: UnderlyingCostModel = UnderlyingCostModel(),
    date_col: str = "trading_date",
    close_col: str = "close",
    position_col: str = "position",
    signal_col: str | None = None,
    symbol_col: str | None = "symbol",
) -> pd.DataFrame:
    """Account for fixed-horizon underlying signals strictly by trading-date rows."""
    if horizon_days not in FROZEN_HORIZONS:
        raise ValueError(f"horizon_days must be one of frozen horizons {FROZEN_HORIZONS}")
    selected_signal_col = signal_col or position_col
    required = {date_col, close_col, selected_signal_col}
    if symbol_col is not None and symbol_col not in rows.columns:
        symbol_col = None
    missing = sorted(required - set(rows.columns))
    if missing:
        raise KeyError(f"missing required columns: {missing}")
    frame = rows.copy()
    if frame.index.has_duplicates:
        raise ValueError("research rows must have a unique row index")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    if dates.isna().any():
        raise ValueError("trading dates must be valid")
    frame[date_col] = dates
    close = pd.to_numeric(frame[close_col], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise ValueError("close prices must be finite positive values")
    frame[close_col] = close.astype(float)
    frame["position"] = [normalize_position(value) for value in frame[selected_signal_col]]
    frame["instrument"] = "underlying"
    frame["return_basis"] = "underlying_close_to_close"
    frame["target_end"] = pd.NaT
    frame["target_close"] = float("nan")
    frame["gross_return"] = float("nan")
    frame["net_return"] = float("nan")
    frame["round_trip_cost_bps"] = float("nan")

    group_key = symbol_col if symbol_col is not None else None
    groups = frame.groupby(group_key, sort=False, dropna=False) if group_key else [(None, frame)]
    for _, group in groups:
        if not group[date_col].is_monotonic_increasing:
            raise ValueError("trading-date rows must be sorted ascending within each symbol")
        if group[date_col].duplicated().any():
            raise ValueError("trading-date rows must be unique within each symbol")
        target_dates = group[date_col].shift(-horizon_days)
        target_close = group[close_col].shift(-horizon_days)
        for index in group.index:
            target = target_close.loc[index]
            if pd.isna(target):
                continue
            result = directional_underlying_return(entry_close=frame.at[index, close_col], exit_close=target,
                                                    position=frame.at[index, "position"], costs=costs)
            frame.at[index, "target_end"] = target_dates.loc[index]
            frame.at[index, "target_close"] = target
            frame.at[index, "gross_return"] = result.gross_return
            frame.at[index, "net_return"] = result.net_return
            frame.at[index, "round_trip_cost_bps"] = result.round_trip_cost_bps
    return frame
