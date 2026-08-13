"""Unit and property tests for Desk regime-conditioned multi-stream fusion."""
from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.adaptive_signal import (
    AdaptiveSignalInputs,
    score_symbol,
    scan_adaptive_signals,
    STREAM_NAMES,
)


def _make_mock_bars(n: int = 100, trend: float = 0.001, vol: float = 0.01) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = rng.normal(loc=trend, scale=vol, size=n)
    close = 100.0 * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.002, size=n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.002, size=n)))
    volume = rng.integers(1_000_000, 5_000_000, size=n).astype(float)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def test_score_symbol_basic_structure():
    bars = _make_mock_bars(60)
    inputs = AdaptiveSignalInputs(symbol="NVDA", bars=bars)
    result = score_symbol(inputs)
    assert result["symbol"] == "NVDA"
    assert result["schema_version"] == "adaptive-live-signal-v1"
    assert result["state"] in ("WATCH", "ABSTAIN")
    assert result["side"] in ("long", "short", "neutral")
    assert "streams" in result
    for stream in STREAM_NAMES:
        assert stream in result["streams"]


def test_long_gamma_dampens_technical_breakout():
    bars = _make_mock_bars(60, trend=0.005)
    
    # Baseline without options context
    res_base = score_symbol(AdaptiveSignalInputs(symbol="SPY", bars=bars))
    base_tech_score = res_base["streams"]["technical"]["score"]
    
    # Long gamma regime (market makers dampen volatility)
    res_dampened = score_symbol(AdaptiveSignalInputs(
        symbol="SPY",
        bars=bars,
        options_context={"gex_regime": "long_gamma", "long_gamma_dampened": True},
    ))
    dampened_tech_score = res_dampened["streams"]["technical"]["score"]
    
    if base_tech_score is not None and abs(base_tech_score) > 0.01:
        assert abs(dampened_tech_score) < abs(base_tech_score)
        assert res_dampened["options_context"]["long_gamma_dampened"] is True
        assert "dealer_long_gamma_dampened" in res_dampened["reasons"]


def test_short_gamma_amplifies_aligned_squeeze():
    bars = _make_mock_bars(60, trend=0.005)
    
    # Baseline
    res_base = score_symbol(AdaptiveSignalInputs(symbol="TSLA", bars=bars))
    base_tech = res_base["streams"]["technical"]["score"]
    
    # Short gamma + high squeeze score aligned with direction
    res_amp = score_symbol(AdaptiveSignalInputs(
        symbol="TSLA",
        bars=bars,
        options_context={"gex_regime": "short_gamma", "squeeze_score": 25.0},
    ))
    amp_tech = res_amp["streams"]["technical"]["score"]
    
    if base_tech is not None and base_tech > 0:
        assert amp_tech >= base_tech
        assert res_amp["options_context"]["squeeze_amplified"] is True
        assert "dealer_short_gamma_amplified" in res_amp["reasons"]


def test_scan_adaptive_signals_ranks_by_composite():
    bars_nvda = _make_mock_bars(60, trend=0.008)
    bars_msft = _make_mock_bars(60, trend=0.0001)
    
    candle_dict = {"NVDA": bars_nvda, "MSFT": bars_msft}
    scan = scan_adaptive_signals(
        symbols=["NVDA", "MSFT"],
        candle_loader=lambda sym: candle_dict[sym],
    )
    assert "rows" in scan
    assert len(scan["rows"]) == 2
    assert scan["rows"][0]["attention_rank"] == 1
    assert scan["rows"][1]["attention_rank"] == 2
