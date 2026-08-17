"""Single-name /api/options fallback when live LSE and local cache both miss."""
from __future__ import annotations

from edge.tools import api_server


def _clear_options_cache() -> None:
    with api_server._OPTIONS_LOCK:
        api_server._OPTIONS_CACHE.clear()


def test_live_miss_captures_delayed_snapshot_instead_of_404(monkeypatch):
    """Names outside the cached universe (QBTS-class) must not hard-fail.

    Live LSE is empty and there is no dated parquet yet. The payload builder
    should capture a delayed snapshot, then serve that chain as a visible
    history fallback — not a 404 that paints a wall of fake zeros.
    """
    _clear_options_cache()
    captured = {"ok": False}

    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], None))
    monkeypatch.setattr(
        api_server,
        "_fetch_live_option_inputs",
        lambda *a, **k: ([], [], None, "unavailable", ["Live chain unavailable: RuntimeError"], None),
    )

    def fake_hist(symbol, *, asof=None, all_days=False):
        if captured["ok"]:
            return (
                [{"occ_symbol": "QBTS260821C00025000", "right": "call", "strike": 25.0}],
                "2026-08-16",
                ["2026-08-16"],
            )
        return [], None, []

    def fake_ensure(symbol, *, max_dte=60, max_age_seconds=15 * 60.0):
        assert symbol == "QBTS"
        assert max_dte >= 60
        captured["ok"] = True
        return True, None

    monkeypatch.setattr(api_server, "_historical_option_rows", fake_hist)
    monkeypatch.setattr(api_server, "_ensure_delayed_chain_snapshot", fake_ensure)
    monkeypatch.setattr(
        api_server,
        "build_options_intelligence",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "mode_resolved": kwargs["mode_resolved"],
            "chain_source": kwargs["chain_source"],
            "warnings": list(kwargs.get("warnings") or []),
        },
    )

    payload, status = api_server._options_payload_impl("QBTS", {"mode": ["live"]})

    assert status == 200
    assert captured["ok"] is True
    assert payload["symbol"] == "QBTS"
    assert payload["mode_resolved"] == "history_fallback"
    assert any("delayed" in str(note).lower() for note in payload.get("warnings") or [])


def test_live_and_delayed_miss_returns_structured_404(monkeypatch):
    _clear_options_cache()
    monkeypatch.setattr(api_server, "_options_price_series", lambda *a, **k: ([], None))
    monkeypatch.setattr(
        api_server,
        "_fetch_live_option_inputs",
        lambda *a, **k: ([], [], None, "unavailable", [], None),
    )
    monkeypatch.setattr(
        api_server, "_historical_option_rows", lambda *a, **k: ([], None, []),
    )
    monkeypatch.setattr(
        api_server,
        "_ensure_delayed_chain_snapshot",
        lambda *a, **k: (False, "provider returned no expiries"),
    )

    payload, status = api_server._options_payload_impl("ZZZZ", {"mode": ["live"]})

    assert status == 404
    assert "ZZZZ" in payload["error"]
    assert payload["reason"] == "live_empty_and_no_local_snapshot"
    assert "no expiries" in (payload.get("delayed_snapshot_error") or "")
