from __future__ import annotations

import pandas as pd

from edge.tools import api_server


def _prices() -> pd.DataFrame:
    index = pd.bdate_range("2026-01-02", periods=25)
    close = pd.Series(range(100, 125), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_pandas_helpers_load_the_lazy_dependency_before_using_it():
    prices = _prices()

    assert api_server._ytd_chg_pct(prices["close"]) is not None

    atr, atr_pct, adv = api_server._atr_adv(prices)
    assert atr is not None
    assert atr_pct is not None
    assert adv is not None

    factors = api_server._compute_factors(prices)
    assert factors["adv20_usd"] is not None
    assert factors["liq"] is not None


def test_compare_payload_uses_the_lazy_pandas_dependency(monkeypatch):
    prices = _prices()
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (prices, "core"))

    payload, status = api_server._compare_payload(["AAA", "BBB"], "1m")

    assert status == 200
    assert set(payload["series"]) == {"AAA", "BBB"}
    assert payload["generated_at"]
    assert payload["stats"]["AAA"]["asof"] == prices.index[-1].date().isoformat()
    assert payload["stats"]["AAA"]["change_basis"] == "last_two_observed_closes"


def test_lite_trajectory_skips_full_market_qlib_context(monkeypatch):
    prices = _prices()
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (prices, "core"))
    monkeypatch.setattr(
        api_server,
        "_trajectory_qlib_context",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("qlib should be skipped")),
    )

    payload, status = api_server._trajectory_payload("AAA", "1m", include_qlib=False)

    assert status == 200
    assert payload["series"]
    assert "qlib" not in payload
    assert "qlib_score" not in payload


def test_options_price_series_reads_one_symbol_and_preserves_volume(monkeypatch):
    prices = _prices()
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (prices, "core"))
    monkeypatch.setattr(
        api_server,
        "_trajectory_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("trajectory should not run")),
    )

    series, spot = api_server._options_price_series("AAA", "1m")

    assert spot == prices["close"].iloc[-1]
    assert series[-1]["volume"] == 1_000_000
    assert len(series) == 23


def test_resolve_live_options_spot_prefers_equity_candles_over_local_close():
    warnings: list[str] = []
    spot, source = api_server._resolve_live_options_spot(
        chain_spot=None,
        equity_spot=772.75,
        equity_asof="2026-08-12T14:40:00+00:00",
        flow_spot=771.0,
        flow_asof="2026-08-12T14:00:00+00:00",
        price_spot=771.33,
        price_asof="2026-08-05T20:00:00+00:00",
        warnings=warnings,
    )
    assert spot == 772.75
    assert source and source.startswith("lse_equity_candles:")
    assert warnings == []


def test_resolve_live_options_spot_warns_when_only_local_close_is_available():
    warnings: list[str] = []
    spot, source = api_server._resolve_live_options_spot(
        chain_spot=None,
        equity_spot=None,
        equity_asof=None,
        flow_spot=None,
        flow_asof=None,
        price_spot=771.33,
        price_asof="2026-08-05T20:00:00+00:00",
        warnings=warnings,
    )
    assert spot == 771.33
    assert source and source.startswith("local_daily_close:")
    assert any("local daily close" in note for note in warnings)


def test_augment_price_series_appends_live_session_when_local_bars_lag():
    series = [
        {"t": "2026-08-04T20:00:00+00:00", "close": 760.0, "volume": 1.0},
        {"t": "2026-08-05T20:00:00+00:00", "close": 771.33, "volume": 1.0},
    ]
    out = api_server._augment_price_series_with_live(
        series, 772.75, "2026-08-12T14:40:00+00:00",
    )
    assert len(out) == 3
    assert out[-1]["close"] == 772.75
    assert out[-1]["t"].startswith("2026-08-12")


def test_spot_from_flow_rows_keeps_most_recent_timestamped_print():
    price, asof = api_server._spot_from_flow_rows(
        [
            {"underlying_price": 770.0, "ts": "2026-08-12T10:00:00+00:00"},
            {"underlying_price": 772.97, "ts": "2026-08-12T14:41:00+00:00"},
            {"underlying_price": 900.0},  # untimestamped must not win
        ]
    )
    assert price == 772.97
    assert asof and asof.startswith("2026-08-12T14:41")


def test_compare_change_does_not_use_forward_filled_overlap(monkeypatch):
    early = _prices().iloc[:20].copy()
    late = _prices().copy()
    expected = ((early["close"].iloc[-1] / early["close"].iloc[-2]) - 1.0) * 100.0

    monkeypatch.setattr(
        api_server,
        "_load_symbol_df",
        lambda symbol: (early if symbol == "AAA" else late, "core"),
    )

    payload, status = api_server._compare_payload(["AAA", "BBB"], "1m")

    assert status == 200
    assert payload["stats"]["AAA"]["chg_1d_pct"] == round(expected, 4)
    assert payload["stats"]["AAA"]["asof"] == early.index[-1].date().isoformat()
    assert payload["stats"]["BBB"]["asof"] == late.index[-1].date().isoformat()


def test_stale_shell_benchmark_prefers_newer_bounded_refresh(monkeypatch):
    local = _prices().copy()
    live = _prices().copy()
    live.index = pd.bdate_range("2026-07-08", periods=len(live))
    live["close"] = live["close"] + 50
    api_server._COMPARE_REFRESH_CACHE.clear()

    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (local, "core"))
    monkeypatch.setattr(api_server, "_fetch_yfinance_ohlcv", lambda _symbol: live)
    monkeypatch.setattr(
        api_server,
        "_frame_age_days",
        lambda frame, now=None: 10 if frame is local else 0,
    )

    payload, status = api_server._compare_payload(["SPY"], "1m")

    assert status == 200
    assert payload["stats"]["SPY"]["source"] == "yfinance_refresh"
    assert payload["stats"]["SPY"]["quality"] == "current"
    assert payload["stats"]["SPY"]["asof"] == live.index[-1].date().isoformat()
    assert payload["stats"]["SPY"]["last_price"] == live["close"].iloc[-1]
    api_server._COMPARE_REFRESH_CACHE.clear()
