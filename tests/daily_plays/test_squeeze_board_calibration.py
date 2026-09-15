"""Regression tests for the options-tab squeeze board calibration.

Each test pins a defect found in the audit of the /options squeeze readout:

1. Factor meters were clamped against their *display* max rather than normalised
   by the true range of their gex_core component, so ``OTM Concentration`` (range
   15, max 20) and ``Wall Asymmetry`` (range 10, max 15) could never fill and a
   perfect structure topped out at 90/100.
2. ``long_gamma_dampened`` required raw squeeze risk < 1e-6, which is unreachable
   under the short-premium assumption (dealer GEX is ≤ 0 by construction), so the
   flag only fired on unmeasurable chains — the inverse of its meaning.
3. The ``Gamma Regime`` meter was signed by wall structure, hiding real
   direction-neutral fuel from whichever board the walls disagreed with.
4. ``negative_fuel`` was reported on a different scale from the one the theory
   scores use, and silently fell back to an unrelated charting-GEX ratio.
"""
from datetime import date, datetime, timedelta, timezone

from edge.daily_plays.gex_core import STRUCTURE_COMPONENT_RANGES, compute_squeeze_score
from edge.daily_plays.options_intelligence import _setup_from_gex_score, _squeeze_readout


def _perfect_bullish_structure():
    return compute_squeeze_score(
        spot=100.0, call_wall=100.0, put_wall=90.0, flip=98.0,
        near_net=-10.0, net_dealer=-10.0,
        otm_call_weight=1000.0, otm_put_weight=0.0, total_weight=1000.0,
        by_strike=[{"strike": 100.0, "call_gex": 50.0, "put_gex": -1.0}],
        expected_move_pct=5.0, expected_move_low=95.0, expected_move_high=105.0,
    )


def test_component_ranges_cover_every_scored_component():
    """The published ranges must describe every term the board reads."""
    produced = set(_perfect_bullish_structure()["structure_components"])
    assert produced <= set(STRUCTURE_COMPONENT_RANGES)


def test_perfect_structure_reaches_full_board():
    """A maximal structure with full fuel must be able to score 100/100."""
    setup = _setup_from_gex_score(
        side="bullish", signed_score=60.0,
        components=_perfect_bullish_structure()["structure_components"],
        wall_level=100.0, wall_pct=0.0, spot=100.0,
        near_net=-10.0, net_dealer=-10.0, fuel=1.0, dampened=False,
    )
    assert setup["score"] == 100
    # and no meter is structurally unfillable
    for factor in setup["factors"]:
        assert factor["score"] == factor["max"], factor


def test_gamma_regime_meter_is_direction_neutral():
    """Fuel amplifies whichever way price moves; it is not owned by one side."""
    # Real fuel, but the wall structure leans bearish.
    structure = compute_squeeze_score(
        spot=100.0, call_wall=112.0, put_wall=100.0, flip=98.0,
        near_net=-20.0, net_dealer=-20.0,
        otm_call_weight=0.0, otm_put_weight=1000.0, total_weight=1000.0,
        by_strike=[{"strike": 112.0, "call_gex": 1.0, "put_gex": -50.0}],
        expected_move_pct=5.0, expected_move_low=95.0, expected_move_high=105.0,
    )
    assert structure["structure_components"]["regime_score"] < 0  # bearish-signed
    regimes = {}
    for side, wall in (("bullish", 112.0), ("bearish", 100.0)):
        setup = _setup_from_gex_score(
            side=side, signed_score=0.0,
            components=structure["structure_components"],
            wall_level=wall, wall_pct=0.0, spot=100.0,
            near_net=-20.0, net_dealer=-20.0, fuel=0.8, dampened=False,
        )
        regimes[side] = next(f for f in setup["factors"] if f["id"] == "regime_score")
    assert regimes["bullish"]["score"] == regimes["bearish"]["score"] == 20


def test_structure_dampening_ignores_a_zero_net_direction():
    """Deeply short-gamma books must not be labelled long-gamma when walls cancel."""
    out = compute_squeeze_score(
        spot=100.0, call_wall=None, put_wall=None, flip=None,
        near_net=-40.0, net_dealer=-40.0,
        otm_call_weight=0.0, otm_put_weight=0.0, total_weight=1000.0,
        by_strike=[], expected_move_pct=5.0,
        expected_move_low=95.0, expected_move_high=105.0,
    )
    assert out["structure_components"]["regime_score"] == 0.0  # no direction
    assert out["long_gamma_dampened"] is False  # but the regime is short gamma
    assert out["negative_fuel"] == 1.0


# --- payload level -----------------------------------------------------------

_GEX_ROWS = [
    {"strike": 100.0, "call_gex_m": 6.0, "put_gex_m": -1.0, "net_gex_m": 5.0,
     "call_oi": 5000, "put_oi": 1000},
    {"strike": 105.0, "call_gex_m": 4.0, "put_gex_m": -0.5, "net_gex_m": 3.5,
     "call_oi": 8000, "put_oi": 500},
]
_SUMMARY = {"total_gex_m": 8.5, "regime": "positive", "call_wall": 105.0,
            "put_wall": 95.0, "gamma_flip": 98.0}
_CHAIN = [
    {"right": "call", "strike": 100.0, "gamma": 0.04, "open_interest": 5000,
     "multiplier": 100, "dte": 30, "iv": 0.4},
    {"right": "put", "strike": 100.0, "gamma": 0.04, "open_interest": 1000,
     "multiplier": 100, "dte": 30, "iv": 0.4},
]


def _readout(daily_volume: float):
    base = date(2026, 8, 18)
    prices = [
        {"date": str(base - timedelta(days=i)), "close": 100.0, "volume": daily_volume}
        for i in range(20)
    ][::-1]
    return _squeeze_readout(
        spot=100.0, gex_summary=_SUMMARY, gex_rows=_GEX_ROWS, chain_rows=_CHAIN,
        price_series=prices, atm_iv=0.4, horizon_days=30,
        asof=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )


def test_long_gamma_with_deep_liquidity_is_dampened():
    """Positive near-spot GEX plus liquidity that swamps the book = no squeeze."""
    out = _readout(daily_volume=90_000_000.0)
    assert out["key_levels"]["near_spot_net_gex_m"] > 0
    assert out["long_gamma_dampened"] is True
    assert out["negative_fuel"] < 0.2


def test_thin_liquidity_clears_the_dampening_flag():
    """Same long-gamma chart, but the book is large relative to ADV — fuel is real."""
    out = _readout(daily_volume=150_000.0)
    assert out["key_levels"]["near_spot_net_gex_m"] > 0
    assert out["long_gamma_dampened"] is False
    assert out["negative_fuel"] > 0.2


def _falling_readout(**flow):
    base = date(2026, 8, 18)
    closes = [100.0] * 14 + [100.0, 99.5, 99.0, 98.5, 98.0, 97.0]
    prices = [
        {"date": str(base - timedelta(days=19 - i)), "close": c, "volume": 150_000.0}
        for i, c in enumerate(closes)
    ]
    return _squeeze_readout(
        spot=100.0, gex_summary=_SUMMARY, gex_rows=_GEX_ROWS, chain_rows=_CHAIN,
        price_series=prices, atm_iv=0.4, horizon_days=30,
        asof=datetime(2026, 8, 19, tzinfo=timezone.utc), **flow,
    )


def test_unsigned_tape_does_not_vote_in_conviction():
    """No aggressor side = flow is dropped, not counted as a neutral half-weight 0."""
    out = _falling_readout()
    theory = out["theory"]
    assert theory["flow_measured"] is False
    assert theory["flow_weight"] == 0.0
    assert theory["directional_flow_imbalance"] is None
    # Momentum alone carries direction, so a saturated down move is full conviction
    # instead of being capped at half of fuel.
    assert theory["conviction_bear"] == theory["mom_dn_gate"] == 1.0
    assert theory["bearish_ui"] > 0.99 * 100.0 * theory["fuel_ui"] - 0.01


def test_signed_tape_keeps_the_flow_weight():
    out = _falling_readout(directional_flow_imbalance=0.0, imbalance_confidence=1.0)
    theory = out["theory"]
    assert theory["flow_measured"] is True
    assert theory["flow_weight"] == 0.5
    assert theory["conviction_bear"] == 0.5


def test_setup_analysis_never_claims_an_opposing_score_supports_a_side():
    out = _falling_readout()
    assert out["score"] < -20
    bull_lines = " ".join(out["bullish_setup"]["setup_analysis"])
    assert "supports bullish" not in bull_lines
    assert "supports bearish" in " ".join(out["bearish_setup"]["setup_analysis"])


def test_reported_fuel_matches_the_theory_scale():
    """``negative_fuel`` must be the same quantity the directional scores consume."""
    out = _readout(daily_volume=150_000.0)
    assert out["negative_fuel"] == round(out["theory"]["fuel_ui"], 4)
    # the charting-GEX ratio is still available, but under its own name
    assert "structure_negative_fuel" in out
