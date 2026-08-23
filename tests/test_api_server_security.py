"""Tests for two hardening fixes in `tools/api_server.py`:

FIX 2 -- state-changing endpoints (`/api/trigger_scan`, `/api/plays/run`,
`/api/options/backfill_oi`) start background jobs and must never be
GET-triggerable: a plain GET can be forced from any page open in the
operator's browser (e.g. an <img src>), which is a local-CSRF vector given
`EDGE_REQUIRE_AUTH` defaults to False. They must now reject non-POST with
405 and an `Allow: POST` header.

FIX 3 -- the generic 500 catch-all (`ApiRequestHandler._error`) must never
echo `str(exception)` to the client, since `FileNotFoundError`/`OSError`
messages routinely embed absolute filesystem paths. The client should only
see a generic message, the exception TYPE name, and a correlation id that
also appears in the server log line.

Both fixes are exercised through the real `ApiRequestHandler` via an
in-memory socket, mirroring the harness in `tests/e2e/conftest.py`, so the
tests cover the actual routing path (`do_GET`/`do_POST` -> `_route` ->
`_dispatch_api`) rather than calling private helpers directly.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import types

import pytest

from edge.tools import api_server


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

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _request(
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
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    return _Response(status, headers, body_part)


def _no_auth(monkeypatch):
    monkeypatch.setenv("EDGE_REQUIRE_AUTH", "0")
    monkeypatch.delenv("CLERK_JWT_KEY", raising=False)
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)


# ---------------------------------------------------------------------------
# FIX 2: GET must be rejected on mutating (job-starting) endpoints.
# ---------------------------------------------------------------------------


def test_mutating_paths_constant_matches_the_three_job_starting_endpoints():
    # Greppable, explicit source of truth -- pin its contents so a future
    # edit can't silently drop or add an endpoint without a test failing.
    assert api_server._MUTATING_API_PATHS == frozenset(
        {
            "/api/trigger_scan",
            "/api/plays/run",
            "/api/options/backfill_oi",
        }
    )


def test_trigger_scan_rejects_get_with_405_and_allow_header(monkeypatch):
    _no_auth(monkeypatch)
    resp = _request("GET", "/api/trigger_scan?depth=quick")
    assert resp.status == 405
    assert resp.headers["Allow"] == "POST"
    assert resp.json()["endpoint"] == "/api/trigger_scan"


def test_plays_run_rejects_get_with_405_and_allow_header(monkeypatch):
    _no_auth(monkeypatch)
    resp = _request("GET", "/api/plays/run")
    assert resp.status == 405
    assert resp.headers["Allow"] == "POST"


def test_backfill_oi_rejects_get_with_405_even_with_valid_params(monkeypatch):
    _no_auth(monkeypatch)
    # The method check must happen before any handler logic runs, so a
    # request with an otherwise-valid symbol is still rejected.
    resp = _request("GET", "/api/options/backfill_oi?symbol=AAPL")
    assert resp.status == 405
    assert resp.headers["Allow"] == "POST"


def test_trigger_scan_accepts_post(monkeypatch):
    _no_auth(monkeypatch)
    monkeypatch.setattr(
        api_server,
        "_start_scan_job",
        lambda depth: ({"id": "job1", "state": "queued", "depth": depth}, True),
    )
    resp = _request("POST", "/api/trigger_scan?depth=quick")
    assert resp.status == 202
    assert resp.json()["job"]["id"] == "job1"


def test_plays_run_accepts_post(monkeypatch):
    _no_auth(monkeypatch)
    monkeypatch.setattr(
        api_server,
        "_start_plays_job",
        lambda account: ({"id": "job2", "state": "queued"}, True),
    )
    resp = _request("POST", "/api/plays/run")
    assert resp.status == 202
    assert resp.json()["job"]["id"] == "job2"


def test_backfill_oi_accepts_post(monkeypatch):
    _no_auth(monkeypatch)
    monkeypatch.setattr(
        api_server,
        "_backfill_oi_payload",
        lambda symbol, *, max_dte: ({"symbol": symbol, "ok": True}, 200),
    )
    resp = _request("POST", "/api/options/backfill_oi?symbol=AAPL")
    assert resp.status == 200
    assert resp.json()["symbol"] == "AAPL"


def test_non_mutating_get_endpoints_are_unaffected(monkeypatch):
    # The 405 gate must be scoped to the three mutating paths only -- an
    # ordinary read endpoint must keep working over GET.
    _no_auth(monkeypatch)
    resp = _request("GET", "/api/health")
    assert resp.status == 200


# ---------------------------------------------------------------------------
# FIX 3: the generic 500 catch-all must not leak str(exception) or a
# filesystem path.
# ---------------------------------------------------------------------------


def test_dispatch_500_never_echoes_exception_string_or_path(monkeypatch):
    _no_auth(monkeypatch)
    secret_path = "/Users/syriljacob/Desktop/alltrading/edge/data/AAPL/secret.parquet"

    def boom(**kwargs):
        raise FileNotFoundError(f"[Errno 2] No such file or directory: '{secret_path}'")

    monkeypatch.setattr(api_server, "get_dashboard_data", boom)

    resp = _request("GET", "/api/status")
    assert resp.status == 500
    payload = resp.json()

    # No filesystem path, and no verbatim str(exception), anywhere in the
    # raw response body.
    assert secret_path not in resp.text
    assert "No such file or directory" not in resp.text
    assert "Errno" not in resp.text

    # The exception TYPE name is still surfaced (useful, non-leaking).
    assert "FileNotFoundError" in payload["error"]
    assert payload["endpoint"] == "/api/status"

    # A correlation id ties the client-visible error to the server log.
    assert "correlation_id" in payload
    assert len(payload["correlation_id"]) >= 8


def test_dispatch_500_correlation_id_matches_server_log(monkeypatch, capsys):
    _no_auth(monkeypatch)

    def boom(**kwargs):
        raise RuntimeError("internal detail nobody outside should see")

    monkeypatch.setattr(api_server, "get_dashboard_data", boom)

    resp = _request("GET", "/api/status")
    payload = resp.json()

    stderr = capsys.readouterr().err
    assert payload["correlation_id"] in stderr
    # Full detail (including the raw message) belongs on stderr, not in
    # the client response.
    assert "internal detail nobody outside should see" in stderr
    assert "internal detail nobody outside should see" not in resp.text


def test_route_level_500_is_also_sanitized(monkeypatch):
    # Exercises the second generic catch-all, in `_route` (errors raised
    # before `_dispatch_api` even runs -- e.g. during the auth check).
    _no_auth(monkeypatch)

    def boom():
        raise RuntimeError("/etc/shadow leaked via auth check boom")

    # `/api/health` is exempt from the auth check, so use a path that
    # actually reaches `_auth_required()`.
    monkeypatch.setattr(api_server, "_auth_required", boom)

    resp = _request("GET", "/api/status")
    assert resp.status == 500
    assert "/etc/shadow" not in resp.text
    assert "RuntimeError" in resp.json()["error"]
    assert "correlation_id" in resp.json()


def test_static_file_read_error_does_not_leak_filesystem_path(monkeypatch, tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_file = dist_dir / "index.html"
    index_file.write_text("<html></html>")
    monkeypatch.setattr(api_server, "DIST_DIR", dist_dir)

    original_read_bytes = pathlib.Path.read_bytes

    def boom(self):
        if self.name == "index.html":
            raise OSError(f"[Errno 13] Permission denied: '{self}'")
        return original_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", boom)

    resp = _request("GET", "/")
    assert resp.status == 500
    assert str(dist_dir) not in resp.text
    assert str(index_file) not in resp.text
    assert "Permission denied" not in resp.text

    payload = resp.json()
    assert "OSError" in payload["error"]
    # `endpoint` must be the request URL, not the resolved filesystem path
    # that failed to read.
    assert payload["endpoint"] == "/"
    assert "correlation_id" in payload


def test_deliberate_validation_messages_are_not_sanitized(monkeypatch):
    # `_sanitize_symbol` and "unknown endpoint" are intentional, safe,
    # user-facing API contract messages that bypass `_error()` entirely
    # via `_send_json` -- they must be unaffected by the 500 sanitization.
    _no_auth(monkeypatch)

    bad_symbol = _request("GET", "/api/analyze?symbol=")
    assert bad_symbol.status == 400
    assert "symbol" in bad_symbol.json()["error"].lower()

    bad_symbol2 = _request("GET", "/api/analyze?symbol=***")
    assert bad_symbol2.status == 400
    assert "invalid symbol" in bad_symbol2.json()["error"].lower()

    unknown = _request("GET", "/api/definitely-not-a-real-endpoint")
    assert unknown.status == 404
    assert unknown.json()["error"] == "unknown endpoint"


# ---------------------------------------------------------------------------
# FIX 4: mutating endpoints must reject a cross-site POST.
#
# Requiring POST (FIX 2) stops <img src>-style GET-CSRF but not a form POST.
# An auto-submitting cross-site
# `<form method="POST" action="http://127.0.0.1:8787/api/trigger_scan">` is a
# CORS *simple request*: the browser sends it with no preflight. CORS then
# hides the response from the attacker, but the scan has already started --
# the side effect is the attack, reading the reply is not required.
# ---------------------------------------------------------------------------


@pytest.fixture
def _stub_dispatch(monkeypatch):
    """Answer 200 without running a real handler.

    Every path below POSTs to a job-starting endpoint. Without this the
    allowed cases would kick off an actual background scan / OI backfill from
    the test suite; the CSRF gate runs before dispatch, so stubbing it keeps
    the test about the gate alone.
    """

    def _fake_dispatch(self, path, query):  # noqa: ANN001 - handler method
        self._send_json({"ok": True, "endpoint": path})

    monkeypatch.setattr(api_server.ApiRequestHandler, "_dispatch_api", _fake_dispatch)


@pytest.mark.parametrize("path", sorted(api_server._MUTATING_API_PATHS))
def test_mutating_post_from_foreign_origin_is_blocked(path, monkeypatch, _stub_dispatch):
    _no_auth(monkeypatch)
    monkeypatch.delenv("EDGE_CORS_ORIGINS", raising=False)
    resp = _request("POST", path, headers={"Origin": "https://evil.example"})
    assert resp.status == 403
    assert resp.json()["error"] == "cross-site request blocked"


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:5178", "http://localhost:5178", "http://[::1]:5178"],
)
def test_mutating_post_from_loopback_origin_is_allowed(origin, monkeypatch, _stub_dispatch):
    # Workstation mode binds to loopback, so a loopback page is the legitimate
    # caller -- the dev Vite server and the served SPA both look like this.
    _no_auth(monkeypatch)
    monkeypatch.delenv("EDGE_CORS_ORIGINS", raising=False)
    resp = _request("POST", "/api/trigger_scan", headers={"Origin": origin})
    assert resp.status == 200


def test_mutating_post_without_origin_header_is_allowed(monkeypatch, _stub_dispatch):
    # curl, the scheduler and python clients send no Origin. They are not a
    # CSRF vector; this gate is anti-CSRF, not authentication.
    _no_auth(monkeypatch)
    monkeypatch.delenv("EDGE_CORS_ORIGINS", raising=False)
    resp = _request("POST", "/api/trigger_scan")
    assert resp.status == 200


def test_explicit_cors_allowlist_is_honoured_for_writes(monkeypatch, _stub_dispatch):
    # Off-loopback deployments must set an explicit allowlist; the write gate
    # must follow that allowlist rather than the loopback rule.
    _no_auth(monkeypatch)
    monkeypatch.setenv("EDGE_CORS_ORIGINS", "https://desk.example")
    allowed = _request("POST", "/api/trigger_scan", headers={"Origin": "https://desk.example"})
    assert allowed.status == 200
    denied = _request("POST", "/api/trigger_scan", headers={"Origin": "http://127.0.0.1:5178"})
    assert denied.status == 403


def test_get_is_still_rejected_before_the_origin_check(monkeypatch, _stub_dispatch):
    # Order matters: a cross-site GET should read as 405 (wrong method), not
    # 403, so the two failures stay diagnosable.
    _no_auth(monkeypatch)
    resp = _request("GET", "/api/trigger_scan", headers={"Origin": "https://evil.example"})
    assert resp.status == 405


# ---------------------------------------------------------------------------
# FIX 5: EDGE_ALLOWED_EMAILS must be enforced by the server.
#
# It was previously read only by the SPA (dashboard/src/auth.ts), and
# vite.config.ts bakes the list into the public bundle. That gated the Vue
# router and nothing else: any holder of a valid session token for the same
# Clerk application could call /api/* directly with a bearer header and skip
# it entirely.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    ["email", "email_address", "primary_email_address", "primary_email"],
)
def test_session_email_reads_every_known_claim_spelling(claim):
    assert api_server._session_email({claim: "Operator@Example.com"}) == "operator@example.com"


def test_session_email_is_empty_when_no_claim_carries_an_address():
    assert api_server._session_email({"sub": "user_1"}) == ""
    assert api_server._session_email({"email": "   "}) == ""
    assert api_server._session_email({"email": None}) == ""


def _fake_clerk(monkeypatch, payload: dict, *, signed_in: bool = True):
    """Install a stand-in clerk_backend_api so auth logic can be exercised."""
    module = types.ModuleType("clerk_backend_api")

    class _State:
        is_signed_in = signed_in
        reason = None

        def __init__(self, payload):
            self.payload = payload

    module.AuthenticateRequestOptions = lambda **kw: kw
    module.authenticate_request = lambda request, options: _State(payload)
    monkeypatch.setitem(sys.modules, "clerk_backend_api", module)
    monkeypatch.setenv("CLERK_JWT_KEY", "test-key")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "http://127.0.0.1:5178")


def test_allowed_email_passes(monkeypatch):
    _fake_clerk(monkeypatch, {"sub": "user_1", "email": "alice@co.com"})
    monkeypatch.setenv("EDGE_ALLOWED_EMAILS", "alice@co.com,bob@co.com")
    ok, user_id, reason = api_server._verify_clerk_request(object())
    assert (ok, user_id, reason) == (True, "user_1", None)


def test_email_outside_the_allowlist_is_rejected(monkeypatch):
    # The exact bypass this fix closes: a valid session for the same Clerk app
    # belonging to someone who is not on the operator list.
    _fake_clerk(monkeypatch, {"sub": "user_2", "email": "mallory@elsewhere.com"})
    monkeypatch.setenv("EDGE_ALLOWED_EMAILS", "alice@co.com")
    ok, _user_id, reason = api_server._verify_clerk_request(object())
    assert ok is False
    assert reason == "Operator is not authorized for this service"


def test_allowlist_comparison_is_case_insensitive(monkeypatch):
    _fake_clerk(monkeypatch, {"sub": "user_1", "email": "Alice@CO.com"})
    monkeypatch.setenv("EDGE_ALLOWED_EMAILS", "alice@co.com")
    ok, _user_id, _reason = api_server._verify_clerk_request(object())
    assert ok is True


def test_allowlist_set_but_token_has_no_email_claim_fails_closed(monkeypatch):
    # Clerk session tokens carry no email unless one is added to the JWT
    # template. Allowing here would silently recreate the very false sense of
    # security this check exists to remove, so it must fail closed and say why.
    _fake_clerk(monkeypatch, {"sub": "user_1"})
    monkeypatch.setenv("EDGE_ALLOWED_EMAILS", "alice@co.com")
    ok, _user_id, reason = api_server._verify_clerk_request(object())
    assert ok is False
    assert "no email claim" in reason


def test_no_allowlist_configured_accepts_any_valid_session(monkeypatch):
    # Preserves the documented default: an empty allowlist is not a deny-all.
    _fake_clerk(monkeypatch, {"sub": "user_9", "email": "anyone@co.com"})
    monkeypatch.delenv("EDGE_ALLOWED_EMAILS", raising=False)
    ok, user_id, reason = api_server._verify_clerk_request(object())
    assert (ok, user_id, reason) == (True, "user_9", None)


# ---------------------------------------------------------------------------
# FIX 6: the request body must be drained, or the CSRF check above is moot.
#
# Nothing in `_dispatch_api` reads a POST body -- every endpoint takes its
# parameters from the query string -- so the bytes were simply left sitting
# in `rfile`. That is not harmless. `protocol_version = "HTTP/1.1"` keeps the
# connection alive, so an unread body is parsed as the *next* request on that
# connection.
#
# That hands a cross-site page exactly what FIX 4 took away. Its form POST
# carries a foreign `Origin` and is refused -- but the body it smuggles is
# re-parsed as a second request, written entirely by the attacker and
# therefore carrying no `Origin` at all, which `_cross_site_write_blocked`
# deliberately allows through as a non-browser client. The job starts anyway.
# ---------------------------------------------------------------------------


def _raw_exchange(raw: bytes) -> list[_Response]:
    """Drive one connection with hand-built bytes; return every response."""
    sock = _FakeSocket(raw)
    api_server.ApiRequestHandler(sock, ("127.0.0.1", 12345), _FakeServer())  # type: ignore[arg-type]
    sock.wfile.seek(0)
    out = sock.wfile.read()
    responses: list[_Response] = []
    for chunk in out.split(b"HTTP/1.1 ")[1:]:
        header_part, _, body_part = chunk.partition(b"\r\n\r\n")
        lines = header_part.decode("utf-8", errors="replace").split("\r\n")
        status = int(lines[0].split(" ")[0])
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        responses.append(_Response(status, headers, body_part))
    return responses


def _smuggling_probe(smuggled: bytes, *, cover_path: str = "/api/health") -> bytes:
    """A cross-site simple POST whose body is a second, forged request."""
    return (
        f"POST {cover_path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Origin: https://evil.example\r\n"
        "Content-Type: text/plain\r\n"
        f"Content-Length: {len(smuggled)}\r\n\r\n"
    ).encode("utf-8") + smuggled


def test_undrained_post_body_cannot_smuggle_a_second_request(monkeypatch):
    _no_auth(monkeypatch)
    smuggled = (
        b"POST /api/trigger_scan HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Length: 0\r\n\r\n"
    )
    responses = _raw_exchange(_smuggling_probe(smuggled))
    # One request in, one response out. A second response means the body was
    # re-parsed as a request -- and a 202 means the scan actually started.
    assert [r.status for r in responses] == [200]


def test_body_is_drained_even_on_a_request_that_is_itself_rejected(monkeypatch):
    # The cover request here is refused (foreign Origin on a mutating path),
    # so the drain must happen on the rejection path too, not only on success.
    _no_auth(monkeypatch)
    smuggled = (
        b"POST /api/plays/run HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n"
    )
    responses = _raw_exchange(
        _smuggling_probe(smuggled, cover_path="/api/trigger_scan")
    )
    assert [r.status for r in responses] == [403]


def test_legitimate_pipelined_requests_still_both_answer(monkeypatch):
    # Draining must consume exactly Content-Length bytes -- no more. Two real
    # pipelined GETs must still produce two real responses.
    _no_auth(monkeypatch)
    raw = (
        b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    responses = _raw_exchange(raw)
    assert [r.status for r in responses] == [200, 200]


def test_oversized_body_is_refused_with_413(monkeypatch):
    # An unbounded read is a memory-exhaustion lever on a threaded server.
    _no_auth(monkeypatch)
    cap = api_server._MAX_REQUEST_BODY_BYTES
    raw = (
        "POST /api/health HTTP/1.1\r\nHost: localhost\r\n"
        f"Content-Length: {cap + 1}\r\n\r\n"
    ).encode("utf-8")
    responses = _raw_exchange(raw)
    assert [r.status for r in responses] == [413]


def test_chunked_body_is_refused_rather_than_left_in_the_stream(monkeypatch):
    # BaseHTTPRequestHandler does not de-chunk, so a chunked body would desync
    # the connection exactly like an undrained Content-Length body.
    _no_auth(monkeypatch)
    raw = (
        b"POST /api/health HTTP/1.1\r\nHost: localhost\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"2b\r\nGET /api/trigger_scan HTTP/1.1\r\nHost: x\r\n\r\n0\r\n\r\n"
    )
    responses = _raw_exchange(raw)
    assert [r.status for r in responses] == [411]


def test_malformed_content_length_is_refused_with_400(monkeypatch):
    _no_auth(monkeypatch)
    raw = (
        b"POST /api/health HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Length: not-a-number\r\n\r\n"
    )
    responses = _raw_exchange(raw)
    assert [r.status for r in responses] == [400]
