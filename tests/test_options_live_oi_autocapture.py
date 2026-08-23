"""Live-path open-interest autocapture.

LSE's live chain ships greeks and activity but never open interest. Every
structural figure the desk reads -- GEX, the walls, the squeeze board -- is a
function of OI, so a name outside the dated ``option_chains`` universe used to
render ``gex_measurable: false`` and a squeeze of 0/100 UNLIKELY on first load.
That is a missing input, not an observation, and it cleared only when somebody
pressed BACKFILL OI by hand.

The live path now captures the delayed snapshot in-process and redoes the
exact-OCC join, so structure is measured for any symbol with a listed chain.
"""
from __future__ import annotations

import sys
import types

import pytest

from edge.tools import api_server
from edge.daily_plays.options_intelligence import OptionsFilters


def _install_fake_providers(monkeypatch, chain_rows: list[dict]) -> None:
    """Stand in for the three network reads `_fetch_live_option_inputs` overlaps."""

    class FakeAdapter:
        def __init__(self, **kwargs):
            pass

        def snapshot(self, symbol, *, asof_utc=None):
            return {
                "contracts": chain_rows,
                "underlying": {"price": 18.20, "quote_asof_utc": asof_utc},
            }

    monkeypatch.setattr(api_server, "LSEOptionsAdapter", FakeAdapter)
    monkeypatch.setattr(api_server, "_fetch_lse_equity_spot", lambda symbol: (18.20, None))

    fake_provider = types.ModuleType("lse_provider")
    fake_provider.fetch_lse_options_flow = lambda *a, **k: []
    monkeypatch.setitem(sys.modules, "lse_provider", fake_provider)


def _live_chain_without_oi() -> list[dict]:
    return [
        {"occ_symbol": "GME260828C00020000", "right": "call", "strike": 20.0, "open_interest": 0},
        {"occ_symbol": "GME260828P00017000", "right": "put", "strike": 17.0, "open_interest": 0},
    ]


def _snapshot_rows() -> list[dict]:
    return [
        {"contractSymbol": "GME260828C00020000", "openInterest": 4200},
        {"contractSymbol": "GME260828P00017000", "openInterest": 1800},
    ]


def test_live_chain_without_oi_autocaptures_a_delayed_snapshot(monkeypatch):
    _install_fake_providers(monkeypatch, _live_chain_without_oi())
    calls = {"ensure": 0, "captured": False}

    def fake_hist(symbol, *, asof=None, all_days=False):
        if calls["captured"]:
            return _snapshot_rows(), "2026-08-22", ["2026-08-22"]
        return [], None, []

    def fake_ensure(symbol, *, max_dte=60, max_age_seconds=15 * 60.0):
        calls["ensure"] += 1
        assert symbol == "GME"
        assert max_dte >= 60
        calls["captured"] = True
        return True, None

    monkeypatch.setattr(api_server, "_historical_option_rows", fake_hist)
    monkeypatch.setattr(api_server, "_ensure_delayed_chain_snapshot", fake_ensure)

    chain_rows, _flow, _spot, oi_source, warnings, _spot_source = (
        api_server._fetch_live_option_inputs("GME", filters=OptionsFilters())
    )

    assert calls["ensure"] == 1
    assert oi_source == "cached_chain_exact_occ:2026-08-22"
    assert [row["open_interest"] for row in chain_rows] == [4200, 1800]
    assert any("auto-captured" in str(note).lower() for note in warnings)


def test_live_oi_present_never_triggers_a_capture(monkeypatch):
    """A chain that already carries OI must not pay for a provider round trip."""
    rows = _live_chain_without_oi()
    rows[0]["open_interest"] = 3100
    _install_fake_providers(monkeypatch, rows)

    def boom(*a, **k):  # pragma: no cover - asserts the branch is never taken
        raise AssertionError("captured a snapshot despite live OI")

    monkeypatch.setattr(
        api_server, "_historical_option_rows", lambda *a, **k: ([], None, [])
    )
    monkeypatch.setattr(api_server, "_ensure_delayed_chain_snapshot", boom)

    _chain, _flow, _spot, oi_source, _warnings, _src = api_server._fetch_live_option_inputs(
        "GME", filters=OptionsFilters()
    )

    assert oi_source == "lse_live"


def test_capture_failure_stays_unmeasured_and_says_why(monkeypatch):
    """An honest `unavailable` beats a fake zero -- but it must carry the reason."""
    _install_fake_providers(monkeypatch, _live_chain_without_oi())
    monkeypatch.setattr(
        api_server, "_historical_option_rows", lambda *a, **k: ([], None, [])
    )
    monkeypatch.setattr(
        api_server,
        "_ensure_delayed_chain_snapshot",
        lambda *a, **k: (False, "provider returned no expiries"),
    )

    chain_rows, _flow, _spot, oi_source, warnings, _src = api_server._fetch_live_option_inputs(
        "ZZZZ", filters=OptionsFilters()
    )

    assert oi_source == "unavailable"
    assert all(int(row["open_interest"]) == 0 for row in chain_rows)
    assert any("no expiries" in str(note) for note in warnings)


@pytest.fixture(autouse=True)
def _clear_miss_cache():
    api_server._DELAYED_CHAIN_MISS.clear()
    yield
    api_server._DELAYED_CHAIN_MISS.clear()


def test_uncovered_symbol_is_not_refetched_on_every_request(monkeypatch):
    """Indices and delisted tickers fail every time; each attempt costs seconds."""
    attempts = {"n": 0}

    def fake_backfill(symbol, *, max_dte):
        attempts["n"] += 1
        return {"error": f"No options data from the provider for {symbol}"}, 404

    monkeypatch.setattr(api_server, "_backfill_oi_payload", fake_backfill)

    first_ok, first_err = api_server._ensure_delayed_chain_snapshot("NODATA")
    second_ok, second_err = api_server._ensure_delayed_chain_snapshot("NODATA")

    assert first_ok is False and second_ok is False
    assert first_err == second_err
    assert attempts["n"] == 1, "the failed capture was retried within its TTL"

    # A distinct symbol is still attempted, and an expired entry retries.
    api_server._ensure_delayed_chain_snapshot("OTHER")
    assert attempts["n"] == 2
    api_server._DELAYED_CHAIN_MISS["NODATA"] = (
        api_server.time.time() - api_server._DELAYED_CHAIN_MISS_TTL_S - 1,
        "stale",
    )
    api_server._ensure_delayed_chain_snapshot("NODATA")
    assert attempts["n"] == 3
