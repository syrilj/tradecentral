"""Causal volatility-target scaling series for a long/short book.

Scope boundary (read this before adding anything here)
--------------------------------------------------------------------------
This module produces SCALING SERIES ONLY. It never computes P&L, never
touches costs, and never produces a Sharpe, a drawdown, or a return series
that is reported as a strategy result. All accounting -- gross/net return,
turnover, cost drag, Sharpe, drawdown -- stays in
`edge.research.portfolio.simulate_long_short`. That is not a style
preference: `edge/research/portfolio.py`'s own docstring documents a
+502.58%/yr, Sharpe 5.38 result that was pure one-bar lookahead, produced
because a second, ad-hoc accounting path outside `simulate_long_short`
existed and got the execution-lag shift wrong. A second accounting path is
exactly how that lookahead survived review. This module deliberately gives
itself no way to grow one: `vol_target_scale` returns a `pd.Series` of
multipliers, `apply_vol_target` returns two `pd.DataFrame`s of scaled
weights shaped for `simulate_long_short`, and `vol_target_diagnostics`
reports on realised vol and leverage -- never a return figure computed by
any path other than `simulate_long_short` itself (it calls the same
`long_w.shift(execution_lag)` accounting internally, purely to size the
book, and discards the returns after using them to fit a vol forecast).
Any change that makes this module report a Sharpe, an annualised return, or
anything else that looks like a performance number is a regression of the
exact kind `portfolio.py` exists to prevent -- put it in `portfolio.py`
instead, downstream of `simulate_long_short`.

Why volatility targeting, specifically
--------------------------------------------------------------------------
The repo's binding constraint is turnover: "10bp halves the edge" is the
working assumption behind every cost-aware gate in this codebase (see
`research/costs.py`, `research/gates.py`). Most ways to raise risk-adjusted
return -- sharper signals, more names, faster rebalancing -- raise turnover
right along with the return. Volatility targeting is one of the few levers
that does not: the scale changes only when *forecast volatility* moves,
which is slow and smooth relative to daily signal churn, so it can raise
Sharpe (by keeping realised vol near a target instead of letting it drift
with the market) while adding comparatively little turnover. If it were
non-causal it would be worthless for exactly the reason PEAD was worthless
at execution_lag=0: a vol forecast that peeks at the bar it is about to
size would be latching onto the same-bar move it is "predicting," and the
resulting Sharpe improvement would be manufactured, not real.

Causality convention (mirrors `research/portfolio.py` exactly)
--------------------------------------------------------------------------
`forecast_vol.iloc[i]` (from `realized_volatility` or `ewma_volatility`) is,
by construction, a function of `returns.iloc[i]` -- the trailing window
(rolling or EWMA) always includes the bar it ends on. That means bar `i`'s
own realised move is baked into `forecast_vol.iloc[i]`. Using
`forecast_vol.iloc[i]` to size a position held during bar `i` is therefore
the same one-bar lookahead documented in `portfolio.py`'s module docstring,
just wearing a volatility costume instead of a momentum one: the position
size would be informed by (part of) the very return it is about to earn.
`vol_target_scale` closes this the same way `simulate_long_short` closes
its lookahead -- by shifting: the scale applied at bar `i` is formed from
`forecast_vol.iloc[i - execution_lag]`, never `forecast_vol.iloc[i]`. See
the "Execution-lag timeline" diagram in `research/portfolio.py` for the
bar-by-bar picture this mirrors. `execution_lag < 1` raises for the same
reason it raises there: there is no honest arrangement of this module's
code that lets a scale depend on its own sizing bar's return.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DEFAULT_TARGET_VOL = 0.10
DEFAULT_MAX_LEVERAGE = 2.0
DEFAULT_MIN_LEVERAGE = 0.0
DEFAULT_WINDOW = 20
DEFAULT_HALFLIFE = 20.0
VALID_METHODS = ("realized", "ewma")


def realized_volatility(
    returns: pd.Series, *, window: int = DEFAULT_WINDOW, annualize: bool = True
) -> pd.Series:
    """Trailing sample std of `returns`, ending at bar `i` INCLUSIVE.

    `pandas.Series.rolling(window, min_periods=window)` is already causal by
    construction: the window ending at position `i` covers
    `returns.iloc[i - window + 1 : i + 1]`, never anything past `i`. The
    value at bar `i` is therefore a function of bars `<= i` only --
    `min_periods=window` (rather than a smaller default) makes the first
    `window - 1` bars NaN instead of computing a std from a partial, silently
    shorter window that would understate volatility during warm-up.

    Bar `i`'s own return is included in the window ending at `i` -- that is
    what "trailing volatility ending at `i`" means. Do not use this value to
    size a position held during bar `i`; see the module docstring and
    `vol_target_scale`'s `execution_lag` shift, which exists precisely to
    keep this function's inherent one-bar inclusion from becoming a
    lookahead when it feeds a scale.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a Series")
    if window < 2:
        raise ValueError("window must be at least two")
    vol = returns.rolling(window, min_periods=window).std(ddof=1)
    if annualize:
        vol = vol * np.sqrt(TRADING_DAYS)
    return vol


def ewma_volatility(
    returns: pd.Series, *, halflife: float = DEFAULT_HALFLIFE, annualize: bool = True
) -> pd.Series:
    """Causal EWMA std of `returns`, ending at bar `i` INCLUSIVE.

    `.ewm(halflife=halflife, adjust=False).std()` is causal: `adjust=False`
    selects pandas's recursive EWMA form,
    `y_i = alpha * x_i + (1 - alpha) * y_{i-1}` (and analogously for the
    variance pandas accumulates to produce `.std()`), which only ever
    references `x_i` and the previous accumulator `y_{i-1}` -- never a future
    observation. This was confirmed empirically, not assumed: mutating
    `returns` strictly after index `i` and recomputing left `.ewm(...,
    adjust=False).std().iloc[:i+1]` bit-identical. (`adjust=True`, the
    pandas default, instead reweights the *entire* history at every step and
    is also technically causal in the sense of not using future data, but it
    is not used here because its early-sample bias-correction denominator
    changes as more history accumulates, which is an unnecessary complication
    for a forecast that already gets its own execution-lag shift downstream.)

    As with `realized_volatility`, the value at bar `i` embeds bar `i`'s own
    return -- do not use it to size bar `i`'s position directly; that is
    what `vol_target_scale`'s `execution_lag` shift is for.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be a Series")
    if not (halflife > 0):
        raise ValueError("halflife must be positive")
    vol = returns.ewm(halflife=halflife, adjust=False).std()
    if annualize:
        vol = vol * np.sqrt(TRADING_DAYS)
    return vol


def vol_target_scale(
    *,
    forecast_vol: pd.Series,
    target_vol: float = DEFAULT_TARGET_VOL,
    max_leverage: float = DEFAULT_MAX_LEVERAGE,
    min_leverage: float = DEFAULT_MIN_LEVERAGE,
    execution_lag: int = 1,
) -> pd.Series:
    """`scale = clip(target_vol / forecast_vol, min_leverage, max_leverage)`,
    lagged so the scale applied at bar `i` only ever depends on
    `forecast_vol.iloc[i - execution_lag]`.

    Why the shift is mandatory, not a tunable default
    ----------------------------------------------------------------------
    `forecast_vol.iloc[i]` (from `realized_volatility`/`ewma_volatility`)
    already embeds bar `i`'s own return -- see those functions' docstrings.
    Sizing bar `i`'s position from `forecast_vol.iloc[i]` would earn a
    position sized with knowledge of (part of) the very move it is about to
    be scored on -- the same one-bar lookahead `research/portfolio.py`
    documents for signal weights, in a volatility costume rather than a
    momentum one. `execution_lag < 1` therefore raises exactly as
    `simulate_long_short` does, before any scale is computed:
    `execution_lag=0` is not "more responsive," it is unrepresentable.

    Warm-up and missing data -> scale 0.0, never NaN, never 1.0
    ----------------------------------------------------------------------
    Rows where `forecast_vol` is NaN (the first `window - 1` bars of
    `realized_volatility`, or any genuinely missing input) map to a scale of
    0.0 -- no position -- rather than being forward-filled from the last
    known vol, and rather than defaulting to 1.0 ("full size"). Forward-fill
    would let a stale vol estimate silently size a live position; defaulting
    to 1.0 is the exact silent-degradation shape
    `research/features.py:assert_no_degenerate_feature_columns` exists to
    catch elsewhere in this repo -- a missing input quietly substituting a
    plausible-looking value (full size looks like a completely reasonable
    scale) instead of the run visibly going flat to say the input is
    missing. A book that is flat during warm-up is honest; a book that is
    silently unscaled during warm-up is not.
    """
    if not isinstance(forecast_vol, pd.Series):
        raise TypeError("forecast_vol must be a Series")
    if not isinstance(execution_lag, (int, np.integer)) or isinstance(execution_lag, bool):
        raise TypeError("execution_lag must be an int")
    if execution_lag < 1:
        raise ValueError(
            f"execution_lag must be >= 1, got {execution_lag}. A scale formed from "
            "bar i's own forecast_vol cannot be applied to bar i's own position: "
            "forecast_vol.iloc[i] is a trailing window ending at (and including) "
            "bar i, so it already embeds bar i's own return. Sizing bar i's "
            "position with it is the same one-bar lookahead documented in "
            "edge/research/portfolio.py's module docstring -- see the "
            "'Execution-lag timeline' diagram there -- wearing a volatility "
            "costume instead of a momentum one."
        )
    if not (target_vol > 0):
        raise ValueError("target_vol must be positive")
    if min_leverage < 0:
        raise ValueError("min_leverage must be non-negative")
    if max_leverage < min_leverage:
        raise ValueError(
            f"max_leverage ({max_leverage}) must be >= min_leverage ({min_leverage})"
        )

    raw = target_vol / forecast_vol
    clipped = raw.clip(lower=min_leverage, upper=max_leverage)
    # forecast_vol == 0 divides to +inf, not NaN; `.clip` already bounds that
    # to max_leverage, which is the defensible reading of a genuinely
    # zero-vol forecast. Only actual NaN forecast_vol (warm-up / missing
    # data) gets the explicit "no position" treatment below.
    clipped = clipped.where(forecast_vol.notna(), 0.0)

    # The one line this function exists for: bar i gets bar (i -
    # execution_lag)'s computed scale, never its own. `fillna(0.0)` covers
    # the leading NaNs the shift introduces at the very start of the series
    # (before even bar 0's forecast is old enough to be shifted in) -- same
    # "missing -> flat, not full size" rule as the warm-up case above, not a
    # second mechanism.
    scale = clipped.shift(execution_lag).fillna(0.0)
    return scale


def _check_book_inputs(long_weights: pd.DataFrame, short_weights: pd.DataFrame, close: pd.DataFrame) -> None:
    if not isinstance(long_weights, pd.DataFrame) or not isinstance(short_weights, pd.DataFrame):
        raise TypeError("long_weights and short_weights must be DataFrames")
    if not long_weights.index.equals(close.index):
        raise ValueError(
            "long_weights.index does not match close.index. Align explicitly; "
            "silent reindexing here would shift the vol forecast by an unknown "
            "number of bars, same failure mode simulate_long_short guards against."
        )
    if not short_weights.index.equals(close.index):
        raise ValueError("short_weights.index does not match close.index")
    missing_long = long_weights.columns.difference(close.columns)
    if len(missing_long):
        raise ValueError(f"long_weights has columns absent from close, e.g. {list(missing_long[:5])}")
    missing_short = short_weights.columns.difference(close.columns)
    if len(missing_short):
        raise ValueError(f"short_weights has columns absent from close, e.g. {list(missing_short[:5])}")


def _book_returns(
    long_weights: pd.DataFrame, short_weights: pd.DataFrame, close: pd.DataFrame, execution_lag: int
) -> pd.Series:
    """The book's own daily return series, aligned exactly the way
    `simulate_long_short` aligns it: `held = weights.shift(execution_lag)`
    earns `close.pct_change(1)`. This mirrors that function's accounting
    line for line (see the "Execution-lag timeline" diagram in
    `research/portfolio.py`) rather than improvising a second alignment,
    because the vol forecast this feeds must be measuring the same book
    `simulate_long_short` will actually score downstream -- a differently
    aligned proxy return series would fit a scale to the wrong book.

    This function is not a P&L path: its output is used only to fit a vol
    forecast and is discarded afterwards. It intentionally does not apply
    `simulate_long_short`'s `max_abs_daily_return` data-error masking --
    that is a data-hygiene concern for `close`, not a vol-targeting concern,
    and stays owned by `portfolio.py`.
    """
    _check_book_inputs(long_weights, short_weights, close)
    columns = long_weights.columns.union(short_weights.columns)
    px = close[columns].astype(float)
    long_w = long_weights.reindex(columns=columns).fillna(0.0).astype(float)
    short_w = short_weights.reindex(columns=columns).fillna(0.0).astype(float)

    daily_ret = px.pct_change(1).fillna(0.0)
    held_long = long_w.shift(execution_lag).fillna(0.0)
    held_short = short_w.shift(execution_lag).fillna(0.0)
    return (held_long * daily_ret).sum(axis=1) - (held_short * daily_ret).sum(axis=1)


def _forecast_vol(
    book_returns: pd.Series, *, method: str, window: int, halflife: float
) -> pd.Series:
    if method == "realized":
        return realized_volatility(book_returns, window=window, annualize=True)
    if method == "ewma":
        return ewma_volatility(book_returns, halflife=halflife, annualize=True)
    raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}")


def apply_vol_target(
    *,
    long_weights: pd.DataFrame,
    short_weights: pd.DataFrame,
    close: pd.DataFrame,
    target_vol: float = DEFAULT_TARGET_VOL,
    window: int = DEFAULT_WINDOW,
    method: str = "realized",
    **kw,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scale `long_weights`/`short_weights` toward `target_vol` and return
    both frames unmodified in shape, ready for `simulate_long_short` with no
    reshaping.

    Procedure: build the UNSCALED book's own daily return series using
    `execution_lag`-aligned accounting identical to `simulate_long_short`
    (see `_book_returns`), forecast that return series's volatility with
    `method`, derive a causal scale with `vol_target_scale`, and multiply
    both weight frames by that scale row-wise. The scale is a `pd.Series`
    indexed like `close`; `DataFrame.mul(scale, axis=0)` broadcasts it across
    columns.

    Extra keyword arguments (all optional, forwarded to `vol_target_scale`
    or the chosen vol estimator): `execution_lag` (default 1), `max_leverage`
    (default 2.0), `min_leverage` (default 0.0), `halflife` (default 20.0,
    used only when `method="ewma"`). Unknown keywords raise `TypeError`
    rather than being silently ignored -- a misspelled `max_leverge` should
    fail loudly, not quietly run with the default cap.
    """
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}")

    execution_lag = int(kw.pop("execution_lag", 1))
    max_leverage = float(kw.pop("max_leverage", DEFAULT_MAX_LEVERAGE))
    min_leverage = float(kw.pop("min_leverage", DEFAULT_MIN_LEVERAGE))
    halflife = float(kw.pop("halflife", DEFAULT_HALFLIFE))
    if kw:
        raise TypeError(f"apply_vol_target() got unexpected keyword arguments: {sorted(kw)}")

    book_returns = _book_returns(long_weights, short_weights, close, execution_lag)
    forecast_vol = _forecast_vol(book_returns, method=method, window=window, halflife=halflife)
    scale = vol_target_scale(
        forecast_vol=forecast_vol,
        target_vol=target_vol,
        max_leverage=max_leverage,
        min_leverage=min_leverage,
        execution_lag=execution_lag,
    )

    scaled_long = long_weights.mul(scale, axis=0)
    scaled_short = short_weights.mul(scale, axis=0)
    return scaled_long, scaled_short


@dataclass(frozen=True)
class VolTargetDiagnostics:
    """How well a vol-targeted book tracked `target_vol`, and how much the
    scale moved to get there. Diagnostics only -- see the module docstring
    for why this dataclass carries no P&L, cost, or Sharpe figure. A
    dashboard is expected to render this; `as_dict()` exists for that.
    """

    target_vol: float
    unscaled_realized_vol: float
    scaled_realized_vol: float
    mean_leverage: float
    median_leverage: float
    max_leverage_applied: float
    frac_at_leverage_cap: float
    frac_flat_warmup: float
    n_bars: int

    def as_dict(self) -> dict[str, float | int | None]:
        """json.dump-safe summary. `NaN` is a legitimate value for some of
        these fields (e.g. realised vol of a too-short or all-flat book) but
        `json.dumps` has no representation for it -- `NaN`/`Infinity` are
        JavaScript literals, not JSON, so a strict `JSON.parse` on the
        dashboard's fetch response throws on one emitted verbatim. Map NaN to
        `None`, which every JSON consumer already handles as "no value."
        """

        def _safe(value: float) -> float | None:
            value = float(value)
            return None if math.isnan(value) else value

        return {
            "target_vol": _safe(self.target_vol),
            "unscaled_realized_vol": _safe(self.unscaled_realized_vol),
            "scaled_realized_vol": _safe(self.scaled_realized_vol),
            "mean_leverage": _safe(self.mean_leverage),
            "median_leverage": _safe(self.median_leverage),
            "max_leverage_applied": _safe(self.max_leverage_applied),
            "frac_at_leverage_cap": _safe(self.frac_at_leverage_cap),
            "frac_flat_warmup": _safe(self.frac_flat_warmup),
            "n_bars": int(self.n_bars),
        }


def vol_target_diagnostics(
    *,
    long_weights: pd.DataFrame,
    short_weights: pd.DataFrame,
    close: pd.DataFrame,
    target_vol: float = DEFAULT_TARGET_VOL,
    window: int = DEFAULT_WINDOW,
    method: str = "realized",
    **kw,
) -> VolTargetDiagnostics:
    """Build the same unscaled book, forecast vol, and scale that
    `apply_vol_target` would from identical inputs, and summarise the
    result. Accepts the same keyword arguments as `apply_vol_target`
    (`execution_lag`, `max_leverage`, `min_leverage`, `halflife`).

    Realised vol figures here are for diagnostic comparison only (does the
    scale actually pull realised vol toward `target_vol`?) -- they are not a
    substitute for `simulate_long_short`, which is still required for any
    reported return, Sharpe, or drawdown.
    """
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}")

    execution_lag = int(kw.pop("execution_lag", 1))
    max_leverage = float(kw.pop("max_leverage", DEFAULT_MAX_LEVERAGE))
    min_leverage = float(kw.pop("min_leverage", DEFAULT_MIN_LEVERAGE))
    halflife = float(kw.pop("halflife", DEFAULT_HALFLIFE))
    if kw:
        raise TypeError(f"vol_target_diagnostics() got unexpected keyword arguments: {sorted(kw)}")

    unscaled_returns = _book_returns(long_weights, short_weights, close, execution_lag)
    forecast_vol = _forecast_vol(unscaled_returns, method=method, window=window, halflife=halflife)
    scale = vol_target_scale(
        forecast_vol=forecast_vol,
        target_vol=target_vol,
        max_leverage=max_leverage,
        min_leverage=min_leverage,
        execution_lag=execution_lag,
    )

    scaled_long = long_weights.mul(scale, axis=0)
    scaled_short = short_weights.mul(scale, axis=0)
    scaled_returns = _book_returns(scaled_long, scaled_short, close, execution_lag)

    n_bars = int(len(unscaled_returns))
    unscaled_vol = float(unscaled_returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if n_bars > 1 else float("nan")
    scaled_vol = float(scaled_returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if n_bars > 1 else float("nan")

    scale_arr = scale.to_numpy(dtype=float)
    # Warm-up rows are exactly the rows `vol_target_scale` mapped to 0.0 --
    # see that function's docstring for why 0.0 (not NaN, not 1.0) is the
    # only value that can mean "missing forecast" here, so testing for it is
    # unambiguous rather than a heuristic.
    at_cap = np.isclose(scale_arr, max_leverage)
    flat_warmup = np.isclose(scale_arr, 0.0)

    return VolTargetDiagnostics(
        target_vol=float(target_vol),
        unscaled_realized_vol=unscaled_vol,
        scaled_realized_vol=scaled_vol,
        mean_leverage=float(scale.mean()) if n_bars else float("nan"),
        median_leverage=float(scale.median()) if n_bars else float("nan"),
        max_leverage_applied=float(scale.max()) if n_bars else float("nan"),
        frac_at_leverage_cap=float(at_cap.mean()) if n_bars else float("nan"),
        frac_flat_warmup=float(flat_warmup.mean()) if n_bars else float("nan"),
        n_bars=n_bars,
    )
