#!/usr/bin/env python3
"""Run the genetic strategy evolution lab (local CPU).

Examples:
  # Fast smoke (CI / preflight)
  python edge/tools/run_ga_evolve.py --smoke

  # Full local search
  python edge/tools/run_ga_evolve.py --pop 200 --gens 15

  # Custom universe file
  python edge/tools/run_ga_evolve.py --universe edge/config/universe_directional_v2.json
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

from edge.research.ga.evolve import EvolveConfig, run_evolution, smoke_evolution  # noqa: E402
from edge.research.ga.fitness import FitnessConfig  # noqa: E402
from edge.research.ga.protocol import EvolutionProtocol  # noqa: E402
from edge.research.ga.storage import DEFAULT_GA_RUNS_DIR  # noqa: E402


DEFAULT_UNIVERSE = EDGE_ROOT / "config" / "universe_directional_v2.json"
DEFAULT_DATA_DIR = EDGE_ROOT / "data" / "1d"


def load_symbols(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        symbols = [str(s).strip().upper() for s in raw if str(s).strip()]
    else:
        symbols = [str(s).strip().upper() for s in raw.get("symbols", []) if str(s).strip()]
    if not symbols:
        raise ValueError(f"no symbols in universe file: {path}")
    return symbols


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_GA_RUNS_DIR)
    parser.add_argument("--smoke", action="store_true", help="Tiny deterministic run")
    parser.add_argument("--pop", type=int, default=200)
    parser.add_argument("--gens", type=int, default=15)
    parser.add_argument("--elite-frac", type=float, default=0.10)
    parser.add_argument("--mutation-rate", type=float, default=0.28)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--no-confirmation", action="store_true")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--min-trades", type=int, default=40)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument(
        "--cs-score",
        action="store_true",
        help="Hybrid research path: factor-probe CS ranks + cs_* genes (not live auth)",
    )
    args = parser.parse_args()

    symbols = load_symbols(args.universe)

    def progress(msg: str) -> None:
        print(f"[ga] {msg}", flush=True)

    if args.smoke:
        result = smoke_evolution(
            symbols,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            use_cs_score=bool(args.cs_score),
        )
    else:
        result = run_evolution(
            symbols,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            protocol=EvolutionProtocol(
                round_trip_cost_bps=args.cost_bps,
                min_trades=args.min_trades,
            ),
            config=EvolveConfig(
                population_size=args.pop,
                n_generations=args.gens,
                elite_fraction=args.elite_frac,
                mutation_rate=args.mutation_rate,
                random_state=args.seed,
                run_confirmation=not args.no_confirmation,
                max_symbols=args.max_symbols,
                use_cs_score=bool(args.cs_score),
            ),
            fitness_config=FitnessConfig(),
            run_id=args.run_id,
            progress=progress,
        )

    summary = {
        "run_id": result.run_id,
        "n_generations": len(result.history),
        "best_final_fitness": (result.history[-1]["best_fitness"] if result.history else None),
        "n_elites": len(result.elites),
        "confirmation_passes": sum(1 for c in result.confirmation if c.get("passes_confirmation")),
        "confirmation_total": len(result.confirmation),
        "output": str(Path(args.output_dir) / result.run_id / "summary.json"),
        "decision_authorized": False,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
