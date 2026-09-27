#!/usr/bin/env python3
"""Closed-loop feedback iteration for the deep-scan ordinal ranker.

Closes the gap between one-shot train/val (``train_qlib_scan_lgb``) and ad-hoc
OOS scoring (``eval_qlib_scan_accuracy``):

  1. Score **champion** on preregistered OOS as-of dates (never used for fit).
  2. Sliding-window Rank-IC stability (drift / regime concentration).
  3. Optionally train a **challenger** with later train/val windows into a
     side directory (does not overwrite champion unless ``--promote``).
  4. Score challenger on the *same* OOS as-ofs.
  5. Apply preregistered gates → promote / hold decision.
  6. Write append-only report under ``runs/qlib_scan_iterate/``.

Quant rules
-----------
* Terminal OOS as-ofs are never used to retune leaves / LR / features.
* Promote only copies artifacts after gates pass; never sets ENTER auth.
* ``--promote`` is fail-closed: refuses if decision.promote is false.

Usage
-----
  # Monitor only (champion OOS + window stability)
  PYTHONPATH=.. python3 tools/iterate_qlib_scan.py

  # Train challenger (train→2024-06, val 2024-H2) then gate on 2025+ OOS
  PYTHONPATH=.. python3 tools/iterate_qlib_scan.py --train-challenger \\
      --challenger-train-end 2024-06-28 \\
      --challenger-val-start 2024-07-01 \\
      --challenger-val-end 2024-12-31

  # Copy challenger → models/qlib_scan_lgb only if gates pass
  PYTHONPATH=.. python3 tools/iterate_qlib_scan.py --train-challenger --promote

Research ordinal only — not ENTER authorization.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EDGE_DIR = Path(__file__).resolve().parents[1]
ROOT = EDGE_DIR.parent

if "edge" not in sys.modules:
    _m = types.ModuleType("edge")
    _m.__path__ = [str(EDGE_DIR)]
    sys.modules["edge"] = _m

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))

from edge.research.qlib_scan_feedback import (  # noqa: E402
    FeedbackGates,
    build_iteration_report,
    decide_promotion,
    expanding_oos_windows,
    snapshot_from_eval,
    summarize_window_ics,
)
from edge.tools.eval_qlib_scan_accuracy import (  # noqa: E402
    DEFAULT_ASOFS,
    DEFAULT_DATA,
    DEFAULT_ONE_WAY_COST_BPS,
    DEFAULT_TOP_N,
    FORWARD_DAYS,
    evaluate,
    recent_friday_asofs,
)

CHAMPION_DIR = EDGE_DIR / "models" / "qlib_scan_lgb"
DEFAULT_ITER_ROOT = EDGE_DIR / "runs" / "qlib_scan_iterate"


def _load_champion_source_id(model_dir: Path) -> str:
    prov = model_dir / "PROVENANCE.json"
    if not prov.is_file():
        return "qlib_scan_lgb_v2"
    try:
        data = json.loads(prov.read_text(encoding="utf-8"))
    except Exception:
        return "qlib_scan_lgb_v2"
    return str(data.get("source_id") or "qlib_scan_lgb_v2")


def _run_eval(
    *,
    asofs: list[str],
    max_symbols: int,
    horizon: int,
    data_dirs: tuple[Path, ...],
    top_n: int,
    cost_bps: float,
    model_dir: Path | None = None,
) -> dict[str, Any]:
    return evaluate(
        asofs=asofs,
        max_symbols=max_symbols,
        horizon=horizon,
        data_dirs=data_dirs,
        top_n=top_n,
        one_way_cost_bps=cost_bps,
        model_dir=model_dir,
    )


def _window_stability(
    asofs: list[str],
    *,
    max_symbols: int,
    horizon: int,
    data_dirs: tuple[Path, ...],
    top_n: int,
    cost_bps: float,
    window: int,
    model_dir: Path | None = None,
) -> dict[str, Any]:
    windows = expanding_oos_windows(asofs, window=window, step=1)
    means: list[float | None] = []
    detail: list[dict[str, Any]] = []
    for win in windows:
        result = _run_eval(
            asofs=list(win),
            max_symbols=max_symbols,
            horizon=horizon,
            data_dirs=data_dirs,
            top_n=top_n,
            cost_bps=cost_bps,
            model_dir=model_dir,
        )
        ic = result.get("qlib_mean_rank_ic")
        means.append(float(ic) if ic is not None else None)
        detail.append({
            "asofs": list(win),
            "qlib_mean_rank_ic": ic,
            "augmented_mean_rank_ic": result.get("augmented_mean_rank_ic"),
            "activity_mean_rank_ic": result.get("activity_mean_rank_ic"),
            "n_ic_days_qlib": result.get("n_ic_days_qlib"),
        })
    return {
        "window_size": window,
        "windows": detail,
        "summary": summarize_window_ics(means),
    }


def _train_challenger(
    *,
    out_dir: Path,
    max_symbols: int,
    data_dirs: tuple[Path, ...],
    train_end: str,
    val_start: str,
    val_end: str,
    source_id: str,
    seed: int,
) -> dict[str, Any]:
    from edge.tools.train_qlib_scan_lgb import train as train_scan

    return train_scan(
        max_symbols=max_symbols,
        data_dirs=data_dirs,
        out_dir=out_dir,
        seed=seed,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        source_id=source_id,
    )


def _promote_artifacts(challenger_dir: Path, champion_dir: Path) -> list[str]:
    champion_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in (
        "model.txt",
        "PROVENANCE.json",
        "metrics.json",
        "sklearn_model.joblib",
        "linear_weights.npz",
    ):
        src = challenger_dir / name
        if not src.is_file():
            continue
        dst = champion_dir / name
        shutil.copy2(src, dst)
        copied.append(name)
    # Invalidate in-process cache so subsequent default loads see new files.
    try:
        import edge.daily_plays.qlib_scan_score as score_mod

        score_mod.load_lgb_scorer(champion_dir, force_reload=True)
    except Exception:
        pass
    return copied


def run_iteration(
    *,
    asofs: list[str],
    max_symbols: int,
    horizon: int,
    data_dirs: tuple[Path, ...],
    top_n: int,
    cost_bps: float,
    window: int,
    train_challenger: bool,
    challenger_dir: Path,
    champion_dir: Path,
    challenger_train_end: str,
    challenger_val_start: str,
    challenger_val_end: str,
    challenger_source_id: str,
    seed: int,
    gates: FeedbackGates,
    do_promote: bool,
    iter_root: Path,
) -> dict[str, Any]:
    iteration_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"iteration_id={iteration_id}")
    print(f"oos_asofs={asofs}")

    # ── 1. Champion OOS ──────────────────────────────────────────────────
    champ_src = _load_champion_source_id(champion_dir)
    print(f"scoring champion source_id={champ_src} dir={champion_dir}")
    champion_eval = _run_eval(
        asofs=asofs,
        max_symbols=max_symbols,
        horizon=horizon,
        data_dirs=data_dirs,
        top_n=top_n,
        cost_bps=cost_bps,
        model_dir=champion_dir,
    )
    champion_snap = snapshot_from_eval(champion_eval, source_id=champ_src)
    print(
        f"champion RankIC={champion_snap.mean_rank_ic} "
        f"aug={champion_snap.augmented_mean_rank_ic} "
        f"paper_net={champion_snap.paper_net_mean} "
        f"n_ic={champion_snap.n_ic_days}"
    )

    # ── 2. Window stability (champion, no retrain) ───────────────────────
    print(f"window stability size={window}")
    stability = _window_stability(
        asofs,
        max_symbols=max_symbols,
        horizon=horizon,
        data_dirs=data_dirs,
        top_n=top_n,
        cost_bps=cost_bps,
        window=window,
        model_dir=champion_dir,
    )
    print(f"window_summary={stability.get('summary')}")

    # ── 3. Optional challenger train + OOS ───────────────────────────────
    train_meta: dict[str, Any] | None = None
    challenger_eval: dict[str, Any] | None = None
    decision = None

    if train_challenger:
        print(
            f"training challenger train_end={challenger_train_end} "
            f"val={challenger_val_start}→{challenger_val_end} → {challenger_dir}"
        )
        train_meta = _train_challenger(
            out_dir=challenger_dir,
            max_symbols=max_symbols,
            data_dirs=data_dirs,
            train_end=challenger_train_end,
            val_start=challenger_val_start,
            val_end=challenger_val_end,
            source_id=challenger_source_id,
            seed=seed,
        )
        print(f"scoring challenger dir={challenger_dir}")
        challenger_eval = _run_eval(
            asofs=asofs,
            max_symbols=max_symbols,
            horizon=horizon,
            data_dirs=data_dirs,
            top_n=top_n,
            cost_bps=cost_bps,
            model_dir=challenger_dir,
        )
        challenger_snap = snapshot_from_eval(
            challenger_eval, source_id=challenger_source_id,
        )
        print(
            f"challenger RankIC={challenger_snap.mean_rank_ic} "
            f"aug={challenger_snap.augmented_mean_rank_ic} "
            f"paper_net={challenger_snap.paper_net_mean} "
            f"n_ic={challenger_snap.n_ic_days}"
        )
        decision = decide_promotion(
            challenger=challenger_snap,
            champion=champion_snap,
            gates=gates,
        )
        print(f"promote={decision.promote} reasons={list(decision.reasons)}")
    else:
        # Monitor-only: treat champion as the unit under test vs absolute floors
        # + activity baseline (no champion-vs-self regression check).
        decision = decide_promotion(
            challenger=champion_snap,
            champion=None,
            gates=gates,
        )
        print(
            f"monitor_only gates_pass={decision.promote} "
            f"reasons={list(decision.reasons)}"
        )

    # ── 4. Optional promote ──────────────────────────────────────────────
    promote_result: dict[str, Any] | None = None
    if do_promote:
        if not train_challenger:
            raise SystemExit("--promote requires --train-challenger")
        if decision is None or not decision.promote:
            promote_result = {
                "copied": False,
                "reason": "gates_failed",
                "decision_reasons": list(decision.reasons) if decision else [],
            }
            print("PROMOTE REFUSED: gates failed (fail-closed)")
        else:
            copied = _promote_artifacts(challenger_dir, champion_dir)
            promote_result = {
                "copied": True,
                "files": copied,
                "from": str(challenger_dir),
                "to": str(champion_dir),
            }
            print(f"PROMOTED files={copied} → {champion_dir}")

    # ── 5. Persist report ────────────────────────────────────────────────
    report = build_iteration_report(
        champion_eval=champion_eval,
        challenger_eval=challenger_eval,
        decision=decision,
        window_summary=stability,
        train_meta=train_meta,
        iteration_id=iteration_id,
    )
    report["promote_action"] = promote_result
    report["gates"] = gates.to_dict()
    report["champion_dir"] = str(champion_dir)
    report["challenger_dir"] = str(challenger_dir) if train_challenger else None

    iter_root.mkdir(parents=True, exist_ok=True)
    out_path = iter_root / f"{iteration_id}.json"
    latest = iter_root / "latest.json"
    text = json.dumps(report, indent=2, default=str) + "\n"
    out_path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"wrote {latest}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-symbols", type=int, default=180)
    ap.add_argument("--horizon", type=int, default=FORWARD_DAYS)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_ONE_WAY_COST_BPS)
    ap.add_argument(
        "--asofs",
        default=",".join(DEFAULT_ASOFS),
        help="Comma-separated terminal OOS as-of dates (never used for fit)",
    )
    ap.add_argument(
        "--recent",
        action="store_true",
        help="Use last ~6 Fridays with forward-return room instead of --asofs",
    )
    ap.add_argument(
        "--window",
        type=int,
        default=3,
        help="Sliding window size (number of as-ofs) for stability check",
    )
    ap.add_argument(
        "--train-challenger",
        action="store_true",
        help="Train a challenger into --challenger-dir with later windows",
    )
    ap.add_argument(
        "--challenger-dir",
        type=Path,
        default=EDGE_DIR / "models" / "qlib_scan_lgb_challenger",
    )
    ap.add_argument("--champion-dir", type=Path, default=CHAMPION_DIR)
    ap.add_argument("--challenger-train-end", default="2024-06-28")
    ap.add_argument("--challenger-val-start", default="2024-07-01")
    ap.add_argument("--challenger-val-end", default="2024-12-31")
    ap.add_argument("--challenger-source-id", default="qlib_scan_lgb_v3_challenger")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--promote",
        action="store_true",
        help="Copy challenger → champion only if preregistered gates pass",
    )
    ap.add_argument("--iter-root", type=Path, default=DEFAULT_ITER_ROOT)
    # Gate knobs (preregister — set intentionally, not tuned on OOS)
    ap.add_argument("--min-oos-rank-ic", type=float, default=0.0)
    ap.add_argument("--max-ic-regression", type=float, default=0.005)
    ap.add_argument("--max-paper-regression", type=float, default=0.001)
    ap.add_argument("--min-oos-ic-days", type=int, default=3)
    ap.add_argument("--min-paper-periods", type=int, default=3)
    ap.add_argument(
        "--activity-mode",
        choices=("augmented", "pure"),
        default="augmented",
    )
    args = ap.parse_args(argv)

    data_dirs = tuple(p for p in DEFAULT_DATA if p.is_dir())
    if not data_dirs:
        print("ERROR: no local daily data dirs found", file=sys.stderr)
        return 2

    if args.recent:
        asofs = recent_friday_asofs(
            data_dirs=data_dirs, n=6, horizon=int(args.horizon),
        )
    else:
        asofs = [s.strip() for s in str(args.asofs).split(",") if s.strip()]
    if not asofs:
        print("ERROR: no OOS as-of dates", file=sys.stderr)
        return 2

    gates = FeedbackGates(
        min_oos_rank_ic=float(args.min_oos_rank_ic),
        max_rank_ic_regression_vs_champion=float(args.max_ic_regression),
        max_paper_net_regression=float(args.max_paper_regression),
        min_oos_ic_days=int(args.min_oos_ic_days),
        min_paper_periods=int(args.min_paper_periods),
        activity_compare_mode=str(args.activity_mode),
    )

    report = run_iteration(
        asofs=asofs,
        max_symbols=int(args.max_symbols),
        horizon=int(args.horizon),
        data_dirs=data_dirs,
        top_n=int(args.top_n),
        cost_bps=float(args.cost_bps),
        window=int(args.window),
        train_challenger=bool(args.train_challenger),
        challenger_dir=Path(args.challenger_dir),
        champion_dir=Path(args.champion_dir),
        challenger_train_end=str(args.challenger_train_end),
        challenger_val_start=str(args.challenger_val_start),
        challenger_val_end=str(args.challenger_val_end),
        challenger_source_id=str(args.challenger_source_id),
        seed=int(args.seed),
        gates=gates,
        do_promote=bool(args.promote),
        iter_root=Path(args.iter_root),
    )

    summary = {
        "iteration_id": report.get("iteration_id"),
        "promote": (report.get("promotion") or {}).get("promote"),
        "reasons": (report.get("promotion") or {}).get("reasons"),
        "promote_action": report.get("promote_action"),
        "champion_rank_ic": (report.get("champion_eval") or {}).get("qlib_mean_rank_ic"),
        "challenger_rank_ic": (
            (report.get("challenger_eval") or {}).get("qlib_mean_rank_ic")
            if report.get("challenger_eval") else None
        ),
        "window_summary": (report.get("window_stability") or {}).get("summary"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
