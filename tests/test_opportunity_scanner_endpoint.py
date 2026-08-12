from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from edge.tools import api_server


def _fake_board_payload(rows):
    def _fn(*, limit, depth, require_live_flow, force):
        _fn.calls.append(
            {"limit": limit, "depth": depth, "require_live_flow": require_live_flow, "force": force}
        )
        return {"rows": rows}

    _fn.calls = []
    return _fn


def _fake_flow_payload(rows):
    def _fn(*, limit, min_premium, force=False):
        _fn.calls.append({"limit": limit, "min_premium": min_premium, "force": force})
        return {"rows": rows}

    _fn.calls = []
    return _fn


def _reset_cache():
    api_server._LIVE_OPPORTUNITIES_CACHE = None
    api_server._LIVE_OPPORTUNITIES_CACHE_TS = 0.0


def _patch(monkeypatch, board_rows, flow_rows):
    board_fn = _fake_board_payload(board_rows)
    flow_fn = _fake_flow_payload(flow_rows)
    monkeypatch.setattr(api_server, "_options_board_payload", board_fn)
    monkeypatch.setattr(api_server, "_unusual_flow_payload", flow_fn)
    _reset_cache()
    return board_fn, flow_fn


def test_payload_reuses_cache_across_calls(monkeypatch):
    board_fn, flow_fn = _patch(
        monkeypatch,
        board_rows=[{"symbol": "AAA", "squeeze_score": 1.0, "spread_pct": 0.1,
                      "open_interest": 500, "selected_dte": 10}],
        flow_rows=[{"symbol": "AAA", "unusual_score": 50.0}],
    )

    first = api_server._live_opportunities_payload()
    second = api_server._live_opportunities_payload()

    assert len(board_fn.calls) == 1
    assert len(flow_fn.calls) == 1
    assert first is second
    assert first["available"] is True
    assert first["rows"][0]["symbol"] == "AAA"


def test_force_bypasses_the_opportunities_cache(monkeypatch):
    board_fn, flow_fn = _patch(monkeypatch, board_rows=[], flow_rows=[])

    api_server._live_opportunities_payload()
    api_server._live_opportunities_payload(force=True)

    assert len(board_fn.calls) == 2
    assert len(flow_fn.calls) == 2


def test_force_cascades_once_to_the_underlying_board_and_flow_fetches(monkeypatch):
    """An explicit operator refresh must pull upstream data, not re-label stale caches."""
    board_fn, flow_fn = _patch(monkeypatch, board_rows=[], flow_rows=[])

    api_server._live_opportunities_payload(force=True)

    assert board_fn.calls[0]["force"] is True
    assert flow_fn.calls[0]["force"] is True


def test_payload_shape_has_the_expected_top_level_keys(monkeypatch):
    _patch(
        monkeypatch,
        board_rows=[{"symbol": "AAA", "squeeze_score": 2.0, "spread_pct": 0.05,
                      "open_interest": 200, "selected_dte": 15}],
        flow_rows=[],
    )

    payload = api_server._live_opportunities_payload()

    assert payload["decision_authorized"] is False
    assert payload["score_kind"] == "ordinal_composite"
    for key in ("rows", "coverage", "warnings", "caveats", "schema_version", "asof_utc"):
        assert key in payload


def test_empty_board_and_flow_produce_the_unavailable_shape(monkeypatch):
    _patch(monkeypatch, board_rows=[], flow_rows=[])

    payload = api_server._live_opportunities_payload()

    assert payload == {"available": False, "reason": "No board or unusual-flow rows were supplied."}


def test_default_board_and_flow_calls_match_the_standalone_endpoints_defaults(monkeypatch):
    """Calling with the same (limit, depth, min_premium) the standalone board/
    unusual-flow routes default to means a warm visit to either page already
    populated the cache entry this endpoint will hit -- no extra vendor call."""
    board_fn, flow_fn = _patch(monkeypatch, board_rows=[], flow_rows=[])

    api_server._live_opportunities_payload()

    assert board_fn.calls[0]["limit"] == 25
    assert board_fn.calls[0]["require_live_flow"] is False
    assert flow_fn.calls[0]["limit"] == 40
    assert flow_fn.calls[0]["min_premium"] == 25_000.0


def test_concurrent_unusual_flow_cache_misses_share_one_build(monkeypatch):
    api_server._UNUSUAL_FLOW_CACHE.clear()
    api_server._UNUSUAL_FLOW_BUILD_LOCKS.clear()
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def build(**_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return {"rows": [], "coverage": {}}

    monkeypatch.setattr(api_server, "build_unusual_options_flow", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            api_server._unusual_flow_payload,
            limit=40,
            min_premium=25_000.0,
            force=False,
        )
        assert entered.wait(timeout=2)
        second = pool.submit(
            api_server._unusual_flow_payload,
            limit=40,
            min_premium=25_000.0,
            force=False,
        )
        time.sleep(0.05)
        release.set()
        assert first.result(timeout=2)["rows"] == []
        assert second.result(timeout=2)["rows"] == []

    assert calls == 1


def test_cold_options_board_uses_lazy_thread_pool(monkeypatch):
    api_server._OPTIONS_BOARD_CACHE.clear()
    monkeypatch.setattr(
        api_server,
        "get_dashboard_data",
        lambda **_: {"activity_scan": {}, "scan_summary": {"depth": "quick"}},
    )
    monkeypatch.setattr(api_server, "select_board_candidates", lambda **_: ([object()], 1))
    monkeypatch.setattr(
        api_server,
        "_options_board_row",
        lambda _candidate: {"available": True, "gex_measurable": True, "rank": 1},
    )
    monkeypatch.setattr(
        api_server,
        "_options_board_wire",
        lambda **kwargs: {"rows": kwargs["rows"]},
    )

    payload = api_server._options_board_payload_impl(
        limit=1, depth="quick", require_live_flow=False, force=True,
    )

    assert payload["rows"] == [{"available": True, "gex_measurable": True, "rank": 1}]


def test_concurrent_forced_board_requests_share_the_newer_build(monkeypatch):
    api_server._OPTIONS_BOARD_CACHE.clear()
    api_server._OPTIONS_BOARD_BUILD_LOCKS.clear()
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def impl(*, limit, depth, require_live_flow, force):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        payload = {"rows": [{"symbol": "AAA"}], "cache": {"hit": False}}
        cache_key = (limit, depth, require_live_flow)
        with api_server._OPTIONS_BOARD_LOCK:
            api_server._OPTIONS_BOARD_CACHE[cache_key] = (time.time(), payload)
        return payload

    monkeypatch.setattr(api_server, "_options_board_payload_impl", impl)
    kwargs = {"limit": 25, "depth": "quick", "require_live_flow": False, "force": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api_server._options_board_payload, **kwargs)
        assert entered.wait(timeout=2)
        second = pool.submit(api_server._options_board_payload, **kwargs)
        time.sleep(0.05)
        release.set()
        assert first.result(timeout=2)["rows"][0]["symbol"] == "AAA"
        assert second.result(timeout=2)["rows"][0]["symbol"] == "AAA"

    assert calls == 1
