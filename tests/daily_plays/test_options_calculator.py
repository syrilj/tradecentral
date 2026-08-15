"""Shipped options P/L + Greeks. No second implementation, no golden tables."""
from __future__ import annotations

from edge.daily_plays.options_calculator import evaluate_strategy, expiry_pnl, summarize_setup_play


def test_long_call_expiry_pnl_is_max_spot_minus_strike_times_100_minus_debit():
    assert expiry_pnl(spot=110, strike=100, right="call", debit=500) == 500.0
    assert expiry_pnl(spot=90, strike=100, right="call", debit=500) == -500.0
    out = evaluate_strategy(
        strategy="long_call",
        spot=110,
        strike=100,
        dte=0,
        vol=0.3,
        debit=500,
    )
    at_spot = next(point for point in out["pnl_at_expiry"] if point["spot"] == 110)
    assert at_spot["pnl"] == 500.0


def test_long_put_expiry_pnl_is_max_strike_minus_spot_times_100_minus_debit():
    assert expiry_pnl(spot=90, strike=100, right="put", debit=400) == 600.0
    assert expiry_pnl(spot=110, strike=100, right="put", debit=400) == -400.0
    out = evaluate_strategy(
        strategy="long_put",
        spot=90,
        strike=100,
        dte=0,
        vol=0.3,
        debit=400,
    )
    at_spot = next(point for point in out["pnl_at_expiry"] if point["spot"] == 90)
    assert at_spot["pnl"] == 600.0


def test_two_leg_book_equals_sum_of_each_leg():
    book = evaluate_strategy(
        strategy="long_straddle",
        spot=100,
        strike=100,
        dte=0,
        vol=0.3,
        premium=5.0,
    )
    call = evaluate_strategy(
        strategy="long_call",
        spot=100,
        strike=100,
        dte=0,
        vol=0.3,
        premium=5.0,
    )
    put = evaluate_strategy(
        strategy="long_put",
        spot=100,
        strike=100,
        dte=0,
        vol=0.3,
        premium=5.0,
    )
    for book_pt, call_pt, put_pt in zip(book["pnl_at_expiry"], call["pnl_at_expiry"], put["pnl_at_expiry"]):
        assert book_pt["spot"] == call_pt["spot"] == put_pt["spot"]
        assert book_pt["pnl"] == call_pt["pnl"] + put_pt["pnl"]


def test_setup_play_computes_breakeven_and_level_pnl_without_authorizing():
    play = summarize_setup_play(
        right="call",
        spot=100,
        strike=105,
        premium=2.5,
        dte=35,
        vol=0.34,
        sell=112,
        invalidation=95,
    )
    assert play["strategy"] == "long_call"
    assert play["breakeven"] == 107.5
    assert play["max_loss"] == 250.0
    assert play["debit"] == 250.0
    assert play["decision_authorized"] is False
    assert play["vol_source"] == "contract_iv"
    assert play["greeks"]["delta"] > 0
    assert play["pnl_at_invalidation"] == -250.0
    # 112 spot, 105 strike, debit 250 → intrinsic 700 − 250 = 450
    assert play["pnl_at_sell"] == 450.0


def test_setup_play_without_vol_keeps_greeks_unavailable():
    play = summarize_setup_play(right="put", spot=100, strike=95, premium=3.0)
    assert play["vol_source"] == "unmeasured"
    assert play["greeks"] is None
    assert play["breakeven"] == 92.0
    assert play["max_loss"] == 300.0
    assert play["decision_authorized"] is False


def test_greeks_have_correct_sign():
    call = evaluate_strategy(strategy="long_call", spot=100, strike=100, dte=30, vol=0.35, premium=4.0)
    put = evaluate_strategy(strategy="long_put", spot=100, strike=100, dte=30, vol=0.35, premium=4.0)
    assert call["greeks"]["delta"] > 0
    assert put["greeks"]["delta"] < 0
    assert call["greeks"]["vega"] > 0
    assert put["greeks"]["vega"] > 0
    assert call["greeks"]["gamma"] > 0
    assert put["greeks"]["gamma"] > 0
