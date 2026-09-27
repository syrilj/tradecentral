"""Native factor tearsheet diagnostics: where does a cross-sectional edge live?

A Rank IC of 0.033 (Newey-West t 2.68) is a single scalar. It cannot say
whether that edge is concentrated in the top/bottom decile -- cheap to hold,
survives realistic turnover -- or spread evenly across the cross-section,
in which case a live book would need to touch nearly every name every bar to
collect it, and transaction costs eat it before it clears the tape. This
module answers that question with three complementary cuts (IC term
structure, quantile-bucket returns, and per-bucket turnover) plus one summary
number (monotonicity) that says whether the ranking is real or a lucky tail.

Conventions -- read `edge/research/portfolio.py`'s module docstring before
touching this file
--------------------------------------------------------------------------
`portfolio.py` documents a shipped bug that turned a -10%/yr honest result
into a reported +502%/yr by crediting a signal formed from bar `i`'s own
close with bar `i`'s own return. Every forward-return computation in this
module obeys the same rule: `scores.iloc[i]` is information available no
later than the close of bar `i`, and the earliest return it may be credited
with starts at that same close, i.e. `close.iloc[i+1]/close.iloc[i] - 1` at
minimum (horizon >= 1 bar, or `execution_lag` bars in `quantile_returns` for
the reasons given on that function). There is no code path in this module
that lets a score earn its own formation bar's return -- the same discipline
`simulate_long_short` enforces by construction, not by convention.

Corporate-action masking uses the identical mechanism and threshold as
`simulate_long_short`'s `max_abs_daily_return` (default 0.50): a daily return
whose magnitude exceeds the threshold is treated as a data error (unadjusted
splits, e.g. CHRD 2020-11-19 ~225x, are known to exist in `edge/data/1d_wide`)
and zeroed rather than compounded into every multi-bar forward return that
happens to span it. Return series computed here are never clipped for the
same reason `portfolio.py` never clips: clipping shrinks the denominator of a
Sharpe-like ratio while leaving a lookahead free to inflate the numerator,
which is precisely how the PEAD hybrid manufactured a Sharpe of 13.33.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DEFAULT_MAX_ABS_DAILY_RETURN = 0.50

# A per-bar Spearman correlation needs at least a handful of names to mean
# anything; below this, one tied pair can swing the correlation from -1 to
# +1. Bars with fewer valid (score, forward-return) pairs than this are
# dropped from the IC series entirely rather than counted as a noisy zero,
# mirroring `cross_sectional_rank_ic`'s `min_names` gate in `portfolio.py`
# (that function defaults to 20 for a much larger production universe; 3 is
# the floor below which a Spearman correlation is not a statistic at all).
MIN_NAMES_FOR_IC = 3


def _validate_frames(scores: pd.DataFrame, close: pd.DataFrame) -> None:
    """Same non-negotiable check as `portfolio.py`'s `_check_frame`.

    Silently reindexing `scores` onto `close`'s index (or vice versa) would
    shift every score-to-return pairing in this module by an unknown number
    of bars -- exactly the class of bug `portfolio.py`'s docstring is about,
    just one keystroke away (`.reindex(...)` where an equality check belongs).
    Raising here means that bug cannot happen silently.
    """
    if not isinstance(scores, pd.DataFrame):
        raise TypeError("scores must be a DataFrame")
    if not isinstance(close, pd.DataFrame):
        raise TypeError("close must be a DataFrame")
    if not scores.index.equals(close.index):
        raise ValueError(
            f"scores.index does not match close.index ({len(scores.index)} vs "
            f"{len(close.index)} rows). Align explicitly before calling -- silent "
            "reindexing here would shift score-to-return attribution by an unknown "
            "number of bars (see edge/research/portfolio.py)."
        )
    missing = pd.Index(scores.columns).difference(close.columns)
    if len(missing):
        raise ValueError(
            f"scores has {len(missing)} columns absent from close, e.g. "
            f"{list(missing[:5])}"
        )


def _masked_daily_returns(
    close: pd.DataFrame, max_abs_daily_return: float | None,
) -> pd.DataFrame:
    """Bar-over-bar returns with data-error bars zeroed, mirroring `portfolio.py`.

    Identical two-step mask used by `simulate_long_short`: flag `|return| >
    max_abs_daily_return` as a data error (not a real move) and zero it, then
    treat any remaining NaN (missing print, not-yet-listed symbol) as a
    zero-return bar too. The second step matters here specifically: multi-bar
    forward returns are built by compounding this series (see
    `_growth_index`), and an unmasked NaN would poison every window's product
    downstream of it, not just the bar where data happened to be missing.
    """
    daily_ret = close.pct_change(1)
    if max_abs_daily_return is not None:
        extreme = daily_ret.abs() > float(max_abs_daily_return)
        daily_ret = daily_ret.mask(extreme, 0.0)
    return daily_ret.fillna(0.0)


def _growth_index(close: pd.DataFrame, max_abs_daily_return: float | None) -> pd.DataFrame:
    """Cumulative-product index built from masked daily returns.

    `growth.iloc[b] / growth.iloc[a] - 1` reproduces the compounded return
    over `[a, b]` with data-error bars excluded, without ever materializing a
    "corrected price" that would need its own corporate-action adjustment
    logic. Every symbol starts its own index at 1.0 on row 0, which is
    immaterial: only ratios between two rows are ever read back out.
    """
    daily_ret = _masked_daily_returns(close, max_abs_daily_return)
    return (1.0 + daily_ret).cumprod()


def _newey_west_t_stat(ic: np.ndarray, lag: int) -> float:
    """HAC t-stat for the mean of `ic`, Bartlett-weighted, truncation `lag`.

    Adjacent h-bar-ahead IC observations share `h - 1` return days by
    construction (bar `i`'s forward window and bar `i+1`'s forward window
    overlap everywhere except the endpoints), so the IC series at horizon `h`
    is autocorrelated up to lag `h - 1` even under a perfectly stable
    relationship. An i.i.d. standard error ignores that overlap and
    understates itself, inflating the t-stat in exactly the direction that
    matters for a GO/NO-GO call -- the same direction two of this repo's
    retracted gates (`GATE_XS3_RESULT.md`, `GATE_PEAD_RESULT.md`) were wrong
    in. Newey & West (1987) is the standard correction; it is implemented by
    hand because statsmodels is not an available dependency in this
    environment.

    var = gamma_0 + 2 * sum_{l=1..lag} (1 - l/(lag+1)) * gamma_l
    t   = mean(ic) / sqrt(var / n)
    """
    n = int(ic.size)
    if n < 2:
        return float("nan")
    demeaned = ic - ic.mean()
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    var = gamma0
    usable_lag = min(lag, n - 1)
    for l in range(1, usable_lag + 1):
        gamma_l = float(np.dot(demeaned[l:], demeaned[:-l]) / n)
        weight = 1.0 - l / (lag + 1)
        var += 2.0 * weight * gamma_l
    # The Bartlett kernel guarantees a non-negative HAC variance estimate in
    # population; a tiny negative value here is floating-point noise on a
    # near-constant IC series, not evidence of a broken formula.
    var = max(var, 0.0)
    if var <= 0.0:
        return float("nan")
    se = math.sqrt(var / n)
    if se <= 0.0 or not math.isfinite(se):
        return float("nan")
    return float(ic.mean() / se)


def _ic_row(horizon: int, ics: list[float]) -> dict[str, Any]:
    if not ics:
        return {
            "horizon": int(horizon), "mean_ic": float("nan"), "ic_std": float("nan"),
            "ic_t_stat": float("nan"), "ic_ir": float("nan"), "n_periods": 0,
            "pct_positive": float("nan"),
        }
    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    lag = max(0, int(horizon) - 1)
    return {
        "horizon": int(horizon),
        "mean_ic": mean,
        "ic_std": std,
        "ic_t_stat": _newey_west_t_stat(arr, lag),
        "ic_ir": float(mean / std) if std > 0 else 0.0,
        "n_periods": int(arr.size),
        "pct_positive": float((arr > 0).mean()),
    }


def information_coefficient_decay(
    *,
    scores: pd.DataFrame,
    close: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 2, 3, 5, 10, 20),
    method: str = "spearman",
    max_abs_daily_return: float | None = DEFAULT_MAX_ABS_DAILY_RETURN,
) -> pd.DataFrame:
    """Per-horizon cross-sectional IC with Newey-West-corrected significance.

    `scores.iloc[i]` is the cross-sectional signal formed from information
    available no later than the close of bar `i`. For horizon `h`, the
    forward return paired with it is `close.iloc[i+h] / close.iloc[i] - 1`
    (see `_growth_index`, which builds this ratio from data-error-masked
    daily returns rather than raw `close`). This is the honest alignment: a
    score formed at bar `i` earns starting from bar `i`'s own close, the
    earliest point at which it could possibly be acted on, and horizon `h=1`
    reproduces exactly `simulate_long_short`'s `execution_lag=1` convention
    (`held.iloc[i+1] earns close[i+1]/close[i] - 1`). If the pairing were off
    by one bar in either direction the perfect-foresight test in
    `test_factor_diagnostics.py` (scores = true forward return) would not
    return IC ~= 1.0 -- that test exists specifically to make a one-bar
    misalignment here visible instead of silently shipping.

    Returns one row per horizon: `horizon`, `mean_ic`, `ic_std`, `ic_t_stat`
    (HAC, lag = h-1), `ic_ir` (mean/std, NOT annualized -- these are
    per-observation IC statistics, not a return series), `n_periods`,
    `pct_positive`.
    """
    _validate_frames(scores, close)
    if method not in ("spearman", "pearson"):
        raise ValueError(f"method must be 'spearman' or 'pearson', got {method!r}")
    for h in horizons:
        if h < 1:
            raise ValueError(f"horizons must all be >= 1, got {h}")

    px = close[scores.columns].astype(float)
    growth = _growth_index(px, max_abs_daily_return)

    rows: list[dict[str, Any]] = []
    n = len(scores)
    for h in horizons:
        forward = growth.shift(-h) / growth - 1.0
        ics: list[float] = []
        for i in range(max(0, n - h)):
            a = scores.iloc[i]
            b = forward.iloc[i]
            valid = a.notna() & b.notna()
            if int(valid.sum()) < MIN_NAMES_FOR_IC:
                continue
            corr = a[valid].corr(b[valid], method=method)
            if pd.notna(corr):
                ics.append(float(corr))
        rows.append(_ic_row(h, ics))
    return pd.DataFrame(
        rows,
        columns=["horizon", "mean_ic", "ic_std", "ic_t_stat", "ic_ir", "n_periods", "pct_positive"],
    )


def _assign_quantiles(scores: pd.DataFrame, n_quantiles: int) -> pd.DataFrame:
    """Per-date cross-sectional bucket, 1 = lowest score .. `n_quantiles` = highest.

    Buckets are assigned from rank fraction (`ceil(rank / count * n_quantiles)`)
    rather than `pd.qcut` on raw score values, because `qcut` raises on
    non-unique bin edges -- routine with a discretized or clipped signal where
    many names tie at the same score. Ties are broken by first-seen order
    (`rank(method="first")`), which keeps bucket sizes as close to equal as
    integer division allows on every date, independent of how many names tie.

    A date with fewer than `n_quantiles` valid (non-null) scores cannot be
    partitioned into `n_quantiles` non-empty buckets, so every symbol on that
    date is left unassigned (NaN) rather than guessing; downstream aggregation
    (`quantile_returns`, `quantile_turnover`) drops NaN bucket membership
    automatically.
    """
    if n_quantiles < 2:
        raise ValueError(f"n_quantiles must be >= 2, got {n_quantiles}")

    def _bucket_row(row: pd.Series) -> pd.Series:
        valid = row.dropna()
        out = pd.Series(np.nan, index=row.index)
        if valid.size < n_quantiles:
            return out
        ranks = valid.rank(method="first")
        buckets = np.ceil(ranks / valid.size * n_quantiles).clip(upper=n_quantiles)
        out.loc[valid.index] = buckets
        return out

    return scores.astype(float).apply(_bucket_row, axis=1)


def _quantile_row(
    quantile: int, values: np.ndarray, counts: np.ndarray, periods_per_year: float,
) -> dict[str, Any]:
    n_obs = int(values.size)
    mean_count = float(counts.mean()) if counts.size else float("nan")
    if n_obs == 0:
        return {
            "quantile": int(quantile), "mean_return": float("nan"), "std_return": float("nan"),
            "sharpe": float("nan"), "n_obs": 0, "mean_count": mean_count,
        }
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if n_obs > 1 else 0.0
    sharpe = float(mean / std * math.sqrt(periods_per_year)) if std > 0 else 0.0
    return {
        "quantile": int(quantile), "mean_return": mean, "std_return": std,
        "sharpe": sharpe, "n_obs": n_obs, "mean_count": mean_count,
    }


def quantile_returns(
    *,
    scores: pd.DataFrame,
    close: pd.DataFrame,
    n_quantiles: int = 5,
    horizon: int = 1,
    execution_lag: int = 1,
    max_abs_daily_return: float | None = DEFAULT_MAX_ABS_DAILY_RETURN,
) -> pd.DataFrame:
    """Equal-weight forward return of each cross-sectional score bucket.

    `execution_lag` bars pass between forming the bucket assignment from
    `scores.iloc[i]` and entering the position -- the identical invariant
    `simulate_long_short` enforces, for the identical reason: a bucket
    assignment formed from bar `i`'s own features cannot be credited with a
    return that starts before or during bar `i` itself. `execution_lag < 1`
    is therefore not a permissive default here either; it raises before any
    return is computed, matching `edge/research/portfolio.py`'s
    `simulate_long_short`, which raises on exactly the same condition for
    exactly the same reason.

    The bucket's forward return over `[i + execution_lag - 1, i + execution_lag
    - 1 + horizon]` (in growth-index terms; see `_growth_index`) generalizes
    that convention to an `horizon`-bar hold: `execution_lag=1, horizon=1`
    reproduces `close[i+1]/close[i] - 1`, identical to
    `information_coefficient_decay`'s `h=1` and to `simulate_long_short`'s
    `execution_lag=1`. `execution_lag=2` shifts the entire hold one bar later,
    matching `simulate_long_short`'s documented use of `execution_lag=2` "when
    the signal cannot be acted on until the following session's close."

    Returns one row per quantile (`quantile` 1..`n_quantiles`, low to high)
    with `mean_return`, `std_return`, `sharpe` (annualized at
    `TRADING_DAYS/horizon`), `n_obs`, `mean_count` (average bucket
    membership), plus one `quantile=-1` spread row (top bucket minus bottom
    bucket, same-date pairing) with `mean_count` left NaN -- a spread is a
    difference of two buckets' returns, not itself a name count.
    """
    _validate_frames(scores, close)
    if not isinstance(execution_lag, (int, np.integer)) or isinstance(execution_lag, bool):
        raise TypeError("execution_lag must be an int")
    if execution_lag < 1:
        raise ValueError(
            f"execution_lag must be >= 1, got {execution_lag}. A bucket formed from "
            "bar i's own features cannot earn bar i's own return -- see "
            "edge/research/portfolio.py, whose simulate_long_short raises on this "
            "identical condition for the identical reason."
        )
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")

    px = close[scores.columns].astype(float)
    growth = _growth_index(px, max_abs_daily_return)
    shift = execution_lag - 1
    entry = growth.shift(-shift)
    exit_ = growth.shift(-(shift + horizon))
    forward = exit_ / entry - 1.0

    buckets = _assign_quantiles(scores, n_quantiles)
    periods_per_year = TRADING_DAYS / horizon

    per_quantile_daily: dict[int, pd.Series] = {}
    rows: list[dict[str, Any]] = []
    for q in range(1, n_quantiles + 1):
        mask = buckets == q
        count = mask.sum(axis=1)
        row_mean = forward.where(mask).mean(axis=1).where(count > 0)
        per_quantile_daily[q] = row_mean
        rows.append(
            _quantile_row(
                q,
                row_mean.dropna().to_numpy(dtype=float),
                count.where(count > 0).dropna().to_numpy(dtype=float),
                periods_per_year,
            )
        )

    spread = (per_quantile_daily[n_quantiles] - per_quantile_daily[1]).dropna()
    rows.append(
        _quantile_row(-1, spread.to_numpy(dtype=float), np.asarray([], dtype=float), periods_per_year)
    )
    return pd.DataFrame(
        rows, columns=["quantile", "mean_return", "std_return", "sharpe", "n_obs", "mean_count"],
    )


def quantile_turnover(*, scores: pd.DataFrame, n_quantiles: int = 5) -> pd.DataFrame:
    """Mean fraction of each bucket's membership that turns over bar-over-bar.

    This is the number that prices out `quantile_returns`: a bucket whose
    return looks attractive but whose membership churns 80% every bar is not
    a 20%-turnover bucket with a good return, it is a bucket that must be
    almost fully re-transacted every period, and realistic per-side costs
    (`DEFAULT_COST_PER_SIDE` in `portfolio.py`) will eat a "spread cheap to
    hold" story that this function alone would not catch.

    For each quantile, turnover on date `t` is `|members(t-1) \\ members(t)|
    / |members(t-1)|` -- the fraction of names that were in the bucket on the
    previous date and are not on this one. Dates with an empty prior bucket
    (including the first date, which has no `t-1`) contribute no observation
    rather than a spurious NaN-derived value.
    """
    if not isinstance(scores, pd.DataFrame):
        raise TypeError("scores must be a DataFrame")
    buckets = _assign_quantiles(scores, n_quantiles)

    rows: list[dict[str, Any]] = []
    for q in range(1, n_quantiles + 1):
        member = buckets == q
        prev_member = member.shift(1, fill_value=False)
        prev_count = prev_member.sum(axis=1)
        left = (prev_member & ~member).sum(axis=1)
        turnover = (left / prev_count.replace(0, np.nan)).dropna()
        rows.append(
            {
                "quantile": int(q),
                "mean_turnover": float(turnover.mean()) if len(turnover) else float("nan"),
                "median_turnover": float(turnover.median()) if len(turnover) else float("nan"),
                "n_periods": int(len(turnover)),
            }
        )
    return pd.DataFrame(rows, columns=["quantile", "mean_turnover", "median_turnover", "n_periods"])


def monotonicity_score(quantile_frame: pd.DataFrame) -> float:
    """Spearman correlation between bucket index and bucket mean return.

    +1.0 means the buckets rank in the same order as their returns, exactly
    -- a real, monotone cross-sectional ranking. A high mean IC with a low
    monotonicity score is the signature this module exists to surface: the
    edge is not a clean ranking, it is a lucky tail (one or two buckets doing
    all the work while the middle is noise), which behaves very differently
    under turnover and capacity than a genuinely monotone factor does.

    Only rows with `quantile >= 1` are used -- the `quantile == -1` spread
    row from `quantile_returns` is a derived difference, not a rung on the
    same ladder, and including it would corrupt the rank correlation with a
    value that was never assigned a consistent ordinal position.
    """
    if not isinstance(quantile_frame, pd.DataFrame):
        raise TypeError("quantile_frame must be a DataFrame")
    required = {"quantile", "mean_return"}
    missing = required.difference(quantile_frame.columns)
    if missing:
        raise ValueError(f"quantile_frame missing required columns: {sorted(missing)}")

    real = quantile_frame.loc[quantile_frame["quantile"] >= 1, ["quantile", "mean_return"]].dropna()
    if len(real) < 2:
        return float("nan")
    corr = real["quantile"].corr(real["mean_return"], method="spearman")
    return float(corr) if pd.notna(corr) else float("nan")


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """`frame.to_dict(orient="records")`, but json.dump-safe.

    Plain `to_dict` leaves numpy scalar dtypes (`np.float64`, `np.int64`) in
    the output, which `json.dumps` cannot serialize, and leaves NaN as NaN,
    which `json.dumps` *can* serialize (as the non-standard token `NaN`) but
    which most JSON consumers on the other end of this dashboard cannot
    parse. This normalizes both: numpy scalars become native Python
    scalars, and any non-finite float becomes `None`.
    """
    records = []
    for row in frame.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (np.floating, float)):
                fv = float(value)
                clean[key] = fv if math.isfinite(fv) else None
            elif isinstance(value, (np.integer,)):
                clean[key] = int(value)
            elif isinstance(value, (np.bool_, bool)):
                clean[key] = bool(value)
            else:
                clean[key] = value
        records.append(clean)
    return records


@dataclass(frozen=True)
class FactorTearsheet:
    """Bundled factor diagnostics: IC term structure, quantile spread, turnover.

    `monotonicity` answers the question this module was built to answer: a
    signal with mean Rank IC 0.033 and a monotonicity score near +1.0 has its
    edge spread across a real ranking (cheap-ish to hold, degrades gracefully
    under partial turnover); the same IC with a monotonicity score near 0 has
    its edge concentrated in one lucky bucket (expensive, fragile, likely to
    not replicate out of sample).
    """

    n_dates: int
    n_symbols: int
    n_quantiles: int
    execution_lag: int
    horizons: tuple[int, ...]
    monotonicity: float
    ic_decay: pd.DataFrame = field(repr=False)
    quantile_returns: pd.DataFrame = field(repr=False)
    quantile_turnover: pd.DataFrame = field(repr=False)

    def as_dict(self) -> dict[str, Any]:
        """json.dump-safe summary: floats, not numpy scalars; NaN -> None."""
        mono = float(self.monotonicity) if math.isfinite(self.monotonicity) else None
        return {
            "n_dates": int(self.n_dates),
            "n_symbols": int(self.n_symbols),
            "n_quantiles": int(self.n_quantiles),
            "execution_lag": int(self.execution_lag),
            "horizons": [int(h) for h in self.horizons],
            "monotonicity": mono,
            "ic_decay": _json_records(self.ic_decay),
            "quantile_returns": _json_records(self.quantile_returns),
            "quantile_turnover": _json_records(self.quantile_turnover),
        }


def factor_tearsheet(
    *,
    scores: pd.DataFrame,
    close: pd.DataFrame,
    n_quantiles: int = 5,
    horizons: tuple[int, ...] = (1, 2, 3, 5, 10, 20),
    execution_lag: int = 1,
    max_abs_daily_return: float | None = DEFAULT_MAX_ABS_DAILY_RETURN,
) -> FactorTearsheet:
    """Run all four diagnostics on one (scores, close) panel and bundle them.

    `quantile_returns` and `quantile_turnover` are computed once at
    `horizon=1` (the bucket-level analogue of `information_coefficient_decay`'s
    shortest horizon) regardless of how many `horizons` are requested for the
    IC term structure -- turnover and one-bar-hold spread are the numbers
    that price a live book; the longer IC horizons describe how long the
    ranking's information content persists, which is a separate question.
    """
    _validate_frames(scores, close)
    ic = information_coefficient_decay(
        scores=scores, close=close, horizons=horizons, max_abs_daily_return=max_abs_daily_return,
    )
    qret = quantile_returns(
        scores=scores, close=close, n_quantiles=n_quantiles, horizon=1,
        execution_lag=execution_lag, max_abs_daily_return=max_abs_daily_return,
    )
    qturn = quantile_turnover(scores=scores, n_quantiles=n_quantiles)
    mono = monotonicity_score(qret)
    return FactorTearsheet(
        n_dates=len(scores),
        n_symbols=len(scores.columns),
        n_quantiles=n_quantiles,
        execution_lag=execution_lag,
        horizons=tuple(int(h) for h in horizons),
        monotonicity=mono,
        ic_decay=ic,
        quantile_returns=qret,
        quantile_turnover=qturn,
    )
