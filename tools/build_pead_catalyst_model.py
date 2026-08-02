#!/usr/bin/env python3
"""Build and Evaluate Post-Earnings Announcement Drift & Catalyst Gap Model (PEAD).

Honest Re-Validation Engine with Purged & Embargoed Cross-Validation:
  - Multi-sector wide universe (557 liquid US equities in edge/data/1d_wide/).
  - Feature set: gap_std, vol_surge, and short_pressure (FINRA short ratio).
  - Leakage control: Purged & embargoed 5-fold CV via edge.research.splits.
  - Evaluation metrics: Rank IC, Rank ICIR, Net Return (cost=10bp/side), Sharpe, Max Drawdown.
  - Calibration: IsotonicRegression / Platt scaling on OOF scores.
  - Pre-registered gate check (GATE_PEAD.md) and GATE_PEAD_RESULT.md generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "edge" / "runs" / "pead_catalyst"
COST_PER_SIDE = 0.0010  # 10bp per side (20bp round-trip)

from edge.research.portfolio import cross_sectional_rank_ic, simulate_long_short
from edge.research.reporting import Figure, GateReportSpec, write_gate_doc
from edge.research.splits import purged_embargoed_kfold_splits
from edge.tools.data_sources import load_finra_short_vol

# `vol_surge` needs bar i's full-day volume, so the score is not knowable until
# bar i's close. One bar is therefore the earliest honest execution.
EXECUTION_LAG = 1


def load_wide_universe_ohlcv() -> dict[str, pd.DataFrame]:
    data_wide_dir = ROOT / "edge" / "data" / "1d_wide"
    data_1d_dir = ROOT / "edge" / "data" / "1d"
    target_dir = data_wide_dir if data_wide_dir.exists() and len(list(data_wide_dir.glob("*.parquet"))) >= 10 else data_1d_dir

    print(f"Loading daily OHLCV from {target_dir}...")
    data = {}
    if target_dir.exists():
        for p in target_dir.glob("*.parquet"):
            sym = p.stem.upper()
            try:
                df = pd.read_parquet(p)
                df.columns = [c.capitalize() for c in df.columns]
                needed = {"Open", "High", "Low", "Close", "Volume"}
                if needed.issubset(df.columns):
                    df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
                    if len(df) >= 60:
                        data[sym] = df
            except Exception:
                pass
    print(f"Loaded {len(data)} symbol histories.")
    return data


def compute_pead_features(
    data: dict[str, pd.DataFrame],
    finra_short_ratio: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Computing PEAD catalyst gap signals (gap_std, vol_surge, short_pressure)...")
    pead_scores = {}
    fwd_returns = {}

    for sym, df in data.items():
        open_p = df["Open"]
        close_p = df["Close"]
        prev_close = close_p.shift(1)
        high_p = df["High"]
        low_p = df["Low"]
        vol = df["Volume"]

        # True Range & 20d ATR
        tr = np.maximum(high_p - low_p, np.maximum(abs(high_p - prev_close), abs(low_p - prev_close)))
        atr_20d = tr.rolling(20).mean()
        atr_pct = (atr_20d / prev_close).replace(0, np.nan)

        # Overnight Gap in ATR units
        gap_pct = (open_p - prev_close) / prev_close
        gap_std = gap_pct / atr_pct

        # Volume Surge Ratio
        vol_20d_sma = vol.rolling(20).mean().replace(0, np.nan)
        vol_surge = vol / vol_20d_sma

        # Short pressure (FINRA short ratio)
        if finra_short_ratio is not None and sym in finra_short_ratio.index.get_level_values("symbol"):
            try:
                finra_sym = finra_short_ratio.xs(sym, level="symbol").reindex(df.index).ffill().fillna(0.5)
            except Exception:
                finra_sym = pd.Series(0.5, index=df.index)
        else:
            finra_sym = pd.Series(0.5, index=df.index)

        # Combined PEAD catalyst score (weighted by short pressure)
        short_mult = 1.0 + (finra_sym - 0.5)
        score = gap_std * np.log1p(np.maximum(0, vol_surge)) * short_mult

        # 5-day forward return
        fwd_ret_5d = close_p.pct_change(5).shift(-5)

        pead_scores[sym] = score
        fwd_returns[sym] = fwd_ret_5d

    df_signal = pd.DataFrame(pead_scores).sort_index()
    df_fwd = pd.DataFrame(fwd_returns).sort_index()
    return df_signal, df_fwd


def run_honest_pead_validation(
    df_signal: pd.DataFrame,
    df_fwd: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    holding_days: int = 5,
    n_splits: int = 5,
    short_pressure_active: bool = False,
) -> dict[str, Any]:
    dates = df_signal.index
    n_dates = len(dates)

    if n_dates < 100:
        raise ValueError(f"Insufficient dates for cross validation: {n_dates}")

    # Purged & Embargoed Cross-Validation
    splits = list(
        purged_embargoed_kfold_splits(
            n_samples=n_dates,
            label_horizon=holding_days,
            n_splits=n_splits,
            embargo=holding_days,
        )
    )

    oof_rows = sorted(
        i for fold in splits for i in fold.validation if i < n_dates - holding_days
    )
    oof_sig = df_signal.iloc[oof_rows]
    oof_fwd = df_fwd.iloc[oof_rows]

    # Labels are 5-bar and sampled every bar, so IC observations overlap.
    ppy = 252.0 / holding_days

    # Headline IC is now the UNCONDITIONAL cross-section. The previous headline
    # restricted each bar to |signal| > 1.5 — a self-selected subset of extreme
    # gappers — which reported +0.0396 where the full cross-section gives
    # -0.0027. GATE_PEAD.md's 0.040 threshold was written for a cross-section.
    ic_full = cross_sectional_rank_ic(oof_sig, oof_fwd, min_names=20, periods_per_year=ppy)
    ic_cond = cross_sectional_rank_ic(
        oof_sig, oof_fwd, min_names=4, min_abs_signal=1.5, periods_per_year=ppy
    )
    mean_ic = ic_full["mean_rank_ic"]
    icir = ic_full["rank_icir"]

    oof_predictions: list[float] = []
    oof_realized: list[float] = []
    for i in range(len(oof_sig)):
        sig_row, ret_row = oof_sig.iloc[i], oof_fwd.iloc[i]
        valid = sig_row.notna() & ret_row.notna() & (np.abs(sig_row) > 1.5)
        if valid.sum() >= 4:
            oof_predictions.extend(sig_row[valid].values)
            oof_realized.extend((ret_row[valid].values > 0).astype(float))

    # Fit Isotonic Calibration on OOF predictions
    if len(oof_predictions) > 50:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.05, y_max=0.95)
        iso.fit(oof_predictions, oof_realized)
        calibrated_sample = float(np.mean(iso.predict(oof_predictions)))
    else:
        calibrated_sample = 0.50

    # Portfolio construction: long the strongest positive gaps, short the
    # strongest negative ones, holding `holding_days`. Weights are stamped on
    # the bar the signal is formed; simulate_long_short applies the execution
    # lag, so nothing here can book a signal bar's own return.
    long_w = pd.DataFrame(0.0, index=dates, columns=df_signal.columns)
    short_w = pd.DataFrame(0.0, index=dates, columns=df_signal.columns)

    for i in range(0, n_dates - holding_days, holding_days):
        sig_row = df_signal.iloc[i]
        top_long = sig_row[sig_row >= 2.0].nlargest(5)
        top_short = sig_row[sig_row <= -2.0].nsmallest(5)

        if len(top_long) > 0:
            for s in top_long.index:
                long_w.iloc[i : i + holding_days, long_w.columns.get_loc(s)] = 1.0 / len(top_long)
        if len(top_short) > 0:
            for s in top_short.index:
                short_w.iloc[i : i + holding_days, short_w.columns.get_loc(s)] = 1.0 / len(top_short)

    close_prices = pd.DataFrame({s: d["Close"] for s, d in data.items()}).reindex(dates).ffill()

    sim = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close_prices,
        execution_lag=EXECUTION_LAG,
        cost_per_side=COST_PER_SIDE,
    )
    # Sensitivity: if the result only survives at the tightest possible
    # execution assumption, it is not a result.
    sim_lag2 = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close_prices,
        execution_lag=EXECUTION_LAG + 1,
        cost_per_side=COST_PER_SIDE,
    )

    net_annual = sim.net_annual_return
    sharpe = sim.sharpe
    max_drawdown = sim.max_drawdown

    # Gate check (GATE_PEAD.md)
    gate_checks = {
        "mean_ic_gt_04": float(mean_ic) > 0.040,
        "icir_gt_05": float(icir) > 0.50,
        "net_annual_gt_8": float(net_annual) > 0.08,
        "sharpe_gt_06": float(sharpe) > 0.60,
        "max_drawdown_lt_15": float(max_drawdown) < 0.15,
    }
    is_go = all(gate_checks.values())

    return {
        "mean_rank_ic": mean_ic,
        "rank_icir": icir,
        "mean_rank_ic_conditional_abs_gt_1p5": ic_cond["mean_rank_ic"],
        "rank_icir_conditional_abs_gt_1p5": ic_cond["rank_icir"],
        "ic_n_bars": ic_full["n_bars"],
        "execution_lag_bars": EXECUTION_LAG,
        "annual_turnover": sim.annual_turnover,
        "cost_drag_pct": sim.cost_drag * 100.0,
        "gross_annual_return_pct": sim.gross_annual_return * 100.0,
        "net_annual_return_pct": net_annual * 100.0,
        "compounded_annual_return_pct": sim.compounded_annual_return * 100.0,
        "annual_volatility_pct": sim.annual_volatility * 100.0,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_drawdown * 100.0,
        "exposure": sim.exposure,
        "n_extreme_bars_masked": sim.n_extreme_masked,
        "sensitivity_lag2_net_annual_pct": sim_lag2.net_annual_return * 100.0,
        "sensitivity_lag2_sharpe": sim_lag2.sharpe,
        "short_pressure_active": short_pressure_active,
        # A plain string, not just a bool, so the doc's prose is itself an
        # artifact key -- see reporting.py's module docstring: every figure
        # (including this sentence) is pulled from the artifact, not
        # synthesized at render time from a bool the template branches on.
        "short_pressure_status_text": (
            "ACTIVE" if short_pressure_active
            else "INACTIVE: FINRA data absent, contributes nothing"
        ),
        "calibrated_prob_mean": calibrated_sample,
        "gate_checks": gate_checks,
        "verdict": "GO" if is_go else "NO-GO",
        "universe_size": len(data),
    }


# ---------------------------------------------------------------------------
# Result doc, rendered from the artifact JSON (edge.research.reporting) --
# not assembled from this dict directly. See reporting.py's module docstring
# for why: GATE_PEAD_RESULT.md was one of the two retracted docs whose
# figures "matched no artifact" (edge/docs/STATUS.md:113). Sourcing every
# figure below through `Figure(key_path=...)` against the *file this run just
# wrote* makes that failure mode structurally unrepresentable rather than
# merely fixed by hand this one time.
# ---------------------------------------------------------------------------

PEAD_CATALYST_GATE_SPEC = GateReportSpec(
    gate_family="pead-catalyst",
    verdict_key_path="verdict",
    figures=(
        Figure("mean_rank_ic", "mean_rank_ic", "ratio4", "> 0.040", "gate_checks.mean_ic_gt_04"),
        Figure("rank_icir", "rank_icir", "ratio2", "> 0.50", "gate_checks.icir_gt_05"),
        Figure("net_annual_return_pct", "net_annual_return_pct", "pct_already", "> +8.0%", "gate_checks.net_annual_gt_8"),
        Figure("sharpe_ratio", "sharpe_ratio", "ratio2", "> 0.60", "gate_checks.sharpe_gt_06"),
        Figure("max_drawdown_pct", "max_drawdown_pct", "pct_already", "< 15.0%", "gate_checks.max_drawdown_lt_15"),
        Figure("sensitivity_lag2_net_annual_pct", "sensitivity_lag2_net_annual_pct", "pct_already"),
        Figure("sensitivity_lag2_sharpe", "sensitivity_lag2_sharpe", "ratio2"),
        Figure("gross_annual_return_pct", "gross_annual_return_pct", "pct_already"),
        Figure("annual_volatility_pct", "annual_volatility_pct", "pct_already"),
        Figure("compounded_annual_return_pct", "compounded_annual_return_pct", "pct_already"),
        Figure("exposure", "exposure", "pct1"),
        Figure("universe_size", "universe_size", "int"),
        Figure("execution_lag_bars", "execution_lag_bars", "int"),
        Figure("n_extreme_bars_masked", "n_extreme_bars_masked", "int"),
        Figure("calibrated_prob_mean", "calibrated_prob_mean", "ratio4"),
        Figure("mean_rank_ic_conditional_abs_gt_1p5", "mean_rank_ic_conditional_abs_gt_1p5", "ratio4"),
        Figure("short_pressure_status_text", "short_pressure_status_text", "str"),
    ),
    template="""# Post-Earnings Announcement Drift (PEAD) Honest Re-Validation Result

**Rendered**: {generated_at}
**Artifact**: `{artifact_path}` (sha256 `{artifact_hash}`)
**Verdict**: {verdict_badge}

---

## Performance Summary (Purged & Embargoed Cross-Validation)

| Metric | Target Threshold | Measured Value | Pass / Fail |
|---|---|---|---|
| **Mean Rank IC** | `{mean_rank_ic_threshold}` | `{mean_rank_ic}` | {mean_rank_ic_badge} |
| **Rank ICIR** | `{rank_icir_threshold}` | `{rank_icir}` | {rank_icir_badge} |
| **Net Annual Return** | `{net_annual_return_pct_threshold}` | `{net_annual_return_pct}` | {net_annual_return_pct_badge} |
| **Sharpe / IR** | `{sharpe_ratio_threshold}` | `{sharpe_ratio}` | {sharpe_ratio_badge} |
| **Max Drawdown** | `{max_drawdown_pct_threshold}` | `{max_drawdown_pct}` | {max_drawdown_pct_badge} |

---

## Execution-Lag Sensitivity

The prior version of this artifact booked each bar's own return against a
weight formed from that same bar's features — a one-bar lookahead. It reported
**+502.98% net annual / Sharpe 5.38**. Corrected, the same signal and universe
give the figures above.

| Execution lag | Net annual | Sharpe |
|---|---:|---:|
| 1 bar (reported) | `{net_annual_return_pct}` | `{sharpe_ratio}` |
| 2 bars | `{sensitivity_lag2_net_annual_pct}` | `{sensitivity_lag2_sharpe}` |

Gross annual `{gross_annual_return_pct}` at annualised vol
`{annual_volatility_pct}`; compounded
`{compounded_annual_return_pct}`. Exposure `{exposure}` of bars.

---

## Validation Environment & Protocol

- **Universe**: Broad liquid equity universe ({universe_size} symbols evaluated).
- **Leakage Control**: 5-Fold Purged & Embargoed Cross Validation (`purged_embargoed_kfold_splits`);
  portfolio accounting via `edge.research.portfolio.simulate_long_short`
  (execution lag {execution_lag_bars} bar, enforced).
- **Features**: `gap_std` (20d ATR normalized gap), `vol_surge` (20d SMA volume surge),
  `short_pressure` (FINRA short ratio) — **{short_pressure_status_text}**.
- **Cost Model**: 10bp per side (20bp round-trip), charged per bar on realised turnover.
- **Data hygiene**: {n_extreme_bars_masked} asset bars with |1-day return| > 50%
  masked as unadjusted corporate actions.
- **Isotonic Calibration Mean**: `{calibrated_prob_mean}`

### Headline IC is unconditional

Mean Rank IC is measured on the full cross-section. Restricting to
`|signal| > 1.5` — the subset the strategy actually trades — gives
`{mean_rank_ic_conditional_abs_gt_1p5}`. That conditional figure was
the previous headline; it is a self-selected subset and is not what
`GATE_PEAD.md`'s 0.040 threshold was written against. Both are reported so
neither can be quoted alone.

---

## Final Status

PEAD evaluation has been strictly re-validated under purged cross-validation
with enforced execution lag.
**Verdict**: {verdict_badge}
""",
)


def generate_gate_pead_result_doc(artifact_path: Path) -> str:
    """Render GATE_PEAD_RESULT.md from the results.json this run just wrote.

    Every figure above traces to a key in `artifact_path` via
    `PEAD_CATALYST_GATE_SPEC.figures` -- a metric with no such key raises
    (`edge.research.reporting.MetricNotFoundError`) instead of rendering.
    """
    doc_path = ROOT / "edge" / "docs" / "GATE_PEAD_RESULT.md"
    content = write_gate_doc(artifact_path=artifact_path, spec=PEAD_CATALYST_GATE_SPEC, doc_path=doc_path)
    print(f"Written GATE_PEAD_RESULT.md → {doc_path}")
    return content


def main():
    print("=" * 60)
    print("  PEAD CATALYST GAP ENGINE — HONEST RE-VALIDATION")
    print("=" * 60)

    data = load_wide_universe_ohlcv()
    if not data:
        print("Error: No symbol data loaded.")
        return

    # load_finra_short_vol() raises rather than returning None (see
    # edge/tools/data_sources.py) — the miss must stay visible instead of
    # silently degrading `short_pressure` to a constant the way it used to.
    # This tool can still run without the feature, but only if that decision
    # is made here, out loud, and recorded in `short_pressure_active` below —
    # not swallowed inside the loader the way it was before this fix.
    try:
        finra_sr = load_finra_short_vol()
    except FileNotFoundError as exc:
        print(f"  ! {exc}")
        print("  ! Proceeding with short_pressure INACTIVE (multiplier neutralized to 1.0).")
        finra_sr = None

    df_signal, df_fwd = compute_pead_features(data, finra_short_ratio=finra_sr)

    res = run_honest_pead_validation(
        df_signal, df_fwd, data, holding_days=5, short_pressure_active=finra_sr is not None
    )

    print("\n[PEAD HONEST RE-VALIDATION RESULTS]")
    print(f"  Universe Size:          {res['universe_size']} symbols")
    print(f"  Execution Lag:          {res['execution_lag_bars']} bar(s)")
    print(f"  Mean Rank IC (full XS): {res['mean_rank_ic']:.4f}")
    print(f"  Rank ICIR:              {res['rank_icir']:.2f}")
    print(f"  Mean Rank IC (|s|>1.5): {res['mean_rank_ic_conditional_abs_gt_1p5']:.4f}  [conditional]")
    print(f"  short_pressure active:  {res['short_pressure_active']}")
    print(f"  Annual Turnover:        {res['annual_turnover']*100:.1f}%")
    print(f"  Cost Drag (10bp):       {res['cost_drag_pct']:.2f}%")
    print(f"  Gross Annual Return:    {res['gross_annual_return_pct']:.2f}%")
    print(f"  Net Annual Return:      {res['net_annual_return_pct']:.2f}%")
    print(f"  Annualised Volatility:  {res['annual_volatility_pct']:.2f}%")
    print(f"  Sharpe Ratio:           {res['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:           {res['max_drawdown_pct']:.2f}%")
    print(f"  Extreme bars masked:    {res['n_extreme_bars_masked']}")
    print(f"  [lag+1 sensitivity]     net {res['sensitivity_lag2_net_annual_pct']:.2f}%  "
          f"sharpe {res['sensitivity_lag2_sharpe']:.2f}")
    print(f"  Verdict:                {res['verdict']}")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nArtifact written to {out_file}")

    generate_gate_pead_result_doc(out_file)


if __name__ == "__main__":
    main()
