"""Market trajectory qlib context must cover the full catalog, not a 220-name slice."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.qlib_scan_score import (
    SCORE_KIND,
    clear_shared_qlib_panel,
    publish_shared_qlib_panel,
    score_cross_section_asof,
)


def _bars(
    *,
    seed: int,
    last_ret: float,
    end: str,
    periods: int = 280,
) -> pd.DataFrame:
    """Synthetic OHLCV ending on ``end`` (staggerable last bars)."""
    rng = np.random.default_rng(seed)
    end_ts = pd.Timestamp(end)
    dates = pd.bdate_range(end=end_ts, periods=periods)
    rets = rng.normal(0.0004, 0.012, size=periods)
    rets[-1] = last_ret
    close = 80.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
        },
        index=dates,
    )


@pytest.fixture()
def wide_catalog(tmp_path, monkeypatch):
    """Mini wide catalog with staggered last dates (real-data shape)."""
    clear_shared_qlib_panel()
    wide = tmp_path / "1d_wide"
    core = tmp_path / "1d"
    wide.mkdir()
    core.mkdir()

    # AAPL ends later than GIS/ZTS — matches the skeptic failure mode where
    # trajectory used win.last_date per symbol and re-cut the cross-section.
    frames = {
        "AAPL": _bars(seed=1, last_ret=-0.05, end="2026-07-31"),
        "GIS": _bars(seed=2, last_ret=0.03, end="2026-07-29"),
        "ZTS": _bars(seed=3, last_ret=-0.02, end="2026-07-29"),
    }
    assert frames["AAPL"].index[-1] > frames["GIS"].index[-1]
    assert frames["AAPL"].index[-1] > frames["ZTS"].index[-1]

    for sym, frame in frames.items():
        frame.to_parquet(wide / f"{sym}.parquet")

    import edge.tools.api_server as api

    monkeypatch.setattr(api, "DATA_WIDE_DIR", wide)
    monkeypatch.setattr(api, "DATA_CORE_DIR", core)
    monkeypatch.setattr(
        "edge.daily_plays.live_activity.load_market_symbol_catalog",
        lambda **_: list(frames),
    )
    # Clear trajectory df cache if present.
    if hasattr(api, "_DF_CACHE"):
        api._DF_CACHE.clear()
    yield {"wide": wide, "frames": frames, "api": api}
    clear_shared_qlib_panel()


def test_trajectory_qlib_after_aapl_still_scores_gis_and_zts(wide_catalog):
    api = wide_catalog["api"]

    aapl = api._trajectory_qlib_context("AAPL")
    assert aapl["quality"] == "ok"
    assert aapl["score_kind"] == SCORE_KIND
    assert isinstance(aapl["qlib_rank"], int)

    gis = api._trajectory_qlib_context("GIS")
    zts = api._trajectory_qlib_context("ZTS")
    assert gis["quality"] == "ok", gis
    assert zts["quality"] == "ok", zts
    assert isinstance(gis["qlib_rank"], int) and gis["qlib_rank"] >= 1
    assert isinstance(zts["qlib_rank"], int) and zts["qlib_rank"] >= 1
    assert math.isfinite(float(gis["qlib_score"]))
    assert math.isfinite(float(zts["qlib_score"]))
    assert aapl["source"] == gis["source"] == zts["source"]
    assert aapl["score_kind"] == gis["score_kind"] == zts["score_kind"] == SCORE_KIND


def test_staggered_last_dates_do_not_change_ranks_after_deep_publish(wide_catalog):
    """Real trajectory path: each symbol has its own last bar; ranks must match deep."""
    api = wide_catalog["api"]
    frames = wide_catalog["frames"]

    # Deep scan uses asof=None (latest available bar per name) then publishes.
    deep = score_cross_section_asof(
        symbols=list(frames),
        asof=None,
        candle_loader=frames.__getitem__,
    )
    publish_shared_qlib_panel(deep)
    assert deep["quality"] == "ok"

    # Simulate the OLD buggy call shape: pass each symbol's own last date.
    # After the fix, match_asof=False means ranks stay identical to deep.
    for sym, frame in frames.items():
        local_last = frame.index[-1].strftime("%Y-%m-%d")
        ctx = api._trajectory_qlib_context(sym, asof=local_last)
        assert ctx["quality"] == "ok", (sym, ctx)
        assert ctx["qlib_rank"] == deep["by_symbol"][sym]["qlib_rank"], (
            f"{sym}: traj rank {ctx['qlib_rank']} != deep {deep['by_symbol'][sym]['qlib_rank']}"
        )
        assert ctx["qlib_score"] == deep["by_symbol"][sym]["qlib_score"]
        assert ctx["source"] == deep["source"]
        assert ctx["asof"] == deep["by_symbol"][sym]["asof"]


def test_real_trajectory_payload_agrees_with_deep_on_staggered_ends(wide_catalog):
    """Drive _trajectory_payload (the shipped Market entry) after deep publish."""
    api = wide_catalog["api"]
    frames = wide_catalog["frames"]

    deep = score_cross_section_asof(
        symbols=list(frames),
        asof=None,
        candle_loader=frames.__getitem__,
    )
    publish_shared_qlib_panel(deep)

    for sym in frames:
        payload, status = api._trajectory_payload(sym, "1y")
        assert status == 200, payload
        assert payload["qlib_quality"] == "ok"
        assert payload["qlib_rank"] == deep["by_symbol"][sym]["qlib_rank"]
        assert payload["qlib_score"] == deep["by_symbol"][sym]["qlib_score"]
        assert payload["qlib_source"] == deep["source"]
        assert payload["qlib_score_kind"] == SCORE_KIND
        # Payload still reports the symbol's own series last_date (may differ).
        assert payload["last_date"] == frames[sym].index[-1].strftime("%Y-%m-%d")


def test_trajectory_matches_deep_panel_ranks(wide_catalog):
    api = wide_catalog["api"]
    frames = wide_catalog["frames"]

    deep = score_cross_section_asof(
        symbols=list(frames),
        asof=None,
        candle_loader=frames.__getitem__,
    )
    publish_shared_qlib_panel(deep)

    for sym in frames:
        ctx = api._trajectory_qlib_context(sym)
        assert ctx["quality"] == "ok"
        assert ctx["qlib_rank"] == deep["by_symbol"][sym]["qlib_rank"]
        assert ctx["qlib_score"] == deep["by_symbol"][sym]["qlib_score"]
        assert ctx["source"] == deep["source"]
        assert ctx["asof"] == deep["by_symbol"][sym]["asof"]


def test_trajectory_missing_symbol_is_explicit(wide_catalog):
    api = wide_catalog["api"]
    ctx = api._trajectory_qlib_context("ZZZZNOTATICKER")
    assert ctx["quality"] == "missing"
    assert ctx["qlib_rank"] is None
    assert ctx["qlib_score"] is None
    assert ctx["score_kind"] == SCORE_KIND
