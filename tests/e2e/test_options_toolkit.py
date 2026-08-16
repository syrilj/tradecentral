"""API contract for the options toolkit: health, unusual-flow, calculator."""
from __future__ import annotations

import math


def test_health_and_unusual_flow_twice(api_client):
    health_a = api_client.get("/api/health")
    health_b = api_client.get("/api/health")
    flow_a = api_client.get("/api/unusual-flow?limit=20&min_premium=25000")
    flow_b = api_client.get("/api/unusual-flow?limit=20&min_premium=25000")
    for response in (health_a, health_b):
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flow_feed_contract"] == "market-wide-v1"
    for response in (flow_a, flow_b):
        assert response.status_code == 200
        body = response.json()
        assert body["source_snapshot"] == "market_flow"
        blob = str(body).lower()
        assert "dark pool" not in blob
        assert "no ats source" not in blob
        tape = body.get("tape") or []
        if tape:
            row = tape[0]
            assert row.get("right") in {"call", "put"}
            assert "heat" in row
            assert "presets" in row or "is_unusual" in row


def test_options_suggest_is_unauthorized_for_a_named_symbol(api_client):
    response = api_client.get("/api/options/suggest?symbol=SPY")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert body.get("decision_authorized") is False


def test_flow_tape_endpoint_is_symbol_scoped(api_client):
    response = api_client.get("/api/flow-tape?symbol=NVDA&from=2026-08-01&to=2026-08-14")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NVDA"
    assert body["from"] == "2026-08-01"
    assert isinstance(body.get("tape"), list)
    assert body["decision_authorized"] is False
    blob = str(body).lower()
    assert "dark pool" not in blob


def test_calculator_long_call_pnl_rises_above_strike(api_client):
    below = api_client.get(
        "/api/options-calculator?strategy=long_call&spot=90&strike=100&dte=0&vol=0.3&debit=500"
    )
    above = api_client.get(
        "/api/options-calculator?strategy=long_call&spot=120&strike=100&dte=0&vol=0.3&debit=500"
    )
    assert below.status_code == 200
    assert above.status_code == 200
    low = below.json()
    high = above.json()
    assert all(math.isfinite(point["pnl"]) for point in low["pnl_at_expiry"])
    assert all(math.isfinite(point["pnl"]) for point in high["pnl_at_expiry"])
    low_at = next(point["pnl"] for point in low["pnl_at_expiry"] if abs(point["spot"] - 90) < 1e-6)
    high_at = next(point["pnl"] for point in high["pnl_at_expiry"] if abs(point["spot"] - 120) < 1e-6)
    assert high_at > low_at


def test_calculator_prices_a_json_book_of_legs(api_client):
    import json
    from urllib.parse import quote

    legs = quote(json.dumps([
        {"right": "call", "strike": 100, "quantity": 1, "premium": 5},
        {"right": "put", "strike": 100, "quantity": 1, "premium": 5},
    ]))
    response = api_client.get(
        f"/api/options-calculator?strategy=custom&spot=100&dte=0&vol=0.3&legs={legs}"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["legs"]) == 2
    assert body["decision_authorized"] is False
    at_spot = next(point["pnl"] for point in body["pnl_at_expiry"] if abs(point["spot"] - 100) < 1e-6)
    assert at_spot == -1000.0
