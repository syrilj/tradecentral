"""Genetic algorithm loop: populate → evaluate → select → breed."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
import uuid

import numpy as np

from .fitness import FitnessConfig, evaluate_genome
from .genome import Genome, breed, random_genome
from .panel import MarketPanel, attach_factor_probe_cs_score, build_market_panel
from .protocol import EvolutionProtocol
from .storage import DEFAULT_GA_RUNS_DIR, write_run


@dataclass(frozen=True)
class EvolveConfig:
    population_size: int = 200
    n_generations: int = 15
    elite_fraction: float = 0.10
    tournament_size: int = 3
    mutation_rate: float = 0.28
    random_state: int = 20260803
    run_confirmation: bool = True
    # Smoke / local defaults can shrink the universe
    max_symbols: int | None = None
    # Attach factor-probe CS scores and allow cs_* genes (research hybrid).
    use_cs_score: bool = False

    def __post_init__(self) -> None:
        if self.population_size < 10:
            raise ValueError("population_size must be >= 10")
        if self.n_generations < 1:
            raise ValueError("n_generations must be >= 1")
        if not (0.02 <= self.elite_fraction <= 0.5):
            raise ValueError("elite_fraction out of range")
        if self.tournament_size < 2:
            raise ValueError("tournament_size must be >= 2")
        if not (0.0 < self.mutation_rate <= 1.0):
            raise ValueError("mutation_rate out of range")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationSnapshot:
    generation: int
    best_fitness: float
    mean_fitness: float
    median_fitness: float
    alive_count: int
    best_genome_id: str
    best_genes: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvolutionResult:
    run_id: str
    created_at: str
    protocol: dict[str, Any]
    config: dict[str, Any]
    fitness_config: dict[str, Any]
    symbols: list[str]
    history: list[dict[str, Any]]
    elites: list[dict[str, Any]]
    confirmation: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "ga_evolution_v1",
            "run_id": self.run_id,
            "created_at": self.created_at,
            "decision_authorized": False,
            "protocol": self.protocol,
            "config": self.config,
            "fitness_config": self.fitness_config,
            "symbols": list(self.symbols),
            "history": list(self.history),
            "elites": list(self.elites),
            "confirmation": list(self.confirmation),
            "notes": list(self.notes),
        }


def _tournament(pop: list[Genome], rng: np.random.Generator, k: int) -> Genome:
    contenders = [pop[i] for i in rng.choice(len(pop), size=min(k, len(pop)), replace=False)]
    contenders.sort(key=lambda g: (g.fitness is not None, g.fitness if g.fitness is not None else -1e9), reverse=True)
    return contenders[0]


def _evaluate_population(
    population: list[Genome],
    panel: MarketPanel,
    *,
    protocol: EvolutionProtocol,
    fitness_config: FitnessConfig,
    progress: Callable[[str], None] | None = None,
) -> list[Genome]:
    for i, genome in enumerate(population):
        evaluate_genome(panel, genome, protocol=protocol, fitness_config=fitness_config)
        if progress and (i + 1) % max(1, len(population) // 10) == 0:
            progress(f"evaluated {i + 1}/{len(population)}")
    return population


def run_evolution(
    symbols: list[str],
    *,
    data_dir: str | Path,
    output_dir: str | Path = DEFAULT_GA_RUNS_DIR,
    protocol: EvolutionProtocol | None = None,
    config: EvolveConfig | None = None,
    fitness_config: FitnessConfig | None = None,
    run_id: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> EvolutionResult:
    """Run the full GA and persist artifacts under ``output_dir/run_id``."""
    protocol = protocol or EvolutionProtocol()
    config = config or EvolveConfig()
    fitness_config = fitness_config or FitnessConfig()
    run_id = run_id or f"ga_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    notes: list[str] = [
        "Fitness never uses the terminal holdout window.",
        "Survivors are research-only until a separate promotion process authorizes shadow use.",
        "decision_authorized is always false for GA artifacts.",
    ]
    if config.use_cs_score:
        notes.append(
            "CS hybrid enabled: factor-probe style ranks on the panel (Qlib-scan weights); "
            "not a trained LGB artifact unless injected later."
        )

    syms = sorted({str(s).upper().strip() for s in symbols if str(s).strip()})
    if config.max_symbols is not None:
        syms = syms[: int(config.max_symbols)]
    if len(syms) < 5:
        raise ValueError("need at least 5 symbols for evolution")

    if progress:
        progress(f"loading panel asof={protocol.confirmation_asof if config.run_confirmation else protocol.fitness_asof}")

    # Load through confirmation end so we can re-score elites OOS without
    # touching the sealed terminal holdout.
    load_asof = protocol.confirmation_asof if config.run_confirmation else protocol.fitness_asof
    full_panel = build_market_panel(syms, asof=load_asof, data_dir=data_dir)
    if config.use_cs_score:
        if progress:
            progress("attaching factor-probe CS scores")
        full_panel = attach_factor_probe_cs_score(full_panel)
    fitness_panel = full_panel.slice_dates(protocol.fitness_start, protocol.fitness_end)

    rng = np.random.default_rng(int(config.random_state))
    population = [
        random_genome(rng, generation=0, allow_cs=config.use_cs_score)
        for _ in range(config.population_size)
    ]
    history: list[dict[str, Any]] = []
    elite_n = max(2, int(round(config.population_size * config.elite_fraction)))

    for gen in range(config.n_generations):
        if progress:
            progress(f"generation {gen}/{config.n_generations - 1}")
        for g in population:
            g.generation = gen
        _evaluate_population(
            population,
            fitness_panel,
            protocol=protocol,
            fitness_config=fitness_config,
            progress=progress,
        )
        population.sort(
            key=lambda g: (g.alive, g.fitness if g.fitness is not None else -1e9),
            reverse=True,
        )
        best = population[0]
        fits = [float(g.fitness) for g in population if g.fitness is not None]
        snap = GenerationSnapshot(
            generation=gen,
            best_fitness=float(best.fitness if best.fitness is not None else -1e9),
            mean_fitness=float(np.mean(fits)) if fits else -1e9,
            median_fitness=float(np.median(fits)) if fits else -1e9,
            alive_count=sum(1 for g in population if g.alive),
            best_genome_id=best.id,
            best_genes=best.genes.as_dict(),
        )
        history.append(snap.as_dict())
        if progress:
            progress(
                f"gen {gen}: best={snap.best_fitness:.4f} mean={snap.mean_fitness:.4f} "
                f"alive={snap.alive_count}/{len(population)}"
            )

        if gen == config.n_generations - 1:
            break

        elites = population[:elite_n]
        next_pop: list[Genome] = [
            Genome(
                id=e.id,
                generation=gen + 1,
                genes=e.genes,
                parent_ids=e.parent_ids,
                fitness=None,
                metrics={},
            )
            for e in elites
        ]
        while len(next_pop) < config.population_size:
            p1 = _tournament(population, rng, config.tournament_size)
            p2 = _tournament(population, rng, config.tournament_size)
            child = breed(
                p1,
                p2,
                rng,
                generation=gen + 1,
                mutation_rate=config.mutation_rate,
                allow_cs=config.use_cs_score,
            )
            next_pop.append(child)
        population = next_pop

    # Final elites from last evaluated population
    population.sort(
        key=lambda g: (g.alive, g.fitness if g.fitness is not None else -1e9),
        reverse=True,
    )
    elites = [g for g in population if g.alive][:elite_n]
    if not elites:
        elites = population[: min(5, len(population))]
        notes.append("No alive elites after hard constraints; reporting top dead genomes for diagnostics.")

    confirmation_rows: list[dict[str, Any]] = []
    if config.run_confirmation:
        conf_panel = full_panel.slice_dates(protocol.confirmation_start, protocol.confirmation_end)
        if progress:
            progress(f"confirmation window on {len(elites)} elites")
        for elite in elites:
            conf_genome = Genome(
                id=elite.id,
                generation=elite.generation,
                genes=elite.genes,
                parent_ids=elite.parent_ids,
            )
            evaluate_genome(conf_panel, conf_genome, protocol=protocol, fitness_config=fitness_config)
            confirmation_rows.append(
                {
                    "id": conf_genome.id,
                    "fitness_in_sample": elite.fitness,
                    "fitness_confirmation": conf_genome.fitness,
                    "alive_confirmation": conf_genome.alive,
                    "death_reason": conf_genome.death_reason,
                    "genes": conf_genome.genes.as_dict(),
                    "metrics_in_sample": elite.metrics,
                    "metrics_confirmation": conf_genome.metrics,
                    "passes_confirmation": bool(
                        conf_genome.alive
                        and conf_genome.fitness is not None
                        and elite.fitness is not None
                        and conf_genome.fitness > 0
                        and conf_genome.fitness >= 0.25 * float(elite.fitness)
                    ),
                }
            )

    result = EvolutionResult(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        protocol=protocol.as_dict(),
        config=config.as_dict(),
        fitness_config=fitness_config.as_dict(),
        symbols=syms,
        history=history,
        elites=[e.as_dict() for e in elites],
        confirmation=confirmation_rows,
        notes=notes,
    )
    write_run(result, Path(output_dir))
    if progress:
        progress(f"wrote run {run_id}")
    return result


def smoke_evolution(
    symbols: list[str],
    *,
    data_dir: str | Path,
    output_dir: str | Path = DEFAULT_GA_RUNS_DIR,
    use_cs_score: bool = False,
) -> EvolutionResult:
    """Tiny deterministic run for CI / local preflight."""
    return run_evolution(
        symbols,
        data_dir=data_dir,
        output_dir=output_dir,
        config=EvolveConfig(
            population_size=12,
            n_generations=3,
            elite_fraction=0.25,
            tournament_size=2,
            mutation_rate=0.3,
            random_state=7,
            run_confirmation=True,
            max_symbols=12,
            use_cs_score=use_cs_score,
        ),
        protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=0.80),
        run_id=f"ga_smoke_{uuid.uuid4().hex[:8]}",
    )
