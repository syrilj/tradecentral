from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from edge.daily_plays.stream_hit_rates import (
    ShadowRealizedEvent,
    load_v90_shadow_events,
    rolling_stream_hit_rates,
    stream_hit_for_event,
)


def _bars(*, end: float, start: float = 100.0, n: int = 120, freq: str = "B") -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=n, freq=freq)
    close = np.linspace(start, end, n)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=dates,
    )


def test_load_v90_shadow_events_skips_unrealized(tmp_path: Path):
    path = tmp_path / "shadow_decisions.jsonl"
    rows = [
        {
            "symbol": "AAA",
            "side": "BUY",
            "asof_bar": "2025-06-02 15:30:00",
            "realized": {"net_return": 0.02, "win": True},
        },
        {
            "symbol": "BBB",
            "side": "BUY",
            "asof_bar": "2025-06-03 15:30:00",
            "realized": None,
        },
        {
            "symbol": "CCC",
            "side": "SELL",
            "asof_bar": "2025-06-04 15:30:00",
            "realized": {"net_return": -0.01, "win": False},
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    events = load_v90_shadow_events(path)
    assert len(events) == 2
    assert events[0].side == "long" and events[0].win is True
    assert events[1].side == "short" and events[1].win is False


def test_stream_hit_technical_agrees_with_winning_long():
    # Strong uptrend bars; decision near the end; long won → technical should hit.
    frame = _bars(start=100.0, end=130.0, n=100)
    event = ShadowRealizedEvent(
        symbol="AAA",
        side="long",
        asof=pd.Timestamp(frame.index[-1]),
        win=True,
        net_return=0.05,
        source="test",
    )
    hits = stream_hit_for_event(event, bars=frame)
    assert hits["technical"] is True


def test_rolling_hit_rates_require_min_events_and_feed_performance_map():
    frame = _bars(start=100.0, end=125.0, n=100)
    events = [
        ShadowRealizedEvent(
            symbol="AAA",
            side="long",
            asof=pd.Timestamp(frame.index[-1]),
            win=True,
            net_return=0.03,
            source="test",
        )
        for _ in range(12)
    ]
    payload = rolling_stream_hit_rates(
        events,
        candle_loader=lambda _s: frame,
        lookback_events=20,
        min_events=8,
    )
    assert payload["decision_authorized"] is False
    assert "technical" in payload["stream_performance"]
    assert 0.0 <= payload["stream_performance"]["technical"] <= 1.0
    assert payload["stream_counts"]["technical"] >= 8
