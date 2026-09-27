"""
Temporal integrity module enforcing point-in-time availability and execution delay rules.

Primary Rule:
t_available <= t_decision

For any decision made at decision_ts, the system may only use records where
record.available_ts <= decision_ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Union
import pandas as pd


@dataclass(frozen=True)
class MarketRecord:
    symbol: str
    event_ts: pd.Timestamp       # Time the market event occurred (e.g. bar close time)
    source_ts: pd.Timestamp      # Time stamp assigned by exchange/source
    received_ts: pd.Timestamp    # Time received by local feed handler
    available_ts: pd.Timestamp   # Time data became legally available for trading decisions
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    is_complete: bool = True

    def __post_init__(self):
        # Validate timestamp ordering
        if self.available_ts < self.event_ts:
            raise ValueError(f"available_ts ({self.available_ts}) cannot be earlier than event_ts ({self.event_ts})")


@dataclass(frozen=True)
class FundamentalRecord:
    symbol: str
    event_ts: pd.Timestamp       # Period end date (e.g. fiscal quarter end date)
    source_ts: pd.Timestamp      # Document creation/filing date
    received_ts: pd.Timestamp    # Vendor / EDGAR feed arrival date
    available_ts: pd.Timestamp   # Public availability timestamp
    metric: str
    value: float
    is_revision: bool = False
    original_available_ts: Optional[pd.Timestamp] = None


def is_available(record: Union[MarketRecord, FundamentalRecord, Any], decision_ts: pd.Timestamp) -> bool:
    """
    Returns True if record.available_ts <= decision_ts.
    If record does not have available_ts attribute, checks dict key or raises TypeError.
    """
    if isinstance(decision_ts, str):
        decision_ts = pd.Timestamp(decision_ts)

    if hasattr(record, "available_ts"):
        avail_ts = record.available_ts
    elif isinstance(record, dict) and "available_ts" in record:
        avail_ts = record["available_ts"]
    else:
        raise AttributeError("Record must have an 'available_ts' attribute or dict key.")

    if isinstance(avail_ts, str):
        avail_ts = pd.Timestamp(avail_ts)

    return avail_ts <= decision_ts


class PointInTimeFilingStore:
    """
    Store for fundamental filings that preserves original reported records
    and prevents revised records from overwriting original records retroactively.
    """
    def __init__(self):
        self._records: List[FundamentalRecord] = []

    def add_record(self, record: FundamentalRecord) -> None:
        self._records.append(record)

    def get_asof(self, symbol: str, metric: str, decision_ts: pd.Timestamp) -> Optional[FundamentalRecord]:
        """
        Returns the latest fundamental record available as of decision_ts,
        ignoring any revisions published after decision_ts.
        """
        decision_ts = pd.Timestamp(decision_ts)
        valid_records = [
            r for r in self._records
            if r.symbol == symbol and r.metric == metric and r.available_ts <= decision_ts
        ]
        if not valid_records:
            return None
        # Return the record with the latest available_ts (or latest source_ts) up to decision_ts
        valid_records.sort(key=lambda r: (r.available_ts, r.source_ts))
        return valid_records[-1]


@dataclass
class OrderIntent:
    symbol: str
    target_weight: float
    order_type: str  # "MARKET" or "LIMIT"
    limit_price: Optional[float] = None
    signal_ts: pd.Timestamp = pd.Timestamp(0)
    submission_ts: pd.Timestamp = pd.Timestamp(0)


@dataclass
class SimulatedFill:
    symbol: str
    quantity: float
    fill_price: float
    fill_ts: pd.Timestamp
    commission: float
    slippage: float
    impact: float
    realized_cost_bps: float


def simulate_order_execution(
    order: OrderIntent,
    decision_ts: pd.Timestamp,
    next_event: MarketRecord,
    commission_bps: float = 2.5,
    slippage_bps: float = 2.5,
    half_spread_bps: float = 2.5,
    market_impact_multiplier: float = 0.5,
    portfolio_adv: float = 1_000_000.0,
) -> Optional[SimulatedFill]:
    """
    Simulates order execution with strict execution lag enforcement.
    A signal generated on bar t (decision_ts) cannot fill at bar t close.
    Earliest fill occurs on next_event (next bar open / next quote) AFTER decision_ts.
    """
    if next_event.available_ts <= decision_ts:
        raise ValueError(
            f"Execution timing violation: fill event available_ts ({next_event.available_ts}) "
            f"is <= decision_ts ({decision_ts}). Fills must occur AFTER submission."
        )

    if not next_event.is_complete:
        raise ValueError("Cannot fill against an incomplete market record.")

    # Determine base execution price
    if order.order_type == "MARKET":
        if next_event.ask is not None and order.target_weight > 0:
            base_price = next_event.ask
        elif next_event.bid is not None and order.target_weight < 0:
            base_price = next_event.bid
        else:
            base_price = next_event.open
    elif order.order_type == "LIMIT":
        if order.limit_price is None:
            raise ValueError("Limit order requires limit_price.")
        # Limit buy fills if low <= limit_price; limit sell fills if high >= limit_price
        if order.target_weight > 0 and next_event.low <= order.limit_price:
            base_price = min(order.limit_price, next_event.open)
        elif order.target_weight < 0 and next_event.high >= order.limit_price:
            base_price = max(order.limit_price, next_event.open)
        else:
            return None  # Limit order not executable on this bar
    else:
        raise ValueError(f"Unknown order type: {order.order_type}")

    # Calculate costs
    trade_size_val = abs(order.target_weight) * portfolio_adv
    volume_ratio = trade_size_val / max(next_event.volume * base_price, 1e-5)
    impact_bps = market_impact_multiplier * 100.0 * (volume_ratio ** 1.5)

    total_cost_bps = commission_bps + half_spread_bps + slippage_bps + impact_bps
    slippage_dir = 1.0 if order.target_weight > 0 else -1.0
    fill_price = base_price * (1.0 + slippage_dir * (total_cost_bps / 10_000.0))

    return SimulatedFill(
        symbol=order.symbol,
        quantity=order.target_weight,
        fill_price=fill_price,
        fill_ts=next_event.available_ts,
        commission=base_price * (commission_bps / 10_000.0),
        slippage=base_price * (slippage_bps / 10_000.0),
        impact=base_price * (impact_bps / 10_000.0),
        realized_cost_bps=total_cost_bps,
    )
