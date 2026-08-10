from datetime import datetime, timezone

import pytest

from edge.daily_plays.options_intelligence import (
    OptionsFilters,
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
        "spot": 100,
    }


def _payload(flow_rows):
    return build_options_intelligence(
        symbol="TEST",
        chain_rows=[_chain("call", 105), _chain("put", 95)],
        flow_rows=flow_rows,
        price_series=[{"t": ASOF.isoformat(), "close": 100}],
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
            "timestamp": "2026-07-31T14:45:00Z", "aggressor": "BUY",
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


def test_tape_back_solves_price_and_classifies_block():
    result = _payload([
        {
            "contract_type": "call", "premium": 750_000, "volume": 50,
            "timestamp": "2026-07-31T14:45:00Z",
        },
    ])
    row = result["flow_tape"][0]
    assert row["price"] == 150.0
    assert row["contracts"] == 50
    assert row["trade_class"] == "block"
    assert row["bias"] is None
    assert row["edge_label"] == "CALL"  # activity identity when unsigned
    assert row["aggressor_label"] == "NO SIDE"


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
        price_series=[{"t": ASOF.isoformat(), "close": 100}],
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
