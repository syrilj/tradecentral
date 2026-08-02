#!/usr/bin/env python3
"""Model-class benchmark on the wide universe — the run GATE_XS3_RESULT.md authorized.

GATE_XS3_RESULT.md section 4 unblocked exactly one thing: "deep Qlib
architectures (ALSTM, GATs, TRA, HIST) trained on the wide universe, evaluated
against LightGBM". This is that run. It changes the MODEL and nothing else --
universe, handler, label, costs, strategy, and segments all carry over
byte-identical from edge/qlib_xs3/workflow_alpha158_lgb_wide.yaml.

WHAT IS AND IS NOT TUNED HERE
-----------------------------
Every hyperparameter below is an upstream qlib benchmark value, copied from
edge/.qlib-src/examples/benchmarks/*/workflow_config_*_Alpha158.yaml without
modification. They were chosen by qlib's authors on CSI300, on Chinese equities,
years before this dataset existed. Nothing in this file was searched against any
window of the US wide data. Trial count against the confirmation segment stays
at 1 per arm, which is what GATE_XS4.md binds on.

THE FEATURE-SET CONFOUND, AND THE CONTROL FOR IT
------------------------------------------------
Upstream's Alpha158 configs for the sequence models do NOT feed all 158
features. They prepend a `FilterCol` processor selecting 20 named columns and
set `d_feat: 20`. LightGBM's upstream Alpha158 config uses all 158. So a naive
"ALSTM vs LGB" comparison confounds model class with feature count.

This runner therefore ships a `lgb20` arm: the frozen LightGBM spec run on the
exact same 20 columns the deep arms see. Reading the three-way result:

    alstm > lgb20 and alstm > lgb158  ->  the sequence model is doing real work
    alstm > lgb20 but alstm < lgb158  ->  the 138 dropped features mattered more
                                          than the architecture did
    alstm ~ lgb20 ~ lgb158            ->  model class is not the binding
                                          constraint; stop spending GPU on it

PHASES
------
dev      test 2022-01-18..2023-12-29. This is the window GATE_XS3 already spent
         its single look on, so it is no longer virgin and cannot be un-spent.
         That makes it the correct place to SELECT among arms -- selection on a
         window you never intend to confirm on is the whole point.
confirm  test 2024-01-16..2026-07-29. GATE_XS3.md line: "deliberately NOT used
         here and is reserved as a future confirmation set -- to be spent, if at
         all, under a new gate, and only once." That gate is GATE_XS4.md. Run
         this phase once, with the single arm dev selected, and never again.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/qlib_deep_wide.py --phase dev --arms lgb158,lgb20
  edge/.venv-qlib/bin/python edge/tools/qlib_deep_wide.py --phase dev --arms all
  edge/.venv-qlib/bin/python edge/tools/qlib_deep_wide.py --phase confirm --arms alstm
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

# mlflow >=3.x raises on the filesystem tracking backend unless this is set.
# Must run before mlflow is imported -- including transitively, by qlib.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

# torch ships its own libomp; LightGBM loads a second OpenMP runtime into the
# same process. On macOS that combination segfaults (SIGSEGV, exit 139) the
# moment the sequence arms start their first epoch -- with n_jobs=0 too, so it
# is not a DataLoader-worker problem. Must be set before torch is imported.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
OUTDIR = EDGE / "runs" / "qlib_xs4"
MLRUNS = EDGE / "qlib_xs4" / "mlruns"

sys.path.insert(0, str(EDGE / "tools"))
# Reused, not reimplemented: the Newey-West estimator, the Spearman IC, the
# recorder->metrics extraction, and IntervalTopkDropoutStrategy all live in
# qlib_run_wide.py and produced the GATE_XS3 numbers. Importing them is what
# makes XS4's metrics comparable to XS3's rather than merely similar-looking.
# NOTE: load_spec() rewrites the strategy module_path to qlib_run_wide.py's
# absolute path, which is where IntervalTopkDropoutStrategy is defined. Do not
# "fix" that to point here.
from qlib_run_wide import gate_metrics, load_spec, _find_record  # noqa: E402

# --- Segments, locked. dev mirrors GATE_XS3.md exactly. ----------------------
# confirm's train/valid end before 2024-01 with a >=10-trading-day purge gap
# ahead of the test segment; the label reads 6 days forward, so contiguous
# splits would leak across the boundary.
PHASES: Dict[str, Dict[str, object]] = {
    "dev": {
        "segments": {
            "train": ["2016-08-01", "2021-06-30"],
            "valid": ["2021-07-16", "2021-12-31"],
            "test": ["2022-01-18", "2023-12-29"],
        },
        "handler_end": "2023-12-29",
        "fit_end": "2021-06-30",
        "backtest": ["2022-01-18", "2023-12-28"],
    },
    "confirm": {
        "segments": {
            "train": ["2016-08-01", "2023-06-30"],
            "valid": ["2023-07-17", "2023-12-29"],
            "test": ["2024-01-16", "2026-07-29"],
        },
        "handler_end": "2026-07-29",
        "fit_end": "2023-06-30",
        "backtest": ["2024-01-16", "2026-07-28"],
    },
}

# Upstream's 20-column Alpha158 subset, verbatim from
# examples/benchmarks/ALSTM/workflow_config_alstm_Alpha158.yaml. Same list in
# the GRU / LSTM / Transformer configs. Order preserved.
FILTER_COL_20 = [
    "RESI5", "WVMA5", "RSQR5", "KLEN", "RSQR10", "CORR5", "CORD5", "CORR10",
    "ROC60", "RESI10", "VSTD5", "RSQR60", "CORR60", "WVMA60", "STD5",
    "RSQR20", "CORD60", "CORD10", "CORR20", "KLOW",
]

# Frozen GATE_XS.md/XS3.md LightGBM hyperparameters. Unchanged.
LGB_KWARGS = {
    "loss": "mse",
    "colsample_bytree": 0.8879,
    "learning_rate": 0.2,
    "subsample": 0.8789,
    "lambda_l1": 205.6999,
    "lambda_l2": 580.9768,
    "max_depth": 8,
    "num_leaves": 210,
    "num_threads": 8,
}

# Same learner, a training configuration that actually trains.
#
# WHY THIS EXISTS. edge/tools/audit_wide_data.py showed the frozen config above
# early-stops at **best_iteration = 1** on this dataset:
#
#   [20]  train's l2: 0.970287   valid's l2: 1.00446
#   Early stopping, best iteration is:
#   [1]   train's l2: 0.995266   valid's l2: 0.998057
#
# Validation loss is worse at round 20 than at round 1, so the model qlib
# carried into the XS3 backtest was a single boosting round. GATE_XS3 therefore
# did not test universe breadth; it tested an untrained model, and its +0.0052
# IC measures nothing about the hypothesis it was written for.
#
# The frozen values are upstream's CSI300 tuning: lambda_l1=205.7 and
# lambda_l2=581 are enormous against a CSRankNorm'd label whose variance is 1 by
# construction (note train l2 ~0.995 -- the model is barely moving off the
# mean), and lr=0.2 with 210 leaves diverges on validation before the shrinkage
# can help. Those three interact; none of them was chosen for this data.
#
# This is a BUG FIX, not tuning-for-a-better-number: the change being made is
# "let the model complete more than one boosting round". It is still a change to
# a frozen spec, so it may only be evaluated on the DEV window, and the trial
# count is recorded. See GATE_XS4.md rule 6.
LGB_TRAINABLE_KWARGS = {
    "loss": "mse",
    "colsample_bytree": 0.8879,
    "subsample": 0.8789,
    "learning_rate": 0.02,     # was 0.2 -- shrinkage the early stop can see
    "lambda_l1": 1.0,          # was 205.6999 -- scaled to a unit-variance label
    "lambda_l2": 10.0,         # was 580.9768
    "max_depth": 8,
    "num_leaves": 64,          # was 210 -- 210 leaves on ~450 names/day overfits
    "num_threads": 8,
    # NOTE: these two are named constructor args on qlib's LGBModel
    # (gbdt.py:19), NOT LightGBM params. Spelling them `early_stop` puts them in
    # self.params, where LightGBM silently ignores them and the 50-round default
    # stays in force -- which is how best_iteration=1 survives a "fix".
    "early_stopping_rounds": 200,  # 50 rounds at lr 0.02 is ~5 rounds at lr 0.2
    "num_boost_round": 2000,       # lr 0.02 needs ~10x the rounds lr 0.2 does
}

# Shared upstream sequence-model settings. n_jobs and GPU are the only two
# fields this runner overrides, and only for machine shape -- see build_cfg().
_SEQ_COMMON = {
    "d_feat": 20,
    "hidden_size": 64,
    "num_layers": 2,
    "dropout": 0.0,
    "n_epochs": 200,
    "early_stop": 10,
    "batch_size": 800,
    "metric": "loss",
    "loss": "mse",
    "seed": 0,
}

ARMS: Dict[str, Dict[str, object]] = {
    "lgb158": {
        "kind": "tabular",
        "filter_col": None,          # all 158 features -- the GATE_XS3 incumbent
        "model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt",
                  "kwargs": dict(LGB_KWARGS)},
        "note": "GATE_XS3 frozen baseline, reproduced. The number to beat.",
    },
    "lgb20": {
        "kind": "tabular",
        "filter_col": FILTER_COL_20,  # control for the feature-set confound
        "model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt",
                  "kwargs": dict(LGB_KWARGS)},
        "note": "Same learner as lgb158 on the deep arms' 20 columns. Isolates "
                "model class from feature count.",
    },
    "lgb158_fit": {
        "kind": "tabular",
        "filter_col": None,
        "model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt",
                  "kwargs": dict(LGB_TRAINABLE_KWARGS)},
        "note": "lgb158 with a training config that survives past round 1. "
                "DEV ONLY -- tests whether XS3's null was an artifact of "
                "best_iteration=1 rather than a real absence of signal.",
    },
    "lgb20_fit": {
        "kind": "tabular",
        "filter_col": FILTER_COL_20,
        "model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt",
                  "kwargs": dict(LGB_TRAINABLE_KWARGS)},
        "note": "lgb158_fit on the deep arms' 20 columns. DEV ONLY.",
    },
    "alstm": {
        "kind": "sequence",
        "filter_col": FILTER_COL_20,
        "model": {"class": "ALSTM", "module_path": "qlib.contrib.model.pytorch_alstm_ts",
                  "kwargs": dict(_SEQ_COMMON, lr=1e-3, rnn_type="GRU")},
        "note": "Upstream ALSTM Alpha158 benchmark values, unchanged.",
    },
    "gru": {
        "kind": "sequence",
        "filter_col": FILTER_COL_20,
        "model": {"class": "GRU", "module_path": "qlib.contrib.model.pytorch_gru_ts",
                  "kwargs": dict(_SEQ_COMMON, lr=2e-4)},
        "note": "Upstream GRU Alpha158 benchmark values, unchanged.",
    },
    "lstm": {
        "kind": "sequence",
        "filter_col": FILTER_COL_20,
        "model": {"class": "LSTM", "module_path": "qlib.contrib.model.pytorch_lstm_ts",
                  "kwargs": dict(_SEQ_COMMON, lr=1e-3)},
        "note": "Upstream LSTM Alpha158 benchmark values, unchanged.",
    },
    "transformer": {
        "kind": "sequence",
        "filter_col": FILTER_COL_20,
        "model": {"class": "TransformerModel",
                  "module_path": "qlib.contrib.model.pytorch_transformer_ts",
                  "kwargs": {"seed": 0}},
        "note": "Upstream Transformer Alpha158 benchmark: library defaults, seed 0.",
    },
}

STEP_LEN = 20  # TSDatasetH lookback, upstream default for the Alpha158 configs

# --- Forward horizon --------------------------------------------------------
# GATE_XS4_DEV.md section 6 named the horizon as the most directly implicated
# untested axis: every gate in this project has predicted the SAME 6-day-forward
# return, and all of them closed NO-GO. Price-derived features have their
# strongest published support at 1-2 days, which no gate here has ever tried.
#
# The -1 leg is what keeps today's close out of today's decision, and it does
# not move. Only the far leg changes:
#
#   Ref($close, -2) / Ref($close, -1) - 1   1 trading day forward
#   Ref($close, -3) / Ref($close, -1) - 1   2 trading days forward
#   Ref($close, -6) / Ref($close, -1) - 1   5 trading days forward (all gates to date)
#
# `nw_lag` is the IC overlap length and must track the horizon: overlapping
# forward returns autocorrelate, and a Newey-West lag shorter than the overlap
# understates the standard error and inflates the t-stat. This is the single
# easiest way to manufacture a fake result, so it is derived here, not chosen.
#
# Segment dates are deliberately NOT changed. The existing >=10-trading-day
# purge gaps are more than sufficient for a 1-2 day label (they were sized for
# 5), and holding the splits fixed keeps every horizon directly comparable to
# the GATE_XS3/XS4 numbers.
HORIZONS: Dict[int, Dict[str, object]] = {
    1: {"label": ["Ref($close, -2) / Ref($close, -1) - 1"], "nw_lag": 2},
    2: {"label": ["Ref($close, -3) / Ref($close, -1) - 1"], "nw_lag": 3},
    5: {"label": ["Ref($close, -6) / Ref($close, -1) - 1"], "nw_lag": 6},
}


def build_cfg(arm: str, market: str, phase: str, n_jobs: int, gpu: int,
              horizon: int = 5) -> Dict[str, object]:
    """Start from the frozen GATE_XS3 spec and change only model + dataset shape."""
    spec = ARMS[arm]
    cfg = load_spec(market)                      # provider_uri, strategy path, market
    ph = PHASES[phase]

    handler_kwargs = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    handler_kwargs["end_time"] = ph["handler_end"]
    handler_kwargs["fit_end_time"] = ph["fit_end"]
    handler_kwargs["label"] = list(HORIZONS[horizon]["label"])

    # FilterCol must run BEFORE RobustZScoreNorm so the z-scores are fit on the
    # surviving columns only -- which is the order upstream uses.
    if spec["filter_col"]:
        handler_kwargs["infer_processors"] = [
            {"class": "FilterCol",
             "kwargs": {"fields_group": "feature", "col_list": list(spec["filter_col"])}},
        ] + list(handler_kwargs["infer_processors"])

    cfg["task"]["model"] = copy.deepcopy(spec["model"])
    if spec["kind"] == "sequence":
        # n_jobs and GPU are machine shape, not modelling choices: upstream's
        # n_jobs=20 / GPU=0 assume their box, not a Vertex worker.
        cfg["task"]["model"]["kwargs"]["n_jobs"] = n_jobs
        cfg["task"]["model"]["kwargs"]["GPU"] = gpu
        cfg["task"]["dataset"]["class"] = "TSDatasetH"
        cfg["task"]["dataset"]["kwargs"]["step_len"] = STEP_LEN

    cfg["task"]["dataset"]["kwargs"]["segments"] = copy.deepcopy(ph["segments"])

    bt = _find_record(cfg, "PortAnaRecord")["kwargs"]["config"]["backtest"]
    bt["start_time"], bt["end_time"] = ph["backtest"]

    return cfg


def init_qlib(market: str) -> None:
    """One qlib.init for the whole run; every arm shares provider_uri and region.

    Points the MLflow experiment manager at edge/qlib_xs4/mlruns so XS4's
    recorders never land in XS3's store.
    """
    import qlib

    cfg = load_spec(market)
    MLRUNS.mkdir(parents=True, exist_ok=True)
    qlib.init(**cfg["qlib_init"], exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {"uri": MLRUNS.as_uri(), "default_exp_name": "Experiment"},
    })


def run_arm(arm: str, market: str, phase: str, n_jobs: int, gpu: int,
            horizon: int = 5) -> Dict[str, object]:
    from qlib.model.trainer import task_train

    cfg = build_cfg(arm, market, phase, n_jobs, gpu, horizon)
    exp_name = f"qlib_xs4_{phase}_{market}_{arm}_h{horizon}"

    # gate_metrics() reads its Newey-West lag from qlib_run_wide's module-level
    # LABEL_FWD_DAYS, which is hard-coded to 6 for the 5-day label. Rebind it so
    # the lag tracks the horizon actually being fit -- see HORIZONS.
    import qlib_run_wide
    qlib_run_wide.LABEL_FWD_DAYS = int(HORIZONS[horizon]["nw_lag"])

    print("=" * 70)
    print(f"ARM {arm}  |  market={market}  phase={phase}")
    print(f"  {ARMS[arm]['note']}")
    print(f"  model    : {cfg['task']['model']['class']} "
          f"({cfg['task']['model']['module_path']})")
    print(f"  features : {len(ARMS[arm]['filter_col']) if ARMS[arm]['filter_col'] else 158}")
    print(f"  dataset  : {cfg['task']['dataset']['class']}"
          + (f" step_len={STEP_LEN}" if ARMS[arm]["kind"] == "sequence" else ""))
    print(f"  horizon  : {horizon}d  label={cfg['task']['dataset']['kwargs']['handler']['kwargs']['label'][0]}  NW lag={HORIZONS[horizon]['nw_lag']}")
    print(f"  segments : {cfg['task']['dataset']['kwargs']['segments']}")
    print("=" * 70)

    t0 = time.time()
    recorder = task_train(cfg["task"], experiment_name=exp_name)
    metrics = gate_metrics(recorder, cfg)
    elapsed = time.time() - t0

    strat = _find_record(cfg, "PortAnaRecord")["kwargs"]["config"]["strategy"]["kwargs"]
    return {
        "arm": arm,
        "horizon_days": horizon,
        "label": cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["label"],
        "nw_lag": int(HORIZONS[horizon]["nw_lag"]),
        "kind": ARMS[arm]["kind"],
        "note": ARMS[arm]["note"],
        "model_class": cfg["task"]["model"]["class"],
        "model_kwargs": cfg["task"]["model"]["kwargs"],
        "n_features": len(ARMS[arm]["filter_col"]) if ARMS[arm]["filter_col"] else 158,
        "dataset_class": cfg["task"]["dataset"]["class"],
        "step_len": STEP_LEN if ARMS[arm]["kind"] == "sequence" else None,
        "market": market,
        "phase": phase,
        "segments": cfg["task"]["dataset"]["kwargs"]["segments"],
        "strategy": {"class": "IntervalTopkDropoutStrategy", **{
            k: strat[k] for k in ("topk", "n_drop", "rebalance_days")}},
        "experiment": exp_name,
        "recorder_id": getattr(recorder, "id", None),
        "elapsed_sec": round(elapsed, 1),
        "metrics": metrics,
    }


def port_stat(metrics: Dict[str, object], block: str, field: str) -> Optional[float]:
    """Pull one number out of qlib's port-analysis frame.

    gate_metrics() stores it as ``{"risk": {"('excess_return_with_cost',
    'information_ratio')": 0.71, ...}}`` -- the MultiIndex rows survive
    ``to_dict()`` as *stringified tuples*, so a plain nested lookup silently
    misses and reports n/a for metrics that are actually present.
    """
    risk = (metrics.get("portfolio") or {}).get("risk") or {}
    val = risk.get(f"('{block}', '{field}')")
    return float(val) if isinstance(val, (int, float)) else None


def summarize(results: List[Dict[str, object]]) -> None:
    """One table, the six GATE_XS3 criteria, so arms are directly comparable."""
    print("\n" + "=" * 96)
    print(f"{'arm':<14}{'h':>3}{'feat':>5}{'IC':>9}{'ICIR':>8}{'NW t':>8}"
          f"{'exc.ret':>10}{'IR':>8}{'turnover':>10}{'sec':>8}")
    print("-" * 96)
    for r in results:
        if "error" in r:
            print(f"{r['arm']:<14}{'':>5}  FAILED: {r['error'][:60]}")
            continue
        m = r["metrics"]
        ric = m.get("rank_ic", {})
        turn = m.get("turnover", {})

        def f(v, spec=".4f"):
            return format(v, spec) if isinstance(v, (int, float)) else "n/a"

        print(f"{r['arm']:<14}{r.get('horizon_days', 5):>3}{r['n_features']:>5}"
              f"{f(ric.get('mean_ic')):>9}{f(ric.get('icir')):>8}"
              f"{f(ric.get('t_stat_newey_west'), '.3f'):>8}"
              f"{f(port_stat(m, 'excess_return_with_cost', 'annualized_return')):>10}"
              f"{f(port_stat(m, 'excess_return_with_cost', 'information_ratio'), '.3f'):>8}"
              f"{f(turn.get('annualized_one_way'), '.3f'):>10}"
              f"{r['elapsed_sec']:>8.0f}")
    print("=" * 96)
    print("Gate bars (GATE_XS4.md, carried from GATE_XS3.md): IC>=0.02  ICIR>=0.20")
    print("  NW t>2.0  exc.ret>0  IR>0.5  turnover<=4.00")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=sorted(PHASES), default="dev",
                    help="dev selects among arms; confirm spends the reserved window ONCE")
    ap.add_argument("--arms", default="lgb158,lgb20,alstm,gru",
                    help="comma-separated arm names, or 'all'")
    ap.add_argument("--market", default="pitwide", help="pitwide | allwide")
    ap.add_argument("--horizon", type=int, choices=sorted(HORIZONS), default=5,
                    help="forward return horizon in trading days (default 5, as in all gates to date)")
    ap.add_argument("--n-jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1),
                    help="dataloader workers for the sequence arms")
    ap.add_argument("--gpu", type=int, default=None,
                    help="CUDA device index; -1 forces CPU. Default: autodetect")
    ap.add_argument("--out", default=None, help="output JSON path")
    ap.add_argument("--keep-going", action="store_true",
                    help="record a failing arm and continue to the next one")
    args = ap.parse_args(argv)

    arms = sorted(ARMS) if args.arms == "all" else [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print(f"unknown arm(s): {', '.join(unknown)}. known: {', '.join(sorted(ARMS))}",
              file=sys.stderr)
        return 2

    needs_torch = any(ARMS[a]["kind"] == "sequence" for a in arms)

    gpu = args.gpu
    if gpu is None:
        # Import torch ONLY when a sequence arm needs it. On macOS, importing
        # torch loads its bundled libomp; LightGBM then loads a second OpenMP
        # runtime into the same process and the fit segfaults (SIGSEGV, exit
        # 139). A tabular-only run must never touch torch.
        if not needs_torch:
            gpu = -1
        else:
            try:
                import torch
                gpu = 0 if torch.cuda.is_available() else -1
            except ImportError:
                gpu = -1
    if gpu < 0 and needs_torch:
        print("note: sequence arms will train on CPU (no CUDA device visible).")

    if args.phase == "confirm":
        print("!" * 70)
        print("CONFIRM PHASE. This spends the 2024-01-16..2026-07-29 window that")
        print("GATE_XS3.md reserved. It is a ONE-TIME look. Per GATE_XS4.md there")
        print("is no re-run, no re-tune, and no second arm after this.")
        print("!" * 70)
        if len(arms) > 1:
            print(f"refusing: confirm takes exactly ONE arm, got {len(arms)}: {', '.join(arms)}",
                  file=sys.stderr)
            return 2

    OUTDIR.mkdir(parents=True, exist_ok=True)
    init_qlib(args.market)

    results: List[Dict[str, object]] = []
    for arm in arms:
        try:
            results.append(run_arm(arm, args.market, args.phase, args.n_jobs, gpu,
                                   args.horizon))
        except Exception as exc:  # noqa: BLE001 - a dead arm must not eat the others
            traceback.print_exc()
            results.append({"arm": arm, "error": f"{type(exc).__name__}: {exc}"})
            if not args.keep_going:
                break

    summarize(results)

    out_path = Path(args.out) if args.out else OUTDIR / f"{args.phase}_{args.market}_h{args.horizon}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "gate": "edge/docs/GATE_XS4.md",
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "phase": args.phase,
        "market": args.market,
        "horizon_days": args.horizon,
        "label": HORIZONS[args.horizon]["label"],
        "arms_run": arms,
        "cost_bps_round_trip": 10.0,
        "trial_count_vs_confirm_segment": 1 if args.phase == "confirm" else 0,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_path}")

    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
