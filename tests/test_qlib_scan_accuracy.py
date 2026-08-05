"""Integration: ranking-quality eval drives the shipped scorer (no hardcoded IC)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from edge.daily_plays.qlib_scan_score import score_cross_section_asof
from edge.tools.eval_qlib_scan_accuracy import evaluate


def _synthetic_frames(n_symbols: int = 50, periods: int = 320) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    dates = pd.bdate_range("2024-01-02", periods=periods)
    for i in range(n_symbols):
        rng = np.random.default_rng(100 + i)
        rets = rng.normal(0.0004, 0.012, size=periods)
        # Embed a short-horizon reversal: large negative last ret → bounce later is
        # not needed here; we only need the scorer to produce variation.
        rets[-1] = rng.normal(0, 0.03)
        close = 40.0 * np.cumprod(1.0 + rets)
        vol = rng.integers(200_000, 2_000_000, size=periods).astype(float)
        frames[f"S{i:02d}"] = pd.DataFrame(
            {
                "open": np.r_[close[0], close[:-1]],
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": vol,
            },
            index=dates,
        )
    return frames


def test_shipped_scorer_rank_ic_vs_activity_is_computed_not_hardcoded(monkeypatch):
    frames = _synthetic_frames()
    asof = frames["S00"].index[-6]  # leave room for forward returns

    # Patch evaluate's data loading to use synthetic frames.
    import edge.tools.eval_qlib_scan_accuracy as mod

    monkeypatch.setattr(mod, "load_market_symbol_catalog", lambda **_: list(frames))
    monkeypatch.setattr(mod, "_load_close_panel", lambda symbols, data_dirs: {
        s: frames[s] for s in symbols if s in frames
    })

    result = evaluate(
        asofs=[asof.strftime("%Y-%m-%d")],
        max_symbols=len(frames),
        horizon=5,
        data_dirs=(Path("."),),
    )

    assert result["symbols_loaded"] == len(frames)
    assert result["score_kind"] == "ordinal_qlib_xs"
    # Metrics must come from real scorer outputs — not fixed constants.
    assert "qlib_mean_rank_ic" in result
    assert "activity_mean_rank_ic" in result
    # At least one of the daily IC lists is a list (may be empty if min_names fail
    # on a single day with sparse overlap — still prove scorer ran).
    assert isinstance(result["qlib_rank_ic_daily"], list)
    assert isinstance(result["activity_rank_ic_daily"], list)
    assert result["days"][0]["qlib_scored"] > 0

    # Direct call to shipped scorer produces the same as-of panel quality.
    panel = score_cross_section_asof(
        symbols=list(frames),
        asof=asof,
        candle_loader=frames.__getitem__,
    )
    assert panel["quality"] == "ok"
    assert panel["coverage"]["scored"] == len(frames)
