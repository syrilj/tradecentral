"""Tests for new stock financial intelligence, profile, insiders, government, and ownership endpoints."""
from __future__ import annotations

import math

try:
    from edge.research.financials_ml_forecast import score_report_forecast
except ImportError:
    from research.financials_ml_forecast import score_report_forecast


def test_financials_endpoint_quarterly_and_annual(api_client):
    """Verify /api/financials returns valid income statement, balance sheet, cash flow, and ratios."""
    # 1. Quarterly
    res_q = api_client.get("/api/financials?symbol=ASTS&period=quarterly")
    assert res_q.status_code == 200
    data_q = res_q.json()
    assert data_q["symbol"] == "ASTS"
    assert data_q["period_type"] == "quarterly"
    assert isinstance(data_q["periods"], list)
    assert len(data_q["periods"]) > 0
    assert "income_statement" in data_q
    assert "rows" in data_q["income_statement"]
    assert len(data_q["income_statement"]["rows"]) > 0
    assert "balance_sheet" in data_q
    assert "cash_flow" in data_q
    assert "revenue_breakdown" in data_q
    assert "ratios" in data_q

    # Check key ratio fields
    ratios = data_q["ratios"]
    assert "market_cap" in ratios
    assert "debt_to_equity" in ratios

    forecast = data_q.get("model_forecast")
    assert isinstance(forecast, dict)
    assert "predicted_price" in forecast
    assert "forecast_score" in forecast
    assert "gearing_up_towards" in forecast
    assert forecast.get("decision_authorized") is False
    if forecast.get("status") == "ok":
        assert forecast["predicted_price"] is not None
        assert forecast["forecast_score"] is not None
        assert math.isfinite(forecast["predicted_price"])
        assert math.isfinite(forecast["forecast_score"])
        assert forecast["gearing_up_towards"]

    # 2. Annual
    res_a = api_client.get("/api/financials?symbol=ASTS&period=annual")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["period_type"] == "annual"
    assert len(data_a["periods"]) > 0


def test_company_profile_endpoint(api_client):
    """Verify /api/company-profile returns about, officers, compensation, forecast, smart score, and bull/bear."""
    res = api_client.get("/api/company-profile?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert "about" in data
    assert "name" in data["about"]
    assert "description" in data["about"]
    assert "compensation" in data
    assert "rows" in data["compensation"]
    assert "forecast" in data
    assert "target_price_median" in data["forecast"]
    assert "consensus_rating" in data["forecast"]
    assert "smart_score" in data
    assert "score" in data["smart_score"]
    assert 1 <= data["smart_score"]["score"] <= 10
    assert "bull_bear" in data
    assert "bulls_say" in data["bull_bear"]
    assert "bears_say" in data["bull_bear"]
    assert "model_forecast" in data
    assert data["model_forecast"].get("label") == "what it should be"


def test_financials_model_forecast_consistent_and_symbol_specific(api_client):
    """Operator /api/financials forecast is deterministic and matches the shipped scorer."""
    first = api_client.get("/api/financials?symbol=ASTS&period=quarterly")
    second = api_client.get("/api/financials?symbol=ASTS&period=quarterly")
    other = api_client.get("/api/financials?symbol=AAPL&period=quarterly")
    assert first.status_code == 200
    assert second.status_code == 200
    assert other.status_code == 200
    a1 = first.json()["model_forecast"]
    a2 = second.json()["model_forecast"]
    b = other.json()["model_forecast"]
    assert a1["predicted_price"] == a2["predicted_price"]
    assert a1["forecast_score"] == a2["forecast_score"]
    assert a1["gearing_up_towards"] == a2["gearing_up_towards"]
    assert a1["status"] == "ok"
    assert a1["predicted_price"] not in (None, 0, "0")
    assert a1["forecast_score"] not in (None, 0, "0")
    assert a1["gearing_up_towards"]
    replay = score_report_forecast(first.json())
    assert replay["predicted_price"] == a1["predicted_price"]
    assert replay["forecast_score"] == a1["forecast_score"]
    assert replay["gearing_up_towards"] == a1["gearing_up_towards"]
    assert (b["predicted_price"], b["forecast_score"], b["gearing_up_towards"]) != (
        a1["predicted_price"],
        a1["forecast_score"],
        a1["gearing_up_towards"],
    )


def test_insiders_endpoint(api_client):
    """Verify /api/insiders returns transactions, quarterly net volume, summary, and strategy backtest."""
    res = api_client.get("/api/insiders?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert "summary" in data
    assert "transactions" in data
    assert len(data["transactions"]) > 0
    tx = data["transactions"][0]
    assert "date" in tx
    assert "insider_name" in tx
    assert "transaction_type" in tx
    assert "shares" in tx
    assert "quarterly_net" in data
    assert "strategy" in data
    assert "cagr" in data["strategy"]
    assert "sharpe" in data["strategy"]


def test_government_endpoint(api_client):
    """Verify /api/government returns congress trades, lobbying, contracts, and patents."""
    res = api_client.get("/api/government?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert "congress" in data
    assert isinstance(data["congress"], list)
    assert len(data["congress"]) > 0
    cg = data["congress"][0]
    assert "politician_name" in cg
    assert "party" in cg
    assert "type" in cg

    assert "lobbying" in data
    assert "history" in data["lobbying"]
    assert "filings" in data["lobbying"]

    assert "contracts" in data
    assert "patents" in data


def test_ownership_endpoint(api_client):
    """Verify /api/ownership returns breakdown, top institutions, top funds, and short interest."""
    res = api_client.get("/api/ownership?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert "breakdown" in data
    assert "institutional_pct" in data["breakdown"]
    assert "insider_pct" in data["breakdown"]
    assert "retail_float_pct" in data["breakdown"]
    assert "top_institutions" in data
    assert isinstance(data["top_institutions"], list)
    assert "institutions_count" in data
    assert "top_funds" in data
    assert "short_interest" in data
    assert "days_to_cover" in data["short_interest"]
