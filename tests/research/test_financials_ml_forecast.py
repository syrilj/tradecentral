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
