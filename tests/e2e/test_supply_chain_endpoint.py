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
