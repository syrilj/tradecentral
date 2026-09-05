"""Integration and Schema Tests for Unified Market Regime API Endpoint."""
from __future__ import annotations

import io
import json
import time
from typing import Any
import pytest

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

    @property
    def status_code(self) -> int:
        return self.status

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


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_market_regime_endpoint_schema_validity():
    """Verify GET /api/market-regime returns valid JSON matching MarketRegimePayload contract."""
    res = _http_request("GET", "/api/market-regime?symbol=SPY&force=1")
    assert res.status_code == 200
    data = res.json()

    # Top-level keys check
    expected_keys = {
        "symbol",
        "asof_utc",
        "spot",
        "primary",
        "primaryLabel",
        "confidence",
        "trend",
        "volatility",
        "structure",
        "flow",
        "transition",
        "agreement",
        "explanation",
        "levels",
        "quality",
        "cache",
    }
    assert expected_keys.issubset(data.keys())

    # Primary regime type check
    valid_primaries = {
        "bull_trend",
        "bear_trend",
        "compression_range",
        "mean_reverting",
        "vol_expansion_breakout",
        "uncertain_transitional",
        "unmeasurable",
    }
    assert data["primary"] in valid_primaries

    # Confidence check
    assert 0.0 <= data["confidence"]["score"] <= 1.0
    assert data["confidence"]["band"] in {"high", "moderate", "low"}
    assert isinstance(data["confidence"]["penaltyFactors"], list)

    # Context pillars check
    assert "state" in data["trend"]
    assert "measured" in data["trend"]
    assert "state" in data["volatility"]
    assert "measured" in data["volatility"]
    assert "state" in data["structure"]
    assert "measured" in data["structure"]
    assert "state" in data["flow"]
    assert "dealerGammaRegime" in data["flow"]

    # Transition risk check
    assert data["transition"]["level"] in {"low", "moderate", "high", "critical"}
    assert 0.0 <= data["transition"]["stabilityScore"] <= 1.0

    # Agreement check
    assert 0.0 <= data["agreement"]["agreementScore"] <= 1.0
    assert isinstance(data["agreement"]["agreeingModels"], list)
    assert isinstance(data["agreement"]["conflictingModels"], list)

    # Explanation check
    assert isinstance(data["explanation"]["headline"], str)
    assert len(data["explanation"]["headline"]) > 0
    assert isinstance(data["explanation"]["summary"], str)
    assert isinstance(data["explanation"]["leadingDrivers"], list)
    assert isinstance(data["explanation"]["riskFactors"], list)
    assert isinstance(data["explanation"]["uncertaintySources"], list)

    # Quality check
    assert isinstance(data["quality"]["measurable"], bool)
    assert isinstance(data["quality"]["missingLenses"], list)


def test_market_regime_caching_and_force_refresh():
    """Verify TTL caching and force=1 query bypass."""
    sym = "QQQ"
    # First request with force=1 ensures cold start
    res1 = _http_request("GET", f"/api/market-regime?symbol={sym}&force=1")
    assert res1.status_code == 200
    assert res1.json()["cache"]["hit"] is False

    # Second immediate request without force should hit cache
    res2 = _http_request("GET", f"/api/market-regime?symbol={sym}")
    assert res2.status_code == 200
    assert res2.json()["cache"]["hit"] is True
    assert res2.json()["cache"]["age_seconds"] >= 0.0

    # Force refresh bypasses cache
    res3 = _http_request("GET", f"/api/market-regime?symbol={sym}&force=1")
    assert res3.status_code == 200
    assert res3.json()["cache"]["hit"] is False


def test_market_regime_invalid_symbol_returns_400():
    """Verify invalid or malicious symbol strings return 400 Bad Request."""
    res = _http_request("GET", "/api/market-regime?symbol=INVALID$$$")
    assert res.status_code == 400
    data = res.json()
    assert "error" in data


def test_market_regime_unmeasurable_on_missing_symbol():
    """Verify unknown or unpriced symbol returns unmeasurable payload cleanly."""
    res = _http_request("GET", "/api/market-regime?symbol=ZZZZZZZZ&force=1")
    assert res.status_code == 200
    data = res.json()
    assert data["primary"] == "unmeasurable"
    assert data["confidence"]["score"] == 0.0
    assert data["quality"]["measurable"] is False
    assert "Withheld" in data["explanation"]["headline"]


