from __future__ import annotations

from datetime import date

import numpy as np

from research.decision_tree_backtest import CausalTree, FEATURES, run_last_week_backtest


def test_dependency_light_cart_is_deterministic_and_bounded():
    rng = np.random.default_rng(17)
    x = rng.normal(size=(600, len(FEATURES)))
    y = ((x[:, 0] > 0.2) | (x[:, 4] < -0.8)).astype(int)

    first = CausalTree(max_depth=3, min_leaf=30).fit(x, y)
    second = CausalTree(max_depth=3, min_leaf=30).fit(x, y)

    p1 = first.predict_probability(x)
    p2 = second.predict_probability(x)
    assert np.array_equal(p1, p2)
    assert np.all((0.0 <= p1) & (p1 <= 1.0))
    assert first.explain(x[0])[-1].startswith("leaf ")


def test_last_completed_week_is_a_strict_unseen_holdout():
    result = run_last_week_backtest()

    assert result["schema_version"] == "decision-tree-oos-v1"
    assert result["status"] == "research_only"
    assert result["decision_authorized"] is False
    assert result["protocol"]["holdout_used_for_training"] is False
    assert date.fromisoformat(result["window"]["training_end"]) < date.fromisoformat(
        result["window"]["holdout_start"]
    )
    assert result["window"]["sessions"] == 5
    assert result["universe"]["training_rows"] > result["universe"]["holdout_rows"]
    assert result["comparison"]["baseline"]["observations"] == result["universe"]["holdout_rows"]

    spcx = result["focus"]["rows"]
    assert len(spcx) == 5
    assert all(
        date.fromisoformat(row["signal_asof"]) < date.fromisoformat(row["session_date"])
        for row in spcx
    )
    # The holdout rolls each week; a fixed 2026-09-16 event is no longer in
    # the latest window. Every abstention must remain below the threshold.
    threshold = result["model"]["confidence_threshold"]
    assert all(
        row["confidence"] < threshold
        for row in spcx
        if row["active"] is False
    )
    assert all(
        result["window"]["holdout_start"] <= row["session_date"] <= result["window"]["holdout_end"]
        for row in spcx
    )
