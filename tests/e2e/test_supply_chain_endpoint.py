#!/usr/bin/env python3
"""E2E / Integration tests for /api/supply-chain and /api/supply-chain/themes endpoints."""
from __future__ import annotations



def test_supply_chain_themes_endpoint(api_client):
    res = api_client.get("/api/supply-chain/themes")
    assert res.status_code == 200
    data = res.json()
    assert "themes" in data
    assert len(data["themes"]) >= 4
    theme_ids = [t["id"] for t in data["themes"]]
    assert "ai_datacenter" in theme_ids
    assert "semi_equipment" in theme_ids
    assert "agentic_software" in theme_ids
    assert "energy_grid" in theme_ids


def test_supply_chain_query_default(api_client):
    res = api_client.get("/api/supply-chain?theme=ai_datacenter&depth=2")
    assert res.status_code == 200
    data = res.json()
    assert data["query"]["theme"] == "ai_datacenter"
    assert data["focal_entity"]["symbol"] == "NVDA"
    assert len(data["nodes"]) >= 5
    assert len(data["edges"]) >= 5

    # Check key beneficiaries
    symbols = {n["symbol"] for n in data["nodes"]}
    assert "AAOI" in symbols
    assert "LITE" in symbols
    assert "MU" in symbols
    assert "VRT" in symbols


def test_supply_chain_query_with_symbol(api_client):
    res = api_client.get("/api/supply-chain?symbol=AAOI&theme=ai_datacenter")
    assert res.status_code == 200
    data = res.json()
    assert data["query"]["symbol"] == "AAOI"
    assert data["focal_entity"]["symbol"] == "AAOI"
    assert data["focal_entity"]["is_focus"] is True


def test_supply_chain_invalid_symbol(api_client):
    res = api_client.get("/api/supply-chain?symbol=INVALID$$$")
    assert res.status_code == 400
    data = res.json()
    assert "error" in data


def test_supply_chain_endpoint_novel_and_arbitrary_symbols(api_client):
    """Verify endpoint handles uncataloged and arbitrary symbols via universal archetype fallback."""
    for sym in ["XYZUNKNOWN", "NONEXISTENT99", "GOOGL", "ARM", "BA", "RKLB"]:
        res = api_client.get(f"/api/supply-chain?symbol={sym}&force=1")
        assert res.status_code == 200, f"Failed for {sym}: {res.text}"
        data = res.json()
        assert data["focal_entity"]["symbol"] == sym
        assert data["focal_entity"]["is_focus"] is True
        assert len(data["nodes"]) >= 4
        assert len(data["edges"]) >= 3


def test_supply_chain_endpoint_whitespace_and_case(api_client):
    """Verify endpoint handles whitespace and casing variations properly."""
    res = api_client.get("/api/supply-chain?symbol=%20%20tsla%20%20")
    assert res.status_code == 200
    assert res.json()["focal_entity"]["symbol"] == "TSLA"

    res2 = api_client.get("/api/supply-chain?symbol=nvda")
    assert res2.status_code == 200
    assert res2.json()["focal_entity"]["symbol"] == "NVDA"


def test_supply_chain_endpoint_malformed_inputs(api_client):
    """Verify endpoint rejects malformed/injection queries with HTTP 400."""
    malicious = [
        "BAD$$$",
        "SELECT%20*%20FROM%20users",
        "../../etc/passwd",
        "%3Cscript%3Ealert(1)%3C/script%3E",
        "A" * 30,
        "AAPL!@#",
    ]
    for bad in malicious:
        res = api_client.get(f"/api/supply-chain?symbol={bad}")
        assert res.status_code == 400, f"Expected 400 for {bad}, got {res.status_code}"
        assert "error" in res.json()


def test_supply_chain_endpoint_depth_and_fallback(api_client):
    """Verify depth query parameter filtering and fallback for invalid values."""
    res_d1 = api_client.get("/api/supply-chain?symbol=NVDA&depth=1&force=1")
    res_d2 = api_client.get("/api/supply-chain?symbol=NVDA&depth=2&force=1")
    assert res_d1.status_code == 200
    assert res_d2.status_code == 200
    d1_len = len(res_d1.json()["nodes"])
    d2_len = len(res_d2.json()["nodes"])
    assert d1_len <= d2_len

    # Invalid depth falls back to default (2) without error
    res_bad = api_client.get("/api/supply-chain?symbol=NVDA&depth=invalid")
    assert res_bad.status_code == 200
    assert res_bad.json()["query"]["depth"] == 2


def test_supply_chain_endpoint_data_honesty(api_client):
    """Verify endpoint never emits fake elasticity scores on unscored nodes."""
    res = api_client.get("/api/supply-chain?symbol=XYZUNKNOWN&force=1")
    assert res.status_code == 200
    data = res.json()
    summary = data["thematic_summary"]
    node_map = {n["symbol"]: n for n in data["nodes"]}

    for b_sym in summary["top_beneficiaries"]:
        assert b_sym in node_map
        score = node_map[b_sym]["metrics"]["elasticity_score"]
        assert score is not None
        assert score > 0.0

    for n in data["nodes"]:
        if not n.get("is_focus"):
            m = n.get("metrics") or {}
            has_inputs = any(
                m.get(k) is not None
                for k in ["capex_sensitivity", "revenue_concentration_pct", "operating_leverage", "flow_sentiment_score"]
            )
            if not has_inputs:
                assert m.get("elasticity_score") is None
                assert n["symbol"] not in summary["top_beneficiaries"]


def test_supply_chain_endpoint_latency_benchmark(api_client):
    """Verify endpoint response time is < 500ms across queries."""
    import time
    symbols = ["NVDA", "ASTS", "XYZUNKNOWN", "ARM", "BA"]
    for sym in symbols:
        t0 = time.perf_counter()
        res = api_client.get(f"/api/supply-chain?symbol={sym}&force=1")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert res.status_code == 200
        assert elapsed_ms < 500.0, f"Query for {sym} took {elapsed_ms:.1f}ms (>500ms limit)"

