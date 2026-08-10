"""
Event-conditioned competing-barrier labels ("is this phenomenon real?").

Pure functions, no I/O/network -- mirrors the separation ``research/labels.py``
and ``research/flow_state.py`` already use. This module answers a narrower
question than ``research/labels.py``'s frozen fixed-horizon labels: given a
flow-state event (a SHOCK/TEST episode start, ``t0``), which of a down
barrier or an up barrier gets hit first, and how does price behave over the
following ``horizon_days`` trading days? No machine learning happens here --
Phase 2 is entirely "is the effect real", not "can we predict it".

Calling convention
-------------------
``competing_barrier_labels`` operates on ONE symbol at a time: ``bars`` is a
single-symbol OHLCV ``pd.DataFrame`` (ascending, duplicate-free
``DatetimeIndex``, matching ``research/flow_state.py``'s convention), and
``events`` is the subset of an events table (e.g. ``extract_events``'s
output, or a synthetic control-date table built by
``research/matched_controls.py``) that all reference that same symbol --
if an ``events["symbol"]`` column is present, every value in it must equal
the same symbol. Multi-symbol callers (the study runner) group events by
symbol and call this function once per group, concatenating the results.
This mirrors the plan's explicit "your call, document it" latitude and keeps
this module's inner loop a simple single-series scan rather than a hidden
groupby, which makes the no-lookahead property easy to audit by eye.

Every row of ``events`` is preserved in the output (never silently dropped
-- ``research/labels.py``'s house rule): the function ADDS label columns to
a copy of ``events`` rather than filtering it. An event whose horizon result
genuinely cannot be resolved from the data supplied (warm-up too short for
``sigma_t0``, or the panel ends before the barrier could have been
confirmed absent) gets ``outcome = None`` (a missing/"MISSING" class), never
a fabricated ``"NEITHER"``.

Units / sign conventions (read before using ``mae``/``mfe``)
---------------------------------------------------------------
``P0`` = ``close`` at ``t0``. ``sigma_t0`` is a trailing realized volatility
in FRACTIONAL return units (e.g. ``0.02`` == 2% daily vol), computed from
``vol_window`` trailing simple daily returns ending at and including ``t0``
(``pandas`` rolling ``std(ddof=1)``, the same convention
``research/regimes.py:classify_regimes`` uses). The barriers are absolute
PRICE levels::

    B_D = P0 * (1 - k_down * sigma_t0)
    B_U = P0 * (1 + k_up * sigma_t0)

``mae``/``mfe`` follow the plan's literal formulas, not a "always positive
magnitude" convention -- read the sign carefully:

* outcome favors UP (``UP_FIRST``): ``mae = min((low - P0) / P0)`` (worst
  ADVERSE move against an up bet -- negative), ``mfe = max((high - P0) / P0)``
  (best FAVORABLE move -- positive).
* outcome favors DOWN (``DOWN_FIRST``): ``mae = max((high - P0) / P0)``
  (worst adverse move against a down bet -- positive, price rallied against
  it), ``mfe = min((low - P0) / P0)`` (best favorable move -- negative,
  price fell further).
* ``NEITHER`` / ``AMBIGUOUS`` / missing: no dominant direction is
  established, so both are reported as ``NaN`` rather than guessing which
  side is "favorable" -- an explicit design choice, not an oversight.

Both are computed over the SAME forward window used for barrier-hit
detection (``t0+1 .. min(t0+horizon_days, last available bar)``), not
truncated at the hit bar -- i.e. they describe the full nominal horizon's
price excursion, not just the excursion up to the first touch.

``terminal_return`` follows ``research/labels.py``'s strict convention
exactly: ``close[t0 + horizon_days] / P0 - 1`` if that bar exists, else
``NaN`` (censored). The "or use the last available bar's return" alternative
mentioned in the plan is deliberately NOT used here -- fabricating a
different-horizon return under the ``terminal_return`` name would silently
change its meaning depending on how much history happened to be loaded,
which is exactly the kind of proxy drift ``research/labels.py`` and
``research/flow_state_panel.py`` both guard against. Callers that want a
partial-horizon return for censored rows can compute it themselves from
``bars`` -- this module never fabricates one under a name that implies a
full horizon.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_REQUIRED_BAR_COLUMNS: tuple[str, ...] = ("high", "low", "close")

_OUTCOME_DOWN = "DOWN_FIRST"
_OUTCOME_UP = "UP_FIRST"
_OUTCOME_NEITHER = "NEITHER"
_OUTCOME_AMBIGUOUS = "AMBIGUOUS"


def _validate_ascending_unique_index(index: pd.Index, *, label: str) -> None:
    if not index.is_monotonic_increasing:
        raise ValueError(f"{label} index must be sorted in ascending order")
    if index.has_duplicates:
        raise ValueError(f"{label} index must not contain duplicate timestamps")


def _validate_bars(bars: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_BAR_COLUMNS if c not in bars.columns]
    if missing:
        raise KeyError(f"missing OHLC columns: {missing}")
    _validate_ascending_unique_index(bars.index, label="bars")


def _validate_events(events: pd.DataFrame) -> None:
    if "t0" not in events.columns:
        raise KeyError("events must have a 't0' column")
    if "symbol" in events.columns and events["symbol"].nunique(dropna=True) > 1:
        raise ValueError(
            "competing_barrier_labels operates on one symbol at a time; "
            "events contains more than one distinct 'symbol' value -- "
            "group events by symbol and call this function once per group"
        )


def _trailing_sigma(close: pd.Series, vol_window: int) -> pd.Series:
    """Trailing realized vol (fractional units), ``std(ddof=1)`` over ``vol_window``
    trailing simple returns ending at and including each row -- causal by
    construction (a rolling window never reaches past its own right edge)."""
    returns = close.pct_change(fill_method=None)
    return returns.rolling(vol_window, min_periods=vol_window).std(ddof=1)


def _scan_forward(
    high: np.ndarray,
    low: np.ndarray,
    i: int,
    horizon_days: int,
    b_down: float,
    b_up: float,
) -> tuple[str | None, int | None, bool]:
    """Scan bars ``i+1 .. min(i+horizon_days, n-1)`` for the first barrier touch.

    Returns ``(outcome, hit_position, horizon_fully_observed)``. ``outcome``
    is ``None`` when no hit occurred AND the horizon window was not fully
    observed (censored / unresolved, never fabricated as ``NEITHER``).
    """
    n = len(high)
    j_max = min(i + horizon_days, n - 1)
    horizon_fully_observed = (i + horizon_days) <= (n - 1)
    for j in range(i + 1, j_max + 1):
        down_hit = np.isfinite(low[j]) and low[j] <= b_down
        up_hit = np.isfinite(high[j]) and high[j] >= b_up
        if down_hit and up_hit:
            return _OUTCOME_AMBIGUOUS, j, horizon_fully_observed
        if down_hit:
            return _OUTCOME_DOWN, j, horizon_fully_observed
        if up_hit:
            return _OUTCOME_UP, j, horizon_fully_observed
    if horizon_fully_observed:
        return _OUTCOME_NEITHER, None, True
    return None, None, False


def competing_barrier_labels(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    k_down: float,
    k_up: float,
    horizon_days: int,
    vol_window: int = 21,
) -> pd.DataFrame:
    """Competing-barrier outcome labels for one symbol's flow-state events.

    See the module docstring for the exact calling convention, units, and
    sign conventions. ``bars`` must be a single-symbol OHLC(V) frame; every
    row of ``events`` is preserved in the output (label columns are added to
    a copy, nothing is filtered).

    Added columns: ``P0``, ``sigma_t0``, ``barrier_down``, ``barrier_up``,
    ``outcome`` (``DOWN_FIRST`` / ``UP_FIRST`` / ``NEITHER`` / ``AMBIGUOUS``
    / ``None``), ``time_to_hit`` (trading days, ``NaN`` if no hit),
    ``mae``, ``mfe``, ``terminal_return``, ``censored`` (``True`` when the
    outcome could not be resolved because the panel ends before
    ``t0 + horizon_days`` and no barrier was touched in the observed
    partial window).
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be positive")
    if vol_window < 2:
        raise ValueError("vol_window must be >= 2")
    if k_down <= 0 or k_up <= 0:
        raise ValueError("k_down and k_up must be positive")
    _validate_bars(bars)
    _validate_events(events)

    close = bars["close"].astype(float)
    high = bars["high"].astype(float).to_numpy()
    low = bars["low"].astype(float).to_numpy()
    n = len(bars)
    sigma = _trailing_sigma(close, vol_window)
    index_pos = {ts: pos for pos, ts in enumerate(bars.index)}

    out = events.copy()
    out_cols: dict[str, list[Any]] = {
        "P0": [], "sigma_t0": [], "barrier_down": [], "barrier_up": [],
        "outcome": [], "time_to_hit": [], "mae": [], "mfe": [],
        "terminal_return": [], "censored": [],
    }

    for t0 in events["t0"]:
        ts = pd.Timestamp(t0)
        if ts not in index_pos:
            raise KeyError(
                f"event t0={ts} not found in bars.index -- events must be "
                "derived from (or aligned to) the same bars supplied here"
            )
        i = index_pos[ts]
        p0 = float(close.iloc[i])
        sigma_t0 = float(sigma.iloc[i]) if pd.notna(sigma.iloc[i]) else np.nan

        # terminal_return: independent of sigma validity, strict research/labels.py
        # convention (NaN when censored, never a substitute-horizon return).
        target_pos = i + horizon_days
        terminal_return = (
            float(close.iloc[target_pos]) / p0 - 1.0 if target_pos < n else np.nan
        )

        if not np.isfinite(sigma_t0) or sigma_t0 <= 0:
            # Insufficient warm-up (or a degenerate zero-vol window): the
            # barrier itself is undefined, so every barrier-dependent column
            # stays missing. This is a distinct "MISSING" class from
            # NEITHER (which asserts a fully-observed non-event).
            out_cols["P0"].append(p0)
            out_cols["sigma_t0"].append(sigma_t0)
            out_cols["barrier_down"].append(np.nan)
            out_cols["barrier_up"].append(np.nan)
            out_cols["outcome"].append(None)
            out_cols["time_to_hit"].append(np.nan)
            out_cols["mae"].append(np.nan)
            out_cols["mfe"].append(np.nan)
            out_cols["terminal_return"].append(terminal_return)
            out_cols["censored"].append(True)
            continue

        b_down = p0 * (1.0 - k_down * sigma_t0)
        b_up = p0 * (1.0 + k_up * sigma_t0)

        outcome, hit_pos, fully_observed = _scan_forward(high, low, i, horizon_days, b_down, b_up)
        censored = outcome is None

        time_to_hit = float(hit_pos - i) if hit_pos is not None else np.nan

        mae = mfe = np.nan
        if outcome in (_OUTCOME_UP, _OUTCOME_DOWN):
            j_max = min(i + horizon_days, n - 1)
            window_high = high[i + 1: j_max + 1]
            window_low = low[i + 1: j_max + 1]
            if window_high.size:
                up_moves = (window_high - p0) / p0
                down_moves = (window_low - p0) / p0
                if outcome == _OUTCOME_UP:
                    mae = float(np.nanmin(down_moves))
                    mfe = float(np.nanmax(up_moves))
                else:
                    mae = float(np.nanmax(up_moves))
                    mfe = float(np.nanmin(down_moves))

        out_cols["P0"].append(p0)
        out_cols["sigma_t0"].append(sigma_t0)
        out_cols["barrier_down"].append(b_down)
        out_cols["barrier_up"].append(b_up)
        out_cols["outcome"].append(outcome)
        out_cols["time_to_hit"].append(time_to_hit)
        out_cols["mae"].append(mae)
        out_cols["mfe"].append(mfe)
        out_cols["terminal_return"].append(terminal_return)
        out_cols["censored"].append(censored)

    for col, values in out_cols.items():
        out[col] = values
    return out


def label_coverage_report(labels: pd.DataFrame) -> dict:
    """Class balance / ambiguity / censoring summary for a labels table.

    ``censoring_rate`` is exactly "fraction NEITHER or missing
    terminal_return" per the plan's own definition (not "fraction with a
    missing outcome" -- those overlap heavily but are not identical: an
    event can have a resolved ``NEITHER`` outcome yet still show a missing
    ``terminal_return`` if the horizon used for the barrier scan differs
    from the one implied by ``terminal_return``'s own availability, though
    in this module's ``competing_barrier_labels`` output the two horizons
    are always the same).
    """
    n = int(len(labels))
    if n == 0:
        return {"n_events": 0, "class_balance": {}, "ambiguity_rate": 0.0, "censoring_rate": 0.0}

    outcome = labels["outcome"]
    counts = outcome.value_counts(dropna=False)
    class_balance: dict[str, int] = {}
    for key, value in counts.items():
        name = "MISSING" if key is None or (isinstance(key, float) and pd.isna(key)) else str(key)
        class_balance[name] = class_balance.get(name, 0) + int(value)

    ambiguity_rate = float((outcome == _OUTCOME_AMBIGUOUS).mean())
    terminal_missing = labels["terminal_return"].isna() if "terminal_return" in labels else pd.Series(False, index=labels.index)
    censored_mask = (outcome == _OUTCOME_NEITHER) | terminal_missing
    censoring_rate = float(censored_mask.mean())

    return {
        "n_events": n,
        "class_balance": class_balance,
        "ambiguity_rate": ambiguity_rate,
        "censoring_rate": censoring_rate,
    }
