"""Unit tests for the Auction Market Theory (AMT) engine.

All fixtures are synthetic bars built in this file -- the suite must not
depend on parquet files under data/ (gitignored, absent in a fresh checkout).
"""

from datetime import date, timedelta

from research.amt_engine import (
    analyze_amt,
    build_profile,
    build_trade_plan,
    evaluate_bars,
    find_balance_window,
    rotation_statistics,
)


# ---------------------------------------------------------------------------
# Synthetic bar builders
# ---------------------------------------------------------------------------

def _bar(dt, o, h, l, c, v):
    return {"date": dt, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _dates(n, start="2026-01-05"):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() + "T00:00:00" for i in range(n)]


def _oscillating_bars(n=60, mid=100.0, amp=5.0):
    """Rotates around `mid`, dwelling near the centre and only briefly
    touching the extremes -- a textbook balance area."""
    bars = []
    for i, d in enumerate(_dates(n)):
        cycle = i % 6
        if cycle == 3:
            c = mid + amp
        elif cycle == 5:
            c = mid - amp
        else:
            c = mid + (0.3 if cycle % 2 == 0 else -0.3)
        o = mid
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        bars.append(_bar(d, o, h, l, c, 1_000_000))
    return bars


def _uptrend_bars(n=60, start_price=100.0, step=1.0):
    """A clean, unbroken uptrend -- initiative activity, not balance."""
    bars = []
    price = start_price
    for d in _dates(n):
        o = price
        c = price + step
        h = c + 0.1
        l = o - 0.1
        bars.append(_bar(d, o, h, l, c, 1_000_000))
        price = c
    return bars


# ---------------------------------------------------------------------------
# 1. Balance regime + centred POC
# ---------------------------------------------------------------------------

def test_oscillating_range_is_balance_with_centered_poc():
    bars = _oscillating_bars()
    res = evaluate_bars(bars, "OSC", "1D")
    assert res["available"] is True
    assert res["regime"]["label"] == "BALANCE"
    poc = res["composite"]["poc"]
    assert abs(poc - 100.0) < 2.0


# ---------------------------------------------------------------------------
# 2. Uptrend is not balance and the plan waits
# ---------------------------------------------------------------------------

def test_clean_uptrend_is_not_balance_and_plan_waits():
    bars = _uptrend_bars()
    res = evaluate_bars(bars, "TREND", "1D")
    assert res["available"] is True
    assert res["regime"]["label"] != "BALANCE"
    plan = res["trade_plan"]
    assert plan["bias"] == "NEUTRAL / WAIT"
    assert plan["risk_reward_unavailable_reason"] is not None


# ---------------------------------------------------------------------------
# 3. Value area bounds
# ---------------------------------------------------------------------------

def test_build_profile_value_area_bounds():
    bars = _oscillating_bars()
    prof = build_profile(bars)
    assert prof is not None
    assert 0.70 <= prof["va_volume_share"] <= 1.0
    assert prof["val"] < prof["poc"] < prof["vah"]


# ---------------------------------------------------------------------------
# 4. Volume is spread across the bar range, not dumped at the close
# ---------------------------------------------------------------------------

def test_volume_distributed_across_bar_range_not_dumped_at_close():
    d = _dates(1)[0]
    close = 100.0
    narrow = [_bar(d, 100.0, 100.2, 99.8, close, 1_000_000)]
    wide = [_bar(d, 100.0, 120.0, 80.0, close, 1_000_000)]

    p_narrow = build_profile(narrow, n_bins=20)
    p_wide = build_profile(wide, n_bins=20)
    assert p_narrow is not None and p_wide is not None
    assert p_narrow["bins"] != p_wide["bins"]

    # The bin at the bottom of the wide bar's range (near 80, far from the
    # 100 close) must carry volume. If volume were dumped at the close only,
    # every bin but the one holding 100 would be empty regardless of range.
    far_bin_wide = p_wide["bins"][0]
    assert far_bin_wide["volume"] > 0


# ---------------------------------------------------------------------------
# 5. Responsive long at the value-area low
# ---------------------------------------------------------------------------

def test_responsive_long_at_value_area_low():
    composite = {"poc": 100.0, "vah": 105.0, "val": 95.0, "high": 106.0, "low": 94.0}
    regime = {"label": "BALANCE"}
    location = {
        "close": 95.0,
        "zone": "VAL_EDGE",
        "acceptance": "none",
        "failed_auction": "none",
        "failed_auction_extreme": None,
    }
    plan = build_trade_plan(regime, composite, location, atr=2.0)
    assert plan["bias"] == "LONG"
    assert plan["entry"] is not None
    assert plan["stop"] is not None
    assert plan["target_1"] is not None
    assert plan["risk_reward"] is not None
    assert plan["risk_reward"] > 0


# ---------------------------------------------------------------------------
# 6. find_balance_window truncates when value migrates
# ---------------------------------------------------------------------------

def test_find_balance_window_truncates_on_value_migration():
    sessions = [
        {"start": "s1", "end": "e1", "bar_count": 8, "val": 100, "vah": 110, "poc": 105, "overlap_prev": None},
        {"start": "s2", "end": "e2", "bar_count": 8, "val": 101, "vah": 111, "poc": 106, "overlap_prev": 0.9},
        {"start": "s3", "end": "e3", "bar_count": 8, "val": 102, "vah": 112, "poc": 107, "overlap_prev": 0.9},
        # Value migrates hard here: no overlap with the prior balance.
        {"start": "s4", "end": "e4", "bar_count": 8, "val": 150, "vah": 160, "poc": 155, "overlap_prev": 0.0},
        {"start": "s5", "end": "e5", "bar_count": 8, "val": 151, "vah": 161, "poc": 156, "overlap_prev": 0.9},
        {"start": "s6", "end": "e6", "bar_count": 8, "val": 152, "vah": 162, "poc": 157, "overlap_prev": 0.9},
    ]
    bars = [{} for _ in range(48)]

    window = find_balance_window(sessions, bars, "1D")
    assert window["truncated"] is True
    assert window["sessions"] == 3
    assert window["start"] == "s4"
    assert window["end"] == "e6"
    assert window["bar_index_start"] == 24


# ---------------------------------------------------------------------------
# 7. Honesty guards
# ---------------------------------------------------------------------------

def test_rotation_statistics_withholds_rates_below_min_attempts():
    stats = rotation_statistics([])
    assert stats["val_attempts"] == 0
    assert stats["val_rotation_rate"] is None
    assert stats["vah_rotation_rate"] is None


def test_analyze_amt_nonexistent_symbol_is_honest_and_does_not_raise():
    res = analyze_amt("ZZZZNOTREAL", "1D", 100)
    assert res["available"] is False
    assert res["reason"]


# ---------------------------------------------------------------------------
# 8. No fabricated constants: different inputs, different scores
# ---------------------------------------------------------------------------

def test_different_inputs_produce_different_regime_scores():
    trend = evaluate_bars(_uptrend_bars(), "TREND", "1D")
    osc = evaluate_bars(_oscillating_bars(), "OSC", "1D")
    assert trend["available"] and osc["available"]
    assert trend["regime"]["score"] != osc["regime"]["score"]


# ---------------------------------------------------------------------------
# 9. build_trade_plan structural + reward-to-risk guards
# ---------------------------------------------------------------------------

def _assert_level_ordering_invariant(plan):
    """A LONG must have stop < entry < target_1; a SHORT the mirror image.
    Anything else (NEUTRAL / WAIT, or missing levels) is exempt."""
    bias = plan["bias"]
    if bias == "LONG":
        assert plan["entry"] is not None and plan["stop"] is not None and plan["target_1"] is not None
        assert plan["stop"] < plan["entry"] < plan["target_1"], plan
    elif bias == "SHORT":
        assert plan["entry"] is not None and plan["stop"] is not None and plan["target_1"] is not None
        assert plan["target_1"] < plan["entry"] < plan["stop"], plan


def test_failed_auction_trap_at_wrong_edge_does_not_produce_inverted_plan():
    """Regression for the PG repro: a look-below-fail happened a bar or two
    ago (extreme 142.5), but the close has since run all the way to the
    value-area high (146.3, zone VAH_EDGE). Trading the stale trap thesis
    put the entry at the VAH (worst place to buy) with target_1 below entry
    -- a LONG whose target is a loss. The gate must fall through to the
    normal zone-based logic instead."""
    composite = {"poc": 144.2865, "vah": 145.956, "val": 143.253, "high": 150.0, "low": 140.0}
    regime = {"label": "BALANCE"}
    location = {
        "close": 146.3,
        "zone": "VAH_EDGE",
        "acceptance": "none",
        "failed_auction": "look_below_fail",
        "failed_auction_extreme": 142.5,
    }
    plan = build_trade_plan(regime, composite, location, atr=2.0)

    # The specific trap: a LONG whose first target sits below its entry.
    if plan["bias"] == "LONG" and plan["entry"] is not None and plan["target_1"] is not None:
        assert plan["target_1"] >= plan["entry"], plan

    # And the general structural invariant must hold for whatever came back.
    _assert_level_ordering_invariant(plan)


def test_reward_below_minimum_downgrades_bias_but_keeps_levels():
    """A responsive long whose stop sits far below the range (a deep range
    low) has plenty of risk and little reward to the POC: RR < 1.0. The bias
    must be downgraded to NEUTRAL / WAIT -- a bias chip that still says LONG
    next to a disqualifying reason is self-contradictory -- but the computed
    levels must stay visible, not be nulled out."""
    composite = {"poc": 102.0, "vah": 103.0, "val": 100.0, "high": 103.0, "low": 85.0}
    regime = {"label": "BALANCE"}
    location = {
        "close": 100.0,
        "zone": "VAL_EDGE",
        "acceptance": "none",
        "failed_auction": "none",
        "failed_auction_extreme": None,
    }
    plan = build_trade_plan(regime, composite, location, atr=1.0)

    assert plan["bias"] == "NEUTRAL / WAIT"
    assert plan["risk_reward"] is not None
    assert plan["risk_reward"] < 1.0
    assert plan["entry"] is not None
    assert plan["stop"] is not None
    assert plan["target_1"] is not None
    assert plan["risk_reward_unavailable_reason"]


def test_level_ordering_invariant_holds_across_synthetic_fixtures():
    """Property-style guard: for any plan with bias LONG or SHORT, the level
    ordering invariant must hold -- across the bar fixtures already used
    elsewhere in this suite plus a spread of build_trade_plan location/
    composite combinations (clean edges, both failed-auction directions, the
    stale-trap case, sub-threshold RR, and inside-value)."""
    for bars, symbol in [(_oscillating_bars(), "OSC"), (_uptrend_bars(), "TREND")]:
        res = evaluate_bars(bars, symbol, "1D")
        assert res["available"] is True
        _assert_level_ordering_invariant(res["trade_plan"])

    regime = {"label": "BALANCE"}
    composite = {"poc": 100.0, "vah": 105.0, "val": 95.0, "high": 106.0, "low": 94.0}
    scenarios = [
        # Clean responsive long / short at the edges.
        {"close": 95.0, "zone": "VAL_EDGE", "acceptance": "none", "failed_auction": "none", "failed_auction_extreme": None},
        {"close": 105.0, "zone": "VAH_EDGE", "acceptance": "none", "failed_auction": "none", "failed_auction_extreme": None},
        # Failed auction at the edge that actually failed (trap thesis intact).
        {"close": 104.0, "zone": "VAH_EDGE", "acceptance": "none", "failed_auction": "look_above_fail", "failed_auction_extreme": 107.0},
        {"close": 96.0, "zone": "VAL_EDGE", "acceptance": "none", "failed_auction": "look_below_fail", "failed_auction_extreme": 93.0},
        # Stale trap: failed auction extreme is stale, close ran to the far edge.
        {"close": 104.5, "zone": "VAH_EDGE", "acceptance": "none", "failed_auction": "look_below_fail", "failed_auction_extreme": 93.0},
        {"close": 95.5, "zone": "VAL_EDGE", "acceptance": "none", "failed_auction": "look_above_fail", "failed_auction_extreme": 107.0},
        # Inside value: no edge, no trade.
        {"close": 100.0, "zone": "POC", "acceptance": "none", "failed_auction": "none", "failed_auction_extreme": None},
    ]
    for location in scenarios:
        plan = build_trade_plan(regime, composite, location, atr=1.0)
        _assert_level_ordering_invariant(plan)

    # A sub-threshold-RR long, from the deep-range-low composite above.
    thin_composite = {"poc": 102.0, "vah": 103.0, "val": 100.0, "high": 103.0, "low": 85.0}
    thin_location = {"close": 100.0, "zone": "VAL_EDGE", "acceptance": "none", "failed_auction": "none", "failed_auction_extreme": None}
    _assert_level_ordering_invariant(build_trade_plan(regime, thin_composite, thin_location, atr=1.0))


def test_failed_auction_trap_dies_once_price_trades_through_the_extreme():
    """Regression for the AMD repro. A look-below-fail printed its low at
    463.68 and closed back inside value, but the NEXT bar closed at 454.785 --
    below the failed low. The trap is over: the sellers it claimed were
    trapped are in profit, and the plan was still offering a long at the
    value-area low (464.85), ten points ABOVE the market, on a thesis its own
    invalidation line already called dead.

    The setup must not survive price trading through the extreme it rests on,
    and any entry that is offered must be reachable from the close."""
    composite = {"poc": 481.6629, "vah": 498.478, "val": 464.8478, "high": 500.0, "low": 451.0}
    regime = {"label": "BALANCE"}
    location = {
        "close": 454.785,
        "zone": "BELOW_VALUE",
        "acceptance": "none",
        "failed_auction": "look_below_fail",
        "failed_auction_extreme": 463.68,
    }
    plan = build_trade_plan(regime, composite, location, atr=19.18)

    assert plan["setup"] != "Look below and fail at VAL", (
        "stale trap survived price trading through the failed low",
        plan,
    )
    # A long entry must never be above the market -- that fill is fiction.
    if plan["bias"] == "LONG" and plan["entry"] is not None:
        assert plan["entry"] <= location["close"] + 1e-9, plan
    _assert_level_ordering_invariant(plan)


def test_live_failed_auction_still_produces_its_trap_plan():
    """The mirror of the above: while the close is still holding ABOVE the
    failed low, the trap thesis is alive and must be traded, so the gate
    cannot simply disable failed-auction setups altogether."""
    composite = {"poc": 481.6629, "vah": 498.478, "val": 464.8478, "high": 500.0, "low": 451.0}
    regime = {"label": "BALANCE"}
    location = {
        "close": 466.0,
        "zone": "VAL_EDGE",
        "acceptance": "none",
        "failed_auction": "look_below_fail",
        "failed_auction_extreme": 463.68,
    }
    plan = build_trade_plan(regime, composite, location, atr=19.18)

    assert plan["setup"] == "Look below and fail at VAL", plan
    assert plan["entry"] is not None and plan["entry"] <= location["close"] + 1e-9
    _assert_level_ordering_invariant(plan)
