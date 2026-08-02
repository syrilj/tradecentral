#!/usr/bin/env python3
"""Turnover / universe sweep for edge/docs/GATE_XS2.md.

Two phases, and the wall between them is enforced here rather than trusted:

  selection    36 configs (2 universes x 3 rebalance x 3 topk x 2 n_drop),
               evaluated on 2022-01-18 -> 2023-12-29. Asserts that no date on
               or after 2024-01-01 is read (GATE_XS2.md rule 4).
  confirmation ONE config, named on the command line, run twice -- 5y train
               (primary) and expanding train (control) -- on 2024-01-16 ->
               2026-07-29.

The learner is identical to the frozen GATE_XS.md spec: LightGBM on Alpha158
with CSRankNorm and the upstream benchmark hyperparameters. Nothing about model
capacity is swept. Only *execution* is: how often the book rebalances, how wide
it is, and which universe it ranks over.

Efficiency note: rebalance / topk / n_drop do not touch the model, so the fit
happens once per (universe, phase, train-window) and all backtest variants run
against the same cached predictions. 36 configs cost 2 fits, not 36.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/qlib_sweep.py --phase selection
  edge/.venv-qlib/bin/python edge/tools/qlib_sweep.py --phase selection --universe pit30
  edge/.venv-qlib/bin/python edge/tools/qlib_sweep.py --phase confirmation \\
      --universe pit30 --rebalance 5 --topk 20 --n-drop 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
PROVIDER = EDGE / "data" / "qlib_us_1d"
OUTDIR = EDGE / "runs" / "qlib_xs2"

BENCHMARK = "SPY"
TRADING_DAYS = 252
LABEL_FWD_DAYS = 6          # Ref($close,-6): IC overlap length, and the NW lag
COST_BPS_PER_SIDE = 0.0005  # 5bp each way = 10bp round trip, as in GATE_XS.md

# --- Frozen segments (GATE_XS2.md). Do not edit without a new gate file. ------
SEGMENTS = {
    "selection": {
        "expanding": {
            "train": ["2016-08-01", "2021-06-30"],
            "valid": ["2021-07-16", "2021-12-31"],
            "test": ["2022-01-18", "2023-12-29"],
        },
    },
    "confirmation": {
        # 5y arm is PRIMARY -- the gate binds on it. Declared in GATE_XS2.md
        # before any run, because the deployment intent is the current regime.
        "5y": {
            "train": ["2018-07-02", "2023-06-30"],
            "valid": ["2023-07-17", "2023-12-29"],
            "test": ["2024-01-16", "2026-07-29"],
        },
        # Expanding arm is the CONTROL. Reported alongside, never instead.
        "expanding": {
            "train": ["2016-08-01", "2023-06-30"],
            "valid": ["2023-07-17", "2023-12-29"],
            "test": ["2024-01-16", "2026-07-29"],
        },
    },
}

# Qlib's TradeCalendarManager.get_step_time reads calendar_index + 1 on every
# step, so a backtest ending on the final calendar day raises IndexError. Same
# mechanical one-day trim as GATE_XS.md; IC is still measured over the full test
# segment, only the portfolio simulation stops a day early.
BACKTEST_END_TRIM = {"2026-07-29": "2026-07-28"}

# --- Frozen grid (GATE_XS2.md): 2 x 3 x 3 x 2 = 36 --------------------------
UNIVERSES = ["xs40", "pit30"]
REBALANCE_DAYS = [1, 5, 21]
TOPK = [10, 20, 30]
N_DROP = [2, 5]

# Upstream Alpha158 LightGBM benchmark values, unchanged from GATE_XS.md.
LGB_KWARGS = dict(
    loss="mse",
    colsample_bytree=0.8879,
    learning_rate=0.2,
    subsample=0.8789,
    lambda_l1=205.6999,
    lambda_l2=580.9768,
    max_depth=8,
    num_leaves=210,
    num_threads=8,
)


# --- IC estimators: identical to tools/qlib_run.py so numbers are comparable --

def _newey_west_tstat(x: np.ndarray, lags: int) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    var = (e @ e) / n
    for lag in range(1, min(lags, n - 1) + 1):
        var += 2.0 * (1.0 - lag / (lags + 1.0)) * ((e[lag:] @ e[:-lag]) / n)
    if var <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(var / n))


def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    ra, rb = a.rank(), b.rank()
    sa, sb = ra.std(), rb.std()
    if not np.isfinite(sa) or not np.isfinite(sb) or sa == 0 or sb == 0:
        return float("nan")
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb) * len(a) / (len(a) - 1))


def rank_ic_metrics(pred: pd.Series, label: pd.Series) -> Dict[str, float]:
    df = pd.concat([pred.rename("score"), label.rename("label")], axis=1).dropna()
    ics = []
    for _, g in df.groupby(level="datetime"):
        if len(g) >= 5:
            ic = _spearman(g["score"], g["label"])
            if np.isfinite(ic):
                ics.append(ic)
    arr = np.asarray(ics, dtype=float)
    if not len(arr):
        return {"n_days": 0}
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else float("nan")
    icir = mean / std if std and np.isfinite(std) and std > 0 else float("nan")
    return {
        "n_days": int(len(arr)),
        "mean_rank_ic": mean,
        "std_rank_ic": std,
        "rank_icir": float(icir),
        "t_stat_naive": float(icir * np.sqrt(len(arr))) if np.isfinite(icir) else float("nan"),
        "t_stat_newey_west": _newey_west_tstat(arr, lags=LABEL_FWD_DAYS),
        "pct_days_positive": float((arr > 0).mean()),
    }


# --- Model / dataset ---------------------------------------------------------

def build_and_fit(universe: str, seg: Dict[str, List[str]]):
    """Fit the frozen learner once. Returns (model, dataset, predictions, label)."""
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data.dataset import DatasetH

    handler = Alpha158(
        instruments=universe,
        start_time=seg["train"][0],
        end_time=seg["test"][1],
        fit_start_time=seg["train"][0],
        fit_end_time=seg["train"][1],
        infer_processors=[
            {"class": "RobustZScoreNorm",
             "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[
            {"class": "DropnaLabel"},
            # The point of the experiment: ranks the label across the
            # cross-section each day, so the model cannot express "everything
            # goes up". Unchanged from GATE_XS.md.
            {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
        ],
        label=["Ref($close, -6) / Ref($close, -1) - 1"],
    )
    dataset = DatasetH(handler=handler, segments={k: tuple(v) for k, v in seg.items()})

    model = LGBModel(**LGB_KWARGS)
    model.fit(dataset)

    pred = model.predict(dataset, segment="test")
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]

    raw_label = dataset.prepare(
        "test", col_set="label", data_key="raw"
    )  # raw: un-CSRankNorm'd forward return, so IC is against real returns
    label = raw_label.iloc[:, 0] if isinstance(raw_label, pd.DataFrame) else raw_label

    return model, dataset, pred.rename("score"), label.rename("label")


# --- Backtest: qlib's own engine, with an N-day rebalance wrapper -------------

def _interval_strategy_cls():
    """TopkDropoutStrategy that only trades every `rebalance_days` steps.

    Wrapping the strategy (rather than resampling the signal) keeps every other
    execution assumption byte-identical to GATE_XS.md -- deal price, costs, the
    dropout selection logic. The only change is which days it is allowed to act.
    """
    from qlib.backtest.decision import TradeDecisionWO
    from qlib.contrib.strategy import TopkDropoutStrategy

    class IntervalTopkDropoutStrategy(TopkDropoutStrategy):
        def __init__(self, *args, rebalance_days: int = 1, **kwargs):
            super().__init__(*args, **kwargs)
            self.rebalance_days = int(rebalance_days)

        def generate_trade_decision(self, execute_result=None):
            step = self.trade_calendar.get_trade_step()
            if self.rebalance_days > 1 and step % self.rebalance_days != 0:
                return TradeDecisionWO([], self)
            return super().generate_trade_decision(execute_result)

    return IntervalTopkDropoutStrategy


def run_backtest(
    pred: pd.Series, seg: Dict[str, List[str]],
    rebalance: int, topk: int, n_drop: int,
) -> Dict[str, object]:
    from qlib.backtest import backtest as normal_backtest
    from qlib.contrib.evaluate import risk_analysis

    start = seg["test"][0]
    end = BACKTEST_END_TRIM.get(seg["test"][1], seg["test"][1])

    strategy = _interval_strategy_cls()(
        signal=pred, topk=topk, n_drop=n_drop, rebalance_days=rebalance,
    )
    portfolio_metric, _indicator = normal_backtest(
        start_time=start, end_time=end, strategy=strategy,
        executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                  "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}},
        account=100000, benchmark=BENCHMARK,
        exchange_kwargs={
            "deal_price": "close",
            "open_cost": COST_BPS_PER_SIDE,
            "close_cost": COST_BPS_PER_SIDE,
            "min_cost": 0,
        },
    )
    report, _positions = portfolio_metric["1day"]

    out: Dict[str, object] = {}
    for key, series in (
        ("excess_return_without_cost", report["return"] - report["bench"]),
        ("excess_return_with_cost", report["return"] - report["bench"] - report["cost"]),
    ):
        stats = risk_analysis(series, freq="day")["risk"].to_dict()
        out[key] = {str(k): float(v) for k, v in stats.items()}

    # Turnover. qlib's `turnover` column is traded notional over account value
    # per step, counting both legs; the gate is written on the one-way number.
    tv = report["turnover"].astype(float)
    out["turnover"] = {
        "annualized_one_way": float(tv.mean() * TRADING_DAYS / 2.0),
        "mean_daily_two_way": float(tv.mean()),
        "pct_days_traded": float((tv > 1e-12).mean()),
    }
    out["max_drawdown_with_cost"] = float(
        ((1 + (report["return"] - report["cost"])).cumprod() /
         (1 + (report["return"] - report["cost"])).cumprod().cummax() - 1).min()
    )
    out["n_backtest_days"] = int(len(report))
    return out


# --- Phases ------------------------------------------------------------------

def assert_selection_wall(seg: Dict[str, List[str]]) -> None:
    """GATE_XS2.md rule 4, enforced rather than trusted."""
    for name, (lo, hi) in seg.items():
        for d in (lo, hi):
            if pd.Timestamp(d) >= pd.Timestamp("2024-01-01"):
                raise AssertionError(
                    f"selection phase touched the confirmation segment: "
                    f"{name}={d}. Forbidden by GATE_XS2.md rule 4."
                )


def evaluate(universe: str, arm: str, seg: Dict[str, List[str]],
             grid: List[Tuple[int, int, int]]) -> List[Dict[str, object]]:
    t0 = time.time()
    print(f"\n=== fit: universe={universe} arm={arm} "
          f"train={seg['train'][0]}..{seg['train'][1]} ===", flush=True)
    _model, _dataset, pred, label = build_and_fit(universe, seg)
    ic = rank_ic_metrics(pred, label)
    print(f"    fit {time.time() - t0:.0f}s | rank IC {ic.get('mean_rank_ic', float('nan')):.4f} "
          f"ICIR {ic.get('rank_icir', float('nan')):.3f} "
          f"NW t {ic.get('t_stat_newey_west', float('nan')):.2f} "
          f"({ic.get('n_days')} days)", flush=True)

    rows: List[Dict[str, object]] = []
    for rebalance, topk, n_drop in grid:
        t1 = time.time()
        row: Dict[str, object] = {
            "universe": universe, "arm": arm, "rebalance_days": rebalance,
            "topk": topk, "n_drop": n_drop, "rank_ic": ic,
            "segments": {k: list(v) for k, v in seg.items()},
        }
        try:
            row.update(run_backtest(pred, seg, rebalance, topk, n_drop))
            ir = row["excess_return_with_cost"]["information_ratio"]
            ann = row["excess_return_with_cost"]["annualized_return"]
            to = row["turnover"]["annualized_one_way"]
            print(f"    rb={rebalance:<2} topk={topk:<2} drop={n_drop} | "
                  f"IR {ir:+.3f} | excess {ann:+.2%} | turnover {to:.0%} | "
                  f"{time.time() - t1:.0f}s", flush=True)
        except Exception as exc:  # noqa: BLE001 - record, never fabricate
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"    rb={rebalance:<2} topk={topk:<2} drop={n_drop} | ERROR {exc}", flush=True)
        rows.append(row)
    return rows


def select_winner(rows: List[Dict[str, object]], turnover_cap: float) -> Optional[Dict[str, object]]:
    """GATE_XS2.md selection rule, applied in the pre-registered order."""
    ok = [r for r in rows if "error" not in r
          and r["turnover"]["annualized_one_way"] <= turnover_cap]
    if not ok:
        return None
    ok.sort(key=lambda r: -r["excess_return_with_cost"]["information_ratio"])
    best_ir = ok[0]["excess_return_with_cost"]["information_ratio"]
    near = [r for r in ok if best_ir - r["excess_return_with_cost"]["information_ratio"] <= 0.02]
    near.sort(key=lambda r: r["turnover"]["annualized_one_way"])
    return near[0]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=["selection", "confirmation"], default="selection")
    ap.add_argument("--universe", default=None, help="restrict to one universe")
    ap.add_argument("--rebalance", type=int, default=None, help="confirmation: selected value")
    ap.add_argument("--topk", type=int, default=None, help="confirmation: selected value")
    ap.add_argument("--n-drop", type=int, default=None, help="confirmation: selected value")
    ap.add_argument("--turnover-cap", type=float, default=4.0, help="annualized one-way, GATE_XS2.md")
    ap.add_argument("--out", default=None, help="output JSON path")
    ap.add_argument("--smoke", action="store_true", help="one config only, for timing")
    args = ap.parse_args(argv)

    import qlib
    qlib.init(provider_uri=str(PROVIDER), region="us")

    universes = [args.universe] if args.universe else UNIVERSES
    rows: List[Dict[str, object]] = []

    if args.phase == "selection":
        seg = SEGMENTS["selection"]["expanding"]
        assert_selection_wall(seg)
        grid = ([(REBALANCE_DAYS[0], TOPK[0], N_DROP[0])] if args.smoke
                else list(product(REBALANCE_DAYS, TOPK, N_DROP)))
        print(f"selection phase | {len(universes)} universes x {len(grid)} backtests "
              f"= {len(universes) * len(grid)} configs | {len(universes)} model fits")
        for u in universes:
            rows.extend(evaluate(u, "expanding", seg, grid))
    else:
        missing = [n for n, v in (("--rebalance", args.rebalance), ("--topk", args.topk),
                                  ("--n-drop", args.n_drop)) if v is None]
        if missing or not args.universe:
            print(f"confirmation requires --universe and {', '.join(missing) or 'the selected params'}",
                  file=sys.stderr)
            return 2
        grid = [(args.rebalance, args.topk, args.n_drop)]
        for arm in ("5y", "expanding"):  # primary first, control second
            rows.extend(evaluate(args.universe, arm, SEGMENTS["confirmation"][arm], grid))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUTDIR / f"{args.phase}.json"
    payload: Dict[str, object] = {
        "gate": "edge/docs/GATE_XS2.md",
        "phase": args.phase,
        "n_configs": len(rows),
        "cost_bps_round_trip": COST_BPS_PER_SIDE * 2 * 1e4,
        "results": rows,
    }

    if args.phase == "selection" and not args.smoke:
        winner = select_winner(rows, args.turnover_cap)
        payload["turnover_cap_annualized_one_way"] = args.turnover_cap
        payload["winner"] = (
            None if winner is None else
            {k: winner[k] for k in ("universe", "rebalance_days", "topk", "n_drop")}
        )
        print("\n" + "=" * 68)
        if winner is None:
            print(f"NO config survived the {args.turnover_cap:.0%} turnover filter.")
            print("GATE_XS2.md selection rule step 4: verdict NO-GO, "
                  "confirmation segment NOT touched.")
        else:
            print(f"SELECTED: universe={winner['universe']} "
                  f"rebalance={winner['rebalance_days']}d "
                  f"topk={winner['topk']} n_drop={winner['n_drop']}")
            print(f"  selection-window IR (post-cost) "
                  f"{winner['excess_return_with_cost']['information_ratio']:+.3f}")
            print(f"  annualized one-way turnover "
                  f"{winner['turnover']['annualized_one_way']:.0%}")
        print("=" * 68)

    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(ROOT) if ROOT in out_path.parents else out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
