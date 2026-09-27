from datetime import datetime, timezone

from edge.daily_plays.options_validation import (OptionsPolicy, generate_occ_symbol, select_directional_contract,
                                                  validate_leg, validate_structure, validate_underlying_quote)


ASOF = datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc)
POLICY = OptionsPolicy(max_quote_age_seconds=30, min_dte=14, max_dte=45, max_spread_pct=.15,
                       min_open_interest=100, min_volume=10)


def leg(**changes):
    result = {"side": "buy", "underlying": "NVDA", "right": "call", "expiry": "2026-08-21", "strike": 180,
              "occ_symbol": "NVDA260821C00180000", "bid": 4.5, "ask": 5.0, "volume": 20, "open_interest": 200,
              "quote_asof_utc": "2026-07-30T14:04:50Z", "provider": "lse", "multiplier": 100,
              "adjusted": False}
    result.update(changes)
    return result


def test_occ_generation_requires_actual_listed_fields_and_matches_supplied_symbol():
    assert generate_occ_symbol(underlying="NVDA", expiry="2026-08-21", right="call", strike=180) == "NVDA260821C00180000"
    assert generate_occ_symbol(underlying="NVDA", expiry=None, right="call", strike=180) is None
    result = validate_leg(leg(occ_symbol="NVDA260821P00180000"), asof_utc=ASOF, policy=POLICY)
    assert result.eligible is False
    assert "occ_symbol_does_not_match_listed_fields" in result.failed_checks
    missing = validate_leg(leg(occ_symbol=None), asof_utc=ASOF, policy=POLICY)
    assert missing.eligible is False
    assert "missing_occ_symbol" in missing.failed_checks


def test_quote_and_liquidity_gates_fail_closed():
    cases = [
        ("stale_quote", {"quote_asof_utc": "2026-07-30T14:04:00Z"}),
        ("crossed_market", {"bid": 5.1, "ask": 5.0}),
        ("zero_or_negative_bid", {"bid": 0}),
        ("excessive_spread", {"bid": 4, "ask": 5}),
        ("insufficient_open_interest", {"open_interest": 99}),
        ("insufficient_volume", {"volume": 9}),
        ("dte_out_of_range", {"expiry": "2026-08-12", "occ_symbol": "NVDA260812C00180000", "dte": 13}),
        ("dte_mismatch", {"dte": 99}),
    ]
    for expected, update in cases:
        result = validate_leg(leg(**update), asof_utc=ASOF, policy=POLICY)
        assert result.eligible is False
        assert result.state == "ABSTAIN"
        assert expected in result.failed_checks


def test_underlying_quote_requires_positive_price_and_independent_fresh_timestamp():
    valid = {
        "underlying": {
            "price": 175.0,
            "quote_asof_utc": "2026-07-30T14:04:50Z",
        }
    }
    assert validate_underlying_quote(valid, asof_utc=ASOF, max_age_seconds=30) == ()
    assert "missing_underlying_quote_timestamp" in validate_underlying_quote(
        {"underlying": {"price": 175.0}},
        asof_utc=ASOF,
        max_age_seconds=30,
    )
    assert "stale_underlying_quote" in validate_underlying_quote(
        {"underlying": {"price": 175.0, "quote_asof_utc": "2026-07-30T14:00:00Z"}},
        asof_utc=ASOF,
        max_age_seconds=30,
    )


def test_degraded_provider_and_risk_budget_cannot_enter():
    fallback = validate_leg(leg(provider="yfinance"), asof_utc=ASOF, policy=POLICY)
    assert fallback.eligible is False
    assert "non_live_or_degraded_provider" in fallback.failed_checks

    result = validate_structure([leg()], asof_utc=ASOF, max_loss_dollars=400, policy=POLICY)
    assert result.eligible is False
    assert result.max_loss_dollars == 500
    assert "risk_budget_exceeded" in result.failed_checks


def test_valid_defined_risk_spread_is_enter_eligible():
    short = leg(side="sell", strike=185, occ_symbol="NVDA260821C00185000", bid=2.0, ask=2.2)
    result = validate_structure([leg(), short], asof_utc=ASOF, max_loss_dollars=300, policy=POLICY)
    assert result.eligible is True
    assert result.state == "ENTER"
    assert result.max_loss_dollars == 300


def shadow_leg(**changes):
    result = leg(expiry="2026-09-18", occ_symbol="NVDA260918C00180000", bid=3.0, ask=3.1,
                 volume=100, open_interest=1000, delta=.49, gamma=.02, iv=.42)
    result.update(changes)
    return result


def test_directional_selection_is_deterministic_and_uses_one_contract_ask_risk():
    farther = shadow_leg(strike=175, occ_symbol="NVDA260918C00175000", delta=.42, ask=3.0)
    selected = select_directional_contract([farther, shadow_leg()], direction="long", asof_utc=ASOF,
                                           account_value=100_000)
    assert selected.eligible is True
    assert selected.leg["occ_symbol"] == "NVDA260918C00180000"
    assert selected.max_loss_dollars == 310


def test_directional_selection_fails_closed_for_greeks_identity_market_and_corporate_action_gaps():
    cases = [
        ("missing_or_out_of_range_delta", {"delta": None}),
        ("missing_or_invalid_gamma", {"gamma": None}),
        ("missing_or_invalid_iv", {"iv": None}),
        ("stale_quote", {"quote_asof_utc": "2026-07-30T14:00:00Z"}),
        ("crossed_market", {"bid": 3.2, "ask": 3.1}),
        ("split_adjusted_contract", {"split_adjusted": True}),
        ("missing_contract_adjustment_metadata", {"adjusted": None}),
        ("nonstandard_contract_multiplier", {"multiplier": None}),
        ("nonstandard_contract_multiplier", {"multiplier": 50}),
        ("occ_symbol_does_not_match_listed_fields", {"occ_symbol": "NVDA260918P00180000"}),
    ]
    for expected, changes in cases:
        result = select_directional_contract([shadow_leg(**changes)], direction="long", asof_utc=ASOF,
                                             account_value=100_000)
        assert result.eligible is False
        assert expected in result.failed_checks


def test_directional_selection_enforces_position_underlying_and_open_risk_budgets():
    over_position = select_directional_contract([shadow_leg(ask=6.0)], direction="long", asof_utc=ASOF,
                                                account_value=100_000)
    assert over_position.eligible is False
    assert "position_risk_budget_exceeded" in over_position.failed_checks

    over_underlying = select_directional_contract([shadow_leg()], direction="long", asof_utc=ASOF,
                                                  account_value=100_000, existing_underlying_risk_dollars=800)
    assert over_underlying.eligible is False
    assert "underlying_risk_budget_exceeded" in over_underlying.failed_checks

    over_aggregate = select_directional_contract([shadow_leg()], direction="long", asof_utc=ASOF,
                                                 account_value=100_000, aggregate_open_risk_dollars=2_800)
    assert over_aggregate.eligible is False
    assert "aggregate_risk_budget_exceeded" in over_aggregate.failed_checks
