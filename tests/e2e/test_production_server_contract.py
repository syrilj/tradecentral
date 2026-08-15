from __future__ import annotations

import gzip
from email.message import Message

from edge.tools import api_server


def test_off_loopback_profile_fails_closed(monkeypatch):
    for name in (
        "EDGE_REQUIRE_AUTH",
        "CLERK_JWT_KEY",
        "CLERK_AUTHORIZED_PARTIES",
        "EDGE_CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)

    errors = api_server._runtime_config_errors("0.0.0.0")
    assert any("EDGE_REQUIRE_AUTH" in error for error in errors)
    assert any("EDGE_CORS_ORIGINS" in error for error in errors)

    monkeypatch.setenv("EDGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("CLERK_JWT_KEY", "test-public-key")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://trade.example.com")
    monkeypatch.setenv("EDGE_CORS_ORIGINS", "https://trade.example.com")
    assert api_server._runtime_config_errors("0.0.0.0") == []


def test_health_is_public_but_other_api_routes_require_auth(api_client, monkeypatch):
    monkeypatch.setenv("EDGE_REQUIRE_AUTH", "1")
    monkeypatch.delenv("CLERK_JWT_KEY", raising=False)
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)

    health = api_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["auth_required"] is True

    protected = api_client.get("/api/readiness")
    assert protected.status_code == 401
    assert protected.headers["Cache-Control"] == "no-store"


def test_cors_uses_exact_origin_allowlist(api_client, monkeypatch):
    monkeypatch.setenv("EDGE_CORS_ORIGINS", "https://trade.example.com")

    allowed = api_client.options(
        "/api/health",
        headers={"Origin": "https://trade.example.com"},
    )
    assert allowed.status_code == 204
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://trade.example.com"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"

    denied = api_client.options(
        "/api/health",
        headers={"Origin": "https://attacker.example"},
    )
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_compresses_large_json_compatible_responses():
    handler = object.__new__(api_server.ApiRequestHandler)
    headers = Message()
    headers["Accept-Encoding"] = "gzip, br"
    handler.headers = headers

    original = b'{"payload":"' + (b"x" * 4096) + b'"}'
    encoded, compressed = handler._encode_body(original, "application/json; charset=utf-8")

    assert compressed is True
    assert len(encoded) < len(original)
    assert gzip.decompress(encoded) == original


def test_security_headers_are_present_on_health(api_client, monkeypatch):
    monkeypatch.setenv("EDGE_REQUIRE_AUTH", "0")
    response = api_client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Permissions-Policy"]
    assert response.headers["X-Request-ID"]
