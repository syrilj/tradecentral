#!/usr/bin/env python3
"""Phase 2 flow-state study: "is this phenomenon real?" -- NO machine learning.

Pipeline: build the flow-state panel (dev-window only, sealed-holdout
guarded) -> classify states (already done inside
``build_flow_state_panel``) -> extract SHOCK/TEST events per symbol ->
PREREGISTER the experiment (grid, config, dataset fingerprint, code
version) via ``research/experiment_ledger.py`` BEFORE any matched-control
or permutation statistic is computed -> for each point of a small, frozen
preregistered grid, competing-barrier labels -> matched controls ->
event-vs-control effect size (Newey-West t + date-block bootstrap CI) ->
circular permutation null -> across the grid, effective-trial-count /
Bonferroni deflation. Writes a dated JSON artifact and a human-readable
markdown summary, and exits 0 only if the T1 gate criterion from the plan
is met on at least one grid point.

T1 gate (per plan): bootstrap CI for ``delta_terminal_return`` excludes 0
AND the deflated permutation p-value is < 0.01. A well-formed FAIL is an
expected, valid outcome, not a bug -- the plan is explicit that the
phenomenon may not survive matched controls at daily resolution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.event_labels import competing_barrier_labels, label_coverage_report  # noqa: E402
from edge.research.experiment_ledger import ExperimentLedger  # noqa: E402
from edge.research.flow_state import FlowStateConfig, extract_events  # noqa: E402
from edge.research.flow_state_panel import TERMINAL_HOLDOUT_START, build_flow_state_panel  # noqa: E402
from edge.research.hashing import stable_hash  # noqa: E402
from edge.research.matched_controls import (  # noqa: E402
    attach_regime_columns,
    deflate_grid_pvalues,
    event_vs_control_stats,
    match_controls,
    permutation_null,
)
from edge.research.provenance import load_upstream_provenance  # noqa: E402

DATA_ROOT = EDGE_ROOT / "data"
OUTPUT_ROOT = EDGE_ROOT / "runs" / "flow_state"

# Frozen preregistered grid (must match exactly what gets preregistered --
# not re-invented per run). Tuple order: (k_down, k_up, horizon_days).
GRID: tuple[tuple[float, float, int], ...] = (
    (1.5, 1.5, 10),
    (2.0, 1.0, 10),
    (1.5, 1.5, 20),
)

VOL_WINDOW = 21
N_CONTROLS = 5
SAME_SYMBOL_EXCLUSION_DAYS = 21

DEFAULT_SYMBOLS: tuple[str, ...] = (
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "JPM", "XOM", "SPY", "QQQ",
)

TERMINAL_HOLDOUT_END = "2027-01-29"


# --------------------------------------------------------------------------- #
# Small local OHLCV loader (competing_barrier_labels/attach_regime_columns
# need raw bars; build_flow_state_panel only returns derived features).
# --------------------------------------------------------------------------- #
def _load_bars(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    path = DATA_ROOT / "1d_wide" / f"{symbol}.parquet"
    if not path.exists():
        return None
    bars = pd.read_parquet(path)
    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in bars.columns]
    if missing:
        return None
    bars = bars.sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    bars = bars.loc[(bars.index >= pd.Timestamp(start)) & (bars.index <= pd.Timestamp(end))]
    return bars if len(bars) > 0 else None


def _code_version() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=EDGE_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return sha or "unknown"
    except Exception:
        return "unknown"


def _events_for_symbol(panel: pd.DataFrame, sym: str, resolution_horizon: int = 20) -> pd.DataFrame:
    sub = panel.loc[panel["symbol"] == sym].sort_values("date")
    if sub.empty:
        return pd.DataFrame(columns=["symbol", "t0"])
    sub = sub.set_index(pd.DatetimeIndex(sub["date"]))
    states = sub["state"]
    features = sub.drop(columns=["symbol", "date", "state"]).copy()
    features["symbol"] = sym
    return extract_events(states, features, resolution_horizon=resolution_horizon)


def _precompute_all_labels(
    bars_by_symbol: dict[str, pd.DataFrame], k_down: float, k_up: float, horizon_days: int,
) -> pd.DataFrame:
    """Run ``competing_barrier_labels`` ONCE per symbol against EVERY bar in
    that symbol's history, for one grid point, instead of re-running it on a
    small events subset inside every permutation.

    Safe because ``competing_barrier_labels``'s output for a given ``t0`` is
    a pure function of that symbol's ``bars`` around ``t0`` (``P0``,
    ``sigma_t0``, the forward high/low barrier scan) -- it never inspects
    which OTHER rows share the ``events`` table it's called with (see the
    module's own docstring and ``tests/research/test_flow_state_no_lookahead.py``,
    which proves the per-row result is unaffected by anything outside that
    row's own trailing/forward window). So labeling every date up front and
    then selecting a subset (``_lookup_labels``) is provably identical, row
    for row, to calling ``competing_barrier_labels`` on that subset
    directly -- it just replaces up to ~200 redundant per-permutation
    barrier-scans (each re-walking every symbol) with exactly one.
    """
    frames = []
    for sym, bars in bars_by_symbol.items():
        if bars.empty:
            continue
        all_dates_events = pd.DataFrame({"symbol": sym, "t0": bars.index})
        frames.append(competing_barrier_labels(bars, all_dates_events, k_down, k_up, horizon_days, vol_window=VOL_WINDOW))
    if not frames:
        return pd.DataFrame(columns=["symbol", "t0", "outcome", "terminal_return"])
    full = pd.concat(frames, axis=0, ignore_index=True)
    full["_date_key"] = pd.to_datetime(full["t0"]).dt.normalize()
    return full


def _lookup_labels(
    events: pd.DataFrame, precomputed: pd.DataFrame, known_symbols: set[str],
) -> pd.DataFrame:
    """Fast replacement for the old ``_label_events_by_symbol``: a merge
    against ``_precompute_all_labels``'s output instead of re-running the
    barrier scan. Preserves that function's exact behavior -- events whose
    symbol has no bars at all are silently dropped (matching the old
    ``if bars is None: continue``), while an event whose symbol IS known but
    whose exact date is missing from the precomputed table raises (matching
    ``competing_barrier_labels``'s own raise-on-unmatched-``t0``), rather
    than being silently dropped by the merge.
    """
    if events.empty or precomputed.empty:
        return pd.DataFrame(columns=["symbol", "t0", "outcome", "terminal_return"])
    ev = events.loc[events["symbol"].isin(known_symbols)].copy()
    if ev.empty:
        return pd.DataFrame(columns=["symbol", "t0", "outcome", "terminal_return"])
    ev["_date_key"] = pd.to_datetime(ev["t0"]).dt.normalize()
    merged = ev.merge(
        precomputed.drop(columns=["t0"]), on=["symbol", "_date_key"], how="left", indicator=True,
    )
    missing = merged["_merge"] == "left_only"
    if missing.any():
        bad = merged.loc[missing].iloc[0]
        raise KeyError(
            f"event t0={pd.Timestamp(bad['_date_key']).date()} symbol={bad['symbol']!r} not found in "
            "precomputed labels -- events must be derived from (or aligned to) the same bars supplied here"
        )
    return merged.drop(columns=["_merge", "_date_key"])


def _paired_diff_series(event_labels: pd.DataFrame, control_labels: pd.DataFrame) -> tuple[list[float], list[Any]]:
    """Recompute the same per-event paired-difference series
    ``event_vs_control_stats`` uses internally (it does not expose the raw
    series, only aggregate statistics) -- needed here for
    ``deflate_grid_pvalues``'s cross-grid correlation structure."""
    if event_labels.empty or control_labels.empty:
        return [], []
    events = event_labels.copy()
    controls = control_labels.copy()
    control_group = controls.groupby(["event_symbol", "event_t0"]).agg(
        control_terminal_return=("terminal_return", "mean"),
    ).reset_index()
    merged = events.merge(
        control_group, left_on=["symbol", "t0"], right_on=["event_symbol", "event_t0"], how="inner",
    )
    paired = merged.dropna(subset=["terminal_return", "control_terminal_return"])
    if paired.empty:
        return [], []
    diffs = (paired["terminal_return"] - paired["control_terminal_return"]).tolist()
    dates = paired["t0"].tolist()
    return diffs, dates


def _make_stat_fn(panel: pd.DataFrame, precomputed_labels: pd.DataFrame, known_symbols: set[str], seed: int):
    """Build the closure ``permutation_null`` calls once per permutation.

    ``precomputed_labels`` (from ``_precompute_all_labels``, one call per
    grid point, BEFORE ``permutation_null`` starts) makes each permutation's
    cost O(n_events) merge-based lookups plus one ``match_controls`` call --
    not a full barrier-scan re-walk of every symbol -- since the labels for
    a given (symbol, date) never depend on which dates happen to be flagged
    as events.
    """
    def stat_fn(perm_events: pd.DataFrame) -> float:
        if perm_events.empty:
            return 0.0
        labels = _lookup_labels(perm_events, precomputed_labels, known_symbols)
        if labels.empty:
            return 0.0
        controls = match_controls(
            perm_events, panel, n_controls=N_CONTROLS,
            same_symbol_exclusion_days=SAME_SYMBOL_EXCLUSION_DAYS, seed=seed,
        )
        if controls.empty:
            return 0.0
        control_events = controls.rename(columns={"control_symbol": "symbol", "control_t0": "t0"})
        control_labels = _lookup_labels(control_events, precomputed_labels, known_symbols)
        if control_labels.empty:
            return 0.0
        # event_symbol/event_t0 survive the _lookup_labels merge unchanged
        # (precomputed's label columns are added on, nothing about the
        # caller's own columns is touched) -- so they do NOT need (and must
        # NOT get) a positional reassignment here, which would silently
        # misalign once the merge reorders rows.
        stats = event_vs_control_stats(labels, control_labels)
        value = stats["delta_terminal_return"]
        return float(value) if np.isfinite(value) else 0.0
    return stat_fn


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars to plain JSON values and
    replace non-finite floats with ``None`` (NaN/Inf are expected here --
    e.g. an unresolved delta_terminal_return -- and must round-trip as an
    explicit missing value, not crash ``json.dumps(allow_nan=False)`` or
    silently serialize as the non-standard literal ``NaN``)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if np.isfinite(v) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _bootstrap_excludes_zero(bootstrap_ci: dict | None) -> bool:
    if bootstrap_ci is None:
        return False
    lower, upper = bootstrap_ci["lower"], bootstrap_ci["upper"]
    return (lower > 0.0) or (upper < 0.0)


def _write_markdown(path: Path, *, as_of: str, symbols: list[str], start: str, end: str,
                     experiment_id: str, deflation: dict, grid_results: list[dict], overall_pass: bool) -> None:
    lines = [
        f"# Flow-State Phase 2 Study -- {as_of}",
        "",
        f"Symbols: {', '.join(symbols)}  ",
        f"Window: {start} .. {end}  ",
        f"Preregistration id: `{experiment_id}`  ",
        f"Effective trial count (grid deflation): {deflation['effective_trial_count']:.3f} of {deflation['raw_trial_count']} raw  ",
        "",
        "| k_down | k_up | horizon_days | n_events | n_controls | n_paired | delta_terminal_return | newey_west_t | bootstrap CI | raw perm p | deflated p | T1 pass |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in grid_results:
        cfg = entry["config"]
        stats = entry["stats"]
        perm = entry["permutation"]
        deflated_p = entry["deflated_p_value"]
        ci = stats["bootstrap_ci"]
        ci_str = f"[{ci['lower']:.5f}, {ci['upper']:.5f}]" if ci else "n/a"
        lines.append(
            f"| {cfg['k_down']} | {cfg['k_up']} | {cfg['horizon_days']} | {stats['n_events']} | "
            f"{stats['n_controls']} | {stats['n_paired']} | {stats['delta_terminal_return']:.6f} | "
            f"{stats['newey_west_t']:.3f} | {ci_str} | {perm['p_value']:.4f} | {deflated_p:.4f} | "
            f"{'YES' if entry['t1_pass'] else 'no'} |"
        )
    lines += [
        "",
        f"## Overall T1 gate: {'PASS' if overall_pass else 'FAIL'}",
        "",
        "T1 criterion (per plan): bootstrap CI for delta_terminal_return excludes 0 AND "
        "deflated permutation p < 0.01, on at least one grid point. A FAIL is a valid, "
        "designed-for outcome -- the phenomenon may not survive matched controls at daily "
        "resolution; the tab still ships as a descriptive T0 state monitor either way.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", type=str, default=None, help="comma-separated symbols (default: a small liquid list)")
    parser.add_argument("--start", type=str, default="2019-01-01", help="dev-window start (inclusive)")
    parser.add_argument("--end", type=str, default=None, help="dev-window end (default: day before the sealed holdout)")
    parser.add_argument("--allow-holdout", action="store_true", help="matches build_flow_state_panel's escape hatch -- do not use casually")
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_ROOT, help="output directory")
    parser.add_argument("--n-perm", type=int, default=200, help="permutations per grid point (spec default is 2000; lowered here for tractable runtime -- override for the real run)")
    parser.add_argument("--seed", type=int, default=0, help="seed for match_controls/permutation_null")
    args = parser.parse_args(argv)

    symbols = sorted(s.strip() for s in args.symbols.split(",") if s.strip()) if args.symbols else sorted(DEFAULT_SYMBOLS)
    holdout_start_ts = pd.Timestamp(TERMINAL_HOLDOUT_START)
    end = args.end or (holdout_start_ts - pd.Timedelta(days=1)).date().isoformat()
    start = args.start
    if not args.allow_holdout and pd.Timestamp(end) >= holdout_start_ts:
        raise ValueError(f"--end {end} touches the sealed terminal holdout ({TERMINAL_HOLDOUT_START}); pass --allow-holdout only for an explicit authorized evaluation")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build_flow_state_study] building panel for {len(symbols)} symbols, {start}..{end}")
    panel = build_flow_state_panel(symbols, start, end, allow_holdout=args.allow_holdout)
    if panel.attrs.get("warnings"):
        for w in panel.attrs["warnings"]:
            print(f"[build_flow_state_study] warning: {w}")
    if panel.empty:
        print("[build_flow_state_study] FAIL: panel is empty, nothing to study")
        return 1

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        bars = _load_bars(sym, start, end)
        if bars is not None:
            bars_by_symbol[sym] = bars
    panel = panel.loc[panel["symbol"].isin(bars_by_symbol)].reset_index(drop=True)

    feature_cols = sorted(c for c in panel.columns if c not in ("symbol", "date", "state"))

    # --- Preregister BEFORE computing any statistic -------------------------
    total_days = max((pd.Timestamp(end) - pd.Timestamp(start)).days, 2)
    validation_start_ts = pd.Timestamp(start) + pd.Timedelta(days=int(total_days * 0.8))
    train_end_ts = validation_start_ts - pd.Timedelta(days=1)

    dataset_fp = stable_hash(
        {"symbols": symbols, "start": start, "end": end, "grid": [list(g) for g in GRID]},
        namespace="edge-flow-state-study-dataset-v1",
    )
    code_version = _code_version()
    config = {
        "grid": [{"k_down": kd, "k_up": ku, "horizon_days": h} for kd, ku, h in GRID],
        "n_controls": N_CONTROLS,
        "same_symbol_exclusion_days": SAME_SYMBOL_EXCLUSION_DAYS,
        "vol_window": VOL_WINDOW,
        "n_perm": args.n_perm,
        "seed": args.seed,
        "symbols": symbols,
        "flow_state_config": asdict(FlowStateConfig()),
    }
    ledger = ExperimentLedger(out_dir / "experiment_ledger.jsonl")
    experiment = ledger.preregister_experiment(
        features=feature_cols,
        model="flow_state_competing_barrier_matched_control_v1",
        config=config,
        upstream_provenance=load_upstream_provenance(),
        dataset_fingerprint=dataset_fp,
        boundaries={
            "train": {"start": start, "end": train_end_ts.date().isoformat()},
            "validation": {"start": validation_start_ts.date().isoformat(), "end": end},
            "terminal_holdout": {"start": TERMINAL_HOLDOUT_START, "end": TERMINAL_HOLDOUT_END},
        },
        code_version=code_version,
    )
    print(f"[build_flow_state_study] preregistered experiment {experiment.record_id}")

    # --- Now compute statistics ---------------------------------------------
    panel = attach_regime_columns(panel, bars_by_symbol)

    all_events = pd.concat(
        [_events_for_symbol(panel, sym) for sym in bars_by_symbol], axis=0, ignore_index=True,
    ) if bars_by_symbol else pd.DataFrame(columns=["symbol", "t0"])
    print(f"[build_flow_state_study] extracted {len(all_events)} SHOCK/TEST events across {len(bars_by_symbol)} symbols")

    grid_results: list[dict] = []
    for k_down, k_up, horizon_days in GRID:
        cfg_label = {"k_down": k_down, "k_up": k_up, "horizon_days": horizon_days}
        print(f"[build_flow_state_study] grid point {cfg_label}")
        if all_events.empty:
            grid_results.append({
                "config": cfg_label,
                "coverage": {"n_events": 0, "class_balance": {}, "ambiguity_rate": 0.0, "censoring_rate": 0.0},
                "stats": {"delta_terminal_return": float("nan"), "delta_p_down_first": float("nan"),
                          "newey_west_t": float("nan"), "bootstrap_ci": None, "n_events": 0, "n_controls": 0, "n_paired": 0},
                "permutation": {"p_value": float("nan"), "null_mean": float("nan"), "null_std": float("nan"), "observed": float("nan"), "n_perm": 0},
                "paired_diff_series": [], "paired_dates": [], "t1_pass": False, "deflated_p_value": float("nan"),
            })
            continue

        # Precompute this grid point's barrier labels ONCE, for every
        # (symbol, date) in the panel -- not just the real events -- so that
        # both the "observed" labeling below AND every one of
        # `permutation_null`'s up-to-`n_perm` calls into `stat_fn` become a
        # fast merge-based lookup (`_lookup_labels`) instead of a full
        # per-permutation re-walk of `competing_barrier_labels` across all
        # 557 symbols. See `_precompute_all_labels`'s docstring for why this
        # is provably identical to the old per-call recomputation.
        known_symbols = set(bars_by_symbol.keys())
        precomputed_labels = _precompute_all_labels(bars_by_symbol, k_down, k_up, horizon_days)

        event_labels = _lookup_labels(all_events, precomputed_labels, known_symbols)
        coverage = label_coverage_report(event_labels)

        controls = match_controls(
            all_events, panel, n_controls=N_CONTROLS,
            same_symbol_exclusion_days=SAME_SYMBOL_EXCLUSION_DAYS, seed=args.seed,
        )
        control_events = controls.rename(columns={"control_symbol": "symbol", "control_t0": "t0"})
        # event_symbol/event_t0 pass through _lookup_labels unchanged (see
        # the identical note in _make_stat_fn) -- no positional
        # reassignment needed or safe here.
        control_labels = _lookup_labels(control_events, precomputed_labels, known_symbols)

        stats = event_vs_control_stats(event_labels, control_labels) if not control_labels.empty else {
            "delta_terminal_return": float("nan"), "delta_p_down_first": float("nan"),
            "newey_west_t": float("nan"), "bootstrap_ci": None,
            "n_events": int(len(event_labels)), "n_controls": int(len(control_labels)), "n_paired": 0,
        }

        stat_fn = _make_stat_fn(panel, precomputed_labels, known_symbols, args.seed)
        perm = permutation_null(all_events, panel, stat_fn, n_perm=args.n_perm, seed=args.seed)

        diffs, dates = _paired_diff_series(event_labels, control_labels)

        grid_results.append({
            "config": cfg_label,
            "coverage": coverage,
            "stats": stats,
            "permutation": perm,
            "paired_diff_series": diffs,
            "paired_dates": [pd.Timestamp(d).isoformat() for d in dates],
        })

    # --- Grid-search multiplicity deflation ---------------------------------
    deflation_input = [
        {"config": g["config"], "p_value": g["permutation"]["p_value"],
         "paired_diff_series": g["paired_diff_series"], "paired_dates": g["paired_dates"]}
        for g in grid_results
    ]
    deflation = deflate_grid_pvalues(deflation_input)
    for entry, deflated in zip(grid_results, deflation["per_grid"]):
        entry["deflated_p_value"] = deflated["deflated_p_value"]
        entry["deflated_sharpe"] = deflated["deflated_sharpe"]
        entry["t1_pass"] = bool(
            _bootstrap_excludes_zero(entry["stats"]["bootstrap_ci"])
            and np.isfinite(entry["deflated_p_value"])
            and entry["deflated_p_value"] < 0.01
        )

    overall_pass = any(g["t1_pass"] for g in grid_results)

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "producing_script": "tools/build_flow_state_study.py",
        "as_of": as_of,
        "symbols": symbols,
        "start": start,
        "end": end,
        "experiment_id": experiment.record_id,
        "dataset_fingerprint": dataset_fp,
        "code_version": code_version,
        "n_events_total": int(len(all_events)),
        "grid": [{"k_down": kd, "k_up": ku, "horizon_days": h} for kd, ku, h in GRID],
        "effective_trial_count": deflation["effective_trial_count"],
        "raw_trial_count": deflation["raw_trial_count"],
        "grid_results": grid_results,
        "t1_pass": overall_pass,
    }
    json_path = out_dir / f"study_{as_of}.json"
    json_path.write_text(json.dumps(_json_safe(payload), indent=2, default=str, allow_nan=False), encoding="utf-8")

    md_path = out_dir / f"study_{as_of}.md"
    _write_markdown(
        md_path, as_of=as_of, symbols=symbols, start=start, end=end,
        experiment_id=experiment.record_id, deflation=deflation, grid_results=grid_results, overall_pass=overall_pass,
    )

    print(f"[build_flow_state_study] wrote {json_path}")
    print(f"[build_flow_state_study] wrote {md_path}")
    print(f"[build_flow_state_study] T1 gate: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
