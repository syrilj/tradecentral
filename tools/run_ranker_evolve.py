#!/usr/bin/env python3
"""Evolve deep-scan ranker recipes with multi-parent survival-of-the-fittest.

Fitness is sealed to pre-holdout as-ofs. Terminal holdout is never used for
selection — only an optional fail-closed promote gate after evolution.

Examples:
  # Fast smoke (CI / preflight) — synthetic fitness, ≥2 generations
  PYTHONPATH=.. python3 edge/tools/run_ranker_evolve.py --smoke

  # Larger synthetic search
  PYTHONPATH=.. python3 edge/tools/run_ranker_evolve.py --pop 24 --gens 5 --seed 42

Research ordinal only — decision_authorized is always false.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.ga.ranker_evolve import (  # noqa: E402
    DEFAULT_RANKER_GA_DIR,
    RankerEvolveConfig,
    run_ranker_evolution,
    smoke_ranker_evolution,
    synthetic_fitness_fn,
)
from edge.research.ga.ranker_protocol import RankerEvolutionProtocol  # noqa: E402
from edge.research.ga.ranker_real_fitness import (  # noqa: E402
    real_fitness_fn,
    terminal_eval_recipe,
)
from edge.research.qlib_scan_feedback import (  # noqa: E402
    FeedbackGates,
    OosSnapshot,
    decide_promotion,
    snapshot_from_eval,
)


def _demo_terminal_eval(recipe, *, seed: int = 0) -> dict:
    """Smoke-only terminal snapshot (does not train models).

    Produces a structured eval-like payload so the promote path is exercised
    without LightGBM. Never used during population fitness ranking.
    """
    from edge.research.ga.ranker_evolve import synthetic_fitness_fn
    from edge.research.ga.ranker_protocol import RankerEvolutionProtocol

    # Intentionally score on terminal dates only inside this demo helper.
    proto = RankerEvolutionProtocol()
    # Build a one-off fitness report shape for snapshot_from_eval
    # Use a hash-based IC so promote is not hard-coded true/false.
    syn = synthetic_fitness_fn(recipe, proto, seed=seed + 99)
    ic = float(syn["metrics"]["fitness_mean_rank_ic"]) * 0.9
    act = ic * 0.5
    return {
        "source_id": f"demo_terminal_{recipe.fingerprint()}",
        "qlib_mean_rank_ic": ic,
        "activity_mean_rank_ic": act,
        "augmented_mean_rank_ic": 0.55 * act + 0.45 * ic,
        "qlib_augmented_non_worse_than_activity": True,
        "qlib_pure_non_worse_than_activity": ic >= act,
        "n_ic_days_qlib": len(proto.terminal_holdout_asofs),
        "asofs": list(proto.terminal_holdout_asofs),
        "horizon_days": 5,
        "symbols_loaded": recipe.max_symbols,
        "schema_version": "qlib-scan-accuracy-v1",
        "paper_portfolio": {
            "augmented": {
                "net": {
                    "mean": ic * 0.12,
                    "n_periods": len(proto.terminal_holdout_asofs),
                }
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="Tiny deterministic multi-gen run")
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--gens", type=int, default=4)
    ap.add_argument("--elite-frac", type=float, default=0.25)
    ap.add_argument("--mutation-rate", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_RANKER_GA_DIR)
    ap.add_argument("--run-id", type=str, default=None)
    ap.add_argument(
        "--attempt-promote",
        action="store_true",
        help="After evolution, run fail-closed terminal gate on best elite",
    )
    ap.add_argument(
        "--real",
        action="store_true",
        help="Train real LightGBM recipes; fitness on sealed 2024 asofs only",
    )
    ap.add_argument("--boost-rounds", type=int, default=200, help="LGB trees when --real")
    ap.add_argument("--eval-symbols", type=int, default=100, help="Max symbols for fitness eval")
    ap.add_argument("--no-confirmation", action="store_true")
    args = ap.parse_args(argv)

    def progress(msg: str) -> None:
        print(f"[ga_ranker] {msg}", flush=True)

    if args.smoke and not args.real:
        result = smoke_ranker_evolution(
            output_dir=args.output_dir,
            seed=int(args.seed),
            run_id=args.run_id,
        )
        # Optional promote path on smoke elite with demo terminal eval
        if args.attempt_promote and result.elites:
            from edge.research.ga.ranker_recipe import RankerRecipe

            elite = result.elites[0]
            recipe = RankerRecipe.from_mapping(elite["recipe"])
            term = _demo_terminal_eval(recipe, seed=int(args.seed))
            challenger = snapshot_from_eval(term)
            # Weak champion so gates can pass without hardcoding promote=True
            champion = OosSnapshot(
                source_id="demo_champion",
                mean_rank_ic=0.0,
                activity_mean_rank_ic=0.0,
                augmented_mean_rank_ic=0.0,
                non_worse_than_activity=True,
                pure_non_worse_than_activity=True,
                n_ic_days=5,
                paper_net_mean=0.0,
                paper_n_periods=5,
            )
            decision = decide_promotion(
                challenger=challenger,
                champion=champion,
                gates=FeedbackGates(min_oos_ic_days=3, min_paper_periods=3),
            )
            promo = {
                "attempted": True,
                "mode": "smoke_demo_terminal",
                "elite_id": elite["id"],
                "decision": decision.to_dict(),
                "promote": decision.promote,
                "decision_authorized": False,
            }
            # Persist promote sidecar
            run_dir = Path(args.output_dir) / result.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "promotion.json").write_text(
                json.dumps(promo, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            )
            result.promotion = promo
    else:
        seed = int(args.seed)
        protocol = RankerEvolutionProtocol()
        if args.real:
            # Prefer smaller recipes for wall-clock: clamp eval symbols; training
            # still follows each recipe's max_symbols (menus include 80+).
            def fitness_fn(recipe, proto, _seed=seed, _br=int(args.boost_rounds), _es=int(args.eval_symbols)):
                return real_fitness_fn(
                    recipe,
                    proto,
                    seed=_seed,
                    num_boost_round=_br,
                    max_eval_symbols=_es,
                    quiet=True,
                )

            def term_fn(recipe, _proto=protocol, _seed=seed, _es=int(args.eval_symbols)):
                return terminal_eval_recipe(
                    recipe, _proto, seed=_seed, max_eval_symbols=_es,
                )

            # Load champion OOS snapshot for non-regression (terminal only)
            champion_snap = None
            try:
                from edge.tools.eval_qlib_scan_accuracy import evaluate
                from pathlib import Path as _P

                champ_dir = EDGE_ROOT / "models" / "qlib_scan_lgb"
                data_dirs = tuple(
                    p for p in (EDGE_ROOT / "data" / "1d_wide", EDGE_ROOT / "data" / "1d")
                    if p.is_dir()
                )
                if champ_dir.is_dir() and data_dirs:
                    progress("scoring champion on terminal holdout (baseline)")
                    champ_eval = evaluate(
                        asofs=list(protocol.terminal_holdout_asofs),
                        max_symbols=int(args.eval_symbols),
                        horizon=5,
                        data_dirs=data_dirs,
                        model_dir=champ_dir,
                    )
                    champion_snap = snapshot_from_eval(champ_eval)
                    progress(
                        f"champion RankIC={champion_snap.mean_rank_ic} "
                        f"paper={champion_snap.paper_net_mean}"
                    )
            except Exception as exc:  # noqa: BLE001
                progress(f"champion baseline skipped: {exc}")

            result = run_ranker_evolution(
                protocol=protocol,
                config=RankerEvolveConfig(
                    population_size=int(args.pop),
                    n_generations=int(args.gens),
                    elite_fraction=float(args.elite_frac),
                    mutation_rate=float(args.mutation_rate),
                    random_state=seed,
                    run_confirmation=False,  # real confirmation is terminal promote
                    attempt_promote=bool(args.attempt_promote),
                ),
                fitness_fn=fitness_fn,
                output_dir=args.output_dir,
                run_id=args.run_id,
                progress=progress,
                champion_snapshot=champion_snap,
                terminal_eval_fn=term_fn if args.attempt_promote else None,
                gates=FeedbackGates(
                    min_oos_ic_days=3,
                    min_paper_periods=3,
                    max_rank_ic_regression_vs_champion=0.0,
                    max_paper_net_regression=0.0,
                ),
            )
        else:
            result = run_ranker_evolution(
                protocol=protocol,
                config=RankerEvolveConfig(
                    population_size=int(args.pop),
                    n_generations=int(args.gens),
                    elite_fraction=float(args.elite_frac),
                    mutation_rate=float(args.mutation_rate),
                    random_state=seed,
                    run_confirmation=not args.no_confirmation,
                    attempt_promote=bool(args.attempt_promote),
                ),
                fitness_fn=lambda recipe, proto: synthetic_fitness_fn(recipe, proto, seed=seed),
                output_dir=args.output_dir,
                run_id=args.run_id,
                progress=progress,
                terminal_eval_fn=(
                    (lambda recipe: _demo_terminal_eval(recipe, seed=seed))
                    if args.attempt_promote
                    else None
                ),
                gates=FeedbackGates(),
            )

    summary = {
        "run_id": result.run_id,
        "n_generations": len(result.history),
        "best_fitness": (result.history[-1]["best_fitness"] if result.history else None),
        "alive_final": (result.history[-1]["alive_count"] if result.history else None),
        "n_elites": len(result.elites),
        "decision_authorized": result.decision_authorized,
        "promotion": result.promotion,
        "output_dir": str(args.output_dir),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
