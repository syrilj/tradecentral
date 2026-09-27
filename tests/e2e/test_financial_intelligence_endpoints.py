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
    assert "income_statement" in data_q
    assert "rows" in data_q["income_statement"]
    assert "balance_sheet" in data_q
    assert "cash_flow" in data_q
    assert "revenue_breakdown" in data_q
    assert "ratios" in data_q

    # Missing provider fundamentals are represented as empty tables and an
    # explicit unavailable state. When data is available, retain the original
    # expectation that the endpoint supplies periods and income statement rows.
    if data_q.get("available") is False:
        assert data_q["periods"] == []
        assert data_q["income_statement"]["rows"] == []
        assert data_q["balance_sheet"]["rows"] == []
        assert data_q["cash_flow"]["rows"] == []
        assert data_q["source"] == "unavailable"
        assert data_q["reason"]
    else:
        assert data_q["periods"]
        assert data_q["income_statement"]["rows"]

    # Check key ratio fields
    ratios = data_q["ratios"]
    if data_q.get("available") is False:
        assert ratios == {}
    else:
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
    assert isinstance(data_a["periods"], list)
    if data_a.get("available") is False:
        assert data_a["periods"] == []
        assert data_a["income_statement"]["rows"] == []
        assert data_a["source"] == "unavailable"
        assert data_a["reason"]
    else:
        assert data_a["periods"]


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
    score = data["smart_score"]["score"]
    assert score is None or 1 <= score <= 10
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
    replay = score_report_forecast(first.json())
    assert replay["predicted_price"] == a1["predicted_price"]
    assert replay["forecast_score"] == a1["forecast_score"]
    assert replay["gearing_up_towards"] == a1["gearing_up_towards"]
    if a1["status"] == "missing":
        assert first.json().get("available") is False
        assert a1["predicted_price"] is None
        assert a1["forecast_score"] is None
        assert not a1["gearing_up_towards"]
        assert b["status"] == "missing"
    else:
        assert a1["status"] == "ok"
        assert a1["predicted_price"] not in (None, 0, "0")
        assert a1["forecast_score"] not in (None, 0, "0")
        assert a1["gearing_up_towards"]
        assert (b["predicted_price"], b["forecast_score"], b["gearing_up_towards"]) != (
            a1["predicted_price"],
            a1["forecast_score"],
            a1["gearing_up_towards"],
        )


def test_insiders_endpoint(api_client):
    """Verify /api/insiders returns real Form 4 rows, or an honest empty result."""
    res = api_client.get("/api/insiders?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert "summary" in data
    assert "transactions" in data
    # Not asserted non-empty: a symbol with no provider rows used to be padded
    # with 16 invented filings attributed to real named executives.
    for tx in data["transactions"]:
        assert "date" in tx
        assert "insider_name" in tx
        assert "transaction_type" in tx
        assert "shares" in tx
    assert "quarterly_net" in data
    # `strategy` is present only if a real backtest produced it. It used to be
    # a fixed invented block, identical for every symbol.
    if "strategy" in data:
        assert data["strategy"].get("cagr") is not None
        assert data["strategy"].get("sharpe") is not None


def test_government_endpoint(api_client):
    """/api/government reports the missing state for every symbol; no feed is wired.

    This case previously required ASTS to come back with non-empty congress,
    contracts and patents. The only source that could satisfy it was the
    fabricated congressional-trade generator's leftover cache, which named real
    members of Congress against invented trades. No disclosure feed is
    configured in this deployment, so the honest answer -- for tracked and
    untracked symbols alike -- is an explicit missing state.
    """
    res = api_client.get("/api/government?symbol=ASTS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ASTS"
    assert isinstance(data["congress"], list)
    assert data["available"] is False
    assert data["source"] == "unavailable"
    assert data["reason"]
    assert data["congress"] == []
    assert "lobbying" in data
    assert "history" in data["lobbying"]
    assert "filings" in data["lobbying"]
    assert data["contracts"] == []
    assert data["patents"] == []

    # 2. Untracked symbol reports unavailable
    res_un = api_client.get("/api/government?symbol=ZZTESTSYM")
    assert res_un.status_code == 200
    data_un = res_un.json()
    assert data_un["symbol"] == "ZZTESTSYM"
    assert data_un["available"] is False
    assert data_un["source"] == "unavailable"
    assert data_un["congress"] == []
    assert data_un["contracts"] == []
    assert data_un["patents"] == []
    assert data_un["reason"]



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
