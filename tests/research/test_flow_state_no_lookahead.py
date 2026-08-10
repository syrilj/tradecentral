"""
Mutation-property no-lookahead test for the Phase 2 flow-state + labeling
pipeline. Pattern copied from ``eval/test_no_lookahead.py``: mutate a bar
strictly AFTER a reference point and prove nothing at-or-before that point
moved; mutate a bar strictly WITHIN a downstream window and prove the
downstream result DOES move (proof the test has teeth, not a tautology).

Unlike ``eval/test_no_lookahead.py`` (which exercises one walk-forward
harness), this test spans two layers: ``research/flow_state.py``'s pure
per-row features/state classifier, and ``research/event_labels.py``'s
``competing_barrier_labels``. Both layers are trailing-only by construction
(documented in each module), so this test is the executable proof.

Feature construction here deliberately does NOT go through
``research/flow_state_panel.py:build_flow_state_panel`` (that module reads
parquet from disk); instead it calls the pure functions in
``research/flow_state.py`` directly against a small synthetic multi-symbol
OHLCV panel, exactly per the phase spec. The four barrier-dependent columns
``classify_states`` requires (``dist_to_barrier_atr``, ``barrier_high_mass``,
``barrier_break_direction``, ``air_pocket_break``) are set to neutral
constants rather than run through the full O(n) ``barrier_density`` kernel
scan -- this test targets the SHOCK-event pathway (flow_z + amihud_shock),
not the barrier-density machinery, which already has its own dedicated
coverage in ``tests/research/test_flow_state.py``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

try:
    from edge.research import event_labels as el
    from edge.research import flow_state as fs
except ImportError:
    from research import event_labels as el
    from research import flow_state as fs


N_BARS = 45
SHOCK_INDEX = 20
HORIZON_DAYS = 8
VOL_WINDOW = 10
K_DOWN, K_UP = 1.0, 1.0


def _make_synthetic_bars(seed: int = 0) -> pd.DataFrame:
    """Small deterministic multi-day OHLCV path with one engineered SHOCK day.

    Day ``SHOCK_INDEX`` gets an outsized down-move on moderate (not huge)
    volume -- verified empirically to push both ``flow_z`` (< -3) and
    ``amihud_shock`` (> 2) past ``FlowStateConfig``'s default SHOCK
    thresholds with the small rolling windows this test uses.
    """
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for i in range(1, N_BARS):
        r = rng.normal(0.0, 0.003)
        if i == SHOCK_INDEX:
            r = -0.08
        closes.append(closes[-1] * (1.0 + r))
    closes = np.array(closes)
    opens = np.concatenate([[100.0], closes[:-1]])
    eps = np.abs(rng.normal(0.0, 0.001, size=N_BARS))
    highs = np.maximum(opens, closes) * (1.0 + eps)
    lows = np.minimum(opens, closes) * (1.0 - eps)
    volume = np.full(N_BARS, 600_000.0)
    volume[SHOCK_INDEX] = 1_200_000.0
    idx = pd.bdate_range("2024-01-02", periods=N_BARS)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=idx,
    )


def _cfg() -> fs.FlowStateConfig:
    return fs.FlowStateConfig(
        flow_z_window=5, amihud_window=5, amihud_shock_window=5,
        corwin_schultz_smooth_window=2, impact_beta_window=5,
    )


def _build_features(bars: pd.DataFrame, cfg: fs.FlowStateConfig) -> pd.DataFrame:
    """Pure-function feature build (mirrors flow_state_panel's per-row
    columns) with barrier-dependent columns neutralized -- see module
    docstring."""
    svp = fs.signed_volume_proxy(bars)
    flow_z = fs.flow_z(svp, cfg.flow_z_window)
    persistence = fs.flow_persistence(flow_z, cfg.flow_persistence_threshold, cfg.flow_persistence_windows)
    amihud = fs.amihud_illiquidity(bars, cfg.amihud_window)
    amihud_shock = fs.amihud_shock(amihud, cfg.amihud_shock_window)
    cs_spread = fs.corwin_schultz_spread(bars, cfg.corwin_schultz_smooth_window)
    returns = bars["close"].pct_change()
    beta = fs.impact_beta(returns, flow_z, cfg.impact_beta_window)

    daily_range = bars["high"] - bars["low"]
    volume_ratio = bars["volume"] / bars["volume"].rolling(20, min_periods=20).mean()
    range_compression = daily_range / daily_range.rolling(20, min_periods=20).mean()

    features = pd.DataFrame(index=bars.index)
    features["signed_volume_proxy"] = svp
    features["flow_z"] = flow_z
    for w in cfg.flow_persistence_windows:
        features[f"flow_persistence_{w}d"] = persistence[f"persistence_{w}d"]
    features["amihud"] = amihud
    features["amihud_shock"] = amihud_shock
    features["corwin_schultz_spread"] = cs_spread
    features["impact_beta"] = beta
    features["volume_ratio"] = volume_ratio
    features["range_compression"] = range_compression
    features["signed_flow_sign"] = np.sign(svp).astype(int)

    # Barrier-dependent columns, neutralized (see module docstring): "far
    # from any barrier" so TEST/CASCADE/ABSORB can never trigger, isolating
    # the SHOCK pathway this test targets.
    features["dist_to_barrier_atr"] = 10.0
    features["barrier_high_mass"] = False
    features["barrier_break_direction"] = 0
    features["air_pocket_break"] = 0.0
    return features


def _run_pipeline(bars: pd.DataFrame, cfg: fs.FlowStateConfig):
    features = _build_features(bars, cfg)
    states = fs.classify_states(features, cfg)
    events_input = features.copy()
    events_input["symbol"] = "TEST"
    events = fs.extract_events(states, events_input)
    return features, states, events


@pytest.fixture(scope="module")
def baseline():
    bars = _make_synthetic_bars()
    cfg = _cfg()
    features, states, events = _run_pipeline(bars, cfg)
    assert states.iloc[SHOCK_INDEX] == "SHOCK", "fixture must reliably trigger a SHOCK event"
    shock_event = events.loc[events["t0"] == bars.index[SHOCK_INDEX]]
    assert len(shock_event) == 1
    labels = el.competing_barrier_labels(bars, shock_event, K_DOWN, K_UP, HORIZON_DAYS, vol_window=VOL_WINDOW)
    return bars, cfg, features, states, shock_event, labels


class TestNoLookaheadMutationProperty:
    def test_baseline_sanity(self, baseline):
        bars, cfg, features, states, shock_event, labels = baseline
        # forward window (t0+1 .. t0+HORIZON_DAYS) exists inside N_BARS.
        assert SHOCK_INDEX + HORIZON_DAYS < N_BARS
        assert len(labels) == 1

    def test_mutating_far_future_bar_leaves_prefix_byte_identical(self, baseline):
        bars, cfg, features, states, shock_event, labels = baseline
        prefix_end = SHOCK_INDEX + 1  # inclusive of t0

        far_future_idx = SHOCK_INDEX + HORIZON_DAYS + 5  # strictly beyond the label's horizon
        assert far_future_idx < N_BARS

        mutated = bars.copy(deep=True)
        mutated.iloc[far_future_idx, mutated.columns.get_loc("close")] *= 5.0
        mutated.iloc[far_future_idx, mutated.columns.get_loc("high")] *= 5.0
        mutated.iloc[far_future_idx, mutated.columns.get_loc("low")] *= 5.0
        mutated.iloc[far_future_idx, mutated.columns.get_loc("volume")] *= 50.0

        features_after, states_after, events_after = _run_pipeline(mutated, cfg)

        pd.testing.assert_frame_equal(
            features.iloc[:prefix_end], features_after.iloc[:prefix_end],
        )
        pd.testing.assert_series_equal(
            states.iloc[:prefix_end], states_after.iloc[:prefix_end],
        )

        shock_event_after = events_after.loc[events_after["t0"] == bars.index[SHOCK_INDEX]]
        assert len(shock_event_after) == 1

        labels_after = el.competing_barrier_labels(
            mutated, shock_event_after, K_DOWN, K_UP, HORIZON_DAYS, vol_window=VOL_WINDOW,
        )
        row_before, row_after = labels.iloc[0], labels_after.iloc[0]
        # sigma_t0 depends only on returns through t0 -- untouched by a bar
        # 13 rows in the future.
        assert row_after["sigma_t0"] == pytest.approx(row_before["sigma_t0"])
        assert row_after["P0"] == pytest.approx(row_before["P0"])
        assert row_after["barrier_down"] == pytest.approx(row_before["barrier_down"])
        assert row_after["barrier_up"] == pytest.approx(row_before["barrier_up"])
        assert row_after["outcome"] == row_before["outcome"]
        assert row_after["time_to_hit"] == row_before["time_to_hit"] or (
            pd.isna(row_after["time_to_hit"]) and pd.isna(row_before["time_to_hit"])
        )
        assert row_after["terminal_return"] == pytest.approx(row_before["terminal_return"])

    def test_mutating_bar_within_forward_window_changes_the_label(self, baseline):
        bars, cfg, features, states, shock_event, labels = baseline
        row_before = labels.iloc[0]

        # Force a deep DOWN breach on the very first forward bar
        # (t0+1, inside (t0, t0+HORIZON_DAYS]) -- this must flip the outcome
        # to DOWN_FIRST with time_to_hit == 1 regardless of what the
        # unmutated path happened to do.
        forced_hit_idx = SHOCK_INDEX + 1
        mutated = bars.copy(deep=True)
        deep_low = row_before["barrier_down"] - 20.0
        mutated.iloc[forced_hit_idx, mutated.columns.get_loc("low")] = deep_low
        mutated.iloc[forced_hit_idx, mutated.columns.get_loc("high")] = max(
            mutated.iloc[forced_hit_idx]["high"], deep_low + 0.5,
        )

        # states/events through t0 are unaffected by a forward mutation
        # (proven above); reuse the original event row, only the bars
        # supplied to the label scan change.
        labels_after = el.competing_barrier_labels(
            mutated, shock_event, K_DOWN, K_UP, HORIZON_DAYS, vol_window=VOL_WINDOW,
        )
        row_after = labels_after.iloc[0]

        assert row_after["outcome"] == "DOWN_FIRST"
        assert row_after["time_to_hit"] == 1
        # proof the mutation methodology has teeth: the label actually moved
        # relative to the unmutated baseline.
        changed = (
            row_after["outcome"] != row_before["outcome"]
            or row_after["time_to_hit"] != row_before["time_to_hit"]
            or not np.isclose(row_after.get("mae", np.nan), row_before.get("mae", np.nan), equal_nan=True)
        )
        assert changed
