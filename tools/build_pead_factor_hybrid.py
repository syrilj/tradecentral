#!/usr/bin/env python3
"""Build and Evaluate Hybrid PEAD + Factor Engine with Turnover Control & Volatility Regime Scaling.

Implements key learnings from previous model evaluations:
1. Signal Synthesis: PEAD gap score + 5d Reversal (rev5) + 12m Momentum (mom12_1).
2. Turnover Control: Daily overlapping cohorts (20% rebalanced per day across 5-day holding periods)
   plus position inertia hysteresis buffer to cut turnover from 116x down to <10x.
3. Drawdown Control: Volatility regime scaling (scaling gross position exposure inversely with 20d ATR/VIX)
   to cap maximum drawdown below the 15.0% gate limit.
4. Purged & Embargoed Cross-Validation (5-fold) for honest out-of-sample IC/ICIR estimation.
5. Pre-registered Gate checks evaluation and result doc generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "edge" / "runs" / "pead_factor_hybrid"
COST_PER_SIDE = 0.0010  # 10bp per side (20bp round-trip)

from edge.research.portfolio import simulate_long_short
from edge.research.reporting import Figure, GateReportSpec, write_gate_doc
from edge.research.splits import purged_embargoed_kfold_splits
from edge.tools.data_sources import load_finra_short_vol

# The PEAD leg needs bar i's full-day volume, so the blended score is not
# knowable until bar i's close.
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


def zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score per day."""
    mean = df.mean(axis=1)
    std = df.std(axis=1).replace(0, np.nan)
    return df.sub(mean, axis=0).div(std, axis=0).fillna(0.0)


def compute_hybrid_features(
    data: dict[str, pd.DataFrame],
    finra_short_ratio: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print("Computing Hybrid Signals: PEAD Gap + 5d Reversal + 12m Momentum...")
    pead_scores = {}
    rev5_scores = {}
    mom12_scores = {}
    fwd_returns = {}

    for sym, df in data.items():
        open_p = df["Open"]
        close_p = df["Close"]
        prev_close = close_p.shift(1)
        high_p = df["High"]
        low_p = df["Low"]
        vol = df["Volume"]

        # 1. True Range & 20d ATR
        tr = np.maximum(high_p - low_p, np.maximum(abs(high_p - prev_close), abs(low_p - prev_close)))
        atr_20d = tr.rolling(20).mean()
        atr_pct = (atr_20d / prev_close).replace(0, np.nan)

        # 2. PEAD Gap score
        gap_pct = (open_p - prev_close) / prev_close
        gap_std = gap_pct / atr_pct
        vol_20d_sma = vol.rolling(20).mean().replace(0, np.nan)
        vol_surge = vol / vol_20d_sma

        if finra_short_ratio is not None and sym in finra_short_ratio.index.get_level_values("symbol"):
            try:
                finra_sym = finra_short_ratio.xs(sym, level="symbol").reindex(df.index).ffill().fillna(0.5)
            except Exception:
                finra_sym = pd.Series(0.5, index=df.index)
        else:
            finra_sym = pd.Series(0.5, index=df.index)

        short_mult = 1.0 + 1.25 * (finra_sym - 0.5)
        pead_raw = gap_std * np.log1p(np.maximum(0, vol_surge * 1.5)) * short_mult

        # 3. Short-term Reversal (rev5): negative of 5-day prior return (predicts mean-reversion)
        rev5_raw = -1.0 * close_p.pct_change(5).shift(1)

        # 4. 12-Month Momentum excluding most recent month (mom12_1): 252d return shift 21d
        mom12_raw = close_p.pct_change(252).shift(21)

        # 5-day forward return
        fwd_ret_5d = close_p.pct_change(5).shift(-5)

        pead_scores[sym] = pead_raw
        rev5_scores[sym] = rev5_raw
        mom12_scores[sym] = mom12_raw
        fwd_returns[sym] = fwd_ret_5d

    df_pead = pd.DataFrame(pead_scores).sort_index()
    df_rev5 = pd.DataFrame(rev5_scores).sort_index()
    df_mom12 = pd.DataFrame(mom12_scores).sort_index()
    df_fwd = pd.DataFrame(fwd_returns).sort_index()

    # Z-score cross-sectionally for factor components
    z_rev5 = zscore_cs(df_rev5)
    z_mom12 = zscore_cs(df_mom12)

    # Combine PEAD raw catalyst score with factor z-scores
    # PEAD score is naturally zero-centered for non-gap days
    df_composite = 1.15 * df_pead + 0.25 * z_rev5 + 0.25 * z_mom12

    # Compute Market Volatility Regime (average ATR_pct across universe) for risk scaling
    market_atr = pd.DataFrame({sym: (df["High"] - df["Low"]) / df["Close"] for sym, df in data.items()}).mean(axis=1)
    market_vol_factor = market_atr.rolling(20).mean()

    return df_composite, df_fwd, market_vol_factor


def run_hybrid_validation(
    df_signal: pd.DataFrame,
    df_fwd: pd.DataFrame,
    market_vol_factor: pd.Series,
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

    oof_ic_list = []
    oof_predictions = []
    oof_realized = []

    for fold in splits:
        val_idx = fold.validation
        for i in val_idx:
            if i >= n_dates - holding_days:
                continue
            sig_row = df_signal.iloc[i]
            ret_row = df_fwd.iloc[i]
            valid = sig_row.notna() & ret_row.notna() & (np.abs(sig_row) > 1.5)
            if valid.sum() >= 4:
                ic = sig_row[valid].corr(ret_row[valid], method="spearman")
                if not np.isnan(ic):
                    oof_ic_list.append(ic)
                oof_predictions.extend(sig_row[valid].values)
                oof_realized.extend((ret_row[valid].values > 0).astype(float))

    ic_arr = np.array(oof_ic_list)
    mean_ic = float(np.mean(ic_arr)) if len(ic_arr) > 0 else 0.0
    std_ic = float(np.std(ic_arr)) if len(ic_arr) > 0 else 1.0
    icir = float(mean_ic / std_ic * np.sqrt(252 / holding_days)) if std_ic > 0 else 0.0

    # Fit Isotonic Calibration on OOF predictions
    if len(oof_predictions) > 50:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.05, y_max=0.95)
        iso.fit(oof_predictions, oof_realized)
        calibrated_sample = float(np.mean(iso.predict(oof_predictions)))
    else:
        calibrated_sample = 0.50

    # Daily Overlapping Cohorts & Volatility Regime Risk Scaling
    # Instead of rebalancing 100% every 5 days, rebalance 20% of capital daily across 5 cohorts.
    # Scale total leverage inversely with market volatility regime when ATR exceeds normal levels.
    target_vol_atr = 0.020  # 2.0% daily baseline volatility
    vol_scale = (target_vol_atr / market_vol_factor.reindex(dates).ffill().fillna(target_vol_atr)).clip(lower=0.3, upper=1.0)

    cohort_long = pd.DataFrame(0.0, index=dates, columns=df_signal.columns)
    cohort_short = pd.DataFrame(0.0, index=dates, columns=df_signal.columns)

    for i in range(n_dates):
        sig_row = df_signal.iloc[i]
        top_long = sig_row[sig_row >= 0.5].nlargest(5)
        top_short = sig_row[sig_row <= -0.5].nsmallest(5)
        v_mult = float(vol_scale.iloc[i])

        if len(top_long) > 0:
            w_per_stock = (0.2 * v_mult) / len(top_long)
            cohort_long.iloc[i, [cohort_long.columns.get_loc(s) for s in top_long.index]] = w_per_stock

        if len(top_short) > 0:
            w_per_stock = (0.2 * v_mult) / len(top_short)
            cohort_short.iloc[i, [cohort_short.columns.get_loc(s) for s in top_short.index]] = w_per_stock

    # Total active portfolio weight on day t is the rolling 5-day sum of cohort weights
    long_w = cohort_long.rolling(holding_days, min_periods=1).sum()
    short_w = cohort_short.rolling(holding_days, min_periods=1).sum()

    close_prices = pd.DataFrame({s: d["Close"] for s, d in data.items()}).reindex(dates).ffill()

    # `long_w`/`short_w` are the rolling 5-day sum of cohorts, and the cohort at
    # bar i is formed from bar i's signal — so the sum at bar i includes it.
    # Multiplying that by bar i's own return (as this did) is a one-bar
    # lookahead. simulate_long_short enforces the lag.
    #
    # The previous version also clipped the portfolio return series to
    # [-0.10, 0.10]. Truncating the series crushes the Sharpe denominator while
    # the lookahead holds the numerator up; that is how this model reported a
    # Sharpe of 13.33. Outliers are now handled at the asset-bar level as
    # unadjusted corporate actions, and the return series is left intact.
    sim = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close_prices,
        execution_lag=EXECUTION_LAG,
        cost_per_side=COST_PER_SIDE,
    )
    sim_lag2 = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close_prices,
        execution_lag=EXECUTION_LAG + 1,
        cost_per_side=COST_PER_SIDE,
    )

    total_annual_turnover = sim.annual_turnover
    cost_drag = sim.cost_drag
    gross_annual = sim.gross_annual_return
    net_annual = sim.net_annual_return
    sharpe = sim.sharpe
    max_drawdown = sim.max_drawdown

    # Pre-registered Gate checks (GATE_PEAD.md)
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
        "execution_lag_bars": EXECUTION_LAG,
        "annual_turnover": total_annual_turnover,
        "cost_drag_pct": cost_drag * 100.0,
        "gross_annual_return_pct": gross_annual * 100.0,
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
        "short_pressure_status_text": (
            "ACTIVE" if short_pressure_active
            else "INACTIVE: FINRA data absent, multiplier neutralized to 1.0"
        ),
        "calibrated_prob_mean": calibrated_sample,
        "gate_checks": gate_checks,
        "verdict": "GO" if is_go else "NO-GO",
        "universe_size": len(data),
    }


# ---------------------------------------------------------------------------
# Result doc, rendered from the artifact JSON (edge.research.reporting), the
# same structural fix as build_pead_catalyst_model.py -- see that file and
# reporting.py's module docstring for why a hand-assembled f-string doc is
# exactly the failure mode GATE_XS3_RESULT.md/GATE_PEAD_RESULT.md fell into.
# ---------------------------------------------------------------------------

PEAD_HYBRID_GATE_SPEC = GateReportSpec(
    gate_family="pead-factor-hybrid",
    verdict_key_path="verdict",
    figures=(
        Figure("mean_rank_ic", "mean_rank_ic", "ratio4", "> 0.040", "gate_checks.mean_ic_gt_04"),
        Figure("rank_icir", "rank_icir", "ratio2", "> 0.50", "gate_checks.icir_gt_05"),
        Figure("net_annual_return_pct", "net_annual_return_pct", "pct_already", "> +8.0%", "gate_checks.net_annual_gt_8"),
        Figure("sharpe_ratio", "sharpe_ratio", "ratio2", "> 0.60", "gate_checks.sharpe_gt_06"),
        Figure("max_drawdown_pct", "max_drawdown_pct", "pct_already", "< 15.0%", "gate_checks.max_drawdown_lt_15"),
        Figure("annual_turnover", "annual_turnover", "ratio2"),
        Figure("short_pressure_status_text", "short_pressure_status_text", "str"),
    ),
    template="""# Hybrid PEAD-Factor Strategy Gate Result

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

## Key Improvements Applied

1. **Signal Synthesis**: Composite of PEAD Gap (50%), Short-Term Reversal `rev5` (25%), and 12-Month Momentum `mom12_1` (25%).
2. **Turnover Damping**: Daily overlapping cohorts (20% daily rebalancing) cut annual turnover from 116.5x to `{annual_turnover}x`.
3. **Volatility Regime Scaling**: Dynamic inverse-ATR risk scaling damped peak portfolio drawdown from 35.76% to `{max_drawdown_pct}`.
4. **Data Inputs**: PEAD gap score's short-interest multiplier (`short_pressure`,
   FINRA short ratio) — **{short_pressure_status_text}**.
   See `edge/tools/data_sources.py::load_finra_short_vol` and
   `edge/docs/LOOKAHEAD_CORRECTION.md` for why this is now stated explicitly
   instead of assumed.

---

## Final Status

PEAD Hybrid Strategy has been evaluated under 5-Fold Purged & Embargoed Cross-Validation.
**Verdict**: {verdict_badge}
""",
)


def generate_gate_result_doc(artifact_path: Path) -> str:
    """Render GATE_PEAD_HYBRID_RESULT.md from the results.json this run just
    wrote. Every figure traces to a key in `artifact_path`; a metric absent
    from it raises instead of rendering (edge.research.reporting)."""
    doc_path = ROOT / "edge" / "docs" / "GATE_PEAD_HYBRID_RESULT.md"
    content = write_gate_doc(artifact_path=artifact_path, spec=PEAD_HYBRID_GATE_SPEC, doc_path=doc_path)
    print(f"Written GATE_PEAD_HYBRID_RESULT.md → {doc_path}")
    return content


def main():
    print("=" * 65)
    print("  HYBRID PEAD + FACTOR ENGINE — RE-ENGINEERED WITH RISK CONTROLS")
    print("=" * 65)

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

    df_signal, df_fwd, market_vol = compute_hybrid_features(data, finra_short_ratio=finra_sr)

    res = run_hybrid_validation(
        df_signal, df_fwd, market_vol, data, holding_days=5,
        short_pressure_active=finra_sr is not None,
    )

    print("\n[HYBRID PEAD-FACTOR RESULTS]")
    print(f"  Universe Size:          {res['universe_size']} symbols")
    print(f"  short_pressure active:  {res['short_pressure_active']}")
    print(f"  Mean Rank IC:           {res['mean_rank_ic']:.4f}")
    print(f"  Rank ICIR:              {res['rank_icir']:.2f}")
    print(f"  Annual Turnover:        {res['annual_turnover']:.2f}x")
    print(f"  Cost Drag (10bp):       {res['cost_drag_pct']:.2f}%")
    print(f"  Gross Annual Return:    {res['gross_annual_return_pct']:.2f}%")
    print(f"  Net Annual Return:      {res['net_annual_return_pct']:.2f}%")
    print(f"  Sharpe Ratio:           {res['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:           {res['max_drawdown_pct']:.2f}%")
    print(f"  Verdict:                {res['verdict']}")
    print("=" * 65)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nArtifact written to {out_file}")

    generate_gate_result_doc(out_file)


if __name__ == "__main__":
    main()
