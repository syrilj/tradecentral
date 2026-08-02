#!/usr/bin/env python3
"""Run the frozen cross-sectional spec and emit GATE_XS.md metrics as JSON.

Usage (from alltrading/, with the qlib venv):
  edge/.venv-qlib/bin/python edge/tools/qlib_run.py --market xs47
  edge/.venv-qlib/bin/python edge/tools/qlib_run.py --market xs40

Why this exists instead of plain ``qrun``
-----------------------------------------
Two reasons, both gate requirements rather than preference:

1. GATE_XS.md binds on a **Newey-West** IC t-stat. ``SigAnaRecord`` reports IC,
   ICIR, Rank IC and Rank ICIR but no autocorrelation-robust t-stat, and with a
   6-day forward label the IC series is autocorrelated -- the naive t-stat is
   optimistic. That correction is computed here from the saved predictions,
   using the same estimator as tools/rank_ic.py so the number is comparable to
   the v90_wide null.
2. The gate requires every metric reported on **two** universes (xs47 / xs40).
   One entry point that takes ``--market`` makes that a parameter rather than a
   second hand-edited copy of the spec that could silently drift.

The spec itself is untouched: the YAML is the single source of truth and is
loaded verbatim apart from ``provider_uri`` (resolved to an absolute path) and
``market`` (the universe under test).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# mlflow >=3.x raises on the filesystem tracking backend unless this is set.
# Qlib's recorder (load_object / list_metrics) is written against the file
# store, so opting out keeps qlib on its tested path and keeps every artifact
# self-contained under edge/qlib_xs/mlruns/. Set before mlflow is imported.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd
import ruamel.yaml as yaml

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
SPEC = EDGE / "qlib_xs" / "workflow_alpha158_lgb.yaml"
OUTDIR = EDGE / "runs" / "qlib_xs"

TRADING_DAYS = 252
LABEL_FWD_DAYS = 6  # Ref($close,-6): the IC overlap length, used as the NW lag


def _newey_west_tstat(x: np.ndarray, lags: int) -> float:
    """Identical estimator to tools/rank_ic.py, so the numbers are comparable."""
    n = len(x)
    if n < 3:
        return float("nan")
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for lag in range(1, min(lags, n - 1) + 1):
        cov = (e[lag:] @ e[:-lag]) / n
        var += 2.0 * (1.0 - lag / (lags + 1.0)) * cov
    if var <= 0:
        return float("nan")
    return float(mu / np.sqrt(var / n))


def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = a.rank(), b.rank()
    sa, sb = ra.std(), rb.std()
    if not np.isfinite(sa) or not np.isfinite(sb) or sa == 0 or sb == 0:
        return float("nan")
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb) * len(a) / (len(a) - 1))


def load_spec(market: str) -> Dict[str, object]:
    y = yaml.YAML(typ="safe", pure=True)
    cfg = y.load(SPEC.read_text(encoding="utf-8"))
    cfg["qlib_init"]["provider_uri"] = str(ROOT / cfg["qlib_init"]["provider_uri"])
    # `market` is an anchor referenced by both the handler and the strategy;
    # after safe-load the alias is already expanded, so set every occurrence.
    cfg["market"] = market
    cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"] = market
    return cfg


def gate_metrics(recorder, cfg: Dict[str, object]) -> Dict[str, object]:
    """Pull IC/ICIR/portfolio numbers off the recorder and add the NW t-stat."""
    out: Dict[str, object] = {}

    # SigAnaRecord's own metrics (IC, ICIR, Rank IC, Rank ICIR).
    out["sig_ana"] = {k: float(v) for k, v in recorder.list_metrics().items() if isinstance(v, (int, float))}

    # Recompute Rank IC from raw predictions so the NW correction is available
    # and so the reported IC is verifiably the same series the t-stat uses.
    pred = recorder.load_object("pred.pkl")
    label = recorder.load_object("label.pkl")
    df = pd.concat([pred.iloc[:, 0].rename("score"), label.iloc[:, 0].rename("label")], axis=1).dropna()

    ics: List[float] = []
    for _, g in df.groupby(level="datetime"):
        if len(g) >= 5:
            ic = _spearman(g["score"], g["label"])
            if np.isfinite(ic):
                ics.append(ic)

    arr = np.asarray(ics, dtype=float)
    mean = float(arr.mean()) if len(arr) else float("nan")
    std = float(arr.std(ddof=1)) if len(arr) > 1 else float("nan")
    icir = mean / std if std and np.isfinite(std) and std > 0 else float("nan")
    out["rank_ic"] = {
        "n_days": int(len(arr)),
        "mean_ic": mean,
        "std_ic": std,
        "icir": icir,
        "t_stat_naive": float(icir * np.sqrt(len(arr))) if np.isfinite(icir) else float("nan"),
        "t_stat_newey_west": _newey_west_tstat(arr, lags=LABEL_FWD_DAYS),
        "pct_days_positive": float((arr > 0).mean()) if len(arr) else float("nan"),
    }

    # Portfolio analysis, with cost.
    try:
        pa = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
        out["portfolio"] = {
            str(k): {str(kk): float(vv) for kk, vv in v.items()} for k, v in pa.to_dict().items()
        }
    except Exception as exc:  # noqa: BLE001 - report, never fabricate
        out["portfolio_error"] = f"{type(exc).__name__}: {exc}"

    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", default="xs47", help="instrument universe (xs47 | xs40)")
    ap.add_argument("--exp", default=None, help="experiment name (default: qlib_xs_<market>)")
    args = ap.parse_args(argv)

    cfg = load_spec(args.market)
    exp_name = args.exp or f"qlib_xs_{args.market}"

    import qlib
    from qlib.model.trainer import task_train

    qlib.init(**cfg["qlib_init"], exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {"uri": (EDGE / "qlib_xs" / "mlruns").as_uri(), "default_exp_name": "Experiment"},
    })

    print(f"market   : {args.market}")
    print(f"segments : {cfg['task']['dataset']['kwargs']['segments']}")
    print(f"benchmark: {cfg['benchmark']}")

    recorder = task_train(cfg["task"], experiment_name=exp_name)

    metrics = gate_metrics(recorder, cfg)
    payload = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "market": args.market,
        "experiment": exp_name,
        "recorder_id": getattr(recorder, "id", None),
        "spec": str(SPEC.relative_to(ROOT)),
        "segments": cfg["task"]["dataset"]["kwargs"]["segments"],
        "benchmark": cfg["benchmark"],
        "label": cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["label"],
        "trial_count_vs_test_segment": 1,
        "metrics": metrics,
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{args.market}.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    ric = metrics["rank_ic"]
    print(f"\n--- {args.market} ---")
    print(f"  mean Rank IC : {ric['mean_ic']:+.5f}")
    print(f"  Rank ICIR    : {ric['icir']:+.4f}")
    print(f"  t (naive)    : {ric['t_stat_naive']:+.2f}")
    print(f"  t (NW)       : {ric['t_stat_newey_west']:+.2f}")
    print(f"  days IC>0    : {ric['pct_days_positive']:.1%} over {ric['n_days']:,} days")
    for k, v in sorted(metrics.get("sig_ana", {}).items()):
        print(f"  {k:<20} {v:+.6f}")
    if "portfolio" in metrics:
        for group, vals in metrics["portfolio"].items():
            print(f"  [{group}] " + "  ".join(f"{k}={v:+.4f}" for k, v in vals.items()))
    elif "portfolio_error" in metrics:
        print(f"  portfolio: {metrics['portfolio_error']}")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
