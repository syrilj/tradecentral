"""Real LightGBM fitness for ranker evolution (sealed fitness asofs only).

Trains a recipe into a fingerprint-keyed cache dir, then scores Rank IC / paper
book on ``protocol.fitness_asofs`` — never on terminal holdout.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from edge.research.ga.ranker_protocol import RankerEvolutionProtocol
from edge.research.ga.ranker_recipe import RankerRecipe

EDGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = EDGE_ROOT / "runs" / "ga_ranker" / "artifacts"
DEFAULT_DATA = (EDGE_ROOT / "data" / "1d_wide", EDGE_ROOT / "data" / "1d")


def _data_dirs() -> tuple[Path, ...]:
    return tuple(p for p in DEFAULT_DATA if p.is_dir())


def train_recipe_artifact(
    recipe: RankerRecipe,
    *,
    cache_dir: Path = DEFAULT_CACHE,
    seed: int = 42,
    num_boost_round: int = 200,
    quiet: bool = True,
) -> Path:
    """Train (or reuse) model for recipe; return artifact directory."""
    from edge.tools.train_qlib_scan_lgb import train

    fp = recipe.fingerprint()
    out = Path(cache_dir) / fp
    marker = out / "PROVENANCE.json"
    if marker.is_file() and (out / "model.txt").is_file():
        return out

    val_start, val_end = recipe.val_window()
    data_dirs = _data_dirs()
    if not data_dirs:
        raise RuntimeError("no local daily data dirs for ranker training")

    out.mkdir(parents=True, exist_ok=True)
    train(
        max_symbols=int(recipe.max_symbols),
        data_dirs=data_dirs,
        out_dir=out,
        seed=seed,
        train_end=recipe.train_end,
        val_start=val_start,
        val_end=val_end,
        source_id=f"ga_ranker_{fp}",
        learning_rate=float(recipe.learning_rate),
        num_leaves=int(recipe.num_leaves),
        min_data_in_leaf=int(recipe.min_data_in_leaf),
        num_boost_round=int(num_boost_round),
        feature_set=str(recipe.feature_set),
        ensemble_ml_weight=float(recipe.ensemble_ml_weight),
        quiet=quiet,
    )
    # Stamp recipe for audit
    (out / "recipe.json").write_text(
        json.dumps(recipe.as_dict(), indent=2) + "\n", encoding="utf-8",
    )
    return out


def real_fitness_fn(
    recipe: RankerRecipe,
    protocol: RankerEvolutionProtocol,
    *,
    cache_dir: Path = DEFAULT_CACHE,
    seed: int = 42,
    num_boost_round: int = 200,
    max_eval_symbols: int | None = None,
    quiet: bool = True,
) -> dict[str, Any]:
    """Fitness = sealed Rank IC (+ soft paper net) on fitness_asofs only."""
    protocol.assert_fitness_dates_sealed(protocol.fitness_asofs)
    from edge.tools.eval_qlib_scan_accuracy import evaluate

    try:
        model_dir = train_recipe_artifact(
            recipe,
            cache_dir=cache_dir,
            seed=seed,
            num_boost_round=num_boost_round,
            quiet=quiet,
        )
    except SystemExit as exc:
        return {
            "fitness": -1e6,
            "alive": False,
            "death_reason": f"train_failed:{exc}",
            "metrics": {"mode": "real_lgb", "error": str(exc)},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "fitness": -1e6,
            "alive": False,
            "death_reason": f"train_error:{type(exc).__name__}:{exc}",
            "metrics": {"mode": "real_lgb", "error": f"{type(exc).__name__}:{exc}"},
        }

    data_dirs = _data_dirs()
    n_sym = int(max_eval_symbols or min(recipe.max_symbols, 120))
    try:
        result = evaluate(
            asofs=list(protocol.fitness_asofs),
            max_symbols=n_sym,
            horizon=5,
            data_dirs=data_dirs,
            top_n=20,
            one_way_cost_bps=5.0,
            model_dir=model_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "fitness": -1e6,
            "alive": False,
            "death_reason": f"eval_error:{type(exc).__name__}:{exc}",
            "metrics": {"mode": "real_lgb", "model_dir": str(model_dir)},
        }

    # Hard seal: refuse if eval somehow used terminal dates
    used = list(result.get("asofs") or [])
    bad = set(used) & set(protocol.terminal_holdout_asofs)
    if bad:
        return {
            "fitness": -1e9,
            "alive": False,
            "death_reason": f"terminal_holdout_leak:{sorted(bad)}",
            "metrics": {"mode": "real_lgb", "fitness_asofs": used},
        }

    mean_ic = result.get("qlib_mean_rank_ic")
    n_days = int(result.get("n_ic_days_qlib") or 0)
    paper = ((result.get("paper_portfolio") or {}).get("augmented") or {}).get("net") or {}
    paper_net = paper.get("mean")
    try:
        mean_ic_f = float(mean_ic) if mean_ic is not None else float("nan")
    except (TypeError, ValueError):
        mean_ic_f = float("nan")
    try:
        paper_f = float(paper_net) if paper_net is not None else 0.0
    except (TypeError, ValueError):
        paper_f = 0.0

    complexity = (
        (recipe.num_leaves / 63.0)
        + (recipe.max_symbols / 280.0)
        + (0.5 if recipe.feature_set == "full16" else 0.0)
    )
    if not math.isfinite(mean_ic_f):
        return {
            "fitness": -1e6,
            "alive": False,
            "death_reason": "rank_ic_nan",
            "metrics": {
                "mode": "real_lgb",
                "model_dir": str(model_dir),
                "fitness_asofs": used,
            },
        }

    fitness = float(mean_ic_f + 0.15 * paper_f - protocol.complexity_penalty * complexity)
    alive = (
        mean_ic_f >= protocol.min_fitness_rank_ic
        and n_days >= protocol.min_fitness_ic_days
    )
    death = None
    if not alive:
        if n_days < protocol.min_fitness_ic_days:
            death = "thin_ic_days"
        else:
            death = "rank_ic_floor"

    return {
        "fitness": fitness,
        "alive": alive,
        "death_reason": death,
        "metrics": {
            "mode": "real_lgb",
            "model_dir": str(model_dir),
            "fingerprint": recipe.fingerprint(),
            "fitness_mean_rank_ic": mean_ic_f,
            "fitness_n_ic_days": n_days,
            "fitness_paper_net_mean": paper_f,
            "fitness_asofs": used,
            "augmented_mean_rank_ic": result.get("augmented_mean_rank_ic"),
            "activity_mean_rank_ic": result.get("activity_mean_rank_ic"),
            "val_window": list(recipe.val_window()),
            "complexity": complexity,
        },
    }


def terminal_eval_recipe(
    recipe: RankerRecipe,
    protocol: RankerEvolutionProtocol,
    *,
    cache_dir: Path = DEFAULT_CACHE,
    seed: int = 42,
    max_eval_symbols: int = 120,
) -> dict[str, Any]:
    """Score a trained recipe on sealed *terminal* holdout only (promote gate)."""
    from edge.tools.eval_qlib_scan_accuracy import evaluate

    model_dir = train_recipe_artifact(recipe, cache_dir=cache_dir, seed=seed, quiet=True)
    return evaluate(
        asofs=list(protocol.terminal_holdout_asofs),
        max_symbols=max_eval_symbols,
        horizon=5,
        data_dirs=_data_dirs(),
        top_n=20,
        one_way_cost_bps=5.0,
        model_dir=model_dir,
    )
