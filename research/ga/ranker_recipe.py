"""Preregistered deep-scan ranker recipes as evolvable genomes.

Each candidate is a *recipe* (train/val windows + discrete knobs), not free
hyperparameter search over the terminal holdout. Bounds are closed menus so
mutation/crossover cannot invent leakage-prone windows.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping
import uuid

import numpy as np


# Discrete train-end anchors (inclusive). Val always starts after train_end +
# purge gap and is sized by val_months.
TRAIN_END_MENU: tuple[str, ...] = (
    "2022-12-30",
    "2023-06-30",
    "2023-12-29",
    "2024-03-28",
    "2024-06-28",
)
VAL_MONTHS_MENU: tuple[int, ...] = (3, 6, 9, 12)
MAX_SYMBOLS_MENU: tuple[int, ...] = (80, 120, 160, 200, 280)
ENSEMBLE_W_MENU: tuple[float, ...] = (0.45, 0.55, 0.65, 0.75, 0.85)
LEARNING_RATE_MENU: tuple[float, ...] = (0.02, 0.025, 0.03)
NUM_LEAVES_MENU: tuple[int, ...] = (31, 48, 63)
MIN_DATA_LEAF_MENU: tuple[int, ...] = (80, 120, 160)
FEATURE_SET_MENU: tuple[str, ...] = (
    "core5",          # rev1,rev5,mom12_1,lowvol,liq
    "core_plus_mom",  # core + ret_5/21/63 + mom_accel
    "full16",         # full FEATURE_NAMES from qlib_scan_score
)
LABEL_HORIZON_DAYS = 5  # must match train_qlib_scan_lgb


@dataclass(frozen=True)
class RankerRecipe:
    """One preregistered deep-scan training recipe."""

    train_end: str
    val_months: int
    max_symbols: int
    ensemble_ml_weight: float
    learning_rate: float
    num_leaves: int
    min_data_in_leaf: int
    feature_set: str

    def __post_init__(self) -> None:
        if self.train_end not in TRAIN_END_MENU:
            raise ValueError(f"train_end not in menu: {self.train_end}")
        if int(self.val_months) not in VAL_MONTHS_MENU:
            raise ValueError(f"val_months not in menu: {self.val_months}")
        if int(self.max_symbols) not in MAX_SYMBOLS_MENU:
            raise ValueError(f"max_symbols not in menu: {self.max_symbols}")
        if float(self.ensemble_ml_weight) not in ENSEMBLE_W_MENU:
            raise ValueError(f"ensemble_ml_weight not in menu: {self.ensemble_ml_weight}")
        if float(self.learning_rate) not in LEARNING_RATE_MENU:
            raise ValueError(f"learning_rate not in menu: {self.learning_rate}")
        if int(self.num_leaves) not in NUM_LEAVES_MENU:
            raise ValueError(f"num_leaves not in menu: {self.num_leaves}")
        if int(self.min_data_in_leaf) not in MIN_DATA_LEAF_MENU:
            raise ValueError(f"min_data_in_leaf not in menu: {self.min_data_in_leaf}")
        if self.feature_set not in FEATURE_SET_MENU:
            raise ValueError(f"feature_set not in menu: {self.feature_set}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_end": self.train_end,
            "val_months": int(self.val_months),
            "max_symbols": int(self.max_symbols),
            "ensemble_ml_weight": float(self.ensemble_ml_weight),
            "learning_rate": float(self.learning_rate),
            "num_leaves": int(self.num_leaves),
            "min_data_in_leaf": int(self.min_data_in_leaf),
            "feature_set": self.feature_set,
            "label_horizon_days": LABEL_HORIZON_DAYS,
        }

    def fingerprint(self) -> str:
        raw = "|".join(f"{k}={self.as_dict()[k]}" for k in sorted(self.as_dict()))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def val_window(self) -> tuple[str, str]:
        """Return (val_start, val_end) with ≥ label-horizon purge after train_end."""
        import pandas as pd

        te = pd.Timestamp(self.train_end)
        # Purge: skip LABEL_HORIZON_DAYS trading-ish calendar days after train_end.
        val_start = te + pd.Timedelta(days=LABEL_HORIZON_DAYS + 2)
        # Align to next business day
        while val_start.weekday() >= 5:
            val_start += pd.Timedelta(days=1)
        val_end = val_start + pd.DateOffset(months=int(self.val_months))
        # Back off one day if weekend
        while val_end.weekday() >= 5:
            val_end -= pd.Timedelta(days=1)
        return val_start.strftime("%Y-%m-%d"), val_end.strftime("%Y-%m-%d")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RankerRecipe":
        return cls(
            train_end=str(raw["train_end"]),
            val_months=int(raw["val_months"]),
            max_symbols=int(raw["max_symbols"]),
            ensemble_ml_weight=float(raw["ensemble_ml_weight"]),
            learning_rate=float(raw["learning_rate"]),
            num_leaves=int(raw["num_leaves"]),
            min_data_in_leaf=int(raw["min_data_in_leaf"]),
            feature_set=str(raw["feature_set"]),
        )


@dataclass
class RankerIndividual:
    """One member of the ranker population."""

    id: str
    generation: int
    recipe: RankerRecipe
    parent_ids: tuple[str, ...] = ()
    fitness: float | None = None
    metrics: dict[str, Any] | None = None
    alive: bool = True
    death_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "generation": int(self.generation),
            "recipe": self.recipe.as_dict(),
            "fingerprint": self.recipe.fingerprint(),
            "parent_ids": list(self.parent_ids),
            "fitness": self.fitness,
            "metrics": dict(self.metrics or {}),
            "alive": bool(self.alive),
            "death_reason": self.death_reason,
        }


def random_recipe(rng: np.random.Generator) -> RankerRecipe:
    return RankerRecipe(
        train_end=str(rng.choice(TRAIN_END_MENU)),
        val_months=int(rng.choice(VAL_MONTHS_MENU)),
        max_symbols=int(rng.choice(MAX_SYMBOLS_MENU)),
        ensemble_ml_weight=float(rng.choice(ENSEMBLE_W_MENU)),
        learning_rate=float(rng.choice(LEARNING_RATE_MENU)),
        num_leaves=int(rng.choice(NUM_LEAVES_MENU)),
        min_data_in_leaf=int(rng.choice(MIN_DATA_LEAF_MENU)),
        feature_set=str(rng.choice(FEATURE_SET_MENU)),
    )


def random_individual(rng: np.random.Generator, *, generation: int = 0) -> RankerIndividual:
    return RankerIndividual(
        id=uuid.uuid4().hex[:12],
        generation=generation,
        recipe=random_recipe(rng),
    )


def _pick_menu(rng: np.random.Generator, menu: tuple[Any, ...], current: Any, rate: float) -> Any:
    if rng.random() < rate:
        return menu[int(rng.integers(0, len(menu)))]
    return current


def mutate_recipe(recipe: RankerRecipe, rng: np.random.Generator, *, rate: float = 0.28) -> RankerRecipe:
    return RankerRecipe(
        train_end=str(_pick_menu(rng, TRAIN_END_MENU, recipe.train_end, rate)),
        val_months=int(_pick_menu(rng, VAL_MONTHS_MENU, recipe.val_months, rate)),
        max_symbols=int(_pick_menu(rng, MAX_SYMBOLS_MENU, recipe.max_symbols, rate)),
        ensemble_ml_weight=float(_pick_menu(rng, ENSEMBLE_W_MENU, recipe.ensemble_ml_weight, rate)),
        learning_rate=float(_pick_menu(rng, LEARNING_RATE_MENU, recipe.learning_rate, rate)),
        num_leaves=int(_pick_menu(rng, NUM_LEAVES_MENU, recipe.num_leaves, rate)),
        min_data_in_leaf=int(_pick_menu(rng, MIN_DATA_LEAF_MENU, recipe.min_data_in_leaf, rate)),
        feature_set=str(_pick_menu(rng, FEATURE_SET_MENU, recipe.feature_set, rate)),
    )


def crossover_recipes(a: RankerRecipe, b: RankerRecipe, rng: np.random.Generator) -> RankerRecipe:
    def pick(x: Any, y: Any) -> Any:
        return x if rng.random() < 0.5 else y

    return RankerRecipe(
        train_end=str(pick(a.train_end, b.train_end)),
        val_months=int(pick(a.val_months, b.val_months)),
        max_symbols=int(pick(a.max_symbols, b.max_symbols)),
        ensemble_ml_weight=float(pick(a.ensemble_ml_weight, b.ensemble_ml_weight)),
        learning_rate=float(pick(a.learning_rate, b.learning_rate)),
        num_leaves=int(pick(a.num_leaves, b.num_leaves)),
        min_data_in_leaf=int(pick(a.min_data_in_leaf, b.min_data_in_leaf)),
        feature_set=str(pick(a.feature_set, b.feature_set)),
    )


def breed(
    parent_a: RankerIndividual,
    parent_b: RankerIndividual,
    rng: np.random.Generator,
    *,
    generation: int,
    mutation_rate: float = 0.28,
) -> RankerIndividual:
    child_recipe = mutate_recipe(
        crossover_recipes(parent_a.recipe, parent_b.recipe, rng),
        rng,
        rate=mutation_rate,
    )
    return RankerIndividual(
        id=uuid.uuid4().hex[:12],
        generation=generation,
        recipe=child_recipe,
        parent_ids=(parent_a.id, parent_b.id),
    )
