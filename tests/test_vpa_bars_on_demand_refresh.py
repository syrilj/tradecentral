"""On-demand refresh for VPA bar loading: a stale-or-missing parquet must heal
itself when the desk searches the symbol.

Root cause covered (2026-09-14 incident): every daily parquet on disk froze at
2026-09-11 while Yahoo already carried the 2026-09-14 close, because
`load_bars` fetched from the provider *only when a symbol's parquet was
missing entirely*. A stale-but-present file was served as-is until the nightly
job refreshed it -- and the launchd jobs were dead (exit 126). The desk read
four-day-old bars for CRDO while the index chips (live-quote path) showed
Monday's close.

The fix, exercised here end to end through `load_bars` with the network
seam stubbed behind a fake `fetch_universe` module:

1. A stale daily file (a newer session has fully closed since its last bar,
   or its last bar's own session just closed and the bar may be a partial
   in-progress write from another writer) is refetched on load, merged
   newest-wins, and re-served -- ``refreshed_on_demand`` marks the event.
2. Cooldown + a verified-through marker bound Yahoo traffic: a healed symbol
   is quiet until the next session close; a provider that has not published
   yet is retried at most once per cooldown, never per request.
3. Bars whose session has not closed are never written to disk by this
   fetch path (defence against the in-progress-bar poisoning documented in
   `bar_is_complete`).
4. A missing hourly parquet is fetched on demand too, so a searched symbol
   stops reporting "no hourly bars on disk" when the provider has them.
5. Failure stays honest: error meta unchanged, no fabricated freshness.
"""

import sys
import types
from datetime import datetime, timezone

import pandas as pd
import pytest

from research import vpa_bars as vb

UTC = timezone.utc
FRI = "2026-09-11"  # Friday
MON = "2026-09-14"  # Monday
TUE = "2026-09-15"  # Tuesday (relative to NOW_* below: not yet closed)
AFTER_CLOSE_MON = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)  # Mon 20:00 ET
MID_SESSION_MON = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)  # Mon 11:00 ET


def _daily_df(rows):
    """rows: list of (date_str, close, volume). open/high/low derived."""
    idx = pd.to_datetime([r[0] for r in rows])
    close = [float(r[1]) for r in rows]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 2.0 for c in close],
            "low": [c - 2.0 for c in close],
            "close": close,
            "volume": [float(r[2]) for r in rows],
        },
        index=idx,
    )


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for sub in ("1d", "1d_wide", "1h"):
        (data / sub).mkdir(parents=True)
    monkeypatch.setattr(vb, "DATA_ROOT", data)
    monkeypatch.setattr(vb, "DAILY_DIRS", (data / "1d", data / "1d_wide"))
    monkeypatch.setattr(vb, "HOURLY_DIR", data / "1h")
    for name in ("_FETCH_ATTEMPT_TS", "_VERIFIED_THROUGH"):
        store = getattr(vb, name, None)
        if store is not None:
            store.clear()
    return data


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replace the tools/fetch_universe network seam with a scripted provider."""
    mod = types.ModuleType("fetch_universe")
    calls = []
    responses = {}

    def fetch_one(symbol, interval):
        calls.append((symbol, interval))
        resp = responses.get((symbol, interval))
        if resp is None:
            raise AssertionError(f"unexpected fetch: {symbol} {interval}")
        if isinstance(resp, Exception):
            raise resp
        return resp

    mod.fetch_one = fetch_one
    monkeypatch.setitem(sys.modules, "fetch_universe", mod)
    return calls, responses


def _write_daily(sandbox, df):
    df.to_parquet(sandbox / "1d" / "CRDO.parquet")


def test_stale_daily_file_is_refreshed_on_search(sandbox, fake_fetch):
    calls, responses = fake_fetch
    _write_daily(sandbox, _daily_df([(FRI, 162.95, 5_889_800)]))
    responses[("CRDO", "1d")] = _daily_df(
        [(FRI, 162.95, 5_889_800), (MON, 150.09, 10_663_800)]
    )

    bars, meta = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    assert calls == [("CRDO", "1d")]
    assert bars[-1]["date"].startswith(MON)
    assert bars[-1]["close"] == pytest.approx(150.09)
    assert meta["timeframe_served"] == "1D"
    assert meta.get("refreshed_on_demand") is True
    disk = pd.read_parquet(sandbox / "1d" / "CRDO.parquet")
    assert disk.index[-1].date().isoformat() == MON


def test_refreshed_symbol_is_not_refetched_until_next_session_close(sandbox, fake_fetch):
    calls, responses = fake_fetch
    _write_daily(sandbox, _daily_df([(FRI, 162.95, 5_889_800)]))
    responses[("CRDO", "1d")] = _daily_df(
        [(FRI, 162.95, 5_889_800), (MON, 150.09, 10_663_800)]
    )

    vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)
    vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    assert calls == [("CRDO", "1d")]


def test_partial_same_day_bar_is_replaced_by_the_complete_bar(sandbox, fake_fetch):
    calls, responses = fake_fetch
    # Someone (api auto-sync) wrote Yahoo's in-progress Monday bar mid-session.
    _write_daily(
        sandbox, _daily_df([(FRI, 162.95, 5_889_800), (MON, 150.00, 2_000_000)])
    )
    responses[("CRDO", "1d")] = _daily_df(
        [(FRI, 162.95, 5_889_800), (MON, 150.09, 10_663_800)]
    )

    bars, meta = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    assert calls == [("CRDO", "1d")]
    assert bars[-1]["close"] == pytest.approx(150.09)
    disk = pd.read_parquet(sandbox / "1d" / "CRDO.parquet")
    assert disk.iloc[-1]["volume"] == pytest.approx(10_663_800)
    assert meta.get("refreshed_on_demand") is True


def test_mid_session_search_never_fetches_and_drops_the_forming_bar(sandbox, fake_fetch):
    calls, responses = fake_fetch
    _write_daily(
        sandbox, _daily_df([(FRI, 162.95, 5_889_800), (MON, 150.00, 2_000_000)])
    )

    bars, meta = vb.load_bars("CRDO", "1D", lookback=30, now=MID_SESSION_MON)

    assert calls == []
    assert bars[-1]["date"].startswith(FRI)
    assert meta["incomplete_bar_dropped"].startswith(MON)
    assert meta["live_bar"] is not None


def test_unclosed_session_rows_from_provider_are_never_written(sandbox, fake_fetch):
    calls, responses = fake_fetch
    _write_daily(sandbox, _daily_df([(FRI, 162.95, 5_889_800)]))
    # Provider hands back a row for Tuesday whose session has not yet closed.
    responses[("CRDO", "1d")] = _daily_df(
        [
            (FRI, 162.95, 5_889_800),
            (MON, 150.09, 10_663_800),
            (TUE, 151.00, 100_000),
        ]
    )

    bars, _meta = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    disk = pd.read_parquet(sandbox / "1d" / "CRDO.parquet")
    assert disk.index[-1].date().isoformat() == MON
    assert bars[-1]["date"].startswith(MON)


def test_provider_lag_does_not_rewrite_and_is_cooldown_limited(sandbox, fake_fetch):
    calls, responses = fake_fetch
    _write_daily(sandbox, _daily_df([(FRI, 162.95, 5_889_800)]))
    # Provider has not yet published Monday's bar (the 2026-09-14 19:37 state).
    responses[("CRDO", "1d")] = _daily_df([(FRI, 162.95, 5_889_800)])

    bars1, meta1 = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)
    bars2, _meta2 = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    assert calls == [("CRDO", "1d")]
    assert bars1[-1]["date"].startswith(FRI)
    assert bars2[-1]["date"].startswith(FRI)
    assert meta1.get("refreshed_on_demand") is False
    disk = pd.read_parquet(sandbox / "1d" / "CRDO.parquet")
    assert disk.index[-1].date().isoformat() == FRI


def test_missing_hourly_parquet_is_fetched_instead_of_downgrading(sandbox, fake_fetch):
    calls, responses = fake_fetch
    idx = pd.date_range("2026-09-14 09:30", periods=7, freq="60min")
    closes = [150.0 + i for i in range(7)]
    responses[("CRDO", "1h")] = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1000.0] * 7,
        },
        index=idx,
    )

    bars, meta = vb.load_bars("CRDO", "1h", lookback=60, now=AFTER_CLOSE_MON)

    assert calls == [("CRDO", "1h")]
    assert meta["timeframe_served"] == "1h"
    assert meta["downgraded"] is False
    assert "15:30" in bars[-1]["date"]


def test_missing_symbol_with_failed_fetch_stays_honest(sandbox, fake_fetch):
    _calls, responses = fake_fetch
    responses[("CRDO", "1d")] = RuntimeError("yahoo unreachable")

    bars, meta = vb.load_bars("CRDO", "1D", lookback=30, now=AFTER_CLOSE_MON)

    assert bars == []
    assert meta["available"] is False
    assert "no daily parquet found" in meta["downgrade_reason"]
    assert meta.get("refreshed_on_demand") is False
