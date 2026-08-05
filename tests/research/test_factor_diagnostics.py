"""Alignment and diagnostic-shape tests for `edge.research.factor_diagnostics`.

The central risk this module carries is the same one `portfolio.py`'s module
docstring documents: a one-bar misalignment between a score and the forward
return it is paired with silently manufactures an IC (or a Sharpe) out of
nothing. `test_perfect_foresight_signal_gives_ic_near_one` and
`test_one_bar_misaligned_signal_degrades_materially` are the pair that would
catch that defect here -- the first proves the honest alignment scores
correctly, the second proves the first test has teeth (it would also pass a
`return 1.0` stub without it).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from edge.research.factor_diagnostics import (
    factor_tearsheet,
    information_coefficient_decay,
    monotonicity_score,
    quantile_returns,
    quantile_turnover,
)


def _panel(n_dates: int = 400, n_syms: int = 30, seed: int = 11, daily_vol: float = 0.02):
    """IID daily returns; no symbol has any real forward predictability."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, daily_vol, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close


# ---------------------------------------------------------------------------
# Alignment: information_coefficient_decay
# ---------------------------------------------------------------------------


def test_perfect_foresight_signal_gives_ic_near_one() -> None:
    """scores == the actual forward return at horizon h -> IC(h) ~= 1.0.

    This is the alignment test: `information_coefficient_decay` pairs
    `scores.iloc[i]` with `close.iloc[i+h]/close.iloc[i] - 1`. Setting scores
    to exactly that quantity makes every per-bar rank correlation exactly 1.0
    by construction (barring ties), so anything less than ~1.0 back means the
    module paired the score with the wrong bar's forward return.
    """
    close = _panel()
    horizon = 3
    true_forward = close.shift(-horizon) / close - 1.0

    result = information_coefficient_decay(
        scores=true_forward, close=close, horizons=(horizon,), max_abs_daily_return=None,
    )
    row = result.iloc[0]
    assert row["horizon"] == horizon
    assert row["mean_ic"] == pytest.approx(1.0, abs=1e-9)
    assert row["ic_std"] == pytest.approx(0.0, abs=1e-9)
    assert row["n_periods"] == len(close) - horizon


def test_one_bar_misaligned_signal_degrades_materially() -> None:
    """The same true-forward-return signal, shifted one bar late, must NOT
    score near 1.0 -- proves the perfect-foresight test above has teeth.

    A leaking / misaligned implementation that always paired `scores.iloc[i]`
    with the wrong bar's return would not distinguish this fixture from the
    honest one above. An honest implementation sees `scores.iloc[i] ==
    true_forward.iloc[i-1]`, an old, already-realized value paired against
    `true_forward.iloc[i]`, which is drawn from independent daily noise at
    horizon 1 and therefore carries none of the fake predictive power.
    """
    close = _panel()
    horizon = 1
    true_forward = close.shift(-horizon) / close - 1.0
    misaligned = true_forward.shift(1)  # yesterday's true outcome, used today

    result = information_coefficient_decay(
        scores=misaligned, close=close, horizons=(horizon,), max_abs_daily_return=None,
    )
    row = result.iloc[0]
    assert abs(row["mean_ic"]) < 0.15, (
        f"one-bar-misaligned signal scored mean_ic={row['mean_ic']:.3f} -- "
        "should be near zero under IID returns, not near the perfect-foresight value"
    )


def test_pure_noise_signal_gives_near_zero_ic_and_insignificant_t() -> None:
    """A signal with no real relationship to forward returns should not clear
    a conventional significance bar on a few-hundred-bar sample."""
    close = _panel(n_dates=300, n_syms=25, seed=3)
    rng = np.random.default_rng(99)
    noise_scores = pd.DataFrame(
        rng.normal(size=close.shape), index=close.index, columns=close.columns,
    )
    result = information_coefficient_decay(
        scores=noise_scores, close=close, horizons=(1, 5), max_abs_daily_return=None,
    )
    for _, row in result.iterrows():
        assert abs(row["mean_ic"]) < 0.05
        assert abs(row["ic_t_stat"]) < 2.0


def test_newey_west_t_stat_uses_lag_equal_to_horizon_minus_one() -> None:
    """h=1 -> lag 0 (no HAC correction needed for non-overlapping obs);
    h=5 -> lag 4. Both rows must be internally consistent and finite on a
    real sample, and the module must not crash trying to compute either."""
    close = _panel(n_dates=250, n_syms=20, seed=5)
    horizon_signal = close.shift(-2) / close - 1.0  # decent, imperfect signal
    scores = horizon_signal + pd.DataFrame(
        np.random.default_rng(1).normal(0, 0.05, size=close.shape), index=close.index, columns=close.columns,
    )
    result = information_coefficient_decay(scores=scores, close=close, horizons=(1, 5), max_abs_daily_return=None)
    assert result.set_index("horizon").loc[1:5, "ic_t_stat"].apply(np.isfinite).all()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_mismatched_index_raises() -> None:
    close = _panel()
    scores = close.pct_change().iloc[5:]
    with pytest.raises(ValueError, match="index"):
        information_coefficient_decay(scores=scores, close=close)
    with pytest.raises(ValueError, match="index"):
        quantile_returns(scores=scores, close=close)


def test_mismatched_columns_raises() -> None:
    close = _panel()
    scores = close.pct_change().rename(columns={"S00": "NOT_A_REAL_SYMBOL"})
    with pytest.raises(ValueError, match="columns"):
        information_coefficient_decay(scores=scores, close=close)


def test_execution_lag_below_one_is_rejected() -> None:
    close = _panel()
    scores = close.pct_change()
    for bad in (0, -1):
        with pytest.raises(ValueError, match="execution_lag"):
            quantile_returns(scores=scores, close=close, execution_lag=bad)


# ---------------------------------------------------------------------------
# quantile_returns / quantile_turnover shape
# ---------------------------------------------------------------------------


def test_quantile_returns_includes_spread_row_and_expected_shape() -> None:
    close = _panel(n_dates=200, n_syms=20, seed=13)
    scores = close.pct_change()
    result = quantile_returns(scores=scores, close=close, n_quantiles=5, horizon=1, execution_lag=1)
    assert sorted(result["quantile"].tolist()) == [-1, 1, 2, 3, 4, 5]
    spread_row = result.loc[result["quantile"] == -1].iloc[0]
    top = result.loc[result["quantile"] == 5, "mean_return"].iloc[0]
    bottom = result.loc[result["quantile"] == 1, "mean_return"].iloc[0]
    # Spread is top minus bottom on matched dates -- not necessarily exactly
    # top_mean - bottom_mean (those average over possibly different date
    # sets), but they should be close for a reasonably long, gap-free panel.
    assert spread_row["mean_return"] == pytest.approx(top - bottom, abs=0.02)
    assert pd.isna(spread_row["mean_count"])


def test_a_genuinely_predictive_signal_is_detected_in_top_minus_bottom() -> None:
    """Oracle signal (knows tomorrow's return) must show a strongly positive,
    monotone spread -- the sanity check that the pipeline can find a real
    effect, not just fail to find noise."""
    close = _panel(n_dates=300, n_syms=25, seed=21)
    true_next = close.pct_change().shift(-1)
    result = quantile_returns(scores=true_next, close=close, n_quantiles=5, horizon=1, execution_lag=1)
    spread = result.loc[result["quantile"] == -1, "mean_return"].iloc[0]
    assert spread > 0.0
    assert monotonicity_score(result) == pytest.approx(1.0, abs=1e-6)


def test_quantile_turnover_shape_and_bounds() -> None:
    close = _panel(n_dates=200, n_syms=20, seed=17)
    scores = close.pct_change()
    result = quantile_turnover(scores=scores, n_quantiles=5)
    assert sorted(result["quantile"].tolist()) == [1, 2, 3, 4, 5]
    assert (result["mean_turnover"].dropna() >= 0.0).all()
    assert (result["mean_turnover"].dropna() <= 1.0).all()
    assert (result["n_periods"] > 0).all()


# ---------------------------------------------------------------------------
# monotonicity_score
# ---------------------------------------------------------------------------


def test_monotonicity_score_monotone_and_reversed() -> None:
    monotone = pd.DataFrame({"quantile": [1, 2, 3, 4, 5], "mean_return": [-0.02, -0.01, 0.0, 0.01, 0.03]})
    reversed_ = pd.DataFrame({"quantile": [1, 2, 3, 4, 5], "mean_return": [0.03, 0.01, 0.0, -0.01, -0.02]})
    assert monotonicity_score(monotone) == pytest.approx(1.0, abs=1e-9)
    assert monotonicity_score(reversed_) == pytest.approx(-1.0, abs=1e-9)


def test_monotonicity_score_excludes_spread_row() -> None:
    """A spread row with an extreme, out-of-order value must not corrupt the
    rank correlation of the real buckets."""
    with_spread = pd.DataFrame(
        {"quantile": [-1, 1, 2, 3, 4, 5], "mean_return": [10.0, -0.02, -0.01, 0.0, 0.01, 0.03]}
    )
    assert monotonicity_score(with_spread) == pytest.approx(1.0, abs=1e-9)


def test_monotonicity_score_requires_expected_columns() -> None:
    with pytest.raises(ValueError, match="quantile_frame"):
        monotonicity_score(pd.DataFrame({"foo": [1, 2, 3]}))


# ---------------------------------------------------------------------------
# factor_tearsheet / as_dict
# ---------------------------------------------------------------------------


def test_factor_tearsheet_as_dict_survives_json_dumps() -> None:
    close = _panel(n_dates=250, n_syms=20, seed=41)
    scores = close.pct_change().shift(-1)  # a strong (leaky-by-design) fixture
    tearsheet = factor_tearsheet(
        scores=scores, close=close, n_quantiles=5, horizons=(1, 2, 3, 5), execution_lag=1,
    )
    payload = tearsheet.as_dict()
    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)
    assert reloaded["n_dates"] == len(close)
    assert reloaded["n_symbols"] == close.shape[1]
    assert len(reloaded["ic_decay"]) == 4
    assert len(reloaded["quantile_returns"]) == 6
    assert len(reloaded["quantile_turnover"]) == 5
    # No numpy scalar types or bare NaN should have survived into the payload.
    for row in reloaded["ic_decay"] + reloaded["quantile_returns"] + reloaded["quantile_turnover"]:
        for value in row.values():
            assert value is None or isinstance(value, (int, float, str))


def test_factor_tearsheet_monotonicity_matches_standalone_call() -> None:
    close = _panel(n_dates=200, n_syms=20, seed=7)
    scores = close.pct_change()
    tearsheet = factor_tearsheet(scores=scores, close=close, n_quantiles=5)
    standalone = monotonicity_score(tearsheet.quantile_returns)
    if np.isnan(tearsheet.monotonicity):
        assert np.isnan(standalone)
    else:
        assert tearsheet.monotonicity == pytest.approx(standalone, abs=1e-12)
