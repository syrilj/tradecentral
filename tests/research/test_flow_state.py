"""Unit tests for research/flow_state.py (+ flow_state_panel.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

try:
    from edge.research import flow_state as fs
    from edge.research import flow_state_panel as fsp
except ImportError:
    from research import flow_state as fs
    from research import flow_state_panel as fsp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bars(opens, highs, lows, closes, volumes, *, start="2024-01-02", freq="B"):
    n = len(opens)
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


def _flat_features(n: int, cfg: fs.FlowStateConfig, *, start="2024-01-02", freq="B") -> pd.DataFrame:
    """A neutral features frame (NORMAL everywhere) that tests mutate in place."""
    idx = pd.date_range(start, periods=n, freq=freq)
    persistence_col = f"flow_persistence_{cfg.pressure_persistence_window}d"
    return pd.DataFrame(
        {
            "flow_z": 0.0,
            "amihud_shock": 0.0,
            persistence_col: 0,
            "dist_to_barrier_atr": 10.0,
            "barrier_high_mass": False,
            "barrier_break_direction": 0,
            "air_pocket_break": 0.0,
            "volume_ratio": 1.0,
            "range_compression": 1.0,
            "signed_flow_sign": 0,
        },
        index=idx,
    )


def _set(f: pd.DataFrame, i: int, **kwargs) -> None:
    for k, v in kwargs.items():
        f.iloc[i, f.columns.get_loc(k)] = v


# ---------------------------------------------------------------------------
# TestSignedVolumeProxy
# ---------------------------------------------------------------------------

class TestSignedVolumeProxy:
    def test_known_answer(self):
        bars = _bars(
            opens=[10, 10, 10],
            highs=[12, 10, 11],
            lows=[8, 10, 9],
            closes=[11, 10, 10],
            volumes=[100, 50, 200],
        )
        result = fs.signed_volume_proxy(bars)
        # row0: clv=(2*11-12-8)/(12-8)=0.5 * 100 = 50
        # row1: high == low -> 0, not NaN
        # row2: clv=(2*10-11-9)/(11-9)=0 * 200 = 0
        assert result.iloc[0] == pytest.approx(50.0)
        assert result.iloc[1] == pytest.approx(0.0)
        assert result.iloc[2] == pytest.approx(0.0)
        assert not result.isna().any()

    def test_zero_range_is_safe_not_nan_or_inf(self):
        bars = _bars(opens=[5], highs=[5], lows=[5], closes=[5], volumes=[1000])
        result = fs.signed_volume_proxy(bars)
        assert result.iloc[0] == 0.0
        assert np.isfinite(result.iloc[0])

    def test_rejects_non_ascending_index(self):
        bars = _bars(opens=[1, 1], highs=[2, 2], lows=[0, 0], closes=[1, 1], volumes=[1, 1])
        bars = bars.iloc[::-1]
        with pytest.raises(ValueError):
            fs.signed_volume_proxy(bars)

    def test_rejects_duplicate_index(self):
        idx = pd.DatetimeIndex(["2024-01-02", "2024-01-02"])
        bars = pd.DataFrame(
            {"open": [1, 1], "high": [2, 2], "low": [0, 0], "close": [1, 1], "volume": [1, 1]},
            index=idx,
        )
        with pytest.raises(ValueError):
            fs.signed_volume_proxy(bars)

    def test_missing_column_raises_keyerror(self):
        bad = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1]})
        with pytest.raises(KeyError):
            fs.signed_volume_proxy(bad)


# ---------------------------------------------------------------------------
# TestFlowZ / robust z warm-up
# ---------------------------------------------------------------------------

class TestFlowZ:
    def test_warmup_is_nan_before_window(self):
        flow = pd.Series(np.arange(30, dtype=float), index=pd.date_range("2024-01-02", periods=30, freq="B"))
        z = fs.flow_z(flow, window=10)
        assert z.iloc[:9].isna().all()
        assert z.iloc[9:].notna().all()

    def test_constant_series_yields_nan_not_inf(self):
        # MAD == 0 for a constant series -> scaled MAD 0 -> z is NaN, not inf.
        flow = pd.Series([5.0] * 15, index=pd.date_range("2024-01-02", periods=15, freq="B"))
        z = fs.flow_z(flow, window=5)
        valid = z.iloc[4:]
        assert not np.isinf(valid).any()
        assert valid.isna().all()

    def test_known_robust_z(self):
        # window of [1,2,3,4,5]: median=3, MAD=median(|1-3|,|2-3|,|3-3|,|4-3|,|5-3|)=median(2,1,0,1,2)=1
        # scaled_mad = 1.4826; current value (last in window) = 5 -> z=(5-3)/1.4826
        flow = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=pd.date_range("2024-01-02", periods=5, freq="B"))
        z = fs.flow_z(flow, window=5)
        assert z.iloc[-1] == pytest.approx((5.0 - 3.0) / 1.4826, rel=1e-6)

    def test_window_too_small_raises(self):
        flow = pd.Series([1.0, 2.0], index=pd.date_range("2024-01-02", periods=2, freq="B"))
        with pytest.raises(ValueError):
            fs.flow_z(flow, window=1)


# ---------------------------------------------------------------------------
# TestHourlySeasonalAdjust
# ---------------------------------------------------------------------------

class TestHourlySeasonalAdjust:
    def test_subtracts_trailing_hour_median(self):
        idx = pd.DatetimeIndex([
            "2024-01-02 09:00", "2024-01-02 10:00",
            "2024-01-03 09:00", "2024-01-03 10:00",
            "2024-01-04 09:00",
        ])
        series = pd.Series([10.0, 20.0, 14.0, 22.0, 16.0], index=idx)
        adjusted = fs.hourly_seasonal_adjust(series)
        # hour=9 bucket: [10, 14, 16] -> expanding median at each point: 10, 12, 14
        assert adjusted.iloc[0] == pytest.approx(10.0 - 10.0)
        assert adjusted.iloc[2] == pytest.approx(14.0 - 12.0)
        assert adjusted.iloc[4] == pytest.approx(16.0 - 14.0)
        # hour=10 bucket: [20, 22] -> expanding median: 20, 21
        assert adjusted.iloc[1] == pytest.approx(20.0 - 20.0)
        assert adjusted.iloc[3] == pytest.approx(22.0 - 21.0)

    def test_only_uses_past_and_current_hour_bucket(self):
        # mutating a later same-hour observation must not change an earlier one
        idx = pd.DatetimeIndex(["2024-01-02 09:00", "2024-01-03 09:00", "2024-01-04 09:00"])
        base = pd.Series([10.0, 12.0, 14.0], index=idx)
        mutated = base.copy()
        mutated.iloc[2] = 999.0
        adj_base = fs.hourly_seasonal_adjust(base)
        adj_mutated = fs.hourly_seasonal_adjust(mutated)
        assert adj_base.iloc[0] == pytest.approx(adj_mutated.iloc[0])
        assert adj_base.iloc[1] == pytest.approx(adj_mutated.iloc[1])


# ---------------------------------------------------------------------------
# TestFlowPersistence
# ---------------------------------------------------------------------------

class TestFlowPersistence:
    def test_known_answer_same_sign_counts(self):
        # threshold=1.0; window=3
        z = pd.Series([2.0, 2.5, -3.0, 3.0, 3.5], index=pd.date_range("2024-01-02", periods=5, freq="B"))
        result = fs.flow_persistence(z, threshold=1.0, windows=(3,))
        # t=2 (value -3.0): window [2.0, 2.5, -3.0]; current sign=-1; only -3.0 matches -> count 1
        assert result["persistence_3d"].iloc[2] == 1
        # t=3 (value 3.0): window [2.5, -3.0, 3.0]; current sign=+1; matches: 2.5, 3.0 -> count 2
        assert result["persistence_3d"].iloc[3] == 2
        # t=4 (value 3.5): window [-3.0, 3.0, 3.5]; current sign=+1; matches: 3.0, 3.5 -> count 2
        assert result["persistence_3d"].iloc[4] == 2

    def test_warmup_nan(self):
        z = pd.Series(np.arange(10, dtype=float) - 5, index=pd.date_range("2024-01-02", periods=10, freq="B"))
        result = fs.flow_persistence(z, threshold=0.5, windows=(3, 5))
        assert result["persistence_3d"].iloc[:2].isna().all()
        assert result["persistence_3d"].iloc[2:].notna().all()
        assert result["persistence_5d"].iloc[:4].isna().all()

    def test_negative_threshold_raises(self):
        z = pd.Series([1.0, 2.0], index=pd.date_range("2024-01-02", periods=2, freq="B"))
        with pytest.raises(ValueError):
            fs.flow_persistence(z, threshold=-1.0)


# ---------------------------------------------------------------------------
# TestShortPressureZ
# ---------------------------------------------------------------------------

class TestShortPressureZ:
    def test_reuses_robust_z_helper(self):
        ratio = pd.Series([0.1, 0.2, 0.3, 0.4, 0.9], index=pd.date_range("2024-01-02", periods=5, freq="B"))
        z_direct = fs._robust_z(ratio, window=5)
        z_short = fs.short_pressure_z(ratio, window=5)
        pd.testing.assert_series_equal(z_direct, z_short, check_names=False)


# ---------------------------------------------------------------------------
# TestAmihud
# ---------------------------------------------------------------------------

class TestAmihud:
    def test_hand_computed_amihud(self):
        closes = [100.0, 102.0, 99.0]
        volumes = [1000.0, 2000.0, 1500.0]
        bars = _bars(opens=closes, highs=closes, lows=closes, closes=closes, volumes=volumes)
        result = fs.amihud_illiquidity(bars, window=2)
        # returns: NaN, 0.02, -0.029411...
        # ratio_t1 = |0.02| / (102*2000) = 0.02 / 204000
        # ratio_t2 = |(99/102 - 1)| / (99*1500) = 0.0294117647 / 148500
        r1 = abs(102.0 / 100.0 - 1.0) / (102.0 * 2000.0)
        r2 = abs(99.0 / 102.0 - 1.0) / (99.0 * 1500.0)
        expected_last = (r1 + r2) / 2.0
        assert result.iloc[2] == pytest.approx(expected_last, rel=1e-9)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])  # window=2 needs 2 valid returns; t1 only has 1

    def test_zero_dollar_volume_guarded(self):
        closes = [100.0, 101.0, 102.0]
        volumes = [0.0, 0.0, 100.0]
        bars = _bars(opens=closes, highs=closes, lows=closes, closes=closes, volumes=volumes)
        result = fs.amihud_illiquidity(bars, window=2)
        assert np.isfinite(result.dropna()).all() if result.notna().any() else True
        assert not np.isinf(result.fillna(0.0)).any()

    def test_amihud_shock_warmup(self):
        rng = np.random.default_rng(1)
        closes = 100 + np.cumsum(rng.normal(0, 1, 40))
        volumes = np.full(40, 5000.0)
        bars = _bars(opens=closes, highs=closes + 1, lows=closes - 1, closes=closes, volumes=volumes)
        amihud = fs.amihud_illiquidity(bars, window=5)
        shock = fs.amihud_shock(amihud, window=5)
        # amihud needs 5 valid returns (row index 5 is first non-NaN amihud),
        # diff() consumes one more valid point, then _robust_z needs 5 more
        # valid diffs -> first non-NaN shock at row index 10.
        assert shock.iloc[:10].isna().all()
        assert shock.iloc[10:].notna().any()


# ---------------------------------------------------------------------------
# TestCorwinSchultz
# ---------------------------------------------------------------------------

class TestCorwinSchultzSpread:
    def test_zero_range_series_yields_zero_spread(self):
        # Corwin & Schultz (2012), JF 67(2): spread collapses to 0 when the
        # daily high-low range never varies (beta == gamma == 0 -> alpha
        # floored at exactly 0 -> S = 2*(e^0-1)/(1+e^0) = 0).
        n = 10
        bars = _bars(
            opens=[100.0] * n, highs=[100.0] * n, lows=[100.0] * n,
            closes=[100.0] * n, volumes=[1000.0] * n,
        )
        spread = fs.corwin_schultz_spread(bars, smooth_window=3)
        assert (spread.dropna() == 0.0).all()

    def test_manual_two_day_example(self):
        # Hand-computed against the published closed form for a single pair.
        h0, l0 = 101.0, 99.0
        h1, l1 = 103.0, 100.0
        bars = _bars(
            opens=[h0, h1], highs=[h0, h1], lows=[l0, l1], closes=[h0, h1], volumes=[1000.0, 1000.0],
        )
        result = fs.corwin_schultz_spread(bars, smooth_window=1)
        log_hl0 = np.log(h0 / l0)
        log_hl1 = np.log(h1 / l1)
        beta = log_hl1 ** 2 + log_hl0 ** 2
        two_day_high, two_day_low = max(h0, h1), min(l0, l1)
        gamma = np.log(two_day_high / two_day_low) ** 2
        k = 3.0 - 2.0 * np.sqrt(2.0)
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        alpha = max(alpha, 0.0)
        expected = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
        expected = max(expected, 0.0)
        assert result.iloc[1] == pytest.approx(expected, rel=1e-9)

    def test_negative_alpha_floored_at_zero(self):
        # A very tight second day right after a wide first day can produce a
        # negative closed-form alpha; the estimator must floor it, not emit
        # a negative spread.
        bars = _bars(
            opens=[100.0, 100.0], highs=[110.0, 100.5], lows=[90.0, 99.5],
            closes=[100.0, 100.0], volumes=[1000.0, 1000.0],
        )
        result = fs.corwin_schultz_spread(bars, smooth_window=1)
        assert result.iloc[1] >= 0.0


# ---------------------------------------------------------------------------
# TestImpactBeta / ImpactResponseCurve
# ---------------------------------------------------------------------------

class TestImpactBeta:
    def test_perfect_linear_relationship_recovers_slope(self):
        idx = pd.date_range("2024-01-02", periods=30, freq="B")
        x = pd.Series(np.linspace(-1, 1, 30), index=idx)
        true_slope = 0.02
        y = true_slope * x
        beta = fs.impact_beta(y, x, window=10)
        assert beta.iloc[-1] == pytest.approx(true_slope, rel=1e-6)

    def test_mismatched_index_raises(self):
        idx1 = pd.date_range("2024-01-02", periods=5, freq="B")
        idx2 = pd.date_range("2024-02-02", periods=5, freq="B")
        x = pd.Series([1.0] * 5, index=idx1)
        y = pd.Series([1.0] * 5, index=idx2)
        with pytest.raises(ValueError):
            fs.impact_beta(y, x, window=3)

    def test_warmup_nan(self):
        idx = pd.date_range("2024-01-02", periods=20, freq="B")
        x = pd.Series(np.random.default_rng(2).normal(size=20), index=idx)
        y = pd.Series(np.random.default_rng(3).normal(size=20), index=idx)
        beta = fs.impact_beta(y, x, window=10)
        assert beta.iloc[:9].isna().all()


class TestImpactResponseCurve:
    def test_shape_and_columns(self):
        idx = pd.date_range("2024-01-02", periods=50, freq="B")
        returns = pd.Series(np.random.default_rng(4).normal(0, 0.01, 50), index=idx)
        shock_mask = pd.Series(False, index=idx)
        shock_mask.iloc[[5, 20, 35]] = True
        curve = fs.impact_response_curve(returns, shock_mask, max_lag=5)
        assert list(curve.columns) == ["lag", "mean_cum_ret", "ci_lo", "ci_hi", "n"]
        assert curve["lag"].tolist() == [1, 2, 3, 4, 5]
        assert (curve["n"] <= 3).all()

    def test_no_events_yields_zero_n_and_nan_stats(self):
        idx = pd.date_range("2024-01-02", periods=10, freq="B")
        returns = pd.Series(0.01, index=idx)
        shock_mask = pd.Series(False, index=idx)
        curve = fs.impact_response_curve(returns, shock_mask, max_lag=3)
        assert (curve["n"] == 0).all()
        assert curve["mean_cum_ret"].isna().all()


# ---------------------------------------------------------------------------
# TestBarrierDensity / AirPocket / NearestNodes
# ---------------------------------------------------------------------------

class TestBarrierDensity:
    def _sample_bars(self, n=40, seed=5):
        rng = np.random.default_rng(seed)
        closes = 100 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + rng.uniform(0.2, 1.0, n)
        lows = closes - rng.uniform(0.2, 1.0, n)
        volumes = rng.uniform(1000, 5000, n)
        return _bars(opens=closes, highs=highs, lows=lows, closes=closes, volumes=volumes)

    def test_returns_series_indexed_by_grid(self):
        bars = self._sample_bars()
        cfg = fs.FlowStateConfig()
        grid = np.linspace(90, 110, 41)
        density = fs.barrier_density(bars, grid, cfg)
        assert isinstance(density, pd.Series)
        np.testing.assert_allclose(density.index.to_numpy(), grid)
        assert (density >= 0).all()
        assert np.isfinite(density.to_numpy()).all()

    def test_grid_too_small_raises(self):
        bars = self._sample_bars()
        cfg = fs.FlowStateConfig()
        with pytest.raises(ValueError):
            fs.barrier_density(bars, np.array([100.0]), cfg)

    def test_air_pocket_score_empty_range_is_zero(self):
        bars = self._sample_bars()
        cfg = fs.FlowStateConfig()
        grid = np.linspace(90, 110, 41)
        density = fs.barrier_density(bars, grid, cfg)
        # A range entirely outside the grid contributes nothing -> 0.0
        assert fs.air_pocket_score(density, 1000.0, 1001.0) == 0.0

    def test_air_pocket_score_lower_density_gives_higher_score(self):
        idx = pd.RangeIndex(5)
        dense = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0], index=pd.Index([1.0, 2.0, 3.0, 4.0, 5.0], name="price"))
        sparse = pd.Series([0.1, 0.1, 0.1, 0.1, 0.1], index=pd.Index([1.0, 2.0, 3.0, 4.0, 5.0], name="price"))
        dense_score = fs.air_pocket_score(dense, 1.0, 5.0)
        sparse_score = fs.air_pocket_score(sparse, 1.0, 5.0)
        assert sparse_score > dense_score

    def test_nearest_nodes_support_and_resistance(self):
        # Three peaks: at 95, 100, 105; query price 100.5 should find
        # support at 100, resistance at 105.
        grid = np.linspace(90, 110, 21)
        values = np.zeros_like(grid)
        for center, mass in [(95.0, 5.0), (100.0, 8.0), (105.0, 3.0)]:
            values += mass * np.exp(-0.5 * ((grid - center) / 1.0) ** 2)
        density = pd.Series(values, index=pd.Index(grid, name="price"))
        nodes = fs.nearest_nodes(density, price=100.5)
        assert nodes["support_price"] == pytest.approx(100.0, abs=1.5)
        assert nodes["resistance_price"] == pytest.approx(105.0, abs=1.5)
        assert nodes["support_mass"] is not None
        assert nodes["resistance_mass"] is not None

    def test_nearest_nodes_missing_side_is_none(self):
        grid = np.linspace(90, 110, 21)
        values = np.exp(-0.5 * ((grid - 90.0) / 1.0) ** 2)
        density = pd.Series(values, index=pd.Index(grid, name="price"))
        nodes = fs.nearest_nodes(density, price=85.0)
        assert nodes["support_price"] is None
        assert nodes["resistance_price"] is not None


# ---------------------------------------------------------------------------
# TestCrossAssetResiduals
# ---------------------------------------------------------------------------

class TestCrossAssetResiduals:
    def test_zero_residual_when_symbol_is_exact_factor_combo(self):
        idx = pd.date_range("2024-01-02", periods=80, freq="B")
        rng = np.random.default_rng(6)
        factor_a = pd.Series(rng.normal(0, 0.01, 80), index=idx)
        factor_b = pd.Series(rng.normal(0, 0.01, 80), index=idx)
        factors = pd.DataFrame({"a": factor_a, "b": factor_b})
        sym_rets = 0.5 * factor_a + 0.3 * factor_b
        residual = fs.cross_asset_residuals(sym_rets, factors, window=20)
        assert residual.iloc[30:].abs().max() < 1e-8

    def test_warmup_nan(self):
        idx = pd.date_range("2024-01-02", periods=30, freq="B")
        rng = np.random.default_rng(7)
        factors = pd.DataFrame({"a": rng.normal(size=30)}, index=idx)
        sym_rets = pd.Series(rng.normal(size=30), index=idx)
        residual = fs.cross_asset_residuals(sym_rets, factors, window=15)
        assert residual.iloc[:14].isna().all()

    def test_mismatched_index_raises(self):
        idx1 = pd.date_range("2024-01-02", periods=10, freq="B")
        idx2 = pd.date_range("2024-03-02", periods=10, freq="B")
        factors = pd.DataFrame({"a": [1.0] * 10}, index=idx1)
        sym_rets = pd.Series([1.0] * 10, index=idx2)
        with pytest.raises(ValueError):
            fs.cross_asset_residuals(sym_rets, factors, window=5)


# ---------------------------------------------------------------------------
# TestClassifier
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_all_states_reachable(self):
        cfg = fs.FlowStateConfig()
        n = 20
        f = _flat_features(n, cfg)
        persistence_col = f"flow_persistence_{cfg.pressure_persistence_window}d"

        _set(f, 0, flow_z=4.0, amihud_shock=3.0)  # SHOCK
        _set(f, 1, **{persistence_col: 5})  # PRESSURE
        _set(f, 2, flow_z=2.0, dist_to_barrier_atr=0.1, barrier_high_mass=True)  # TEST
        _set(f, 3, barrier_break_direction=1, air_pocket_break=10.0, signed_flow_sign=1)  # CASCADE
        _set(f, 4, dist_to_barrier_atr=0.1, barrier_high_mass=True, volume_ratio=2.0, range_compression=0.5)  # ABSORB
        # EXHAUSTION: decaying |flow_z| over exhaustion_lookback trailing bars + elevated amihud_shock
        for i, v in zip(range(5, 9), [5.0, 4.0, 3.0, 2.0]):
            _set(f, i, flow_z=v, amihud_shock=1.5)
        # rows 6,7,8 have decaying flow_z relative to their own trailing 3; row 8 is EXHAUSTION
        # FADE should follow within fade_lookback with amihud renormalized
        _set(f, 9, amihud_shock=0.1)

        states = fs.classify_states(f, cfg)
        seen = set(states.unique())
        assert seen == set(fs.ALL_STATES), f"missing states: {set(fs.ALL_STATES) - seen}"

    def test_no_state_appears_without_its_trigger(self):
        cfg = fs.FlowStateConfig()
        f = _flat_features(15, cfg)
        states = fs.classify_states(f, cfg)
        assert set(states.unique()) == {"NORMAL"}

    def test_determinism(self):
        cfg = fs.FlowStateConfig()
        f = _flat_features(20, cfg)
        _set(f, 5, flow_z=4.0, amihud_shock=3.0)
        s1 = fs.classify_states(f, cfg)
        s2 = fs.classify_states(f, cfg)
        pd.testing.assert_series_equal(s1, s2)

    def test_only_looks_at_row_leq_t(self):
        cfg = fs.FlowStateConfig()
        f = _flat_features(20, cfg)
        _set(f, 3, flow_z=4.0, amihud_shock=3.0)
        _set(f, 10, flow_z=4.0, amihud_shock=3.0)
        states_before = fs.classify_states(f, cfg)

        mutated = f.copy()
        _set(mutated, 15, flow_z=10.0, amihud_shock=10.0, barrier_break_direction=1, air_pocket_break=99.0)
        states_after = fs.classify_states(mutated, cfg)

        # rows strictly before the mutation (index < 15) must be identical.
        pd.testing.assert_series_equal(states_before.iloc[:15], states_after.iloc[:15])

    def test_shock_priority_over_pressure(self):
        cfg = fs.FlowStateConfig()
        f = _flat_features(6, cfg)
        persistence_col = f"flow_persistence_{cfg.pressure_persistence_window}d"
        _set(f, 3, flow_z=4.0, amihud_shock=3.0, **{persistence_col: 5})
        states = fs.classify_states(f, cfg)
        assert states.iloc[3] == "SHOCK"

    def test_state_rules_table_is_inspectable(self):
        names = [name for name, _ in fs.STATE_RULES]
        assert names == ["SHOCK", "PRESSURE", "TEST", "CASCADE", "ABSORB", "EXHAUSTION", "FADE"]

    def test_missing_column_raises_keyerror(self):
        cfg = fs.FlowStateConfig()
        f = _flat_features(5, cfg).drop(columns=["flow_z"])
        with pytest.raises(KeyError):
            fs.classify_states(f, cfg)


# ---------------------------------------------------------------------------
# TestExtractEvents
# ---------------------------------------------------------------------------

class TestExtractEvents:
    def test_one_row_per_contiguous_episode(self):
        idx = pd.date_range("2024-01-02", periods=10, freq="B")
        states = pd.Series(
            ["NORMAL", "SHOCK", "SHOCK", "NORMAL", "TEST", "NORMAL", "NORMAL", "SHOCK", "NORMAL", "NORMAL"],
            index=idx,
        )
        features = pd.DataFrame({"flow_z": [0, 3.5, 3.0, 0, -2.0, 0, 0, 4.0, 0, 0], "x": range(10)}, index=idx)
        events = fs.extract_events(states, features, resolution_horizon=2)
        assert len(events) == 3
        assert events.iloc[0]["t0"] == idx[1]
        assert events.iloc[0]["direction"] == 1
        assert events.iloc[1]["t0"] == idx[4]
        assert events.iloc[1]["direction"] == -1
        assert "feat_x" in events.columns
        assert events.iloc[0]["feat_x"] == 1

    def test_resolution_state_uses_horizon(self):
        idx = pd.date_range("2024-01-02", periods=8, freq="B")
        states = pd.Series(["SHOCK"] + ["NORMAL"] * 6 + ["FADE"], index=idx)
        features = pd.DataFrame({"flow_z": [3.5] + [0.0] * 7}, index=idx)
        events = fs.extract_events(states, features, resolution_horizon=7)
        assert events.iloc[0]["resolution_state"] == "FADE"
        assert events.iloc[0]["resolution_date"] == idx[7]

    def test_resolution_clamps_to_last_available_row(self):
        idx = pd.date_range("2024-01-02", periods=5, freq="B")
        states = pd.Series(["NORMAL", "NORMAL", "NORMAL", "NORMAL", "SHOCK"], index=idx)
        features = pd.DataFrame({"flow_z": [0, 0, 0, 0, 4.0]}, index=idx)
        events = fs.extract_events(states, features, resolution_horizon=20)
        assert events.iloc[0]["resolution_date"] == idx[-1]

    def test_no_events_returns_empty_frame(self):
        idx = pd.date_range("2024-01-02", periods=5, freq="B")
        states = pd.Series(["NORMAL"] * 5, index=idx)
        features = pd.DataFrame({"flow_z": [0.0] * 5}, index=idx)
        events = fs.extract_events(states, features)
        assert len(events) == 0


# ---------------------------------------------------------------------------
# TestBuildFlowStatePanel -- holdout guard
# ---------------------------------------------------------------------------

class TestBuildFlowStatePanel:
    def test_holdout_guard_raises_without_flag(self):
        with pytest.raises(ValueError, match="holdout"):
            fsp.build_flow_state_panel(["AAPL"], start="2020-01-01", end="2026-07-13")

    def test_holdout_guard_raises_for_dates_after_start(self):
        with pytest.raises(ValueError, match="holdout"):
            fsp.build_flow_state_panel(["AAPL"], start="2020-01-01", end="2026-09-01")

    def test_holdout_guard_does_not_fire_before_cutoff(self, tmp_path):
        # allow_holdout=False, end well before the sealed cutoff: the guard
        # itself must not raise. The call may still return an empty panel
        # (no data at tmp_path) -- that is a data-availability outcome, not
        # the guard firing, so we only assert no ValueError is raised here.
        result = fsp.build_flow_state_panel(
            ["NOPE"], start="2020-01-01", end="2020-06-01", data_root=tmp_path,
        )
        assert "NOPE" in " ".join(result.attrs.get("warnings", []))

    def test_allow_holdout_true_does_not_raise_the_guard(self, tmp_path):
        # With allow_holdout=True the sealed-holdout ValueError specifically
        # must not fire, even though the symbol/data won't resolve.
        try:
            fsp.build_flow_state_panel(
                ["NOPE"], start="2020-01-01", end="2026-08-01",
                data_root=tmp_path, allow_holdout=True,
            )
        except ValueError as exc:
            assert "holdout" not in str(exc).lower()

    def test_missing_symbol_is_reported_not_raised(self, tmp_path):
        result = fsp.build_flow_state_panel(
            ["ZZZDOESNOTEXIST"], start="2020-01-01", end="2020-06-01", data_root=tmp_path,
        )
        assert isinstance(result, pd.DataFrame)
        assert any("ZZZDOESNOTEXIST" in w for w in result.attrs.get("warnings", []))

    def test_end_to_end_on_synthetic_parquet(self, tmp_path):
        wide_dir = tmp_path / "1d_wide"
        wide_dir.mkdir(parents=True)
        n = 120
        rng = np.random.default_rng(9)
        idx = pd.date_range("2024-01-02", periods=n, freq="B")
        closes = 50 + np.cumsum(rng.normal(0, 0.5, n))
        highs = closes + rng.uniform(0.1, 1.0, n)
        lows = closes - rng.uniform(0.1, 1.0, n)
        opens = closes + rng.normal(0, 0.2, n)
        volumes = rng.uniform(1e5, 5e5, n)
        bars = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=idx,
        )
        bars.to_parquet(wide_dir / "SYN.parquet")

        result = fsp.build_flow_state_panel(
            ["SYN"], start="2024-01-01", end="2024-06-01", data_root=tmp_path,
        )
        assert not result.empty
        assert set(result["symbol"].unique()) == {"SYN"}
        assert "state" in result.columns
        assert result["state"].isin(fs.ALL_STATES).all()


# ---------------------------------------------------------------------------
# Synthetic multi-year OHLCV builders for periodic-barrier-recompute tests.
# Both are hand-tuned and verified (via ad hoc exploration) to make the full
# build_flow_state_panel pipeline actually emit TEST/CASCADE/ABSORB at a
# specific, known, mid-panel row -- not just at the last row.
# ---------------------------------------------------------------------------

def _shelf_bars_with_test_and_cascade(n: int = 400, seed: int = 42):
    """A resistance shelf at 110 forms early (bars 30-60); a mid-panel
    approach (bars 180-194) produces TEST rows, and bar 195 breaks out
    through the shelf on a volume surge, producing a CASCADE row well
    before the end of the 400-row series."""
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0, 0.15, n))
    high = base + rng.uniform(0.3, 0.6, n)
    low = base - rng.uniform(0.3, 0.6, n)
    close = base.copy()
    open_ = base + rng.normal(0, 0.1, n)
    volume = rng.uniform(2e5, 4e5, n)

    shelf_price = 110.0
    for i in range(30, 61):
        high[i] = shelf_price + rng.uniform(-0.1, 0.1)
        close[i] = shelf_price - rng.uniform(0.2, 1.0)
        low[i] = close[i] - rng.uniform(0.2, 0.5)

    for i in range(62, n):
        close[i] = close[i - 1] + rng.normal(0, 0.15)
        high[i] = close[i] + rng.uniform(0.3, 0.6)
        low[i] = close[i] - rng.uniform(0.3, 0.6)
        open_[i] = close[i - 1]

    approach_start = 180
    for j, i in enumerate(range(approach_start, approach_start + 15)):
        close[i] = 105 + j * 0.5
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.3
        volume[i] = 3e5 + j * 5e4

    brk = approach_start + 15  # index 195
    close[brk], high[brk], low[brk], open_[brk], volume[brk] = 116.0, 117.0, 109.0, 109.5, 3.5e6
    for i in range(brk + 1, min(brk + 20, n)):
        close[i] = close[i - 1] + rng.normal(0.3, 0.2)
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.4
        open_[i] = close[i - 1]

    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)




# ---------------------------------------------------------------------------
# TestPeriodicBarrierRecompute -- coordinator-requested fix verification
# ---------------------------------------------------------------------------

class TestPeriodicBarrierRecompute:
    def test_barrier_columns_are_populated_at_multiple_historical_points(self):
        # (a) Not just the last row: many mid-panel rows must carry a real
        # (non-placeholder) barrier signal once past the warm-up window.
        cfg = fs.FlowStateConfig(barrier_recompute_every_n_days=5)
        bars = _shelf_bars_with_test_and_cascade()
        features = fsp._symbol_flow_state_features(bars, cfg)

        min_bars = max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1
        post_warmup = features.iloc[min_bars:-1]  # exclude last row on purpose
        finite_dist = post_warmup["dist_to_barrier_atr"].notna()
        assert finite_dist.sum() > 50, "expected many historical rows with a real barrier distance"
        assert post_warmup.loc[finite_dist, "dist_to_barrier_atr"].nunique() > 5, (
            "barrier distance should vary across recompute points, not sit at one placeholder value"
        )
        # At least one non-last row must show barrier_high_mass True somewhere.
        assert post_warmup["barrier_high_mass"].any()

    def test_cadence_is_respected_constant_between_recomputes_changes_at_boundary(self):
        # (b) Values are piecewise-constant between recompute points and are
        # only allowed to change exactly at a recompute boundary.
        cfg = fs.FlowStateConfig(barrier_recompute_every_n_days=5)
        bars = _shelf_bars_with_test_and_cascade()
        filled = fsp._periodic_barrier_fields(bars, cfg)

        min_bars = max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1
        cadence = cfg.barrier_recompute_every_n_days
        recompute_idx = sorted(set(range(min_bars - 1, len(bars), cadence)) | {len(bars) - 1})

        # Within each block [recompute_idx[k], recompute_idx[k+1]) every row
        # must carry exactly the value set at the block's own recompute row.
        for k in range(len(recompute_idx) - 1):
            block_start = recompute_idx[k]
            block_end = recompute_idx[k + 1]  # exclusive upper bound of the held value
            if block_end - block_start < 2:
                continue
            held_value = filled["resistance_price"].iloc[block_start]
            block = filled["resistance_price"].iloc[block_start:block_end]
            if pd.isna(held_value):
                assert block.isna().all()
            else:
                assert (block == held_value).all(), (
                    f"resistance_price changed mid-block [{block_start}, {block_end})"
                )

        # And the field does actually change value at some point across the
        # whole series (i.e. the cadence isn't accidentally a no-op).
        distinct_values = filled["resistance_price"].dropna().round(6).nunique()
        assert distinct_values > 1

    def test_last_row_is_always_recomputed_exactly(self):
        cfg = fs.FlowStateConfig(barrier_recompute_every_n_days=7)
        bars = _shelf_bars_with_test_and_cascade()
        filled = fsp._periodic_barrier_fields(bars, cfg)
        n = len(bars)
        min_bars = max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1
        # The last row's own recompute uses the full trailing history, so it
        # must not simply equal whatever the prior cadence block held unless
        # that happens to be the true snapshot -- verify it against a direct
        # one-off snapshot computed the same way build_flow_state_panel does.
        window_start = max(0, n - cfg.barrier_history_lookback_bars)
        direct = fsp._compute_barrier_snapshot(bars.iloc[window_start:], cfg, grid_points=121)
        assert direct is not None
        for field in fsp._BARRIER_SNAPSHOT_FIELDS:
            expected = direct[field]
            actual = filled[field].iloc[-1]
            if expected is None:
                assert pd.isna(actual)
            else:
                assert actual == pytest.approx(expected)

    def test_test_and_cascade_reachable_mid_panel_not_only_last_row(self):
        # (c) TEST/CASCADE reachable well before the final row via the full
        # build_flow_state_panel feature pipeline (not a hand-built
        # classify_states frame -- this exercises the periodic-recompute
        # barrier wiring end to end).
        cfg = fs.FlowStateConfig(barrier_recompute_every_n_days=5)
        bars = _shelf_bars_with_test_and_cascade()
        n = len(bars)
        features = fsp._symbol_flow_state_features(bars, cfg)
        states = fs.classify_states(features, cfg)

        test_positions = np.flatnonzero((states == "TEST").to_numpy())
        cascade_positions = np.flatnonzero((states == "CASCADE").to_numpy())
        assert test_positions.size > 0
        assert cascade_positions.size > 0
        # "Not only at the final row": at least one occurrence of each must
        # sit well before the end of the panel (some rows may recur later
        # too -- that's fine, the point is it is not exclusively the last
        # row that matters here).
        assert test_positions.min() < n - 100
        assert cascade_positions.min() < n - 100

    def test_absorb_reachable_mid_panel_via_derived_barrier_row_features(self):
        # (c) ABSORB, proven against the periodic-recompute wiring directly:
        # hand-crafting raw OHLCV that makes barrier_density's *organic* KDE
        # pick a specific node as "the" resistance turned out too brittle to
        # hand-tune reliably (the volume-at-price kernel from a ramp of
        # approach bars can itself become the nearest node, out-competing an
        # intentional shelf a few dollars away). Instead this drives
        # _derive_barrier_row_features -- the actual per-row logic
        # build_flow_state_panel uses to turn a forward-filled barrier
        # snapshot into classify_states columns -- with a controlled,
        # shaped-like-_periodic_barrier_fields "filled" frame that places a
        # held resistance node at a known price for a multi-row block in the
        # middle of the panel, and checks ABSORB is reached there while the
        # panel's last row is a different (non-barrier) situation.
        cfg = fs.FlowStateConfig()
        n = 60
        idx = pd.date_range("2022-01-03", periods=n, freq="B")
        rng = np.random.default_rng(11)
        close = 100 + rng.normal(0, 0.05, n)
        high = close + 0.2
        low = close - 0.2
        open_ = close - 0.02
        volume = np.full(n, 2e5)

        absorb_idx = 30
        close[absorb_idx], open_[absorb_idx] = 109.7, 109.6
        high[absorb_idx], low[absorb_idx] = 109.85, 109.55  # narrow range, stays under 110
        volume[absorb_idx] = 3e6  # huge surge vs 2e5 baseline

        bars = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx,
        )

        filled = pd.DataFrame(
            {
                "support_price": 95.0, "support_mass": 10.0,
                "resistance_price": 110.0, "resistance_mass": 500.0,  # far above mass_threshold
                "mass_threshold": 50.0,
                "air_pocket_up": 20.0, "air_pocket_down": 20.0,
            },
            index=bars.index,
        )
        barrier_rows = fsp._derive_barrier_row_features(bars, filled, cfg)

        features = pd.DataFrame(index=bars.index)
        features["flow_z"] = 0.0
        features["amihud_shock"] = 0.0
        features[f"flow_persistence_{cfg.pressure_persistence_window}d"] = 0
        features["signed_flow_sign"] = 0
        daily_range = bars["high"] - bars["low"]
        features["volume_ratio"] = bars["volume"] / bars["volume"].rolling(20, min_periods=1).mean()
        features["range_compression"] = daily_range / daily_range.rolling(20, min_periods=1).mean()
        for col in barrier_rows.columns:
            features[col] = barrier_rows[col]

        states = fs.classify_states(features, cfg)
        assert states.iloc[absorb_idx] == "ABSORB"
        absorb_positions = np.flatnonzero((states == "ABSORB").to_numpy())
        assert absorb_positions.max() < n - 10, "ABSORB must not only appear at the final row"

    def test_build_flow_state_panel_end_to_end_reaches_test_cascade(self, tmp_path):
        # Same proof, but through the public build_flow_state_panel entry
        # point (parquet -> panel), not the private per-symbol helper.
        wide_dir = tmp_path / "1d_wide"
        wide_dir.mkdir(parents=True)
        bars = _shelf_bars_with_test_and_cascade()
        bars.to_parquet(wide_dir / "SHELF.parquet")

        cfg = fs.FlowStateConfig(barrier_recompute_every_n_days=5)
        result = fsp.build_flow_state_panel(
            ["SHELF"], start="2022-01-01", end="2023-11-01", data_root=tmp_path, cfg=cfg,
        )
        assert not result.empty
        seen_states = set(result["state"].unique())
        assert "TEST" in seen_states
        assert "CASCADE" in seen_states
        last_date = result["date"].max()
        mid_panel_rows = result[result["date"] < last_date - pd.Timedelta(days=30)]
        assert "TEST" in set(mid_panel_rows["state"].unique())
        assert "CASCADE" in set(mid_panel_rows["state"].unique())


# ---------------------------------------------------------------------------
# Barrier continuation sleeve
# ---------------------------------------------------------------------------

class TestBarrierContinuationScore:
    def test_score_rises_with_barrier_proximity_and_impact(self):
        cfg = fs.FlowStateConfig()
        n = 80
        idx = pd.date_range("2024-01-02", periods=n, freq="B")
        flow = pd.Series(0.0, index=idx)
        impact = pd.Series(0.0, index=idx)
        pers = pd.Series(0.0, index=idx)
        dist = pd.Series(5.0, index=idx)

        # Last row: strong persistent flow, high impact beta, at barrier
        flow.iloc[-1] = -4.0
        impact.iloc[-20:] = np.linspace(0.0, 0.05, 20)  # rising impact
        impact.iloc[-1] = 0.08
        pers.iloc[-1] = 5.0
        dist.iloc[-1] = 0.1

        # Control row mid-sample: same flow/persistence but far from barrier, flat impact
        flow.iloc[40] = -4.0
        pers.iloc[40] = 5.0
        dist.iloc[40] = 4.0
        impact.iloc[40] = 0.0

        # Supply impact_beta_z directly so the test does not depend on MAD warm-up
        z_beta = pd.Series(0.0, index=idx)
        z_beta.iloc[-1] = 2.5
        z_beta.iloc[40] = 2.5

        out = fs.barrier_continuation_score(
            flow, impact, pers, dist, cfg=cfg, impact_beta_z=z_beta,
        )
        assert out.loc[idx[-1], "continuation_direction"] == -1
        assert out.loc[idx[-1], "continuation_score"] > out.loc[idx[40], "continuation_score"]
        assert out.loc[idx[-1], "barrier_proximity"] > out.loc[idx[40], "barrier_proximity"]
        # Far-from-barrier + zeroed proximity should crush the mid score
        assert out.loc[idx[40], "continuation_score"] < out.loc[idx[-1], "continuation_score"] * 0.5

    def test_negative_impact_z_does_not_contribute(self):
        cfg = fs.FlowStateConfig()
        idx = pd.date_range("2024-01-02", periods=5, freq="B")
        flow = pd.Series([0, 0, 0, 0, 3.0], index=idx)
        impact = pd.Series(0.01, index=idx)
        pers = pd.Series([0, 0, 0, 0, 5.0], index=idx)
        dist = pd.Series(0.1, index=idx)
        z_beta = pd.Series([0, 0, 0, 0, -2.0], index=idx)
        out = fs.barrier_continuation_score(
            flow, impact, pers, dist, cfg=cfg, impact_beta_z=z_beta,
        )
        assert out["continuation_score"].iloc[-1] == pytest.approx(0.0)
