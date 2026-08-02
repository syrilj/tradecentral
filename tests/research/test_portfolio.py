"""Property tests proving a portfolio simulator cannot book a return on the
same bar the signal was formed from.

The defect these tests exist to catch: `build_pead_catalyst_model.py` set
`long_w.iloc[i:i+h]` from `df_signal.iloc[i]` and then multiplied by
`close.pct_change(1)`, so bar `i`'s weight earned bar `i`'s own return. Because
the signal was an overnight-gap feature, and the gap is a *component* of that
same bar's close-to-close return, the simulator was booking the gap it had
already observed. It reported +502.98% net annual / Sharpe 5.38. At one bar of
execution lag the same signal returns -10.38% / Sharpe 0.03.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.portfolio import simulate_long_short


def _panel(n_dates: int = 500, n_syms: int = 24, seed: int = 7):
    """IID returns; no symbol has any forward predictability by construction."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, 0.02, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close, rets


def _top_bottom_weights(signal: pd.DataFrame, k: int = 5):
    """Equal-weight long the top k / short the bottom k of `signal` each bar."""
    rank = signal.rank(axis=1, ascending=False)
    n = signal.shape[1]
    long_w = (rank <= k).astype(float) / k
    short_w = (rank > n - k).astype(float) / k
    return long_w, short_w


def test_execution_lag_below_one_bar_is_rejected() -> None:
    """Same-bar execution is not a tunable option — it is unrepresentable."""
    close, rets = _panel()
    long_w, short_w = _top_bottom_weights(rets)
    for bad in (0, -1):
        with pytest.raises(ValueError, match="execution_lag"):
            simulate_long_short(
                long_weights=long_w, short_weights=short_w, close=close, execution_lag=bad
            )


def test_a_pure_same_bar_signal_earns_nothing() -> None:
    """The signal IS the current bar's realized return: perfect same-bar
    correlation, zero forward information. A leaking simulator prints a fortune
    here; an honest one prints noise around zero.

    This is the exact shape of the PEAD defect.
    """
    close, rets = _panel()
    long_w, short_w = _top_bottom_weights(rets)  # signal == same-bar return

    res = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close,
        execution_lag=1, cost_per_side=0.0,
    )
    # Ten equal-weighted legs of 2% daily vol -> annual return |mu| well under
    # 50% under the null. Measured: this fixture gives -8.7% / Sharpe -0.44 at
    # lag=1, and +1326% / Sharpe +101 at lag=0. The threshold is not tight.
    assert abs(res.gross_annual_return) < 0.50, (
        f"same-bar signal earned {res.gross_annual_return:.2%} annual at lag=1 — "
        "the simulator is booking the signal bar's own return"
    )
    assert abs(res.sharpe) < 1.0


def test_a_genuinely_predictive_signal_is_still_detected() -> None:
    """Guard against the trivial way to pass the test above: always return zero.
    A signal that really does predict t+1 must still show up at lag=1."""
    close, rets = _panel()
    oracle = rets.shift(-1)  # knows tomorrow
    long_w, short_w = _top_bottom_weights(oracle.fillna(0.0))

    res = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close,
        execution_lag=1, cost_per_side=0.0,
    )
    assert res.gross_annual_return > 1.0
    assert res.sharpe > 3.0


def test_unadjusted_split_prints_are_masked_and_counted() -> None:
    """edge/data/1d_wide carries unadjusted corporate actions (CHRD 2020-11-19,
    ~225x). One such print produced a +410% day and a -1262% drawdown before.
    """
    close, rets = _panel()
    close.iloc[250, 0] *= 100.0  # inject an unadjusted split print

    long_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    long_w.iloc[:, 0] = 1.0
    short_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)

    masked = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close,
        execution_lag=1, cost_per_side=0.0, max_abs_daily_return=0.50,
    )
    unmasked = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close,
        execution_lag=1, cost_per_side=0.0, max_abs_daily_return=None,
    )
    assert masked.n_extreme_masked == 2  # the jump up and the snap back
    assert unmasked.n_extreme_masked == 0
    assert abs(masked.gross_annual_return) < abs(unmasked.gross_annual_return)


def test_reported_sharpe_is_consistent_with_return_and_vol() -> None:
    """ann_return / ann_vol must equal Sharpe. When they disagree an outlier is
    inflating the series (or the return series was clipped, which is how the
    PEAD hybrid manufactured Sharpe 13.33)."""
    close, rets = _panel()
    long_w, short_w = _top_bottom_weights(rets.shift(-1).fillna(0.0))
    res = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close, execution_lag=1
    )
    assert res.gross_annual_return / res.annual_volatility == pytest.approx(
        res.gross_sharpe, rel=1e-9
    )


def test_weights_are_not_silently_realigned() -> None:
    """A signal frame whose index does not match the price frame is a bug, not
    something to reindex around."""
    close, rets = _panel()
    long_w, short_w = _top_bottom_weights(rets)
    with pytest.raises(ValueError, match="index"):
        simulate_long_short(
            long_weights=long_w.iloc[5:], short_weights=short_w, close=close
        )
