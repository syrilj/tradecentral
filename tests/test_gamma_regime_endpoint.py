"""GET /api/gamma/regime — dealer gamma regime across a fixed index + sector
universe, for the breadth strip in dashboard/src/regimeContracts.ts.

This endpoint is the conviction board's close sibling (same live-chain
fetch, same threadpool/TTL-cache/build-lock pattern) but with a FIXED
universe instead of scan candidates, and a much smaller row. The wire shape
is owned by `RegimeSymbolRow`/`RegimeBreadthPayload` in that TS file and is
camelCase by contract, so these tests pin the exact field names rather than
trusting Python convention.

None of these tests touch the live LSE provider: `_fetch_live_option_inputs`
and `build_options_intelligence` are monkeypatched throughout, following the
pattern in tests/test_options_payload_fallback.py.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
import threading
import time

from edge.tools import api_server


# ---------------------------------------------------------------------------
# Shared fakes for the per-symbol chain fetch (`_gamma_regime_row`).
# ---------------------------------------------------------------------------


def _fake_intel(*, spot=100.0, total_gex_m=-12.5, zero_gamma=101.0, gex_measurable=True):
    """A minimal stand-in for `build_options_intelligence`'s return shape,
    carrying only the fields `_gamma_regime_row` actually reads."""
    return {
        "mode_resolved": "live",
        "summary": {
            "spot": spot,
            "total_gex_m": total_gex_m,
            "zero_gamma": zero_gamma,
            "regime": "negative" if (total_gex_m or 0) < 0 else "positive",
            "call_oi": 4000,
            "put_oi": 3500,
        },
        "quality": {"gex_measurable": gex_measurable},
        "provider": {"chain": "lse_live", "open_interest": "lse_live"},
        "warnings": [],
    }


def _patch_live_chain(monkeypatch, *, intel, chain_rows=None, price_spot=100.0):
    """Route `_gamma_regime_row`'s fetch to a live chain with a fake intel."""
    chain_rows = [{"strike": 100.0}] if chain_rows is None else chain_rows
    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], price_spot))
    monkeypatch.setattr(
        api_server,
        "_fetch_live_option_inputs",
        lambda *a, **k: (chain_rows, [], price_spot, "lse_live", [], "lse_live:now"),
    )
    monkeypatch.setattr(api_server, "build_options_intelligence", lambda **kwargs: intel)


def _clear_cache():
    with api_server._GAMMA_REGIME_LOCK:
        api_server._GAMMA_REGIME_CACHE.clear()
        api_server._GAMMA_REGIME_BUILD_LOCKS.clear()


def setup_function(_fn):
    _clear_cache()


def teardown_function(_fn):
    _clear_cache()


# ---------------------------------------------------------------------------
# Universe: fixed, greppable, pinned so a future edit can't silently drop or
# reorder a name without a test failing (same rationale as
# test_mutating_paths_constant_matches... in test_api_server_security.py).
# ---------------------------------------------------------------------------


def test_universe_is_the_pinned_fixed_index_and_sector_list():
    assert api_server._GAMMA_REGIME_UNIVERSE == (
        ("SPY", "index", "S&P 500"),
        ("QQQ", "index", "Nasdaq 100"),
        ("IWM", "index", "Russell 2000"),
        ("DIA", "index", "Dow Jones Industrial Average"),
        ("XLK", "sector", "Technology"),
        ("XLF", "sector", "Financials"),
        ("XLE", "sector", "Energy"),
        ("XLV", "sector", "Health Care"),
        ("XLI", "sector", "Industrials"),
        ("XLY", "sector", "Consumer Discretionary"),
        ("XLP", "sector", "Consumer Staples"),
        ("XLU", "sector", "Utilities"),
        ("XLB", "sector", "Materials"),
        ("XLRE", "sector", "Real Estate"),
        ("XLC", "sector", "Communication Services"),
    )


# ---------------------------------------------------------------------------
# `_gamma_regime_row`: wire shape and regime classification.
# ---------------------------------------------------------------------------


def test_row_wire_shape_matches_the_regime_contract(monkeypatch):
    _patch_live_chain(
        monkeypatch, intel=_fake_intel(spot=100.0, total_gex_m=-12.5, zero_gamma=101.0)
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert set(row) == {
        "symbol", "kind", "label", "spot", "netGammaM", "zeroGamma",
        "regime", "distanceToFlip", "trend", "measurable", "note",
    }
    assert row["symbol"] == "SPY"
    assert row["kind"] == "index"
    assert row["label"] == "S&P 500"
    assert row["spot"] == 100.0
    assert row["netGammaM"] == -12.5
    assert row["zeroGamma"] == 101.0
    assert row["measurable"] is True
    assert row["trend"] is None
    assert row["note"] is None


def test_short_gamma_regime_when_net_gamma_negative_and_away_from_flip(monkeypatch):
    _patch_live_chain(
        monkeypatch, intel=_fake_intel(spot=100.0, total_gex_m=-12.5, zero_gamma=90.0)
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert row["regime"] == "short"
    assert row["distanceToFlip"] == round((100.0 - 90.0) / 100.0, 6)


def test_long_gamma_regime_when_net_gamma_positive_and_away_from_flip(monkeypatch):
    _patch_live_chain(
        monkeypatch, intel=_fake_intel(spot=100.0, total_gex_m=12.5, zero_gamma=90.0)
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert row["regime"] == "long"


def test_flip_band_threshold_transitions_from_flip_to_directional(monkeypatch):
    # Just inside the 0.0025 neutral band -> flip.
    _patch_live_chain(
        monkeypatch,
        intel=_fake_intel(spot=100.0, total_gex_m=-5.0, zero_gamma=100.0 * (1 - 0.002)),
    )
    inside = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)
    assert inside["regime"] == "flip"

    # Just outside it -> classified by net-gamma sign instead.
    _patch_live_chain(
        monkeypatch,
        intel=_fake_intel(spot=100.0, total_gex_m=-5.0, zero_gamma=100.0 * (1 - 0.004)),
    )
    outside = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)
    assert outside["regime"] == "short"


def test_missing_zero_gamma_falls_back_to_net_gamma_sign_with_null_distance(monkeypatch):
    # gex_measurable true, but the profile had no sign crossing to flip on.
    _patch_live_chain(
        monkeypatch, intel=_fake_intel(spot=100.0, total_gex_m=-4.0, zero_gamma=None)
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert row["regime"] == "short"
    assert row["zeroGamma"] is None
    assert row["distanceToFlip"] is None


def test_net_gamma_exactly_zero_without_flip_level_reads_as_flip(monkeypatch):
    _patch_live_chain(
        monkeypatch, intel=_fake_intel(spot=100.0, total_gex_m=0.0, zero_gamma=None)
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert row["regime"] == "flip"
    assert row["measurable"] is True


# ---------------------------------------------------------------------------
# Unmeasurable rows: every numeric field null, never a fake zero.
# ---------------------------------------------------------------------------


def test_unmeasurable_row_nulls_every_numeric_field_never_zero(monkeypatch):
    # A fake-zero read (total_gex_m=0.0, no OI) must never leak through as a
    # confident "quiet" number just because gex_measurable is False.
    _patch_live_chain(
        monkeypatch,
        intel=_fake_intel(spot=100.0, total_gex_m=0.0, zero_gamma=None, gex_measurable=False),
    )

    row = api_server._gamma_regime_row(("XLF", "sector", "Financials"), want_trend=False)

    assert row["measurable"] is False
    assert row["regime"] == "unmeasurable"
    assert row["spot"] is None
    assert row["netGammaM"] is None
    assert row["zeroGamma"] is None
    assert row["distanceToFlip"] is None
    assert isinstance(row["note"], str) and row["note"]


def test_a_raising_symbol_degrades_to_a_noted_row_without_failing_the_request(monkeypatch):
    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], 100.0))

    def boom(*_a, **_k):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(api_server, "_fetch_live_option_inputs", boom)

    row = api_server._gamma_regime_row(("XLE", "sector", "Energy"), want_trend=False)

    assert row["measurable"] is False
    assert row["regime"] == "unmeasurable"
    assert row["netGammaM"] is None
    assert "RuntimeError" in row["note"]
    assert "provider timeout" in row["note"]


def test_missing_live_chain_falls_back_to_dated_history_and_notes_it(monkeypatch):
    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], 100.0))
    monkeypatch.setattr(
        api_server,
        "_fetch_live_option_inputs",
        lambda *a, **k: ([], [], None, "unavailable", [], None),
    )
    monkeypatch.setattr(
        api_server,
        "_historical_option_rows",
        lambda symbol, *, all_days=False: (
            [{"occ_symbol": "XLK260821C00100000", "right": "call", "strike": 100.0}],
            "2026-08-20",
            ["2026-08-20"],
        ),
    )
    monkeypatch.setattr(
        api_server,
        "build_options_intelligence",
        lambda **kwargs: _fake_intel(spot=100.0, total_gex_m=3.0, zero_gamma=95.0),
    )

    row = api_server._gamma_regime_row(("XLK", "sector", "Technology"), want_trend=False)

    assert row["measurable"] is True
    assert row["note"] == "Live chain unavailable; showing the latest dated chain."


def test_no_chain_anywhere_returns_unmeasurable_with_a_no_chain_note(monkeypatch):
    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], 100.0))
    monkeypatch.setattr(
        api_server,
        "_fetch_live_option_inputs",
        lambda *a, **k: ([], [], None, "unavailable", [], None),
    )
    monkeypatch.setattr(
        api_server, "_historical_option_rows", lambda symbol, *, all_days=False: ([], None, [])
    )
    monkeypatch.setattr(
        api_server,
        "_ensure_delayed_chain_snapshot",
        lambda *a, **k: (False, "provider returned no expiries"),
    )

    row = api_server._gamma_regime_row(("IWM", "index", "Russell 2000"), want_trend=False)

    assert row["measurable"] is False
    assert "No options chain is available for IWM" in row["note"]


# ---------------------------------------------------------------------------
# Trend: opt-in, cheap (local bars, no network), never fatal.
# ---------------------------------------------------------------------------


def test_trend_defaults_to_none_when_not_requested(monkeypatch):
    _patch_live_chain(monkeypatch, intel=_fake_intel())
    calls: list[str] = []
    monkeypatch.setattr(
        api_server, "_gamma_regime_trend", lambda symbol: calls.append(symbol) or "up"
    )

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=False)

    assert row["trend"] is None
    assert calls == []  # trend must not even be attempted when not requested


def test_trend_is_populated_when_requested(monkeypatch):
    _patch_live_chain(monkeypatch, intel=_fake_intel())
    monkeypatch.setattr(api_server, "_gamma_regime_trend", lambda symbol: "down")

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=True)

    assert row["trend"] == "down"


def test_trend_is_still_attempted_for_an_unmeasurable_gex_row(monkeypatch):
    # Trend reads price bars, not open interest -- a missing options chain
    # must not blank out a perfectly good price-trend read.
    _patch_live_chain(monkeypatch, intel=_fake_intel(gex_measurable=False))
    monkeypatch.setattr(api_server, "_gamma_regime_trend", lambda symbol: "flat")

    row = api_server._gamma_regime_row(("SPY", "index", "S&P 500"), want_trend=True)

    assert row["measurable"] is False
    assert row["trend"] == "flat"


def test_gamma_regime_trend_reduces_kalman_position_to_up_down_flat(monkeypatch):
    for position, expected in (("long", "up"), ("short", "down"), ("flat", "flat")):
        monkeypatch.setattr(
            api_server,
            "_kalman_trend_payload",
            lambda *a, **k: {"available": True, "now": {"position": position}},
        )
        assert api_server._gamma_regime_trend("SPY") == expected


def test_gamma_regime_trend_is_none_when_the_filter_has_no_data(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "_kalman_trend_payload",
        lambda *a, **k: {"available": False, "reason": "no bars found for 'SPY'"},
    )

    assert api_server._gamma_regime_trend("SPY") is None


def test_gamma_regime_trend_is_none_when_the_filter_raises(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kalman blew up")

    monkeypatch.setattr(api_server, "_kalman_trend_payload", boom)

    assert api_server._gamma_regime_trend("SPY") is None


# ---------------------------------------------------------------------------
# Divergence: SPY's regime vs. sectors running short gamma underneath it.
# ---------------------------------------------------------------------------


def _row(symbol, kind, regime, *, measurable=True):
    return {
        "symbol": symbol,
        "kind": kind,
        "label": symbol,
        "spot": 100.0 if measurable else None,
        "netGammaM": (-1.0 if regime == "short" else 1.0) if measurable else None,
        "zeroGamma": 99.0 if measurable else None,
        "regime": regime,
        "distanceToFlip": 0.01 if measurable else None,
        "trend": None,
        "measurable": measurable,
        "note": None,
    }


def test_divergence_is_null_when_spy_is_unmeasurable():
    rows = [
        _row("SPY", "index", "unmeasurable", measurable=False),
        _row("XLF", "sector", "short"),
    ]
    assert api_server._gamma_regime_divergence(rows) is None


def test_divergence_is_null_when_spy_is_missing_from_the_rows():
    rows = [_row("XLF", "sector", "short")]
    assert api_server._gamma_regime_divergence(rows) is None


def test_divergence_lists_sectors_running_short_gamma_under_a_long_spy():
    rows = [
        _row("SPY", "index", "long"),
        _row("XLF", "sector", "short"),
        _row("XLE", "sector", "long"),
        _row("XLK", "sector", "short"),
    ]

    divergence = api_server._gamma_regime_divergence(rows)

    assert divergence["indexRegime"] == "long"
    assert divergence["shortGammaSectors"] == ["XLF", "XLK"]
    assert "SPY" in divergence["note"]


def test_divergence_reports_an_empty_list_when_no_sector_runs_short():
    rows = [_row("SPY", "index", "long"), _row("XLF", "sector", "long")]

    divergence = api_server._gamma_regime_divergence(rows)

    assert divergence["shortGammaSectors"] == []


# ---------------------------------------------------------------------------
# Payload assembly, TTL cache, force bypass, and build-lock coalescing --
# mirrors test_opportunity_scanner_endpoint.py's coverage of the conviction
# board's identical pattern.
# ---------------------------------------------------------------------------


def _fake_row_builder(regime_by_symbol=None, note_by_symbol=None):
    regime_by_symbol = regime_by_symbol or {}
    note_by_symbol = note_by_symbol or {}
    calls: list[str] = []

    def _fn(entry, *, want_trend):
        symbol, kind, label = entry
        calls.append(symbol)
        regime = regime_by_symbol.get(symbol, "long")
        measurable = regime != "unmeasurable"
        return {
            "symbol": symbol,
            "kind": kind,
            "label": label,
            "spot": 100.0 if measurable else None,
            "netGammaM": 1.0 if measurable else None,
            "zeroGamma": 99.0 if measurable else None,
            "regime": regime,
            "distanceToFlip": 0.01 if measurable else None,
            "trend": "up" if want_trend else None,
            "measurable": measurable,
            "note": note_by_symbol.get(symbol),
        }

    _fn.calls = calls
    return _fn


def test_payload_wire_shape_matches_the_regime_contract(monkeypatch):
    monkeypatch.setattr(api_server, "_gamma_regime_row", _fake_row_builder())

    payload = api_server._gamma_regime_payload_impl(want_trend=False, force=True)

    assert set(payload) == {"asof", "universe", "rows", "divergence", "warnings", "cache"}
    assert payload["universe"] == "core"
    assert len(payload["rows"]) == len(api_server._GAMMA_REGIME_UNIVERSE)
    assert set(payload["cache"]) == {"hit", "age_seconds", "ttl_seconds"}
    assert payload["cache"]["hit"] is False


def test_payload_divergence_is_null_when_spy_row_is_unmeasurable(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "_gamma_regime_row",
        _fake_row_builder(regime_by_symbol={"SPY": "unmeasurable"}),
    )

    payload = api_server._gamma_regime_payload_impl(want_trend=False, force=True)

    assert payload["divergence"] is None


def test_payload_warnings_collect_per_row_notes(monkeypatch):
    note = "Live chain unavailable; showing the latest dated chain."
    monkeypatch.setattr(
        api_server, "_gamma_regime_row", _fake_row_builder(note_by_symbol={"XLE": note})
    )

    payload = api_server._gamma_regime_payload_impl(want_trend=False, force=True)

    assert note in payload["warnings"]


def test_payload_warnings_dedupe_identical_notes(monkeypatch):
    # Observed live: nine rows falling back to dated chains produced nine
    # identical warnings. One warning per condition is the readable form.
    note = "Live chain unavailable; showing the latest dated chain."
    monkeypatch.setattr(
        api_server,
        "_gamma_regime_row",
        _fake_row_builder(note_by_symbol={"XLE": note, "XLF": note, "XLV": note}),
    )

    payload = api_server._gamma_regime_payload_impl(want_trend=False, force=True)

    assert payload["warnings"] == [note]


def test_ttl_cache_serves_a_second_call_without_refetching(monkeypatch):
    row_fn = _fake_row_builder()
    monkeypatch.setattr(api_server, "_gamma_regime_row", row_fn)

    first = api_server._gamma_regime_payload(force=False, want_trend=False)
    assert first["cache"]["hit"] is False
    n_after_first = len(row_fn.calls)
    assert n_after_first == len(api_server._GAMMA_REGIME_UNIVERSE)

    second = api_server._gamma_regime_payload(force=False, want_trend=False)
    assert second["cache"]["hit"] is True
    assert len(row_fn.calls) == n_after_first  # no refetch on the cache hit


def test_force_bypasses_the_cache(monkeypatch):
    row_fn = _fake_row_builder()
    monkeypatch.setattr(api_server, "_gamma_regime_row", row_fn)

    api_server._gamma_regime_payload(force=False, want_trend=False)
    n_after_first = len(row_fn.calls)

    forced = api_server._gamma_regime_payload(force=True, want_trend=False)

    assert forced["cache"]["hit"] is False
    assert len(row_fn.calls) == n_after_first + len(api_server._GAMMA_REGIME_UNIVERSE)


def test_trend_flag_is_a_separate_cache_key(monkeypatch):
    row_fn = _fake_row_builder()
    monkeypatch.setattr(api_server, "_gamma_regime_row", row_fn)

    api_server._gamma_regime_payload(force=False, want_trend=False)
    n_after_first = len(row_fn.calls)

    with_trend = api_server._gamma_regime_payload(force=False, want_trend=True)

    assert with_trend["cache"]["hit"] is False
    assert len(row_fn.calls) == n_after_first + len(api_server._GAMMA_REGIME_UNIVERSE)


def test_concurrent_forced_requests_share_the_newer_build(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def impl(*, want_trend, force):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        payload = {"rows": [{"symbol": "SPY"}], "cache": {"hit": False}}
        cache_key = ("gamma_regime", want_trend)
        with api_server._GAMMA_REGIME_LOCK:
            api_server._GAMMA_REGIME_CACHE[cache_key] = (time.time(), payload)
        return payload

    monkeypatch.setattr(api_server, "_gamma_regime_payload_impl", impl)
    kwargs = {"force": True, "want_trend": False}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api_server._gamma_regime_payload, **kwargs)
        assert entered.wait(timeout=2)
        second = pool.submit(api_server._gamma_regime_payload, **kwargs)
        time.sleep(0.05)
        release.set()
        assert first.result(timeout=2)["rows"][0]["symbol"] == "SPY"
        assert second.result(timeout=2)["rows"][0]["symbol"] == "SPY"

    assert calls == 1  # the second request reused the first's build, not its own


# ---------------------------------------------------------------------------
# Route dispatch: query param parsing. There is no user-supplied symbol on
# this endpoint (the universe is fixed), so "sanitization" here means the
# boolean query flags degrade safely on garbage input rather than raising.
# Harness mirrors test_api_server_security.py's in-memory-socket dispatch so
# the real do_GET -> _route -> _dispatch_api path is exercised.
# ---------------------------------------------------------------------------


class _FakeSocket:
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


def _request(method: str, path: str):
    raw = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n"
    ).encode("utf-8")
    sock = _FakeSocket(raw)
    server = _FakeServer()
    api_server.ApiRequestHandler(sock, ("127.0.0.1", 12345), server)  # type: ignore[arg-type]
    sock.wfile.seek(0)
    raw_response = sock.wfile.read()
    header_part, _, body_part = raw_response.partition(b"\r\n\r\n")
    status = int(header_part.decode("utf-8", errors="replace").split("\r\n")[0].split(" ")[1])
    return status, json.loads(body_part.decode("utf-8"))


def _no_auth(monkeypatch):
    monkeypatch.setenv("EDGE_REQUIRE_AUTH", "0")
    monkeypatch.delenv("CLERK_JWT_KEY", raising=False)
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)


def test_route_dispatches_force_and_trend_query_params_as_booleans(monkeypatch):
    _no_auth(monkeypatch)
    captured = {}

    def fake_payload(*, force, want_trend):
        captured["force"] = force
        captured["want_trend"] = want_trend
        return {
            "asof": "now", "universe": "core", "rows": [],
            "divergence": None, "warnings": [], "cache": None,
        }

    monkeypatch.setattr(api_server, "_gamma_regime_payload", fake_payload)

    status, body = _request("GET", "/api/gamma/regime?force=1&trend=true")

    assert status == 200
    assert captured == {"force": True, "want_trend": True}
    assert body["universe"] == "core"


def test_route_treats_garbage_query_values_as_false(monkeypatch):
    _no_auth(monkeypatch)
    captured = {}

    def fake_payload(*, force, want_trend):
        captured["force"] = force
        captured["want_trend"] = want_trend
        return {}

    monkeypatch.setattr(api_server, "_gamma_regime_payload", fake_payload)

    status, _ = _request("GET", "/api/gamma/regime?force=banana&trend=nah")

    assert status == 200
    assert captured == {"force": False, "want_trend": False}


def test_route_defaults_both_flags_to_false_when_absent(monkeypatch):
    _no_auth(monkeypatch)
    captured = {}

    def fake_payload(*, force, want_trend):
        captured["force"] = force
        captured["want_trend"] = want_trend
        return {}

    monkeypatch.setattr(api_server, "_gamma_regime_payload", fake_payload)

    status, _ = _request("GET", "/api/gamma/regime")

    assert status == 200
    assert captured == {"force": False, "want_trend": False}
