"""Unit tests for research/matched_controls.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

try:
    from edge.research import matched_controls as mc
except ImportError:
    from research import matched_controls as mc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(symbols, n_days, *, seed=0, low_bucket_symbols=None):
    """Synthetic long panel with regime columns already attached."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    low_bucket_symbols = set(low_bucket_symbols or symbols)
    frames = []
    for sym in symbols:
        if sym in low_bucket_symbols:
            vol = rng.uniform(0.005, 0.015, size=n_days)
            vol_regime = np.array(["LOW"] * n_days)
            trend_regime = np.array(["UP"] * n_days)
        else:
            vol = rng.uniform(0.03, 0.05, size=n_days)
            vol_regime = np.array(["HIGH"] * n_days)
            trend_regime = np.array(["DOWN"] * n_days)
        frames.append(pd.DataFrame({
            "symbol": sym,
            "date": dates,
            "realized_volatility": vol,
            "volatility_regime": vol_regime,
            "trend_regime": trend_regime,
        }))
    return pd.concat(frames, ignore_index=True)


def _make_bars(n, *, start_price=100.0, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0002, 0.01, size=n)
    close = start_price * np.cumprod(1.0 + rets)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame({
        "open": close, "high": close * 1.005, "low": close * 0.995, "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, size=n).astype(float),
    }, index=idx)


# ---------------------------------------------------------------------------
# attach_regime_columns
# ---------------------------------------------------------------------------

class TestAttachRegimeColumns:
    def test_attaches_columns(self):
        bars = {"AAA": _make_bars(80, seed=1), "BBB": _make_bars(80, seed=2)}
        panel = pd.DataFrame({
            "symbol": ["AAA"] * 80 + ["BBB"] * 80,
            "date": list(bars["AAA"].index) + list(bars["BBB"].index),
        })
        merged = mc.attach_regime_columns(panel, bars, volatility_window=5, trend_window=10)
        for col in ("realized_volatility", "volatility_regime", "trend_regime"):
            assert col in merged.columns
        assert len(merged) == len(panel)
        # tail rows (past warmup) should be populated
        assert merged["volatility_regime"].notna().sum() > 0

    def test_missing_symbol_raises(self):
        bars = {"AAA": _make_bars(60)}
        panel = pd.DataFrame({"symbol": ["AAA", "ZZZ"], "date": [bars["AAA"].index[0]] * 2})
        with pytest.raises(KeyError):
            mc.attach_regime_columns(panel, bars)


# ---------------------------------------------------------------------------
# match_controls
# ---------------------------------------------------------------------------

class TestMatchControls:
    def test_exclusion_window_respected(self):
        panel = _make_panel(["A", "B", "C"], 60, seed=3)
        event_t0 = panel.loc[panel["symbol"] == "A", "date"].iloc[20]
        events = pd.DataFrame({"symbol": ["A"], "t0": [event_t0]})

        result = mc.match_controls(
            events, panel, n_controls=5, same_symbol_exclusion_days=10, seed=0,
        )
        same_symbol_rows = result.loc[result["control_symbol"] == "A"]
        for control_t0 in same_symbol_rows["control_t0"]:
            gap_days = abs((pd.Timestamp(control_t0) - pd.Timestamp(event_t0)).days)
            assert gap_days > 10

    def test_exclusion_applies_across_all_events_on_symbol(self):
        panel = _make_panel(["A", "B"], 80, seed=4)
        t0s = panel.loc[panel["symbol"] == "A", "date"].iloc[[10, 40]].tolist()
        events = pd.DataFrame({"symbol": ["A", "A"], "t0": t0s})

        result = mc.match_controls(events, panel, n_controls=3, same_symbol_exclusion_days=8, seed=1)
        same_symbol_rows = result.loc[result["control_symbol"] == "A"]
        for control_t0 in same_symbol_rows["control_t0"]:
            for t0 in t0s:
                gap_days = abs((pd.Timestamp(control_t0) - pd.Timestamp(t0)).days)
                assert gap_days > 8

    def test_regime_bucket_matching(self):
        panel = _make_panel(["A", "B", "C", "D"], 60, seed=5, low_bucket_symbols=["A", "B"])
        event_t0 = panel.loc[panel["symbol"] == "A", "date"].iloc[30]
        events = pd.DataFrame({"symbol": ["A"], "t0": [event_t0]})
        result = mc.match_controls(events, panel, n_controls=4, same_symbol_exclusion_days=5, seed=2)
        assert len(result) > 0
        assert (result["volatility_regime"] == "LOW").all()
        assert (result["trend_regime"] == "UP").all()
        # symbols C/D are HIGH/DOWN bucket -> must never appear as controls
        assert not result["control_symbol"].isin(["C", "D"]).any()

    def test_deterministic_given_seed(self):
        panel = _make_panel(["A", "B", "C"], 50, seed=6)
        event_t0 = panel.loc[panel["symbol"] == "A", "date"].iloc[25]
        events = pd.DataFrame({"symbol": ["A"], "t0": [event_t0]})
        r1 = mc.match_controls(events, panel, n_controls=3, seed=42)
        r2 = mc.match_controls(events, panel, n_controls=3, seed=42)
        pd.testing.assert_frame_equal(r1.reset_index(drop=True), r2.reset_index(drop=True))

    def test_missing_match_cols_raises(self):
        panel = pd.DataFrame({"symbol": ["A"], "date": [pd.Timestamp("2023-01-02")]})
        events = pd.DataFrame({"symbol": ["A"], "t0": [pd.Timestamp("2023-01-02")]})
        with pytest.raises(KeyError):
            mc.match_controls(events, panel)

    def test_falls_back_across_symbol_when_same_symbol_insufficient(self):
        # symbol A has almost every row excluded (events every 3 days), so
        # same-symbol candidates run out and B/C fill the remainder.
        panel = _make_panel(["A", "B", "C"], 60, seed=7)
        a_dates = panel.loc[panel["symbol"] == "A", "date"].tolist()
        many_events = pd.DataFrame({"symbol": ["A"] * len(a_dates[::3]), "t0": a_dates[::3]})
        target_event = pd.DataFrame({"symbol": ["A"], "t0": [a_dates[1]]})
        events = pd.concat([many_events, target_event], ignore_index=True)
        result = mc.match_controls(events, panel, n_controls=5, same_symbol_exclusion_days=20, seed=3)
        assert len(result) > 0
        # some fallback controls from other symbols should appear given how
        # aggressively symbol A's own dates are excluded.
        assert result["control_symbol"].isin(["B", "C"]).any() or len(result) < 5 * len(events)


# ---------------------------------------------------------------------------
# event_vs_control_stats
# ---------------------------------------------------------------------------

class TestEventVsControlStats:
    def test_paired_delta_and_bootstrap_shape(self):
        dates = pd.bdate_range("2023-02-01", periods=6)
        event_labels = pd.DataFrame({
            "symbol": ["A", "B", "C"],
            "t0": [dates[0], dates[1], dates[2]],
            "outcome": ["DOWN_FIRST", "UP_FIRST", "NEITHER"],
            "terminal_return": [-0.05, 0.03, 0.0],
        })
        control_labels = pd.DataFrame({
            "event_symbol": ["A", "A", "B", "B", "C", "C"],
            "event_t0": [dates[0], dates[0], dates[1], dates[1], dates[2], dates[2]],
            "outcome": ["NEITHER", "UP_FIRST", "NEITHER", "NEITHER", "NEITHER", "DOWN_FIRST"],
            "terminal_return": [0.0, 0.01, -0.01, 0.0, 0.0, 0.0],
        })
        stats = mc.event_vs_control_stats(event_labels, control_labels)
        assert stats["n_events"] == 3
        assert stats["n_controls"] == 6
        assert stats["n_paired"] == 3
        # event A: -0.05 - mean(0.0, 0.01) = -0.055
        # event B: 0.03 - mean(-0.01, 0.0) = 0.035
        # event C: 0.0 - mean(0.0, 0.0) = 0.0
        expected = np.mean([-0.05 - 0.005, 0.03 - (-0.005), 0.0 - 0.0])
        assert stats["delta_terminal_return"] == pytest.approx(expected)
        assert stats["bootstrap_ci"] is not None
        assert set(stats["bootstrap_ci"]) == {"estimate", "lower", "upper", "confidence", "n_dates", "block_size", "n_bootstrap"}
        assert np.isfinite(stats["newey_west_t"])

    def test_missing_columns_raise(self):
        with pytest.raises(KeyError):
            mc.event_vs_control_stats(pd.DataFrame({"symbol": ["A"]}), pd.DataFrame())

    def test_empty_pairing_yields_nan_without_raising(self):
        event_labels = pd.DataFrame({
            "symbol": ["A"], "t0": [pd.Timestamp("2023-01-02")],
            "outcome": ["NEITHER"], "terminal_return": [np.nan],
        })
        control_labels = pd.DataFrame({
            "event_symbol": ["A"], "event_t0": [pd.Timestamp("2023-01-02")],
            "outcome": ["NEITHER"], "terminal_return": [np.nan],
        })
        stats = mc.event_vs_control_stats(event_labels, control_labels)
        assert stats["n_paired"] == 0
        assert np.isnan(stats["delta_terminal_return"])
        assert stats["bootstrap_ci"] is None


# ---------------------------------------------------------------------------
# permutation_null -- coarse statistical smoke test under a null-true setup
# ---------------------------------------------------------------------------

class TestPermutationNull:
    def _null_true_panel_and_lookup(self, seed=0, n_days=50, symbols=("A", "B", "C")):
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range("2023-01-02", periods=n_days)
        frames = []
        for sym in symbols:
            frames.append(pd.DataFrame({
                "symbol": sym, "date": dates, "noise": rng.normal(size=n_days),
            }))
        panel = pd.concat(frames, ignore_index=True)
        lookup = panel.set_index(["symbol", "date"])["noise"]
        return panel, lookup

    def _make_stat_fn(self, lookup):
        def stat_fn(events: pd.DataFrame) -> float:
            vals = []
            for _, row in events.iterrows():
                key = (row["symbol"], pd.Timestamp(row["t0"]))
                if key in lookup.index:
                    v = lookup.loc[key]
                    vals.append(float(v.iloc[0]) if isinstance(v, pd.Series) else float(v))
            return float(np.mean(vals)) if vals else 0.0
        return stat_fn

    def test_roughly_uniform_pvalues_under_null(self):
        panel, lookup = self._null_true_panel_and_lookup(seed=11)
        rng = np.random.default_rng(99)
        a_dates = panel.loc[panel["symbol"] == "A", "date"].sample(3, random_state=1).tolist()
        b_dates = panel.loc[panel["symbol"] == "B", "date"].sample(2, random_state=2).tolist()
        events = pd.DataFrame({
            "symbol": ["A"] * 3 + ["B"] * 2,
            "t0": a_dates + b_dates,
        })
        stat_fn = self._make_stat_fn(lookup)

        p_values = []
        for seed in (1, 2, 3, 4, 5):
            result = mc.permutation_null(events, panel, stat_fn, n_perm=300, seed=seed)
            assert 0.0 <= result["p_value"] <= 1.0
            assert result["n_perm"] == 300
            p_values.append(result["p_value"])

        # coarse smoke check: under a genuinely null-true relationship, the
        # p-values should not be systematically crushed near 0.
        assert not all(p < 0.05 for p in p_values)
        assert any(p > 0.1 for p in p_values)

    def test_deterministic_given_seed(self):
        panel, lookup = self._null_true_panel_and_lookup(seed=22)
        events = pd.DataFrame({
            "symbol": ["A", "B"],
            "t0": [panel.loc[panel["symbol"] == "A", "date"].iloc[5],
                   panel.loc[panel["symbol"] == "B", "date"].iloc[10]],
        })
        stat_fn = self._make_stat_fn(lookup)
        r1 = mc.permutation_null(events, panel, stat_fn, n_perm=100, seed=7)
        r2 = mc.permutation_null(events, panel, stat_fn, n_perm=100, seed=7)
        assert r1 == r2

    def test_invalid_args_raise(self):
        panel, lookup = self._null_true_panel_and_lookup()
        events = pd.DataFrame({"symbol": ["A"], "t0": [panel["date"].iloc[0]]})
        stat_fn = self._make_stat_fn(lookup)
        with pytest.raises(ValueError):
            mc.permutation_null(events, panel, stat_fn, n_perm=0)


# ---------------------------------------------------------------------------
# deflate_grid_pvalues
# ---------------------------------------------------------------------------

class TestDeflateGridPvalues:
    def test_single_grid_point_no_reduction(self):
        result = mc.deflate_grid_pvalues([{"config": {"k": 1}, "p_value": 0.02}])
        assert result["raw_trial_count"] == 1
        assert result["effective_trial_count"] == pytest.approx(1.0)
        assert result["per_grid"][0]["deflated_p_value"] == pytest.approx(0.02)

    def test_perfectly_correlated_series_reduces_effective_trials(self):
        dates = pd.bdate_range("2023-01-02", periods=20)
        base = np.linspace(-0.01, 0.01, len(dates))
        grid_results = [
            {"config": {"k": i}, "p_value": 0.01, "paired_diff_series": list(base), "paired_dates": list(dates)}
            for i in range(3)
        ]
        result = mc.deflate_grid_pvalues(grid_results)
        assert result["raw_trial_count"] == 3
        # identical series across grid points -> effective trials well below 3
        assert result["effective_trial_count"] < 2.0
        for entry in result["per_grid"]:
            assert entry["deflated_p_value"] >= entry["raw_p_value"]

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            mc.deflate_grid_pvalues([])
