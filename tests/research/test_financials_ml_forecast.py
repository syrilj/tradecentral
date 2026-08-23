"""Drive the shipped financials ML forecast — features, score, missing policy."""
from __future__ import annotations

import math

import pytest

try:
    from edge.research.financials_ml_forecast import (
        GEARING_EXPANSION,
        GEARING_REPAIR,
        build_report_features,
        score_report_forecast,
    )
except ImportError:
    from research.financials_ml_forecast import (
        GEARING_EXPANSION,
        GEARING_REPAIR,
        build_report_features,
        score_report_forecast,
    )


def _row(key: str, label: str, values: list[float | None]) -> dict:
    return {"key": key, "label": label, "values": values}


def _growth_report() -> dict:
    """High growth, high R&D/capex, fat margins, low leverage, cash-generative."""
    return {
        "symbol": "GROW",
        "period_type": "quarterly",
        "periods": ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"],
        "income_statement": {
            "rows": [
                _row("total_revenue", "Total Revenue", [200e6, 170e6, 150e6, 130e6, 110e6]),
                _row("gross_profit", "Gross Profit", [120e6, 98e6, 84e6, 70e6, 55e6]),
                _row("research_and_development", "Research & Development", [40e6, 32e6, 28e6, 24e6, 20e6]),
                _row("operating_income", "Operating Income (EBIT)", [50e6, 38e6, 30e6, 22e6, 14e6]),
                _row("net_income", "Net Income", [40e6, 30e6, 22e6, 16e6, 10e6]),
                _row("diluted_eps", "Diluted EPS", [2.0, 1.5, 1.1, 0.8, 0.5]),
                _row("gross_margin_pct", "Gross Margin %", [60.0, 57.6, 56.0, 53.8, 50.0]),
                _row("operating_margin_pct", "Operating Margin %", [25.0, 22.4, 20.0, 16.9, 12.7]),
                _row("net_margin_pct", "Net Margin %", [20.0, 17.6, 14.7, 12.3, 9.1]),
            ]
        },
        "balance_sheet": {
            "rows": [
                _row("cash_equivalents", "Cash & Cash Equivalents", [80e6, 70e6, 60e6]),
                _row("current_assets", "Total Current Assets", [140e6, 120e6, 100e6]),
                _row("current_liabilities", "Total Current Liabilities", [50e6, 48e6, 46e6]),
                _row("total_assets", "Total Assets", [300e6, 270e6, 240e6]),
                _row("long_term_debt", "Long-Term Debt", [20e6, 22e6, 24e6]),
                _row("stockholders_equity", "Total Stockholders' Equity", [220e6, 200e6, 180e6]),
            ]
        },
        "cash_flow": {
            "rows": [
                _row("operating_cash_flow", "Cash from Operating Activities", [55e6, 42e6, 30e6]),
                _row("capital_expenditures", "Capital Expenditures (CapEx)", [-36e6, -28e6, -20e6]),
                _row("free_cash_flow", "Free Cash Flow", [19e6, 14e6, 10e6]),
            ]
        },
        "ratios": {
            "current_price": 40.0,
            "market_cap": 800e6,
            "pe_trailing": 20.0,
            "pb_trailing": 3.6,
        },
        "revenue_breakdown": {"by_segment": [], "by_geography": []},
    }


def _levered_report() -> dict:
    """Shrinking sales, thin/negative FCF, high leverage — opposite shape."""
    return {
        "symbol": "LEVR",
        "period_type": "quarterly",
        "periods": ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"],
        "income_statement": {
            "rows": [
                _row("total_revenue", "Total Revenue", [80e6, 90e6, 100e6, 110e6, 125e6]),
                _row("gross_profit", "Gross Profit", [20e6, 24e6, 30e6, 36e6, 44e6]),
                _row("research_and_development", "Research & Development", [2e6, 2e6, 2.2e6, 2.4e6, 2.5e6]),
                _row("operating_income", "Operating Income (EBIT)", [2e6, 4e6, 7e6, 10e6, 14e6]),
                _row("net_income", "Net Income", [-4e6, -1e6, 2e6, 4e6, 6e6]),
                _row("diluted_eps", "Diluted EPS", [-0.20, -0.05, 0.10, 0.20, 0.30]),
                _row("gross_margin_pct", "Gross Margin %", [25.0, 26.7, 30.0, 32.7, 35.2]),
                _row("operating_margin_pct", "Operating Margin %", [2.5, 4.4, 7.0, 9.1, 11.2]),
                _row("net_margin_pct", "Net Margin %", [-5.0, -1.1, 2.0, 3.6, 4.8]),
            ]
        },
        "balance_sheet": {
            "rows": [
                _row("cash_equivalents", "Cash & Cash Equivalents", [8e6, 10e6, 14e6]),
                _row("current_assets", "Total Current Assets", [30e6, 36e6, 42e6]),
                _row("current_liabilities", "Total Current Liabilities", [40e6, 38e6, 36e6]),
                _row("total_assets", "Total Assets", [180e6, 190e6, 200e6]),
                _row("long_term_debt", "Long-Term Debt", [120e6, 118e6, 115e6]),
                _row("stockholders_equity", "Total Stockholders' Equity", [40e6, 45e6, 50e6]),
            ]
        },
        "cash_flow": {
            "rows": [
                _row("operating_cash_flow", "Cash from Operating Activities", [1e6, 3e6, 6e6]),
                _row("capital_expenditures", "Capital Expenditures (CapEx)", [-4e6, -4e6, -5e6]),
                _row("free_cash_flow", "Free Cash Flow", [-3e6, -1e6, 1e6]),
            ]
        },
        "ratios": {
            "current_price": 40.0,
            "market_cap": 160e6,
            "pe_trailing": 80.0,
            "pb_trailing": 4.0,
        },
        "revenue_breakdown": {"by_segment": [], "by_geography": []},
    }


def _empty_report() -> dict:
    return {
        "symbol": "MISS",
        "period_type": "quarterly",
        "periods": [],
        "income_statement": {"rows": []},
        "balance_sheet": {"rows": []},
        "cash_flow": {"rows": []},
        "ratios": {},
        "revenue_breakdown": {"by_segment": [], "by_geography": []},
    }


def test_feature_builder_keeps_missing_fields_null():
    feats = build_report_features(_empty_report())
    assert feats["revenue"] is None
    assert feats["log_revenue"] is None
    assert feats["current_price"] is None
    assert all(v is None for v in feats.values())


def test_feature_builder_reads_statement_growth_not_street_targets():
    payload = _growth_report()
    payload["forecast"] = {"target_price_median": 999.0, "consensus_rating": "Strong Buy"}
    feats = build_report_features(payload, intel={"consensus_rating": "Strong Buy"})
    assert feats["revenue"] == pytest.approx(200e6)
    assert feats["revenue_growth"] is not None and feats["revenue_growth"] > 0.5
    assert feats["rd_intensity"] == pytest.approx(0.20)
    assert feats["current_price"] == pytest.approx(40.0)
    # Street fields are not features
    assert "consensus_rating" not in feats
    assert "target_price_median" not in feats


def test_scorer_contrasting_payloads_differ():
    grow = score_report_forecast(_growth_report())
    levered = score_report_forecast(_levered_report())

    assert grow["status"] == "ok"
    assert levered["status"] == "ok"
    assert grow["predicted_price"] is not None and math.isfinite(grow["predicted_price"])
    assert levered["predicted_price"] is not None and math.isfinite(levered["predicted_price"])
    assert grow["forecast_score"] is not None and math.isfinite(grow["forecast_score"])
    assert levered["forecast_score"] is not None and math.isfinite(levered["forecast_score"])
    assert grow["gearing_up_towards"]
    assert levered["gearing_up_towards"]
    assert (grow["predicted_price"], grow["forecast_score"], grow["gearing_up_towards"]) != (
        levered["predicted_price"],
        levered["forecast_score"],
        levered["gearing_up_towards"],
    )
    assert grow["predicted_price"] > levered["predicted_price"]
    assert grow["forecast_score"] > levered["forecast_score"]
    assert grow["gearing_up_towards"] == GEARING_EXPANSION
    assert levered["gearing_up_towards"] == GEARING_REPAIR
    assert grow["decision_authorized"] is False


def test_scorer_is_deterministic():
    a = score_report_forecast(_growth_report())
    b = score_report_forecast(_growth_report())
    assert a["predicted_price"] == b["predicted_price"]
    assert a["forecast_score"] == b["forecast_score"]
    assert a["gearing_up_towards"] == b["gearing_up_towards"]


def test_scorer_moves_when_growth_changes():
    base = _growth_report()
    hotter = _growth_report()
    base["income_statement"]["rows"][0]["values"] = [125e6, 120e6, 116e6, 112e6, 108e6]
    base["income_statement"]["rows"][4]["values"] = [14e6, 13.4e6, 12.9e6, 12.5e6, 12.1e6]
    hotter["income_statement"]["rows"][0]["values"] = [220e6, 170e6, 150e6, 130e6, 110e6]
    base_out = score_report_forecast(base)
    hot_out = score_report_forecast(hotter)
    assert hot_out["predicted_price"] != base_out["predicted_price"]
    assert hot_out["implied_log_return"] != base_out["implied_log_return"]
    assert hot_out["forecast_score"] != base_out["forecast_score"]


def test_missing_report_is_not_zero():
    out = score_report_forecast(_empty_report())
    assert out["status"] == "missing"
    assert out["predicted_price"] is None
    assert out["forecast_score"] is None
    assert out["gearing_up_towards"] is None
    assert out["predicted_price"] != 0
    assert out["forecast_score"] != 0
    assert out["forecast_score"] != "0"
    assert out["gearing_up_towards"] != ""
    assert out["gearing_up_towards"] != "0"


def test_none_payload_is_missing():
    out = score_report_forecast(None)
    assert out["status"] == "missing"
    assert out["predicted_price"] is None
    assert out["forecast_score"] is None


def test_live_tape_not_synthetic_support_print():
    """ASTS-shaped case: live ~71, expansion tape. Must not print $55 support."""
    payload = _growth_report()
    payload["source"] = "deterministic_synthetic_financials"
    payload["ratios"]["current_price"] = 35.0
    out = score_report_forecast(
        payload,
        intel={
            "last_price": 70.98,
            "current_price": 70.98,
            "ret_3m": 0.48,
            "range_position": 0.84,
        },
    )
    assert out["status"] == "ok"
    assert out["spot_used"] == pytest.approx(70.98)
    assert out["spot_source"] == "live"
    assert out["predicted_price"] is not None
    assert out["predicted_price"] > 100
    assert out["predicted_price"] > out["spot_used"]
    assert out["gearing_up_towards"] == GEARING_EXPANSION
    # The discarded $35 mark must not leak into the published price.
    assert out["predicted_price"] != pytest.approx(35.0 * math.exp(out["implied_log_return"]))


def test_future_earnings_growth_lifts_price_vs_slow_name():
    """Faster future earnings / growth must not be haircut to the same low mark."""
    slow = _growth_report()
    fast = _growth_report()
    slow["income_statement"]["rows"][0]["values"] = [120e6, 118e6, 116e6, 114e6, 112e6]
    slow["income_statement"]["rows"][4]["values"] = [12e6, 11.6e6, 11.3e6, 11.1e6, 10.9e6]
    slow["ratios"]["earnings_growth_yoy"] = 6.0
    fast["ratios"]["earnings_growth_yoy"] = 62.0
    intel = {"last_price": 80.0, "current_price": 80.0}
    a = score_report_forecast(slow, intel)
    b = score_report_forecast(fast, intel)
    assert a["predicted_price"] is not None and b["predicted_price"] is not None
    assert b["predicted_price"] > a["predicted_price"]
    assert b["predicted_price"] / 80.0 > 1.55
    assert (b.get("lookthrough_growth") or 0) > (a.get("lookthrough_growth") or 0)


def test_timeframe_factors_and_bull_bear_cases():
    out = score_report_forecast(
        _growth_report(),
        intel={"last_price": 70.98, "current_price": 70.98, "ret_3m": 0.29},
    )
    assert out["timeframe"]
    assert "month" in out["timeframe"]
    assert out["timeframe_months"] in (10, 12, 16, 18, 20, 22, 24)
    assert isinstance(out["factors"], list) and len(out["factors"]) >= 3
    assert all(f.get("display") not in (None, "", "0") for f in out["factors"])
    cases = out["cases"]
    bear, base, bull = cases["bear"]["price"], cases["base"]["price"], cases["bull"]["price"]
    assert bear is not None and base is not None and bull is not None
    assert bear < base < bull
    assert bear < out["spot_used"]
    assert cases["bear"]["thesis"]
    assert cases["bull"]["thesis"]
    assert cases["base"]["price"] == out["predicted_price"]


def test_bear_case_prints_below_live_mark_on_expansion_tape():
    """A growth name at $71 can still miss — bear is not a cheaper bull."""
    out = score_report_forecast(
        _growth_report(),
        intel={"last_price": 70.98, "current_price": 70.98, "ret_3m": 0.48, "range_position": 0.84},
    )
    bear = out["cases"]["bear"]["price"]
    assert out["status"] == "ok"
    assert out["spot_used"] == pytest.approx(70.98)
    assert bear is not None
    assert bear < out["spot_used"]
    assert bear < out["predicted_price"]
    assert out["cases"]["bull"]["price"] > out["predicted_price"]


def test_missing_has_no_fake_case_prices():
    out = score_report_forecast(_empty_report())
    assert out["cases"]["bear"]["price"] is None
    assert out["cases"]["base"]["price"] is None
    assert out["cases"]["bull"]["price"] is None
    assert out["factors"] == []
    assert out["timeframe"] is None


# ==============================================================================
# Financial-soundness regressions. Each test below pins a defect found in the
# 2026-08 audit of the Market-tab forecast; see the docstrings for the failure.
# ==============================================================================


def _annual_report() -> dict:
    """Same figures as the growth report, but the periods span four YEARS."""
    rep = _growth_report()
    rep["symbol"] = "ANNL"
    rep["period_type"] = "annual"
    rep["periods"] = [
        "2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31",
    ]
    return rep


def test_annual_periods_are_annualised_not_read_as_one_year():
    """A 4-year span must not be published as if it were one year of growth.

    Before the fix, `_growth` returned (newest-oldest)/oldest regardless of
    period type, so a company that grew 82% over four years was capitalised as
    an 82%-a-year compounder.
    """
    from research.financials_ml_forecast import _growth, _periods_per_year

    assert _periods_per_year(_annual_report()) == 1
    assert _periods_per_year(_growth_report()) == 4

    quarterly = score_report_forecast(_growth_report())
    annual = score_report_forecast(_annual_report())
    # Identical cells, different calendars -> the annual read must be slower.
    assert annual["lookthrough_growth"] < quarterly["lookthrough_growth"]
    assert annual["predicted_price"] < quarterly["predicted_price"]
    # 100 -> 200 over four years is ~19% CAGR, nowhere near the 82% raw span.
    assert 0.10 < _growth([200.0, 170.0, 150.0, 130.0, 100.0], 1) < 0.25


def test_negative_book_equity_is_distress_not_a_pristine_balance_sheet():
    """Negative equity made D/E negative, which the model read as no leverage.

    A buyback-heavy or impaired name printed a *better* score than a healthy
    one because -2.67x standardised as extraordinarily low gearing.
    """
    rep = _growth_report()
    rep["balance_sheet"]["rows"] = [
        _row("current_assets", "Total Current Assets", [140e6, 120e6, 100e6]),
        _row("current_liabilities", "Total Current Liabilities", [50e6, 48e6, 46e6]),
        _row("total_assets", "Total Assets", [300e6, 270e6, 240e6]),
        _row("long_term_debt", "Long-Term Debt", [400e6, 380e6, 360e6]),
        _row("stockholders_equity", "Total Stockholders' Equity", [-150e6, -120e6, -90e6]),
    ]
    feats = build_report_features(rep)
    assert feats["debt_to_equity"] > 1.0, "negative equity must not read as low gearing"
    assert feats["roe"] is None, "return on a negative book is not a real ROE"

    impaired = score_report_forecast(rep)
    healthy = score_report_forecast(_growth_report())
    assert impaired["forecast_score"] < healthy["forecast_score"]
    assert impaired["predicted_price"] < healthy["predicted_price"]


def test_vendor_percentage_debt_to_equity_is_normalised():
    """yfinance reports debtToEquity as a percent: 150.0 means 1.5x.

    Passed through raw it standardised to z>600 against the fitted panel and
    pinned the Ridge leg to its floor for every vendor-covered symbol.
    """
    from research.financials_ml_forecast import _normalise_debt_to_equity

    assert _normalise_debt_to_equity(150.0) == pytest.approx(1.5)
    assert _normalise_debt_to_equity(1.5) == pytest.approx(1.5)
    assert _normalise_debt_to_equity(-3.0) > 1.0  # negative book -> distress

    rep = _growth_report()
    rep["balance_sheet"]["rows"] = [
        r for r in rep["balance_sheet"]["rows"]
        if r["key"] not in {"long_term_debt", "stockholders_equity"}
    ]
    rep["ratios"]["debt_to_equity"] = 150.0
    feats = build_report_features(rep)
    assert feats["debt_to_equity"] == pytest.approx(1.5)


def test_expensive_names_are_not_rewarded_for_being_expensive():
    """The fitted panel must carry a value tilt, not 'expensive == good'.

    The original synthetic panel drove P/E, P/B and the return label off the
    same latent, so the Ridge learned a POSITIVE loading on both multiples.
    """
    from research.financials_ml_forecast import FEATURE_NAMES, get_fitted_models

    ridge = get_fitted_models()["return"].named_steps["ridge"]
    coefs = dict(zip(FEATURE_NAMES, ridge.coef_))
    assert coefs["log_pe"] < 0, "paying a higher multiple must not raise expected return"
    assert coefs["log_pb"] < 0
    assert coefs["revenue_growth"] > 0
    assert coefs["debt_to_equity"] < 0


def test_flat_mature_name_at_a_full_multiple_is_allowed_to_be_negative():
    """The model must be able to say 'overvalued'.

    Hard floors (`log_ret = max(log_ret, log(1.28))` on expansion, and a
    `predicted_price = spot * 1.28` override) made a bearish base case
    structurally impossible.
    """
    rep = _growth_report()
    rep["symbol"] = "MATR"
    rep["income_statement"]["rows"] = [
        _row("total_revenue", "Total Revenue", [100e6, 100e6, 99e6, 100e6, 99e6]),
        _row("gross_profit", "Gross Profit", [40e6, 40e6, 39e6, 40e6, 39e6]),
        _row("operating_income", "Operating Income (EBIT)", [15e6, 15e6, 14e6, 15e6, 14e6]),
        _row("net_income", "Net Income", [11e6, 11e6, 10e6, 11e6, 10e6]),
        _row("diluted_eps", "Diluted EPS", [1.1, 1.1, 1.0, 1.1, 1.0]),
    ]
    out = score_report_forecast(rep)
    assert out["status"] == "ok"
    assert out["predicted_price"] < out["spot_used"], (
        "a flat compounder on a 20x multiple should not be marked up"
    )
    assert out["excess_annualized_return"] < 0


def test_implied_return_is_railed_in_annualised_terms():
    """No filing may produce an unbounded target price."""
    from research.financials_ml_forecast import (
        MAX_ANNUALISED_RETURN,
        MIN_ANNUALISED_RETURN,
    )

    for rep in (_growth_report(), _levered_report(), _annual_report()):
        out = score_report_forecast(rep, intel={"last_price": 70.98, "ret_3m": 0.9})
        ann = out["annualized_return"]
        assert MIN_ANNUALISED_RETURN - 1e-6 <= ann <= MAX_ANNUALISED_RETURN + 1e-6, (
            f"{rep['symbol']} annualised {ann:.3f} outside the published rails"
        )


def test_scenario_band_widens_with_risk_instead_of_fixed_brackets():
    """Bear/bull must carry information, not be clamped to +/-8% of spot."""
    calm = _growth_report()
    calm["income_statement"]["rows"][0]["values"] = [102e6, 101e6, 101e6, 100e6, 100e6]
    calm["income_statement"]["rows"][4]["values"] = [11e6, 11e6, 10.8e6, 10.6e6, 10.5e6]

    intel = {"last_price": 40.0}
    wild_out = score_report_forecast(_growth_report(), intel)
    calm_out = score_report_forecast(calm, intel)

    def width(o):
        return (o["cases"]["bull"]["price"] - o["cases"]["bear"]["price"]) / o["spot_used"]

    assert wild_out["scenario_sigma"] > calm_out["scenario_sigma"]
    assert width(wild_out) > width(calm_out), "a riskier name must get a wider band"
    for o in (wild_out, calm_out):
        assert o["cases"]["bear"]["price"] < o["cases"]["base"]["price"]
        assert o["cases"]["base"]["price"] < o["cases"]["bull"]["price"]


def test_forecast_publishes_hurdle_and_coverage_for_the_desk():
    """The UI needs the hurdle and the input coverage to be auditable."""
    out = score_report_forecast(_growth_report(), intel={"last_price": 40.0})
    assert out["cost_of_equity"] > 0
    assert out["annualized_return"] is not None
    assert out["excess_annualized_return"] == pytest.approx(
        out["annualized_return"] - out["cost_of_equity"], abs=1e-6
    )
    assert out["expected_return"] == pytest.approx(
        math.expm1(out["implied_log_return"]), abs=1e-6
    )
    assert out["feature_count_total"] == 14
    assert 0 < out["observed_feature_count"] <= out["feature_count_total"]
    # Leverage must raise the hurdle.
    assert score_report_forecast(_levered_report())["cost_of_equity"] > out["cost_of_equity"]


def test_missing_report_publishes_no_fake_hurdle_or_return():
    out = score_report_forecast(_empty_report())
    for key in (
        "expected_return", "annualized_return", "cost_of_equity",
        "excess_annualized_return", "scenario_sigma", "sustainable_growth",
    ):
        assert out[key] is None, f"{key} must stay null when the report is missing"
    assert out["feature_count_total"] == 14


def test_live_tape_growth_is_a_fraction_not_a_percentage():
    """yfinance reports revenueGrowth as a fraction: 1.8 means +180%.

    Running the percent heuristic over it crushed a genuine 180% grower to
    1.8% growth — silently, and only for the fastest names on the board.
    """
    from research.financials_ml_forecast import _tape_growth

    assert _tape_growth(1.8) == pytest.approx(1.8)
    assert _tape_growth(0.18) == pytest.approx(0.18)
    assert _tape_growth(None) is None

    hyper = score_report_forecast(_growth_report(), intel={
        "last_price": 40.0, "revenue_growth": 1.8, "earnings_growth": 2.1,
    })
    steady = score_report_forecast(_growth_report(), intel={
        "last_price": 40.0, "revenue_growth": 0.05, "earnings_growth": 0.05,
    })
    assert hyper["lookthrough_growth"] > steady["lookthrough_growth"]
    assert hyper["predicted_price"] > steady["predicted_price"]
