"""Unit tests for the pure as-of qlib scan scorer (no future leakage)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.qlib_scan_score import (
    SCORE_KIND,
    SOURCE_ID,
    SOURCE_ID_FACTORS,
    SOURCE_ID_LGB,
    clear_shared_qlib_panel,
    feature_row_from_frame,
    get_shared_qlib_panel,
    lookup_symbol_on_shared_panel,
    lookup_symbol_qlib_context,
    merge_qlib_into_activity_rows,
    publish_shared_qlib_panel,
    qlib_priority_symbols,
    score_cross_section_asof,
    truncate_to_asof,
)

def _ok_source(src: str | None) -> bool:
    s = str(src or "")
    return (
        s in {SOURCE_ID, SOURCE_ID_FACTORS, SOURCE_ID_LGB, "qlib_scan_lgb_v1", "qlib_scan_lgb_v2"}
        or s.startswith("qlib_scan_lgb_")
        or s.startswith("qlib_alpha_factor")
    )


def _bars(
    *,
    start: str = "2024-01-02",
    periods: int = 300,
    last_ret: float = 0.0,
    volume: float = 1_000_000.0,
    seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods)
    # Geometric random walk with a controlled final return.
    rets = rng.normal(0.0005, 0.015, size=periods)
    rets[-1] = last_ret
    close = 100.0 * np.cumprod(1.0 + rets)
    vol = np.full(periods, volume)
    vol[-1] = volume * (2.0 if abs(last_ret) > 0.03 else 1.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": vol,
        },
        index=dates,
    )


def test_truncate_to_asof_drops_future_bars():
    frame = _bars(periods=100)
    cut = frame.index[50]
    pit = truncate_to_asof(frame, cut)
    assert pit.index.max() <= pd.Timestamp(cut)
    assert len(pit) == 51
    # Feature math on truncated frame cannot see the post-cut close.
    future_close = float(frame["close"].iloc[-1])
    assert float(pit["close"].iloc[-1]) != future_close or cut == frame.index[-1]


def test_score_panel_is_point_in_time_and_ordinal():
    frames = {
        "AAA": _bars(last_ret=-0.06, seed=1),  # loser yesterday → high rev1
        "BBB": _bars(last_ret=0.06, seed=2),   # winner yesterday → low rev1
        "CCC": _bars(last_ret=0.0, seed=3),
    }
    asof = frames["AAA"].index[-1]

    # Inject a poisoned future bar that must never enter features.
    poisoned = frames["AAA"].copy()
    extra_idx = asof + pd.Timedelta(days=5)
    poisoned.loc[extra_idx] = poisoned.iloc[-1]
    poisoned.loc[extra_idx, "close"] = 1e9
    frames["AAA"] = poisoned

    panel = score_cross_section_asof(
        symbols=list(frames),
        asof=asof,
        candle_loader=frames.__getitem__,
    )

    assert panel["quality"] == "ok"
    assert panel["score_kind"] == SCORE_KIND
    assert _ok_source(panel["source"])
    assert panel["coverage"]["scored"] == 3
    assert panel["decision_authorized"] is False
    assert all(row["score_kind"] == SCORE_KIND for row in panel["rows"])
    assert all(row["decision_authorized"] is False for row in panel["rows"])
    # Ranks are 1..N dense.
    ranks = sorted(row["qlib_rank"] for row in panel["rows"])
    assert ranks == [1, 2, 3]
    # Future poison did not produce an absurd score dominated by 1e9 close.
    aaa = panel["by_symbol"]["AAA"]
    assert abs(float(aaa["qlib_score"])) < 50.0


def test_missing_data_fails_closed_without_invented_ranks():
    panel = score_cross_section_asof(
        symbols=["NOSUCH"],
        candle_loader=lambda _: pd.DataFrame(),
    )
    assert panel["quality"] == "missing"
    assert panel["rows"] == []
    assert panel["by_symbol"] == {}
    assert panel["coverage"]["scored"] == 0
    assert "no_symbols_scored" in panel["warnings"] or panel["coverage"]["skipped_insufficient_history"] >= 1

    ctx = lookup_symbol_qlib_context("NOSUCH", panel=panel)
    assert ctx["quality"] == "missing"
    assert ctx["qlib_score"] is None
    assert ctx["qlib_rank"] is None
    assert ctx["score_kind"] == SCORE_KIND


def test_no_loader_fails_closed():
    panel = score_cross_section_asof(symbols=["AAPL"], data_dirs=())
    assert panel["quality"] == "missing"
    assert panel["rows"] == []
    assert any("no_data" in w for w in panel["warnings"])


def test_qlib_provider_failure_fails_closed(monkeypatch):
    def boom(**_):
        raise RuntimeError("provider down")

    # Force provider path via the public API.
    from edge.daily_plays import qlib_scan_score as mod

    monkeypatch.setattr(mod, "_score_via_qlib_provider", boom)
    panel = score_cross_section_asof(
        symbols=["AAPL"],
        provider="qlib",
    )
    assert panel["quality"] == "missing"
    assert panel["rows"] == []
    assert any("qlib_provider_failed" in w for w in panel["warnings"])


def test_merge_and_priority_helpers():
    frames = {
        "AAA": _bars(last_ret=-0.05, seed=10),
        "BBB": _bars(last_ret=0.05, seed=11),
        "CCC": _bars(last_ret=0.0, seed=12),
    }
    panel = score_cross_section_asof(
        symbols=list(frames),
        candle_loader=frames.__getitem__,
    )
    activity = [
        {"symbol": "BBB", "activity_score": 90, "sources": ["daily OHLCV"]},
        {"symbol": "ZZZ", "activity_score": 10, "sources": []},
    ]
    merged = merge_qlib_into_activity_rows(activity, panel)
    assert merged[0]["qlib_rank"] is not None
    assert merged[0]["qlib_score_kind"] == SCORE_KIND
    assert SOURCE_ID in merged[0]["sources"]
    assert merged[1]["qlib_rank"] is None  # ZZZ not scored
    assert merged[1]["qlib_score"] is None

    top = qlib_priority_symbols(panel, limit=2, allowed_symbols={"AAA", "BBB", "CCC"})
    assert len(top) == 2
    assert set(top) <= {"AAA", "BBB", "CCC"}


def test_feature_row_requires_history():
    short = _bars(periods=20)
    feats = feature_row_from_frame(short)
    assert all(v is None for v in feats.values())


def test_shared_panel_covers_late_alphabet_after_early_prime(tmp_path, monkeypatch):
    """Partial focus cache must not leave GIS/ZTS missing after AAPL primes."""
    clear_shared_qlib_panel()
    wide = tmp_path / "1d_wide"
    wide.mkdir()
    # Alphabetically early + late names (mirrors the skeptic bug).
    frames = {
        "AAPL": _bars(last_ret=-0.04, seed=1),
        "GIS": _bars(last_ret=0.03, seed=2),
        "ZTS": _bars(last_ret=-0.02, seed=3),
    }
    for sym, frame in frames.items():
        frame.to_parquet(wide / f"{sym}.parquet")

    monkeypatch.setattr(
        "edge.daily_plays.live_activity.load_market_symbol_catalog",
        lambda **_: ["AAPL", "GIS", "ZTS"],
    )

    # Poison the shared cache with a partial panel (old 220-slice behaviour).
    partial = score_cross_section_asof(
        symbols=["AAPL"],
        candle_loader=frames.__getitem__,
    )
    publish_shared_qlib_panel(partial)
    assert "GIS" not in (partial.get("by_symbol") or {})

    # Shared getter must rebuild to full catalog coverage.
    panel = get_shared_qlib_panel(
        data_dirs=(wide,),
        force_include=["GIS"],
        candle_loader=frames.__getitem__,
    )
    assert panel["quality"] == "ok"
    assert "AAPL" in panel["by_symbol"]
    assert "GIS" in panel["by_symbol"]
    assert "ZTS" in panel["by_symbol"]

    aapl = lookup_symbol_on_shared_panel("AAPL", data_dirs=(wide,), candle_loader=frames.__getitem__)
    gis = lookup_symbol_on_shared_panel("GIS", data_dirs=(wide,), candle_loader=frames.__getitem__)
    zts = lookup_symbol_on_shared_panel("ZTS", data_dirs=(wide,), candle_loader=frames.__getitem__)
    assert aapl["quality"] == "ok"
    assert gis["quality"] == "ok"
    assert zts["quality"] == "ok"
    assert isinstance(gis["qlib_rank"], int) and gis["qlib_rank"] >= 1
    assert isinstance(zts["qlib_rank"], int) and zts["qlib_rank"] >= 1
    # Same provenance for all three.
    assert aapl["source"] == gis["source"] == zts["source"]
    assert _ok_source(aapl["source"])
    assert aapl["score_kind"] == SCORE_KIND
    clear_shared_qlib_panel()


def test_published_deep_panel_matches_market_lookup(tmp_path, monkeypatch):
    clear_shared_qlib_panel()
    wide = tmp_path / "1d_wide"
    wide.mkdir()
    frames = {
        "AAPL": _bars(last_ret=-0.05, seed=4),
        "GIS": _bars(last_ret=0.02, seed=5),
        "ZTS": _bars(last_ret=-0.01, seed=6),
    }
    for sym, frame in frames.items():
        frame.to_parquet(wide / f"{sym}.parquet")
    monkeypatch.setattr(
        "edge.daily_plays.live_activity.load_market_symbol_catalog",
        lambda **_: list(frames),
    )

    deep_panel = score_cross_section_asof(
        symbols=list(frames),
        candle_loader=frames.__getitem__,
    )
    publish_shared_qlib_panel(deep_panel)

    for sym in frames:
        ctx = lookup_symbol_on_shared_panel(
            sym,
            data_dirs=(wide,),
            candle_loader=frames.__getitem__,
        )
        assert ctx["quality"] == "ok"
        assert ctx["qlib_rank"] == deep_panel["by_symbol"][sym]["qlib_rank"]
        assert ctx["qlib_score"] == deep_panel["by_symbol"][sym]["qlib_score"]
        assert ctx["source"] == deep_panel["source"]
        assert ctx["asof"] == deep_panel["by_symbol"][sym]["asof"]
    clear_shared_qlib_panel()
