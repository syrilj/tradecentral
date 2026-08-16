"""
Unit tests for Workstream 1: Temporal Integrity & Availability Enforcement.
"""

from __future__ import annotations

import pytest
import pandas as pd

try:
    from edge.research.temporal import (
        MarketRecord,
        FundamentalRecord,
        PointInTimeFilingStore,
        OrderIntent,
        is_available,
        simulate_order_execution,
    )
except ImportError:
    from research.temporal import (
        MarketRecord,
        FundamentalRecord,
        PointInTimeFilingStore,
        OrderIntent,
        is_available,
        simulate_order_execution,
    )


def test_same_bar_fill_is_rejected():
    """Verify that attempting to fill an order against the bar where decision_ts was formed is rejected."""
    t0 = pd.Timestamp("2026-08-01 16:00:00")

    # Bar t record
    bar_t = MarketRecord(
        symbol="AAPL",
        event_ts=t0,
        source_ts=t0,
        received_ts=t0,
        available_ts=t0,
        open=150.0,
        high=152.0,
        low=149.0,
        close=151.0,
        volume=1_000_000,
    )

    order = OrderIntent(
        symbol="AAPL",
        target_weight=0.05,
        order_type="MARKET",
        signal_ts=t0,
        submission_ts=t0,
    )

    # Filling on bar t (where available_ts <= decision_ts) must raise ValueError
    with pytest.raises(ValueError, match="Execution timing violation"):
        simulate_order_execution(order, decision_ts=t0, next_event=bar_t)


def test_unfinished_bar_is_rejected():
    """Verify that incomplete bars cannot be used for execution."""
    t0 = pd.Timestamp("2026-08-01 16:00:00")
    t1 = pd.Timestamp("2026-08-01 16:01:00")

    incomplete_bar = MarketRecord(
        symbol="AAPL",
        event_ts=t1,
        source_ts=t1,
        received_ts=t1,
        available_ts=t1,
        open=151.0,
        high=151.5,
        low=150.8,
        close=151.2,
        volume=50_000,
        is_complete=False,  # Unfinished bar
    )

    order = OrderIntent(
        symbol="AAPL",
        target_weight=0.05,
        order_type="MARKET",
        signal_ts=t0,
        submission_ts=t0,
    )

    with pytest.raises(ValueError, match="incomplete market record"):
        simulate_order_execution(order, decision_ts=t0, next_event=incomplete_bar)


def test_future_fundamental_is_rejected():
    """Verify that fundamental filings are inaccessible prior to their available_ts."""
    q4_end = pd.Timestamp("2025-12-31")
    filing_date = pd.Timestamp("2026-02-15")

    record = FundamentalRecord(
        symbol="AAPL",
        event_ts=q4_end,
        source_ts=filing_date,
        received_ts=filing_date,
        available_ts=filing_date,
        metric="EPS",
        value=2.18,
    )

    jan_decision_ts = pd.Timestamp("2026-01-15")
    feb_decision_ts = pd.Timestamp("2026-02-16")

    assert not is_available(record, jan_decision_ts)
    assert is_available(record, feb_decision_ts)


def test_revised_filing_does_not_replace_original_record():
    """Verify that PointInTimeFilingStore preserves original filing values at historical decision timestamps."""
    store = PointInTimeFilingStore()

    q4_end = pd.Timestamp("2025-12-31")
    original_filing_ts = pd.Timestamp("2026-02-15")
    revision_filing_ts = pd.Timestamp("2026-04-10")

    orig_rec = FundamentalRecord(
        symbol="AAPL",
        event_ts=q4_end,
        source_ts=original_filing_ts,
        received_ts=original_filing_ts,
        available_ts=original_filing_ts,
        metric="REVENUE",
        value=100_000_000.0,
        is_revision=False,
    )

    rev_rec = FundamentalRecord(
        symbol="AAPL",
        event_ts=q4_end,
        source_ts=revision_filing_ts,
        received_ts=revision_filing_ts,
        available_ts=revision_filing_ts,
        metric="REVENUE",
        value=98_000_000.0,
        is_revision=True,
        original_available_ts=original_filing_ts,
    )

    store.add_record(orig_rec)
    store.add_record(rev_rec)

    # Decision on 2026-03-01: revision does not exist yet! Must get original record
    march_rec = store.get_asof("AAPL", "REVENUE", pd.Timestamp("2026-03-01"))
    assert march_rec is not None
    assert march_rec.value == 100_000_000.0

    # Decision on 2026-05-01: revision is now available
    may_rec = store.get_asof("AAPL", "REVENUE", pd.Timestamp("2026-05-01"))
    assert may_rec is not None
    assert may_rec.value == 98_000_000.0


def test_unavailable_symbol_is_excluded():
    """Verify that symbols not yet listed or available as of decision_ts are excluded."""
    listing_ts = pd.Timestamp("2026-05-01")
    decision_ts = pd.Timestamp("2026-03-01")

    record = MarketRecord(
        symbol="NEWCO",
        event_ts=listing_ts,
        source_ts=listing_ts,
        received_ts=listing_ts,
        available_ts=listing_ts,
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=100_000,
    )

    assert not is_available(record, decision_ts)


def test_prediction_changes_when_execution_lag_is_added():
    """Verify that enforcing execution lag alters fill prices and realized returns compared to immediate same-bar fills."""
    t0 = pd.Timestamp("2026-08-01 16:00:00")
    t1 = pd.Timestamp("2026-08-02 09:30:00")

    # Next bar (t+1) open fill
    next_bar = MarketRecord(
        symbol="AAPL",
        event_ts=t1,
        source_ts=t1,
        received_ts=t1,
        available_ts=t1,
        open=152.5,
        high=154.0,
        low=152.0,
        close=153.8,
        volume=500_000,
    )

    order = OrderIntent(
        symbol="AAPL",
        target_weight=0.10,
        order_type="MARKET",
        signal_ts=t0,
        submission_ts=t0,
    )

    fill = simulate_order_execution(order, decision_ts=t0, next_event=next_bar)
    assert fill is not None
    assert fill.fill_ts == t1
    # Fill price includes slippage and costs on top of open price (152.5)
    assert fill.fill_price > 152.5
