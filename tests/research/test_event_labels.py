"""Unit tests for research/event_labels.py -- crafted-path known-answer tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

try:
    from edge.research import event_labels as el
except ImportError:
    from research import event_labels as el


VOL_WINDOW = 6  # small so test bars stay short; needs VOL_WINDOW+1 warmup closes


def _warmup_closes(vol_window: int = VOL_WINDOW, start_price: float = 100.0) -> list[float]:
    """Deterministic alternating +/-2% returns -> a known, non-degenerate sigma."""
    prices = [start_price]
    for i in range(vol_window):
        r = 0.02 if i % 2 == 0 else -0.02
        prices.append(prices[-1] * (1.0 + r))
    return prices


def _expected_sigma(vol_window: int = VOL_WINDOW, start_price: float = 100.0) -> float:
    closes = _warmup_closes(vol_window, start_price)
    returns = pd.Series(closes).pct_change().dropna()
    return float(returns.std(ddof=1))


def _bars_from_ohlc(dates, opens, highs, lows, closes) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(dates),
    )


def _make_bars(forward_highs: list[float], forward_lows: list[float], forward_closes: list[float] | None = None, *, vol_window: int = VOL_WINDOW, start_price: float = 100.0) -> pd.DataFrame:
    """Warmup bars (deterministic sigma) followed by hand-crafted forward bars.

    Event t0 sits at position ``vol_window`` (0-indexed): exactly enough
    trailing closes for one fully-warmed sigma reading and nothing more.
    """
    warmup = _warmup_closes(vol_window, start_price)
    n_warmup = len(warmup)
    n_forward = len(forward_highs)
    dates = pd.bdate_range("2024-01-02", periods=n_warmup + n_forward)

    opens = list(warmup) + list(forward_closes if forward_closes is not None else forward_highs)
    closes = list(warmup) + list(forward_closes if forward_closes is not None else forward_highs)
    highs = list(warmup) + list(forward_highs)
    lows = list(warmup) + list(forward_lows)
    # warmup bars: open==high==low==close (only close matters pre-event)
    return _bars_from_ohlc(dates, opens, highs, lows, closes)


def _events_at(bars: pd.DataFrame, i: int, symbol: str = "TEST") -> pd.DataFrame:
    return pd.DataFrame({"symbol": [symbol], "t0": [bars.index[i]]})


# ---------------------------------------------------------------------------
# competing_barrier_labels -- crafted outcome paths
# ---------------------------------------------------------------------------

class TestCompetingBarrierLabelsOutcomes:
    def test_down_first(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        b_down = p0 * (1 - k_down * sigma)
        b_up = p0 * (1 + k_up * sigma)
        # bar+1: low dips just below b_down, high stays well under b_up
        highs = [p0 * 1.001, p0 * 1.001, p0 * 1.001, p0 * 1.001, p0 * 1.001]
        lows = [b_down - 0.01, p0 * 0.999, p0 * 0.999, p0 * 0.999, p0 * 0.999]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "DOWN_FIRST"
        assert row["time_to_hit"] == 1
        assert row["censored"] == False  # noqa: E712
        assert np.isclose(row["sigma_t0"], sigma)
        assert np.isclose(row["barrier_down"], b_down)
        assert np.isclose(row["barrier_up"], b_up)

    def test_up_first(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        b_down = p0 * (1 - k_down * sigma)
        b_up = p0 * (1 + k_up * sigma)
        highs = [p0 * 0.999, b_up + 0.01, p0 * 1.001, p0 * 1.001, p0 * 1.001]
        lows = [p0 * 0.999, p0 * 0.999, p0 * 0.999, p0 * 0.999, p0 * 0.999]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "UP_FIRST"
        assert row["time_to_hit"] == 2
        assert row["censored"] == False  # noqa: E712

    def test_neither(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        b_down = p0 * (1 - k_down * sigma)
        b_up = p0 * (1 + k_up * sigma)
        # stay strictly inside the barriers for the full horizon
        highs = [p0 * 1.001] * horizon
        lows = [p0 * 0.999] * horizon
        assert all(low > b_down for low in lows)
        assert all(high < b_up for high in highs)
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "NEITHER"
        assert pd.isna(row["time_to_hit"])
        assert row["censored"] == False  # noqa: E712
        assert not pd.isna(row["terminal_return"])

    def test_ambiguous_same_bar_both_hit(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        b_down = p0 * (1 - k_down * sigma)
        b_up = p0 * (1 + k_up * sigma)
        highs = [b_up + 0.01, p0, p0, p0, p0]
        lows = [b_down - 0.01, p0, p0, p0, p0]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "AMBIGUOUS"
        assert row["time_to_hit"] == 1
        assert pd.isna(row["mae"])
        assert pd.isna(row["mfe"])


# ---------------------------------------------------------------------------
# Trading-day counting (row position, not calendar days)
# ---------------------------------------------------------------------------

class TestTradingDayCounting:
    def test_time_to_hit_counts_rows_not_calendar_days(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 3
        b_down = p0 * (1 - k_down * sigma)

        warmup = _warmup_closes()
        n_warmup = len(warmup)
        # Irregular calendar gaps: a 4-calendar-day jump between forward
        # bar 1 and forward bar 2 (simulating a long weekend/holiday), but
        # the hit bar is only 2 ROWS after t0.
        base = pd.bdate_range("2024-01-02", periods=n_warmup)
        forward_dates = [
            base[-1] + pd.Timedelta(days=1),
            base[-1] + pd.Timedelta(days=6),  # big calendar gap, still row 2
            base[-1] + pd.Timedelta(days=7),
        ]
        dates = list(base) + forward_dates
        opens = list(warmup) + [p0, p0, p0]
        closes = list(warmup) + [p0, p0, p0]
        highs = list(warmup) + [p0 * 1.001, p0 * 1.001, p0 * 1.001]
        lows = list(warmup) + [p0 * 0.999, b_down - 0.01, p0 * 0.999]
        bars = _bars_from_ohlc(dates, opens, highs, lows, closes)

        i = n_warmup - 1
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        # row-position count: hit is the 2nd forward bar -> time_to_hit == 2,
        # NOT the ~7 calendar days between t0 and that bar's timestamp.
        assert row["outcome"] == "DOWN_FIRST"
        assert row["time_to_hit"] == 2
        calendar_days = (row.name and (dates[i + 2] - dates[i]).days) or (dates[i + 2] - dates[i]).days
        assert calendar_days > 2


# ---------------------------------------------------------------------------
# Censoring
# ---------------------------------------------------------------------------

class TestCensoring:
    def test_terminal_return_censored_at_end_of_data_when_no_hit(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        # only 2 forward bars exist even though horizon=5; neither hits.
        highs = [p0 * 1.001, p0 * 1.001]
        lows = [p0 * 0.999, p0 * 0.999]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] is None
        assert row["censored"] == True  # noqa: E712
        assert pd.isna(row["terminal_return"])
        assert pd.isna(row["time_to_hit"])

    def test_terminal_return_censored_even_when_hit_found_early(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 5
        b_down = p0 * (1 - k_down * sigma)
        # only 2 forward bars, but a DOWN hit occurs on the 1st -> outcome is
        # resolved even though terminal_return (t0+5) is unobservable.
        highs = [p0 * 1.001, p0 * 1.001]
        lows = [b_down - 0.01, p0 * 0.999]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "DOWN_FIRST"
        assert row["time_to_hit"] == 1
        assert pd.isna(row["terminal_return"])  # genuinely censored, not fabricated

    def test_insufficient_warmup_yields_missing_outcome(self):
        # Only 3 warmup bars for vol_window=6 -> sigma_t0 is NaN.
        dates = pd.bdate_range("2024-01-02", periods=3 + 5)
        closes = [100.0, 101.0, 99.5] + [99.5] * 5
        opens = highs = lows = closes
        bars = _bars_from_ohlc(dates, opens, highs, lows, closes)
        events = _events_at(bars, 2)
        labels = el.competing_barrier_labels(bars, events, 1.0, 1.0, 5, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] is None
        assert row["censored"] == True  # noqa: E712
        assert pd.isna(row["barrier_down"])
        assert pd.isna(row["barrier_up"])


# ---------------------------------------------------------------------------
# mae/mfe sign convention
# ---------------------------------------------------------------------------

class TestMaeMfe:
    def test_up_first_signs(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 3
        b_up = p0 * (1 + k_up * sigma)
        highs = [b_up + 0.01, p0 * 1.02, p0 * 1.0]
        lows = [p0 * 0.995, p0 * 0.99, p0 * 1.0]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "UP_FIRST"
        # mfe: best favorable (up) move over the window -> positive
        assert row["mfe"] > 0
        # mae: worst adverse (down) move over the window -> negative
        assert row["mae"] < 0

    def test_down_first_signs(self):
        sigma = _expected_sigma()
        p0 = _warmup_closes()[-1]
        k_down, k_up, horizon = 1.0, 1.0, 3
        b_down = p0 * (1 - k_down * sigma)
        highs = [p0 * 1.0, p0 * 1.02, p0 * 1.0]
        lows = [b_down - 0.01, p0 * 0.97, p0 * 1.0]
        bars = _make_bars(highs, lows)
        i = VOL_WINDOW
        events = _events_at(bars, i)
        labels = el.competing_barrier_labels(bars, events, k_down, k_up, horizon, vol_window=VOL_WINDOW)
        row = labels.iloc[0]
        assert row["outcome"] == "DOWN_FIRST"
        # mfe: best favorable (down) move -> negative (lower price is better)
        assert row["mfe"] < 0
        # mae: worst adverse (up) move -> positive
        assert row["mae"] > 0


# ---------------------------------------------------------------------------
# Validation / calling-convention errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_t0_column_raises(self):
        bars = _make_bars([100.0], [100.0])
        with pytest.raises(KeyError):
            el.competing_barrier_labels(bars, pd.DataFrame({"symbol": ["X"]}), 1.0, 1.0, 5)

    def test_multi_symbol_events_raises(self):
        bars = _make_bars([100.0] * 3, [100.0] * 3)
        events = pd.DataFrame({"symbol": ["A", "B"], "t0": [bars.index[VOL_WINDOW], bars.index[VOL_WINDOW]]})
        with pytest.raises(ValueError, match="one symbol"):
            el.competing_barrier_labels(bars, events, 1.0, 1.0, 5)

    def test_t0_not_in_bars_raises(self):
        bars = _make_bars([100.0] * 3, [100.0] * 3)
        events = pd.DataFrame({"symbol": ["X"], "t0": [pd.Timestamp("1999-01-01")]})
        with pytest.raises(KeyError):
            el.competing_barrier_labels(bars, events, 1.0, 1.0, 5)

    def test_invalid_params_raise(self):
        bars = _make_bars([100.0] * 3, [100.0] * 3)
        events = _events_at(bars, VOL_WINDOW)
        with pytest.raises(ValueError):
            el.competing_barrier_labels(bars, events, -1.0, 1.0, 5)
        with pytest.raises(ValueError):
            el.competing_barrier_labels(bars, events, 1.0, 1.0, 0)
        with pytest.raises(ValueError):
            el.competing_barrier_labels(bars, events, 1.0, 1.0, 5, vol_window=1)


# ---------------------------------------------------------------------------
# label_coverage_report
# ---------------------------------------------------------------------------

class TestLabelCoverageReport:
    def test_empty(self):
        report = el.label_coverage_report(pd.DataFrame(columns=["outcome", "terminal_return"]))
        assert report["n_events"] == 0
        assert report["class_balance"] == {}
        assert report["ambiguity_rate"] == 0.0
        assert report["censoring_rate"] == 0.0

    def test_mixed_classes(self):
        labels = pd.DataFrame({
            "outcome": ["DOWN_FIRST", "UP_FIRST", "NEITHER", "AMBIGUOUS", None],
            "terminal_return": [0.01, -0.02, 0.0, np.nan, np.nan],
        })
        report = el.label_coverage_report(labels)
        assert report["n_events"] == 5
        assert report["class_balance"] == {
            "DOWN_FIRST": 1, "UP_FIRST": 1, "NEITHER": 1, "AMBIGUOUS": 1, "MISSING": 1,
        }
        assert report["ambiguity_rate"] == pytest.approx(1 / 5)
        # censored = NEITHER (1) or terminal_return missing (AMBIGUOUS + MISSING rows = 2, no overlap here)
        assert report["censoring_rate"] == pytest.approx(3 / 5)
