#!/usr/bin/env python3
"""Run the frozen GATE_XS3 wide-universe spec and emit gate metrics as JSON.

Usage (from alltrading/, with the qlib venv):
  edge/.venv-qlib/bin/python edge/tools/qlib_run_wide.py --market pitwide
  edge/.venv-qlib/bin/python edge/tools/qlib_run_wide.py --market allwide

Adapted from edge/tools/qlib_run.py (read-only reference for the mlflow-env
fix and the Newey-West estimator; not imported, not modified). Two things are
new here, both required by edge/docs/GATE_XS3.md:

1. ``IntervalTopkDropoutStrategy`` (below) -- GATE_XS3.md's strategy
   rebalances WEEKLY, not daily, and qlib's stock ``TopkDropoutStrategy`` has
   no rebalance-frequency parameter. This wraps it so every OTHER execution
   assumption (deal price, costs, dropout selection) stays byte-identical to
   a daily TopkDropoutStrategy; only which days it is allowed to act changes.
   Same idea used for reference in edge/tools/qlib_sweep.py (GATE_XS2.md, a
   concurrent experiment -- not touched or imported here, reimplemented
   independently). Declared in THIS file, and the spec YAML's
   ``module_path`` is rewritten to this file's absolute path at load time
   (see ``load_spec``) -- qlib's ``get_module_by_module_path``
   (qlib/utils/mod.py) natively supports a ``.py``-suffixed module_path via
   ``importlib.util.spec_from_file_location``, so this is a supported
   mechanism, not a workaround.
2. Annualized one-way turnover, read from the saved backtest report's
   ``turnover`` column (``portfolio_analysis/report_normal_1day.pkl``, written
   by ``PortAnaRecord``). Qlib's ``report["turnover"]`` is two-way traded
   notional over account value per step; ``* 252 / 2`` gives the one-way
   annualized figure GATE_XS3.md's gate binds on -- the same formula
   edge/tools/qlib_sweep.py uses for GATE_XS2.md, reimplemented here
   independently since that file is a read-only reference, not a dependency.

Why this exists instead of plain ``qrun`` -- same two reasons as qlib_run.py:
the Newey-West IC t-stat GATE_XS3.md binds on (SigAnaRecord does not report
one), and one entry point taking ``--market`` for the two required universes
(pitwide / allwide) rather than a hand-edited second copy of the spec.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# mlflow >=3.x raises on the filesystem tracking backend unless this is set.
# Must run before mlflow is imported -- including transitively, by qlib.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd
import ruamel.yaml as yaml
from qlib.backtest.decision import TradeDecisionWO
from qlib.contrib.strategy import TopkDropoutStrategy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from edge.research.reporting import Figure, GateReportSpec, get_metric, write_gate_doc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
SPEC = EDGE / "qlib_xs3" / "workflow_alpha158_lgb_wide.yaml"
OUTDIR = EDGE / "runs" / "qlib_xs3"
MLRUNS = EDGE / "qlib_xs3" / "mlruns"
THIS_FILE = Path(__file__).resolve()
DOCS = ROOT / "edge" / "docs"

TRADING_DAYS = 252
LABEL_FWD_DAYS = 6  # Ref($close,-6): the IC overlap length, used as the NW lag

# Pre-registered thresholds, GATE_XS3.md section 2 (inherited unchanged from
# GATE_XS.md except turnover, added by GATE_XS2.md as the live-tradeability
# floor). `gate_metrics()` below only ever EXTRACTS numbers off the qlib
# recorder; nothing in this file used to compare them against these bars --
# the "GO" in the retracted GATE_XS3_RESULT.md was not derived from this
# code at all (edge/docs/GATE_XS3_CORRECTION.md; edge/docs/STATUS.md:21).
XS3_KEY_EXCESS_RETURN_WITH_COST = "('excess_return_with_cost', 'annualized_return')"
XS3_KEY_IR_WITH_COST = "('excess_return_with_cost', 'information_ratio')"
XS3_THRESHOLDS = {
    "mean_ic_gte_0020": ("metrics.rank_ic.mean_ic", 0.020, "gte"),
    "rank_icir_gte_020": ("metrics.rank_ic.icir", 0.20, "gte"),
    "nw_tstat_gt_2": ("metrics.rank_ic.t_stat_newey_west", 2.0, "gt"),
    "excess_return_with_cost_gt_0": (
        f"metrics.portfolio.risk.{XS3_KEY_EXCESS_RETURN_WITH_COST}", 0.0, "gt",
    ),
    "post_cost_ir_gt_05": (f"metrics.portfolio.risk.{XS3_KEY_IR_WITH_COST}", 0.5, "gt"),
    "annualized_one_way_turnover_lte_400pct": (
        "metrics.turnover.annualized_one_way", 4.0, "lte",
    ),
}


class IntervalTopkDropoutStrategy(TopkDropoutStrategy):
    """TopkDropoutStrategy that only rebalances every `rebalance_days` steps.

    Wrapping the strategy (rather than resampling the signal) keeps every
    other execution assumption byte-identical to a plain daily
    TopkDropoutStrategy -- deal price, costs, the dropout selection logic.
    The only change is which days it is allowed to act.
    """

    def __init__(self, *args, rebalance_days: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.rebalance_days = int(rebalance_days)

    def generate_trade_decision(self, execute_result=None):
        step = self.trade_calendar.get_trade_step()
        if self.rebalance_days > 1 and step % self.rebalance_days != 0:
            return TradeDecisionWO([], self)
        return super().generate_trade_decision(execute_result)


def _newey_west_tstat(x: np.ndarray, lags: int) -> float:
    """Identical estimator to tools/rank_ic.py and tools/qlib_run.py."""
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


def _find_record(cfg: Dict[str, object], cls_name: str) -> Dict[str, object]:
    for r in cfg["task"]["record"]:
        if r.get("class") == cls_name:
            return r
    raise KeyError(f"record class {cls_name!r} not found in {SPEC}")


def load_spec(market: str) -> Dict[str, object]:
    y = yaml.YAML(typ="safe", pure=True)
    cfg = y.load(SPEC.read_text(encoding="utf-8"))
    cfg["qlib_init"]["provider_uri"] = str(ROOT / cfg["qlib_init"]["provider_uri"])
    # `market` is an anchor referenced by both the handler and the strategy;
    # after safe-load the alias is already expanded, so set every occurrence.
    cfg["market"] = market
    cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["instruments"] = market
    # The custom weekly-rebalance strategy lives in THIS file (qlib has no
    # stock equivalent); point qlib's dynamic loader at this file's absolute
    # path so resolution never depends on cwd or sys.path.
    strat_cfg = _find_record(cfg, "PortAnaRecord")["kwargs"]["config"]["strategy"]
    strat_cfg["module_path"] = str(THIS_FILE)
    return cfg


def gate_metrics(recorder, cfg: Dict[str, object]) -> Dict[str, object]:
    """Pull IC/ICIR/portfolio numbers off the recorder, plus NW t-stat and turnover."""
    out: Dict[str, object] = {}

    out["sig_ana"] = {k: float(v) for k, v in recorder.list_metrics().items() if isinstance(v, (int, float))}

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

    try:
        pa = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
        out["portfolio"] = {
            str(k): {str(kk): float(vv) for kk, vv in v.items()} for k, v in pa.to_dict().items()
        }
    except Exception as exc:  # noqa: BLE001 - report, never fabricate
        out["portfolio_error"] = f"{type(exc).__name__}: {exc}"

    try:
        report = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        tv = report["turnover"].astype(float)
        out["turnover"] = {
            "annualized_one_way": float(tv.mean() * TRADING_DAYS / 2.0),
            "mean_daily_two_way": float(tv.mean()),
            "pct_days_traded": float((tv > 1e-12).mean()),
            "n_backtest_days": int(len(tv)),
        }
    except Exception as exc:  # noqa: BLE001 - report, never fabricate
        out["turnover_error"] = f"{type(exc).__name__}: {exc}"

    return out


_CMP = {
    "gte": lambda value, bar: value >= bar,
    "gt": lambda value, bar: value > bar,
    "lte": lambda value, bar: value <= bar,
    "lt": lambda value, bar: value < bar,
}


def gate_verdict(payload: Dict[str, object]) -> Dict[str, object]:
    """Evaluate GATE_XS3.md's 6 pre-registered criteria against `payload`.

    `gate_metrics()` above only extracts numbers off the qlib recorder -- it
    has never compared them to a threshold or produced a verdict. That gap is
    exactly how GATE_XS3_RESULT.md ended up with a "GO" that was not derived
    from this code at all (GATE_XS3_CORRECTION.md). Every threshold here is
    checked via `reporting.get_metric` against the SAME `payload` dict that
    gets written to `{market}.json` -- if a required metric is missing (e.g.
    `metrics.portfolio_error` fired instead of `metrics.portfolio`), this
    raises (`MetricNotFoundError`) rather than silently treating the gate as
    passed or failed on absent evidence.
    """
    checks: Dict[str, bool] = {}
    values: Dict[str, float] = {}
    for name, (key_path, bar, op) in XS3_THRESHOLDS.items():
        value = float(get_metric(payload, key_path))
        values[name] = value
        checks[name] = bool(_CMP[op](value, bar))
    return {
        "gate_checks": checks,
        "gate_check_values": values,
        "verdict": "GO" if all(checks.values()) else "NO-GO",
        "gate_spec": "edge/docs/GATE_XS3.md",
    }


# ---------------------------------------------------------------------------
# Result doc, rendered from the artifact JSON (edge.research.reporting) --
# not assembled by hand. This is gate path #2, "THE RETRACTED ONE"
# (GATE_XS3_RESULT.md, edge/docs/STATUS.md:21): a document that announced GO
# with figures matching no artifact, including an authorization to unblock
# GPU budget (GATE_XS3_RESULT.md:54) on a result that never happened. Every
# figure below is pulled from the artifact `main()` just wrote via
# `Figure(key_path=...)`; a metric absent from it raises instead of
# rendering.
# ---------------------------------------------------------------------------

XS3_GATE_SPEC = GateReportSpec(
    gate_family="xs3-wide-universe",
    verdict_key_path="verdict",
    figures=(
        Figure("mean_ic", "metrics.rank_ic.mean_ic", "ratio4", "≥ +0.0200",
               "gate_checks.mean_ic_gte_0020"),
        Figure("rank_icir", "metrics.rank_ic.icir", "ratio4", "≥ +0.2000",
               "gate_checks.rank_icir_gte_020"),
        Figure("nw_tstat", "metrics.rank_ic.t_stat_newey_west", "ratio2", "> +2.0000",
               "gate_checks.nw_tstat_gt_2"),
        Figure("excess_return_with_cost",
               f"metrics.portfolio.risk.{XS3_KEY_EXCESS_RETURN_WITH_COST}", "pct",
               "> 0.00%", "gate_checks.excess_return_with_cost_gt_0"),
        Figure("post_cost_ir", f"metrics.portfolio.risk.{XS3_KEY_IR_WITH_COST}", "ratio4",
               "> +0.5000", "gate_checks.post_cost_ir_gt_05"),
        Figure("turnover_one_way", "metrics.turnover.annualized_one_way", "pct1",
               "≤ 400.0%", "gate_checks.annualized_one_way_turnover_lte_400pct"),
        Figure("n_days", "metrics.rank_ic.n_days", "int"),
        Figure("market", "market", "str"),
        Figure("experiment", "experiment", "str"),
        Figure("recorder_id", "recorder_id", "str"),
        Figure("topk", "strategy.topk", "int"),
        Figure("n_drop", "strategy.n_drop", "int"),
        Figure("rebalance_days", "strategy.rebalance_days", "int"),
        Figure("benchmark", "benchmark", "str"),
        Figure("spec", "spec", "str"),
        Figure("generated_utc", "generated_utc", "str"),
    ),
    template=f"""# GATE_XS3 Result — {{market}}

**Rendered**: {{generated_at}}
**Run generated (UTC)**: {{generated_utc}}
**Artifact**: `{{artifact_path}}` (sha256 `{{artifact_hash}}`)
**Experiment**: `{{experiment}}` (recorder `{{recorder_id}}`)
**Verdict**: {{verdict_badge}}

---

## Pre-Registered Criteria vs. Observed Metrics ({{market}})

Every row is pulled from the artifact above by key path (see
`edge/tools/qlib_run_wide.py::XS3_GATE_SPEC`) -- a figure with no such key
cannot appear in this table; the renderer raises instead.

| Criterion | Pre-Registered Hurdle | Observed | Status |
| :--- | :--- | :---: | :---: |
| Mean Rank IC | {{mean_ic_threshold}} | {{mean_ic}} | {{mean_ic_badge}} |
| Rank ICIR | {{rank_icir_threshold}} | {{rank_icir}} | {{rank_icir_badge}} |
| Newey-West t-stat (lags={LABEL_FWD_DAYS}) | {{nw_tstat_threshold}} | {{nw_tstat}} | {{nw_tstat_badge}} |
| Post-cost excess ann. return vs {{benchmark}} | {{excess_return_with_cost_threshold}} | {{excess_return_with_cost}} | {{excess_return_with_cost_badge}} |
| Post-cost Information Ratio | {{post_cost_ir_threshold}} | {{post_cost_ir}} | {{post_cost_ir_badge}} |
| Annualized one-way turnover | {{turnover_one_way_threshold}} | {{turnover_one_way}} | {{turnover_one_way_badge}} |

n_days = {{n_days}}. Strategy: `IntervalTopkDropoutStrategy` topk={{topk}} n_drop={{n_drop}}
rebalance_days={{rebalance_days}}. Spec: `{{spec}}`.

---

## Provenance

This document did not exist as hand-written prose: it is rendered from
`{{artifact_path}}` by `edge.research.reporting.write_gate_doc`, called from
`edge/tools/qlib_run_wide.py::main()` immediately after that file is written.
Re-running `qlib_run_wide.py --market {{market}}` regenerates both the artifact
and this document together, from the same run, every time.
""",
)


def render_xs3_result_doc(artifact_path: Path, *, market: str) -> str:
    """Render this market's GATE_XS3 result doc from the artifact `main()`
    just wrote. Raises if any declared figure is absent from it."""
    doc_path = DOCS / f"GATE_XS3_RESULT_{market}.md"
    content = write_gate_doc(artifact_path=artifact_path, spec=XS3_GATE_SPEC, doc_path=doc_path)
    print(f"wrote {doc_path.relative_to(ROOT)}")
    return content


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", default="pitwide", help="instrument universe (pitwide | allwide)")
    ap.add_argument("--exp", default=None, help="experiment name (default: qlib_xs3_<market>)")
    args = ap.parse_args(argv)

    cfg = load_spec(args.market)
    exp_name = args.exp or f"qlib_xs3_{args.market}"

    import qlib
    from qlib.model.trainer import task_train

    MLRUNS.mkdir(parents=True, exist_ok=True)
    qlib.init(**cfg["qlib_init"], exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {"uri": MLRUNS.as_uri(), "default_exp_name": "Experiment"},
    })

    strat_kwargs = _find_record(cfg, "PortAnaRecord")["kwargs"]["config"]["strategy"]["kwargs"]
    print(f"market   : {args.market}")
    print(f"segments : {cfg['task']['dataset']['kwargs']['segments']}")
    print(f"benchmark: {cfg['benchmark']}")
    print(f"strategy : topk={strat_kwargs['topk']} n_drop={strat_kwargs['n_drop']} rebalance_days={strat_kwargs['rebalance_days']}")

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
        "strategy": {
            "class": "IntervalTopkDropoutStrategy",
            "topk": strat_kwargs["topk"],
            "n_drop": strat_kwargs["n_drop"],
            "rebalance_days": strat_kwargs["rebalance_days"],
        },
        "trial_count_vs_test_segment": 1,
        "metrics": metrics,
    }
    # Computed from `payload` itself (not from live Python objects), so the
    # verdict written to disk is derived the same way a later, independent
    # render of the doc would re-derive it -- see gate_verdict()'s docstring.
    payload.update(gate_verdict(payload))

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
    if "turnover" in metrics:
        print(f"  turnover (annualized one-way): {metrics['turnover']['annualized_one_way']:.2%}")
    elif "turnover_error" in metrics:
        print(f"  turnover: {metrics['turnover_error']}")
    print(f"\nwrote {out.relative_to(ROOT)}")

    print(f"\n  verdict: {payload['verdict']}  (checks: {payload['gate_checks']})")
    render_xs3_result_doc(out, market=args.market)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
