"""
Matched controls + permutation null for flow-state events ("is it real?").

Pure functions except ``attach_regime_columns`` (which needs each symbol's
OHLCV bars to derive its own volatility/trend regime -- it takes those bars
already in memory as an argument, so it still does no I/O of its own). No
machine learning: this module answers "does a flow-state event behave
differently from an unremarkable day with the same volatility/trend
regime", using nearest-neighbor matching, Newey-West + date-block bootstrap
inference (``research/statistics.py``, not reimplemented here), and a
circular per-symbol permutation null.

Panel contract
--------------
``panel`` throughout this module is the long-format table produced by
``research/flow_state_panel.py:build_flow_state_panel`` (columns ``symbol``,
``date``, plus feature columns) -- NOT indexed by date, since that panel
concatenates many symbols with a plain ``RangeIndex``. That panel has no raw
OHLCV columns (only derived features), so it cannot regime-classify itself;
``attach_regime_columns`` is the explicit, separate step that adds
``realized_volatility`` / ``volatility_regime`` / ``trend_regime`` /
``drawdown`` / ``bear_market`` columns by calling
``research/regimes.py:classify_regimes`` per symbol against bars the caller
supplies. ``match_controls`` itself does not call ``classify_regimes`` --
that keeps its signature exactly the one specified upstream (no ``bars``
parameter) and makes the regime-attachment step a visible, testable action
in the study runner rather than a hidden side effect of matching.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from .regimes import classify_regimes
from .statistics import (
    bonferroni_deflated_sharpe_approximation,
    date_block_bootstrap_ci,
    effective_trial_count_from_correlation,
    newey_west_tstat,
    trial_return_correlation_matrix,
)

_OUTCOME_DOWN = "DOWN_FIRST"


# ---------------------------------------------------------------------------
# attach_regime_columns
# ---------------------------------------------------------------------------

def attach_regime_columns(
    panel: pd.DataFrame,
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    volatility_window: int = 20,
    trend_window: int = 60,
    bear_drawdown: float = -0.15,
) -> pd.DataFrame:
    """Left-join causal regime columns onto ``panel``, one symbol at a time.

    ``bars_by_symbol`` must supply an OHLCV frame (with a ``close`` column
    and an ascending, duplicate-free ``DatetimeIndex``) for every distinct
    symbol present in ``panel["symbol"]`` -- a missing symbol raises rather
    than silently leaving that symbol's rows with NaN regimes, since a
    caller who forgot a symbol should find out immediately, not three
    functions later when ``match_controls`` can't find any candidates for
    it. Adds ``realized_volatility``, ``volatility_regime``, ``trend_regime``,
    ``drawdown``, ``bear_market`` (``classify_regimes``'s exact output
    columns) via a ``(symbol, date)`` merge; rows in ``panel`` whose date has
    no matching bars row (should not happen for panel-derived dates, but is
    not fatal) get NaN regime columns.
    """
    if "symbol" not in panel.columns or "date" not in panel.columns:
        raise KeyError("panel must have 'symbol' and 'date' columns")
    symbols = list(pd.unique(panel["symbol"]))
    missing = [s for s in symbols if s not in bars_by_symbol]
    if missing:
        raise KeyError(f"bars_by_symbol is missing OHLCV bars for symbols: {sorted(missing)}")

    frames: list[pd.DataFrame] = []
    for sym in symbols:
        regimes = classify_regimes(
            bars_by_symbol[sym],
            volatility_window=volatility_window,
            trend_window=trend_window,
            bear_drawdown=bear_drawdown,
        )
        regimes = regimes.reset_index()
        regimes = regimes.rename(columns={regimes.columns[0]: "date"})
        regimes.insert(0, "symbol", sym)
        frames.append(regimes)
    regime_panel = pd.concat(frames, axis=0, ignore_index=True) if frames else pd.DataFrame(
        columns=["symbol", "date", "realized_volatility", "volatility_regime", "trend_regime", "drawdown", "bear_market"]
    )

    panel_copy = panel.copy()
    panel_copy["_date_key"] = pd.to_datetime(panel_copy["date"]).dt.normalize()
    regime_panel["_date_key"] = pd.to_datetime(regime_panel["date"]).dt.normalize()
    merged = panel_copy.merge(
        regime_panel.drop(columns=["date"]), on=["symbol", "_date_key"], how="left",
    ).drop(columns=["_date_key"])
    return merged


# ---------------------------------------------------------------------------
# match_controls
# ---------------------------------------------------------------------------

def _nearest_k(
    z_values: np.ndarray,
    positions: np.ndarray,
    own_z: float,
    k: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(positions, distances)`` of the ``k`` nearest rows to
    ``own_z`` by ``|z - own_z|``, nearest first -- numpy-array replacement
    for the old ``_select_nearest`` (deterministic-given-``rng``, same
    nearest-first/seeded-tiebreak contract, but never materializes a
    shuffled COPY of the candidate pool just to pick a handful of rows).

    ``np.argpartition`` finds the ``k`` smallest-distance elements in
    ``O(n)`` instead of a full ``O(n log n)`` sort; only those ``k``
    candidates are then sorted (by distance, with a small seeded random
    tiebreak) to fix their final nearest-first order. Ties are broken with
    ``k`` fresh draws from ``rng`` -- not ``n`` -- since exact float64 ties
    in a continuous feature (e.g. realized_volatility) are effectively
    measure-zero in real data; this keeps the random draw cost bounded by
    ``k`` (typically ``n_controls`` <= 5) regardless of how large the
    candidate pool (``n``) is, which is what makes this tractable at
    full-universe scale (candidate pools of 10^5+ rows per regime bucket).

    When ``own_z`` is NaN (the event's own continuous feature is missing),
    every distance is equally undefined -- mirrors the old implementation's
    behavior in that case (all distances tied, so selection degenerates to
    the seeded shuffle order) via a small, bounded rejection sample of
    ``k`` distinct indices rather than a full-pool permutation.
    """
    n = z_values.size
    if n == 0 or k <= 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
    k_eff = min(k, n)
    if np.isnan(own_z):
        if k_eff >= n:
            idx = np.arange(n)
        else:
            chosen: set[int] = set()
            while len(chosen) < k_eff:
                chosen.add(int(rng.integers(0, n)))
            idx = np.array(sorted(chosen), dtype=np.int64)
        return positions[idx], np.full(idx.size, np.nan)

    dist = np.abs(z_values - own_z)
    part = np.argpartition(dist, k_eff - 1)[:k_eff] if k_eff < n else np.arange(n)
    tiebreak = rng.random(k_eff)
    order_within = np.lexsort((tiebreak, dist[part]))
    selected = part[order_within]
    return positions[selected], dist[selected]


def match_controls(
    events: pd.DataFrame,
    panel: pd.DataFrame,
    n_controls: int = 5,
    match_cols: tuple[str, ...] = ("realized_volatility", "volatility_regime", "trend_regime"),
    same_symbol_exclusion_days: int = 21,
    seed: int = 0,
) -> pd.DataFrame:
    """Sample ``n_controls`` matched (symbol, date) rows per event.

    ``match_cols[0]`` is treated as the continuous nearest-neighbor feature
    (standardized panel-wide, ``(x - mean) / std``); ``match_cols[1:]`` are
    exact-match categorical bucket keys -- this is the exact
    ``("realized_volatility", "volatility_regime", "trend_regime")`` default
    order and the convention every caller of this function must follow.
    ``panel`` must already carry ``match_cols`` (call
    ``attach_regime_columns`` first if it does not -- this function does not
    attach them itself, see the module docstring).

    Exclusion: a candidate ``(symbol, date)`` row is off-limits if it falls
    within ``same_symbol_exclusion_days`` CALENDAR days of ANY event on that
    symbol (not only the event currently being matched), so a control set
    never accidentally straddles a neighboring event's own pre/post-event
    dynamics.

    Same-symbol candidates within the event's regime bucket are preferred;
    if fewer than ``n_controls`` remain after exclusion, the remainder is
    filled from any symbol in the same bucket (documented degrade -- there
    is no sector taxonomy wired into this repo's panel, so "prefer
    same-sector" is not implementable and is not attempted; this is a
    genuine simplification, not a fake sector map). If the whole bucket
    (any symbol) has fewer than ``n_controls`` eligible rows, however many
    are available are returned rather than fabricating extras.

    Deterministic given ``seed`` (``numpy.random.default_rng``), used only
    to break exact-distance ties reproducibly.

    Returns one row per (event, selected control) pair: ``event_symbol``,
    ``event_t0``, ``control_symbol``, ``control_t0``, ``rank`` (1-indexed,
    nearest first), ``same_symbol``, ``distance`` (standardized |Δcontinuous
    feature|), plus the matched categorical bucket values and the raw
    continuous feature value for the control row.
    """
    if n_controls < 1:
        raise ValueError("n_controls must be positive")
    if same_symbol_exclusion_days < 0:
        raise ValueError("same_symbol_exclusion_days must be non-negative")
    if not match_cols:
        raise ValueError("match_cols must contain at least one column (the continuous NN feature)")
    missing_cols = [c for c in match_cols if c not in panel.columns]
    if missing_cols:
        raise KeyError(
            f"panel is missing match_cols {missing_cols}; call "
            "attach_regime_columns(panel, bars_by_symbol) first"
        )
    if "symbol" not in events.columns or "t0" not in events.columns:
        raise KeyError("events must have 'symbol' and 't0' columns")
    if "symbol" not in panel.columns or "date" not in panel.columns:
        raise KeyError("panel must have 'symbol' and 'date' columns")

    continuous_col = match_cols[0]
    categorical_cols = list(match_cols[1:])
    rng = np.random.default_rng(seed)

    work = panel.reset_index(drop=True).copy()
    work["_date"] = pd.to_datetime(work["date"]).dt.normalize()
    cont = pd.to_numeric(work[continuous_col], errors="coerce")
    mean = float(cont.mean()) if cont.notna().any() else 0.0
    std = float(cont.std(ddof=0)) if cont.notna().any() else 0.0
    std = std if std > 0 else 1.0
    work["_z"] = (cont - mean) / std
    if categorical_cols:
        work["_bucket"] = list(zip(*(work[c].astype(str) for c in categorical_cols)))
    else:
        work["_bucket"] = [()] * len(work)

    events_reset = events.reset_index(drop=True)
    events_ts = pd.to_datetime(events_reset["t0"]).dt.normalize()
    events_by_symbol: dict[Any, np.ndarray] = {}
    for sym, grp in pd.DataFrame({"symbol": events_reset["symbol"].to_numpy(), "t0": events_ts.to_numpy()}).groupby("symbol"):
        events_by_symbol[sym] = np.sort(grp["t0"].to_numpy())

    # Vectorized exclusion mask -- replaces a Python-level `_is_excluded`
    # scan over every panel row (O(n_panel_rows * events_per_symbol)) with a
    # per-symbol `searchsorted` against that symbol's SORTED event dates:
    # the nearest event to any query date is always its immediate neighbor
    # at the sorted insertion point, so checking just those two neighbors
    # (clipped at the array edges) is exactly equivalent to checking "is any
    # event within the window" -- standard 1D nearest-neighbor-in-sorted-
    # array reasoning, just applied per symbol group instead of per row.
    work_dates = work["_date"].to_numpy()
    work_symbols = work["symbol"].to_numpy()
    excluded = np.zeros(len(work), dtype=bool)
    for sym, t0s in events_by_symbol.items():
        if t0s.size == 0:
            continue
        sym_mask = work_symbols == sym
        if not sym_mask.any():
            continue
        idx = np.nonzero(sym_mask)[0]
        d = work_dates[idx]
        pos_right = np.clip(np.searchsorted(t0s, d), 0, t0s.size - 1)
        pos_left = np.clip(pos_right - 1, 0, t0s.size - 1)
        gap_right = np.abs((t0s[pos_right] - d) / np.timedelta64(1, "D"))
        gap_left = np.abs((t0s[pos_left] - d) / np.timedelta64(1, "D"))
        excluded[idx] = np.minimum(gap_right, gap_left) <= same_symbol_exclusion_days
    work["_excluded"] = excluded

    available = work.loc[~work["_excluded"]]
    # Per-bucket numpy arrays (row position / symbol / z-score) so the
    # per-event nearest-neighbor selection below is pure numpy indexing,
    # never pandas `.loc` boolean masking, inside the hot loop.
    bucket_arrays: dict[Any, dict[str, np.ndarray]] = {
        key: {
            "_pos": grp.index.to_numpy(dtype=np.int64),
            "symbol": grp["symbol"].to_numpy(),
            "_z": grp["_z"].to_numpy(dtype=float),
        }
        for key, grp in available.groupby("_bucket")
    }
    # (bucket, symbol) -> (same_pos, same_z, other_pos, other_z), filled
    # lazily and reused across every event that shares a (bucket, symbol)
    # pair (an event's own symbol repeats across ~n_events/n_symbols events
    # on average) instead of re-masking the bucket array from scratch each
    # time.
    split_cache: dict[tuple[Any, Any], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}

    # One-time vectorized (symbol, date) -> row-position lookup for every
    # event's OWN panel row. Replaces the old per-event
    # `panel.loc[(panel["symbol"] == sym) & (pd.to_datetime(panel["date"]).dt.normalize() == t0)]`,
    # which re-parsed and re-scanned the ENTIRE panel date column on every
    # single event -- O(n_events * n_panel_rows), by far the dominant cost
    # at full-universe scale (20k+ events against a 1M+ row panel). Semantics
    # preserved exactly: for a (symbol, date) with multiple panel rows
    # (shouldn't happen per the panel contract, but not fatal), the FIRST
    # row in panel's original order is used -- matching the old code's
    # `.iloc[0]` on the boolean-filtered slice.
    own_key = pd.DataFrame({
        "symbol": events_reset["symbol"].to_numpy(),
        "_date": events_ts.to_numpy(),
        "_evorder": np.arange(len(events_reset)),
    })
    work_positions = pd.DataFrame({
        "symbol": work["symbol"].to_numpy(),
        "_date": work_dates,
        "_pos": np.arange(len(work)),
    }).drop_duplicates(subset=["symbol", "_date"], keep="first")
    own_merged = own_key.merge(work_positions, on=["symbol", "_date"], how="left").sort_values("_evorder")
    missing = own_merged["_pos"].isna()
    if missing.any():
        bad = own_merged.loc[missing].iloc[0]
        raise ValueError(
            f"event ({bad['symbol']}, {pd.Timestamp(bad['_date']).date()}) has no matching (symbol,date) row in panel"
        )
    own_pos_arr = own_merged["_pos"].to_numpy(dtype=np.int64)

    rows: list[dict] = []
    for i, (_, event) in enumerate(events_reset.iterrows()):
        sym = event["symbol"]
        t0 = pd.Timestamp(event["t0"]).normalize()
        own = work.iloc[own_pos_arr[i]]
        own_z = (float(own[continuous_col]) - mean) / std if pd.notna(own[continuous_col]) else np.nan
        own_bucket = tuple(str(own[c]) for c in categorical_cols) if categorical_cols else ()

        info = bucket_arrays.get(own_bucket)
        if info is None:
            same_pos = other_pos = np.empty(0, dtype=np.int64)
            same_z = other_z = np.empty(0, dtype=float)
        else:
            cache_key = (own_bucket, sym)
            cached = split_cache.get(cache_key)
            if cached is None:
                sym_mask = info["symbol"] == sym
                same_pos = info["_pos"][sym_mask]
                same_z = info["_z"][sym_mask]
                other_pos = info["_pos"][~sym_mask]
                other_z = info["_z"][~sym_mask]
                split_cache[cache_key] = (same_pos, same_z, other_pos, other_z)
            else:
                same_pos, same_z, other_pos, other_z = cached

        picked_pos, picked_dist = _nearest_k(same_z, same_pos, own_z, n_controls, rng)
        remaining = n_controls - picked_pos.size
        if remaining > 0:
            fill_pos, fill_dist = _nearest_k(other_z, other_pos, own_z, remaining, rng)
            picked_pos = np.concatenate([picked_pos, fill_pos])
            picked_dist = np.concatenate([picked_dist, fill_dist])

        for rank, (pos, dist) in enumerate(zip(picked_pos, picked_dist), start=1):
            control = work.iloc[pos]
            row = {
                "event_symbol": sym,
                "event_t0": t0,
                "control_symbol": control["symbol"],
                "control_t0": control["_date"],
                "rank": rank,
                "same_symbol": bool(control["symbol"] == sym),
                "distance": float(dist) if np.isfinite(own_z) else np.nan,
                continuous_col: float(control[continuous_col]) if pd.notna(control[continuous_col]) else np.nan,
            }
            for c in categorical_cols:
                row[c] = control[c]
            rows.append(row)

    columns = ["event_symbol", "event_t0", "control_symbol", "control_t0", "rank", "same_symbol", "distance", continuous_col, *categorical_cols]
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# event_vs_control_stats
# ---------------------------------------------------------------------------

def event_vs_control_stats(event_labels: pd.DataFrame, control_labels: pd.DataFrame) -> dict:
    """Event-vs-matched-control effect sizes with date-clustered inference.

    Sign convention (fixed, documented once, used consistently):

    * ``delta_p_down_first = P(DOWN_FIRST | events) - P(DOWN_FIRST | controls)``
      -- positive means events break down first more often than controls.
    * ``delta_terminal_return`` is the mean, across events, of
      ``event.terminal_return - mean(that event's matched controls'
      terminal_return)`` -- a PAIRED difference, not an unpaired
      two-sample difference of means, so each event's own idiosyncratic
      level is differenced out before averaging. Positive means events
      subsequently outperform their matched controls over the horizon.

    ``control_labels`` must carry ``event_symbol``/``event_t0`` pass-through
    columns (exactly what ``match_controls``'s output has, after running its
    rows through ``competing_barrier_labels`` with ``t0=control_t0``,
    ``symbol=control_symbol`` -- ``competing_barrier_labels`` preserves
    every input column unchanged) so each control can be attributed back to
    the event it was matched to.

    Newey-West t and the date-block bootstrap CI (both from
    ``research/statistics.py``, not reimplemented) are computed on the
    paired-difference series, blocked/dated by each event's OWN ``t0`` --
    this is what makes the inference respect cross-sectional clustering on
    high-stress days (many symbols cascading the same date), per the plan's
    explicit risk note: multiple events sharing a date are still multiple
    independent paired-difference observations at the row level, but
    ``date_block_bootstrap_ci`` collapses same-date rows to one mean before
    resampling dates as blocks, which is exactly the intended clustering
    correction.
    """
    required_event_cols = {"symbol", "t0", "outcome", "terminal_return"}
    missing = required_event_cols.difference(event_labels.columns)
    if missing:
        raise KeyError(f"event_labels missing columns: {sorted(missing)}")
    required_control_cols = {"event_symbol", "event_t0", "outcome", "terminal_return"}
    missing_c = required_control_cols.difference(control_labels.columns)
    if missing_c:
        raise KeyError(f"control_labels missing columns: {sorted(missing_c)}")

    events = event_labels.copy()
    events["_down"] = (events["outcome"] == _OUTCOME_DOWN).astype(float)

    controls = control_labels.copy()
    controls["_down"] = (controls["outcome"] == _OUTCOME_DOWN).astype(float)
    control_group = controls.groupby(["event_symbol", "event_t0"]).agg(
        control_terminal_return=("terminal_return", "mean"),
        control_down_first=("_down", "mean"),
        n_controls_used=("terminal_return", "size"),
    ).reset_index()

    merged = events.merge(
        control_group,
        left_on=["symbol", "t0"],
        right_on=["event_symbol", "event_t0"],
        how="inner",
    )

    p_down_events = float(events["_down"].mean()) if len(events) else float("nan")
    p_down_controls = float(controls["_down"].mean()) if len(controls) else float("nan")
    delta_p_down_first = p_down_events - p_down_controls

    paired = merged.dropna(subset=["terminal_return", "control_terminal_return"]).copy()

    if paired.empty:
        delta_terminal_return = float("nan")
        newey_west_t = float("nan")
        bootstrap_ci: dict | None = None
        n_paired = 0
    else:
        paired["_diff"] = paired["terminal_return"] - paired["control_terminal_return"]
        delta_terminal_return = float(paired["_diff"].mean())
        newey_west_t = newey_west_tstat(paired["_diff"].to_numpy(dtype=float))
        ci = date_block_bootstrap_ci(paired["_diff"].to_numpy(dtype=float), paired["t0"].to_numpy())
        bootstrap_ci = {
            "estimate": ci.estimate,
            "lower": ci.lower,
            "upper": ci.upper,
            "confidence": ci.confidence,
            "n_dates": ci.n_dates,
            "block_size": ci.block_size,
            "n_bootstrap": ci.n_bootstrap,
        }
        n_paired = int(len(paired))

    return {
        "delta_terminal_return": delta_terminal_return,
        "delta_p_down_first": delta_p_down_first,
        "newey_west_t": newey_west_t,
        "bootstrap_ci": bootstrap_ci,
        "n_events": int(len(event_labels)),
        "n_controls": int(len(control_labels)),
        "n_paired": n_paired,
    }


# ---------------------------------------------------------------------------
# permutation_null
# ---------------------------------------------------------------------------

def permutation_null(
    events: pd.DataFrame,
    panel: pd.DataFrame,
    stat_fn: Callable[[pd.DataFrame], float],
    n_perm: int = 2000,
    seed: int = 0,
) -> dict:
    """Circular per-symbol date-shift permutation null for ``stat_fn(events)``.

    Calling convention: ``stat_fn`` takes an ``events``-shaped DataFrame
    (must have ``symbol``/``t0`` columns; typically the same columns as the
    real ``events`` table) and returns a single scalar effect size -- the
    intended composition is a small closure over
    ``competing_barrier_labels`` + ``match_controls`` +
    ``event_vs_control_stats`` that recomputes ``delta_terminal_return`` (or
    another chosen effect size) end-to-end for whatever ``(symbol, t0)``
    pairs it is given. ``permutation_null`` does not know or care what
    ``stat_fn`` does internally -- it only manipulates the ``t0`` column.

    For each of ``n_perm`` draws, every symbol present in ``events`` gets
    its OWN random circular offset (via ``rng.integers``) applied to ALL of
    that symbol's event dates at once: each event's ``t0`` is located in
    that symbol's sorted date universe (``panel``'s trading dates for that
    symbol) and moved forward by ``offset`` positions, wrapping around
    (modulo the number of trading dates). Shifting every one of a symbol's
    events by the SAME offset preserves the relative spacing between that
    symbol's own events (and therefore its autocorrelation structure) while
    destroying the true alignment between "this date was flagged as an
    event" and whatever happened next -- exactly the property the plan asks
    for. Only ``t0`` is touched; every other column of ``events``
    (``direction``, ``feat_*`` frozen-at-``t0`` values, etc.) is left as-is,
    so a ``stat_fn`` that reads those other columns is reading stale values
    under permutation -- by design, since the only thing this null is
    allowed to break is the ``t0`` <-> outcome alignment.

    ``p_value`` is two-sided against the empirical null distribution's own
    mean (not assumed to be exactly zero): ``(1 + #{|null - null_mean| >=
    |observed - null_mean|}) / (n_perm + 1)``.
    """
    if n_perm < 1:
        raise ValueError("n_perm must be positive")
    if "symbol" not in events.columns or "t0" not in events.columns:
        raise KeyError("events must have 'symbol' and 't0' columns")
    if "symbol" not in panel.columns or "date" not in panel.columns:
        raise KeyError("panel must have 'symbol' and 'date' columns")

    rng = np.random.default_rng(seed)
    observed = float(stat_fn(events))

    symbol_dates: dict[Any, np.ndarray] = {
        sym: np.sort(pd.to_datetime(grp["date"]).unique())
        for sym, grp in panel.groupby("symbol")
    }

    base_t0 = pd.to_datetime(events["t0"]).to_numpy()
    symbols = events["symbol"].to_numpy()
    unique_symbols = pd.unique(symbols)

    null_values = np.empty(n_perm, dtype=float)
    for p in range(n_perm):
        shifted = events.copy()
        new_t0 = base_t0.copy()
        for sym in unique_symbols:
            dates = symbol_dates.get(sym)
            mask = symbols == sym
            if dates is None or dates.size == 0:
                continue
            offset = int(rng.integers(0, dates.size))
            positions = np.searchsorted(dates, base_t0[mask])
            positions = np.clip(positions, 0, dates.size - 1)
            new_positions = (positions + offset) % dates.size
            new_t0[mask] = dates[new_positions]
        shifted["t0"] = new_t0
        null_values[p] = float(stat_fn(shifted))

    null_mean = float(np.mean(null_values))
    null_std = float(np.std(null_values, ddof=1)) if n_perm > 1 else 0.0
    observed_dev = abs(observed - null_mean)
    extreme = int(np.sum(np.abs(null_values - null_mean) >= observed_dev))
    p_value = float((1 + extreme) / (n_perm + 1))

    return {
        "p_value": p_value,
        "null_mean": null_mean,
        "null_std": null_std,
        "observed": observed,
        "n_perm": int(n_perm),
    }


# ---------------------------------------------------------------------------
# deflate_grid_pvalues
# ---------------------------------------------------------------------------

def deflate_grid_pvalues(grid_results: Sequence[Mapping[str, Any]]) -> dict:
    """Search-multiplicity deflation across a small preregistered grid.

    Composes ``research/statistics.py``'s two existing multiplicity tools
    rather than reimplementing either:

    1. Each grid point's paired per-event difference series (from
       ``event_vs_control_stats``, expected under keys
       ``"paired_diff_series"`` / ``"paired_dates"`` on each entry of
       ``grid_results``) is collapsed to one daily-mean series (same
       date-clustering idea ``date_block_bootstrap_ci`` uses).
    2. When at least two grid points supply a usable series AND their daily
       series share at least two common dates, those series are aligned on
       their common date intersection into an
       ``(n_dates, n_trials)`` matrix, correlated
       (``trial_return_correlation_matrix``), and reduced to an effective
       trial count (``effective_trial_count_from_correlation``) -- the
       entropy-based Kish effective-N the two functions already implement.
       This is a genuine (if coarse) multiplicity correction: three highly
       correlated grid variants (e.g. two configs differing only in
       ``horizon_days``) should not each count as a full independent trial.
    3. When fewer than two grid points have usable series, or they share
       fewer than two common dates, this degrades to the conservative
       fallback ``effective_trial_count = len(grid_results)`` (no
       reduction -- full Bonferroni), which is always valid, just not
       tightened by the correlation structure.
    4. Each grid point's raw permutation ``p_value`` is Bonferroni-deflated
       by the resulting effective trial count
       (``min(1.0, p_value * k_eff)``), and, when that grid point's series
       has at least 2 non-degenerate observations,
       ``bonferroni_deflated_sharpe_approximation`` is also run on it with
       ``trial_count=round(k_eff)`` for a second, Sharpe-scale view of the
       same deflation.

    This function is intentionally a light, documented composition -- not a
    new statistical primitive -- per the plan's own "implement a small
    helper ... if that composition isn't obvious" allowance.
    """
    if not grid_results:
        raise ValueError("grid_results must be non-empty")
    k = len(grid_results)

    daily_series: list[pd.Series | None] = []
    for entry in grid_results:
        diffs = np.asarray(entry.get("paired_diff_series", []), dtype=float)
        raw_dates = entry.get("paired_dates", [])
        if diffs.size == 0 or len(raw_dates) != diffs.size:
            daily_series.append(None)
            continue
        dates = pd.to_datetime(list(raw_dates)).normalize()
        series = pd.Series(diffs, index=dates).groupby(level=0).mean()
        daily_series.append(series)

    valid = [s for s in daily_series if s is not None]
    k_eff = float(k)
    if len(valid) >= 2:
        common_index = valid[0].index
        for s in valid[1:]:
            common_index = common_index.intersection(s.index)
        if len(common_index) >= 2:
            matrix = np.column_stack([s.reindex(common_index).to_numpy(dtype=float) for s in valid])
            corr = trial_return_correlation_matrix(matrix)
            k_eff = effective_trial_count_from_correlation(corr).effective_trial_count

    trial_count = max(1, int(round(k_eff)))
    per_grid: list[dict[str, Any]] = []
    for entry, series in zip(grid_results, daily_series):
        raw_p = entry.get("p_value")
        raw_p = float(raw_p) if raw_p is not None else float("nan")
        deflated_p = min(1.0, raw_p * k_eff) if np.isfinite(raw_p) else float("nan")
        deflated_sharpe = None
        if series is not None and series.size >= 2 and float(np.std(series.to_numpy(dtype=float), ddof=1)) > 0.0:
            approx = bonferroni_deflated_sharpe_approximation(series.to_numpy(dtype=float), trial_count=trial_count)
            deflated_sharpe = {
                "observed_sharpe": approx.observed_sharpe,
                "lower_bound_sharpe": approx.lower_bound_sharpe,
                "daily_sharpe": approx.daily_sharpe,
                "trial_count": approx.trial_count,
                "n_observations": approx.n_observations,
                "confidence": approx.confidence,
                "critical_z": approx.critical_z,
            }
        per_grid.append({
            "config": entry.get("config"),
            "raw_p_value": raw_p,
            "deflated_p_value": deflated_p,
            "deflated_sharpe": deflated_sharpe,
        })

    return {
        "raw_trial_count": k,
        "effective_trial_count": k_eff,
        "per_grid": per_grid,
    }
