"""Tests for research.quant_core — the shared math layer pinned by spec
section 1 of docs/QUANT_RESEARCH_TABS_SPEC.md.

Synthetic Series only: no market-data files, no network, fast (<2s).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from edge.research import quant_core as qc
from edge.research.vol_targeting import ewma_volatility, realized_volatility


def _series(values, name="s", start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, name=name)


def _ar1(n, phi, sigma, seed):
    rng = np.random.default_rng(seed)
    out = np.zeros(n)
    e = rng.normal(0.0, sigma, n)
    for t in range(1, n):
        out[t] = phi * out[t - 1] + e[t]
    return out


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


def test_simple_and_log_returns_match_definitions():
    px = _series([100.0, 110.0, 99.0])
    sr = qc.simple_returns(px)
    lr = qc.log_returns(px)
    assert pd.isna(sr.iloc[0]) and pd.isna(lr.iloc[0])
    assert sr.iloc[1] == pytest.approx(0.10)
    assert sr.iloc[2] == pytest.approx(99.0 / 110.0 - 1.0)
    assert lr.iloc[1] == pytest.approx(math.log(1.10))
    # log return equals ln(1 + simple return) where both are defined
    assert lr.iloc[1] == pytest.approx(math.log1p(sr.iloc[1]))


# ---------------------------------------------------------------------------
# Rolling stats: warm-up NaN + no-lookahead
# ---------------------------------------------------------------------------


def test_rolling_mean_std_nan_before_window():
    s = _series(np.arange(10, dtype=float))
    w = 4
    rm = qc.rolling_mean(s, w)
    rs = qc.rolling_std(s, w)
    assert rm.iloc[: w - 1].isna().all() and rs.iloc[: w - 1].isna().all()
    assert not rm.iloc[w - 1 :].isna().any() and not rs.iloc[w - 1 :].isna().any()
    assert rm.iloc[3] == pytest.approx(np.mean([0, 1, 2, 3]))
    # sample std, ddof=1
    assert rs.iloc[3] == pytest.approx(np.std([0, 1, 2, 3], ddof=1))


def test_rolling_zscore_nan_until_window_and_value():
    w = 3
    s = _series([1.0, 2.0, 3.0, 100.0])
    z = qc.rolling_zscore(s, w)
    assert z.iloc[: w - 1].isna().all()
    # window [1,2,3]: mean 2, std 1 -> z = 1
    assert z.iloc[2] == pytest.approx(1.0)
    assert pd.notna(z.iloc[3])


def test_rolling_zscore_uses_only_trailing_data():
    """A future spike must not change any earlier z-score."""
    base = _ar1(200, 0.0, 1.0, seed=7)
    s = _series(base)
    w = 20
    z_trunc = qc.rolling_zscore(s.iloc[:120], w)
    # blow up the final 60 observations after the truncated sample
    spiked = s.copy()
    spiked.iloc[120:] = spiked.iloc[120:] + 50.0
    z_full = qc.rolling_zscore(spiked, w)
    pd.testing.assert_series_equal(z_trunc, z_full.iloc[:120], check_names=False)


def test_rolling_ols_beta_trailing_only_no_lookahead():
    """beta_t must not change when future data changes."""
    rng = np.random.default_rng(11)
    n, w = 200, 30
    x = _series(np.cumsum(rng.normal(0, 1, n)))
    y = 2.0 * x + _series(rng.normal(0, 0.5, n))
    beta_full = qc.rolling_ols_beta(y, x, w)
    assert beta_full.iloc[: w - 1].isna().all()
    truncated_x = x.iloc[:150]
    truncated_y = y.iloc[:150]
    beta_trunc = qc.rolling_ols_beta(truncated_y, truncated_x, w)
    pd.testing.assert_series_equal(
        beta_trunc, beta_full.iloc[:150], check_names=False
    )
    # beta_t equals the full-sample beta over the trailing window ending at t
    t = n - 1
    beta_t = beta_full.iloc[t]
    window_y = y.iloc[t - w + 1 : t + 1]
    window_x = x.iloc[t - w + 1 : t + 1]
    assert beta_t == pytest.approx(qc.beta(window_y, window_x), rel=1e-8)


# ---------------------------------------------------------------------------
# EMA / drawdown / performance
# ---------------------------------------------------------------------------


def test_ema_span_matches_pandas_and_is_causal():
    s = _series([1.0, 2.0, 3.0, 4.0])
    e = qc.ema(s, 3)
    expected = s.ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(e, expected)
    # causal: mutating the future leaves earlier values untouched
    s2 = s.copy()
    s2.iloc[-1] = 999.0
    assert (qc.ema(s2, 3).iloc[:-1] == e.iloc[:-1]).all()


def test_drawdown_and_max_drawdown():
    eq = _series([100.0, 120.0, 90.0, 110.0, 111.0])
    dd = qc.drawdown(eq)
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)  # new high
    assert dd.iloc[2] == pytest.approx(90.0 / 120.0 - 1.0)
    assert dd.iloc[3] == pytest.approx(110.0 / 120.0 - 1.0)
    assert qc.max_drawdown(eq) == pytest.approx(90.0 / 120.0 - 1.0)
    # monotonic (never falling) equity -> zero drawdown at the end
    up = _series(np.linspace(1.0, 2.0, 50))
    assert qc.max_drawdown(up) == 0.0
    assert qc.drawdown(up).iloc[-1] == 0.0


def test_sharpe_none_on_constant_and_short_series():
    assert qc.sharpe(_series([0.01] * 30)) is None  # std == 0
    assert qc.sharpe(_series([0.01])) is None  # n < 2
    assert qc.sharpe(_series([])) is None
    # zero-mean alternating returns -> sharpe exactly 0
    alt = _series([0.01, -0.01] * 25)
    assert qc.sharpe(alt) == pytest.approx(0.0)
    # hand-computed value
    r = _series([0.01, 0.02, -0.005, 0.015])
    expected = r.mean() / r.std(ddof=1) * math.sqrt(252)
    assert qc.sharpe(r) == pytest.approx(expected)


def test_cagr_trading_day_count():
    # 253 equity points -> n = 252 trading days; doubling -> exactly 100%
    eq = _series([1.0] + [1.5] * 251 + [2.0])
    assert qc.cagr(eq) == pytest.approx(2.0 ** (252 / 252) - 1.0)
    flat = _series([1.0] * 253)
    assert qc.cagr(flat) == pytest.approx(0.0)
    assert qc.cagr(_series([1.0])) is None  # no return periods
    assert qc.cagr(_series([])) is None


def test_equity_curve_starts_at_one():
    r = _series([0.10, -0.05, 0.02])
    eq = qc.equity_curve(r)
    assert eq.iloc[0] == pytest.approx(1.0)
    assert eq.iloc[-1] == pytest.approx(1.10 * 0.95 * 1.02)
    assert list(eq.index) == list(r.index)


def test_transaction_costs_first_row_is_entry_turnover():
    idx = pd.bdate_range("2024-01-01", periods=3)
    w = pd.DataFrame({"leg_a": [0.5, 0.5, 0.6], "leg_b": [-0.5, -0.5, -0.4]}, index=idx)
    costs = qc.transaction_costs(w, cost_bps=10.0)
    # first row: entry from a flat book -> |0.5| + |-0.5| = 1.0 notional
    assert costs.iloc[0] == pytest.approx(1.0 * 10.0 / 1e4)
    assert costs.iloc[1] == pytest.approx(0.0)  # no change -> no cost
    assert costs.iloc[2] == pytest.approx(0.2 * 10.0 / 1e4)  # |+0.1| + |+0.1|


# ---------------------------------------------------------------------------
# Cross-series statistics
# ---------------------------------------------------------------------------


def test_beta_recovers_known_slope_and_rejects_degenerate():
    rng = np.random.default_rng(3)
    n = 500
    x = _series(rng.normal(0, 1, n), name="x")
    y = 2.0 * x + _series(rng.normal(0, 0.1, n), name="y")
    assert qc.beta(y, x) == pytest.approx(2.0, abs=0.05)
    const = _series([5.0] * 50)
    assert qc.beta(y, const) is None  # zero variance in x
    assert qc.beta(_series([1.0, 2.0]), _series([3.0, 4.0, 5.0])) is not None
    # a single aligned observation is not enough
    assert qc.beta(_series([1.0]), _series([2.0])) is None


def test_correlation_scalar_and_rolling():
    rng = np.random.default_rng(5)
    n = 300
    x = _series(rng.normal(0, 1, n), name="x")
    assert qc.correlation(x, x) == pytest.approx(1.0)
    assert qc.correlation(x, -x) == pytest.approx(-1.0)
    noise = _series(rng.normal(0, 1, n), name="z")
    c = qc.correlation(x, noise)
    assert isinstance(c, float) and -1.0 <= c <= 1.0
    w = 30
    rc = qc.correlation(x, x, window=w)
    assert isinstance(rc, pd.Series)
    assert rc.iloc[: w - 1].isna().all()
    assert rc.dropna().iloc[0] == pytest.approx(1.0)


def test_autocorrelation_known_values():
    alt = _series([1.0, -1.0] * 30)
    assert qc.autocorrelation(alt, lag=1) == pytest.approx(-1.0)
    trend = _series([1.0, 1.1, 1.2, 1.3, 1.4, 1.5])
    # a linear trend is perfectly autocorrelated at any lag
    assert qc.autocorrelation(trend, lag=1) == pytest.approx(1.0)
    assert qc.autocorrelation(_series([3.0] * 20)) is None  # constant
    assert qc.autocorrelation(_series([1.0, 2.0])) is None  # overlap of 1


# ---------------------------------------------------------------------------
# Engle-Granger, OU half-life, Hurst
# ---------------------------------------------------------------------------


def test_engle_granger_cointegrated_rejects_harder_than_random_walks():
    rng = np.random.default_rng(42)
    n = 600
    x = np.cumsum(rng.normal(0, 1, n))  # I(1)
    stationary = _ar1(n, 0.3, 1.0, seed=99)
    y_coint = 2.0 * x + stationary  # y - 2x is stationary
    y_rw = np.cumsum(rng.normal(0, 1, n))  # independent I(1)

    res_coint = qc.engle_granger(_series(y_coint, name="y"), _series(x, name="x"))
    res_rw = qc.engle_granger(_series(y_rw, name="y"), _series(x, name="x"))

    for res in (res_coint, res_rw):
        assert set(res) == {"statistic", "p_value", "critical_values", "n_obs", "window_note"}
        assert res["n_obs"] == n
        assert res["critical_values"] == {"1%": -3.90, "5%": -3.34, "10%": -3.04}
        # p_value is a float when statsmodels is importable, else None
        assert res["p_value"] is None or 0.0 <= res["p_value"] <= 1.0
        assert isinstance(res["statistic"], float)
        assert isinstance(res["window_note"], str)

    # cointegrated pair rejects (statistic below the 5% critical value) and
    # far more strongly than the independent random-walk pair.
    assert res_coint["statistic"] < -3.34
    assert res_coint["statistic"] < res_rw["statistic"]


def test_engle_granger_short_overlap_returns_none_statistic():
    res = qc.engle_granger(_series([1.0, 2.0]), _series([1.0, 2.0]))
    assert res["statistic"] is None and res["n_obs"] == 2


def test_ou_half_life_mean_reverting_ar1():
    s = _series(_ar1(5000, 0.5, 1.0, seed=13))
    res = qc.ou_half_life(s)
    assert res["mean_reverting"] is True
    assert res["half_life"] is not None and res["half_life"] > 0
    # true half-life for phi=0.5 is ln(2)/0.5 ~ 1.386; estimator tolerance
    assert res["half_life"] == pytest.approx(1.386, abs=0.7)
    assert res["lambda"] < 0
    assert res["n_obs"] == 4999


def test_ou_half_life_random_walk_not_mean_reverting():
    rw = _series(np.cumsum(np.random.default_rng(21).normal(0, 1, 3000)))
    res = qc.ou_half_life(rw)
    assert res["mean_reverting"] is False
    assert res["half_life"] is None
    assert res["n_obs"] == 2999


def test_ou_half_life_lambda_ge_zero_not_mean_reverting():
    # explosive AR(1): lambda > 0 must never yield a half-life
    s = _series(_ar1(1000, 1.02, 0.1, seed=4))
    res = qc.ou_half_life(s)
    assert res["mean_reverting"] is False
    assert res["half_life"] is None


def test_student_t_pvalue_against_scipy_when_available():
    t, df = 2.5, 40
    ours = qc._student_t_two_sided_p(t, df)
    assert 0.0 < ours < 0.05
    scipy_stats = pytest.importorskip("scipy.stats")
    assert ours == pytest.approx(2.0 * scipy_stats.t.sf(t, df), rel=1e-6)


def test_hurst_exponent_bands_and_minimum_length():
    rng = np.random.default_rng(17)
    rw = _series(np.cumsum(rng.normal(0, 1, 4000)))
    h_rw = qc.hurst_exponent(rw)
    assert h_rw is not None and 0.35 < h_rw < 0.65
    # strongly trending (persistent) series -> H above the random-walk band
    trend = _series(np.cumsum(np.sign(rng.normal(0, 1, 4000)) * 0.5 + 0.05))
    h_trend = qc.hurst_exponent(trend)
    assert h_trend is not None
    assert h_trend > 0.6
    # mean-reverting series -> H below the random-walk value
    mr = _series(_ar1(4000, 0.0, 1.0, seed=23))
    h_mr = qc.hurst_exponent(mr)
    assert h_mr is not None
    assert h_mr < h_trend
    # n < 60 -> None
    assert qc.hurst_exponent(_series(np.arange(59, dtype=float))) is None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_to_records_nan_to_none_and_json_safe():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df = pd.DataFrame(
        {
            "a": [1.0, np.nan, 3.5],
            "b": [1, 2, 3],
            "keep": ["x", "y", None],
            "drop_me": [9.0, 9.0, 9.0],
        },
        index=idx,
    )
    recs = qc.to_records(df, ["a", "b", "keep"])
    assert len(recs) == 3
    assert recs[0]["date"] == "2024-01-01"
    assert recs[1]["date"] == "2024-01-02"
    assert recs[1]["a"] is None  # NaN -> None
    assert recs[0]["a"] == 1.0
    assert recs[2]["a"] == 3.5
    assert recs[0]["b"] == 1
    assert "drop_me" not in recs[0]  # only listed columns
    assert recs[2]["keep"] is None
    # whole payload must round-trip through json
    json.dumps(recs)


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------


def test_volatility_helpers_are_reexported_not_duplicated():
    assert qc.realized_volatility is realized_volatility
    assert qc.ewma_volatility is ewma_volatility
    assert qc.ANNUAL == 252