"""Tests for the order-flow absorption matrix (daily_plays.absorption.build_orderflow_matrix)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.daily_plays.absorption import (
    AbsorptionConfig,
    OrderflowMatrixConfig,
    build_orderflow_matrix,
    detect_absorption_series,
    observations_from_bars,
)


def _bars(n=260, base=100.0):
    """Gently trending frame with realistic ranges and volumes."""
    rng = np.random.default_rng(7)
    closes = base + np.cumsum(rng.normal(0.02, 1.0, n))
    opens = closes - rng.normal(0.0, 0.4, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.2, 1.2, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.2, 1.2, n)
    volumes = rng.uniform(800, 1200, n) * 1000
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


def test_matrix_shape_and_invariants():
    bars = _bars()
    cfg = OrderflowMatrixConfig(bins=20, lookback=200)
    m = build_orderflow_matrix(bars, cfg=cfg)

    assert m["available"] is True
    assert m["window_bars"] == 200
    assert m["bins_used"] == 20
    assert len(m["bins"]) == 20
    assert m["window_low"] < m["poc"] < m["window_high"]
    # VAL <= POC <= VAH by construction.
    assert m["val"] <= m["poc"] <= m["vah"]

    # Buy/sell split sums to total in every bin and overall. Output numbers
    # are rounded to 2 decimals for the wire, so totals tolerate one rounding
    # unit per bin.
    round_tol = 0.005 * m["bins_used"] + 1e-6
    for b in m["bins"]:
        # buy and sell are rounded independently, so the split can drift two
        # rounding units from the rounded total.
        assert abs(b["buy"] + b["sell"] - b["total"]) < 0.02
    assert abs(sum(b["total"] for b in m["bins"]) - bars.tail(200)["volume"].sum()) < round_tol

    p = m["pressure"]
    assert -100 <= p["score"] <= 100
    assert p["regime"] in ("ACCUM", "DISTRIB", "BALANCED")
    assert abs(p["buy_share"] + p["sell_share"] - 1.0) < 1e-6


def test_matrix_aligns_with_detector_readouts():
    bars = _bars()
    readouts = detect_absorption_series(observations_from_bars(bars), AbsorptionConfig())
    m = build_orderflow_matrix(bars, readouts)
    assert m["available"] is True
    # ATR comes straight from the last readout when readouts are aligned.
    assert abs(m["atr"] - readouts[-1].atr) < 1e-3
    # Deltas in the window sum to the window's net flow (within one rounding
    # unit per bin -- bin deltas are rounded to 2 decimals for the wire).
    win = readouts[-m["window_bars"]:]
    assert abs(sum(b["delta"] for b in m["bins"]) - sum(r.net_flow for r in win)) < 0.005 * m["bins_used"] + 1e-6


def test_matrix_wick_absorption_concentrates_at_extremes():
    # 60 bars where every bar has a dominant upper wick: aggressive buying
    # absorbed at the highs. Absorption must stack in the top bin.
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    closes = np.full(n, 100.0)
    bars = pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 102.0),
            "low": np.full(n, 99.8),
            "close": closes,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )
    m = build_orderflow_matrix(bars, cfg=OrderflowMatrixConfig(bins=10, lookback=n))
    assert m["available"] is True
    absorb_top = m["bins"][-1]["absorption"]
    absorb_rest = sum(b["absorption"] for b in m["bins"][:-1])
    assert absorb_top > 0
    assert absorb_rest == 0


def test_matrix_zones_rank_poc_first_on_pinned_volume():
    # Volume pinned at one price level -> that level is POC and the top zone.
    n = 80
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    base = _bars(n)
    pinned = base.copy()
    # Flatten half the window's bars into a single tight range with big volume.
    pinned.iloc[:40, pinned.columns.get_loc("open")] = 100.0
    pinned.iloc[:40, pinned.columns.get_loc("close")] = 100.1
    pinned.iloc[:40, pinned.columns.get_loc("high")] = 100.5
    pinned.iloc[:40, pinned.columns.get_loc("low")] = 99.7
    pinned.iloc[:40, pinned.columns.get_loc("volume")] = 5_000_000.0
    m = build_orderflow_matrix(pinned, cfg=OrderflowMatrixConfig(bins=20, lookback=n))
    assert m["available"] is True
    assert abs(m["poc"] - 100.1) < (m["window_high"] - m["window_low"]) / 20
    if m["zones"]:
        assert abs(m["zones"][0]["mid"] - 100.1) < (m["window_high"] - m["window_low"]) / 20


def test_matrix_degenerate_inputs_are_explicit_not_fabricated():
    idx = pd.date_range("2026-01-01", periods=3, freq="h")
    tiny = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100.0}, index=idx
    )
    m = build_orderflow_matrix(tiny)
    assert m["available"] is False
    assert m["bins"] == []
    assert m["poc"] is None
    assert m["pressure"] is None

    # Zero-range frame (all identical prices) with enough bars.
    idx = pd.date_range("2026-01-01", periods=30, freq="h")
    flat = pd.DataFrame(
        {"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0, "volume": 10.0}, index=idx
    )
    m2 = build_orderflow_matrix(flat)
    assert m2["available"] is False
