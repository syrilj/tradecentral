from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from edge.research.directional_bakeoff import (
    BakeoffProtocol,
    FEATURE_COLUMNS,
    ScoreCalibrator,
    _model_gate,
    _selection_key,
    build_decision_features,
)


EDGE_ROOT = Path(__file__).resolve().parents[2]


def _bars(periods: int = 340) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-03", periods=periods)
    pieces = []
    for offset, symbol in enumerate(("SPY", "AAA", "BBB")):
        step = np.arange(periods, dtype=float)
        close = 100.0 + offset * 8.0 + 0.05 * step + 2.0 * np.sin(step / (9.0 + offset))
        frame = pd.DataFrame(
            {
                "timestamp": dates,
                "symbol": symbol,
                "open": close * (1.0 + 0.001 * np.cos(step / 5.0)),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000.0 + offset * 50_000.0 + 10_000.0 * np.sin(step / 7.0),
            }
        )
        pieces.append(frame)
    return pd.concat(pieces).set_index(["timestamp", "symbol"]).sort_index()


def test_directional_features_are_shifted_and_future_invariant() -> None:
    bars = _bars()
    sectors = {"SPY": "index", "AAA": "test", "BBB": "test"}
    cutoff = pd.Timestamp("2024-02-01")
    before = build_decision_features(bars, sectors)
    mutated = bars.copy()
    future = mutated.index.get_level_values("timestamp") > cutoff
    mutated.loc[future, ["open", "high", "low", "close"]] *= 4.0
    mutated.loc[future, "volume"] *= 10.0
    after = build_decision_features(mutated, sectors)
    pd.testing.assert_frame_equal(
        before.loc[before.index.get_level_values("timestamp") <= cutoff],
        after.loc[after.index.get_level_values("timestamp") <= cutoff],
    )
    assert tuple(before.columns) == FEATURE_COLUMNS


def test_frozen_directional_universe_exactly_matches_local_research_cache() -> None:
    config = json.loads((EDGE_ROOT / "config" / "universe_directional_v2.json").read_text())
    files = sorted(path.stem for path in (EDGE_ROOT / "data" / "1d").glob("*.parquet"))
    assert sorted(config["symbols"]) == files
    assert len(files) == 60


def test_score_calibration_is_deterministic_and_bounded() -> None:
    scores = np.linspace(-2.0, 2.0, 200)
    labels = (scores + 0.2 * np.sin(np.arange(200)) > 0).astype(int)
    first = ScoreCalibrator().fit(scores, labels).apply(scores)
    second = ScoreCalibrator().fit(scores, labels).apply(scores)
    np.testing.assert_allclose(first, second)
    assert np.all((first > 0.0) & (first < 1.0))
    assert np.all(np.diff(first) > 0.0)


def _metrics(*, accurate: bool) -> dict[str, object]:
    lower = 0.54 if accurate else 0.48
    return {
        "pooled_auc": 0.57 if accurate else 0.49,
        "date_mean_auc": 0.56 if accurate else 0.49,
        "date_mean_auc_ci": {"lower": lower},
        "brier_skill": 0.03 if accurate else -0.01,
        "adaptive_ece": 0.02,
        "calibration_slope": 1.0,
        "coverage": {
            "10pct": {
                "accuracy": 0.61 if accurate else 0.50,
                "accuracy_ci": {"lower": 0.56 if accurate else 0.46},
                "net_expectancy_ci": {"lower": 0.002 if accurate else -0.002},
            },
            "100pct": {"accuracy": 0.54 if accurate else 0.50},
        },
        "net_difference_vs_momentum_ci": {"lower": 0.001 if accurate else -0.001},
    }


def test_confirmation_gate_requires_discrimination_calibration_selectivity_and_costs() -> None:
    assert _model_gate(_metrics(accurate=True))["passed"] is True
    rejected = _model_gate(_metrics(accurate=False))
    assert rejected["passed"] is False
    assert "date_auc_lower_bound_above_random" in rejected["failed_checks"]
    assert "selective_net_lower_bound_positive" in rejected["failed_checks"]


def test_selection_rule_prefers_high_confidence_accuracy_lower_bound() -> None:
    stronger = _metrics(accurate=True)
    weaker = _metrics(accurate=True)
    weaker["coverage"]["10pct"]["accuracy_ci"]["lower"] = 0.55
    assert _selection_key(("elastic_net", stronger)) > _selection_key(("xgboost", weaker))


def test_protocol_keeps_confirmation_before_sealed_holdout() -> None:
    protocol = BakeoffProtocol()
    assert pd.Timestamp(protocol.selection_end) < pd.Timestamp(protocol.confirmation_start)
    assert pd.Timestamp(protocol.development_end) < pd.Timestamp(protocol.terminal_holdout_start)
