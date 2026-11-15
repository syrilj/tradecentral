import math
from datetime import date, datetime, timezone

import pytest
from edge.daily_plays.options_intelligence import (
    OptionsFilters,
    _best_observation_time,
    _bs_delta,
    _bs_gamma,
    _gex_map,
    _imbalance_confidence,
    _net_gex_at_spots,
    _setup_from_gex_score,
    _usd_millions,
    build_options_intelligence,
)

ASOF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def _chain(right: str, strike: float, gamma: float = 0.02) -> dict:
    return {
        "right": right,
        "expiry": "2026-08-28",
        "strike": strike,
        "bid": 4.9,
        "ask": 5.1,
        "volume": 500,
        "open_interest": 2_000,
        "iv": 0.35,
        "gamma": gamma,
        "multiplier": 100,
        "captured_utc": ASOF.isoformat(),
        "quote_live": True,
        "quote_source": "fixture_live",
        "spot": 100,
    }


def _payload(flow_rows):
    return build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=flow_rows,
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )


def test_signed_flow_requires_explicit_provider_aggressor():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 100_000,
                "volume": 10,
                "timestamp": "2026-07-31T14:45:00Z",
                "aggressor": "BUY",
                "multiplier": 100,
            },
            {
                "contract_type": "put",
                "premium": 150_000,
                "volume": 12,
                "timestamp": "2026-07-31T14:46:00Z",
                "aggressor": "BUY",
            },
        ]
    )

    assert result["provider"]["signed_flow_available"] is True
    assert result["summary"]["signed_net_premium"] == -50_000
    assert result["summary"]["activity_imbalance"] == -0.2
    tape = {row["right"]: row for row in result["flow_tape"]}
    assert tape["call"]["bias"] == "bullish"
    assert tape["call"]["edge_label"] == "BULL"
    assert tape["call"]["aggressor_label"] == "BUY"
    assert tape["call"]["contracts"] == 10
    assert tape["call"]["price"] == 100.0  # 100k / (10 * 100)
    assert tape["put"]["bias"] == "bearish"
    assert tape["put"]["edge_label"] == "BEAR"
    assert tape["put"]["aggressor_label"] == "BUY"


def test_tape_back_solves_price_with_multiplier_and_preserves_vendor_block():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 750_000,
                "volume": 50,
                "timestamp": "2026-07-31T14:45:00Z",
                "multiplier": 100,
                "trade_class": "block",
            },
        ]
    )
    row = result["flow_tape"][0]
    assert row["price"] == 150.0
    assert row["contracts"] == 50
    assert row["trade_class"] == "block"
    assert row["trade_class_source"] == "vendor"
    assert row["bias"] is None
    assert row["edge_label"] == "CALL"  # activity identity when unsigned
    assert row["aggressor_label"] == "NO SIDE"


def test_contract_focus_names_a_specific_liquid_contract_for_each_right():
    chain = [
        _chain("call", 100) | {"delta": 0.72, "bid": 7.0, "ask": 7.8},
        _chain("call", 105)
        | {"delta": 0.46, "bid": 3.9, "ask": 4.1, "occ_symbol": "TEST260828C00105000"},
        _chain("put", 95)
        | {"delta": -0.44, "bid": 3.7, "ask": 3.9, "occ_symbol": "TEST260828P00095000"},
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=chain,
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    call = result["contract_focus"]["call"]
    put = result["contract_focus"]["put"]
    assert call["occ_symbol"] == "TEST260828C00105000"
    assert call["strike"] == pytest.approx(105)
    assert call["midpoint"] == pytest.approx(4.0)
    assert call["spread_pct"] == pytest.approx(0.05)
    assert call["quote_complete"] is True
    assert call["liquidity_complete"] is True
    assert call["contract_complete"] is True
    assert put["strike"] == pytest.approx(95)
    assert "volume/OI gates before fine delta distance" in call["selection_method"]


def test_contract_focus_prefers_liquidity_and_keeps_delayed_quotes_paper_only():
    chain = [
        _chain("call", 105)
        | {
            "delta": 0.45,
            "open_interest": 3,
            "volume": 20,
            "quote_live": False,
            "quote_source": "yfinance_delayed_exact_occ",
            "occ_symbol": "TEST260828C00105000",
        },
        _chain("call", 107)
        | {
            "delta": 0.52,
            "open_interest": 1200,
            "volume": 300,
            "quote_live": False,
            "quote_source": "yfinance_delayed_exact_occ",
            "occ_symbol": "TEST260828C00107000",
        },
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=chain,
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    call = result["contract_focus"]["call"]
    assert call["occ_symbol"] == "TEST260828C00107000"
    assert call["open_interest"] == 1200
    assert call["quote_status"] == "delayed_reference"
    assert call["quote_reference_only"] is True
    assert call["quote_complete"] is False
    assert call["contract_complete"] is False
    assert any("delayed reference only" in reason for reason in call["rejection_reasons"])


def test_contract_focus_rejects_extreme_strikes_from_provider_normalization():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[
            _chain("call", 5) | {"delta": 0.45},
            _chain("put", 950) | {"delta": -0.45},
        ],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    assert result["contract_focus"] == {}


def test_large_untagged_print_is_not_certified_as_vendor_block():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 750_000,
                "volume": 50,
                "timestamp": "2026-07-31T14:45:00Z",
            }
        ]
    )
    row = result["flow_tape"][0]
    assert row["price"] is None
    assert row["trade_class"] == "large"
    assert row["trade_class_source"] == "size_heuristic"


def test_expired_print_is_rejected_instead_of_clamped_to_zero_dte():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 100_000,
                "volume": 10,
                "expiry": "2026-07-30",
                "timestamp": "2026-07-31T14:45:00Z",
            }
        ]
    )
    assert result["flow_tape"] == []
    assert result["quality"]["flow_rejected"]["invalid"] == 1


def test_sweep_burst_promotes_trade_class():
    rows = [
        {
            "contract_type": "call",
            "premium": 80_000,
            "volume": 20,
            "strike": 105,
            "expiry": "2026-08-28",
            "timestamp": f"2026-07-31T14:45:0{i}Z",
            "aggressor": "BUY",
        }
        for i in range(3)
    ]
    result = _payload(rows)
    assert all(r["trade_class"] == "sweep" for r in result["flow_tape"])
    assert any("sweep_burst" in r["anomaly_flags"] for r in result["flow_tape"])
    assert any("burst sweep ≤3s" in (r.get("why") or []) for r in result["flow_tape"])


def test_call_put_identity_and_stale_quote_proxy_stay_unsigned():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 125_000,
                "volume": 10,
                "timestamp": "2026-07-31T14:45:00Z",
                "_stale_quote_side": "BUY",
            },
        ]
    )

    assert result["provider"]["signed_flow_available"] is False
    assert result["summary"]["signed_net_premium"] is None
    assert result["summary"]["unresolved_premium"] == 125_000
    assert result["summary"]["activity_lean"] == "bullish"
    assert result["summary"]["activity_lean_source"] == "call_put_premium"
    assert result["summary"]["activity_lean_label"] == "BULLISH"
    assert result["summary"]["decision_authorized"] is False
    assert result["flow_tape"][0]["bias"] is None
    assert result["flow_tape"][0]["edge_label"] == "CALL"
    assert "why" in result["flow_tape"][0]


def test_unsigned_call_put_mix_never_drives_squeeze_direction():
    unsigned = _payload(
        [
            {
                "contract_type": "call",
                "premium": 125_000,
                "volume": 10,
                "timestamp": "2026-07-31T14:45:00Z",
            },
        ]
    )
    assert unsigned["summary"]["activity_imbalance"] == 1.0
    assert unsigned["summary"]["signed_flow_imbalance"] is None
    theory = unsigned["summary"]["squeeze"]["theory"]
    # Unmeasured, not a neutral 0.0 vote: the flow term is dropped from conviction.
    assert theory["directional_flow_imbalance"] is None
    assert theory["flow_measured"] is False
    assert theory["flow_weight"] == 0.0
    # Unsigned tape still gets a live activity-shift readout (call+/put−),
    # which must not leak into the signed squeeze term.
    activity = unsigned["summary"]["activity_shift"]
    assert activity is not None
    assert activity["kind"] == "contract_activity"
    assert activity["n"] >= 1
    assert activity["signed_imbalance"] > 0


def test_signed_flow_imbalance_is_sample_size_shrunk_for_squeeze():
    signed = _payload(
        [
            {
                "contract_type": "call",
                "premium": 125_000,
                "volume": 10,
                "timestamp": "2026-07-31T14:45:00Z",
                "aggressor": "BUY",
            },
        ]
    )
    # One fully bullish signed print gets 1/8 confidence, not a saturated +1.
    assert signed["summary"]["signed_flow_confidence"] == 0.125
    assert signed["summary"]["signed_flow_imbalance"] == 0.125
    assert signed["summary"]["squeeze"]["theory"]["directional_flow_imbalance"] == 0.125
    assert signed["summary"]["signed_flow_confidence_band"] != "high"


def _signed_prints(n, *, side, start_hour=12):
    right = "call" if side == "buy_call" else "put"
    aggressor = "BUY"
    rows = []
    for i in range(n):
        minute = (i * 4) % 60
        hour = start_hour + (i * 4) // 60
        rows.append(
            {
                "contract_type": right,
                "premium": 125_000,
                "volume": 10,
                "timestamp": f"2026-07-31T{hour:02d}:{minute:02d}:00Z",
                "aggressor": aggressor,
            }
        )
    return rows


def test_mid_tape_reversal_updates_live_squeeze_instead_of_locking_pre_shift():
    prices = [
        {"t": f"2026-07-{day:02d}T20:00:00+00:00", "close": 90.0 + day, "volume": 2_000_000.0}
        for day in range(1, 22)
    ]
    chain = [
        _chain("call", 101, gamma=0.08) | {"open_interest": 50_000},
        _chain("put", 99, gamma=0.02) | {"open_interest": 5_000},
    ]
    common = dict(
        symbol="TEST",
        chain_rows=chain,
        price_series=prices,
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    stable = build_options_intelligence(flow_rows=_signed_prints(12, side="buy_call"), **common)
    flipped = build_options_intelligence(
        flow_rows=_signed_prints(8, side="buy_call")
        + _signed_prints(8, side="buy_put", start_hour=13),
        **common,
    )
    assert stable["summary"]["signed_flow_imbalance"] > 0
    assert flipped["summary"]["signed_flow_imbalance"] < 0
    assert flipped["summary"]["squeeze"]["score"] != stable["summary"]["squeeze"]["score"]
    assert flipped["summary"]["flow_shift"]["last_shift_index"] is not None
    # Just after a long one-sided run the locked cumulative would still be
    # bullish; post-shift flow must not keep that sign.
    locked_net = 8 * 125_000 - 8 * 125_000
    assert locked_net == 0
    assert flipped["summary"]["signed_flow_imbalance"] != 0.0


def test_squeeze_uses_observed_adv_instead_of_spot_proxy():
    prices = [
        {
            "t": f"2026-07-{day:02d}T20:00:00+00:00",
            "close": 100.0,
            "volume": 2_000_000.0,
        }
        for day in range(1, 22)
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[],
        price_series=prices,
        spot=100,
        filters=OptionsFilters(range="1m", min_premium=0, min_volume=0),
        mode_requested="history",
        mode_resolved="history",
        chain_source="fixture",
        flow_source="none",
        asof_utc=ASOF,
    )
    assert result["summary"]["squeeze"]["theory"]["adv_m"] == 200.0


def test_stale_price_bars_cannot_drive_live_squeeze_direction():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[],
        price_series=[
            {"t": "2026-07-15T20:00:00+00:00", "close": 90, "volume": 1_000_000},
            {"t": "2026-07-20T20:00:00+00:00", "close": 100, "volume": 1_000_000},
        ],
        spot=100,
        filters=OptionsFilters(range="1m", min_premium=0, min_volume=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="none",
        asof_utc=ASOF,
    )
    theory = result["summary"]["squeeze"]["theory"]
    assert theory["momentum"] == 0.0
    assert theory["momentum_fresh"] is False
    assert any("excludes momentum" in warning for warning in result["warnings"])


def test_zero_provider_gamma_falls_back_to_black_scholes():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105, gamma=0.0), _chain("put", 95, gamma=0.0)],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="history",
        mode_resolved="history",
        chain_source="fixture",
        flow_source="none",
        asof_utc=ASOF,
    )
    assert result["quality"]["gamma_source"]["black_scholes"] == 2
    assert result["summary"]["abs_gex_m"] > 0


def test_gex_and_probability_are_explicitly_model_derived():
    result = _payload([])

    assert result["quality"]["gamma_source"]["provider"] == 2
    assert result["summary"]["call_wall"] == 105
    assert result["summary"]["put_wall"] == 95
    assert result["summary"]["call_wall_pct"] is not None and result["summary"]["call_wall_pct"] > 0
    assert result["summary"]["put_wall_pct"] is not None and result["summary"]["put_wall_pct"] < 0
    assert result["gex_by_expiry"]
    assert result["gex_price_profile"]
    assert result["probability"]["available"] is True
    assert "risk-neutral" in result["probability"]["method"]
    assert any(
        "True dealer inventory is not public" in note
        or "true dealer inventory is not public" in note
        for note in result["caveats"]
    )


def test_gex_walls_are_directional_not_global_argmax():
    """ATM strike with both huge call and put mass must not set both walls there.

    InsiderFinance / SpotGamma: call wall = resistance above spot, put wall =
    support below spot.
    """
    asof = ASOF
    chain = [
        {
            "right": "call",
            "expiry": "2026-08-28",
            "strike": 100,
            "bid": 4.9,
            "ask": 5.1,
            "volume": 500,
            "open_interest": 50_000,
            "iv": 0.35,
            "gamma": 0.05,
            "multiplier": 100,
            "captured_utc": asof.isoformat(),
            "spot": 100,
        },
        {
            "right": "put",
            "expiry": "2026-08-28",
            "strike": 100,
            "bid": 4.9,
            "ask": 5.1,
            "volume": 500,
            "open_interest": 50_000,
            "iv": 0.35,
            "gamma": 0.05,
            "multiplier": 100,
            "captured_utc": asof.isoformat(),
            "spot": 100,
        },
        {
            "right": "call",
            "expiry": "2026-08-28",
            "strike": 110,
            "bid": 1.9,
            "ask": 2.1,
            "volume": 100,
            "open_interest": 8_000,
            "iv": 0.35,
            "gamma": 0.02,
            "multiplier": 100,
            "captured_utc": asof.isoformat(),
            "spot": 100,
        },
        {
            "right": "put",
            "expiry": "2026-08-28",
            "strike": 90,
            "bid": 1.9,
            "ask": 2.1,
            "volume": 100,
            "open_interest": 8_000,
            "iv": 0.35,
            "gamma": 0.02,
            "multiplier": 100,
            "captured_utc": asof.isoformat(),
            "spot": 100,
        },
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=chain,
        flow_rows=[],
        price_series=[{"t": asof.isoformat(), "close": 100}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0, min_open_interest=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=asof,
    )
    assert result["summary"]["call_wall"] == 110
    assert result["summary"]["put_wall"] == 90
    assert result["summary"]["call_wall"] != result["summary"]["put_wall"]


def test_squeeze_readout_is_attached_to_summary():
    result = _payload(
        [
            {
                "contract_type": "call",
                "premium": 250_000,
                "volume": 40,
                "timestamp": "2026-07-31T14:45:00Z",
                "aggressor": "BUY",
            },
        ]
    )
    squeeze = result["summary"]["squeeze"]
    assert "bullish" in squeeze and "bearish" in squeeze
    assert "score" in squeeze  # signed gex_core score [-100, 100]
    assert -100 <= squeeze["score"] <= 100
    assert squeeze["label"] in {
        "quiet",
        "two_way",
        "bullish_lean",
        "bullish_squeeze",
        "bearish_lean",
        "bearish_squeeze",
    }
    assert squeeze["primary"] in {"quiet", "two_way", "bullish", "bearish"}
    method = squeeze.get("method") or ""
    assert "theory" in method or "gex_core" in method
    assert "theory" in squeeze or "components" in squeeze
    assert "components" in squeeze
    theory = squeeze["theory"]
    assert theory["fuel_scale"] == 25.0
    assert theory["urgency_dte_basis"] == "front40"
    assert "urgency_dte" in theory
    assert "front40_weighted_dte" in theory
    assert "theory_urgency_dte" in squeeze["components"]
    assert "theory_fuel_scale" in squeeze["components"]
    assert "bullish_setup" in squeeze and "bearish_setup" in squeeze
    bull = squeeze["bullish_setup"]
    bear = squeeze["bearish_setup"]
    assert 0 <= bull["score"] <= 100
    assert 0 <= bear["score"] <= 100
    # Side scores derived from signed score — one side non-negative match
    if squeeze["score"] >= 0:
        assert bull["score"] >= bear["score"]
    else:
        assert bear["score"] >= bull["score"]
    assert bull["likelihood"] in {"unlikely", "possible", "likely", "imminent"}
    assert len(bull["factors"]) >= 4
    assert bull["trading_implication"]
    assert isinstance(squeeze["signals"], list)
    assert "call_gex_m" in result["summary"]
    assert "put_gex_m" in result["summary"]
    assert "key_levels" in squeeze
    assert "near_spot_net_gex_m" in squeeze["key_levels"]


def test_live_tape_ignores_history_date_to_clamp():
    """Stale history `date_to` must not reject every live print as outside_range."""
    asof = ASOF
    # History chain day two weeks earlier — used to wipe the live tape.
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[
            {
                "contract_type": "call",
                "premium": 100_000,
                "volume": 10,
                "timestamp": "2026-07-31T14:45:00Z",
                "aggressor": "BUY",
            },
            {
                "contract_type": "put",
                "premium": 80_000,
                "volume": 8,
                "timestamp": "2026-07-31T15:10:00Z",
                "aggressor": "SELL",
            },
        ],
        price_series=[{"t": asof.isoformat(), "close": 100}],
        spot=100,
        filters=OptionsFilters(
            range="5d",
            min_premium=50_000,
            min_volume=1,
            date_to="2026-07-15",  # leftover history day
        ),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=asof,
    )
    assert result["provider"]["activity_basis"] == "trade_tape"
    assert result["quality"]["flow_prints_included"] >= 2
    assert int(result["quality"]["flow_rejected"].get("outside_range") or 0) == 0
    assert len(result["flow_tape"]) >= 2


def test_live_tape_relaxes_window_when_prints_just_outside_default_span():
    asof = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)
    # Prints slightly older than the 1d window but still recent — should recover.
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[
            {
                "contract_type": "call",
                "premium": 120_000,
                "volume": 20,
                "timestamp": "2026-07-28T12:00:00Z",
                "aggressor": "BUY",
            },
        ],
        price_series=[],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=asof,
    )
    assert result["provider"]["activity_basis"] == "trade_tape"
    assert result["quality"]["flow_rejected"].get("window_relaxed") is True
    assert len(result["flow_tape"]) == 1


def test_liquidity_filter_rejections_are_counted_not_silently_zeroed():
    thin = _chain("call", 105)
    thin["open_interest"] = 3
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[thin, _chain("put", 95)],
        flow_rows=[],
        price_series=[],
        spot=100,
        filters=OptionsFilters(min_open_interest=100),
        mode_requested="history",
        mode_resolved="history",
        chain_source="fixture",
        flow_source="none",
        asof_utc=ASOF,
    )

    assert result["quality"]["chain_contracts_raw"] == 2
    assert result["quality"]["chain_contracts_included"] == 1
    assert result["quality"]["chain_rejected"]["low_open_interest"] == 1


def test_nearest_expiry_is_explicit_and_filters_structural_calculations():
    farther_call = _chain("call", 120)
    farther_call["expiry"] = "2026-09-18"
    farther_put = _chain("put", 80)
    farther_put["expiry"] = "2026-09-18"
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95), farther_call, farther_put],
        flow_rows=[],
        price_series=[],
        spot=100,
        filters=OptionsFilters(expiry="nearest"),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    assert result["chain_context"]["selected_expiry"] == "2026-08-28"
    assert result["chain_context"]["selected_dte"] == 28
    assert len(result["chain_context"]["available_expiries"]) == 2
    assert result["quality"]["chain_contracts_included"] == 2
    assert result["quality"]["chain_rejected"]["outside_expiry"] == 2
    assert result["summary"]["call_wall"] == 105
    assert result["summary"]["put_wall"] == 95


def test_exact_expiry_keeps_gex_focus_but_relaxes_an_empty_trade_tape():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[
            {
                "contract_type": "call",
                "premium": 1_000,
                "volume": 10,
                "strike": 105,
                "expiry": "2026-08-28",
                "timestamp": "2026-07-31T14:45:00Z",
            },
            {
                "contract_type": "put",
                "premium": 125_000,
                "volume": 20,
                "strike": 90,
                "expiry": "2026-09-18",
                "timestamp": "2026-07-31T14:46:00Z",
            },
        ],
        price_series=[],
        spot=100,
        filters=OptionsFilters(
            range="1d",
            min_premium=50_000,
            min_volume=1,
            expiry="2026-08-28",
        ),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    assert result["chain_context"]["selected_expiry"] == "2026-08-28"
    assert result["summary"]["call_wall"] == 105
    assert len(result["flow_tape"]) == 1
    assert result["flow_tape"][0]["expiry"] == "2026-09-18"
    assert result["provider"]["activity_basis"] == "trade_tape"
    assert result["quality"]["flow_rejected"]["expiry_filter_relaxed"] is True
    assert result["quality"]["flow_rejected"]["requested_expiry"] == "2026-08-28"
    assert any("Flow tape widened to all expiries" in item for item in result["warnings"])


def test_tape_anomalies_use_robust_observable_rules_and_respect_depth_limit():
    rows = [
        {
            "contract_type": "call",
            "premium": 80_000 + i * 5_000,
            "volume": 10 + i,
            "strike": 90 + i,
            "timestamp": f"2026-07-31T14:{i:02d}:00Z",
        }
        for i in range(9)
    ]
    rows.append(
        {
            "contract_type": "put",
            "premium": 2_000_000,
            "volume": 500,
            "strike": 70,
            "timestamp": "2026-07-31T14:10:00Z",
        }
    )
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=rows,
        price_series=[],
        spot=100,
        filters=OptionsFilters(min_premium=0, min_volume=0, tape_limit=5),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )

    assert result["quality"]["flow_prints_included"] == 10
    assert len(result["flow_tape"]) == 5
    outlier = next(row for row in result["flow_tape"] if row["premium"] == 2_000_000)
    assert "premium_outlier" in outlier["anomaly_flags"]
    assert "volume_outlier" in outlier["anomaly_flags"]
    assert result["anomalies"]["count"] == 1
    assert "MAD" in result["anomalies"]["method"]


def test_best_observation_time_prefers_precise_clocks_over_midnight_buckets():
    midnight = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
    precise = datetime(2026, 8, 12, 15, 18, tzinfo=timezone.utc)
    older_precise = datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc)
    assert _best_observation_time([midnight, precise, older_precise]) == precise
    assert _best_observation_time([midnight, None]) == midnight
    assert _best_observation_time([None, None]) is None


def test_freshness_tracks_feed_even_when_min_premium_filters_recent_prints():
    """Small live prints must keep the feed lamp live under a high min $ floor."""
    flow_rows = [
        {
            "contract_type": "call",
            "premium": 500,  # below $50k floor
            "volume": 2,
            "strike": 100,
            "timestamp": "2026-07-31T15:00:00Z",
        },
        {
            "contract_type": "put",
            "premium": 80_000,
            "volume": 20,
            "strike": 95,
            "timestamp": "2026-07-30T20:00:00Z",  # day-old whale
        },
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=flow_rows,
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="5d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    assert result["provider"]["activity_basis"] == "trade_tape"
    assert len(result["flow_tape"]) == 1
    assert result["flow_tape"][0]["premium"] == 80_000
    freshness = result["freshness"]
    # Feed age follows the small live print, not the filtered-out whale lag alone.
    assert freshness["feed_asof"] is not None
    assert "2026-07-31T15:00:00" in str(freshness["feed_asof"])
    assert freshness["age_seconds"] is not None
    assert freshness["age_seconds"] < 60  # asof is 15:00, feed stamp 15:00
    assert freshness["tape_age_seconds"] is not None
    assert freshness["tape_age_seconds"] > freshness["age_seconds"]


def test_imbalance_confidence_shrinks_thin_tape():
    """A 2-print tape must not saturate the squeeze direction at ±1.0."""
    assert _imbalance_confidence(0) == 0.0
    assert _imbalance_confidence(2) == 0.25
    assert _imbalance_confidence(8) == 1.0
    # Never exceeds 1.0 no matter how deep the tape.
    assert _imbalance_confidence(500) == 1.0
    # Monotone in sample size.
    assert _imbalance_confidence(2) < _imbalance_confidence(5) < _imbalance_confidence(8)


# ---------------------------------------------------------------------------
# Measurability: a missing input must never render as a measured zero.
# ---------------------------------------------------------------------------


def _measurability_payload(*, open_interest: int, oi_source: str) -> dict:
    call = {**_chain("call", 105), "open_interest": open_interest}
    put = {**_chain("put", 95), "open_interest": open_interest}
    return build_options_intelligence(
        symbol="TEST",
        chain_rows=[call, put],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(
            range="1d",
            min_premium=0,
            min_volume=0,
            min_open_interest=0,
        ),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
        open_interest_source=oi_source,
    )


def test_observed_open_interest_marks_gex_measurable():
    payload = _measurability_payload(open_interest=2_000, oi_source="lse_live")
    assert payload["quality"]["gex_measurable"] is True


def test_zero_open_interest_marks_gex_unmeasurable():
    payload = _measurability_payload(open_interest=0, oi_source="lse_live")
    assert payload["quality"]["gex_measurable"] is False


def test_unavailable_oi_source_marks_gex_unmeasurable():
    payload = _measurability_payload(open_interest=0, oi_source="unavailable")
    assert payload["quality"]["gex_measurable"] is False


def test_unavailable_oi_emits_a_warning_before_any_zero_is_read():
    payload = _measurability_payload(open_interest=0, oi_source="unavailable")
    joined = " ".join(payload["warnings"])
    assert "unmeasured rather than zero" in joined
    assert "backfill_option_oi.py" in joined


def test_measurable_chain_emits_no_unmeasured_warning():
    payload = _measurability_payload(open_interest=2_000, oi_source="lse_live")
    assert not any("unmeasured" in w for w in payload["warnings"])


def test_median_spread_pct_is_reported_on_summary():
    # _chain() rows both quote bid=4.9/ask=5.1 on mid=5.0 -> spread_pct 0.04.
    result = _payload([])
    assert result["summary"]["median_spread_pct"] == pytest.approx(0.04)


def test_median_spread_pct_is_none_without_usable_bid_ask():
    payload = build_options_intelligence(
        symbol="TEST",
        chain_rows=[
            {
                "right": "call",
                "expiry": "2026-08-28",
                "strike": 105,
                "volume": 500,
                "open_interest": 2_000,
                "iv": 0.35,
                "gamma": 0.02,
                "multiplier": 100,
                "captured_utc": ASOF.isoformat(),
                "spot": 100,
            }
        ],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    assert payload["summary"]["median_spread_pct"] is None


def test_charm_is_delta_decay_per_day_and_identical_for_calls_and_puts_at_q0():
    from edge.daily_plays.options_intelligence import _bs_charm_per_day

    # ATM, 30 DTE, IV 0.35, r 0.045, q 0.
    call = _bs_charm_per_day(spot=100, strike=100, years=30 / 365, iv=0.35, rate=0.045)
    put = _bs_charm_per_day(
        spot=100, strike=100, years=30 / 365, iv=0.35, rate=0.045, is_call=False
    )
    assert call is not None and put is not None
    assert call == pytest.approx(put, abs=1e-12)
    # Charm is negative for ATM options: delta decays toward 0/1 as time passes.
    assert call < 0
    # Units: delta per day — a sane magnitude for 30 DTE ATM.
    assert abs(call) < 0.01


def test_charm_skips_near_expiry_and_implausible_iv_instead_of_exploding():
    from edge.daily_plays.options_intelligence import _bs_charm_per_day

    assert _bs_charm_per_day(spot=100, strike=100, years=0.5 / 365, iv=0.35, rate=0.045) is None
    assert _bs_charm_per_day(spot=100, strike=100, years=30 / 365, iv=0.0, rate=0.045) is None
    assert _bs_charm_per_day(spot=100, strike=100, years=30 / 365, iv=9.0, rate=0.045) is None


def test_charm_flow_by_strike_uses_dealer_sign_convention_and_oi():
    # ATM strikes: charm is negative for both rights (delta decays toward 0/1),
    # so the dealer sign convention (calls +, puts −) flips the put side.
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 100), _chain("put", 100)],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    rows = {row["strike"]: row for row in result["charm_by_strike"]}
    assert 100 in rows
    # ATM charm < 0 → call flow negative, put flow positive (sign convention).
    assert rows[100]["call_charm_flow"] < 0
    assert rows[100]["put_charm_flow"] > 0
    assert rows[100]["net_charm_flow"] == pytest.approx(
        rows[100]["call_charm_flow"] + rows[100]["put_charm_flow"]
    )
    # Summary aggregates the same numbers.
    summary = result["charm_summary"]
    assert summary["net_charm_flow"] == pytest.approx(rows[100]["net_charm_flow"])
    assert summary["contracts_measured"] == 2
    assert summary["source"] == "black_scholes_charm"


def test_charm_summary_pressure_tag_follows_dealer_hedge_convention():
    # §5.5: net charm flow > 0 → dealers sell to stay neutral → selling pressure.
    from edge.daily_plays.options_intelligence import _charm_map

    rows = [
        {
            "right": "call",
            "strike": 100,
            "dte": 30,
            "iv": 0.35,
            "open_interest": 2_000,
            "multiplier": 100,
        },
        {
            "right": "put",
            "strike": 100,
            "dte": 30,
            "iv": 0.35,
            "open_interest": 2_000,
            "multiplier": 100,
        },
    ]
    _, summary, _ = _charm_map(rows, spot=100, rate=0.045)
    # Equal OI on both sides → net ≈ 0 → balanced.
    assert summary["pressure"] == "balanced"

    rows = [
        {
            "right": "call",
            "strike": 100,
            "dte": 30,
            "iv": 0.35,
            "open_interest": 2_000,
            "multiplier": 100,
        },
    ]
    _, summary, _ = _charm_map(rows, spot=100, rate=0.045)
    # Call-only book: net charm flow < 0 (ATM charm negative) → dealers buy.
    assert summary["net_charm_flow"] < 0
    assert summary["pressure"] == "buying"


def test_pressure_gauge_readout_agrees_with_dealer_hedge_convention():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    # §5.5: positive net charm flow → dealers sell → selling pressure.
    # The gauge negates the charm term so it agrees with the charm KPI.
    gauge = _pressure_gauge(
        net_charm_flow=500.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(-1.0)
    assert gauge["label"] == "selling"

    gauge = _pressure_gauge(
        net_charm_flow=-500.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(1.0)
    assert gauge["label"] == "buying"

    gauge = _pressure_gauge(
        net_charm_flow=0.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(0.0)
    assert gauge["label"] == "balanced"


def test_payload_exposes_charm_pressure_and_delta_weighted_volume():
    result = _payload([])
    assert "charm_by_strike" in result
    assert "chain_by_strike" in result
    assert "charm_summary" in result
    assert "pressure" in result
    assert "delta_weighted_volume" in result
    assert result["pressure"]["label"] in {"buying", "selling", "balanced"}
    assert result["pressure"]["components"]["net_charm_flow"] == pytest.approx(
        result["charm_summary"]["net_charm_flow"]
    )
    assert result["delta_weighted_volume"]["call"] >= 0
    assert result["delta_weighted_volume"]["put"] >= 0


def test_negative_gex_takeaway_puts_the_sign_ahead_of_the_dollar_sign():
    """`f"${-6.55:.2f}M"` renders "$-6.55M", which reads as a malformed amount.

    Near-spot and total dealer GEX are negative for most of the short-gamma
    tape this takeaway describes, so the sign placement is the common case, not
    an edge case. The dashboard formats the same numbers as "-$6.55M".
    """
    assert _usd_millions(-6.55) == "-$6.55M"
    assert _usd_millions(6.55) == "$6.55M"
    assert _usd_millions(0.0) == "$0.00M"
    assert _usd_millions(-0.004) == "-$0.00M"
    assert _usd_millions(-1234.5, 1) == "-$1234.5M"

    setup = _setup_from_gex_score(
        side="bearish",
        signed_score=-1.1,
        components={
            "regime_score": 20.0,
            "put_prox_score": -9.4,
            "put_conc_score": -15.0,
            "wall_asym_score": -10.0,
            "em_score": 10.0,
            "flip_score": 0.0,
        },
        wall_level=200.0,
        wall_pct=-0.049409,
        spot=210.3955,
        near_net=-6.5479,
        net_dealer=-7.2359,
        fuel=0.0329,
    )
    headline = setup["setup_analysis"][0]
    assert "-$6.55M" in headline
    assert "-$7.24M" in headline
    assert "$-" not in headline


# --- charm / pressure-gauge math audit regressions ---------------------------


def _charm_row(
    right: str, strike: float, *, oi: int = 2_000, dte: int | None = 30, iv: float = 0.35
) -> dict:
    return {
        "right": right,
        "strike": strike,
        "open_interest": oi,
        "volume": 0,
        "iv": iv,
        "dte": dte,
        "multiplier": 100,
    }


def test_charm_map_skips_contracts_with_unknown_expiry_instead_of_pricing_them_as_1dte():
    """Missing DTE must not be silently floored to 1 day.

    Charm scales like tau^-3/2, so a stray unknown-expiry contract priced as
    1DTE carried ~60x the weight of a real 30DTE contract and dominated the
    chain total. Unknown tenor is unmeasurable, not maximally urgent.
    """
    from edge.daily_plays.options_intelligence import _charm_map

    _, summary, chain = _charm_map([_charm_row("call", 97, dte=None)], spot=100, rate=0.045)
    assert summary["contracts_measured"] == 0
    assert summary["skipped_reasons"] == {"missing_dte": 1}
    assert chain[0]["charm_per_day"] is None
    assert chain[0]["charm_flow"] == 0.0


def test_charm_map_honors_the_documented_one_day_validity_floor():
    """The T < 1 day guard in _bs_charm_per_day must be reachable from _charm_map.

    _charm_map used to floor years at exactly 1/365 before calling, so the guard
    could never fire and 0DTE contracts were charmed as if they had a full day.
    """
    from edge.daily_plays.options_intelligence import _charm_map

    _, summary, chain = _charm_map([_charm_row("call", 97, dte=0)], spot=100, rate=0.045)
    assert summary["contracts_measured"] == 0
    assert summary["skipped_reasons"] == {"expiring_within_one_day": 1}
    assert chain[0]["charm_per_day"] is None

    # 1DTE is still inside the model's validity range and must be measured.
    _, summary_1dte, _ = _charm_map([_charm_row("call", 97, dte=1)], spot=100, rate=0.045)
    assert summary_1dte["contracts_measured"] == 1
    assert summary_1dte["skipped_reasons"] == {}


def test_charm_map_counters_reconcile_to_the_chain_size():
    """measured + skipped must equal the chain, with no double counting."""
    from edge.daily_plays.options_intelligence import _charm_map

    rows = [_charm_row("call", k) for k in (95, 100, 105)] + [_charm_row("call", 97, dte=None)]
    _, summary, chain = _charm_map(rows, spot=100, rate=0.045)
    assert summary["contracts_measured"] == 3
    assert summary["contracts_skipped"] == 1
    assert summary["contracts_measured"] + summary["contracts_skipped"] == len(chain)


def test_abs_charm_flow_is_gross_magnitude_not_net_of_opposing_strikes():
    """Charm flips sign either side of spot, so |sum| cancels and understates gross.

    On a symmetric chain the old |sum(calls)| + |sum(puts)| form reported ~21% of
    the true gross magnitude, which made it useless as a pressure-gauge normalizer.
    """
    from edge.daily_plays.options_intelligence import _charm_map

    rows = [_charm_row("call", k) for k in (90, 95, 100, 105, 110)] + [
        _charm_row("put", k) for k in (90, 95, 100, 105, 110)
    ]
    mapped, summary, _ = _charm_map(rows, spot=100, rate=0.045)

    expected = sum(abs(r["call_charm_flow"]) + abs(r["put_charm_flow"]) for r in mapped)
    assert summary["abs_charm_flow"] == pytest.approx(expected)
    # Strikes genuinely straddle spot, so this test would be vacuous otherwise.
    assert any(r["call_charm_flow"] > 0 for r in mapped)
    assert any(r["call_charm_flow"] < 0 for r in mapped)
    assert summary["abs_charm_flow"] > abs(summary["net_charm_flow"])


def test_pressure_gauge_channels_abstain_when_they_have_no_gross_magnitude():
    """A channel with no data must not vote 'balanced' and dilute the others."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=250_000.0,
        abs_charm_flow=900_000.0,
        net_gex_m=0.0,
        abs_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
    )
    assert gauge["channels"]["gex"] is None
    assert gauge["channels"]["volume"] is None
    # Pure charm read: -250k/900k, undiluted by the two silent channels.
    assert gauge["channels"]["charm"] == pytest.approx(-250_000.0 / 900_000.0)
    assert gauge["imbalance"] == pytest.approx(-250_000.0 / 900_000.0)


def test_pressure_gauge_stays_bounded_and_unsigned_context_never_votes():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=-900_000.0,
        abs_charm_flow=900_000.0,
        net_gex_m=150.0,
        abs_gex_m=150.0,
        delta_weighted_call_vol=90_000.0,
        delta_weighted_put_vol=0.0,
    )
    # Charm maxed bullish -> saturates at exactly +1, never beyond. The unsigned
    # call/put mix and the GEX sign are context only and never vote.
    assert gauge["imbalance"] == pytest.approx(1.0)
    assert gauge["label"] == "buying"
    assert gauge["channels"] == {
        "charm": 1.0,
        "tape": None,
        "underlying": None,
        "volume": None,
        "gex": None,
    }


def test_bs_gamma_matches_bs_delta_on_dividend_handling():
    """Gamma dropped the yield terms that d1/delta carried, so they disagreed."""
    kwargs = dict(spot=100, strike=105, years=30 / 365, iv=0.35, rate=0.045)
    q = 0.03
    # Finite-difference gamma from the dividend-adjusted delta.
    h = 0.01
    up = _bs_delta(**{**kwargs, "spot": 100 + h}, yield_rate=q)
    down = _bs_delta(**{**kwargs, "spot": 100 - h}, yield_rate=q)
    numeric = (up - down) / (2 * h)
    assert _bs_gamma(**kwargs, yield_rate=q) == pytest.approx(numeric, rel=1e-4)

    # q = 0 must be unchanged from the previous behaviour.
    assert _bs_gamma(**kwargs) == pytest.approx(_bs_gamma(**kwargs, yield_rate=0.0))
    assert not math.isclose(_bs_gamma(**kwargs), _bs_gamma(**kwargs, yield_rate=q))


def _scalar_net_gex(contracts, spots, rate, yield_rate=0.0):
    """Independent per-spot sum through `_bs_gamma`. Oracle for the grid."""
    totals = []
    for spot in spots:
        spot_f = float(spot)
        total = 0.0
        for row in contracts:
            gamma = _bs_gamma(
                spot=spot_f,
                strike=float(row["strike"]),
                years=float(row["years"]),
                iv=float(row.get("iv") or 0.0),
                rate=rate,
                yield_rate=yield_rate,
            )
            if gamma is None:
                continue
            total += (
                float(row["sign"])
                * gamma
                * float(row["oi"])
                * float(row["multiplier"])
                * spot_f
                * spot_f
                * 0.01
            )
        totals.append(total)
    return totals


def _crossings(grid):
    found = []
    for (x0, y0), (x1, y1) in zip(grid, grid[1:]):
        if y0 == 0:
            found.append(x0)
        elif y0 * y1 < 0:
            found.append(x0 + (x1 - x0) * abs(y0) / (abs(y0) + abs(y1)))
    return found


def test_bs_gamma_locks_atm_one_year_value():
    """S = K = 100, T = 1, σ = 0.20, r = q = 0 → d1 = 0.1, Γ = φ(d1) / (S σ)."""
    d1 = 0.1
    expected = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi) / (100.0 * 0.2)
    got = _bs_gamma(spot=100.0, strike=100.0, years=1.0, iv=0.2, rate=0.0, yield_rate=0.0)
    assert got == pytest.approx(expected, rel=1e-12)
    assert got == pytest.approx(0.0198476273663, rel=1e-9)


def test_net_gex_grid_matches_scalar_black_scholes():
    rate = 0.045
    yield_rate = 0.02
    contracts = [
        {
            "strike": 100.0,
            "years": 30 / 365,
            "iv": 0.25,
            "sign": 1.0,
            "oi": 1500,
            "multiplier": 100,
        },
        {
            "strike": 90.0,
            "years": 30 / 365,
            "iv": 0.32,
            "sign": -1.0,
            "oi": 2200,
            "multiplier": 100,
        },
        {
            "strike": 110.0,
            "years": 7 / 365,
            "iv": 0.18,
            "sign": 1.0,
            "oi": 800,
            "multiplier": 100,
        },
        # Rejected by _bs_gamma: must not move the total even with huge OI.
        {
            "strike": 100.0,
            "years": 30 / 365,
            "iv": 0.001,
            "sign": 1.0,
            "oi": 5_000_000,
            "multiplier": 100,
        },
        {
            "strike": -5.0,
            "years": 30 / 365,
            "iv": 0.30,
            "sign": -1.0,
            "oi": 5_000_000,
            "multiplier": 100,
        },
        {
            "strike": 100.0,
            "years": 0.0,
            "iv": 0.30,
            "sign": 1.0,
            "oi": 5_000_000,
            "multiplier": 100,
        },
    ]
    spots = [0.0, -10.0, 80.0, 100.0, 120.0]
    got = _net_gex_at_spots(contracts, spots, rate=rate, yield_rate=yield_rate)
    ref = _scalar_net_gex(contracts, spots, rate, yield_rate)
    assert got == pytest.approx(ref, rel=1e-12, abs=1e-9)
    assert got[0] == 0.0
    assert got[1] == 0.0
    assert _net_gex_at_spots([], [100.0], rate=rate) == [0.0]
    assert _net_gex_at_spots(contracts, [], rate=rate) == []


def test_gex_price_profile_matches_scalar_gamma_grid():
    spot = 100.0
    rate = 0.045
    asof = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    expiry = date(2026, 12, 19)
    rows = []
    # Puts below spot and calls above it, so net exposure changes sign in the band.
    for strike, right, oi in (
        (80.0, "put", 4000),
        (90.0, "put", 8000),
        (100.0, "call", 1500),
        (100.0, "put", 1500),
        (110.0, "call", 8000),
        (120.0, "call", 4000),
    ):
        rows.append(
            {
                "strike": strike,
                "dte": 34,
                "expiry": expiry,
                "iv": 0.22 + abs(strike - spot) / 400.0,
                "gamma": None,
                "right": right,
                "open_interest": oi,
                "multiplier": 100,
            }
        )
    rows.append(
        {
            "strike": 100.0,
            "dte": 34,
            "expiry": expiry,
            "iv": 0.001,
            "gamma": None,
            "right": "call",
            "open_interest": 9_000_000,
            "multiplier": 100,
        }
    )
    _mapped, summary, _source, _by_expiry, profile = _gex_map(rows, spot=spot, asof=asof, rate=rate)
    enriched = []
    for row in rows:
        years = max(float(row["dte"] or 0), 0.5) / 365.0
        gamma = _bs_gamma(
            spot=spot,
            strike=float(row["strike"]),
            years=years,
            iv=float(row["iv"] or 0.0),
            rate=rate,
        )
        if not row["strike"] or gamma is None or row["right"] not in {"call", "put"}:
            continue
        enriched.append(
            {
                "strike": float(row["strike"]),
                "years": years,
                "iv": row["iv"],
                "sign": 1.0 if row["right"] == "call" else -1.0,
                "oi": row["open_interest"],
                "multiplier": row["multiplier"],
            }
        )
    band_spots = [spot * (0.80 + i * 0.005) for i in range(81)]
    band_totals = _scalar_net_gex(enriched, band_spots, rate)
    assert [point["net_gex_m"] for point in profile] == [
        round(total / 1_000_000.0, 6) for total in band_totals
    ]
    assert [point["spot"] for point in profile] == [round(value, 4) for value in band_spots]
    crossings = _crossings(list(zip(band_spots, band_totals)))
    assert crossings
    scalar_flip = min(crossings, key=lambda value: abs(value - spot))
    assert summary["gamma_flip"] == round(scalar_flip, 4)
    assert summary["zero_gamma"] == summary["gamma_flip"]


def test_gex_flip_outside_the_band_matches_scalar_search():
    """A zero past ±20% still has to land on the scalar extended search."""
    spot = 100.0
    rate = 0.045
    asof = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    expiry = date(2026, 12, 19)
    rows = [
        {
            "strike": 100.0,
            "dte": 30,
            "expiry": expiry,
            "iv": 0.25,
            "gamma": None,
            "right": "put",
            "open_interest": 50_000,
            "multiplier": 100,
        },
        {
            "strike": 250.0,
            "dte": 30,
            "expiry": expiry,
            "iv": 0.35,
            "gamma": None,
            "right": "call",
            "open_interest": 80_000,
            "multiplier": 100,
        },
    ]
    _mapped, summary, _source, _by_expiry, profile = _gex_map(rows, spot=spot, asof=asof, rate=rate)
    enriched = []
    for row in rows:
        years = max(float(row["dte"] or 0), 0.5) / 365.0
        enriched.append(
            {
                "strike": float(row["strike"]),
                "years": years,
                "iv": row["iv"],
                "sign": 1.0 if row["right"] == "call" else -1.0,
                "oi": row["open_interest"],
                "multiplier": 100,
            }
        )
    band_spots = [spot * (0.80 + i * 0.005) for i in range(81)]
    assert not _crossings(list(zip(band_spots, _scalar_net_gex(enriched, band_spots, rate))))
    search_lo = max(spot * 0.20, 100.0 * 0.90)
    search_hi = min(spot * 3.00, 250.0 * 1.10)
    step = (search_hi - search_lo) / 120
    ext_spots = [search_lo + i * step for i in range(121)]
    ext_totals = _scalar_net_gex(enriched, ext_spots, rate)
    crossings = _crossings(list(zip(ext_spots, ext_totals)))
    assert crossings
    scalar_flip = min(crossings, key=lambda value: abs(value - spot))
    assert scalar_flip > spot * 1.20
    assert summary["gamma_flip"] == round(scalar_flip, 4)
    profile_lo = min(spot * 0.80, scalar_flip * 0.95)
    profile_hi = max(spot * 1.20, scalar_flip * 1.05)
    step = (profile_hi - profile_lo) / 80
    profile_spots = [profile_lo + i * step for i in range(81)]
    profile_totals = _scalar_net_gex(enriched, profile_spots, rate)
    assert [point["net_gex_m"] for point in profile] == [
        round(total / 1_000_000.0, 6) for total in profile_totals
    ]
    assert [point["spot"] for point in profile] == [round(value, 4) for value in profile_spots]


def test_a_thin_same_day_strike_cannot_invert_the_whole_chains_charm_sign():
    """The regression this audit exists for.

    Charm scales like tau^-3/2, so flooring same-day contracts at 1 day let a
    single 0DTE strike with 25x LESS open interest flip the chain's net charm
    flow from -1,444 sh/d (dealers buying) to +162 sh/d (dealers selling) —
    a full sign inversion of the headline signal that drives the directional
    narrative and the trade recommendations on the drift tab.
    """
    from edge.daily_plays.options_intelligence import _charm_map

    book = [_charm_row("call", k, oi=5_000, dte=30) for k in (95, 97, 100, 103, 105)]
    stray = [_charm_row("call", 97, oi=200, dte=0)]

    _, real, _ = _charm_map(book, spot=100, rate=0.045)
    _, mixed, _ = _charm_map(book + stray, spot=100, rate=0.045)

    assert real["net_charm_flow"] < 0, "fixture must be a dealer-buying book"
    # The stray same-day strike is excluded, so it cannot move the aggregate.
    assert mixed["net_charm_flow"] == pytest.approx(real["net_charm_flow"])
    assert mixed["net_charm_flow"] < 0
    assert mixed["skipped_reasons"] == {"expiring_within_one_day": 1}


def test_expiration_day_chain_reports_zero_measured_rather_than_fabricating_flow():
    """A wholly 0DTE chain must say 'not measurable', not print inflated numbers."""
    from edge.daily_plays.options_intelligence import _charm_map

    rows = [_charm_row("call", k, oi=5_000, dte=0) for k in (95, 100, 105)]
    mapped, summary, _ = _charm_map(rows, spot=100, rate=0.045)

    assert summary["contracts_measured"] == 0
    assert summary["skipped_reasons"] == {"expiring_within_one_day": 3}
    assert summary["net_charm_flow"] == 0.0
    assert summary["abs_charm_flow"] == 0.0
    assert all(row["net_charm_flow"] == 0.0 for row in mapped)


# --- pressure read: buyer/seller imbalance, corroboration, confidence ---------
#
# The gauge used to blend three things that are not the same kind of evidence:
# a charm positioning proxy, an UNSIGNED call-vs-put volume mix (every put print
# counted as selling, every call print as buying) and the sign of net GEX (a
# dampening/amplifying regime, not a direction). The result contradicted the
# charm KPI on the same screen and carried no confidence at all. The contract
# below is: only signed evidence votes on direction, unsigned data is context,
# and the read says how much to trust it and why.


def _tape_channel(**overrides):
    base = {
        "signed_premium": 0.0,
        "gross_premium": 0.0,
        "resolved_premium": 0.0,
        "total_premium": 0.0,
        "n_signed": 0,
        "n_total": 0,
        "source_mix": {"vendor": 0, "quote_rule_live": 0, "quote_rule_delayed": 0, "unresolved": 0},
        "buy_premium": 0.0,
        "sell_premium": 0.0,
    }
    base.update(overrides)
    return base


def test_pressure_gauge_unsigned_call_put_mix_is_context_not_direction():
    """Call/put volume identity has no aggressor side, so it must not vote."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=0.0,
        abs_charm_flow=0.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=10_000.0,
        delta_weighted_put_vol=1_000.0,
    )
    assert gauge["imbalance"] == pytest.approx(0.0)
    assert gauge["label"] == "balanced"
    assert gauge["channels"]["volume"] is None
    assert gauge["context"]["call_put_mix"] == pytest.approx(9_000.0 / 11_000.0)
    assert gauge["actionable"] is False
    assert gauge["confidence"]["band"] == "unmeasurable"


def test_pressure_gauge_gex_sets_follow_through_not_direction():
    """GEX sign is a regime (dampening vs amplifying), never buying/selling."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    def gauge(net_gex_m: float):
        return _pressure_gauge(
            net_charm_flow=250_000.0,
            abs_charm_flow=900_000.0,
            net_gex_m=net_gex_m,
            abs_gex_m=150.0,
            delta_weighted_call_vol=0.0,
            delta_weighted_put_vol=0.0,
        )

    positive, negative = gauge(150.0), gauge(-150.0)
    assert positive["imbalance"] == pytest.approx(negative["imbalance"])
    assert positive["imbalance"] == pytest.approx(-250_000.0 / 900_000.0)
    assert positive["channels"]["gex"] is None and negative["channels"]["gex"] is None
    assert positive["context"]["gex_regime"] == "dampening"
    assert negative["context"]["gex_regime"] == "amplifying"


def test_pressure_gauge_tape_channel_votes_with_resolved_sides():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-800_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_250_000.0,
        n_signed=30,
        n_total=40,
        source_mix={"vendor": 0, "quote_rule_live": 30, "quote_rule_delayed": 0, "unresolved": 10},
        buy_premium=100_000.0,
        sell_premium=900_000.0,
    )
    gauge = _pressure_gauge(
        net_charm_flow=0.0,
        abs_charm_flow=0.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
        tape=tape,
    )
    assert gauge["channels"]["tape"] == pytest.approx(-0.8)
    assert gauge["imbalance"] == pytest.approx(-0.8)
    assert gauge["label"] == "selling"
    assert gauge["tape"]["coverage"] == pytest.approx(0.8)
    assert gauge["tape"]["n_signed"] == 30


def test_pressure_gauge_tape_channel_abstains_below_evidence_floor():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    thin = _tape_channel(
        signed_premium=-90_000.0,
        gross_premium=100_000.0,
        resolved_premium=100_000.0,
        total_premium=2_000_000.0,
        n_signed=3,
        n_total=60,
    )
    gauge = _pressure_gauge(
        net_charm_flow=0.0,
        abs_charm_flow=0.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
        tape=thin,
    )
    assert gauge["channels"]["tape"] is None
    assert gauge["imbalance"] == pytest.approx(0.0)
    assert any("tape" in reason for reason in gauge["reasons"])


def test_pressure_gauge_conflicting_channels_are_not_actionable():
    """Charm says buying, the tape says selling: the read must say so, not average it away."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-800_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_100_000.0,
        n_signed=40,
        n_total=44,
        source_mix={"vendor": 40, "quote_rule_live": 0, "quote_rule_delayed": 0, "unresolved": 4},
    )
    gauge = _pressure_gauge(
        net_charm_flow=-800_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
        tape=tape,
    )
    assert abs(gauge["imbalance"]) < 0.25
    assert gauge["actionable"] is False
    names = {item["channel"] for item in gauge["conflicts"]}
    assert {"charm", "tape"} <= names
    assert gauge["confidence"]["band"] in {"low", "unmeasurable"}


def test_pressure_gauge_agreeing_live_channels_are_high_confidence():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-700_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=40,
        n_total=48,
        source_mix={"vendor": 0, "quote_rule_live": 40, "quote_rule_delayed": 0, "unresolved": 8},
    )
    underlying = {"ratio": -0.5, "rvol": 1.4, "bars_used": 7, "timeframe": "1h", "stale": False}
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=-80.0,
        abs_gex_m=120.0,
        delta_weighted_call_vol=1_000.0,
        delta_weighted_put_vol=4_000.0,
        tape=tape,
        underlying=underlying,
        charm_coverage=0.95,
        mode_resolved="live",
    )
    assert gauge["label"] == "selling"
    assert gauge["direction"] == "selling"
    assert gauge["actionable"] is True
    assert gauge["confidence"]["band"] == "high"
    assert gauge["conflicts"] == []
    assert gauge["channels"]["underlying"] == pytest.approx(-0.5)
    assert gauge["context"]["gex_regime"] == "amplifying"
    assert "SELLING" in gauge["verdict"]


def test_pressure_gauge_charm_alone_is_never_actionable():
    """A single positioning proxy cannot confirm itself."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=900_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
        charm_coverage=1.0,
    )
    assert gauge["label"] == "selling"
    assert gauge["actionable"] is False
    assert gauge["confidence"]["band"] in {"low", "unmeasurable"}
    assert any("uncorroborated" in reason for reason in gauge["reasons"])


def test_pressure_gauge_delayed_mode_is_never_actionable():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-700_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=40,
        n_total=48,
        source_mix={"vendor": 40, "quote_rule_live": 0, "quote_rule_delayed": 0, "unresolved": 8},
    )
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=0.0,
        delta_weighted_call_vol=0.0,
        delta_weighted_put_vol=0.0,
        tape=tape,
        charm_coverage=1.0,
        mode_resolved="history",
    )
    assert gauge["label"] == "selling"
    assert gauge["actionable"] is False
    assert gauge["confidence"]["band"] != "high"
    assert any("delayed" in reason or "history" in reason for reason in gauge["reasons"])


def test_underlying_pressure_uses_close_location_value_as_a_labelled_proxy():
    from edge.daily_plays.options_intelligence import _underlying_pressure

    def bar(i: int, *, close_at_high: bool) -> dict:
        return {
            "t": f"2026-07-31T{9 + i:02d}:30:00+00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 101.0 if close_at_high else 99.0,
            "volume": 1_000.0,
        }

    bullish = _underlying_pressure([bar(i, close_at_high=True) for i in range(7)])
    assert bullish is not None
    assert bullish["ratio"] == pytest.approx(1.0)
    assert bullish["bars_used"] == 7
    assert bullish["method"] == "clv_volume_proxy"

    bearish = _underlying_pressure([bar(i, close_at_high=False) for i in range(7)])
    assert bearish["ratio"] == pytest.approx(-1.0)

    assert _underlying_pressure([bar(0, close_at_high=True), bar(1, close_at_high=True)]) is None
    assert _underlying_pressure([]) is None


def _quote_chain(right: str, strike: float, *, quote_live: bool = True) -> dict:
    row = _chain(right, strike)
    row["quote_live"] = quote_live
    return row


_PRINT_SEQ = iter(range(1, 10_000))


def _print(right: str, strike: float, price: float, premium: float = 100_000, **extra) -> dict:
    # Distinct timestamps a minute apart: the tape dedup identity does not
    # include price, and same-contract fills within a few seconds are merged
    # into one sweep-burst row, either of which would hide a fixture print.
    minutes = next(_PRINT_SEQ)
    return {
        "contract_type": right,
        "strike": strike,
        "expiry": "2026-08-28",
        "price": price,
        "premium": premium,
        "volume": 20,
        "timestamp": f"2026-07-31T{13 + minutes // 60:02d}:{minutes % 60:02d}:00Z",
        "multiplier": 100,
        **extra,
    }


def test_quote_rule_infers_print_side_from_live_chain_quote():
    """Trade at the ask = buyer aggressor, at the bid = seller; mid = unresolved.

    Underlying direction: buy call / sell put → buying; buy put / sell call → selling.
    Vendor-signed premium stays untouched so the existing explicit-aggressor
    guarantee is preserved; the inference lives in separate fields.
    """
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_quote_chain("call", 105), _quote_chain("put", 95)],
        flow_rows=[
            _print("call", 105, 5.10),  # lifted the ask → buy call → buying
            _print("put", 95, 5.10),  # lifted the ask → buy put → selling
            _print("call", 105, 4.90),  # hit the bid → sell call → selling
            _print("put", 95, 5.00),  # mid → unresolved
        ],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    tape = result["pressure"]["tape"]
    assert tape["n_total"] == 4
    assert tape["n_signed"] == 4
    assert tape["source_mix"]["quote_rule_live"] == 3
    # The mid print gets the tick test: 5.00 after 5.10 on the same put is a
    # downtick → sold put → buying, at the tick rule's 0.4 weight.
    assert tape["source_mix"]["tick_rule"] == 1
    assert tape["source_mix"]["unresolved"] == 0
    # +100k (buy call) −100k (buy put) −100k (sell call) at 0.8, +100k (sold put) at 0.4.
    assert tape["signed_premium"] == pytest.approx(-100_000.0 * 0.8 + 100_000.0 * 0.4)
    assert tape["coverage"] == pytest.approx(1.0)

    rows = {(row["right"], row["price"]): row for row in result["flow_tape"]}
    assert rows[("call", 5.1)]["inferred_side"] == "buy"
    assert rows[("call", 5.1)]["side_source"] == "quote_rule_live"
    assert rows[("call", 5.1)]["flow_direction"] == 1
    assert rows[("put", 5.1)]["flow_direction"] == -1
    assert rows[("call", 4.9)]["inferred_side"] == "sell"
    assert rows[("put", 5.0)]["inferred_side"] == "sell"
    assert rows[("put", 5.0)]["side_source"] == "tick_rule"
    # Vendor-only signed premium is unchanged by inference.
    assert all(row["signed_premium"] is None for row in result["flow_tape"])
    assert result["quality"]["signed_flow_prints"] == 0


def test_quote_rule_on_delayed_quote_only_counts_prints_outside_the_touch():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[
            _quote_chain("call", 105, quote_live=False),
            _quote_chain("put", 95, quote_live=False),
        ],
        flow_rows=[
            _print("call", 105, 5.20),  # through the ask → buy, discounted
            _print("call", 105, 5.06),  # inside the spread → unresolved on a stale quote
            _print("put", 95, 4.80),  # through the bid → sell put → buying, discounted
        ],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    tape = result["pressure"]["tape"]
    assert tape["source_mix"]["quote_rule_delayed"] == 2
    # Inside the stale spread the quote rule abstains; the tick test then reads
    # 5.06 after 5.20 on the same call as a downtick → sold call.
    assert tape["source_mix"]["tick_rule"] == 1
    assert tape["source_mix"]["unresolved"] == 0
    rows = {(row["right"], row["price"]): row for row in result["flow_tape"]}
    assert rows[("call", 5.2)]["side_source"] == "quote_rule_delayed"
    assert rows[("call", 5.2)]["side_weight"] == pytest.approx(0.5)
    assert rows[("call", 5.06)]["side_source"] == "tick_rule"
    assert rows[("call", 5.06)]["inferred_side"] == "sell"
    assert rows[("put", 4.8)]["flow_direction"] == 1


def test_vendor_aggressor_outranks_quote_rule():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_quote_chain("call", 105), _quote_chain("put", 95)],
        flow_rows=[_print("call", 105, 4.90, aggressor="BUY")],  # at the bid but vendor says buy
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    row = result["flow_tape"][0]
    assert row["inferred_side"] == "buy"
    assert row["side_source"] == "vendor"
    assert row["side_weight"] == pytest.approx(1.0)
    assert row["signed_premium"] is not None


def test_payload_exposes_underlying_channel_when_bars_are_supplied():
    bars = [
        {
            "t": f"2026-07-31T{9 + i:02d}:30:00+00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 99.0,
            "volume": 1_000.0,
        }
        for i in range(7)
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
        underlying_bars=bars,
    )
    pressure = result["pressure"]
    assert pressure["channels"]["underlying"] == pytest.approx(-1.0)
    assert pressure["underlying"]["method"] == "clv_volume_proxy"
    assert pressure["underlying"]["bars_used"] == 7
    # Without bars the channel abstains and says so.
    without = _payload([])["pressure"]
    assert without["channels"]["underlying"] is None
    assert without["underlying"] is None


def _quoteless_chain(right: str, strike: float) -> dict:
    row = _chain(right, strike)
    row.pop("bid")
    row.pop("ask")
    row["quote_live"] = False
    return row


def test_tick_rule_signs_prints_when_the_chain_has_no_quote():
    """Live LSE chains carry no bid/ask; the tick test is the remaining side evidence."""
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_quoteless_chain("call", 105), _quoteless_chain("put", 95)],
        flow_rows=[
            _print("call", 105, 5.00),  # first print: nothing to compare → unresolved
            _print("call", 105, 5.20),  # uptick → buy call → buying
            _print("call", 105, 5.20),  # zero tick inherits the buy
            _print("call", 105, 5.10),  # downtick → sell call → selling
            _print("put", 95, 4.00),  # lone print on its contract → unresolved
        ],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    tape = result["pressure"]["tape"]
    assert tape["n_total"] == 5
    assert tape["n_signed"] == 3
    assert tape["source_mix"]["tick_rule"] == 3
    assert tape["source_mix"]["unresolved"] == 2
    assert tape["quality"] == pytest.approx(0.4)
    # +100k +100k −100k, each at 0.4 weight.
    assert tape["signed_premium"] == pytest.approx(40_000.0)

    rows = sorted(
        (row for row in result["flow_tape"] if row["right"] == "call"),
        key=lambda row: row["timestamp"],
    )
    assert [row["inferred_side"] for row in rows] == [None, "buy", "buy", "sell"]
    assert [row["side_source"] for row in rows] == [None, "tick_rule", "tick_rule", "tick_rule"]
    assert rows[1]["side_weight"] == pytest.approx(0.4)
    assert rows[1]["flow_direction"] == 1 and rows[3]["flow_direction"] == -1


def test_tick_rule_never_overrides_a_quote_rule_side():
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_quote_chain("call", 105), _quote_chain("put", 95)],
        flow_rows=[
            _print("call", 105, 5.10),  # at the ask → buy (quote rule)
            _print(
                "call", 105, 4.90
            ),  # at the bid → sell (quote rule), even though it is a downtick anyway
            _print("call", 105, 5.00),  # mid: quote rule abstains → tick test says uptick → buy
        ],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    rows = {row["price"]: row for row in result["flow_tape"]}
    assert rows[5.1]["side_source"] == "quote_rule_live"
    assert rows[4.9]["side_source"] == "quote_rule_live"
    assert rows[5.0]["side_source"] == "tick_rule" and rows[5.0]["inferred_side"] == "buy"


def test_delayed_quote_from_another_day_is_not_a_reference():
    stale = _quote_chain("call", 105, quote_live=False)
    stale["captured_utc"] = "2026-07-20T15:00:00+00:00"  # eleven days before the prints
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[stale, _quote_chain("put", 95, quote_live=False)],
        flow_rows=[_print("call", 105, 5.20)],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    row = result["flow_tape"][0]
    assert row["inferred_side"] is None
    assert row["side_source"] is None


def test_tick_test_only_tape_caps_confidence_at_medium():
    """Tick-test sides are observed but weak; they confirm a read, never make it 'high'."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-280_000.0,
        gross_premium=400_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=300,
        n_total=360,
        source_mix={
            "vendor": 0,
            "quote_rule_live": 0,
            "quote_rule_delayed": 0,
            "tick_rule": 300,
            "unresolved": 60,
        },
    )
    underlying = {"ratio": -0.6, "rvol": 1.2, "bars_used": 7, "timeframe": "1h", "stale": False}
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=0.0,
        tape=tape,
        underlying=underlying,
        charm_coverage=1.0,
        mode_resolved="live",
    )
    assert gauge["label"] == "selling"
    assert gauge["tape"]["quality"] == pytest.approx(0.4)
    assert gauge["confidence"]["band"] == "medium"
    assert gauge["actionable"] is True
    assert any("tick-test only" in reason for reason in gauge["reasons"])


def test_pressure_gauge_stale_source_age_is_never_actionable():
    """A live mode label cannot promote an 86,000s stale feed into an actionable entry."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-700_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=40,
        n_total=48,
        source_mix={"vendor": 0, "quote_rule_live": 40, "quote_rule_delayed": 0, "unresolved": 8},
    )
    underlying = {"ratio": -0.5, "rvol": 1.4, "bars_used": 7, "timeframe": "1h", "stale": False}
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=-80.0,
        abs_gex_m=120.0,
        delta_weighted_call_vol=1_000.0,
        delta_weighted_put_vol=4_000.0,
        tape=tape,
        underlying=underlying,
        charm_coverage=0.95,
        mode_resolved="live",
        source_age_seconds=86_000.0,
    )
    assert gauge["label"] == "selling"
    assert gauge["actionable"] is False
    assert gauge["confidence"]["freshness"] == 0.0
    assert any("stale" in r for r in gauge["reasons"])
    assert "UNCONFIRMED" in gauge["verdict"]


def test_pressure_gauge_unknown_source_age_is_never_actionable():
    """Missing or unverified feed freshness cannot authorize a live entry."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-700_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=40,
        n_total=48,
        source_mix={"vendor": 0, "quote_rule_live": 40, "quote_rule_delayed": 0, "unresolved": 8},
    )
    underlying = {"ratio": -0.5, "rvol": 1.4, "bars_used": 7, "timeframe": "1h", "stale": False}
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=-80.0,
        abs_gex_m=120.0,
        delta_weighted_call_vol=1_000.0,
        delta_weighted_put_vol=4_000.0,
        tape=tape,
        underlying=underlying,
        charm_coverage=0.95,
        mode_resolved="live",
        source_age_seconds=None,
    )
    assert gauge["label"] == "selling"
    assert gauge["actionable"] is False
    assert gauge["confidence"]["freshness"] <= 0.4
    assert any("unknown" in r for r in gauge["reasons"])


def test_pressure_gauge_fresh_source_age_permits_actionable():
    """A fresh feed under 5 minutes allows high confidence actionable trades."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    tape = _tape_channel(
        signed_premium=-700_000.0,
        gross_premium=1_000_000.0,
        resolved_premium=1_000_000.0,
        total_premium=1_200_000.0,
        n_signed=40,
        n_total=48,
        source_mix={"vendor": 0, "quote_rule_live": 40, "quote_rule_delayed": 0, "unresolved": 8},
    )
    underlying = {"ratio": -0.5, "rvol": 1.4, "bars_used": 7, "timeframe": "1h", "stale": False}
    gauge = _pressure_gauge(
        net_charm_flow=700_000.0,
        abs_charm_flow=1_000_000.0,
        net_gex_m=-80.0,
        abs_gex_m=120.0,
        delta_weighted_call_vol=1_000.0,
        delta_weighted_put_vol=4_000.0,
        tape=tape,
        underlying=underlying,
        charm_coverage=0.95,
        mode_resolved="live",
        source_age_seconds=15.0,
    )
    assert gauge["label"] == "selling"
    assert gauge["actionable"] is True
    assert gauge["confidence"]["freshness"] == 1.0


def test_build_options_intelligence_passes_feed_age_and_prevents_stale_actionable():
    """End-to-end: build_options_intelligence incorporates feed age into pressure gauge."""
    from datetime import timedelta

    # Tape timestamp is 86,000 seconds in the past
    stale_ts = (ASOF - timedelta(seconds=86_000)).isoformat()
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=[
            {
                "contract_type": "call",
                "premium": 100_000,
                "volume": 10,
                "timestamp": stale_ts,
                "aggressor": "BUY",
                "multiplier": 100,
            },
        ],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    assert result["freshness"]["age_seconds"] >= 86_000
    assert result["pressure"]["actionable"] is False
    assert result["pressure"]["confidence"]["freshness"] == 0.0
