#!/usr/bin/env python3
"""xs5_pit_optimizer.py — GATE_XS5 runner: cost-aware execution on the PIT universe.

Pre-registered spec (edge/docs/GATE_XS5.md, frozen 2026-08-16):
  - universe: pit30 dated-interval instruments file, authoritative
  - signal:   mom12_1 = close.shift(21) / close.shift(126) - 1
  - rebalance: weekly (every 5 trading days)
  - weights:  cost-aware optimizer (L1 trade-cost penalty inside the objective)
  - vol targeting: target 10%, max leverage 2.0, 20-day realized window
  - accounting: edge.research.portfolio.simulate_long_short, execution_lag=1
  - costs: 10bp per side, charged per bar of realized turnover

The runner never loads a bar after 2026-07-29 (asserted, not conventional).
Development is evaluated as expanding purged/embargoed walk-forward folds on the
trading-date axis; the strategy is a fixed spec with no fitting, so each fold's
validation dates are sliced out as out-of-sample daily net returns.

Usage:
  edge/.venv-qlib/bin/python edge/tools/xs5_pit_optimizer.py
  edge/.venv-qlib/bin/python edge/tools/xs5_pit_optimizer.py --smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from edge.research.daily_data import load_daily_universe  # noqa: E402
from edge.research.optimizer import OptimizerConfig, optimize_panel  # noqa: E402
from edge.research.portfolio import simulate_long_short  # noqa: E402
from edge.research.splits import expanding_walk_forward_splits  # noqa: E402
from edge.research.statistics import (  # noqa: E402
    bonferroni_deflated_sharpe_approximation,
    date_block_bootstrap_ci,
)
from edge.research.vol_targeting import apply_vol_target  # noqa: E402

EDGE = ROOT / "edge"
OUT_DIR = EDGE / "runs" / "xs5"
PIT_INSTRUMENTS = EDGE / "data" / "qlib_us_1d" / "instruments" / "pit30.txt"
DATA_DIR = EDGE / "data" / "1d"

# Frozen by GATE_XS5.md. Changing any of these changes the gate.
DEV_END = pd.Timestamp("2026-07-29")
HOLDOUT_START = pd.Timestamp("2026-07-30")
REBALANCE_EVERY = 5
COST_PER_SIDE = 0.0010
EXECUTION_LAG = 1
MAX_ABS_DAILY_RETURN = 0.50
TRIAL_COUNT = 4
SIGNALS = ("mom12_1", "mom21", "rev5")
PRIMARY_SIGNAL = "mom12_1"
MIN_NAMES = 10
FOLD_LABEL_HORIZON = 1
FOLD_EMBARGO = 5
FOLD_INITIAL_TRAIN = 504
FOLD_VALIDATION = 126
FOLD_STEP = 126
FOLD_MIN_PARTIAL = 60
OPTIMIZER_CONFIG = OptimizerConfig(
    risk_aversion=1.0,
    turnover_penalty=1.0,
    cost_per_side=COST_PER_SIDE,
    max_weight=0.05,
    leverage=1.0,
    dollar_neutral=True,
)
VOL_TARGET_KW = dict(target_vol=0.10, max_leverage=2.0, window=20, method="realized")


def load_pit_panel() -> pd.DataFrame:
    """Load the pit30 universe with authoritative PIT membership filtering."""
    symbols = sorted(
        {line.split("\t")[0] for line in PIT_INSTRUMENTS.read_text(encoding="utf-8").splitlines() if line.strip()}
    )
    panel = load_daily_universe(
        symbols,
        asof=DEV_END,
        data_dir=DATA_DIR,
        pit_instruments=PIT_INSTRUMENTS,
        pit_required=True,
    )
    assert panel.index.get_level_values("timestamp").max() <= DEV_END, (
        "GATE_XS5 rule 3: the runner may not read any date after 2026-07-29"
    )
    return panel


def build_signal(panel: pd.DataFrame, signal: str) -> pd.DataFrame:
    """Per-symbol backward-looking signal, wide (date x symbol)."""
    close = panel["close"].unstack("symbol").sort_index()
    if signal == "mom12_1":
        values = close.shift(21) / close.shift(126) - 1.0
    elif signal == "mom21":
        values = close.pct_change(21)
    elif signal == "rev5":
        values = -close.pct_change(5)
    else:
        raise ValueError(f"unknown signal: {signal}")
    return values


def decile_weights(signal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Frozen baseline: long top decile / short bottom decile, dollar-neutral.

    Rebalanced weekly (same cadence as the primary spec) so the only difference
    between baseline and primary is the weight-formation mechanism.
    """
    wide = signal.copy()
    long_w = pd.DataFrame(0.0, index=wide.index, columns=wide.columns)
    short_w = pd.DataFrame(0.0, index=wide.index, columns=wide.columns)
    for i in range(0, len(wide), REBALANCE_EVERY):
        row = wide.iloc[i]
        valid = row.dropna()
        if len(valid) < MIN_NAMES:
            continue
        pct = valid.rank(pct=True)
        top = pct[pct >= 0.9].index
        bottom = pct[pct <= 0.1].index
        if len(top):
            long_w.iloc[i, long_w.columns.get_indexer(top)] = 1.0 / len(top)
        if len(bottom):
            short_w.iloc[i, short_w.columns.get_indexer(bottom)] = 1.0 / len(bottom)
    return long_w, short_w


def run_spec(
    panel: pd.DataFrame,
    signal_name: str,
    *,
    use_optimizer: bool,
    use_vol_target: bool,
) -> pd.DataFrame:
    """Return the daily net-return series for one frozen spec."""
    signal = build_signal(panel, signal_name)
    close = panel["close"].unstack("symbol").sort_index()
    common = signal.index.intersection(close.index)
    signal, close = signal.loc[common], close.loc[common]

    if use_optimizer:
        long_w, short_w = optimize_panel(
            alpha=signal,
            close=close,
            config=OPTIMIZER_CONFIG,
            covariance_window=120,
            rebalance_every=REBALANCE_EVERY,
        )
    else:
        long_w, short_w = decile_weights(signal)

    if use_vol_target:
        long_w, short_w = apply_vol_target(
            long_weights=long_w,
            short_weights=short_w,
            close=close,
            execution_lag=EXECUTION_LAG,
            **VOL_TARGET_KW,
        )

    sim = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close,
        execution_lag=EXECUTION_LAG,
        cost_per_side=COST_PER_SIDE,
        max_abs_daily_return=MAX_ABS_DAILY_RETURN,
    )
    return sim.net_returns


def oof_daily_returns(
    daily: pd.Series,
    *,
    initial_train: int = FOLD_INITIAL_TRAIN,
    validation: int = FOLD_VALIDATION,
    step: int = FOLD_STEP,
    min_partial: int = FOLD_MIN_PARTIAL,
) -> pd.Series:
    """Slice the walk-forward validation dates out of a full daily series.

    The fold parameters default to the frozen GATE_XS5 values; smoke mode
    passes smaller ones so a truncated panel still produces folds. Smoke
    results are diagnostic only and never a gate verdict.
    """
    dates = pd.DatetimeIndex(daily.index).normalize()
    folds = list(expanding_walk_forward_splits(
        len(dates),
        label_horizon=FOLD_LABEL_HORIZON,
        initial_train_size=initial_train,
        validation_size=validation,
        step=step,
        embargo=FOLD_EMBARGO,
        include_partial_final=True,
        min_partial_validation_size=min_partial,
    ))
    oof_index = np.concatenate([fold.validation_indices for fold in folds])
    return daily.iloc[np.unique(oof_index)]


def metrics_for(daily: pd.Series, *, trial_count: int) -> dict:
    """Date-block bootstrap expectancy, deflated Sharpe, drawdown, turnover proxy."""
    values = daily.to_numpy(dtype=float)
    dates = pd.DatetimeIndex(daily.index).normalize()
    ci = date_block_bootstrap_ci(values, dates, confidence=0.95, block_size=5,
                                 n_bootstrap=2_000, seed=0)
    dsr = bonferroni_deflated_sharpe_approximation(values, trial_count=trial_count)
    equity = pd.Series(1.0 + values).cumprod()
    drawdown = float((equity / equity.cummax() - 1.0).min())
    return {
        "n_days": int(len(values)),
        "net_expectancy": float(ci.estimate),
        "net_expectancy_ci95_lower": float(ci.lower),
        "net_expectancy_ci95_upper": float(ci.upper),
        "observed_sharpe": float(dsr.observed_sharpe),
        "deflated_sharpe_lower": float(dsr.lower_bound_sharpe),
        "max_drawdown": drawdown,
    }


def paired_difference(candidate: pd.Series, baseline: pd.Series) -> dict:
    joined = pd.concat([candidate.rename("candidate"), baseline.rename("baseline")],
                       axis=1).dropna()
    difference = joined["candidate"] - joined["baseline"]
    dates = pd.DatetimeIndex(joined.index).normalize()
    ci = date_block_bootstrap_ci(difference.to_numpy(dtype=float), dates,
                                 confidence=0.95, block_size=5,
                                 n_bootstrap=2_000, seed=0)
    return {
        "paired_days": int(len(joined)),
        "difference_expectancy": float(ci.estimate),
        "difference_ci95_lower": float(ci.lower),
        "difference_ci95_upper": float(ci.upper),
    }


def turnover_estimate(long_w: pd.DataFrame, short_w: pd.DataFrame) -> float:
    """Annualized one-way turnover of the held book (same definition as the gate)."""
    held_long = long_w.shift(EXECUTION_LAG).fillna(0.0)
    held_short = short_w.shift(EXECUTION_LAG).fillna(0.0)
    per_bar = held_long.diff().abs().to_numpy().sum(axis=1) + held_short.diff().abs().to_numpy().sum(axis=1)
    per_bar[0] = held_long.iloc[0].abs().to_numpy().sum() + held_short.iloc[0].abs().to_numpy().sum()
    return float(per_bar.mean() * 252.0)


def run(smoke: bool = False) -> dict:
    panel = load_pit_panel()
    print(f"pit30 panel: {panel.index.get_level_values('symbol').nunique()} symbols, "
          f"{panel.index.get_level_values('timestamp').nunique()} dates "
          f"({panel.index.get_level_values('timestamp').min().date()} -> "
          f"{panel.index.get_level_values('timestamp').max().date()})")

    if smoke:
        # Smoke mode: truncate to the last ~2 years and shrink the fold
        # geometry so the run finishes fast. Diagnostic only -- smoke results
        # are never a gate verdict.
        cutoff = panel.index.get_level_values("timestamp").max() - pd.Timedelta(days=730)
        panel = panel.loc[panel.index.get_level_values("timestamp") >= cutoff]
        fold_kw = dict(initial_train=252, validation=63, step=63, min_partial=30)
    else:
        fold_kw = {}

    trials: dict[str, dict] = {}
    primary_daily = None
    baseline_daily = None
    for signal_name in SIGNALS:
        for use_optimizer, use_vol_target, tag in (
            (True, True, "opt_vol"),
            (False, False, "decile"),
        ):
            key = f"{signal_name}_{tag}"
            daily = run_spec(panel, signal_name, use_optimizer=use_optimizer,
                             use_vol_target=use_vol_target)
            oof = oof_daily_returns(daily, **fold_kw)
            trials[key] = metrics_for(oof, trial_count=TRIAL_COUNT)
            if signal_name == PRIMARY_SIGNAL and tag == "opt_vol":
                primary_daily = oof
            if signal_name == PRIMARY_SIGNAL and tag == "decile":
                baseline_daily = oof
            print(f"  {key}: n={trials[key]['n_days']} "
                  f"net={trials[key]['net_expectancy']:+.5f} "
                  f"CI95_low={trials[key]['net_expectancy_ci95_lower']:+.5f} "
                  f"DSR_low={trials[key]['deflated_sharpe_lower']:+.3f}")

    primary = trials[f"{PRIMARY_SIGNAL}_opt_vol"]
    baseline = trials[f"{PRIMARY_SIGNAL}_decile"]
    paired = paired_difference(primary_daily, baseline_daily)

    # Turnover of the primary spec's held book.
    signal = build_signal(panel, PRIMARY_SIGNAL)
    close = panel["close"].unstack("symbol").sort_index()
    common = signal.index.intersection(close.index)
    long_w, short_w = optimize_panel(
        alpha=signal.loc[common], close=close.loc[common],
        config=OPTIMIZER_CONFIG, covariance_window=120,
        rebalance_every=REBALANCE_EVERY,
    )
    long_w, short_w = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=close.loc[common],
        execution_lag=EXECUTION_LAG, **VOL_TARGET_KW,
    )
    turnover = turnover_estimate(long_w, short_w)

    checks = {
        "net_expectancy_ci95_lower_positive": primary["net_expectancy_ci95_lower"] > 0.0,
        "deflated_sharpe_lower_positive": primary["deflated_sharpe_lower"] > 0.0,
        "paired_difference_ci95_lower_positive": paired["difference_ci95_lower"] > 0.0,
        "turnover_within_limit": turnover <= 400.0,
    }
    verdict = "PASS_DEVELOPMENT" if all(checks.values()) else "FAIL_DEVELOPMENT"

    result = {
        "schema_version": "edge-xs5-result-v1",
        "gate": "edge/docs/GATE_XS5.md",
        "verdict": verdict,
        "checks": checks,
        "primary": primary,
        "baseline": baseline,
        "paired_difference": paired,
        "annualized_one_way_turnover": turnover,
        "trials": trials,
        "trial_count": TRIAL_COUNT,
        "holdout": {
            "start": str(HOLDOUT_START.date()),
            "status": "SEALED_UNEVALUATED",
            "minimum_sessions": 120,
        },
        "live_capital_authorized": False,
        "broker_connectivity_authorized": False,
        "shadow_collection_authorized": False,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nverdict: {verdict}")
    print(f"checks: {json.dumps(checks, indent=2)}")
    print(f"written to {OUT_DIR / 'results.json'}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GATE_XS5 runner")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    run(smoke=args.smoke)
    return 0


if __name__ == "__main__":
    sys.exit(main())
