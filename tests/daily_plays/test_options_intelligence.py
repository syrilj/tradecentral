from datetime import datetime, timezone

import pytest

from edge.daily_plays.options_intelligence import (
    OptionsFilters,
    _best_observation_time,
    _imbalance_confidence,
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
    result = _payload([
        {
            "contract_type": "call", "premium": 100_000, "volume": 10,
            "timestamp": "2026-07-31T14:45:00Z", "aggressor": "BUY", "multiplier": 100,
        },
        {
            "contract_type": "put", "premium": 150_000, "volume": 12,
            "timestamp": "2026-07-31T14:46:00Z", "aggressor": "BUY",
        },
    ])

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
    result = _payload([
        {
            "contract_type": "call", "premium": 750_000, "volume": 50,
            "timestamp": "2026-07-31T14:45:00Z", "multiplier": 100,
            "trade_class": "block",
        },
    ])
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
        _chain("call", 105) | {"delta": 0.46, "bid": 3.9, "ask": 4.1, "occ_symbol": "TEST260828C00105000"},
        _chain("put", 95) | {"delta": -0.44, "bid": 3.7, "ask": 3.9, "occ_symbol": "TEST260828P00095000"},
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
        _chain("call", 105) | {
            "delta": 0.45, "open_interest": 3, "volume": 20,
            "quote_live": False, "quote_source": "yfinance_delayed_exact_occ",
            "occ_symbol": "TEST260828C00105000",
        },
        _chain("call", 107) | {
            "delta": 0.52, "open_interest": 1200, "volume": 300,
            "quote_live": False, "quote_source": "yfinance_delayed_exact_occ",
            "occ_symbol": "TEST260828C00107000",
        },
    ]
    result = build_options_intelligence(
        symbol="TEST", chain_rows=chain, flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100, filters=OptionsFilters(range="1d", min_premium=0, min_volume=0),
        mode_requested="live", mode_resolved="live", chain_source="fixture",
        flow_source="fixture", asof_utc=ASOF,
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
    result = _payload([{
        "contract_type": "call", "premium": 750_000, "volume": 50,
        "timestamp": "2026-07-31T14:45:00Z",
    }])
    row = result["flow_tape"][0]
    assert row["price"] is None
    assert row["trade_class"] == "large"
    assert row["trade_class_source"] == "size_heuristic"


def test_expired_print_is_rejected_instead_of_clamped_to_zero_dte():
    result = _payload([{
        "contract_type": "call", "premium": 100_000, "volume": 10,
        "expiry": "2026-07-30", "timestamp": "2026-07-31T14:45:00Z",
    }])
    assert result["flow_tape"] == []
    assert result["quality"]["flow_rejected"]["invalid"] == 1


def test_sweep_burst_promotes_trade_class():
    rows = [
        {
            "contract_type": "call", "premium": 80_000, "volume": 20, "strike": 105,
            "expiry": "2026-08-28",
            "timestamp": f"2026-07-31T14:45:0{i}Z", "aggressor": "BUY",
        }
        for i in range(3)
    ]
    result = _payload(rows)
    assert all(r["trade_class"] == "sweep" for r in result["flow_tape"])
    assert any("sweep_burst" in r["anomaly_flags"] for r in result["flow_tape"])
    assert any("burst sweep ≤3s" in (r.get("why") or []) for r in result["flow_tape"])


def test_call_put_identity_and_stale_quote_proxy_stay_unsigned():
    result = _payload([
        {
            "contract_type": "call", "premium": 125_000, "volume": 10,
            "timestamp": "2026-07-31T14:45:00Z", "_stale_quote_side": "BUY",
        },
    ])

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
    unsigned = _payload([
        {
            "contract_type": "call", "premium": 125_000, "volume": 10,
            "timestamp": "2026-07-31T14:45:00Z",
        },
    ])
    assert unsigned["summary"]["activity_imbalance"] == 1.0
    assert unsigned["summary"]["signed_flow_imbalance"] is None
    assert unsigned["summary"]["squeeze"]["theory"]["directional_flow_imbalance"] == 0.0
    # Unsigned tape still gets a live activity-shift readout (call+/put−),
    # which must not leak into the signed squeeze term.
    activity = unsigned["summary"]["activity_shift"]
    assert activity is not None
    assert activity["kind"] == "contract_activity"
    assert activity["n"] >= 1
    assert activity["signed_imbalance"] > 0


def test_signed_flow_imbalance_is_sample_size_shrunk_for_squeeze():
    signed = _payload([
        {
            "contract_type": "call", "premium": 125_000, "volume": 10,
            "timestamp": "2026-07-31T14:45:00Z", "aggressor": "BUY",
        },
    ])
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
        rows.append({
            "contract_type": right,
            "premium": 125_000,
            "volume": 10,
            "timestamp": f"2026-07-31T{hour:02d}:{minute:02d}:00Z",
            "aggressor": aggressor,
        })
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
        flow_rows=_signed_prints(8, side="buy_call") + _signed_prints(8, side="buy_put", start_hour=13),
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
    assert any("True dealer inventory is not public" in note or "true dealer inventory is not public" in note for note in result["caveats"])


def test_gex_walls_are_directional_not_global_argmax():
    """ATM strike with both huge call and put mass must not set both walls there.

    InsiderFinance / SpotGamma: call wall = resistance above spot, put wall =
    support below spot.
    """
    asof = ASOF
    chain = [
        {
            "right": "call", "expiry": "2026-08-28", "strike": 100, "bid": 4.9, "ask": 5.1,
            "volume": 500, "open_interest": 50_000, "iv": 0.35, "gamma": 0.05,
            "multiplier": 100, "captured_utc": asof.isoformat(), "spot": 100,
        },
        {
            "right": "put", "expiry": "2026-08-28", "strike": 100, "bid": 4.9, "ask": 5.1,
            "volume": 500, "open_interest": 50_000, "iv": 0.35, "gamma": 0.05,
            "multiplier": 100, "captured_utc": asof.isoformat(), "spot": 100,
        },
        {
            "right": "call", "expiry": "2026-08-28", "strike": 110, "bid": 1.9, "ask": 2.1,
            "volume": 100, "open_interest": 8_000, "iv": 0.35, "gamma": 0.02,
            "multiplier": 100, "captured_utc": asof.isoformat(), "spot": 100,
        },
        {
            "right": "put", "expiry": "2026-08-28", "strike": 90, "bid": 1.9, "ask": 2.1,
            "volume": 100, "open_interest": 8_000, "iv": 0.35, "gamma": 0.02,
            "multiplier": 100, "captured_utc": asof.isoformat(), "spot": 100,
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
    result = _payload([
        {
            "contract_type": "call", "premium": 250_000, "volume": 40,
            "timestamp": "2026-07-31T14:45:00Z", "aggressor": "BUY",
        },
    ])
    squeeze = result["summary"]["squeeze"]
    assert "bullish" in squeeze and "bearish" in squeeze
    assert "score" in squeeze  # signed gex_core score [-100, 100]
    assert -100 <= squeeze["score"] <= 100
    assert squeeze["label"] in {
        "quiet", "two_way", "bullish_lean", "bullish_squeeze", "bearish_lean", "bearish_squeeze",
    }
    assert squeeze["primary"] in {"quiet", "two_way", "bullish", "bearish"}
    method = squeeze.get("method") or ""
    assert "theory" in method or "gex_core" in method
    assert "theory" in squeeze or "components" in squeeze
    assert "components" in squeeze
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
                "contract_type": "call", "premium": 1_000, "volume": 10,
                "strike": 105, "expiry": "2026-08-28",
                "timestamp": "2026-07-31T14:45:00Z",
            },
            {
                "contract_type": "put", "premium": 125_000, "volume": 20,
                "strike": 90, "expiry": "2026-09-18",
                "timestamp": "2026-07-31T14:46:00Z",
            },
        ],
        price_series=[],
        spot=100,
        filters=OptionsFilters(
            range="1d", min_premium=50_000, min_volume=1,
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
    rows.append({
        "contract_type": "put",
        "premium": 2_000_000,
        "volume": 500,
        "strike": 70,
        "timestamp": "2026-07-31T14:10:00Z",
    })
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
            range="1d", min_premium=0, min_volume=0, min_open_interest=0,
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
        chain_rows=[{
            "right": "call", "expiry": "2026-08-28", "strike": 105,
            "volume": 500, "open_interest": 2_000, "iv": 0.35, "gamma": 0.02,
            "multiplier": 100, "captured_utc": ASOF.isoformat(), "spot": 100,
        }],
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
    put = _bs_charm_per_day(spot=100, strike=100, years=30 / 365, iv=0.35, rate=0.045, is_call=False)
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
        {"right": "call", "strike": 100, "dte": 30, "iv": 0.35, "open_interest": 2_000, "multiplier": 100},
        {"right": "put", "strike": 100, "dte": 30, "iv": 0.35, "open_interest": 2_000, "multiplier": 100},
    ]
    _, summary, _ = _charm_map(rows, spot=100, rate=0.045)
    # Equal OI on both sides → net ≈ 0 → balanced.
    assert summary["pressure"] == "balanced"

    rows = [
        {"right": "call", "strike": 100, "dte": 30, "iv": 0.35, "open_interest": 2_000, "multiplier": 100},
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
        net_charm_flow=500.0, net_gex_m=0.0,
        delta_weighted_call_vol=0.0, delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(-1.0)
    assert gauge["label"] == "selling"

    gauge = _pressure_gauge(
        net_charm_flow=-500.0, net_gex_m=0.0,
        delta_weighted_call_vol=0.0, delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(1.0)
    assert gauge["label"] == "buying"

    gauge = _pressure_gauge(
        net_charm_flow=0.0, net_gex_m=0.0,
        delta_weighted_call_vol=0.0, delta_weighted_put_vol=0.0,
    )
    assert gauge["imbalance"] == pytest.approx(0.0)
    assert gauge["label"] == "balanced"


def test_pressure_gauge_blends_gex_and_delta_weighted_volume():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    # Charm flow 0, GEX 0, but delta-weighted call volume dominates → buying.
    gauge = _pressure_gauge(
        net_charm_flow=0.0, net_gex_m=0.0,
        delta_weighted_call_vol=10_000.0, delta_weighted_put_vol=1_000.0,
    )
    assert gauge["imbalance"] > 0.25
    assert gauge["label"] == "buying"
    assert gauge["components"]["delta_weighted_call_vol"] == pytest.approx(10_000.0)


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


# --- charm / pressure-gauge math audit regressions ---------------------------


def _charm_row(right: str, strike: float, *, oi: int = 2_000, dte: int | None = 30,
               iv: float = 0.35) -> dict:
    return {
        "right": right, "strike": strike, "open_interest": oi, "volume": 0,
        "iv": iv, "dte": dte, "multiplier": 100,
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

    rows = [_charm_row("call", k) for k in (90, 95, 100, 105, 110)] + \
           [_charm_row("put", k) for k in (90, 95, 100, 105, 110)]
    mapped, summary, _ = _charm_map(rows, spot=100, rate=0.045)

    expected = sum(abs(r["call_charm_flow"]) + abs(r["put_charm_flow"]) for r in mapped)
    assert summary["abs_charm_flow"] == pytest.approx(expected)
    # Strikes genuinely straddle spot, so this test would be vacuous otherwise.
    assert any(r["call_charm_flow"] > 0 for r in mapped)
    assert any(r["call_charm_flow"] < 0 for r in mapped)
    assert summary["abs_charm_flow"] > abs(summary["net_charm_flow"])


def test_pressure_gauge_gex_channel_is_not_drowned_by_charm_flow_units():
    """GEX ($M) must still move the gauge against charm flow (shares/day).

    The old additive form summed raw quantities across incompatible units; on a
    realistic name the GEX term supplied ~0% of the denominator and even a
    $5,000M GEX moved the reading only from -1.000 to -0.980.
    """
    from edge.daily_plays.options_intelligence import _pressure_gauge

    def gauge(net_gex_m: float) -> float:
        return _pressure_gauge(
            net_charm_flow=250_000.0, abs_charm_flow=900_000.0,
            net_gex_m=net_gex_m, abs_gex_m=150.0,
            delta_weighted_call_vol=0.0, delta_weighted_put_vol=0.0,
        )["imbalance"]

    swing = gauge(150.0) - gauge(-150.0)
    assert swing > 0.5, f"GEX barely moves the gauge (swing={swing})"
    assert gauge(150.0) > gauge(0.0) > gauge(-150.0)


def test_pressure_gauge_channels_abstain_when_they_have_no_gross_magnitude():
    """A channel with no data must not vote 'balanced' and dilute the others."""
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=250_000.0, abs_charm_flow=900_000.0,
        net_gex_m=0.0, abs_gex_m=0.0,
        delta_weighted_call_vol=0.0, delta_weighted_put_vol=0.0,
    )
    assert gauge["channels"]["gex"] is None
    assert gauge["channels"]["volume"] is None
    # Pure charm read: -250k/900k, undiluted by the two silent channels.
    assert gauge["channels"]["charm"] == pytest.approx(-250_000.0 / 900_000.0)
    assert gauge["imbalance"] == pytest.approx(-250_000.0 / 900_000.0)


def test_pressure_gauge_stays_bounded_and_blends_all_three_channels():
    from edge.daily_plays.options_intelligence import _pressure_gauge

    gauge = _pressure_gauge(
        net_charm_flow=-900_000.0, abs_charm_flow=900_000.0,
        net_gex_m=150.0, abs_gex_m=150.0,
        delta_weighted_call_vol=90_000.0, delta_weighted_put_vol=0.0,
    )
    # Every channel maxed bullish -> saturates at exactly +1, never beyond.
    assert gauge["imbalance"] == pytest.approx(1.0)
    assert gauge["label"] == "buying"
    assert gauge["channels"] == {"charm": 1.0, "volume": 1.0, "gex": 1.0}


def test_bs_gamma_matches_bs_delta_on_dividend_handling():
    """Gamma dropped the yield terms that d1/delta carried, so they disagreed."""
    import math
    from edge.daily_plays.options_intelligence import _bs_gamma, _bs_delta

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
