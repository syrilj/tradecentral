"""Long/short portfolio accounting with mandatory execution lag.

Every builder in `edge/tools/` used to re-implement this loop by hand, and two
of them got the time alignment wrong in the same way:

    long_w.iloc[i : i + h] = <formed from signal.iloc[i]>
    port_ret = (long_w * close.pct_change(1)).sum(axis=1)

`close.pct_change(1).iloc[i]` is the return *already realised* over bar `i`.
Booking it against a weight formed from bar `i`'s own features is a one-bar
lookahead. For a gap/volume signal it is close to circular: the overnight gap
is a component of the very close-to-close return being collected.

Measured on `build_pead_catalyst_model.py`, 557 symbols, 2016-08 .. 2026-07:

    execution_lag=0 (as shipped)   net +502.58%/yr   Sharpe  5.38
    execution_lag=1 (honest)       net  -10.38%/yr   Sharpe  0.03
    execution_lag=2               net  -13.31%/yr   Sharpe -0.05

The entire reported edge was the lookahead. `execution_lag` is therefore not a
tunable with a permissive default — values below 1 raise.

Conventions
-----------
`long_weights.iloc[i]` is the exposure *decided* using information available no
later than the close of bar `i`. With ``execution_lag=1`` it earns
``close.pct_change().iloc[i + 1]``, i.e. you trade at the close of bar `i` and
collect the move to the close of bar `i + 1`. Use ``execution_lag=2`` when the
signal cannot be acted on until the following session's close.

Execution-lag timeline (the reference diagram — check other tools against
this, not the other way around)
--------------------------------------------------------------------------
``held_long = long_w.shift(execution_lag)`` is the one line this module
exists for. Everything above is what it is protecting:

                     bar i-1          bar i          bar i+1         bar i+2
                        │               │               │               │
    close price    ─────●───────────────●───────────────●───────────────●─────
                     C[i-1]            C[i]            C[i+1]          C[i+2]
                                         │
                                         │ long_w.iloc[i] — the SIGNAL, formed
                                         │ from data known no later than the
                                         │ close of bar i (bar i's own O/H/L/C
                                         ▼ and full-day volume all included)
                              ┌───────────────────────┐
                              │   long_w.iloc[i]       │
                              └───────────┬────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │ execution_lag = 1 bar                       │
                    │ held_long = long_w.shift(1)                 │
                    ▼                                              │
        ┌───────────────────────────┐                             │
        │ held_long.iloc[i+1]        │  = long_w.iloc[i]           │
        │ = the WEIGHT actually held │  (the signal, one bar late) │
        └─────────────┬──────────────┘                             │
                       │ earns                                     │
                       ▼                                           │
          daily_ret.iloc[i+1] = C[i+1]/C[i] - 1                    │
          = the RETURN, from the close bar i was formed at         │
            to the very next close — the first return that         │
            can exist after the signal does. Honest.                │
                                                                     │
    ────────────────────────────────────────────────────────────────┘
    execution_lag = 0 is not "more aggressive," it is a different claim:
        held_long.iloc[i]  (no shift)         =  long_w.iloc[i]
        earns daily_ret.iloc[i] = C[i]/C[i-1] - 1
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        the move realised DURING bar i — the same bar whose close, high,
        low, and full-day volume were used to FORM long_w.iloc[i]. The
        position is credited with a return that happened before (or as) the
        information that justified it became available. For a gap/volume
        signal this is close to circular: bar i's overnight gap is a
        *component* of C[i]/C[i-1] - 1, so the strategy would be "predicting"
        a move built partly out of itself.

    That is why ``execution_lag`` is not a permissive tunable:
    ``simulate_long_short`` raises ``ValueError`` for ``execution_lag < 1``
    before a single return is computed (see the check a few lines into the
    function body). The lag-0 path is not merely discouraged, it does not
    exist — there is no arrangement of this module's code that lets a weight
    earn its own formation bar's return.

Costs are charged per bar against realised turnover, so net Sharpe and net
drawdown reflect them — rather than subtracting a scalar drag from an
annualised number, which leaves the risk metrics measured on a gross series.

The portfolio return series is never clipped. Truncating it collapses the
Sharpe denominator while a lookahead holds the numerator up; that combination
is what produced the PEAD hybrid's Sharpe of 13.33. Data errors are handled at
source instead, via `max_abs_daily_return`, which drops individual asset bars
whose move exceeds the threshold (see `edge/data/1d_wide` unadjusted corporate
actions, e.g. CHRD 2020-11-19, ~225x).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DEFAULT_COST_PER_SIDE = 0.0010  # 10bp per side, 20bp round-trip
DEFAULT_MAX_ABS_DAILY_RETURN = 0.50


@dataclass(frozen=True)
class PortfolioResult:
    """Accounting for one simulated long/short book.

    `gross_annual_return / annual_volatility == gross_sharpe` holds exactly by
    construction. If a caller reports figures where it does not, the figures did
    not come from here.
    """

    execution_lag: int
    n_bars: int
    gross_annual_return: float
    net_annual_return: float
    annual_volatility: float
    gross_sharpe: float
    sharpe: float
    compounded_annual_return: float
    max_drawdown: float
    annual_turnover: float
    cost_drag: float
    exposure: float
    n_extreme_masked: int
    net_returns: pd.Series = field(repr=False)
    gross_returns: pd.Series = field(repr=False)

    def as_dict(self) -> dict[str, float | int]:
        """Scalar summary, safe to json.dump."""
        return {
            "execution_lag": self.execution_lag,
            "n_bars": self.n_bars,
            "gross_annual_return_pct": self.gross_annual_return * 100.0,
            "net_annual_return_pct": self.net_annual_return * 100.0,
            "compounded_annual_return_pct": self.compounded_annual_return * 100.0,
            "annual_volatility_pct": self.annual_volatility * 100.0,
            "gross_sharpe": self.gross_sharpe,
            "sharpe_ratio": self.sharpe,
            "max_drawdown_pct": self.max_drawdown * 100.0,
            "annual_turnover": self.annual_turnover,
            "cost_drag_pct": self.cost_drag * 100.0,
            "exposure": self.exposure,
            "n_extreme_masked": self.n_extreme_masked,
        }


def _check_frame(name: str, frame: pd.DataFrame, close: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a DataFrame")
    if not frame.index.equals(close.index):
        raise ValueError(
            f"{name}.index does not match close.index "
            f"({len(frame.index)} vs {len(close.index)} rows). Align explicitly; "
            "silent reindexing here would shift the return attribution by an "
            "unknown number of bars."
        )
    missing = frame.columns.difference(close.columns)
    if len(missing):
        raise ValueError(f"{name} has {len(missing)} columns absent from close, e.g. {list(missing[:5])}")


def simulate_long_short(
    *,
    long_weights: pd.DataFrame,
    short_weights: pd.DataFrame,
    close: pd.DataFrame,
    execution_lag: int = 1,
    cost_per_side: float = DEFAULT_COST_PER_SIDE,
    max_abs_daily_return: float | None = DEFAULT_MAX_ABS_DAILY_RETURN,
) -> PortfolioResult:
    """Simulate a dollar-weighted long/short book.

    Parameters
    ----------
    long_weights, short_weights
        Exposure decided from information available at the close of each bar.
        `short_weights` are positive magnitudes; the short leg is subtracted.
    close
        Close prices, same index as the weight frames.
    execution_lag
        Bars between forming a weight and earning on it. Must be >= 1.
    cost_per_side
        Charged per bar on |change in executed weight|.
    max_abs_daily_return
        Asset bars moving more than this are treated as data errors and zeroed.
        Pass ``None`` to disable (only for data known to be split-adjusted).
    """
    if not isinstance(execution_lag, (int, np.integer)) or isinstance(execution_lag, bool):
        raise TypeError("execution_lag must be an int")
    if execution_lag < 1:
        raise ValueError(
            f"execution_lag must be >= 1, got {execution_lag}. A weight formed from "
            "bar i's features cannot earn bar i's own return — that is the lookahead "
            "this module exists to prevent."
        )
    if cost_per_side < 0:
        raise ValueError("cost_per_side must be non-negative")

    _check_frame("long_weights", long_weights, close)
    _check_frame("short_weights", short_weights, close)

    columns = long_weights.columns.union(short_weights.columns)
    px = close[columns].astype(float)
    long_w = long_weights.reindex(columns=columns).fillna(0.0).astype(float)
    short_w = short_weights.reindex(columns=columns).fillna(0.0).astype(float)

    daily_ret = px.pct_change(1)
    if max_abs_daily_return is not None:
        extreme = daily_ret.abs() > float(max_abs_daily_return)
        n_extreme_masked = int(extreme.to_numpy().sum())
        daily_ret = daily_ret.mask(extreme, 0.0)
    else:
        n_extreme_masked = 0
    daily_ret = daily_ret.fillna(0.0)

    # The single line this module exists for — see the "Execution-lag
    # timeline" diagram in the module docstring above for what this shift
    # means bar-by-bar and why `execution_lag < 1` is rejected below rather
    # than merely discouraged.
    held_long = long_w.shift(execution_lag).fillna(0.0)
    held_short = short_w.shift(execution_lag).fillna(0.0)

    gross = (held_long * daily_ret).sum(axis=1) - (held_short * daily_ret).sum(axis=1)

    turnover_per_bar = held_long.diff().abs().sum(axis=1) + held_short.diff().abs().sum(axis=1)
    turnover_per_bar.iloc[0] = held_long.iloc[0].abs().sum() + held_short.iloc[0].abs().sum()
    net = gross - turnover_per_bar * cost_per_side

    n_bars = int(len(gross))
    gross_std = float(gross.std())
    net_std = float(net.std())

    annual_volatility = gross_std * np.sqrt(TRADING_DAYS)
    gross_annual = float(gross.mean()) * TRADING_DAYS
    net_annual = float(net.mean()) * TRADING_DAYS

    gross_sharpe = float(gross.mean() / gross_std * np.sqrt(TRADING_DAYS)) if gross_std > 0 else 0.0
    net_sharpe = float(net.mean() / net_std * np.sqrt(TRADING_DAYS)) if net_std > 0 else 0.0

    equity = (1.0 + net.clip(lower=-0.99)).cumprod()
    peak = equity.cummax()
    max_drawdown = float(((peak - equity) / peak).max()) if n_bars else 0.0
    final = float(equity.iloc[-1]) if n_bars else 1.0
    compounded = (final ** (TRADING_DAYS / n_bars) - 1.0) if (n_bars > 0 and final > 0) else -1.0

    return PortfolioResult(
        execution_lag=int(execution_lag),
        n_bars=n_bars,
        gross_annual_return=gross_annual,
        net_annual_return=net_annual,
        annual_volatility=float(annual_volatility),
        gross_sharpe=gross_sharpe,
        sharpe=net_sharpe,
        compounded_annual_return=float(compounded),
        max_drawdown=max_drawdown,
        annual_turnover=float(turnover_per_bar.mean() * TRADING_DAYS),
        cost_drag=float(turnover_per_bar.mean() * TRADING_DAYS * cost_per_side),
        exposure=float((gross != 0).mean()) if n_bars else 0.0,
        n_extreme_masked=n_extreme_masked,
        net_returns=net,
        gross_returns=gross,
    )


def cross_sectional_rank_ic(
    signal: pd.DataFrame,
    forward_return: pd.DataFrame,
    *,
    min_names: int = 20,
    min_abs_signal: float | None = None,
    periods_per_year: float = TRADING_DAYS,
) -> dict[str, float]:
    """Per-bar Spearman IC of `signal` against `forward_return`.

    `min_abs_signal` restricts each bar to names above a magnitude threshold.
    That is a *conditional* IC on a self-selected subset and is not comparable
    to a gate written for the full cross-section — PEAD's headline +0.0396 came
    from `|signal| > 1.5`, while the unconditional figure is -0.0027. When you
    set it, report both.

    `periods_per_year` scales the ICIR. With an h-bar forward label sampled
    every bar the IC observations overlap, so pass ``TRADING_DAYS / h``, not the
    default — otherwise the ICIR is overstated by ``sqrt(h)``.
    """
    if not signal.index.equals(forward_return.index):
        raise ValueError("signal.index does not match forward_return.index")

    ics: list[float] = []
    for i in range(len(signal)):
        a = signal.iloc[i]
        b = forward_return.iloc[i]
        valid = a.notna() & b.notna()
        if min_abs_signal is not None:
            valid &= a.abs() > float(min_abs_signal)
        if int(valid.sum()) < min_names:
            continue
        ic = a[valid].corr(b[valid], method="spearman")
        if not np.isnan(ic):
            ics.append(float(ic))

    if not ics:
        return {"mean_rank_ic": 0.0, "rank_ic_std": 0.0, "rank_icir": 0.0, "n_bars": 0}

    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std())
    return {
        "mean_rank_ic": mean,
        "rank_ic_std": std,
        "rank_icir": float(mean / std * np.sqrt(periods_per_year)) if std > 0 else 0.0,
        "n_bars": len(ics),
    }
