from __future__ import annotations

import numpy as np
import pandas as pd

from edge.daily_plays.adaptive_signal import (
    AdaptiveSignalInputs,
    SCORE_KIND,
    adapt_weights,
    base_weights_for_regime,
    calendar_return,
    detect_bar_freq,
    scan_adaptive_signals,
    score_symbol,
    score_technical,
)


def _bars(*, end: float = 110.0, start: float = 100.0, n: int = 90, vol_spike: float = 1.0) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=n, freq="B")
    close = np.linspace(start, end, n)
    volume = np.full(n, 1_000_000.0)
    volume[-1] *= vol_spike
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_technical_scores_uptrend_positive():
    result = score_technical(_bars(start=100.0, end=118.0))
    assert result["quality"] == "ok"
    assert result["score"] is not None
    assert result["score"] > 0.1


def test_regime_weights_shift_in_high_vol_down():
    low_up = base_weights_for_regime({"volatility_regime": "LOW", "trend_regime": "UP"})
    high_down = base_weights_for_regime({"volatility_regime": "HIGH", "trend_regime": "DOWN"})
    assert abs(sum(low_up.values()) - 1.0) < 1e-9
    assert abs(sum(high_down.values()) - 1.0) < 1e-9
    assert high_down["sentiment"] > low_up["sentiment"]
    assert high_down["technical"] < low_up["technical"]


def test_online_adapt_boosts_winning_stream_with_floor():
    base = {"technical": 0.4, "sector": 0.2, "sentiment": 0.2, "fundamental": 0.2}
    adapted, mode = adapt_weights(
        base,
        stream_performance={"technical": 0.8, "sector": 0.3, "sentiment": 0.5, "fundamental": 0.5},
        present_streams=("technical", "sector", "sentiment", "fundamental"),
    )
    assert mode == "regime_map_plus_online_soft"
    assert adapted["technical"] > base["technical"] * 0.9
    assert min(adapted.values()) >= 0.08 - 1e-9
    assert abs(sum(adapted.values()) - 1.0) < 1e-9


def test_score_symbol_is_ordinal_not_authorized_and_adapts_to_sector():
    bull = score_symbol(
        AdaptiveSignalInputs(
            symbol="AAA",
            bars=_bars(start=100.0, end=120.0),
            sector_context={"flow_direction": "in", "rs_5d": 0.04, "sector_etf": "XLK"},
            market_sentiment={"risk_on_score": 0.4},
            fundamental_context={"pead_score": 0.3},
        )
    )
    assert bull["score_kind"] == SCORE_KIND
    assert bull["decision_authorized"] is False
    assert bull["live_capital_authorized"] is False
    assert bull["promotion_authorized"] is False
    assert bull["side"] == "long"
    assert bull["composite_score"] is not None and bull["composite_score"] > 0
    assert "technical" in bull["present_streams"]
    assert bull["weights"]["adaptation_mode"] in {"regime_map_only", "regime_map_plus_online_soft"}

    bearish_sector = score_symbol(
        AdaptiveSignalInputs(
            symbol="AAA",
            bars=_bars(start=100.0, end=120.0),
            sector_context={"flow_direction": "out", "rs_5d": -0.05, "sector_etf": "XLK"},
            market_sentiment={"risk_on_score": -0.5},
            fundamental_context={"short_ratio_z": 2.5},
        )
    )
    assert bearish_sector["composite_score"] < bull["composite_score"]


def test_calendar_return_works_on_hourly_bars():
    dates = pd.date_range("2025-06-01 09:30", periods=200, freq="h")
    close = np.linspace(100.0, 110.0, len(dates))
    series = pd.Series(close, index=dates)
    assert detect_bar_freq(dates) == "1h"
    ret = calendar_return(series, days=5)
    assert ret is not None and ret > 0


def test_score_symbol_uses_stream_performance_for_online_adapt():
    bull = score_symbol(
        AdaptiveSignalInputs(
            symbol="AAA",
            bars=_bars(start=100.0, end=120.0),
            market_sentiment={"risk_on_score": 0.2},
            stream_performance={"technical": 0.85, "sector": 0.4, "sentiment": 0.5, "fundamental": 0.55},
        )
    )
    assert bull["weights"]["adaptation_mode"] == "regime_map_plus_online_soft"
    assert bull["stream_performance_used"]["technical"] == 0.85


def test_scan_ranks_by_absolute_composite_without_probability_keys():
    frames = {
        "HOT": _bars(start=100.0, end=125.0),
        "FLAT": _bars(start=100.0, end=101.0),
        "COLD": _bars(start=100.0, end=88.0),
    }
    result = scan_adaptive_signals(
        symbols=list(frames),
        candle_loader=frames.__getitem__,
        market_sentiment={"risk_on_score": 0.1},
        row_limit=10,
    )
    assert result["coverage"]["scored"] == 3
    assert result["decision_authorized"] is False
    assert result["rows"][0]["attention_rank"] == 1
    assert abs(result["rows"][0]["composite_score"]) >= abs(result["rows"][1]["composite_score"])
    for row in result["rows"]:
        assert "probability" not in row
        assert row["score_kind"] == SCORE_KIND
