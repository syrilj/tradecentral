from __future__ import annotations

from edge.tools import api_server


def test_momentum_scan_payload_uses_loaders_and_caches(monkeypatch):
    calls = {"price": 0, "float": 0}

    def fake_price_data():
        calls["price"] += 1
        return {}

    def fake_float_data():
        calls["float"] += 1
        return {}

    monkeypatch.setattr(api_server, "_load_smallcap_price_data", fake_price_data)
    monkeypatch.setattr(api_server, "load_float_data", fake_float_data)
    api_server._MOMENTUM_SCAN_CACHE = None
    api_server._MOMENTUM_SCAN_CACHE_TS = 0.0

    first = api_server._momentum_scan_payload()
    second = api_server._momentum_scan_payload()

    assert calls["price"] == 1
    assert calls["float"] == 1
    assert first is second
    assert first["candidates"] == []


def test_momentum_scan_payload_force_bypasses_cache(monkeypatch):
    calls = {"price": 0}

    def fake_price_data():
        calls["price"] += 1
        return {}

    monkeypatch.setattr(api_server, "_load_smallcap_price_data", fake_price_data)
    monkeypatch.setattr(api_server, "load_float_data", lambda: {})
    api_server._MOMENTUM_SCAN_CACHE = None
    api_server._MOMENTUM_SCAN_CACHE_TS = 0.0

    api_server._momentum_scan_payload()
    api_server._momentum_scan_payload(force=True)

    assert calls["price"] == 2
