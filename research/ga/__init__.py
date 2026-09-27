"""Genetic-algorithm evolution lab for rule-based daily strategies.

Research-only: genomes never touch the sealed terminal holdout during fitness.
Survivors are artifacts under ``runs/ga/`` until a separate promotion process
authorizes shadow or live use.
"""
from __future__ import annotations

from .evolve import EvolveConfig, EvolutionResult, run_evolution
from .fitness import FitnessConfig, FitnessResult, evaluate_genome
from .genome import SIGNAL_FAMILIES, Genes, Genome, random_genome
from .protocol import EvolutionProtocol
from .ranker_evolve import RankerEvolveConfig, RankerEvolutionResult, run_ranker_evolution, smoke_ranker_evolution
from .ranker_protocol import RankerEvolutionProtocol
from .ranker_recipe import RankerRecipe, random_recipe
from .storage import DEFAULT_GA_RUNS_DIR, list_runs, load_run_summary, run_payload

__all__ = [
    "DEFAULT_GA_RUNS_DIR",
    "EvolutionProtocol",
    "EvolutionResult",
    "EvolveConfig",
    "FitnessConfig",
    "FitnessResult",
    "Genes",
    "Genome",
    "RankerEvolveConfig",
    "RankerEvolutionProtocol",
    "RankerEvolutionResult",
    "RankerRecipe",
    "SIGNAL_FAMILIES",
    "evaluate_genome",
    "list_runs",
    "load_run_summary",
    "random_genome",
    "random_recipe",
    "run_evolution",
    "run_ranker_evolution",
    "run_payload",
    "smoke_ranker_evolution",
]
