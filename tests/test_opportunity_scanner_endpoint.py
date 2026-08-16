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
    api_server._FLOW_SUGGESTION_CACHE.clear()


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

    assert payload["available"] is False
    assert payload["reason"] == "No board or unusual-flow rows were supplied."
    assert payload["suggestion"]["right"] == "blocked"
    assert payload["suggestion"]["sell"] is None


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


def test_flow_click_builds_the_exact_symbol_even_outside_the_broad_board(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "get_dashboard_data",
        lambda **_: {"directional_signals": [], "activity_scan": {}},
    )
    monkeypatch.setattr(api_server, "select_board_candidates", lambda **_: ([], 0))
    monkeypatch.setattr(
        api_server,
        "_unusual_flow_payload",
        lambda **_: {
            "rows": [{
                "symbol": "XYZ", "unusual_score": 8.0, "context_side": "long",
                "live": True, "live_asof": "2026-08-14T01:00:00+00:00",
            }],
            "cache": {"age_seconds": 0},
            "asof": "2026-08-14T01:00:00+00:00",
        },
    )
    seen = []

    def board_row(candidate):
        seen.append(candidate)
        return {
            "symbol": candidate.symbol,
            "context_side": candidate.context_side,
            "available": True,
            "spot": 100,
            "call_wall": 108,
            "put_wall": 96,
            "squeeze_score": 2,
            "spread_pct": 0.05,
            "open_interest": 500,
            "selected_dte": 21,
            "mode_resolved": "live",
            "observed_at": "2026-08-14T01:00:00+00:00",
        }

    monkeypatch.setattr(api_server, "_options_board_row", board_row)
    monkeypatch.setattr(api_server, "peek_shared_qlib_panel", lambda: None)
    api_server._FLOW_SUGGESTION_CACHE.clear()

    payload = api_server._flow_suggestion_payload("XYZ", force=True)

    assert seen[0].symbol == "XYZ"
    assert payload["requested_symbol"] == "XYZ"
    assert payload["sources"]["symbol_specific"] is True
    assert payload["rows"][0]["symbol"] == "XYZ"
    assert payload["rows"][0]["suggestion"]["right"] == "call"
    assert payload["decision_authorized"] is False


def test_symbol_suggestion_reuses_its_short_live_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_server,
        "_flow_suggestion_payload_impl",
        lambda symbol, force=False: calls.append((symbol, force)) or {"requested_symbol": symbol},
    )
    api_server._FLOW_SUGGESTION_CACHE.clear()

    first = api_server._flow_suggestion_payload("ABC")
    second = api_server._flow_suggestion_payload("ABC")

    assert first is second
    assert calls == [("ABC", False)]


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


def test_payload_folds_published_qlib_without_rebuilding(monkeypatch):
    from edge.daily_plays.qlib_scan_score import clear_shared_qlib_panel, publish_shared_qlib_panel

    clear_shared_qlib_panel()
    publish_shared_qlib_panel({
        "quality": "ok",
        "source": "qlib_scan_lgb_v2",
        "score_kind": "ordinal_qlib_xs",
        "asof": "2026-08-09",
        "coverage": {"scored": 9},
        "by_symbol": {
            "AAA": {"symbol": "AAA", "qlib_score": 0.4, "qlib_rank": 2, "source": "qlib_scan_lgb_v2"},
        },
    })
    rebuilt = []

    def boom(*_args, **_kwargs):
        rebuilt.append(1)
        raise AssertionError("must not rebuild the published qlib panel")

    monkeypatch.setattr("edge.daily_plays.qlib_scan_score.score_cross_section_asof", boom)
    _patch(
        monkeypatch,
        board_rows=[{
            "symbol": "AAA", "squeeze_score": 1.0, "spread_pct": 0.1,
            "open_interest": 500, "selected_dte": 10, "context_side": "long",
            "spot": 100, "call_wall": 108, "put_wall": 96,
        }],
        flow_rows=[{"symbol": "AAA", "unusual_score": 50.0, "context_side": "long"}],
    )

    payload = api_server._live_opportunities_payload()
    sug = payload["rows"][0]["suggestion"]
    assert sug["right"] == "call"
    assert sug["sell"] == 108
    assert sug["qlib"]["score"] == 0.4
    assert sug["qlib"]["measured"] is True
    assert rebuilt == []
    assert payload["sources"]["qlib"]["published"] is True
    clear_shared_qlib_panel()
