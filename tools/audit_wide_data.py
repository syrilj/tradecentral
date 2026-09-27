#!/usr/bin/env python3
"""Why is the wide-universe Rank IC 0.005? Split model failure from data failure.

GATE_XS3_CORRECTION.md establishes the real pitwide test IC is +0.0052 (NW
t=0.47). qlib's own Alpha158+LightGBM benchmark reports IC ~0.04 on CSI300 with
the same handler, same learner, same hyperparameters. An order of magnitude
below the reference implementation is not "US equities are harder" -- it is the
signature of a broken input.

This script asks four questions in order of how cheap they are to answer.

  1. IN-SAMPLE FIT. Fit on train, score IC on train / valid / test separately.
     A model that cannot rank its OWN TRAINING DATA has broken features or a
     misaligned label. A model that ranks train well and test at zero is
     overfitting or a regime break -- a completely different problem with a
     completely different fix. This single number decides which.

  2. PRICE ADJUSTMENT. Unadjusted splits show up as isolated ~-50% / ~+100%
     single-day returns. Alpha158 is built almost entirely from price ratios,
     so one unhandled 4:1 split poisons every window feature that spans it,
     for that name, for 60 days.

  3. LABEL SANITY. Ref($close,-6)/Ref($close,-1)-1 should look like a 5-day
     forward return: roughly symmetric, std ~4-6% for US large caps. If it is
     all zeros, all NaN, or has an implausible scale, the label is wrong and
     nothing downstream can work.

  4. CROSS-SECTIONAL COVERAGE. Rank IC is computed across names per day. If
     most days only have a handful of names with both a feature row and a
     label, the daily IC is a 5-name correlation -- pure noise that averages
     to zero no matter how good the model is.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/audit_wide_data.py --market pitwide
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
sys.path.insert(0, str(EDGE / "tools"))

from qlib_run_wide import load_spec, _spearman  # noqa: E402

SEGMENTS = {
    "train": ("2016-08-01", "2021-06-30"),
    "valid": ("2021-07-16", "2021-12-31"),
    "test": ("2022-01-18", "2023-12-29"),
}


def ic_series(df: pd.DataFrame) -> np.ndarray:
    out = []
    for _, g in df.groupby(level="datetime"):
        if len(g) >= 5:
            ic = _spearman(g["score"], g["label"])
            if np.isfinite(ic):
                out.append(ic)
    return np.asarray(out, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="pitwide")
    args = ap.parse_args()

    import qlib
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.utils import init_instance_by_config

    cfg = load_spec(args.market)
    qlib.init(**cfg["qlib_init"])

    print("=" * 74)
    print(f"WIDE DATA AUDIT  market={args.market}  provider={cfg['qlib_init']['provider_uri']}")
    print("=" * 74)

    # ---- 4. coverage, first: it is the cheapest and it gates the rest --------
    ds_cfg = cfg["task"]["dataset"]
    ds_cfg["kwargs"]["segments"] = {k: list(v) for k, v in SEGMENTS.items()}
    dataset: DatasetH = init_instance_by_config(ds_cfg)

    print("\n[4] CROSS-SECTIONAL COVERAGE  (Rank IC is a per-day correlation across names)")
    for seg in SEGMENTS:
        raw = dataset.prepare(seg, col_set=["feature", "label"], data_key="learn")
        if raw.empty:
            print(f"  {seg:<6} EMPTY -- no rows survived the handler")
            continue
        per_day = raw.groupby(level="datetime").size()
        print(f"  {seg:<6} rows={len(raw):>9,}  days={len(per_day):>5}  "
              f"names/day median={per_day.median():>6.0f}  min={per_day.min():>4}  max={per_day.max():>4}")
        if per_day.median() < 30:
            print(f"         ^^ median {per_day.median():.0f} names/day is too thin for a "
                  f"cross-sectional IC to mean anything")

    # ---- 3. label sanity ----------------------------------------------------
    print("\n[3] LABEL DISTRIBUTION  Ref($close,-6)/Ref($close,-1)-1, pre-CSRankNorm")
    lab = dataset.prepare("train", col_set=["label"], data_key="infer").iloc[:, 0].dropna()
    if lab.empty:
        print("  EMPTY -- the label produced no finite values. Everything downstream is void.")
    else:
        print(f"  n={len(lab):,}  mean={lab.mean():+.5f}  std={lab.std():.5f}  "
              f"min={lab.min():+.4f}  max={lab.max():+.4f}")
        print(f"  quantiles  1%={lab.quantile(.01):+.4f}  50%={lab.quantile(.50):+.4f}  "
              f"99%={lab.quantile(.99):+.4f}")
        print(f"  exact zeros: {(lab == 0).mean():.2%}    |ret|>50%: {(lab.abs() > 0.5).mean():.4%}")
        if lab.std() < 0.005 or lab.std() > 0.30:
            print(f"  ^^ std {lab.std():.4f} is implausible for a 5-day US large-cap return")

    # ---- 2. price adjustment ------------------------------------------------
    print("\n[2] PRICE ADJUSTMENT  (isolated ~-50%/+100% days = unhandled splits)")
    insts = D.instruments(market=args.market)
    px = D.features(insts, ["$close"], start_time="2016-08-01", end_time="2023-12-29",
                    freq="day")
    if px.empty:
        print("  no price rows returned")
    else:
        r = px["$close"].groupby(level="instrument").pct_change()
        r = r.replace([np.inf, -np.inf], np.nan).dropna()
        big = r[r.abs() > 0.35]
        n_names = px.index.get_level_values("instrument").nunique()
        print(f"  names={n_names}  price rows={len(px):,}  daily returns={len(r):,}")
        print(f"  |daily move|>35%: {len(big):,} ({len(big)/max(len(r),1):.3%} of rows), "
              f"across {big.index.get_level_values('instrument').nunique()} names")
        near_split = big[(big < -0.45) & (big > -0.55) | (big > 0.95) & (big < 1.05)]
        print(f"  in the 1:2 / 2:1 split band specifically: {len(near_split):,}")
        if len(near_split) > 20:
            print("  ^^ that many clustered at exact split ratios means adjustment is "
                  "incomplete; Alpha158's ratio features will be corrupted around each one")
        worst = big.abs().groupby(level="instrument").size().sort_values(ascending=False)
        if len(worst):
            print("  worst names: " + ", ".join(f"{i}({int(c)})" for i, c in worst.head(6).items()))

    # ---- 1. in-sample fit: the decisive one ---------------------------------
    print("\n[1] IN-SAMPLE FIT  (does the model rank its own training data?)")
    model = init_instance_by_config(cfg["task"]["model"])
    model.fit(dataset)

    print(f"  {'segment':<8}{'days':>7}{'mean IC':>11}{'ICIR':>9}{'%days>0':>10}")
    print("  " + "-" * 45)
    results = {}
    for seg in SEGMENTS:
        pred = model.predict(dataset, segment=seg)
        label = dataset.prepare(seg, col_set=["label"], data_key="infer").iloc[:, 0]
        df = pd.concat([pred.rename("score"), label.rename("label")], axis=1).dropna()
        if df.empty:
            print(f"  {seg:<8}   no overlapping pred/label rows")
            continue
        arr = ic_series(df)
        mean = arr.mean() if len(arr) else float("nan")
        icir = mean / arr.std(ddof=1) if len(arr) > 1 and arr.std(ddof=1) > 0 else float("nan")
        results[seg] = mean
        print(f"  {seg:<8}{len(arr):>7}{mean:>11.4f}{icir:>9.4f}{(arr > 0).mean():>10.2%}")

    print("\n" + "=" * 74)
    tr, te = results.get("train"), results.get("test")
    if tr is not None and np.isfinite(tr):
        if tr < 0.02:
            print("VERDICT: the model cannot rank its OWN TRAINING DATA (train IC "
                  f"{tr:.4f}).")
            print("  This is not overfitting and not a hard market -- it is a broken input.")
            print("  Look at [2]/[3]/[4] above: feature-label misalignment, unadjusted")
            print("  prices, or too few names per day. Do NOT spend GPU on deep models")
            print("  until train IC is healthy; they will fit the same broken target.")
        elif te is not None and te < 0.01:
            print(f"VERDICT: fits train ({tr:.4f}) but not test ({te:.4f}) -- genuine")
            print("  overfitting or regime break, NOT a data bug. The fix is")
            print("  regularization / shorter horizons / regime conditioning, and a deep")
            print("  model is a reasonable thing to try next.")
        else:
            print(f"VERDICT: train {tr:.4f} / test {te:.4f} -- both healthy.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
