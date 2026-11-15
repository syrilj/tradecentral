"""Pre-trade gamma reads: call resistance, absolute gamma, zero gamma, support."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from edge.daily_plays.gamma_resistance import (
    compute_gamma_resistance,
    gamma_resistance_from_chain,
    parse_dte_param,
)
from edge.daily_plays.options_intelligence import _bs_gamma

ASOF = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
RATE = 0.045


def _expected_gamma(
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float,
    q: float,
) -> float:
    root = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * iv * iv) * years) / (iv * root)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return math.exp(-q * years) * pdf / (spot * iv * root)


def _contract(
    right: str,
    strike: float,
    *,
    oi: float = 1000,
    iv: float | None = 0.25,
    dte: int = 30,
    gamma: float | None = None,
    spot: float = 100.0,
    yield_rate: float | None = None,
    multiplier: float = 100,
) -> dict:
    row = {
        "right": right,
        "strike": strike,
        "open_interest": oi,
        "iv": iv,
        "dte": dte,
        "expiry": (ASOF.date() + timedelta(days=dte)).isoformat(),
        "multiplier": multiplier,
        "spot": spot,
        "captured_utc": ASOF.isoformat(),
    }
    if gamma is not None:
        row["gamma"] = gamma
    if yield_rate is not None:
        row["dividend_yield"] = yield_rate
    return row


def _reads(rows: list[dict], **kwargs):
    kwargs.setdefault("spot", 100.0)
    kwargs.setdefault("asof", ASOF)
    kwargs.setdefault("now", ASOF)
    kwargs.setdefault("rate", RATE)
    return gamma_resistance_from_chain(rows, **kwargs)


def test_black_scholes_gamma_matches_the_dividend_adjusted_formula():
    """The screen reprices with the dividend-adjusted gamma, not the q=0 shortcut."""
    years = 1.0
    got = _bs_gamma(spot=100.0, strike=100.0, years=years, iv=0.2, rate=0.0, yield_rate=0.0)
    # d1 = 0.1, Γ = φ(0.1) / (S σ √T) = 0.01984762737385059
    assert got is not None
    assert abs(got - 0.01984762737385059) < 1e-12
    assert abs(got - _expected_gamma(100, 100, years, 0.2, 0.0, 0.0)) < 1e-15

    with_yield = _bs_gamma(
        spot=100.0, strike=100.0, years=years, iv=0.2, rate=0.045, yield_rate=0.02
    )
    without = _bs_gamma(spot=100.0, strike=100.0, years=years, iv=0.2, rate=0.045, yield_rate=0.0)
    assert with_yield is not None and without is not None
    assert with_yield != without
    assert abs(with_yield - _expected_gamma(100, 100, years, 0.2, 0.045, 0.02)) < 1e-15
    assert abs(without - _expected_gamma(100, 100, years, 0.2, 0.045, 0.0)) < 1e-15


def test_dividend_yield_changes_absolute_gamma():
    years = 30 / 365
    plain = _reads([_contract("call", 100, yield_rate=0.0)])
    yielded = _reads([_contract("call", 100, yield_rate=0.02)])
    g0 = _expected_gamma(100, 100, years, 0.25, RATE, 0.0)
    gq = _expected_gamma(100, 100, years, 0.25, RATE, 0.02)
    assert plain["absolute_gamma_m"] > 0
    assert abs(yielded["absolute_gamma_m"] / plain["absolute_gamma_m"] - gq / g0) < 1e-6


def test_missing_open_interest_is_not_a_flat_book():
    rows = [
        {"right": "call", "strike": 105, "iv": 0.3, "dte": 30, "spot": 100, "gamma": 0.04},
        {"right": "put", "strike": 95, "iv": 0.3, "dte": 30, "spot": 100, "open_interest": None},
    ]
    payload = _reads(rows)
    assert payload["measurable"] is False
    assert payload["absolute_gamma_m"] is None
    assert payload["net_gamma_m"] is None
    assert payload["zero_gamma"] is None
    assert payload["call_resistance"] is None
    assert payload["nearby_support"] is None
    assert payload["regime"] == "unmeasured"
    assert payload["reason"] == "open_interest_unavailable"


def test_explicit_zero_open_interest_does_not_invent_a_level():
    payload = _reads([_contract("call", 110, oi=0), _contract("put", 90, oi=0)])
    assert payload["measurable"] is False
    assert payload["absolute_gamma_m"] is None
    assert payload["reason"] == "unmeasured"


def test_call_resistance_follows_dollar_gamma_not_open_interest():
    near_g = _bs_gamma(spot=100, strike=105, years=30 / 365, iv=0.25, rate=RATE)
    far_g = _bs_gamma(spot=100, strike=140, years=30 / 365, iv=0.25, rate=RATE)
    assert near_g and far_g and far_g / near_g < 0.5
    oi_far = 20_000
    oi_near = max(1, int(oi_far * (far_g / near_g) * 3))
    assert oi_near < oi_far
    payload = _reads(
        [
            _contract("call", 140, oi=oi_far),
            _contract("call", 105, oi=oi_near),
            _contract("put", 95, oi=500),
        ]
    )
    resistance = payload["call_resistance"]
    assert resistance is not None
    assert resistance["level"] == 105
    assert resistance["distance"] == 5
    assert resistance["dollar_gamma_m"] > 0
    assert resistance["share"] > 0.5
    assert resistance["concentrated"] is True


def test_no_call_above_spot_leaves_resistance_missing():
    payload = _reads([_contract("call", 90, oi=5_000), _contract("put", 80, oi=4_000)])
    assert payload["measurable"] is True
    assert payload["call_resistance"] is None
    assert payload["call_resistance_reason"] == "no_calls_above_spot"
    assert payload["absolute_gamma_m"] > 0


def test_absolute_gamma_is_the_unsigned_sum_and_names_its_peak_strike():
    payload = _reads(
        [
            _contract("call", 100, oi=1_000),
            _contract("put", 100, oi=1_000),
            _contract("call", 110, oi=100),
        ]
    )
    assert payload["absolute_gamma_m"] == round(
        payload["call_gamma_m"] + abs(payload["put_gamma_m"]), 6
    )
    assert payload["absolute_gamma_strike"] == 100
    assert payload["regime"] == "positive"
    # Equal call and put gamma at one strike cancel; the extra call keeps net positive.
    assert payload["net_gamma_m"] > 0
    assert payload["net_gamma_m"] < payload["absolute_gamma_m"]


def test_balanced_straddle_is_neutral_and_has_no_unique_zero():
    """Call and put gamma match at every spot when the strike, IV, and tenor match.

    Net dollar-gamma is identically zero, so there is no flip to point at.
    """
    payload = _reads([_contract("call", 100, oi=2_000), _contract("put", 100, oi=2_000)])
    assert payload["regime"] == "neutral"
    assert abs(payload["net_gamma_m"]) < 1e-6
    assert payload["absolute_gamma_m"] > 0
    assert payload["zero_gamma"] is None
    assert payload["zero_gamma_reason"] == "no_sign_change"


def test_zero_gamma_is_the_repriced_sign_change_nearest_spot():
    rows = [
        _contract("call", 110, oi=8_000),
        _contract("put", 90, oi=8_000),
        _contract("call", 100, oi=1_000),
        _contract("put", 100, oi=1_000),
    ]
    payload = _reads(rows)
    zero = payload["zero_gamma"]
    assert zero is not None
    assert 75 < zero < 125
    at = _reads(rows, spot=zero)
    below = _reads(rows, spot=zero - 1.0)
    above = _reads(rows, spot=zero + 1.0)
    assert abs(at["net_gamma_m"]) < min(abs(below["net_gamma_m"]), abs(above["net_gamma_m"]))
    assert below["net_gamma_m"] * above["net_gamma_m"] < 0
    assert payload["zero_gamma_side"] in {"above", "below", "at"}


def test_call_only_book_does_not_invent_a_zero():
    payload = _reads([_contract("call", 105, oi=2_000), _contract("call", 110, oi=2_000)])
    assert payload["regime"] == "positive"
    assert payload["zero_gamma"] is None
    assert payload["zero_gamma_reason"] == "no_sign_change"
    assert payload["nearby_support"] is None
    assert payload["nearby_support_reason"] == "no_puts_below_spot"


def test_zero_gamma_stays_blank_when_less_than_half_the_contracts_have_iv():
    """A few fat IV strikes must not publish a flip the rest of the book cannot reprice."""
    priced = [
        _contract("call", 110, oi=50_000),
        _contract("put", 90, oi=50_000),
    ]
    quoted = [
        {
            "right": "call",
            "strike": strike,
            "open_interest": 10,
            "gamma": 0.01,
            "dte": 30,
            "spot": 100,
            "captured_utc": ASOF.isoformat(),
        }
        for strike in (98, 100, 102)
    ]
    payload = _reads([*priced, *quoted])
    assert payload["quality"]["gamma_black_scholes"] == 2
    assert payload["quality"]["contracts_measured"] == 5
    assert payload["quality"]["revalue_coverage"] > 0.5
    assert payload["zero_gamma"] is None
    assert payload["zero_gamma_reason"] == "iv_coverage_insufficient"


def test_nearby_shelf_is_not_erased_by_a_heavier_distant_wall():
    payload = _reads(
        [
            _contract("call", 110, oi=2_000),
            _contract("put", 96, oi=800),
            _contract("put", 91, oi=40_000),
        ]
    )
    support = payload["nearby_support"]
    wall = payload["put_wall"]
    assert wall is not None and wall["level"] == 91
    assert support is not None
    assert support["level"] == 96
    assert abs(support["distance_pct"]) <= 0.08


def test_provider_gamma_without_iv_cannot_set_the_zero():
    rows = [
        {
            "right": "call",
            "strike": 105,
            "open_interest": 1_000,
            "gamma": 0.05,
            "dte": 30,
            "spot": 100,
            "captured_utc": ASOF.isoformat(),
        },
        {
            "right": "put",
            "strike": 95,
            "open_interest": 1_000,
            "gamma": 0.05,
            "dte": 30,
            "spot": 100,
            "captured_utc": ASOF.isoformat(),
        },
    ]
    payload = _reads(rows)
    assert payload["measurable"] is True
    assert payload["absolute_gamma_m"] > 0
    assert payload["call_resistance"]["level"] == 105
    assert payload["zero_gamma"] is None
    assert payload["zero_gamma_reason"] == "iv_coverage_insufficient"
    assert payload["quality"]["gamma_provider"] == 2
    assert payload["quality"]["gamma_black_scholes"] == 0
    assert payload["quality"]["revalue_coverage"] == 0


def test_nearby_support_is_the_close_shelf_not_the_distant_wall():
    # 95 is inside the 8% band. 90 is just outside it and, at this open interest,
    # carries more put dollar-gamma — the heavy wall, not the nearby shelf.
    payload = _reads(
        [
            _contract("call", 110, oi=2_000),
            _contract("put", 95, oi=1_650),
            _contract("put", 90, oi=10_000),
        ]
    )
    support = payload["nearby_support"]
    wall = payload["put_wall"]
    assert support is not None and wall is not None
    assert support["level"] == 95
    assert wall["level"] == 90
    assert support["distance"] < 0
    assert payload["nearby_support_reason"] is None


def test_distant_put_wall_is_not_called_nearby_support():
    payload = _reads(
        [
            _contract("call", 105, oi=1_000),
            _contract("put", 90, oi=5_000),
        ]
    )
    assert payload["nearby_support"] is None
    assert payload["nearby_support_reason"] == "no_put_gamma_inside_band"
    assert payload["put_wall"]["level"] == 90
    assert payload["absolute_gamma_m"] is not None


def test_percent_iv_is_rescaled_and_matches_a_decimal_quote():
    decimal = _reads([_contract("call", 100, iv=0.30)])
    percent = _reads([_contract("call", 100, iv=30)])
    assert decimal["absolute_gamma_m"] == percent["absolute_gamma_m"]
    assert percent["quality"]["iv_rescaled"] == 1


def test_implausible_vendor_gamma_is_not_a_measurement():
    payload = _reads(
        [
            {
                "right": "call",
                "strike": 100,
                "open_interest": 500,
                "gamma": 50,
                "dte": 30,
                "spot": 100,
            }
        ]
    )
    assert payload["measurable"] is False
    assert payload["absolute_gamma_m"] is None
    assert payload["reason"] == "gamma_unavailable"


def test_nan_and_blank_rows_are_skipped_without_poisoning_the_sum():
    payload = _reads(
        [
            _contract("call", 105, oi=1_000),
            {"right": "call", "strike": 110, "open_interest": float("nan"), "iv": 0.3, "dte": 20},
            {"right": "put", "strike": float("nan"), "open_interest": 100, "iv": 0.3, "dte": 20},
        ]
    )
    assert payload["measurable"] is True
    assert payload["absolute_gamma_m"] > 0
    assert math.isfinite(payload["absolute_gamma_m"])
    assert payload["quality"]["contracts_measured"] == 1


def test_max_dte_window_drops_the_book_instead_of_zeroing_it():
    payload = _reads([_contract("call", 105, dte=30), _contract("put", 95, dte=30)], max_dte=7)
    assert payload["measurable"] is False
    assert payload["reason"] == "outside_dte"
    assert payload["absolute_gamma_m"] is None
    assert payload["zero_gamma"] is None
    assert payload["by_strike"] == []


def test_missing_spot_is_an_empty_read_not_a_zero_spot():
    row = _contract("call", 105)
    row.pop("spot")
    payload = gamma_resistance_from_chain([row], asof=ASOF, now=ASOF)
    assert payload["spot"] is None
    assert payload["measurable"] is False
    assert payload["reason"] == "spot_missing"
    assert payload["absolute_gamma_m"] is None


def test_stale_chain_keeps_the_numbers_and_names_the_age():
    payload = _reads([_contract("call", 105), _contract("put", 95)], now=ASOF + timedelta(days=3))
    assert payload["stale"] is True
    assert payload["stale_reason"] == "chain_older_than_20h"
    assert payload["measurable"] is True
    assert payload["absolute_gamma_m"] > 0

    fresh = _reads([_contract("call", 105)], now=ASOF + timedelta(hours=1))
    assert fresh["stale"] is False
    assert fresh["stale_reason"] is None


def test_undated_chain_is_stale_and_still_not_a_zero():
    row = _contract("call", 105)
    row.pop("captured_utc")
    payload = gamma_resistance_from_chain([row], spot=100, now=ASOF, rate=RATE)
    # dte is on the row, so the contract is measurable, but the clock is missing.
    assert payload["stale"] is True
    assert payload["stale_reason"] == "asof_missing"
    assert payload["asof"] is None
    assert payload["absolute_gamma_m"] > 0


def test_parse_dte_param_rejects_garbage_and_keeps_the_default():
    assert parse_dte_param(None, default=365, lo=0, hi=3650) == (365, None)
    assert parse_dte_param("  ", default=30, lo=0, hi=3650) == (30, None)
    assert parse_dte_param("7", default=365, lo=0, hi=3650) == (7, None)
    value, err = parse_dte_param("nope", default=365, lo=0, hi=3650)
    assert value is None and err == "must be an integer"
    value, err = parse_dte_param("-1", default=365, lo=0, hi=3650)
    assert value is None and "between" in (err or "")


def test_compute_gamma_resistance_none_without_a_chain(monkeypatch):
    monkeypatch.setattr(
        "edge.daily_plays.gamma_resistance._load_cached_chain",
        lambda _symbol: ([], None),
    )
    assert compute_gamma_resistance("SPY", now=ASOF) is None


def test_compute_gamma_resistance_stamps_the_symbol(monkeypatch):
    def _load(_symbol: str):
        return ([_contract("call", 105, oi=800), _contract("put", 95, oi=800)], "2026-11-14")

    monkeypatch.setattr("edge.daily_plays.gamma_resistance._load_cached_chain", _load)
    payload = compute_gamma_resistance("spy", now=ASOF)
    assert payload is not None
    assert payload["symbol"] == "SPY"
    assert payload["measurable"] is True
    assert payload["call_resistance"]["level"] == 105
    assert payload["absolute_gamma_m"] > 0
