"""Tests for deep-scan ranker multi-parent evolution (sealed fitness)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge.research.ga.ranker_evolve import (
    evaluate_individual,
    run_ranker_evolution,
    select_elites,
    smoke_ranker_evolution,
    synthetic_fitness_fn,
    tournament_select,
)
from edge.research.ga.ranker_protocol import RankerEvolutionProtocol
from edge.research.ga.ranker_recipe import (
    TRAIN_END_MENU,
    RankerIndividual,
    RankerRecipe,
    breed,
    mutate_recipe,
    random_individual,
    random_recipe,
)
from edge.research.qlib_scan_feedback import FeedbackGates, OosSnapshot, decide_promotion


def test_protocol_rejects_fitness_terminal_overlap():
    with pytest.raises(ValueError, match="overlap terminal"):
        RankerEvolutionProtocol(
            fitness_asofs=("2025-06-30", "2025-09-30"),
            confirmation_asofs=("2024-01-02",),
            terminal_holdout_asofs=("2025-06-30", "2026-03-31"),
        )


def test_protocol_assert_fitness_dates_sealed():
    proto = RankerEvolutionProtocol()
    proto.assert_fitness_dates_sealed(proto.fitness_asofs)
    with pytest.raises(ValueError, match="terminal holdout"):
        proto.assert_fitness_dates_sealed(["2024-06-28", "2025-06-30"])


def test_recipe_menus_reject_unknown_train_end():
    with pytest.raises(ValueError, match="train_end"):
        RankerRecipe(
            train_end="2019-01-01",
            val_months=6,
            max_symbols=120,
            ensemble_ml_weight=0.65,
            learning_rate=0.025,
            num_leaves=48,
            min_data_in_leaf=120,
            feature_set="full16",
        )


def test_mutate_and_breed_stay_in_menus():
    rng = np.random.default_rng(0)
    for _ in range(40):
        r = random_recipe(rng)
        m = mutate_recipe(r, rng, rate=0.9)
        assert m.train_end in TRAIN_END_MENU
        a = random_individual(rng, generation=0)
        b = random_individual(rng, generation=0)
        child = breed(a, b, rng, generation=1)
        assert child.parent_ids == (a.id, b.id)
        assert child.recipe.train_end in TRAIN_END_MENU


def test_select_elites_are_highest_fitness_alive():
    recipes = [
        RankerRecipe(
            train_end=TRAIN_END_MENU[0],
            val_months=6,
            max_symbols=120,
            ensemble_ml_weight=0.65,
            learning_rate=0.025,
            num_leaves=48,
            min_data_in_leaf=120,
            feature_set="core5",
        )
        for _ in range(5)
    ]
    pop = [
        RankerIndividual(id="a", generation=0, recipe=recipes[0], fitness=0.01, alive=True),
        RankerIndividual(id="b", generation=0, recipe=recipes[1], fitness=0.05, alive=True),
        RankerIndividual(id="c", generation=0, recipe=recipes[2], fitness=0.99, alive=False, death_reason="dead"),
        RankerIndividual(id="d", generation=0, recipe=recipes[3], fitness=0.03, alive=True),
        RankerIndividual(id="e", generation=0, recipe=recipes[4], fitness=None, alive=False),
    ]
    elites = select_elites(pop, elite_n=2)
    assert [e.id for e in elites] == ["b", "d"]
    assert all(e.alive for e in elites)
    assert elites[0].fitness >= elites[1].fitness


def test_evaluate_kills_terminal_holdout_leak_in_metrics():
    proto = RankerEvolutionProtocol()
    ind = random_individual(np.random.default_rng(1), generation=0)

    def leaky_fn(recipe, protocol):
        return {
            "fitness": 0.5,
            "alive": True,
            "death_reason": None,
            "metrics": {
                "fitness_asofs": list(protocol.fitness_asofs) + [protocol.terminal_holdout_asofs[0]],
            },
        }

    evaluate_individual(ind, proto, leaky_fn)
    assert ind.alive is False
    assert ind.death_reason and "terminal_holdout_leak" in ind.death_reason


def test_synthetic_fitness_never_uses_terminal_dates():
    proto = RankerEvolutionProtocol()
    recipe = random_recipe(np.random.default_rng(2))
    out = synthetic_fitness_fn(recipe, proto, seed=2)
    asofs = out["metrics"]["fitness_asofs"]
    assert not set(asofs) & set(proto.terminal_holdout_asofs)
    assert set(asofs) <= set(proto.fitness_asofs)


def test_smoke_evolution_writes_history_and_elites(tmp_path: Path):
    result = smoke_ranker_evolution(output_dir=tmp_path, seed=7, run_id="test_smoke_a")
    assert result.decision_authorized is False
    assert len(result.history) >= 2
    assert len(result.elites) >= 1
    summary = tmp_path / "test_smoke_a" / "summary.json"
    history = tmp_path / "test_smoke_a" / "history.json"
    elites = tmp_path / "test_smoke_a" / "elites.json"
    assert summary.is_file()
    assert history.is_file()
    assert elites.is_file()
    # Elites must be highest-fitness survivors among last gen metrics
    best_hist = result.history[-1]["best_fitness"]
    elite_fits = [e["fitness"] for e in result.elites if e.get("fitness") is not None]
    assert elite_fits
    assert max(elite_fits) == pytest.approx(best_hist, rel=0, abs=1e-9)


def test_run_evolution_multi_gen_improves_or_stable_best(tmp_path: Path):
    """Selection pressure: final best fitness ≥ first-gen best (soft, synthetic)."""
    result = run_ranker_evolution(
        config=__import__("edge.research.ga.ranker_evolve", fromlist=["RankerEvolveConfig"]).RankerEvolveConfig(
            population_size=16,
            n_generations=4,
            elite_fraction=0.25,
            tournament_size=3,
            mutation_rate=0.2,
            random_state=11,
            run_confirmation=False,
            attempt_promote=False,
        ),
        output_dir=tmp_path,
        run_id="test_pressure",
    )
    first = result.history[0]["best_fitness"]
    last = result.history[-1]["best_fitness"]
    # Elitism should not lose the best genome fitness
    assert last + 1e-12 >= first


def test_promote_fail_closed_when_gates_fail():
    challenger = OosSnapshot(
        source_id="ch",
        mean_rank_ic=-0.01,
        activity_mean_rank_ic=0.02,
        augmented_mean_rank_ic=0.0,
        non_worse_than_activity=False,
        pure_non_worse_than_activity=False,
        n_ic_days=5,
        paper_net_mean=-0.001,
        paper_n_periods=5,
    )
    decision = decide_promotion(
        challenger=challenger,
        champion=None,
        gates=FeedbackGates(),
    )
    assert decision.promote is False
    assert decision.to_dict()["decision_authorized"] is False


def test_tournament_prefers_alive_higher_fitness():
    rng = np.random.default_rng(0)
    r = random_recipe(rng)
    pop = [
        RankerIndividual(id="weak", generation=0, recipe=r, fitness=0.01, alive=True),
        RankerIndividual(id="strong", generation=0, recipe=r, fitness=0.08, alive=True),
        RankerIndividual(id="dead", generation=0, recipe=r, fitness=0.5, alive=False),
    ]
    # With k=3 always includes strong when present
    winner = tournament_select(pop, rng, k=3)
    assert winner.id == "strong"
