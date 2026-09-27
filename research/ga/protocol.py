"""Date protocol for genetic evolution — sealed holdout never enters fitness."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EvolutionProtocol:
    """Leakage-safe calendar shared by local and GCP evolution runs.

    Fitness uses only ``fitness_start`` .. ``fitness_end``.
    Survivors may be re-scored on the confirmation window.
    The terminal holdout is never loaded by the GA.
    """

    fitness_start: str = "2018-01-02"
    fitness_end: str = "2024-12-31"
    confirmation_start: str = "2025-01-02"
    confirmation_end: str = "2026-07-10"
    terminal_holdout_start: str = "2026-07-13"
    terminal_holdout_end: str = "2027-01-29"
    round_trip_cost_bps: float = 10.0
    min_trades: int = 40
    max_turnover: float = 8.0
    max_drawdown_hard: float = 0.45

    def __post_init__(self) -> None:
        ordered = [
            pd.Timestamp(self.fitness_start),
            pd.Timestamp(self.fitness_end),
            pd.Timestamp(self.confirmation_start),
            pd.Timestamp(self.confirmation_end),
            pd.Timestamp(self.terminal_holdout_start),
            pd.Timestamp(self.terminal_holdout_end),
        ]
        if ordered != sorted(ordered) or ordered[1] >= ordered[2]:
            raise ValueError("evolution protocol dates must be strictly ordered")
        if self.round_trip_cost_bps < 0:
            raise ValueError("round_trip_cost_bps must be non-negative")
        if self.min_trades < 5:
            raise ValueError("min_trades too small")
        if not (0.05 < self.max_drawdown_hard <= 1.0):
            raise ValueError("max_drawdown_hard out of range")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fitness_asof(self) -> str:
        """Latest bar allowed when building the fitness panel."""
        return self.fitness_end

    @property
    def confirmation_asof(self) -> str:
        return self.confirmation_end
