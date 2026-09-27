#!/usr/bin/env python3
"""Direct unit tests for supply chain payload dispatch in api_server."""
from __future__ import annotations

from edge.tools.supply_chain import build_supply_chain_payload, get_available_themes


def test_themes_direct():
    themes = get_available_themes()
    assert len(themes) >= 4


def test_supply_chain_direct():
    payload = build_supply_chain_payload(theme="ai_datacenter", depth=2)
    assert payload["focal_entity"]["symbol"] == "NVDA"
    assert len(payload["nodes"]) >= 4
