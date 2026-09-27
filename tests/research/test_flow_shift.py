"""Causal flow-shift detector: prefix-consistency, incremental=batch, honest confidence."""
from __future__ import annotations

import pytest

from edge.research.flow_shift import (
    FlowShiftConfig,
    current_flow_after_shift,
    detect_flow_shift_at,
    detect_flow_shift_series,
    empty_flow_shift_state,
    score_flow_confidence,
    signed_observations_from_bars,
    update_flow_shift,
)


def test_one_sided_series_never_flags_a_shift():
    values = [1.0] * 12
    series = detect_flow_shift_series(values)
    assert series
    assert all(not snap.shifted for snap in series)
    assert all(snap.last_shift_index is None for snap in series)
    assert series[-1].post_imbalance == pytest.approx(1.0)
    assert series[-1].regime_sign == 1


def test_prefix_before_reversal_does_not_report_the_later_shift():
    values = [1.0] * 8 + [-1.0] * 6
    reversal = 8
    pre = detect_flow_shift_at(values, end=reversal)
    assert pre is not None
    assert pre.shifted is False
    assert pre.last_shift_index is None
    assert pre.post_imbalance > 0

    at = detect_flow_shift_at(values, end=reversal + 1)
    assert at is not None
    assert at.shifted is True
    assert at.last_shift_index == reversal
    assert at.post_imbalance < 0

    after = detect_flow_shift_at(values, end=len(values))
    assert after is not None
    assert after.last_shift_index == reversal
    assert after.post_imbalance < 0
    # The confirming step is the only one that newly flags; later steps keep
    # the last_shift_index without re-firing unless flow flips again.
    rest = detect_flow_shift_series(values)
    assert rest[reversal].shifted is True
    assert all(not snap.shifted for snap in rest[reversal + 1:])


def test_incremental_updates_match_batch_to_t():
    values = [1.0, 1.0, 1.0, 1.0, 0.2, 1.0, -1.0, -1.0, -0.5, 1.0]
    batch = detect_flow_shift_series(values)
    state = empty_flow_shift_state()
    for i, value in enumerate(values):
        state = update_flow_shift(state, value)
        assert state.n == i + 1
        assert state.shifted == batch[i].shifted
        assert state.last_shift_index == batch[i].last_shift_index
        assert state.post_imbalance == pytest.approx(batch[i].post_imbalance)
        assert state.regime_sign == batch[i].regime_sign
        assert state.post_n == batch[i].post_n


def test_persistence_break_resets_stale_imbalance_without_a_clean_flip():
    values = [1.0] * 8 + [0.0] * 6
    series = detect_flow_shift_series(values)
    # Still one-sided at the last pre-quiet bar.
    assert series[7].shifted is False
    assert series[7].post_imbalance == pytest.approx(1.0)
    breaks = [snap for snap in series if snap.shifted and snap.shift_kind == "persistence"]
    assert breaks, "quieting after a locked regime must break persistence"
    last = series[-1]
    assert last.last_shift_index is not None
    assert abs(last.post_imbalance) < 1.0


def test_thin_stale_and_pre_shift_cannot_be_high_confidence():
    thin = current_flow_after_shift([1.0, 1.0])
    assert thin.thin is True
    assert thin.confidence_band != "high"
    assert thin.confidence == pytest.approx(2.0 / 8.0)
    assert "thin_sample" in thin.confidence_reasons

    stale = current_flow_after_shift([1.0] * 12, last_age=10.0, max_fresh_age=2.0)
    assert stale.stale is True
    assert stale.confidence_band != "high"
    assert stale.confidence == pytest.approx(0.0)
    assert "stale" in stale.confidence_reasons

    just_flipped = current_flow_after_shift([1.0] * 8 + [-1.0])
    assert just_flipped.shifted is True
    assert just_flipped.confidence_band != "high"
    assert "pre_shift_or_warmup" in just_flipped.confidence_reasons


def test_high_and_low_confidence_buckets_are_scored_separately():
    high = current_flow_after_shift([1.0] * 12, last_age=0.0, max_fresh_age=2.0)
    low = current_flow_after_shift([1.0], last_age=30.0, max_fresh_age=2.0)
    assert high.confidence_band == "high"
    assert low.confidence_band == "low"
    assert high.confidence > low.confidence
    # The two buckets must remain distinct objects in a caller-side split.
    rows = [high, low]
    high_bucket = [row for row in rows if row.confidence_band == "high"]
    low_bucket = [row for row in rows if row.confidence_band == "low"]
    assert len(high_bucket) == 1 and len(low_bucket) == 1
    assert high_bucket[0].n_post_shift != low_bucket[0].n_post_shift


def test_post_shift_imbalance_ignores_pre_shift_mass():
    values = [1.0] * 10 + [-1.0] * 10
    readout = current_flow_after_shift(values)
    assert readout.signed_imbalance == pytest.approx(-1.0)
    assert readout.last_shift_index == 10
    # Full-window net would be 0; post-shift must not collapse to that.
    assert readout.signed_imbalance != 0.0


def test_score_flow_confidence_hard_blocks_high_band():
    conf, band, reasons, stale, thin = score_flow_confidence(
        n=20,
        n_post_shift=20,
        shifted_now=False,
        last_shift_index=None,
        last_age=0.0,
        max_fresh_age=2.0,
    )
    assert band == "high"
    assert not reasons and not stale and not thin

    _, blocked, blocked_reasons, _, _ = score_flow_confidence(
        n=20,
        n_post_shift=20,
        shifted_now=True,
        last_shift_index=19,
        last_age=0.0,
        max_fresh_age=2.0,
    )
    assert blocked != "high"
    assert "pre_shift_or_warmup" in blocked_reasons


def test_signed_observations_from_bars_use_shipped_clv_proxy():
    import pandas as pd

    from edge.research.flow_state import signed_volume_proxy

    idx = pd.bdate_range("2024-01-02", periods=4)
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [11.0, 10.5, 12.0, 10.2],
            "low": [9.0, 9.5, 10.0, 9.8],
            "close": [11.0, 9.5, 12.0, 10.0],
            "volume": [100.0, 100.0, 100.0, 100.0],
        },
        index=idx,
    )
    got = signed_observations_from_bars(bars)
    expected = [float(x) for x in signed_volume_proxy(bars).to_numpy()]
    assert got == expected
    assert got[0] > 0
    assert got[1] < 0


def test_no_lookahead_future_bar_cannot_move_prefix_shift():
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range("2024-01-02", periods=16)
    close = np.linspace(100.0, 108.0, 16)
    close[12:] = np.linspace(108.0, 96.0, 4)
    bars = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(16, 1_000_000.0),
        },
        index=idx,
    )
    cut = 10
    prefix_obs = signed_observations_from_bars(bars.iloc[:cut])
    full_obs = signed_observations_from_bars(bars)
    prefix = detect_flow_shift_series(prefix_obs)
    full_to_cut = detect_flow_shift_series(full_obs[:cut])
    assert [snap.post_imbalance for snap in prefix] == [snap.post_imbalance for snap in full_to_cut]
    assert [snap.shifted for snap in prefix] == [snap.shifted for snap in full_to_cut]
    mutated = bars.copy()
    mutated.iloc[cut:, mutated.columns.get_loc("close")] = 50.0
    mutated_obs = signed_observations_from_bars(mutated)
    mutated_prefix = detect_flow_shift_series(mutated_obs[:cut])
    assert [snap.post_imbalance for snap in mutated_prefix] == [snap.post_imbalance for snap in prefix]


def test_custom_confirm_delays_the_flag_but_prefix_stays_clean():
    cfg = FlowShiftConfig(min_regime=3, confirm=2)
    values = [1.0, 1.0, 1.0, 1.0, -1.0, -1.0]
    series = detect_flow_shift_series(values, cfg=cfg)
    assert series[3].shifted is False
    assert series[4].shifted is False
    assert series[5].shifted is True
    assert detect_flow_shift_at(values, end=5, cfg=cfg).shifted is False
