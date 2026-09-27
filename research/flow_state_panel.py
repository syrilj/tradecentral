"""
Flow-state panel assembly (I/O layer).

This module is the only place in the flow-state feature stack that touches
disk. All the actual math lives in ``research/flow_state.py`` as pure
functions; this module loads ``data/1d_wide/*.parquet`` bars (and,
optionally, the FINRA short-volume panel), calls those pure functions per
symbol, and concatenates the results into one long panel -- mirroring the
``research/`` (pure math) vs ``tools/`` (I/O) split described in the plan
doc, pulled one level into ``research/`` only because ``flow_state.py``
itself was already long enough (~800 lines) that adding the loader here
keeps each file under a readable size, per the plan's own escape hatch.

Sealed terminal holdout: bars from 2026-07-13 onward are never loaded by
this module unless the caller explicitly passes ``allow_holdout=True``
(mirrors ``research/directional_bakeoff.py``'s ``BakeoffProtocol``).

Barrier-field recompute cadence
--------------------------------
``barrier_density`` is documented (in ``flow_state.py``) as an as-of-now
snapshot -- it scans every bar for swing pivots and spreads each bar's
volume across its high/low range, an O(n) cost per call. Phase 2's matched-
control study needs TEST/CASCADE/ABSORB episodes scattered across the whole
~8-year history for all 557 symbols, not just each symbol's latest session,
which means the panel needs barrier-derived features at many historical
points -- but recomputing the full snapshot at every one of ~2500 daily
rows x 557 symbols is not tractable for a nightly batch build.

The compromise implemented here (``_periodic_barrier_fields``): recompute
the barrier snapshot every ``cfg.barrier_recompute_every_n_days`` trading
days (default 10), using only bars up to and including that recompute row
(still trailing-only -- no lookahead), and forward-fill the resulting
support/resistance price, mass, and air-pocket-score fields to the rows in
between. This is a genuine structural approximation, not a documentation
fig-leaf: the barrier field (swing highs/lows, volume nodes, round numbers)
moves slowly relative to daily flow/liquidity features, so treating it as
piecewise-constant between recomputes is a reasonable trade against O(n)-
per-row cost. What breaks if a caller forgets this: a barrier break/test
detected on a specific historical date is being checked against a
support/resistance level that can be up to ``barrier_recompute_every_n_days``
sessions stale, not the exact level as of that date -- acceptable for a
matched-control study over thousands of events, not acceptable if a caller
later wants an exact intraday-precision barrier read for one date. Each
recompute also bounds its input bars to the trailing
``cfg.barrier_history_lookback_bars`` (not full symbol history) to keep
per-call cost roughly constant; ``barrier_density``'s linear time-decay
already makes older bars contribute near-zero mass, so little is lost.
Every symbol's LAST row is always recomputed exactly, unconditionally --
that is the "current state" a live tab would show.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from .flow_state import (
    FlowStateConfig,
    air_pocket_score,
    amihud_illiquidity,
    amihud_shock,
    barrier_continuation_score,
    barrier_density,
    classify_states,
    corwin_schultz_spread,
    flow_persistence,
    flow_z,
    impact_beta,
    nearest_nodes,
    signed_volume_proxy,
    short_pressure_z,
)
from .flow_state import _trailing_atr  # shared ATR definition (module-internal, same package)

EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = EDGE_ROOT / "data"

TERMINAL_HOLDOUT_START = "2026-07-13"

REQUIRED_OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def _guard_holdout(end: str, allow_holdout: bool) -> None:
    if allow_holdout:
        return
    if pd.Timestamp(end) >= pd.Timestamp(TERMINAL_HOLDOUT_START):
        raise ValueError(
            f"build_flow_state_panel: end={end!r} touches the sealed terminal "
            f"holdout (>= {TERMINAL_HOLDOUT_START}). Pass allow_holdout=True "
            "only for an explicit, authorized holdout evaluation."
        )


def _load_symbol_bars(symbol: str, data_root: Path, start: str, end: str) -> pd.DataFrame | None:
    path = data_root / "1d_wide" / f"{symbol}.parquet"
    if not path.exists():
        return None
    bars = pd.read_parquet(path)
    missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in bars.columns]
    if missing:
        return None
    bars = bars.sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    bars = bars.loc[(bars.index >= pd.Timestamp(start)) & (bars.index <= pd.Timestamp(end))]
    return bars if len(bars) > 0 else None


_BARRIER_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "support_price", "support_mass", "resistance_price", "resistance_mass",
    "mass_threshold", "air_pocket_up", "air_pocket_down",
)


def _compute_barrier_snapshot(bars_upto: pd.DataFrame, cfg: FlowStateConfig, grid_points: int) -> dict | None:
    """One as-of-``bars_upto``'s-last-row barrier snapshot (see ``barrier_density``).

    Builds a price grid centered on the last close, spanning +/- 10 ATR, runs
    ``barrier_density``, and reduces it to the handful of scalars
    ``classify_states`` (and the panel) actually need: nearest support/
    resistance node price + mass, the density's 75th-percentile "high mass"
    threshold, and the air-pocket score in both directions from the last
    close to the nearest node on that side. Returns ``None`` when there
    isn't enough history yet.
    """
    if len(bars_upto) < max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1:
        return None
    close = bars_upto["close"].astype(float)
    last_close = float(close.iloc[-1])
    atr = float(_trailing_atr(bars_upto, cfg.barrier_atr_window).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        atr = max(last_close * 0.01, 1e-6)
    grid = np.linspace(last_close - atr * 10, last_close + atr * 10, grid_points)
    grid = grid[grid > 0]
    if grid.size < 2:
        return None

    density = barrier_density(bars_upto, grid, cfg)
    nodes = nearest_nodes(density, last_close)
    mass_threshold = float(np.nanpercentile(density.to_numpy(), 75)) if density.size else 0.0
    support_price = nodes.get("support_price")
    resistance_price = nodes.get("resistance_price")
    air_pocket_up = air_pocket_score(density, last_close, resistance_price) if resistance_price is not None else 0.0
    air_pocket_down = air_pocket_score(density, support_price, last_close) if support_price is not None else 0.0
    return {
        "support_price": support_price,
        "support_mass": nodes.get("support_mass"),
        "resistance_price": resistance_price,
        "resistance_mass": nodes.get("resistance_mass"),
        "mass_threshold": mass_threshold,
        "air_pocket_up": air_pocket_up,
        "air_pocket_down": air_pocket_down,
    }


def _periodic_barrier_fields(bars: pd.DataFrame, cfg: FlowStateConfig, grid_points: int = 121) -> pd.DataFrame:
    """Periodically-recomputed, forward-filled barrier snapshot fields.

    ``barrier_density`` is an O(n) computation (swing-pivot scan + volume-
    at-price spread over the lookback window); recomputing a full KDE at
    every historical row for 557 symbols x ~2500 sessions is not tractable
    for a nightly batch build. Instead this recomputes the snapshot only
    every ``cfg.barrier_recompute_every_n_days`` trading days -- using only
    bars available up to and including that recompute row (still
    trailing-only, no lookahead) -- and forward-fills the resulting
    support/resistance price, mass, and air-pocket-score fields to every row
    in between. The barrier field genuinely does not move much day to day,
    so this is a deliberate structural approximation, not a shortcut -- but
    callers must not assume day-to-day exactness: a barrier interaction
    detected between two recompute points is evaluated against a
    support/resistance level that can be up to
    ``barrier_recompute_every_n_days`` sessions stale. The LAST row of
    ``bars`` is always recomputed unconditionally regardless of cadence --
    that is the "current state" a live tab would show.

    Each recompute additionally bounds its input to the trailing
    ``cfg.barrier_history_lookback_bars`` bars, not the symbol's full
    history, to keep the per-call cost roughly constant; ``barrier_density``
    already linearly time-decays older bars to near-zero weight, so this
    mainly discards history that was already contributing almost nothing.
    """
    n = len(bars)
    min_bars = max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1
    cadence = max(int(cfg.barrier_recompute_every_n_days), 1)
    lookback = max(int(cfg.barrier_history_lookback_bars), min_bars)

    raw = {name: pd.Series(np.nan, index=bars.index, dtype=float) for name in _BARRIER_SNAPSHOT_FIELDS}

    if n >= min_bars:
        recompute_idx = sorted(set(range(min_bars - 1, n, cadence)) | {n - 1})
        for i in recompute_idx:
            window_start = max(0, i + 1 - lookback)
            snapshot = _compute_barrier_snapshot(bars.iloc[window_start:i + 1], cfg, grid_points)
            if snapshot is None:
                continue
            for name in _BARRIER_SNAPSHOT_FIELDS:
                value = snapshot[name]
                raw[name].iloc[i] = np.nan if value is None else float(value)

    return pd.DataFrame(raw).ffill()


def _derive_barrier_row_features(bars: pd.DataFrame, filled: pd.DataFrame, cfg: FlowStateConfig) -> pd.DataFrame:
    """Per-row ``classify_states`` barrier columns from the forward-filled snapshot fields.

    Uses each row's own close/high/low (always permitted -- a row may use
    its own data) together with the most recently forward-filled
    support/resistance snapshot (which was, by construction, computed from
    bars at or before that recompute point) plus a genuinely per-row causal
    ATR series -- so every value here still only depends on data <= t.
    """
    close = bars["close"].astype(float)
    atr = _trailing_atr(bars, cfg.barrier_atr_window)
    atr_guarded = atr.where(atr > 0, close * 0.01).replace(0.0, np.nan)

    support = filled["support_price"]
    resistance = filled["resistance_price"]
    support_mass = filled["support_mass"]
    resistance_mass = filled["resistance_mass"]
    mass_threshold = filled["mass_threshold"]
    air_up = filled["air_pocket_up"]
    air_down = filled["air_pocket_down"]

    dist_support = (close - support).abs() / atr_guarded
    dist_resistance = (resistance - close).abs() / atr_guarded
    dist_to_barrier = pd.concat([dist_support, dist_resistance], axis=1).min(axis=1)

    support_is_nearer = dist_support <= dist_resistance
    nearer_mass = support_mass.where(support_is_nearer, resistance_mass)
    barrier_high_mass = nearer_mass.notna() & mass_threshold.notna() & (nearer_mass >= mass_threshold)

    broke_up = resistance.notna() & (close > resistance)
    broke_down = support.notna() & (close < support)
    break_direction = pd.Series(0, index=bars.index, dtype=int)
    break_direction.loc[broke_up] = 1
    break_direction.loc[broke_down & ~broke_up] = -1

    air_pocket_break = pd.Series(0.0, index=bars.index)
    air_pocket_break.loc[break_direction == 1] = air_up.loc[break_direction == 1]
    air_pocket_break.loc[break_direction == -1] = air_down.loc[break_direction == -1]

    out = pd.DataFrame(index=bars.index)
    out["dist_to_barrier_atr"] = dist_to_barrier
    out["barrier_high_mass"] = barrier_high_mass.fillna(False)
    out["barrier_break_direction"] = break_direction
    out["air_pocket_break"] = air_pocket_break.fillna(0.0)
    return out


def _symbol_flow_state_features(bars: pd.DataFrame, cfg: FlowStateConfig, grid_points: int = 121) -> pd.DataFrame:
    """Compute every per-row pure feature for one symbol's bars.

    Barrier-dependent columns required by ``classify_states``
    (``dist_to_barrier_atr``, ``barrier_high_mass``, ``barrier_break_direction``,
    ``air_pocket_break``) come from ``_periodic_barrier_fields`` /
    ``_derive_barrier_row_features``: a periodically-recomputed,
    forward-filled barrier snapshot (see that function's docstring for the
    cadence/cost trade-off), not an exact per-row recomputation -- so
    TEST/CASCADE/ABSORB detected from this panel are accurate to within
    ``cfg.barrier_recompute_every_n_days`` sessions of staleness, not exact
    to the day, except on each symbol's final row which is always fresh.
    """
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    volume = bars["volume"].astype(float)
    returns = close.pct_change()

    svp = signed_volume_proxy(bars)
    fz = flow_z(svp, cfg.flow_z_window)
    persistence = flow_persistence(fz, cfg.flow_persistence_threshold, cfg.flow_persistence_windows)
    amihud = amihud_illiquidity(bars, cfg.amihud_window)
    a_shock = amihud_shock(amihud, cfg.amihud_shock_window)
    cs_spread = corwin_schultz_spread(bars, cfg.corwin_schultz_smooth_window)
    beta = impact_beta(returns, fz, cfg.impact_beta_window)

    daily_range = high - low
    volume_ratio = volume / volume.rolling(20, min_periods=20).mean()
    range_compression = daily_range / daily_range.rolling(20, min_periods=20).mean()

    features = pd.DataFrame(index=bars.index)
    features["signed_volume_proxy"] = svp
    features["flow_z"] = fz
    for w in cfg.flow_persistence_windows:
        features[f"flow_persistence_{w}d"] = persistence[f"persistence_{w}d"]
    features["amihud"] = amihud
    features["amihud_shock"] = a_shock
    features["corwin_schultz_spread"] = cs_spread
    features["impact_beta"] = beta
    features["volume_ratio"] = volume_ratio
    features["range_compression"] = range_compression
    features["signed_flow_sign"] = np.sign(svp).astype(int)

    barrier_snapshots = _periodic_barrier_fields(bars, cfg, grid_points)
    barrier_rows = _derive_barrier_row_features(bars, barrier_snapshots, cfg)
    for col in barrier_rows.columns:
        features[col] = barrier_rows[col]

    # Evidence-backed continuation sleeve: abnormal flow x elevated impact
    # x barrier proximity. Cascade/fade are intentionally not folded in.
    pers_col = f"flow_persistence_{cfg.continuation_persistence_window}d"
    sleeve = barrier_continuation_score(
        features["flow_z"],
        features["impact_beta"],
        features[pers_col],
        features["dist_to_barrier_atr"],
        cfg=cfg,
    )
    for col in sleeve.columns:
        features[col] = sleeve[col]

    return features


def build_flow_state_panel(
    symbols: Sequence[str],
    start: str,
    end: str,
    data_root: Path | None = None,
    *,
    cfg: FlowStateConfig | None = None,
    allow_holdout: bool = False,
) -> pd.DataFrame:
    """Load daily bars for ``symbols``, compute flow-state features, concatenate.

    Loads from ``<data_root or edge/data>/1d_wide/<symbol>.parquet``
    (matching ``tools/api_server.py:_load_smallcap_price_data``'s
    ``open,high,low,close,volume`` / ascending-``DatetimeIndex`` convention).
    Optionally joins the FINRA short-ratio panel via
    ``edge.tools.data_sources.load_finra_short_vol()``; a missing panel
    (``FileNotFoundError``) is caught and reported in the returned warnings
    -- ``short_pressure_z`` becomes absent/NaN for every row rather than
    raising.

    Hard-raises ``ValueError`` if ``end`` touches the sealed terminal
    holdout (>= 2026-07-13) unless ``allow_holdout=True`` is passed
    explicitly (mirrors ``research/directional_bakeoff.py``'s
    ``BakeoffProtocol.__post_init__`` guard).

    Returns a long panel with ``symbol`` and ``date`` columns (not a
    MultiIndex -- simpler to filter/test), one row per symbol-session, plus
    every per-row feature column and the classified ``state`` column. Also
    attaches a ``.attrs["warnings"]`` list of human-readable notes (missing
    symbols, missing short-volume panel, etc.) since a DataFrame has no
    other conventional slot for out-of-band diagnostics.
    """
    _guard_holdout(end, allow_holdout)
    cfg = cfg or FlowStateConfig()
    root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT

    warnings: list[str] = []

    short_vol: pd.Series | None = None
    try:
        from edge.tools.data_sources import load_finra_short_vol
        short_vol = load_finra_short_vol()
    except FileNotFoundError as exc:
        warnings.append(f"FINRA short-volume panel unavailable, short_pressure_z omitted: {exc}")
    except ImportError as exc:
        warnings.append(f"tools.data_sources unavailable, short_pressure_z omitted: {exc}")

    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        bars = _load_symbol_bars(symbol, root, start, end)
        if bars is None:
            warnings.append(f"{symbol}: no usable 1d_wide parquet in range [{start}, {end}]")
            continue
        min_rows = max(cfg.flow_z_window, cfg.amihud_window, cfg.impact_beta_window) + 1
        if len(bars) < min_rows:
            warnings.append(f"{symbol}: only {len(bars)} rows (<{min_rows}), skipped")
            continue

        features = _symbol_flow_state_features(bars, cfg)

        if short_vol is not None:
            try:
                sym_short = short_vol.xs(symbol, level="symbol")
                sym_short = sym_short.reindex(bars.index)
                features["short_pressure_z"] = short_pressure_z(
                    sym_short.dropna(), cfg.short_pressure_window,
                ).reindex(bars.index)
            except KeyError:
                features["short_pressure_z"] = np.nan
        else:
            features["short_pressure_z"] = np.nan

        features["state"] = classify_states(features, cfg)
        features.insert(0, "date", features.index)
        features.insert(0, "symbol", symbol)
        frames.append(features.reset_index(drop=True))

    if frames:
        panel = pd.concat(frames, axis=0, ignore_index=True)
    else:
        panel = pd.DataFrame(columns=["symbol", "date"])

    panel.attrs["warnings"] = warnings
    return panel
