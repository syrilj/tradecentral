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
