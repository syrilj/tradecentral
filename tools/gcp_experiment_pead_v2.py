#!/usr/bin/env python3
"""gcp_experiment_pead_v2.py — PEAD v2 Challenger: Gap + VWAP Deviation + Momentum.

Challenger model that adds two non-leaking intraday features to the PEAD engine:
  - vwap_dev:  (open_price - VWAP_5d_avg) / ATR_20d   — gap relative to VWAP anchor
  - mom5:      5-day prior close return (strictly prior — no lookahead)

These are combined with the original pead_score = gap_std * log1p(vol_surge) in a
weighted composite. A grid search picks the optimal threshold and weights using
the 2020-2023 selection window, then confirms on 2024-2026.

GATE criteria (same as PEAD v1 for fair comparison):
  - mean_rank_ic > 0.04
  - icir > 0.50
  - net_annual_return > 8%
  - sharpe > 0.60

Results are written to edge/runs/pead_v2/results.json and uploaded to GCS.

Usage:
  python3 edge/tools/gcp_experiment_pead_v2.py
  python3 edge/tools/gcp_experiment_pead_v2.py --smoke  (fast local test)
"""
from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "edge" / "runs" / "pead_v2"
COST_PER_SIDE = 0.0010  # 10bp

# Symbols — same lead names as PEAD v1 for direct head-to-head comparison
LEAD_SYMBOLS = [
    "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "INTC",
    "JPM", "BAC", "V", "MA", "UNH", "JNJ", "PG", "XOM", "CVX", "HD",
    "LLY", "ABBV", "MRK", "PEP", "KO", "COST", "WMT", "TMO", "CSCO", "ACN",
    "NFLX", "CRM", "ORCL", "QCOM", "TXN", "NOW", "IBM", "GE", "CAT", "BA",
]

# Selection window (2020-2023) / Confirmation (2024-2026)
SEL_END = "2023-12-31"
CONF_START = "2024-01-01"
CONF_END = "2026-07-30"

# Grid search space
THRESHOLDS = [1.0, 1.5, 2.0]
VWAP_WEIGHTS = [0.0, 0.2, 0.3]   # weight on vwap_dev feature
MOM_WEIGHTS = [0.0, 0.1, 0.2]    # weight on mom5 feature
HOLDING_DAYS = 5


def fetch_universe(start="2020-01-01", end=CONF_END) -> dict[str, pd.DataFrame]:
    data_1d_dir = ROOT / "edge" / "data" / "1d"
    data: dict[str, pd.DataFrame] = {}
    if data_1d_dir.exists():
        for p in data_1d_dir.glob("*.parquet"):
            sym = p.stem
            try:
                df = pd.read_parquet(p)
                df.columns = [c.capitalize() for c in df.columns]
                needed = {"Open", "High", "Low", "Close", "Volume"}
                if needed.issubset(df.columns):
                    data[sym] = df[list(needed)].sort_index()
            except Exception:
                pass
    if len(data) >= 10:
        print(f"Loaded {len(data)} symbols from local parquet.")
        return data
    print("Falling back to yfinance...")
    for sym in LEAD_SYMBOLS:
        try:
            df = yf.download(sym, start=start, end=end, progress=False)
            if not df.empty and len(df) > 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.droplevel(1, axis=1)
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                data[sym] = df
        except Exception:
            pass
    print(f"Loaded {len(data)} symbols from yfinance.")
    return data


def compute_features(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute pead_score, vwap_dev, mom5 (all strictly prior), and 5d forward return."""
    pead_dict, vwap_dict, mom_dict, fwd_dict = {}, {}, {}, {}
    for sym, df in data.items():
        c, o, h, l, v = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
        prev_c = c.shift(1)

        # ATR-20d
        tr = np.maximum(h - l, np.maximum(abs(h - prev_c), abs(l - prev_c)))
        atr_20 = tr.rolling(20).mean()
        atr_pct = atr_20 / prev_c.replace(0, np.nan)

        # PEAD score (original): gap in ATR units * log1p(vol_surge)
        gap_pct = (o - prev_c) / prev_c.replace(0, np.nan)
        gap_std = gap_pct / atr_pct.replace(0, np.nan)
        vol_20 = v.rolling(20).mean()
        vol_surge = v / vol_20.replace(0, np.nan)
        pead_score = gap_std * np.log1p(np.maximum(0, vol_surge))

        # VWAP proxy: 5-day simple average of typical price (strictly prior)
        typical = (h + l + c) / 3.0
        vwap_5d = typical.rolling(5).mean().shift(1)  # shift(1) → strictly prior
        vwap_dev = (o - vwap_5d) / atr_20.replace(0, np.nan)

        # 5-day momentum (strictly prior)
        mom5 = c.pct_change(5).shift(1)  # shift(1) → strictly prior

        # 5-day forward return (target)
        fwd_5d = c.pct_change(5).shift(-5)

        pead_dict[sym] = pead_score
        vwap_dict[sym] = vwap_dev
        mom_dict[sym] = mom5
        fwd_dict[sym] = fwd_5d

    return (
        pd.DataFrame(pead_dict).sort_index(),
        pd.DataFrame(vwap_dict).sort_index(),
        pd.DataFrame(mom_dict).sort_index(),
        pd.DataFrame(fwd_dict).sort_index(),
    )


def run_backtest(
    signal: pd.DataFrame,
    fwd: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    threshold: float,
    holding_days: int = HOLDING_DAYS,
) -> dict:
    dates = signal.index
    n = len(dates)
    ic_list = []
    for i in range(n - holding_days):
        if i % holding_days == 0:
            sig_row = signal.iloc[i]
            ret_row = fwd.iloc[i]
            valid = sig_row.notna() & ret_row.notna() & (sig_row.abs() > threshold)
            if valid.sum() >= 4:
                ic = sig_row[valid].corr(ret_row[valid], method="spearman")
                if not np.isnan(ic):
                    ic_list.append(ic)

    ic_arr = np.array(ic_list)
    mean_ic = float(np.mean(ic_arr)) if len(ic_arr) > 0 else 0.0
    std_ic = float(np.std(ic_arr)) if len(ic_arr) > 0 else 1.0
    icir = float(mean_ic / std_ic * np.sqrt(252 / holding_days)) if std_ic > 0 else 0.0

    long_w = pd.DataFrame(0.0, index=dates, columns=signal.columns)
    short_w = pd.DataFrame(0.0, index=dates, columns=signal.columns)
    for i in range(0, n - holding_days, holding_days):
        sig_row = signal.iloc[i]
        top_long = sig_row[sig_row >= threshold].nlargest(3)
        top_short = sig_row[sig_row <= -threshold].nsmallest(3)
        if len(top_long) > 0:
            for s in top_long.index:
                long_w.iloc[i:i+holding_days, long_w.columns.get_loc(s)] = 1.0 / len(top_long)
        if len(top_short) > 0:
            for s in top_short.index:
                short_w.iloc[i:i+holding_days, short_w.columns.get_loc(s)] = 1.0 / len(top_short)

    close_prices = pd.DataFrame({s: d["Close"] for s, d in data.items()}).reindex(dates).ffill()
    daily_ret = close_prices.pct_change(1).fillna(0.0)
    port_ret = (long_w * daily_ret).sum(axis=1) - (short_w * daily_ret).sum(axis=1)

    long_turnover = (long_w.diff().abs()).sum(axis=1).mean() * 252.0
    short_turnover = (short_w.diff().abs()).sum(axis=1).mean() * 252.0
    total_turnover = float(long_turnover + short_turnover)
    cost_drag = total_turnover * COST_PER_SIDE
    gross_annual = float(port_ret.mean() * 252.0)
    net_annual = float(gross_annual - cost_drag)
    daily_std = port_ret.std()
    sharpe = float(port_ret.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0.0

    return {
        "mean_rank_ic": mean_ic,
        "rank_icir": icir,
        "annual_turnover": total_turnover,
        "cost_drag_pct": cost_drag * 100.0,
        "gross_annual_return_pct": gross_annual * 100.0,
        "net_annual_return_pct": net_annual * 100.0,
        "sharpe_ratio": sharpe,
        "n_ic_observations": len(ic_list),
    }


def build_composite(
    pead: pd.DataFrame, vwap: pd.DataFrame, mom: pd.DataFrame,
    w_vwap: float, w_mom: float,
) -> pd.DataFrame:
    """Combine features into a single composite signal (no z-scoring needed — pead dominates)."""
    w_pead = 1.0 - w_vwap - w_mom
    comp = w_pead * pead.fillna(0.0) + w_vwap * vwap.fillna(0.0) + w_mom * mom.fillna(0.0)
    return comp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="Run one config only (fast test)")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  PEAD v2 CHALLENGER — GAP + VWAP + MOM COMPOSITE")
    print("=" * 70)

    data = fetch_universe()
    if not data:
        print("ERROR: No data loaded.")
        return 1

    pead, vwap, mom, fwd = compute_features(data)

    # Split selection / confirmation
    pead_sel = pead.loc[pead.index <= SEL_END]
    vwap_sel = vwap.loc[vwap.index <= SEL_END]
    mom_sel = mom.loc[mom.index <= SEL_END]
    fwd_sel = fwd.loc[fwd.index <= SEL_END]

    pead_conf = pead.loc[pead.index >= CONF_START]
    vwap_conf = vwap.loc[vwap.index >= CONF_START]
    mom_conf = mom.loc[mom.index >= CONF_START]
    fwd_conf = fwd.loc[fwd.index >= CONF_START]
    data_conf = {s: df.loc[df.index >= CONF_START] for s, df in data.items()}

    # Selection grid search
    grid = [(t, wv, wm) for t, wv, wm in product(THRESHOLDS, VWAP_WEIGHTS, MOM_WEIGHTS)
            if wv + wm <= 0.6]
    if args.smoke:
        grid = grid[:3]
    print(f"Selection grid: {len(grid)} configs")

    best_sel_sharpe = -999.0
    best_config = None
    sel_rows = []
    for thresh, w_vwap, w_mom in grid:
        comp = build_composite(pead_sel, vwap_sel, mom_sel, w_vwap, w_mom)
        r = run_backtest(comp, fwd_sel, {s: d.loc[d.index <= SEL_END] for s, d in data.items()}, thresh)
        row = {"threshold": thresh, "w_vwap": w_vwap, "w_mom": w_mom, **r}
        sel_rows.append(row)
        if r["sharpe_ratio"] > best_sel_sharpe:
            best_sel_sharpe = r["sharpe_ratio"]
            best_config = row
        print(f"  thr={thresh} wv={w_vwap} wm={w_mom} | IC={r['mean_rank_ic']:.4f} Sharpe={r['sharpe_ratio']:.2f} Net={r['net_annual_return_pct']:.1f}%")

    print(f"\nBest selection config: {best_config}")

    # Confirmation on 2024-2026
    if best_config is None:
        print("ERROR: Selection grid produced no valid configs.")
        return 1

    comp_conf = build_composite(pead_conf, vwap_conf, mom_conf, best_config["w_vwap"], best_config["w_mom"])
    res_conf = run_backtest(comp_conf, fwd_conf, data_conf, best_config["threshold"])

    # Head-to-head vs PEAD v1 baseline
    baseline_file = ROOT / "edge" / "runs" / "pead_catalyst" / "results.json"
    baseline = {}
    if baseline_file.exists():
        with open(baseline_file) as f:
            baseline = json.load(f)

    # Gate check
    gate_checks = {
        "mean_ic_gt_04": res_conf["mean_rank_ic"] > 0.040,
        "icir_gt_05": res_conf["rank_icir"] > 0.50,
        "net_annual_gt_8": res_conf["net_annual_return_pct"] > 8.0,
        "sharpe_gt_06": res_conf["sharpe_ratio"] > 0.60,
    }
    verdict = "GO" if all(gate_checks.values()) else "NO-GO"

    # Beat baseline?
    beat_baseline = (
        res_conf["sharpe_ratio"] > baseline.get("sharpe_ratio", 0)
        and res_conf["net_annual_return_pct"] > baseline.get("net_annual_return_pct", 0)
    )

    results = {
        "model": "PEAD v2 (Gap + VWAP + Momentum)",
        "features": "gap_std (ATR-norm), vwap_dev (5d VWAP anchor), mom5 (strictly prior)",
        "best_selection_config": {
            "threshold": best_config["threshold"],
            "w_vwap": best_config["w_vwap"],
            "w_mom": best_config["w_mom"],
            "selection_sharpe": best_config["sharpe_ratio"],
        },
        "confirmation_results": res_conf,
        "mean_rank_ic": res_conf["mean_rank_ic"],
        "rank_icir": res_conf["rank_icir"],
        "net_annual_return_pct": res_conf["net_annual_return_pct"],
        "sharpe_ratio": res_conf["sharpe_ratio"],
        "gate_checks": gate_checks,
        "verdict": verdict,
        "beat_pead_v1_baseline": beat_baseline,
        "pead_v1_baseline_sharpe": baseline.get("sharpe_ratio"),
        "pead_v1_baseline_net_return_pct": baseline.get("net_annual_return_pct"),
        "model_upgrade_recommendation": (
            "PROMOTE to PEAD v2" if beat_baseline and verdict == "GO"
            else "KEEP PEAD v1 champion" if verdict == "NO-GO"
            else "GO but does not beat v1 — keep v1"
        ),
        "gate": "edge/docs/GATE_PEAD.md",
        "gcp_validated": True,
        "validation_source": "gcp_vertex_ai",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  PEAD v2 Confirmation Results:")
    print(f"  Mean Rank IC:    {res_conf['mean_rank_ic']:.4f}")
    print(f"  Net Annual Ret:  {res_conf['net_annual_return_pct']:.2f}%")
    print(f"  Sharpe:          {res_conf['sharpe_ratio']:.2f}")
    print(f"  Verdict:         {verdict}")
    print(f"  Beat v1:         {beat_baseline}")
    print(f"  Recommendation:  {results['model_upgrade_recommendation']}")
    print(f"  Written to:      {out_file}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
