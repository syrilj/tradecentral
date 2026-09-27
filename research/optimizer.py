"""Cost-aware weight formation. Puts the trade-cost term INSIDE the objective.

`portfolio.simulate_long_short` charges `turnover_per_bar * cost_per_side`
AFTER weights are already formed (see its module docstring for the +502%/yr
lookahead this repo exists to remember). That accounting is correct, but it
gives the process that *produced* the weights no way to know costs exist: a
rank-and-cap heuristic, or an unconstrained mean-variance solve, has no reason
to prefer a neighbouring portfolio that captures 95% of the same alpha while
turning over a third as much. The repo README names the resulting failure
mode directly -- "turnover (10bp halves the edge)".

This module is the fix at the source: it solves for the weight vector that
maximizes alpha net of a risk penalty and an *L1 trade-cost penalty against
the previous holding*, so the optimizer itself is cost-aware rather than
cost-blind. Turnover reduction here is a first-order objective term, not a
post-hoc haircut.

HARD BOUNDARY -- read before adding anything to this file
---------------------------------------------------------
This module produces WEIGHTS ONLY. It never computes P&L, a return series,
Sharpe, or any GO/NO-GO verdict. All performance accounting for weights
produced here MUST go through `edge.research.portfolio.simulate_long_short`
-- that is the one audited path, and `test_portfolio_primitive_guard.py`
polices `edge/tools/` for exactly this. A second, hand-rolled accounting path
is how the +502%/yr lookahead survived un-noticed for as long as it did. Do
not add a `backtest()`, `evaluate()`, or `sharpe()` helper to this file, no
matter how convenient it looks in the moment -- wire the output of
`optimize_panel` into `simulate_long_short` instead.

Causality
---------
`optimize_panel` forms the weight at bar `i` from a covariance estimated on
returns available no later than the close of bar `i` (a trailing window
ending at `i`, inclusive). Using a centred or forward window here would
silently rebuild the exact defect `portfolio.py` documents, just one layer
upstream of where that module can see it -- `simulate_long_short` only knows
about the lag between forming a weight and earning on it; it has no way to
know whether the weight itself was formed with future information. See
`tests/research/test_optimizer.py::test_covariance_uses_no_future_data` for
the mutation test that proves this module does not do that.
"""
from __future__ import annotations

from dataclasses import dataclass

import cvxpy as cp
import numpy as np
import pandas as pd

from edge.research.portfolio import DEFAULT_COST_PER_SIDE
from edge.research.statistics import _clip_eigenvalues

# cvxpy/CLARABEL return weights with float noise on the order of 1e-9 -- 1e-7
# even on well-posed problems (e.g. a name capped at exactly `max_weight`
# resolves to `max_weight - 3e-9`). Left alone, that noise (a) makes
# `simulate_long_short`'s turnover accounting count phantom trades every bar
# a name sits at ~0, and (b) fails exact-equality-shaped tests for no
# economic reason. Snapping anything below this to exactly 0.0 removes dust
# without touching any weight large enough to matter.
_WEIGHT_DUST_TOL = 1e-6


@dataclass(frozen=True)
class OptimizerConfig:
    """Knobs for `optimize_weights` / `optimize_panel`.

    `cost_per_side` defaults to `portfolio.DEFAULT_COST_PER_SIDE` rather than
    restating the 0.0010 literal here -- the whole point of this module is
    that the cost charged during accounting (`simulate_long_short`) and the
    cost assumed while *forming* the weights must agree. A second literal
    that could drift from the first would silently reopen the mismatch this
    module exists to close.
    """

    risk_aversion: float = 1.0
    turnover_penalty: float = 1.0
    cost_per_side: float = DEFAULT_COST_PER_SIDE
    max_weight: float = 0.05
    leverage: float = 1.0
    dollar_neutral: bool = True
    solver: str = "CLARABEL"


def _symmetric_psd(covariance: pd.DataFrame, *, negative_eigenvalue_atol: float = 1e-8) -> np.ndarray:
    """Symmetrize and PSD-project a covariance estimate before it enters the solve.

    A sample covariance from a short trailing window is not guaranteed exactly
    symmetric in floating point, and can have small negative eigenvalues from
    estimation noise even though the true population covariance is PSD. cvxpy's
    `quad_form` requires a matrix it can certify as PSD and will raise on
    either defect. Reuses the same symmetrize-then-clip-eigenvalues approach as
    `statistics._clip_eigenvalues` (see that function's docstring for why a
    *materially* negative eigenvalue raises rather than getting silently
    absorbed -- the same reasoning applies here: a real break in the input
    is a caller bug worth surfacing, not a numerical artifact worth hiding).
    """
    values = covariance.to_numpy(dtype=float)
    symmetric = (values + values.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    cleaned = _clip_eigenvalues(eigenvalues, negative_eigenvalue_atol=negative_eigenvalue_atol)
    return (eigenvectors * cleaned) @ eigenvectors.T


def optimize_weights(
    *,
    alpha: pd.Series,
    prev_weights: pd.Series | None,
    covariance: pd.DataFrame | None,
    config: OptimizerConfig,
) -> pd.Series:
    """Solve one bar's weight vector.

        maximize    w'alpha - risk_aversion * w'Sigma w
                       - turnover_penalty * cost_per_side * ||w - w_prev||_1
        subject to  ||w||_1 <= leverage
                    |w_i| <= max_weight
                    sum(w) == 0                        if dollar_neutral

    `covariance=None` drops the risk term (`w'Sigma w`) entirely -- the
    objective becomes pure alpha capture net of the turnover penalty and
    constraints, nothing more. This is NOT the same as passing an identity
    matrix: identity would still penalize gross concentration (large `w_i`
    directly raises `w'Iw = sum(w_i^2)`), silently shrinking weights toward
    equal-weight even when the caller asked for no risk model at all. Passing
    `None` means exactly what it says -- no risk term, full stop.

    Alpha that is all-NaN or has zero cross-sectional variance raises rather
    than silently returning a degenerate (all-zero, or arbitrary-tiebreak)
    weight vector -- the same reasoning as
    `features.assert_no_degenerate_feature_columns`: a caller silently
    getting zeros back from a flat input is exactly the failure mode that
    lets a broken upstream feature go unnoticed while a run keeps producing
    output.

    A non-optimal solver status raises with that status in the message.
    Returning `prev_weights` or zeros on failure would let a bar silently
    fall back to stale or empty exposure while every downstream consumer
    (including `simulate_long_short`) keeps computing statistics as if
    nothing happened -- the same class of silent-fallback bug
    `assert_no_degenerate_feature_columns` exists to prevent, just at the
    solver boundary instead of the feature boundary.
    """
    if not isinstance(alpha, pd.Series):
        raise TypeError("alpha must be a pd.Series indexed by asset")
    names = alpha.index
    n = len(names)
    if n == 0:
        raise ValueError("alpha is empty -- nothing to optimize over")

    a = alpha.to_numpy(dtype=float)
    finite = np.isfinite(a)
    if not finite.any():
        raise ValueError("alpha is all-NaN -- cannot form a weight vector from no information")
    if np.nanstd(a[finite]) == 0.0:
        raise ValueError(
            "alpha has zero cross-sectional variance -- every name carries the same "
            "signal, so any weight vector the solver picks is an arbitrary tiebreak, "
            "not a reflection of the alpha"
        )
    # NaNs are legitimate (a name outside coverage that bar) and are excluded
    # from the objective by zeroing their alpha contribution and forcing their
    # weight to zero below -- they must not silently become "average" alpha.
    a = np.where(finite, a, 0.0)

    if prev_weights is None:
        w_prev = np.zeros(n)
    else:
        w_prev = prev_weights.reindex(names).fillna(0.0).to_numpy(dtype=float)

    if config.max_weight <= 0:
        raise ValueError("config.max_weight must be positive")
    if config.leverage <= 0:
        raise ValueError("config.leverage must be positive")
    if config.cost_per_side < 0:
        raise ValueError("config.cost_per_side must be non-negative")
    if config.risk_aversion < 0:
        raise ValueError("config.risk_aversion must be non-negative")
    if config.turnover_penalty < 0:
        raise ValueError("config.turnover_penalty must be non-negative")

    w = cp.Variable(n)
    objective = w @ a - config.turnover_penalty * config.cost_per_side * cp.norm1(w - w_prev)

    if covariance is not None:
        if not isinstance(covariance, pd.DataFrame):
            raise TypeError("covariance must be a pd.DataFrame indexed/columned by asset")
        sigma_df = covariance.reindex(index=names, columns=names)
        if sigma_df.isna().to_numpy().any():
            raise ValueError("covariance has missing entries after reindexing to alpha's index")
        sigma = _symmetric_psd(sigma_df)
        objective = objective - config.risk_aversion * cp.quad_form(w, cp.psd_wrap(sigma))

    constraints = [
        cp.norm1(w) <= config.leverage,
        cp.abs(w) <= config.max_weight,
    ]
    if not finite.all():
        # Names with no alpha this bar are held at exactly zero -- there is
        # nothing informing a nonzero position in them.
        constraints.append(w[~finite] == 0)
    if config.dollar_neutral:
        constraints.append(cp.sum(w) == 0)

    problem = cp.Problem(cp.Maximize(objective), constraints)
    try:
        problem.solve(solver=config.solver)
    except cp.error.SolverError as exc:
        raise RuntimeError(f"solver {config.solver!r} raised for this bar: {exc}") from exc

    if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        raise RuntimeError(
            f"optimizer did not reach an optimal solution (status={problem.status!r}); "
            "refusing to fall back to previous weights or zeros -- see optimize_weights "
            "docstring for why a silent fallback here is exactly the bug class "
            "assert_no_degenerate_feature_columns exists to prevent"
        )

    values = np.asarray(w.value, dtype=float)
    # See _WEIGHT_DUST_TOL above -- snap solver noise to exact zero.
    values = np.where(np.abs(values) < _WEIGHT_DUST_TOL, 0.0, values)
    return pd.Series(values, index=names, name=alpha.name)


def optimize_panel(
    *,
    alpha: pd.DataFrame,
    close: pd.DataFrame,
    config: OptimizerConfig,
    covariance_window: int = 120,
    rebalance_every: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `optimize_weights` bar-by-bar over a panel.

    Returns `(long_weights, short_weights)` in exactly the shape
    `simulate_long_short` expects: both frames share `close`'s index and
    columns, and `short_weights` holds POSITIVE magnitudes (that function
    subtracts the short leg itself -- see its docstring). A solved weight
    `w_i < 0` for a name is therefore split into `long=0, short=|w_i|`, and
    `w_i > 0` into `long=w_i, short=0`; the two frames are never both nonzero
    for the same name/bar.

    Causality (read this before changing `covariance_window` handling): the
    covariance used to form the weight at bar `i` is estimated from
    `close.pct_change()` over the trailing window `(i - covariance_window,
    i]` -- i.e. it uses returns available no later than the close of bar `i`,
    the same boundary `simulate_long_short` enforces one level up via
    `execution_lag`. A centred or forward window here would let the
    covariance at bar `i` see returns realised after bar `i`, which is the
    same lookahead shape as the PEAD defect, just moved into the risk
    estimate instead of the alpha. `test_covariance_uses_no_future_data`
    mutates `close` strictly after bar `i` and asserts the weight at `i` is
    unchanged -- and is itself verified to fail against a centred window, so
    it is not merely decorative.

    Bars before `covariance_window` full trailing returns are available fall
    back to `covariance=None` (see `optimize_weights` for what that drops)
    rather than a partial-window estimate, which would be noisier and would
    make the causality boundary above harder to state precisely (a
    same-length window that changes size at the start of history invites
    exactly the kind of off-by-one this repo's docstrings keep warning
    about).

    `rebalance_every > 1` solves fresh weights only every `rebalance_every`
    bars and holds the previous bar's weights on the bars in between -- a
    direct turnover lever, since a held weight contributes zero to the L1
    trade-cost term at every bar it is merely carried forward rather than
    re-solved.
    """
    if not isinstance(alpha, pd.DataFrame):
        raise TypeError("alpha must be a DataFrame")
    if not alpha.index.equals(close.index):
        raise ValueError(
            "alpha.index does not match close.index -- align explicitly; silently "
            "reindexing here would shift which bar's information forms which weight"
        )
    missing = alpha.columns.difference(close.columns)
    if len(missing):
        raise ValueError(f"alpha has {len(missing)} columns absent from close, e.g. {list(missing[:5])}")
    if covariance_window < 2:
        raise ValueError("covariance_window must be >= 2 (need at least 2 returns to estimate variance)")
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be >= 1")

    columns = close.columns
    returns = close[columns].astype(float).pct_change()

    long_weights = pd.DataFrame(0.0, index=close.index, columns=columns)
    short_weights = pd.DataFrame(0.0, index=close.index, columns=columns)

    prev_solved: pd.Series | None = None  # last *solved* weight, fed as w_prev to the next solve
    held: pd.Series | None = None  # weight actually reported for the current bar (solved or carried)

    for i in range(len(close.index)):
        if i % rebalance_every == 0:
            row = alpha.iloc[i].reindex(columns)
            covered = row.dropna().index
            if len(covered) == 0:
                w = pd.Series(0.0, index=columns)
            else:
                # Trailing window ending at bar i INCLUSIVE -- see causality
                # note in the docstring above. `returns.iloc[i]` is
                # `close.iloc[i]/close.iloc[i-1] - 1`, itself known no later
                # than the close of bar i, so including it is still honest.
                # Only a FULL trailing window is used (start == i -
                # covariance_window + 1 >= 0); a shorter window at the start
                # of history falls back to covariance=None rather than
                # estimating on fewer than covariance_window observations
                # (see docstring: this keeps the causality boundary a single
                # simple statement instead of a window that changes size).
                start = i - covariance_window + 1
                if start < 0:
                    cov_full = None
                else:
                    window = returns.iloc[start : i + 1][covered]
                    usable_cols = window.columns[window.notna().sum() >= 2]
                    if len(usable_cols) >= 2:
                        # Listwise deletion: pandas' default pairwise .cov()
                        # is not guaranteed positive semi-definite when names
                        # have different NaN patterns (e.g. PIT universe gaps),
                        # and _symmetric_psd correctly raises on a materially
                        # negative eigenvalue. A sample covariance over the
                        # rows where every usable name has a return is PSD by
                        # construction.
                        sub = window[usable_cols].dropna()
                        if len(sub) >= 2:
                            cov = sub.cov()
                            cov_full = cov.reindex(index=covered, columns=covered)
                        else:
                            cov_full = None
                    else:
                        cov_full = None

                sub_alpha = row[covered]
                sub_prev = prev_solved.reindex(covered).fillna(0.0) if prev_solved is not None else None
                solved_sub = optimize_weights(
                    alpha=sub_alpha,
                    prev_weights=sub_prev,
                    covariance=cov_full,
                    config=config,
                )
                w = solved_sub.reindex(columns).fillna(0.0)
            prev_solved = w
            held = w
        # else: held stays whatever it was on the last solved bar (a plain
        # carry-forward, not a re-solve) -- this is the rebalance_every lever.

        long_weights.iloc[i] = held.clip(lower=0.0).to_numpy()
        short_weights.iloc[i] = (-held.clip(upper=0.0)).to_numpy()

    return long_weights, short_weights
