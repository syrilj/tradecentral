"""Sealed calendar for deep-scan *ranker* evolution (separate from rule GA).

Fitness may only use ``fitness_asofs``. Confirmation may use
``confirmation_asofs``. Terminal holdout as-ofs are sealed: never used to rank
the population or mutate recipes — only for a final fail-closed promote gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class RankerEvolutionProtocol:
    """Date sealing for ranker recipe search."""

    # Pre-holdout fitness dates (used for selection).
    fitness_asofs: tuple[str, ...] = (
        "2024-03-29",
        "2024-06-28",
        "2024-09-30",
        "2024-12-31",
    )
    # Optional confirmation (not terminal; may re-score elites only).
    confirmation_asofs: tuple[str, ...] = (
        "2025-01-31",
        "2025-03-31",
    )
    # Sealed terminal holdout — promotion only, never fitness ranking.
    terminal_holdout_asofs: tuple[str, ...] = (
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
        "2026-03-31",
        "2026-06-30",
    )
    min_fitness_ic_days: int = 2
    min_fitness_rank_ic: float = -0.05
    # Soft complexity penalty scale on fitness.
    complexity_penalty: float = 0.002

    def __post_init__(self) -> None:
        fit = set(self.fitness_asofs)
        conf = set(self.confirmation_asofs)
        term = set(self.terminal_holdout_asofs)
        if not self.fitness_asofs:
            raise ValueError("fitness_asofs must be non-empty")
        if not self.terminal_holdout_asofs:
            raise ValueError("terminal_holdout_asofs must be non-empty")
        if fit & term:
            raise ValueError(
                f"fitness_asofs overlap terminal holdout: {sorted(fit & term)}"
            )
        if conf & term:
            raise ValueError(
                f"confirmation_asofs overlap terminal holdout: {sorted(conf & term)}"
            )
        if fit & conf:
            raise ValueError(
                f"fitness_asofs overlap confirmation: {sorted(fit & conf)}"
            )
        # Lexical ISO date order: max fitness < min terminal
        if max(self.fitness_asofs) >= min(self.terminal_holdout_asofs):
            raise ValueError("fitness window must end before terminal holdout starts")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def assert_fitness_dates_sealed(self, asofs: Sequence[str]) -> None:
        """Raise if any requested fitness date is in the terminal holdout."""
        term = set(self.terminal_holdout_asofs)
        bad = [a for a in asofs if a in term]
        if bad:
            raise ValueError(f"terminal holdout dates forbidden in fitness: {bad}")
