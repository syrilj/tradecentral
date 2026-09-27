"""Unit tests for Fintel adapter (no live network)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

try:
    from edge.daily_plays.adapters.fintel import (
        FintelAuthError,
        FintelClient,
        FintelQuotaError,
        QUOTA_MESSAGE,
        _attention_score,
        _build_analysis_summary,
        fetch_market_stream,
        fetch_security_intel,
        status_payload,
    )
except ImportError:
    from daily_plays.adapters.fintel import (
        FintelAuthError,
        FintelClient,
        FintelQuotaError,
        QUOTA_MESSAGE,
        _attention_score,
        _build_analysis_summary,
        fetch_market_stream,
        fetch_security_intel,
        status_payload,
    )


def test_status_never_leaks_key(monkeypatch):
    monkeypatch.setenv("FINTEL_API_KEY", "super-secret-key-xyz")
    payload = status_payload()
    blob = str(payload)
    assert "super-secret-key-xyz" not in blob
    assert payload["configured"] is True
    assert payload["env_var"] == "FINTEL_API_KEY"
    assert payload["auth_header"] == "X-API-KEY"
    assert payload["decision_authorized"] is False


def test_client_requires_key(monkeypatch):
    monkeypatch.delenv("FINTEL_API_KEY", raising=False)
    c = FintelClient(api_key="")
    assert c.configured is False
    with pytest.raises(FintelAuthError):
        c.get("/v1/account")


def test_attention_score_bounds():
    score = _attention_score(
        {
            "short_pct_float": 20,
            "days_to_cover": 8,
            "borrow_fee_pct": 10,
            "unusual_options_prints": 5,
            "insider_buys": 2,
            "insider_sells": 0,
        }
    )
    assert 0 <= score <= 100


def test_analysis_summary_flags_high_short():
    blocks = {
        "short_interest": {
            "short_interest_percent_of_float": 18.5,
            "days_to_cover": 6.2,
        },
        "borrow_rate": {"borrow_fee_rate_percent": 12.0, "shares_available": 50_000},
        "owners": [{"name": "Fund A"}],
        "insiders": [{"transaction_type": "Buy"}, {"transaction_type": "Sell"}],
        "options_flow_unusual": [{"premium": 1}],
        "last_price": {"price": 42.5},
    }
    analysis = _build_analysis_summary("GME", blocks)
    assert analysis["metrics"]["short_pct_float"] == 18.5
    assert analysis["attention_score"] > 0
    assert any("short interest" in n.lower() for n in analysis["notes"])


def test_fetch_security_intel_core_partial():
    client = MagicMock(spec=FintelClient)
    client.configured = True

    def fake_get(path, params=None):
        if path.endswith("/short-interest"):
            return {"data": {"short_interest_percent_of_float": 12.0}}
        if path.endswith("/last-price"):
            return {"data": {"price": 100.0}}
        if path.endswith("/borrow-rate"):
            raise RuntimeError("slice down")
        return {"data": {}}

    client.get.side_effect = fake_get
    out = fetch_security_intel("AAPL", client=client, depth="core")
    assert out["available"] is True
    assert out["symbol"] == "AAPL"
    assert out["depth"] == "core"
    assert out["blocks"]["short_interest"]["short_interest_percent_of_float"] == 12.0
    assert "borrow_rate" in out["errors"]
    assert "owners" not in out["blocks"]  # core does not request owners
    assert out["decision_authorized"] is False
    assert client.get.call_count == 3


def test_fetch_security_intel_stops_on_quota():
    client = MagicMock(spec=FintelClient)
    client.configured = True
    calls: list[str] = []

    def fake_get(path, params=None):
        calls.append(path)
        if path.endswith("/last-price"):
            return {"data": {"price": 1.0}}
        raise FintelQuotaError(QUOTA_MESSAGE)

    client.get.side_effect = fake_get
    out = fetch_security_intel("AAPL", client=client, depth="full")
    assert out.get("quota_exceeded") or out.get("error_kind") == "quota" or out.get("error")
    # Must not keep calling after first quota
    assert len(calls) < 8
    assert any("skipped: monthly quota" in v for v in out.get("errors", {}).values()) or out.get(
        "quota_exceeded"
    )


def test_fetch_market_stream_auth_fail():
    client = MagicMock(spec=FintelClient)
    client.configured = False
    client.get.side_effect = FintelAuthError("missing key")
    out = fetch_market_stream(client=client)
    assert out["available"] is False
    assert "missing key" in out["error"]


def test_fetch_market_stream_quota():
    client = MagicMock(spec=FintelClient)
    client.configured = True
    client.get.side_effect = FintelQuotaError(QUOTA_MESSAGE)
    out = fetch_market_stream(client=client)
    assert out["available"] is False
    assert out.get("quota_exceeded") is True
    assert "weight limit" in out["error"].lower() or "quota" in out["error"].lower()


def test_ssl_context_uses_certifi_when_available():
    try:
        from edge.daily_plays.adapters.fintel import _ssl_context
    except ImportError:
        from daily_plays.adapters.fintel import _ssl_context
    import ssl

    ctx = _ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
