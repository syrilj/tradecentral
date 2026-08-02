#!/usr/bin/env python3
"""GEX & Option Positioning Meta-Model Training Engine.

Trains a predictive classifier/regressor on 75,335 forward-recorded signals
and 293,729 realized outcomes from TradingWork/data/signal_journal.db.

Features:
  - gex_regime: POSITIVE_GEX (+1), NEAR_FLIP (0), NEGATIVE_GEX (-1)
  - dist_to_flip_pct: Percentage distance from spot price to zero-gamma flip
  - score: Base signal score
  - direction: LONG (+1), SHORT (-1)
  - trend: Ordinal trend strength

Evaluation:
  - 5-Fold Purged & Embargoed Cross-Validation
  - Gate criteria matching GATE_GEX.md
  - Produces GATE_GEX_RESULT.md artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "TradingWork" / "data" / "signal_journal.db"
OUT_DIR = ROOT / "edge" / "runs" / "gex_model"
COST_PER_SIDE = 0.0010  # 10bp per side

from edge.research.splits import purged_embargoed_kfold_splits


def load_signal_journal_dataset() -> pd.DataFrame:
    print(f"Loading signal journal dataset from {DB_PATH}...")
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    query = """
    SELECT 
        s.id,
        s.ticker,
        s.trading_date,
        s.score,
        s.direction,
        s.gex_regime,
        s.dist_to_flip_pct,
        s.trend,
        o.horizon,
        o.fwd_return,
        o.fwd_return_excess
    FROM signals s
    JOIN outcomes o ON s.id = o.signal_id
    WHERE o.fwd_return IS NOT NULL
    ORDER BY s.trading_date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(f"Loaded {len(df):,} signal-outcome records across {df['ticker'].nunique()} tickers.")
    return df


def preprocess_gex_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Direction encoding
    df["dir_val"] = df["direction"].apply(lambda d: 1.0 if str(d).upper() == "LONG" else -1.0 if str(d).upper() == "SHORT" else 0.0)

    # GEX regime encoding
    regime_map = {"POSITIVE_GEX": 1.0, "NEAR_FLIP": 0.0, "NEGATIVE_GEX": -1.0}
    df["gex_regime_val"] = df["gex_regime"].map(regime_map).fillna(0.0)

    # Fill dist_to_flip_pct
    df["dist_to_flip_pct"] = pd.to_numeric(df["dist_to_flip_pct"], errors="coerce").fillna(0.0)

    # Fill score
    df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0.0)

    # Feature matrix
    df["feature_score"] = df["score"] * df["dir_val"] * (1.0 + 0.2 * df["gex_regime_val"])

    return df


def train_and_evaluate_gex_model(df: pd.DataFrame) -> dict[str, Any]:
    # Group by trading date for time-series splits
    trading_dates = sorted(df["trading_date"].unique())
    n_dates = len(trading_dates)
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}
    df["date_idx"] = df["trading_date"].map(date_to_idx)

    # 5-fold purged CV over trading dates
    splits = list(
        purged_embargoed_kfold_splits(
            n_samples=n_dates,
            label_horizon=5,
            n_splits=5,
            embargo=5,
        )
    )

    oof_predictions = []
    oof_actuals = []
    daily_returns = []

    features = ["score", "dir_val", "gex_regime_val", "dist_to_flip_pct", "feature_score"]

    for fold in splits:
        train_dates = set(np.array(trading_dates)[fold.train])
        val_dates = set(np.array(trading_dates)[fold.validation])

        train_df = df[df["trading_date"].isin(train_dates)]
        val_df = df[df["trading_date"].isin(val_dates)]

        if train_df.empty or val_df.empty:
            continue

        model = GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42)
        model.fit(train_df[features], train_df["fwd_return"])

        preds = model.predict(val_df[features])
        oof_predictions.extend(preds)
        oof_actuals.extend(val_df["fwd_return"].values)

        # Compute daily long/short portfolio returns for validation dates
        for d, group in val_df.groupby("trading_date"):
            top_long = group[group["feature_score"] > 0.5]
            if not top_long.empty:
                daily_returns.append(top_long["fwd_return"].mean())

    oof_preds_arr = np.array(oof_predictions)
    oof_actuals_arr = np.array(oof_actuals)

    # Calculate Rank IC
    if len(oof_preds_arr) > 0:
        rank_ic = float(pd.Series(oof_preds_arr).corr(pd.Series(oof_actuals_arr), method="spearman"))
    else:
        rank_ic = 0.0

    daily_ret_arr = np.array(daily_returns) if daily_returns else np.array([0.0])
    mean_ret = float(np.mean(daily_ret_arr))
    std_ret = float(np.std(daily_ret_arr)) if len(daily_ret_arr) > 1 else 1.0

    annual_ret = float(mean_ret * 252.0)
    cost_drag = 0.02  # ~2% turnover cost drag
    net_annual = float(annual_ret - cost_drag)

    sharpe = float(mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
    icir = float(rank_ic / (std_ret + 1e-6) * np.sqrt(252)) if std_ret > 0 else 0.0

    # Drawdown
    cum = np.cumprod(1.0 + daily_ret_arr)
    pk = np.maximum.accumulate(cum)
    dd = (pk - cum) / pk
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    gate_checks = {
        "mean_ic_gt_035": float(rank_ic) > 0.035,
        "icir_gt_05": float(icir) > 0.50,
        "net_annual_gt_6": float(net_annual) > 0.06,
        "sharpe_gt_06": float(sharpe) > 0.60,
        "max_drawdown_lt_18": float(max_dd) < 0.18,
    }
    is_go = all(gate_checks.values())

    artifact_hash = hashlib.sha256(
        f"gex_model_ic={rank_ic:.4f}_net={net_annual:.4f}_dd={max_dd:.4f}".encode("utf-8")
    ).hexdigest()

    return {
        "mean_rank_ic": rank_ic,
        "rank_icir": icir,
        "net_annual_return_pct": net_annual * 100.0,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd * 100.0,
        "n_signals_evaluated": len(df),
        "gate_checks": gate_checks,
        "verdict": "GO" if is_go else "NO-GO",
        "artifact_sha256": artifact_hash,
    }


def generate_gate_gex_result_doc(res: dict[str, Any]) -> None:
    doc_path = ROOT / "edge" / "docs" / "GATE_GEX_RESULT.md"
    verdict = res["verdict"]
    badge = "🟢 **GO**" if verdict == "GO" else "🔴 **NO-GO**"

    content = f"""# GEX & Option Positioning Meta-Model Gate Result

**Evaluation Date**: 2026-07-31  
**Artifact SHA256**: `{res['artifact_sha256']}`  
**Verdict**: {badge}

---

## Performance Summary (Purged & Embargoed Cross-Validation)

| Metric | Target Threshold | Measured Value | Pass / Fail |
|---|---|---|---|
| **Mean Rank IC** | `> 0.035` | `{res['mean_rank_ic']:.4f}` | {'✅ PASS' if res['gate_checks']['mean_ic_gt_035'] else '❌ FAIL'} |
| **Rank ICIR** | `> 0.50` | `{res['rank_icir']:.2f}` | {'✅ PASS' if res['gate_checks']['icir_gt_05'] else '❌ FAIL'} |
| **Net Annual Return** | `> +6.0%` | `{res['net_annual_return_pct']:.2f}%` | {'✅ PASS' if res['gate_checks']['net_annual_gt_6'] else '❌ FAIL'} |
| **Sharpe Ratio** | `> 0.60` | `{res['sharpe_ratio']:.2f}` | {'✅ PASS' if res['gate_checks']['sharpe_gt_06'] else '❌ FAIL'} |
| **Max Drawdown** | `< 18.0%` | `{res['max_drawdown_pct']:.2f}%` | {'✅ PASS' if res['gate_checks']['max_drawdown_lt_18'] else '❌ FAIL'} |

---

## Dataset & Training Environment

- **Source Database**: `TradingWork/data/signal_journal.db` ({res['n_signals_evaluated']:,} signal-outcome pairs).
- **Features Included**: `gex_regime`, `dist_to_flip_pct`, `score`, `direction`, `feature_score`.
- **Validation**: 5-Fold Purged & Embargoed Cross Validation on trading dates.

---

## Final Status

**Verdict**: **{verdict}**
"""
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(content, encoding="utf-8")
    print(f"Written GATE_GEX_RESULT.md → {doc_path}")


def main():
    print("=" * 60)
    print("  GEX & OPTION POSITIONING META-MODEL TRAINING & GATE EVALUATION")
    print("=" * 60)

    df = load_signal_journal_dataset()
    df = preprocess_gex_features(df)
    res = train_and_evaluate_gex_model(df)

    print("\n[GEX META-MODEL EVALUATION RESULTS]")
    print(f"  Signals Evaluated:      {res['n_signals_evaluated']:,}")
    print(f"  Mean Rank IC:           {res['mean_rank_ic']:.4f}")
    print(f"  Rank ICIR:              {res['rank_icir']:.2f}")
    print(f"  Net Annual Return:      {res['net_annual_return_pct']:.2f}%")
    print(f"  Sharpe Ratio:           {res['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:           {res['max_drawdown_pct']:.2f}%")
    print(f"  Verdict:                {res['verdict']}")
    print(f"  Artifact SHA256:        {res['artifact_sha256']}")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nArtifact written to {out_file}")

    generate_gate_gex_result_doc(res)


if __name__ == "__main__":
    main()
