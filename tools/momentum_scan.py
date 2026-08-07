"""Pure computation for the Ross Cameron 'Five Pillars' momentum pre-scan.

No network, no filesystem writes -- callers hand this module in-memory
OHLCV frames and a float lookup, and get back a ranked candidate list. Kept
separate from api_server.py so it is testable without booting the server,
mirroring how render_dashboard.py holds get_dashboard_data's logic and
api_server.py only wraps/caches it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

RVOL_LOOKBACK = 50
RVOL_MIN_MULTIPLE = 5.0
PRICE_MIN = 2.0
PRICE_MAX = 20.0
GAP_MIN_PCT = 0.02
GAP_SWEET_LOW = 0.10
GAP_SWEET_HIGH = 0.30
FLOAT_QUALIFY_MAX = 20_000_000
FLOAT_OPTIMAL_MAX = 3_000_000


def compute_rvol(volumes: pd.Series) -> float | None:
    """Last session's volume / mean of the RVOL_LOOKBACK sessions before it.
    None if there isn't enough history yet."""
    if len(volumes) < RVOL_LOOKBACK + 1:
        return None
    last = float(volumes.iloc[-1])
    baseline = volumes.iloc[-(RVOL_LOOKBACK + 1):-1].mean()
    if not baseline or baseline <= 0:
        return None
    return last / float(baseline)


def compute_gap_pct(open_price: float, prior_close: float) -> float | None:
    if not prior_close:
        return None
    return (open_price - prior_close) / prior_close


def compute_day_change_pct(close: float, prior_close: float) -> float | None:
    if not prior_close:
        return None
    return (close - prior_close) / prior_close


def price_qualifies(price: float) -> bool:
    return PRICE_MIN <= price <= PRICE_MAX


def gap_qualifies(gap_pct: float | None) -> bool:
    return gap_pct is not None and gap_pct >= GAP_MIN_PCT


def rvol_qualifies(rvol: float | None) -> bool:
    return rvol is not None and rvol > RVOL_MIN_MULTIPLE


def float_badge(float_shares: float | None) -> str:
    if float_shares is None:
        return "unknown"
    if float_shares < FLOAT_OPTIMAL_MAX:
        return "optimal"
    if float_shares < FLOAT_QUALIFY_MAX:
        return "qualifies"
    return "no"


def build_candidate(symbol: str, df: pd.DataFrame, float_shares: float | None) -> dict | None:
    """One candidate record from a symbol's OHLCV history, or None if there
    isn't enough history to compute RVOL yet."""
    if len(df) < RVOL_LOOKBACK + 1:
        return None
    last = df.iloc[-1]
    prior_close = float(df.iloc[-2]["close"])
    rvol = compute_rvol(df["volume"])
    gap_pct = compute_gap_pct(float(last["open"]), prior_close)
    day_change_pct = compute_day_change_pct(float(last["close"]), prior_close)
    price = float(last["close"])
    return {
        "symbol": symbol,
        "price": price,
        "gap_pct": gap_pct,
        "day_change_pct": day_change_pct,
        "rvol": rvol,
        "float_shares": float_shares,
        "float_badge": float_badge(float_shares),
        "gap_sweet_spot": gap_pct is not None and GAP_SWEET_LOW <= gap_pct <= GAP_SWEET_HIGH,
        "price_qualifies": price_qualifies(price),
        "gap_qualifies": gap_qualifies(gap_pct),
        "rvol_qualifies": rvol_qualifies(rvol),
        "pillars_met": sum([price_qualifies(price), gap_qualifies(gap_pct), rvol_qualifies(rvol)]),
    }


def rank_candidates(records: list[dict]) -> list[dict]:
    """Candidates meeting all three always-computable pillars (price, gap,
    RVOL), ranked by RVOL descending. Float never gates -- it renders as a
    badge on every row instead (float_badge); a meaningful share of the
    universe will have unresolvable float and must not be hidden for it."""
    qualifying = [r for r in records if r["price_qualifies"] and r["gap_qualifies"] and r["rvol_qualifies"]]
    return sorted(qualifying, key=lambda r: r["rvol"], reverse=True)


def build_momentum_scan(
    price_data: dict[str, pd.DataFrame],
    float_data: dict[str, float | None],
    *,
    expected_universe_size: int,
) -> dict:
    """Top-level entry point. price_data maps symbol -> OHLCV DataFrame
    (columns open/high/low/close/volume, DatetimeIndex, most-recent-last).
    float_data maps symbol -> float_shares or None."""
    records = []
    for symbol, df in price_data.items():
        candidate = build_candidate(symbol, df, float_data.get(symbol))
        if candidate is not None:
            records.append(candidate)
    ranked = rank_candidates(records)
    known_float = sum(1 for r in records if r["float_shares"] is not None)
    float_coverage_pct = (known_float / len(records) * 100.0) if records else 0.0
    return {
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "universe_size": len(price_data),
        "expected_universe_size": expected_universe_size,
        "float_coverage_pct": round(float_coverage_pct, 1),
        "candidates": ranked,
    }
