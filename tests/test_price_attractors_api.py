"""Integration and Unit Tests for Price Attractors API Endpoint and State Layer.

Tests:
1. GET /api/price-attractors response contract, schema validation, and zero-spoofing guarantees.
2. Missing / invalid symbol parameters returning HTTP 400.
3. Unmeasurable option chains returning measurable: false with explicit nulls / unmeasured states.
4. Single-flight mutex locking and TTL caching with cache telemetry (hit, age_seconds, ttl_seconds).
5. Options endpoint enrichment (GET /api/options) embedding price_attractor_snapshot.
6. Quotes endpoint enrichment (GET /api/quotes) embedding regime_badge, primary_magnet_target, and magnet_distance_pct.
7. Concurrency, thread-safety, and cache invalidation on OI backfill.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from edge.daily_plays.regime_attractor_engine import (
    MarketRegimeState,
    PriceMagnetLevel,
    RegimeAttractorSnapshot,
    compute_price_attractors,
)
from edge.tools import api_server


# ---------------------------------------------------------------------------
# In-Memory Socket Test Harness for Full HTTP Request Dispatch
# ---------------------------------------------------------------------------


class _FakeSocket:
    """In-memory socket stream for BaseHTTPRequestHandler dispatch."""

    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode="r", buffering=None):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class _FakeServer:
    server_name = "127.0.0.1"
    server_port = 8787


class _Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _http_request(
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> _Response:
    extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    raw = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{extra}"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode("utf-8") + body
    sock = _FakeSocket(raw)
    server = _FakeServer()
    api_server.ApiRequestHandler(sock, ("127.0.0.1", 12345), server)  # type: ignore[arg-type]
    sock.wfile.seek(0)
    raw_response = sock.wfile.read()
    header_part, _, body_part = raw_response.partition(b"\r\n\r\n")
    lines = header_part.decode("utf-8", errors="replace").split("\r\n")
    status = int(lines[0].split(" ")[1])
    resp_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip()] = v.strip()
    return _Response(status, resp_headers, body_part)


@pytest.fixture(autouse=True)
def _reset_price_attractor_cache():
    """Clear memory caches between tests to ensure test isolation."""
    with api_server._PRICE_ATTRACTOR_LOCK:
        api_server._PRICE_ATTRACTOR_CACHE.clear()
        api_server._PRICE_ATTRACTOR_BUILD_LOCKS.clear()
    with api_server._OPTIONS_LOCK:
        api_server._OPTIONS_CACHE.clear()
        api_server._OPTIONS_BUILD_LOCKS.clear()


def _mock_chain_rows(spot: float = 100.0) -> list[dict[str, Any]]:
    """Generates synthetic options chain rows for deterministic testing."""
    rows = []
    for k in [90.0, 95.0, 100.0, 105.0, 110.0]:
        rows.append(
            {
                "strike": k,
                "right": "call",
                "open_interest": 10000.0 if k == 105.0 else 2000.0,
                "iv": 0.25,
                "dte": 30.0,
                "volume": 500.0,
                "multiplier": 100.0,
                "spot": spot,
            }
        )
        rows.append(
            {
                "strike": k,
                "right": "put",
                "open_interest": 12000.0 if k == 95.0 else 1500.0,
                "iv": 0.25,
                "dte": 30.0,
                "volume": 300.0,
                "multiplier": 100.0,
                "spot": spot,
            }
        )
    return rows


# ===========================================================================
# Test Suite 1: GET /api/price-attractors Endpoint & Contracts
# ===========================================================================


class TestPriceAttractorsApiEndpoint:
    """Core endpoint tests for GET /api/price-attractors."""

    def test_price_attractors_endpoint_success_contract(self, monkeypatch):
        """Valid symbol returns HTTP 200 with complete PriceDrawTelemetryPayload matching PROJECT.md."""
        spot = 100.0
        chain = _mock_chain_rows(spot)

        # Mock _options_payload to return predictable options intelligence
        def fake_options_payload(sym, query):
            return {
                "symbol": sym.upper(),
                "summary": {"spot": spot, "call_wall": 105.0, "put_wall": 95.0},
                "chain_by_strike": chain,
                "price_series": [{"c": 98.0}, {"c": 99.0}, {"c": 100.0}],
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        payload, status = api_server._price_attractors_payload("AAPL")
        assert status == 200
        assert payload["symbol"] == "AAPL"
        assert payload["spot"] == spot
        assert "asof_utc" in payload
        assert "regime_state" in payload
        assert "regime_label" in payload
        assert "regime_strength" in payload
        assert "dominant_direction" in payload
        assert "primary_magnet" in payload
        assert "levels" in payload
        assert "confluence_clusters" in payload
        assert "quality" in payload
        assert "warnings" in payload
        assert "cache" in payload

        # Check telemetry quality
        assert payload["quality"]["measurable"] is True
        assert payload["quality"]["open_interest_available"] is True
        assert isinstance(payload["levels"], list)
        assert len(payload["levels"]) >= 2

        # Check cache metadata
        assert payload["cache"]["hit"] is False
        assert payload["cache"]["age_seconds"] == 0.0
        assert payload["cache"]["ttl_seconds"] == api_server._PRICE_ATTRACTOR_CACHE_TTL_S

    def test_price_attractors_missing_symbol_returns_400(self):
        """Missing symbol parameter returns HTTP 400 error."""
        resp = _http_request("GET", "/api/price-attractors")
        assert resp.status == 400
        body = resp.json()
        assert "error" in body
        assert body["endpoint"] == "/api/price-attractors"

    def test_price_attractors_invalid_symbol_returns_400(self):
        """Malformed or path-traversal symbol returns HTTP 400."""
        resp = _http_request("GET", "/api/price-attractors?symbol=INVALID$$$")
        assert resp.status == 400
        body = resp.json()
        assert "error" in body

        resp_traversal = _http_request("GET", "/api/price-attractors?symbol=../../etc/passwd")
        assert resp_traversal.status == 400

    def test_price_attractors_unmeasurable_chain_zero_spoofing(self, monkeypatch):
        """When option chain is unavailable, returns measurable: false without fake zeroes."""
        def fake_options_payload(sym, query):
            return {"error": f"No options chain for {sym}"}, 404

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)
        monkeypatch.setattr(api_server, "_symbol_quote", lambda sym: {"last": None, "quality": "stale"})
        monkeypatch.setattr(api_server, "_load_symbol_df", lambda sym: (None, None))

        payload, status = api_server._price_attractors_payload("UNKNOWN")
        assert status == 200
        assert payload["symbol"] == "UNKNOWN"
        assert payload["spot"] is None
        assert payload["regime_state"] == "unmeasurable"
        assert payload["regime_strength"] is None
        assert payload["dominant_direction"] == "unmeasured"
        assert payload["primary_magnet"] is None
        assert payload["levels"] == []
        assert payload["confluence_clusters"] == []
        assert payload["quality"]["measurable"] is False
        assert payload["quality"]["open_interest_available"] is False
        assert len(payload["warnings"]) > 0

    def test_price_attractors_ttl_cache_hit_and_telemetry(self, monkeypatch):
        """Sequential requests return cache hit with updated age_seconds."""
        spot = 100.0
        chain = _mock_chain_rows(spot)
        call_count = 0

        def fake_options_payload(sym, query):
            nonlocal call_count
            call_count += 1
            return {
                "symbol": sym.upper(),
                "summary": {"spot": spot},
                "chain_by_strike": chain,
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        # 1. First call (miss)
        res1, status1 = api_server._price_attractors_payload("MSFT")
        assert status1 == 200
        assert res1["cache"]["hit"] is False
        assert call_count == 1

        # Small sleep
        time.sleep(0.05)

        # 2. Second call (hit)
        res2, status2 = api_server._price_attractors_payload("MSFT")
        assert status2 == 200
        assert res2["cache"]["hit"] is True
        assert res2["cache"]["age_seconds"] >= 0.05
        assert call_count == 1  # Options payload not re-invoked

    def test_price_attractors_force_refresh_bypasses_cache(self, monkeypatch):
        """Request with force=True bypasses cache and forces recalculation."""
        spot = 100.0
        chain = _mock_chain_rows(spot)
        call_count = 0

        def fake_options_payload(sym, query):
            nonlocal call_count
            call_count += 1
            return {
                "symbol": sym.upper(),
                "summary": {"spot": spot},
                "chain_by_strike": chain,
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        # Initial call
        api_server._price_attractors_payload("NVDA")
        assert call_count == 1

        # Forced call
        res_forced, status = api_server._price_attractors_payload("NVDA", force=True)
        assert status == 200
        assert res_forced["cache"]["hit"] is False
        assert call_count == 2

    def test_price_attractors_custom_rate_and_dte_params(self, monkeypatch):
        """Custom rate and max_dte query parameters are parsed and passed to calculation."""
        observed_query = {}

        def fake_options_payload(sym, query):
            nonlocal observed_query
            observed_query = query
            return {
                "symbol": sym.upper(),
                "summary": {"spot": 100.0},
                "chain_by_strike": _mock_chain_rows(100.0),
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        payload, status = api_server._price_attractors_payload(
            "TSLA", {"rate": ["0.055"], "max_dte": ["90"]}
        )
        assert status == 200
        assert observed_query.get("rate") == ["0.055"]
        assert observed_query.get("max_dte") == ["90"]


# ===========================================================================
# Test Suite 2: Options Endpoint Enrichment (GET /api/options)
# ===========================================================================


class TestOptionsEndpointAttractorEnrichment:
    """Tests for price attractor embedding in /api/options."""

    def test_options_payload_contains_price_attractor_snapshot(self, monkeypatch):
        """GET /api/options response embeds full price_attractor_snapshot without extra roundtrips."""
        spot = 150.0
        chain = _mock_chain_rows(spot)

        monkeypatch.setattr(api_server, "_historical_option_rows", lambda sym, asof=None, all_days=False: (chain, "2026-08-29", ["2026-08-29"]))
        monkeypatch.setattr(api_server, "_fetch_live_option_inputs", lambda sym, filters=None: (chain, [], spot, "lse_live", [], "lse_equity_candles"))

        payload, status = api_server._options_payload_impl("AAPL", {"mode": ["live"]})
        assert status == 200
        assert "price_attractor_snapshot" in payload
        snap = payload["price_attractor_snapshot"]
        assert isinstance(snap, dict)
        assert snap["symbol"] == "AAPL"
        assert snap["spot"] == spot
        assert snap["quality"]["measurable"] is True
        assert len(snap["levels"]) >= 2
        assert snap["primary_magnet"] is not None
        with api_server._PRICE_ATTRACTOR_LOCK:
            cached = api_server._PRICE_ATTRACTOR_CACHE.get("AAPL")
        assert cached is not None
        assert cached[1]["levels"] == snap["levels"]
        assert cached[1]["quality"]["measurable"] is True

    def test_options_payload_unmeasurable_fallback_snapshot(self, monkeypatch):
        """When options chain has zero OI, price_attractor_snapshot flags measurable: false."""
        empty_chain = [
            {"strike": 100.0, "right": "call", "open_interest": 0.0, "iv": 0.2, "dte": 10.0, "volume": 0.0, "multiplier": 100.0, "spot": 100.0}
        ]
        monkeypatch.setattr(api_server, "_historical_option_rows", lambda sym, asof=None, all_days=False: (empty_chain, "2026-08-29", ["2026-08-29"]))
        monkeypatch.setattr(api_server, "_fetch_live_option_inputs", lambda sym, filters=None: (empty_chain, [], 100.0, "lse_live", [], "lse_equity_candles"))

        payload, status = api_server._options_payload_impl("EMPTY", {"mode": ["live"]})
        assert status == 200
        assert "price_attractor_snapshot" in payload
        snap = payload["price_attractor_snapshot"]
        assert snap["quality"]["measurable"] is False
        assert snap["regime_state"] == "unmeasurable"
        with api_server._PRICE_ATTRACTOR_LOCK:
            assert "EMPTY" not in api_server._PRICE_ATTRACTOR_CACHE


# ===========================================================================
# Test Suite 3: Quotes Endpoint Enrichment (GET /api/quotes)
# ===========================================================================


class TestQuotesEndpointRegimeBadges:
    """Tests for regime & magnet badges in /api/quotes and /api/status."""

    def test_quotes_payload_contains_regime_and_magnet_badges(self, monkeypatch):
        """Quotes rows include regime_badge, primary_magnet_target, and magnet_distance_pct."""
        spot = 200.0
        chain = _mock_chain_rows(spot)

        monkeypatch.setattr(api_server, "_fetch_lse_equity_spot", lambda sym: (spot, "2026-08-29T16:00:00Z"))
        monkeypatch.setattr(api_server, "_option_chain_dates", lambda sym: ["2026-08-29"])
        monkeypatch.setattr(api_server, "_historical_option_rows", lambda sym, asof=None, all_days=False: (chain, "2026-08-29", ["2026-08-29"]))

        payload = api_server._quotes_payload(["AAPL"])
        assert "rows" in payload
        assert len(payload["rows"]) == 1
        row = payload["rows"][0]

        assert row["symbol"] == "AAPL"
        assert row["last"] == spot
        assert "regime_badge" in row
        assert "primary_magnet_target" in row
        assert "magnet_distance_pct" in row
        assert row["regime_badge"] in {"volatility_dampening", "volatility_amplification", "neutral_transition", "charm_decay_selling", "charm_decay_buying"}
        assert isinstance(row["primary_magnet_target"], (int, float))

    def test_quotes_unmeasured_symbol_returns_none_badges(self, monkeypatch):
        """Symbol without options chain returns explicit None for magnet targets."""
        monkeypatch.setattr(api_server, "_fetch_lse_equity_spot", lambda sym: (50.0, "2026-08-29T16:00:00Z"))
        monkeypatch.setattr(api_server, "_option_chain_dates", lambda sym: [])

        payload = api_server._quotes_payload(["NOCHAIN"])
        assert len(payload["rows"]) == 1
        row = payload["rows"][0]
        assert row["symbol"] == "NOCHAIN"
        assert row["primary_magnet_target"] is None
        assert row["magnet_distance_pct"] is None

    def test_quotes_cached_attractor_badge_lookup(self):
        """Quotes endpoint utilizes pre-cached price attractor data when available."""
        # Pre-seed cache
        cached_data = {
            "symbol": "PRELOAD",
            "spot": 100.0,
            "regime_state": "volatility_dampening",
            "primary_magnet": {"price": 105.0, "distance_pct": 5.0},
        }
        with api_server._PRICE_ATTRACTOR_LOCK:
            api_server._PRICE_ATTRACTOR_CACHE["PRELOAD"] = (time.time(), cached_data)

        with patch.object(api_server, "_fetch_lse_equity_spot", return_value=(100.0, "2026-08-29T16:00:00Z")):
            row = api_server._symbol_quote("PRELOAD")
            assert row["regime_badge"] == "volatility_dampening"
            assert row["primary_magnet_target"] == 105.0
            assert row["magnet_distance_pct"] == 5.0


# ===========================================================================
# Test Suite 4: Concurrency, Locks & Cache Invalidation
# ===========================================================================


class TestConcurrencyAndSingleFlightLocking:
    """Tests for thread safety, single-flight mutex locking, and cache invalidation."""

    def test_concurrent_price_attractor_payload_calls(self, monkeypatch):
        """Multiple concurrent requests for the same symbol coalesce safely without duplicate computations."""
        spot = 100.0
        chain = _mock_chain_rows(spot)
        compute_count = 0
        compute_lock = threading.Lock()

        def fake_options_payload(sym, query):
            nonlocal compute_count
            time.sleep(0.02)  # Simulate small processing delay
            with compute_lock:
                compute_count += 1
            return {
                "symbol": sym.upper(),
                "summary": {"spot": spot},
                "chain_by_strike": chain,
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        # Launch 8 simultaneous threads requesting the same symbol
        def worker():
            res, status = api_server._price_attractors_payload("CONCUR")
            assert status == 200
            assert res["symbol"] == "CONCUR"
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker) for _ in range(8)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 8
        # Single-flight locking guarantees compute runs only once
        assert compute_count == 1

    def test_cache_eviction_on_oi_backfill(self, monkeypatch):
        """Triggering OI backfill evicts _PRICE_ATTRACTOR_CACHE entry for symbol."""
        # Seed cache
        with api_server._PRICE_ATTRACTOR_LOCK:
            api_server._PRICE_ATTRACTOR_CACHE["SPY"] = (time.time(), {"symbol": "SPY", "spot": 500.0})

        # Mock capture and parquet write
        import pandas as pd
        dummy_df = pd.DataFrame({"openInterest": [10, 20]})
        monkeypatch.setattr(api_server, "_capture_option_oi", lambda sym, asof=None, max_dte=60: dummy_df)
        monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, p: None)

        res, status = api_server._backfill_oi_payload("SPY", max_dte=60)
        assert status == 200

        # Verify eviction
        with api_server._PRICE_ATTRACTOR_LOCK:
            assert "SPY" not in api_server._PRICE_ATTRACTOR_CACHE


# ===========================================================================
# Test Suite 5: Full HTTP Dispatch & Routing
# ===========================================================================


class TestHttpIntegrationAndRouting:
    """Tests for full HTTP request dispatch through ApiRequestHandler."""

    def test_http_dispatch_price_attractors_route(self, monkeypatch):
        """GET /api/price-attractors?symbol=QQQ returns HTTP 200 JSON through HTTP server."""
        spot = 450.0
        chain = _mock_chain_rows(spot)

        def fake_options_payload(sym, query):
            return {
                "symbol": sym.upper(),
                "summary": {"spot": spot},
                "chain_by_strike": chain,
                "quality": {"gex_measurable": True},
            }, 200

        monkeypatch.setattr(api_server, "_options_payload", fake_options_payload)

        resp = _http_request("GET", "/api/price-attractors?symbol=QQQ")
        assert resp.status == 200
        body = resp.json()
        assert body["symbol"] == "QQQ"
        assert body["spot"] == spot
        assert "regime_state" in body
        assert "primary_magnet" in body

    def test_http_dispatch_quotes_route_with_badges(self, monkeypatch):
        """GET /api/quotes?symbols=AAPL,MSFT preserves regime & magnet badges in HTTP response."""
        spot = 150.0
        chain = _mock_chain_rows(spot)

        monkeypatch.setattr(api_server, "_fetch_lse_equity_spot", lambda sym: (spot, "2026-08-29T16:00:00Z"))
        monkeypatch.setattr(api_server, "_option_chain_dates", lambda sym: ["2026-08-29"])
        monkeypatch.setattr(api_server, "_historical_option_rows", lambda sym, asof=None, all_days=False: (chain, "2026-08-29", ["2026-08-29"]))

        resp = _http_request("GET", "/api/quotes?symbols=AAPL,MSFT")
        assert resp.status == 200
        body = resp.json()
        assert "rows" in body
        assert len(body["rows"]) == 2
        for r in body["rows"]:
            assert "regime_badge" in r
            assert "primary_magnet_target" in r
            assert "magnet_distance_pct" in r
