"""Multi-parent evolutionary search over deep-scan ranker recipes.

Survival of the fittest on a *sealed* fitness window only. Terminal holdout
never enters selection. Final promote is fail-closed via
``qlib_scan_feedback.decide_promotion``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Sequence
import uuid

import numpy as np

from edge.research.qlib_scan_feedback import (
    FeedbackGates,
    OosSnapshot,
    decide_promotion,
    snapshot_from_eval,
)

from .ranker_protocol import RankerEvolutionProtocol
from .ranker_recipe import (
    RankerIndividual,
    RankerRecipe,
    breed,
    random_individual,
)


EDGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RANKER_GA_DIR = EDGE_ROOT / "runs" / "ga_ranker"


FitnessFn = Callable[[RankerRecipe, RankerEvolutionProtocol], dict[str, Any]]


def _confirmation_protocol(protocol: RankerEvolutionProtocol) -> RankerEvolutionProtocol:
    """Build a protocol whose fitness_asofs are the parent's confirmation dates.

    Confirmation remains sealed from terminal holdout. A tiny dummy confirmation
    slot is filled with one date from the original fitness window (not scored as
    selection fitness in the main loop).
    """
    dummy_conf = (protocol.fitness_asofs[0],)
    return RankerEvolutionProtocol(
        fitness_asofs=protocol.confirmation_asofs,
        confirmation_asofs=dummy_conf,
        terminal_holdout_asofs=protocol.terminal_holdout_asofs,
        min_fitness_ic_days=1,
        min_fitness_rank_ic=protocol.min_fitness_rank_ic,
        complexity_penalty=protocol.complexity_penalty,
    )


@dataclass(frozen=True)
class RankerEvolveConfig:
    population_size: int = 16
    n_generations: int = 4
    elite_fraction: float = 0.25
    tournament_size: int = 3
    mutation_rate: float = 0.30
    random_state: int = 20260804
    run_confirmation: bool = True
    attempt_promote: bool = False

    def __post_init__(self) -> None:
        if self.population_size < 4:
            raise ValueError("population_size must be >= 4")
        if self.n_generations < 2:
            raise ValueError("n_generations must be >= 2 for multi-gen survival")
        if not (0.05 <= self.elite_fraction <= 0.5):
            raise ValueError("elite_fraction out of range")
        if self.tournament_size < 2:
            raise ValueError("tournament_size must be >= 2")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankerEvolutionResult:
    run_id: str
    created_at: str
    protocol: dict[str, Any]
    config: dict[str, Any]
    history: list[dict[str, Any]]
    elites: list[dict[str, Any]]
    confirmation: list[dict[str, Any]]
    promotion: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    decision_authorized: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "ga_ranker_evolution_v1",
            "run_id": self.run_id,
            "created_at": self.created_at,
            "decision_authorized": False,
            "protocol": self.protocol,
            "config": self.config,
            "history": list(self.history),
            "elites": list(self.elites),
            "confirmation": list(self.confirmation),
            "promotion": self.promotion,
            "notes": list(self.notes),
        }


def synthetic_fitness_fn(
    recipe: RankerRecipe,
    protocol: RankerEvolutionProtocol,
    *,
    seed: int = 0,
) -> dict[str, Any]:
    """Deterministic smoke fitness — never touches terminal holdout.

    Encodes a mild preference for later train_end + mid ensemble weight so
    selection has a real ranking signal without training LightGBM.
    """
    protocol.assert_fitness_dates_sealed(protocol.fitness_asofs)
    # Hash recipe into a stable pseudo Rank-IC in [-0.02, 0.08]
    h = int(recipe.fingerprint()[:8], 16) ^ int(seed)
    rng = np.random.default_rng(h % (2**32 - 1))
    base = float(rng.normal(0.02, 0.015))
    # Prefer later train anchors (index in menu)
    from .ranker_recipe import TRAIN_END_MENU

    recency = TRAIN_END_MENU.index(recipe.train_end) / max(1, len(TRAIN_END_MENU) - 1)
    ensemble_mid = 1.0 - abs(float(recipe.ensemble_ml_weight) - 0.65) / 0.40
    feature_bonus = {"core5": 0.0, "core_plus_mom": 0.005, "full16": 0.008}.get(
        recipe.feature_set, 0.0,
    )
    mean_ic = base + 0.025 * recency + 0.01 * ensemble_mid + feature_bonus
    n_days = len(protocol.fitness_asofs)
    paper_net = mean_ic * 0.15  # toy mapping
    complexity = (
        (recipe.num_leaves / 63.0)
        + (recipe.max_symbols / 280.0)
        + (0.5 if recipe.feature_set == "full16" else 0.0)
    )
    fitness = float(mean_ic - protocol.complexity_penalty * complexity)
    alive = mean_ic >= protocol.min_fitness_rank_ic and n_days >= protocol.min_fitness_ic_days
    death = None if alive else (
        "rank_ic_floor" if mean_ic < protocol.min_fitness_rank_ic else "thin_ic_days"
    )
    return {
        "fitness": fitness,
        "alive": alive,
        "death_reason": death,
        "metrics": {
            "fitness_mean_rank_ic": mean_ic,
            "fitness_n_ic_days": n_days,
            "fitness_paper_net_mean": paper_net,
            "fitness_asofs": list(protocol.fitness_asofs),
            "complexity": complexity,
            "mode": "synthetic",
        },
    }


def evaluate_individual(
    individual: RankerIndividual,
    protocol: RankerEvolutionProtocol,
    fitness_fn: FitnessFn,
) -> RankerIndividual:
    """Score one recipe on the sealed fitness window only."""
    protocol.assert_fitness_dates_sealed(protocol.fitness_asofs)
    result = fitness_fn(individual.recipe, protocol)
    individual.fitness = float(result["fitness"]) if result.get("fitness") is not None else None
    individual.alive = bool(result.get("alive", False))
    individual.death_reason = result.get("death_reason")
    individual.metrics = dict(result.get("metrics") or {})
    # Belt-and-suspenders: refuse metrics that claim terminal dates.
    claimed = individual.metrics.get("fitness_asofs") or []
    bad = set(claimed) & set(protocol.terminal_holdout_asofs)
    if bad:
        individual.alive = False
        individual.death_reason = f"terminal_holdout_leak:{sorted(bad)}"
        individual.fitness = -1e9
    return individual


def tournament_select(
    population: Sequence[RankerIndividual],
    rng: np.random.Generator,
    k: int,
) -> RankerIndividual:
    idx = rng.choice(len(population), size=min(k, len(population)), replace=False)
    contenders = [population[int(i)] for i in idx]
    contenders.sort(
        key=lambda g: (g.alive, g.fitness if g.fitness is not None else -1e9),
        reverse=True,
    )
    return contenders[0]


def select_elites(
    population: Sequence[RankerIndividual],
    *,
    elite_n: int,
) -> list[RankerIndividual]:
    """Highest-fitness alive first; fall back to top dead for diagnostics."""
    ordered = sorted(
        population,
        key=lambda g: (g.alive, g.fitness if g.fitness is not None else -1e9),
        reverse=True,
    )
    alive = [g for g in ordered if g.alive]
    if alive:
        return alive[:elite_n]
    return list(ordered[:elite_n])


def run_ranker_evolution(
    *,
    protocol: RankerEvolutionProtocol | None = None,
    config: RankerEvolveConfig | None = None,
    fitness_fn: FitnessFn | None = None,
    output_dir: str | Path = DEFAULT_RANKER_GA_DIR,
    run_id: str | None = None,
    progress: Callable[[str], None] | None = None,
    champion_snapshot: OosSnapshot | None = None,
    terminal_eval_fn: Callable[[RankerRecipe], dict[str, Any]] | None = None,
    gates: FeedbackGates | None = None,
) -> RankerEvolutionResult:
    """Populate → fitness → elite → breed for ≥2 generations; optional promote."""
    protocol = protocol or RankerEvolutionProtocol()
    config = config or RankerEvolveConfig()
    fitness_fn = fitness_fn or (
        lambda recipe, proto: synthetic_fitness_fn(recipe, proto, seed=config.random_state)
    )
    gates = gates or FeedbackGates()
    run_id = run_id or (
        f"ga_ranker_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    notes = [
        "Fitness never uses terminal_holdout_asofs.",
        "Selection is survival-of-the-fittest on sealed fitness Rank-IC proxy.",
        "decision_authorized is always false for ranker GA artifacts.",
        "Promote is fail-closed via FeedbackGates on terminal holdout only.",
    ]

    rng = np.random.default_rng(int(config.random_state))
    population = [random_individual(rng, generation=0) for _ in range(config.population_size)]
    history: list[dict[str, Any]] = []
    elite_n = max(2, int(round(config.population_size * config.elite_fraction)))

    for gen in range(config.n_generations):
        if progress:
            progress(f"generation {gen}/{config.n_generations - 1}")
        for ind in population:
            ind.generation = gen
            evaluate_individual(ind, protocol, fitness_fn)

        elites_now = select_elites(population, elite_n=elite_n)
        best = elites_now[0]
        fits = [float(g.fitness) for g in population if g.fitness is not None]
        snap = {
            "generation": gen,
            "best_fitness": float(best.fitness if best.fitness is not None else -1e9),
            "mean_fitness": float(np.mean(fits)) if fits else -1e9,
            "median_fitness": float(np.median(fits)) if fits else -1e9,
            "alive_count": sum(1 for g in population if g.alive),
            "best_individual_id": best.id,
            "best_recipe": best.recipe.as_dict(),
            "best_fingerprint": best.recipe.fingerprint(),
        }
        history.append(snap)
        if progress:
            progress(
                f"gen {gen}: best={snap['best_fitness']:.4f} "
                f"alive={snap['alive_count']}/{len(population)}"
            )

        if gen == config.n_generations - 1:
            break

        next_pop: list[RankerIndividual] = [
            RankerIndividual(
                id=e.id,
                generation=gen + 1,
                recipe=e.recipe,
                parent_ids=e.parent_ids,
            )
            for e in elites_now
        ]
        while len(next_pop) < config.population_size:
            p1 = tournament_select(population, rng, config.tournament_size)
            p2 = tournament_select(population, rng, config.tournament_size)
            next_pop.append(
                breed(
                    p1, p2, rng,
                    generation=gen + 1,
                    mutation_rate=config.mutation_rate,
                )
            )
        population = next_pop

    elites = select_elites(population, elite_n=elite_n)
    if not any(e.alive for e in elites):
        notes.append("No alive elites; reporting top dead recipes for diagnostics.")

    confirmation_rows: list[dict[str, Any]] = []
    if config.run_confirmation and protocol.confirmation_asofs:
        # Score elites on confirmation asofs only (still sealed from terminal).
        conf_proto = _confirmation_protocol(protocol)
        for elite in elites:
            conf_ind = RankerIndividual(
                id=elite.id,
                generation=elite.generation,
                recipe=elite.recipe,
                parent_ids=elite.parent_ids,
            )
            evaluate_individual(conf_ind, conf_proto, fitness_fn)
            confirmation_rows.append(
                {
                    "id": conf_ind.id,
                    "fitness_in_sample": elite.fitness,
                    "fitness_confirmation": conf_ind.fitness,
                    "alive_confirmation": conf_ind.alive,
                    "death_reason": conf_ind.death_reason,
                    "recipe": conf_ind.recipe.as_dict(),
                    "metrics_confirmation": conf_ind.metrics,
                    "confirmation_asofs": list(protocol.confirmation_asofs),
                    "passes_confirmation": bool(
                        conf_ind.alive
                        and conf_ind.fitness is not None
                        and elite.fitness is not None
                        and conf_ind.fitness > -0.02
                    ),
                }
            )

    promotion_payload: dict[str, Any] | None = None
    if config.attempt_promote and elites:
        best = elites[0]
        if terminal_eval_fn is None:
            promotion_payload = {
                "attempted": False,
                "reason": "no_terminal_eval_fn",
                "elite_id": best.id,
                "decision_authorized": False,
            }
        else:
            # Terminal eval only here — never used during population ranking.
            term_result = terminal_eval_fn(best.recipe)
            challenger = snapshot_from_eval(
                term_result,
                source_id=f"ga_ranker_{best.recipe.fingerprint()}",
            )
            decision = decide_promotion(
                challenger=challenger,
                champion=champion_snapshot,
                gates=gates,
            )
            promotion_payload = {
                "attempted": True,
                "elite_id": best.id,
                "elite_recipe": best.recipe.as_dict(),
                "terminal_eval": term_result,
                "decision": decision.to_dict(),
                "promote": decision.promote,
                "decision_authorized": False,
            }
            if decision.promote:
                notes.append(
                    "Elite cleared terminal OOS gates (research promote candidate only)."
                )
            else:
                notes.append(
                    f"Elite failed terminal gates: {list(decision.reasons)}"
                )

    result = RankerEvolutionResult(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        protocol=protocol.as_dict(),
        config=config.as_dict(),
        history=history,
        elites=[e.as_dict() for e in elites],
        confirmation=confirmation_rows,
        promotion=promotion_payload,
        notes=notes,
        decision_authorized=False,
    )
    _write_ranker_run(result, Path(output_dir))
    if progress:
        progress(f"wrote run {run_id}")
    return result


def _write_ranker_run(result: RankerEvolutionResult, output_dir: Path) -> Path:
    run_dir = output_dir / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = result.as_dict()
    summary = run_dir / "summary.json"
    summary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "elites.json").write_text(
        json.dumps(payload.get("elites", []), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "history.json").write_text(
        json.dumps(payload.get("history", []), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "promotion.json").write_text(
        json.dumps(payload.get("promotion"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "LATEST.json").write_text(
        json.dumps({"run_id": result.run_id, "path": str(summary)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def smoke_ranker_evolution(
    *,
    output_dir: str | Path = DEFAULT_RANKER_GA_DIR,
    seed: int = 7,
    run_id: str | None = None,
) -> RankerEvolutionResult:
    """Tiny deterministic multi-gen run for CI / preflight."""
    return run_ranker_evolution(
        protocol=RankerEvolutionProtocol(),
        config=RankerEvolveConfig(
            population_size=12,
            n_generations=3,
            elite_fraction=0.25,
            tournament_size=2,
            mutation_rate=0.35,
            random_state=seed,
            run_confirmation=True,
            attempt_promote=False,
        ),
        fitness_fn=lambda recipe, proto: synthetic_fitness_fn(recipe, proto, seed=seed),
        output_dir=output_dir,
        run_id=run_id or f"ga_ranker_smoke_{uuid.uuid4().hex[:8]}",
    )
