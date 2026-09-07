"""Execution gates: session phase, expiry policy, routing, sizing.

The behaviours pinned here are the ones whose failure mode is silent. A
mis-set session boundary, a fabricated spread, or a position sized off a
premium percentage all produce plausible numbers and no error, so each gets a
test that fails loudly rather than a smoke test that only checks a call
returns.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edge.research.execution_gates import (
    DELTA_CORRIDOR,
    InitialBalance,
    classify_session_phase,
    expiry_policy,
    fractional_kelly,
    initial_balance,
    position_size,
    select_contract,
    session_gate,
    spread_friction,
)
from edge.research.zero_dte import EXCHANGE_TZ


def _et(y, m, d, hh, mm) -> datetime:
    """An aware exchange-local timestamp."""
    return datetime(y, m, d, hh, mm, tzinfo=EXCHANGE_TZ)


# --------------------------------------------------------------------------
# Session phases
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hh,mm,expected",
    [
        (8, 30, "pre_market"),
        (9, 29, "pre_market"),
        (9, 30, "opening_auction"),
        (9, 44, "opening_auction"),
        (9, 45, "morning_initiative"),
        (11, 29, "morning_initiative"),
        (11, 30, "lunch_consolidation"),
        (13, 29, "lunch_consolidation"),
        (13, 30, "afternoon_acceleration"),
        (15, 29, "afternoon_acceleration"),
        (15, 30, "liquidation"),
        (16, 0, "post_market"),
    ],
)
def test_session_boundaries_are_exact(hh, mm, expected):
    # 2026-09-02 is a Wednesday.
    assert classify_session_phase(_et(2026, 9, 2, hh, mm)) == expected


def test_naive_datetime_is_rejected_not_assumed_local():
    """A naive timestamp read as exchange-local shifts every boundary by hours."""
    with pytest.raises(ValueError, match="aware datetime"):
        classify_session_phase(datetime(2026, 9, 2, 10, 30))


def test_utc_input_is_converted_not_read_literally():
    """14:30 UTC is 10:30 ET -- the morning window, not the lunch one."""
    assert classify_session_phase(datetime(2026, 9, 2, 14, 30, tzinfo=timezone.utc)) == (
        "morning_initiative"
    )


def test_weekend_is_never_a_trading_phase():
    assert classify_session_phase(_et(2026, 9, 5, 10, 30)) == "post_market"  # Saturday


def test_opening_auction_forbids_entry():
    gate = session_gate(_et(2026, 9, 2, 9, 35))
    assert gate.may_enter is False
    assert gate.permitted_setups == frozenset()


def test_lunch_permits_reversion_but_not_breakouts():
    gate = session_gate(_et(2026, 9, 2, 12, 0))
    assert gate.may_enter is True
    assert "mean_reversion" in gate.permitted_setups
    assert "expansion" not in gate.permitted_setups


def test_flatten_flag_turns_on_at_1545():
    assert session_gate(_et(2026, 9, 2, 15, 44)).must_be_flat is False
    assert session_gate(_et(2026, 9, 2, 15, 45)).must_be_flat is True


# --------------------------------------------------------------------------
# Initial Balance
# --------------------------------------------------------------------------


def _bar(hh, mm, high, low):
    return {"ts": _et(2026, 9, 2, hh, mm), "high": high, "low": low}


def test_initial_balance_uses_only_the_first_fifteen_minutes():
    bars = [
        _bar(9, 30, 101.0, 100.0),
        _bar(9, 35, 102.0, 100.5),
        _bar(9, 40, 101.5, 99.5),
        _bar(9, 45, 110.0, 90.0),  # outside the window; must not widen the IB
        _bar(10, 0, 120.0, 80.0),
    ]
    ib = initial_balance(bars)
    assert ib.measurable is True
    assert (ib.high, ib.low) == (102.0, 99.5)
    assert ib.bar_count == 3
    assert ib.width == pytest.approx(2.5)


def test_initial_balance_is_unmeasurable_before_the_open():
    ib = initial_balance([_bar(9, 0, 101.0, 100.0)])
    assert ib.measurable is False
    assert ib.high is None and ib.low is None
    assert "09:30-09:45" in ib.reason


def test_naive_bar_timestamps_are_skipped_not_placed_in_the_window():
    """A bar that cannot be located in the session must not widen the range."""
    bars = [
        _bar(9, 30, 101.0, 100.0),
        {"ts": datetime(2026, 9, 2, 9, 35), "high": 999.0, "low": 1.0},
    ]
    ib = initial_balance(bars)
    assert ib.measurable is True
    assert (ib.high, ib.low) == (101.0, 100.0)


def test_empty_input_reports_a_reason():
    assert initial_balance([]) == InitialBalance(False, None, None, 0, None, "no bars supplied")


# --------------------------------------------------------------------------
# Expiry policy
# --------------------------------------------------------------------------


def test_spy_runs_0dte_only_before_the_theta_cutoff():
    morning = expiry_policy("SPY", _et(2026, 9, 2, 10, 0))
    assert morning.zero_dte_permitted is True
    assert morning.admits(0)

    afternoon = expiry_policy("SPY", _et(2026, 9, 2, 14, 0))
    assert afternoon.zero_dte_permitted is False
    assert not afternoon.admits(0)
    assert afternoon.admits(1)


def test_friday_afternoon_index_can_still_reach_monday():
    """"1DTE" means the next expiry; on a Friday that is three days out.

    An exact dte == 1 test routes nothing on Friday afternoon -- the very
    session the post-13:30 rule exists to serve.
    """
    friday = expiry_policy("SPY", _et(2026, 9, 4, 14, 0))
    assert friday.admits(3)
    assert not friday.admits(0)
    assert not friday.admits(4)


def test_single_names_never_run_0dte():
    for hour in (10, 14):
        policy = expiry_policy("TSLA", _et(2026, 9, 2, hour, 0))
        assert policy.zero_dte_permitted is False
        assert not policy.admits(0)
        assert policy.admits(2) and policy.admits(5)


def test_thursday_entry_reaches_past_the_weekend():
    policy = expiry_policy("MSTR", _et(2026, 9, 3, 10, 0))  # Thursday
    assert policy.min_dte == 7 and policy.max_dte == 14


def test_weekend_does_not_claim_a_thursday_friday_entry():
    """Saturday is not late in the week; it is not a trading day at all."""
    saturday = expiry_policy("MSTR", _et(2026, 9, 5, 10, 0))
    assert (saturday.min_dte, saturday.max_dte) == (2, 5)
    assert "Thu/Fri" not in saturday.rationale


# --------------------------------------------------------------------------
# Spread friction
# --------------------------------------------------------------------------


def test_missing_quotes_are_unmeasured_never_zero_spread():
    """The live option feed carries no bid/ask; absence must not read as free."""
    check = spread_friction("SPY", None, None)
    assert check.measurable is False
    assert check.passes is False
    assert check.ratio_pct is None


def test_spread_ratio_and_per_symbol_caps():
    tight = spread_friction("SPY", 1.00, 1.01)
    assert tight.ratio_pct == pytest.approx(0.995, abs=1e-3)
    assert tight.passes is True

    # The identical spread fails on SPY's 1% cap but clears MSTR's 5% one.
    assert spread_friction("SPY", 1.00, 1.03).passes is False
    assert spread_friction("MSTR", 1.00, 1.03).passes is True


def test_crossed_book_is_rejected():
    assert spread_friction("SPY", 1.05, 1.00).measurable is False


# --------------------------------------------------------------------------
# Contract routing
# --------------------------------------------------------------------------


def _chain(strikes, expiry, right="call", **extra):
    return [{"strike": k, "right": right, "expiry": expiry, "iv": 0.18, **extra} for k in strikes]


def test_router_picks_the_middle_of_the_delta_corridor():
    rows = _chain(range(600, 681, 2), "2026-09-02")
    choice = select_contract(
        symbol="SPY",
        direction="long",
        chain_rows=rows,
        spot=640.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=False,
    )
    assert choice.measurable is True
    lo, hi = DELTA_CORRIDOR
    assert lo <= abs(choice.delta) <= hi + 0.02
    assert abs(abs(choice.delta) - (lo + hi) / 2) < 0.1


def test_router_admits_the_at_the_money_strike():
    """ATM delta exceeds 0.50 by the drift term; the corridor must still take it."""
    rows = _chain([640], "2026-09-02")
    choice = select_contract(
        symbol="SPY",
        direction="long",
        chain_rows=rows,
        spot=640.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=False,
    )
    assert choice.measurable is True
    assert abs(choice.delta) > 0.50


def test_router_enforces_the_expiry_policy():
    """A 0DTE chain is unroutable for a single name at any hour."""
    rows = _chain(range(400, 441, 5), "2026-09-02")
    choice = select_contract(
        symbol="TSLA",
        direction="long",
        chain_rows=rows,
        spot=420.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=False,
    )
    assert choice.measurable is False
    assert "DTE policy" in choice.reason


def test_unmeasured_spread_is_surfaced_as_a_warning_when_not_required():
    rows = _chain(range(600, 681, 2), "2026-09-02")
    choice = select_contract(
        symbol="SPY",
        direction="long",
        chain_rows=rows,
        spot=640.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=False,
    )
    assert choice.spread.measurable is False
    assert any("unchecked" in w for w in choice.warnings)


def test_requiring_spread_rejects_a_quoteless_chain():
    rows = _chain(range(600, 681, 2), "2026-09-02")
    choice = select_contract(
        symbol="SPY",
        direction="long",
        chain_rows=rows,
        spot=640.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=True,
    )
    assert choice.measurable is False


def test_rows_without_delta_or_iv_are_counted_not_assigned_one():
    rows = [{"strike": 640, "right": "call", "expiry": "2026-09-02"}]
    choice = select_contract(
        symbol="SPY",
        direction="long",
        chain_rows=rows,
        spot=640.0,
        moment=_et(2026, 9, 2, 10, 0),
        require_spread=False,
    )
    assert choice.measurable is False
    assert "no delta and no IV" in choice.reason


# --------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------


def test_kelly_matches_the_closed_form():
    # p=0.55, b=1.5 -> (0.55*1.5 - 0.45)/1.5 = 0.25; one-fifth of that is 0.05.
    assert fractional_kelly(0.55, 1.5) == pytest.approx(0.05)


def test_no_edge_sizes_to_zero_not_to_a_short():
    assert fractional_kelly(0.30, 1.0) == 0.0


def test_position_size_is_capped_at_the_risk_ceiling():
    size = position_size(
        equity=100_000,
        win_rate=0.80,          # a Kelly well above the ceiling
        payoff_ratio=3.0,
        entry_premium=2.50,
        premium_at_stop=1.60,
    )
    assert size.capped is True
    assert size.risk_fraction == pytest.approx(0.015)
    assert size.risk_dollars == pytest.approx(1500.0)
    # $0.90 of premium at risk * 100 = $90 per contract.
    assert size.contracts == 16


def test_zero_edge_trades_nothing():
    size = position_size(
        equity=100_000,
        win_rate=0.30,
        payoff_ratio=1.0,
        entry_premium=2.50,
        premium_at_stop=1.60,
    )
    assert size.contracts == 0
    assert "no edge" in size.reason


def test_contract_too_expensive_for_the_budget_returns_zero_not_one():
    size = position_size(
        equity=10_000,
        win_rate=0.55,
        payoff_ratio=1.5,
        entry_premium=40.0,
        premium_at_stop=10.0,
    )
    assert size.contracts == 0
    assert "above the" in size.reason


def test_stop_above_entry_is_rejected():
    """A 'stop' that is not a loss cannot size anything."""
    with pytest.raises(ValueError, match="must be below entry_premium"):
        position_size(
            equity=100_000,
            win_rate=0.55,
            payoff_ratio=1.5,
            entry_premium=2.00,
            premium_at_stop=2.50,
        )
