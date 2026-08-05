"""Strategy genomes: fixed gene schema, random init, crossover, mutation."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Any, Mapping
import uuid

import numpy as np


SIGNAL_FAMILIES: tuple[str, ...] = (
    "momentum",
    "mean_reversion",
    "vol_scaled_momentum",
    "breakout",
)
LONG_SHORT_MODES: tuple[str, ...] = ("long_only", "short_only", "long_short")
HORIZONS: tuple[int, ...] = (5, 10, 20)
# Cross-sectional aux score (Qlib-style ranks) — research hybrid only.
CS_MODES: tuple[str, ...] = ("off", "filter", "blend")

LOOKBACK_MIN, LOOKBACK_MAX = 5, 126
VOL_WINDOW_MIN, VOL_WINDOW_MAX = 10, 63
TOP_K_MIN, TOP_K_MAX = 1, 10
ENTRY_Z_MIN, ENTRY_Z_MAX = 0.25, 2.5
EXIT_Z_MIN, EXIT_Z_MAX = 0.0, 1.5
DOLLAR_RANK_MIN, DOLLAR_RANK_MAX = 0.0, 0.40
CS_MIN_RANK_MIN, CS_MIN_RANK_MAX = 0.0, 0.90
CS_BLEND_MIN, CS_BLEND_MAX = 0.0, 1.0


@dataclass(frozen=True)
class Genes:
    """Parameters of one rule-based daily strategy."""

    signal_family: str
    lookback: int
    entry_z: float
    exit_z: float
    horizon_days: int
    top_k: int
    long_short: str
    vol_window: int
    dollar_volume_min_rank: float
    # Optional cross-section aux (Qlib / factor-probe ranks on the panel).
    cs_mode: str = "off"
    cs_min_rank: float = 0.0
    cs_blend: float = 0.0

    def __post_init__(self) -> None:
        if self.signal_family not in SIGNAL_FAMILIES:
            raise ValueError(f"unknown signal_family: {self.signal_family}")
        if self.long_short not in LONG_SHORT_MODES:
            raise ValueError(f"unknown long_short: {self.long_short}")
        if int(self.horizon_days) not in HORIZONS:
            raise ValueError(f"horizon_days must be one of {HORIZONS}")
        if not (LOOKBACK_MIN <= int(self.lookback) <= LOOKBACK_MAX):
            raise ValueError("lookback out of bounds")
        if not (VOL_WINDOW_MIN <= int(self.vol_window) <= VOL_WINDOW_MAX):
            raise ValueError("vol_window out of bounds")
        if not (TOP_K_MIN <= int(self.top_k) <= TOP_K_MAX):
            raise ValueError("top_k out of bounds")
        if not (ENTRY_Z_MIN <= float(self.entry_z) <= ENTRY_Z_MAX):
            raise ValueError("entry_z out of bounds")
        if not (EXIT_Z_MIN <= float(self.exit_z) <= EXIT_Z_MAX):
            raise ValueError("exit_z out of bounds")
        if not (DOLLAR_RANK_MIN <= float(self.dollar_volume_min_rank) <= DOLLAR_RANK_MAX):
            raise ValueError("dollar_volume_min_rank out of bounds")
        if self.cs_mode not in CS_MODES:
            raise ValueError(f"unknown cs_mode: {self.cs_mode}")
        if not (CS_MIN_RANK_MIN <= float(self.cs_min_rank) <= CS_MIN_RANK_MAX):
            raise ValueError("cs_min_rank out of bounds")
        if not (CS_BLEND_MIN <= float(self.cs_blend) <= CS_BLEND_MAX):
            raise ValueError("cs_blend out of bounds")
        if float(self.exit_z) > float(self.entry_z) and self.signal_family == "mean_reversion":
            # exit must be tighter than entry for MR; still allow equality edge
            pass

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_family": self.signal_family,
            "lookback": int(self.lookback),
            "entry_z": float(self.entry_z),
            "exit_z": float(self.exit_z),
            "horizon_days": int(self.horizon_days),
            "top_k": int(self.top_k),
            "long_short": self.long_short,
            "vol_window": int(self.vol_window),
            "dollar_volume_min_rank": float(self.dollar_volume_min_rank),
            "cs_mode": str(self.cs_mode),
            "cs_min_rank": float(self.cs_min_rank),
            "cs_blend": float(self.cs_blend),
        }

    def complexity(self) -> float:
        """Higher = more degrees of freedom; used as a soft fitness penalty."""
        family_cost = {
            "momentum": 0.0,
            "vol_scaled_momentum": 0.15,
            "mean_reversion": 0.25,
            "breakout": 0.20,
        }[self.signal_family]
        cs_cost = 0.0 if self.cs_mode == "off" else (0.12 if self.cs_mode == "filter" else 0.18)
        return (
            family_cost
            + cs_cost
            + 0.02 * max(0, self.lookback - 20) / 100.0
            + 0.05 * (self.top_k / TOP_K_MAX)
            + (0.1 if self.long_short == "long_short" else 0.0)
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Genes":
        return cls(
            signal_family=str(raw["signal_family"]),
            lookback=int(raw["lookback"]),
            entry_z=float(raw["entry_z"]),
            exit_z=float(raw["exit_z"]),
            horizon_days=int(raw["horizon_days"]),
            top_k=int(raw["top_k"]),
            long_short=str(raw["long_short"]),
            vol_window=int(raw["vol_window"]),
            dollar_volume_min_rank=float(raw["dollar_volume_min_rank"]),
            cs_mode=str(raw.get("cs_mode") or "off"),
            cs_min_rank=float(raw.get("cs_min_rank") or 0.0),
            cs_blend=float(raw.get("cs_blend") or 0.0),
        )


@dataclass
class Genome:
    id: str
    generation: int
    genes: Genes
    parent_ids: tuple[str, ...] = ()
    fitness: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    alive: bool = True
    death_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "generation": int(self.generation),
            "genes": self.genes.as_dict(),
            "parent_ids": list(self.parent_ids),
            "fitness": None if self.fitness is None else float(self.fitness),
            "metrics": dict(self.metrics),
            "alive": bool(self.alive),
            "death_reason": self.death_reason,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Genome":
        return cls(
            id=str(raw["id"]),
            generation=int(raw.get("generation", 0)),
            genes=Genes.from_mapping(raw["genes"]),
            parent_ids=tuple(str(x) for x in (raw.get("parent_ids") or ())),
            fitness=None if raw.get("fitness") is None else float(raw["fitness"]),
            metrics=dict(raw.get("metrics") or {}),
            alive=bool(raw.get("alive", True)),
            death_reason=raw.get("death_reason"),
        )

    def fingerprint(self) -> str:
        payload = str(sorted(self.genes.as_dict().items())).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()[:12]


def _new_id(generation: int) -> str:
    return f"g{int(generation):03d}_{uuid.uuid4().hex[:10]}"


def random_genes(rng: np.random.Generator, *, allow_cs: bool = False) -> Genes:
    family = str(rng.choice(SIGNAL_FAMILIES))
    lookback = int(rng.integers(LOOKBACK_MIN, LOOKBACK_MAX + 1))
    vol_window = int(rng.integers(VOL_WINDOW_MIN, VOL_WINDOW_MAX + 1))
    entry_z = float(rng.uniform(ENTRY_Z_MIN, ENTRY_Z_MAX))
    exit_z = float(rng.uniform(EXIT_Z_MIN, min(EXIT_Z_MAX, entry_z)))
    horizon = int(rng.choice(HORIZONS))
    top_k = int(rng.integers(TOP_K_MIN, TOP_K_MAX + 1))
    long_short = str(rng.choice(LONG_SHORT_MODES))
    dollar_rank = float(rng.uniform(DOLLAR_RANK_MIN, DOLLAR_RANK_MAX))
    if allow_cs:
        cs_mode = str(rng.choice(CS_MODES))
        cs_min_rank = float(rng.uniform(CS_MIN_RANK_MIN, 0.60)) if cs_mode != "off" else 0.0
        cs_blend = float(rng.uniform(0.15, 0.85)) if cs_mode == "blend" else 0.0
    else:
        cs_mode, cs_min_rank, cs_blend = "off", 0.0, 0.0
    return Genes(
        signal_family=family,
        lookback=lookback,
        entry_z=round(entry_z, 4),
        exit_z=round(exit_z, 4),
        horizon_days=horizon,
        top_k=top_k,
        long_short=long_short,
        vol_window=vol_window,
        dollar_volume_min_rank=round(dollar_rank, 4),
        cs_mode=cs_mode,
        cs_min_rank=round(cs_min_rank, 4),
        cs_blend=round(cs_blend, 4),
    )


def random_genome(rng: np.random.Generator, *, generation: int = 0, allow_cs: bool = False) -> Genome:
    return Genome(
        id=_new_id(generation),
        generation=generation,
        genes=random_genes(rng, allow_cs=allow_cs),
    )


def _clip_int(value: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(round(value)))))


def _clip_float(value: float, lo: float, hi: float) -> float:
    if not math.isfinite(value):
        return lo
    return float(max(lo, min(hi, value)))


def mutate_genes(
    genes: Genes,
    rng: np.random.Generator,
    *,
    rate: float = 0.25,
    allow_cs: bool = False,
) -> Genes:
    """Point-mutate each gene with probability ``rate``."""
    if not (0.0 < rate <= 1.0):
        raise ValueError("mutation rate must be in (0, 1]")
    g = genes.as_dict()
    if rng.random() < rate:
        g["signal_family"] = str(rng.choice(SIGNAL_FAMILIES))
    if rng.random() < rate:
        g["lookback"] = _clip_int(g["lookback"] + int(rng.integers(-10, 11)), LOOKBACK_MIN, LOOKBACK_MAX)
    if rng.random() < rate:
        g["vol_window"] = _clip_int(g["vol_window"] + int(rng.integers(-5, 6)), VOL_WINDOW_MIN, VOL_WINDOW_MAX)
    if rng.random() < rate:
        g["entry_z"] = round(
            _clip_float(float(g["entry_z"]) + float(rng.normal(0, 0.2)), ENTRY_Z_MIN, ENTRY_Z_MAX),
            4,
        )
    if rng.random() < rate:
        g["exit_z"] = round(
            _clip_float(float(g["exit_z"]) + float(rng.normal(0, 0.15)), EXIT_Z_MIN, EXIT_Z_MAX),
            4,
        )
    if rng.random() < rate:
        g["horizon_days"] = int(rng.choice(HORIZONS))
    if rng.random() < rate:
        g["top_k"] = _clip_int(g["top_k"] + int(rng.integers(-2, 3)), TOP_K_MIN, TOP_K_MAX)
    if rng.random() < rate:
        g["long_short"] = str(rng.choice(LONG_SHORT_MODES))
    if rng.random() < rate:
        g["dollar_volume_min_rank"] = round(
            _clip_float(
                float(g["dollar_volume_min_rank"]) + float(rng.normal(0, 0.05)),
                DOLLAR_RANK_MIN,
                DOLLAR_RANK_MAX,
            ),
            4,
        )
    if allow_cs and rng.random() < rate:
        g["cs_mode"] = str(rng.choice(CS_MODES))
    if allow_cs and rng.random() < rate:
        g["cs_min_rank"] = round(
            _clip_float(float(g["cs_min_rank"]) + float(rng.normal(0, 0.08)), CS_MIN_RANK_MIN, CS_MIN_RANK_MAX),
            4,
        )
    if allow_cs and rng.random() < rate:
        g["cs_blend"] = round(
            _clip_float(float(g["cs_blend"]) + float(rng.normal(0, 0.12)), CS_BLEND_MIN, CS_BLEND_MAX),
            4,
        )
    if not allow_cs:
        g["cs_mode"] = "off"
        g["cs_min_rank"] = 0.0
        g["cs_blend"] = 0.0
    elif g["cs_mode"] == "off":
        g["cs_min_rank"] = 0.0
        g["cs_blend"] = 0.0
    elif g["cs_mode"] == "filter":
        g["cs_blend"] = 0.0
    # Keep MR exit <= entry when possible
    if float(g["exit_z"]) > float(g["entry_z"]):
        g["exit_z"] = round(float(g["entry_z"]) * 0.5, 4)
    return Genes.from_mapping(g)


def crossover(a: Genes, b: Genes, rng: np.random.Generator) -> Genes:
    """Uniform crossover of two parent gene maps."""
    da, db = a.as_dict(), b.as_dict()
    child = {k: (da[k] if rng.random() < 0.5 else db[k]) for k in da}
    if float(child["exit_z"]) > float(child["entry_z"]):
        child["exit_z"] = round(float(child["entry_z"]) * 0.5, 4)
    return Genes.from_mapping(child)


def breed(
    parent_a: Genome,
    parent_b: Genome,
    rng: np.random.Generator,
    *,
    generation: int,
    mutation_rate: float = 0.25,
    allow_cs: bool = False,
) -> Genome:
    child_genes = mutate_genes(
        crossover(parent_a.genes, parent_b.genes, rng),
        rng,
        rate=mutation_rate,
        allow_cs=allow_cs,
    )
    return Genome(
        id=_new_id(generation),
        generation=generation,
        genes=child_genes,
        parent_ids=(parent_a.id, parent_b.id),
    )
