from __future__ import annotations

import pandas as pd
import pytest

from edge.tools import momentum_scan as ms


def _ohlcv(closes, volumes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )


def test_compute_rvol_basic():
    volumes = pd.Series([100_000] * 50 + [600_000])
    assert ms.compute_rvol(volumes) == pytest.approx(6.0)


def test_compute_rvol_insufficient_history():
    volumes = pd.Series([100_000] * 30)
    assert ms.compute_rvol(volumes) is None


def test_compute_gap_pct():
    assert ms.compute_gap_pct(11.0, 10.0) == pytest.approx(0.10)


def test_price_qualifies_band_edges():
    assert ms.price_qualifies(2.00) is True
    assert ms.price_qualifies(20.00) is True
    assert ms.price_qualifies(1.99) is False
    assert ms.price_qualifies(20.01) is False


def test_float_badge_thresholds():
    assert ms.float_badge(None) == "unknown"
    assert ms.float_badge(2_000_000) == "optimal"
    assert ms.float_badge(10_000_000) == "qualifies"
    assert ms.float_badge(50_000_000) == "no"


def test_build_candidate_unknown_float_never_silently_passes_or_fails():
    closes = [10.0] * 50 + [12.0]
    volumes = [100_000] * 50 + [700_000]
    opens = [10.0] * 50 + [11.5]
    df = _ohlcv(closes, volumes, opens)
    candidate = ms.build_candidate("TEST", df, None)
    assert candidate["float_shares"] is None
    assert candidate["float_badge"] == "unknown"
    assert candidate["price_qualifies"] is True
    assert candidate["gap_qualifies"] is True
    assert candidate["rvol_qualifies"] is True


def test_build_candidate_insufficient_history_returns_none():
    df = _ohlcv([10.0] * 20, [100_000] * 20)
    assert ms.build_candidate("TEST", df, None) is None


def test_rank_candidates_sorts_by_rvol_desc_and_drops_non_qualifying():
    records = [
        {"symbol": "A", "rvol": 6.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": True},
        {"symbol": "B", "rvol": 9.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": True},
        {"symbol": "C", "rvol": 20.0, "price_qualifies": True, "gap_qualifies": True, "rvol_qualifies": False},
    ]
    ranked = ms.rank_candidates(records)
    assert [r["symbol"] for r in ranked] == ["B", "A"]


def test_build_momentum_scan_reports_universe_and_float_coverage():
    closes = [10.0] * 50 + [12.0]
    volumes = [100_000] * 50 + [700_000]
    opens = [10.0] * 50 + [11.5]
    price_data = {
        "AAA": _ohlcv(closes, volumes, opens),
        "BBB": _ohlcv(closes, volumes, opens),
    }
    float_data = {"AAA": 5_000_000, "BBB": None}
    result = ms.build_momentum_scan(price_data, float_data, expected_universe_size=5000)
    assert result["universe_size"] == 2
    assert result["expected_universe_size"] == 5000
    assert result["float_coverage_pct"] == pytest.approx(50.0)
    assert len(result["candidates"]) == 2


def test_build_momentum_scan_zero_candidates_is_not_an_error():
    flat = _ohlcv([10.0] * 51, [100_000] * 51)
    result = ms.build_momentum_scan({"FLAT": flat}, {"FLAT": None}, expected_universe_size=1)
    assert result["candidates"] == []
    assert result["universe_size"] == 1
