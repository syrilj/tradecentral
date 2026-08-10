#!/usr/bin/env python3
"""Flow-state cross-section: offline artifact producer (Phase 4).

Mirrors `tools/build_changepoints.py`'s shape: nightly, per-symbol-robust,
"read an offline artifact, never compute on request" contract for the
dashboard's `/api/flow-state` endpoint.

Pipeline: `research.flow_state_panel.build_flow_state_panel` (dev-window,
sealed-holdout guarded -- this script never passes `allow_holdout=True`) ->
per-symbol `research.flow_state.extract_events` (already classified inside
the panel) -> event-conditioned competing-barrier labels
(`research.event_labels.competing_barrier_labels`, using a single fixed
config -- this artifact is a descriptive display surface, not the Phase 2
statistical study; the study's own grid search lives in
`tools/build_flow_state_study.py`) -> merge the latest
`runs/flow_state/study_*.json` (if one exists) for the `phenomenon` block ->
write `runs/flow_state/<date>.json` + `latest.json`.

Phase 3 (cascade/fade ML models) does not exist yet: `models` is always
`null` and `tier` is always 0 or 1 -- 1 only when a study artifact exists
AND its own recorded `t1_pass` is `True`. `gate` (the Phase-3 development
gate) is always in its "not yet evaluated" state. Every payload key is
always present, even when empty -- no key is ever omitted, matching the
`_changepoints_payload`/`opportunity_scanner` "never fabricate, always
present" discipline this repo uses everywhere else.

One bad symbol (missing parquet, too little history, a classifier/labeling
exception) is logged, skipped, and counted -- never allowed to kill the
whole run. If literally every symbol fails, this still writes a valid
`latest.json` with `available: false` and a `reason`, never leaving the
file stale or missing (Changepoints/`build_changepoints.py` convention).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.event_labels import competing_barrier_labels  # noqa: E402
from edge.research.flow_state import (  # noqa: E402
    ALL_STATES,
    FlowStateConfig,
    air_pocket_score,
    barrier_density,
    extract_events,
    nearest_nodes,
)
from edge.research.flow_state import _trailing_atr  # noqa: E402  (module-internal, same package -- see flow_state_panel.py's identical import)
from edge.research.flow_state_panel import (  # noqa: E402
    TERMINAL_HOLDOUT_START,
    build_flow_state_panel,
)

DATA_ROOT = EDGE_ROOT / "data"
OUTPUT_ROOT = EDGE_ROOT / "runs" / "flow_state"
DEFAULT_UNIVERSE_PATH = EDGE_ROOT / "config" / "universe_wide.json"

# This artifact's own fixed competing-barrier config for the event table --
# deliberately NOT a grid search (that is Phase 2's job, `build_flow_state_study.py`).
# Matches the first point of that script's frozen GRID so the two surfaces
# agree when both are available.
EVENT_LABEL_K_DOWN = 1.5
EVENT_LABEL_K_UP = 1.5
EVENT_LABEL_HORIZON_DAYS = 10
EVENT_LABEL_VOL_WINDOW = 21
EVENT_RESOLUTION_HORIZON = 20

DEFAULT_TOP_N = 20
DEFAULT_TIMELINE_SESSIONS = 120
BARRIER_GRID_POINTS = 121

CAVEATS: tuple[str, ...] = (
    "Every state/flow/impact feature here is a daily-bar proxy, not true "
    "intraday order-flow imbalance -- this repo has no trades/quotes/L2 data.",
    "No order-book depth exists anywhere in this repo; liquidity is inferred "
    "from dollar-volume (Amihud illiquidity) and the Corwin-Schultz high-low "
    "spread estimator, not a measured book.",
    "continuation_score is the barrier-conditioned sleeve candidate "
    "(|flow_z| x max(impact_beta_z,0) x persistence x exp(-d/tau)) -- a "
    "descriptive ranking for 15-30m-style CONTINUATION research, not a "
    "bottom/fade predictor and not a trading authorization.",
    "stress_rank is an ORDINAL rank across the symbols in this run (1 = most "
    "stressed), not a probability or expected value -- same convention as "
    "daily_plays/opportunity_scanner.py's composite_score.",
    "barrier_density/next_support/next_resistance are a periodic, "
    "forward-filled snapshot (see research/flow_state_panel.py) -- they can "
    "be up to FlowStateConfig.barrier_recompute_every_n_days sessions stale "
    "except on each symbol's most recent session, which is always fresh.",
    "impact_curve is a descriptive event-study curve pooled across symbols, "
    "not a causal impact estimate.",
    "CASCADE/FADE remain labeled for research visibility but are NOT part of "
    "the evidence-backed continuation sleeve (sample was insufficient).",
    "This artifact never authorizes a trade: decision_authorized is only "
    "true once a Phase-3 development gate (research/gates.py) records a "
    "pass, which does not exist yet.",
)


# --------------------------------------------------------------------------- #
# Small numeric/JSON helpers (matches build_changepoints.py's `_safe_round`).
# --------------------------------------------------------------------------- #
def _safe_round(x: Any, dp: int) -> float | None:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, dp)


def _safe_float(x: Any) -> float | None:
    return _safe_round(x, 8)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# --------------------------------------------------------------------------- #
# Universe resolution -- same convention as tools/build_changepoints.py.
# --------------------------------------------------------------------------- #
def _load_universe(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"{path} has no non-empty 'symbols' list")
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


# --------------------------------------------------------------------------- #
# Raw OHLCV bars -- needed for barrier snapshots and competing-barrier labels;
# build_flow_state_panel only returns derived features, not raw bars.
# --------------------------------------------------------------------------- #
def _load_bars(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    path = DATA_ROOT / "1d_wide" / f"{symbol}.parquet"
    if not path.is_file():
        return None
    try:
        bars = pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return None
    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in bars.columns]
    if missing:
        return None
    bars = bars.sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    bars = bars.loc[(bars.index >= pd.Timestamp(start)) & (bars.index <= pd.Timestamp(end))]
    return bars if len(bars) > 0 else None


# --------------------------------------------------------------------------- #
# Latest Phase-2 study artifact (glob by filename -- study_<date>.json sorts
# lexically by date since the date format is ISO 8601).
# --------------------------------------------------------------------------- #
def _latest_study_path(out_dir: Path) -> Path | None:
    candidates = sorted(out_dir.glob("study_*.json"))
    return candidates[-1] if candidates else None


def _load_latest_study(out_dir: Path) -> dict | None:
    path = _latest_study_path(out_dir)
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _select_phenomenon_grid_point(study: dict) -> dict | None:
    """Pick one grid point to summarize in the `phenomenon` block.

    Preference: any grid point whose own `t1_pass` is True (if several pass,
    the one with the smallest deflated p-value); otherwise the grid point
    with the smallest deflated p-value overall (most suggestive evidence,
    even though it didn't clear the T1 bar) so the panel shows something
    informative rather than an arbitrary first entry.
    """
    results = study.get("grid_results")
    if not isinstance(results, list) or not results:
        return None

    def _deflated_p(entry: dict) -> float:
        p = entry.get("deflated_p_value")
        try:
            pf = float(p)
        except (TypeError, ValueError):
            return float("inf")
        return pf if math.isfinite(pf) else float("inf")

    passing = [r for r in results if isinstance(r, dict) and r.get("t1_pass")]
    pool = passing if passing else [r for r in results if isinstance(r, dict)]
    if not pool:
        return None
    return min(pool, key=_deflated_p)


def _build_phenomenon_block(study: dict | None) -> dict:
    empty = {
        "tested": False, "effect": None, "nw_t": None, "boot_ci": None,
        "perm_p": None, "n_events": 0, "n_controls": 0, "grid": [],
        "prereg_id": None, "passed": False,
    }
    if not study:
        return empty
    chosen = _select_phenomenon_grid_point(study)
    if chosen is None:
        return {**empty, "tested": True, "grid": study.get("grid") or [],
                "prereg_id": study.get("experiment_id"), "passed": bool(study.get("t1_pass", False))}

    stats = chosen.get("stats") or {}
    boot_ci = stats.get("bootstrap_ci")
    boot_ci_pair = None
    if isinstance(boot_ci, dict) and boot_ci.get("lower") is not None and boot_ci.get("upper") is not None:
        boot_ci_pair = [_safe_float(boot_ci["lower"]), _safe_float(boot_ci["upper"])]

    return {
        "tested": True,
        "effect": _safe_float(stats.get("delta_terminal_return")),
        "nw_t": _safe_float(stats.get("newey_west_t")),
        "boot_ci": boot_ci_pair,
        # Deflated (multiplicity-corrected) p-value -- the gating-relevant
        # number, not the raw per-grid-point permutation p.
        "perm_p": _safe_float(chosen.get("deflated_p_value")),
        "n_events": int(stats.get("n_events") or 0),
        "n_controls": int(stats.get("n_controls") or 0),
        "grid": study.get("grid") or [],
        "prereg_id": study.get("experiment_id"),
        "passed": bool(study.get("t1_pass", False)),
    }


def _gate_block() -> dict:
    # Phase 3 (development gate) does not exist yet -- always "not evaluated".
    return {"evaluated": False, "passed": False, "checks": {}, "ledger_id": None}


# --------------------------------------------------------------------------- #
# Per-symbol barrier snapshot -- a fresh as-of-last-row barrier_density call
# (research/flow_state.py's documented single-snapshot convention), reused
# for both the state board's next_support/next_resistance/air-pocket scalars
# and (for top-N symbols only) the full density curve in `barrier_fields`.
# --------------------------------------------------------------------------- #
def _barrier_snapshot(bars: pd.DataFrame, cfg: FlowStateConfig, grid_points: int = BARRIER_GRID_POINTS) -> dict | None:
    min_bars = max(cfg.barrier_swing_lookback, cfg.barrier_atr_window) + 1
    if len(bars) < min_bars:
        return None
    close = bars["close"].astype(float)
    last_close = float(close.iloc[-1])
    atr = float(_trailing_atr(bars, cfg.barrier_atr_window).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        atr = max(last_close * 0.01, 1e-6)
    grid = np.linspace(last_close - atr * 10, last_close + atr * 10, grid_points)
    grid = grid[grid > 0]
    if grid.size < 2:
        return None

    density = barrier_density(bars, grid, cfg)
    nodes = nearest_nodes(density, last_close)
    support_price = nodes.get("support_price")
    resistance_price = nodes.get("resistance_price")
    air_up = air_pocket_score(density, last_close, resistance_price) if resistance_price is not None else 0.0
    air_down = air_pocket_score(density, support_price, last_close) if support_price is not None else 0.0

    return {
        "price": last_close,
        "grid": grid,
        "density": density.to_numpy(dtype=float),
        "support_price": support_price,
        "support_mass": nodes.get("support_mass"),
        "resistance_price": resistance_price,
        "resistance_mass": nodes.get("resistance_mass"),
        "air_pocket_up": air_up,
        "air_pocket_down": air_down,
    }


def _density_peaks(grid: np.ndarray, density: np.ndarray, top_k: int = 8) -> list[dict]:
    """Local-maxima nodes across the whole density curve, strongest first.

    Same trailing/leading-comparison peak definition `nearest_nodes` uses
    internally, but returns every peak (capped to `top_k` by mass) instead of
    only the nearest support/resistance pair -- meant for the barrier chart
    to plot multiple node markers, not just the two nearest the price.
    """
    n = len(grid)
    if n < 3:
        return []
    is_peak = np.ones(n, dtype=bool)
    left_ok = np.empty(n, dtype=bool)
    right_ok = np.empty(n, dtype=bool)
    left_ok[0], left_ok[1:] = True, density[1:] >= density[:-1]
    right_ok[-1], right_ok[:-1] = True, density[:-1] >= density[1:]
    is_peak = left_ok & right_ok
    peak_prices = grid[is_peak]
    peak_mass = density[is_peak]
    order = np.argsort(-peak_mass)[:top_k]
    return [
        {"price": _safe_round(float(peak_prices[i]), 4), "mass": _safe_round(float(peak_mass[i]), 6)}
        for i in order
    ]


# --------------------------------------------------------------------------- #
# Days-in-state, state path.
# --------------------------------------------------------------------------- #
def _days_in_state(states: pd.Series) -> int:
    if len(states) == 0:
        return 0
    current = states.iloc[-1]
    count = 0
    for value in states.iloc[::-1]:
        if value != current:
            break
        count += 1
    return count


def _state_path(states: pd.Series, t0: pd.Timestamp, resolution_date: pd.Timestamp) -> list[str]:
    try:
        sub = states.loc[(states.index >= pd.Timestamp(t0)) & (states.index <= pd.Timestamp(resolution_date))]
    except Exception:  # noqa: BLE001
        return []
    return [str(v) for v in sub.tolist()]


# --------------------------------------------------------------------------- #
# Per-symbol events -> competing-barrier labels -> schema rows.
# --------------------------------------------------------------------------- #
def _events_for_symbol(panel_sub: pd.DataFrame, symbol: str) -> pd.DataFrame:
    sub = panel_sub.sort_values("date")
    if sub.empty:
        return pd.DataFrame(columns=["symbol", "t0"])
    sub = sub.set_index(pd.DatetimeIndex(sub["date"]))
    states = sub["state"]
    features = sub.drop(columns=["symbol", "date", "state"]).copy()
    features["symbol"] = symbol
    return extract_events(states, features, resolution_horizon=EVENT_RESOLUTION_HORIZON)


def _event_rows_for_symbol(bars: pd.DataFrame, states: pd.Series, events: pd.DataFrame, symbol: str) -> list[dict]:
    if events.empty:
        return []
    try:
        labels = competing_barrier_labels(
            bars, events, EVENT_LABEL_K_DOWN, EVENT_LABEL_K_UP, EVENT_LABEL_HORIZON_DAYS,
            vol_window=EVENT_LABEL_VOL_WINDOW,
        )
    except Exception:  # noqa: BLE001
        return []

    rows: list[dict] = []
    for _, row in labels.iterrows():
        t0 = pd.Timestamp(row["t0"])
        resolution_date = row.get("resolution_date")
        resolution_date = pd.Timestamp(resolution_date) if pd.notna(resolution_date) else t0
        rows.append({
            "symbol": symbol,
            "t0": t0.strftime("%Y-%m-%d"),
            "direction": int(row.get("direction") or 0),
            "state_path": _state_path(states, t0, resolution_date),
            "outcome": row.get("outcome") if pd.notna(row.get("outcome")) else None,
            "time_to_hit": _safe_round(row.get("time_to_hit"), 1),
            "mfe": _safe_round(row.get("mfe"), 6),
            "mae": _safe_round(row.get("mae"), 6),
        })
    return rows


# --------------------------------------------------------------------------- #
# Impact curve -- pooled across symbols. impact_response_curve is a single-
# series (per-symbol) event study; this manually pools each symbol's own
# per-lag (mean, ci, n) into one cross-symbol curve. Sample-size-weighted
# pooling, NOT a rigorous inverse-variance meta-analysis -- adequate for a
# descriptive, non-gating display panel (see the `impact_curve` caveat),
# not a substitute for the Phase-2 matched-control study.
# --------------------------------------------------------------------------- #
def _pooled_impact_curve(per_symbol_curves: list[pd.DataFrame], max_lag: int) -> dict:
    lags = list(range(1, max_lag + 1))
    mean_cum_ret: list[float | None] = []
    ci_lo: list[float | None] = []
    ci_hi: list[float | None] = []

    for lag in lags:
        weighted_sum = 0.0
        weight_total = 0
        se_terms = []
        for curve in per_symbol_curves:
            row = curve.loc[curve["lag"] == lag]
            if row.empty:
                continue
            n = int(row["n"].iloc[0])
            m = row["mean_cum_ret"].iloc[0]
            if n <= 0 or not np.isfinite(m):
                continue
            weighted_sum += m * n
            weight_total += n
            lo, hi = row["ci_lo"].iloc[0], row["ci_hi"].iloc[0]
            if n > 1 and np.isfinite(lo) and np.isfinite(hi):
                se_terms.append(((hi - lo) / (2 * 1.96)) ** 2 * n)

        if weight_total == 0:
            mean_cum_ret.append(None)
            ci_lo.append(None)
            ci_hi.append(None)
            continue

        pooled_mean = weighted_sum / weight_total
        mean_cum_ret.append(_safe_round(pooled_mean, 6))
        if se_terms and weight_total > 1:
            pooled_se = math.sqrt(sum(se_terms) / weight_total / weight_total)
            ci_lo.append(_safe_round(pooled_mean - 1.96 * pooled_se, 6))
            ci_hi.append(_safe_round(pooled_mean + 1.96 * pooled_se, 6))
        else:
            ci_lo.append(None)
            ci_hi.append(None)

    return {"lags": lags, "mean_cum_ret": mean_cum_ret, "ci_lo": ci_lo, "ci_hi": ci_hi}


# --------------------------------------------------------------------------- #
# Envelope assembly.
# --------------------------------------------------------------------------- #
def build_payload(
    symbols: list[str],
    start: str,
    end: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    timeline_sessions: int = DEFAULT_TIMELINE_SESSIONS,
    cfg: FlowStateConfig | None = None,
    study_dir: Path = OUTPUT_ROOT,
) -> tuple[dict, list[tuple[str, str]]]:
    """Returns (payload, skipped) where skipped is [(symbol, reason), ...].

    Never raises: every failure mode (empty panel, one bad symbol, a
    classifier exception) degrades to a per-symbol skip or an
    `available: false` payload, matching build_changepoints.py's discipline.
    """
    cfg = cfg or FlowStateConfig()
    empty_payload = {
        "available": False, "as_of": None, "tier": 0, "decision_authorized": False,
        "caveats": list(CAVEATS), "states": [], "timelines": {}, "events": [],
        "barrier_fields": {}, "impact_curve": {"lags": [], "mean_cum_ret": [], "ci_lo": [], "ci_hi": []},
        "phenomenon": _build_phenomenon_block(None), "gate": _gate_block(), "models": None,
        "producing_script": "tools/build_flow_state.py",
    }

    try:
        panel = build_flow_state_panel(symbols, start, end, data_root=DATA_ROOT, cfg=cfg, allow_holdout=False)
    except Exception as e:  # noqa: BLE001
        return {**empty_payload, "reason": f"build_flow_state_panel failed: {type(e).__name__}: {e}"}, []

    skipped: list[tuple[str, str]] = []
    general_warnings: list[str] = []
    panel_warnings = list(panel.attrs.get("warnings", []) or [])
    requested = set(symbols)
    for w in panel_warnings:
        # build_flow_state_panel emits two shapes: per-symbol skips
        # ("<SYMBOL>: <reason>", symbol always one of the requested symbols)
        # and general notices ("FINRA short-volume panel unavailable...",
        # "tools.data_sources unavailable...") that are not about any one
        # symbol -- only the former belongs in `skipped`.
        head = w.split(":", 1)[0].strip() if ":" in w else ""
        if head in requested:
            sym, reason = w.split(":", 1)
            skipped.append((sym.strip(), reason.strip()))
        else:
            general_warnings.append(w)

    if panel.empty:
        detail = skipped[0][1] if skipped else (general_warnings[0] if general_warnings else None)
        reason = "panel is empty" + (f" ({detail})" if detail else "")
        return {**empty_payload, "reason": reason}, skipped

    study = _load_latest_study(study_dir)
    phenomenon = _build_phenomenon_block(study)
    tier = 1 if phenomenon.get("passed") else 0

    state_rows: list[dict] = []
    timelines: dict[str, list[dict]] = {}
    event_rows: list[dict] = []
    barrier_snapshots: dict[str, dict] = {}
    impact_curves: list[pd.DataFrame] = []

    processed_symbols = sorted(panel["symbol"].unique().tolist())
    for symbol in processed_symbols:
        try:
            panel_sub = panel.loc[panel["symbol"] == symbol].sort_values("date").reset_index(drop=True)
            if panel_sub.empty:
                skipped.append((symbol, "no panel rows after filtering"))
                continue

            bars = _load_bars(symbol, start, end)
            if bars is None:
                skipped.append((symbol, "no usable raw OHLCV bars for barrier snapshot"))
                continue

            states_indexed = panel_sub.set_index(pd.DatetimeIndex(panel_sub["date"]))["state"]
            last = panel_sub.iloc[-1]

            snapshot = _barrier_snapshot(bars, cfg)

            flow_z_val = _safe_round(last.get("flow_z"), 4)
            persistence_col = f"flow_persistence_{cfg.pressure_persistence_window}d"
            persistence_val = _safe_round(last.get(persistence_col), 2)
            amihud_z_val = _safe_round(last.get("amihud_shock"), 4)
            cs_spread_val = _safe_round(last.get("corwin_schultz_spread"), 6)
            cont_score = _safe_round(last.get("continuation_score"), 4)
            cont_dir = last.get("continuation_direction")
            try:
                cont_dir_i = int(cont_dir) if cont_dir is not None and pd.notna(cont_dir) else 0
            except (TypeError, ValueError):
                cont_dir_i = 0
            impact_beta_z_val = _safe_round(last.get("impact_beta_z"), 4)
            barrier_prox = _safe_round(last.get("barrier_proximity"), 4)
            dist_barrier = _safe_round(last.get("dist_to_barrier_atr"), 4)
            impact_beta_val = _safe_round(last.get("impact_beta"), 6)

            # Prefer the evidence-backed sleeve when present; fall back to the
            # older stress composite so ranking still works on partial rows.
            composite = cont_score if cont_score is not None else (
                abs(flow_z_val or 0.0)
                + max(amihud_z_val or 0.0, 0.0)
                + 0.5 * (persistence_val or 0.0)
            )

            row = {
                "symbol": symbol,
                "current_state": str(last.get("state", "NORMAL")),
                "days_in_state": _days_in_state(panel_sub["state"]),
                "flow_z": flow_z_val,
                "persistence_5d": persistence_val,
                "amihud_z": amihud_z_val,
                "cs_spread": cs_spread_val,
                "impact_beta": impact_beta_val,
                "impact_beta_z": impact_beta_z_val,
                "continuation_score": cont_score,
                "continuation_direction": cont_dir_i,
                "barrier_proximity": barrier_prox,
                "dist_to_barrier_atr": dist_barrier,
                "air_pocket_up": _safe_round(snapshot["air_pocket_up"], 4) if snapshot else None,
                "air_pocket_down": _safe_round(snapshot["air_pocket_down"], 4) if snapshot else None,
                "next_support": _safe_round(snapshot["support_price"], 4) if snapshot else None,
                "next_resistance": _safe_round(snapshot["resistance_price"], 4) if snapshot else None,
                "_composite_stress": float(composite or 0.0),
            }
            state_rows.append(row)

            tail = panel_sub.tail(timeline_sessions)
            timelines[symbol] = [
                {"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "state": str(s)}
                for d, s in zip(tail["date"], tail["state"])
            ]

            events = _events_for_symbol(panel_sub, symbol)
            event_rows.extend(_event_rows_for_symbol(bars, states_indexed, events, symbol))

            returns = bars["close"].astype(float).pct_change()
            shock_mask = states_indexed.reindex(bars.index).fillna("NORMAL") == "SHOCK"
            try:
                from edge.research.flow_state import impact_response_curve
                curve = impact_response_curve(returns, shock_mask, max_lag=10)
                if curve["n"].sum() > 0:
                    impact_curves.append(curve)
            except Exception:  # noqa: BLE001
                pass

            if snapshot is not None:
                barrier_snapshots[symbol] = snapshot
        except Exception as e:  # noqa: BLE001
            skipped.append((symbol, f"unhandled exception: {type(e).__name__}: {e}"))
            continue

    if not state_rows:
        reason = "every symbol failed feature/state extraction" + (f" ({skipped[0][1]})" if skipped else "")
        return {**empty_payload, "reason": reason, "phenomenon": phenomenon, "tier": tier}, skipped

    # Ordinal stress_rank: 1 = most stressed, ties broken by symbol.
    state_rows.sort(key=lambda r: (-r["_composite_stress"], r["symbol"]))
    for i, row in enumerate(state_rows, start=1):
        row["stress_rank"] = i
        del row["_composite_stress"]

    top_symbols = {row["symbol"] for row in state_rows[:top_n]}
    barrier_fields = {}
    for symbol in top_symbols:
        snap = barrier_snapshots.get(symbol)
        if snap is None:
            continue
        peaks = _density_peaks(snap["grid"], snap["density"])
        barrier_fields[symbol] = {
            "grid": [_safe_round(float(v), 4) for v in snap["grid"]],
            "density": [_safe_round(float(v), 6) for v in snap["density"]],
            "price": _safe_round(snap["price"], 4),
            "nodes": peaks,
            # Today's live options-chain snapshot is not wired into this
            # offline builder (Phase 4 scope) -- always null; the dashboard
            # is expected to label it "today's chain only" if it is ever
            # populated by a future pass, per the plan's own schema example.
            "strikes_overlay": None,
        }

    timelines = {sym: tl for sym, tl in timelines.items() if sym in top_symbols}

    impact_curve = _pooled_impact_curve(impact_curves, max_lag=10) if impact_curves else {
        "lags": [], "mean_cum_ret": [], "ci_lo": [], "ci_hi": [],
    }

    # as_of: the latest date actually present across the processed panel.
    as_of_ts = pd.to_datetime(panel["date"]).max()
    as_of = as_of_ts.strftime("%Y-%m-%d") if pd.notna(as_of_ts) else None

    payload = {
        "available": True,
        "reason": None,
        "as_of": as_of,
        "tier": tier,
        "decision_authorized": False,
        "caveats": list(CAVEATS),
        "states": state_rows,
        "timelines": timelines,
        "events": event_rows,
        "barrier_fields": barrier_fields,
        "impact_curve": impact_curve,
        "phenomenon": phenomenon,
        "gate": _gate_block(),
        "models": None,
        "producing_script": "tools/build_flow_state.py",
        # Additive bookkeeping (not part of the pinned minimum schema), same
        # convention build_changepoints.py uses for n_requested/skipped.
        "n_requested": len(symbols),
        "n_processed": len(state_rows),
        "n_skipped": len(skipped),
        "skipped": [{"symbol": s, "reason": r} for s, r in skipped],
        "warnings": general_warnings,
        "all_states": list(ALL_STATES),
    }
    return payload, skipped


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", type=str, default=None, help="comma-separated symbol list (overrides --universe)")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH, help="universe JSON with a 'symbols' key")
    parser.add_argument("--start", type=str, default="2019-01-01", help="dev-window start (inclusive)")
    parser.add_argument("--end", type=str, default=None, help="dev-window end (default: day before the sealed holdout)")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of symbols processed (smoke testing)")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="symbols kept in barrier_fields/timelines, ranked by stress_rank")
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_ROOT, help="output root (default: edge/runs/flow_state)")
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = _load_universe(args.universe)
    seen: set[str] = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]
    if args.limit is not None:
        symbols = symbols[: max(0, args.limit)]
    if not symbols:
        print("no symbols to process", file=sys.stderr)
        return 1

    holdout_start_ts = pd.Timestamp(TERMINAL_HOLDOUT_START)
    end = args.end or (holdout_start_ts - pd.Timedelta(days=1)).date().isoformat()
    if pd.Timestamp(end) >= holdout_start_ts:
        print(f"--end {end} touches the sealed terminal holdout ({TERMINAL_HOLDOUT_START}); refusing", file=sys.stderr)
        return 1

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    payload, skipped = build_payload(symbols, args.start, end, top_n=args.top_n, study_dir=out_dir)
    elapsed = time.time() - t0

    as_of = payload.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dated_path = out_dir / f"{as_of}.json"
    latest_path = out_dir / "latest.json"
    body = json.dumps(_json_safe(payload), indent=2, allow_nan=False)
    dated_path.write_text(body, encoding="utf-8")
    latest_path.write_text(body, encoding="utf-8")

    print(f"processed {len(symbols)} symbols in {elapsed:.1f}s "
          f"({payload.get('n_processed', 0)} ok, {len(skipped)} skipped)")
    print(f"available     : {payload['available']}")
    if not payload["available"]:
        print(f"reason        : {payload.get('reason')}")
    print(f"as_of         : {payload.get('as_of')}")
    print(f"tier          : {payload.get('tier')}")
    print(f"n_states      : {len(payload.get('states', []))}")
    print(f"n_events      : {len(payload.get('events', []))}")
    print(f"n_barrier_flds: {len(payload.get('barrier_fields', {}))}")
    if skipped:
        print("skipped:")
        for sym, reason in skipped[:20]:
            print(f"  {sym}: {reason}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")
    print(f"\nwrote {dated_path}")
    print(f"wrote {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
