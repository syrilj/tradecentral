"""
Unit tests for Workstream 6 & 7: Deterministic Strategy Decision Interface & Replay Parity.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

try:
    from edge.research.safety import StrategyState, SafetyConfig
    from edge.research.decision import make_decision, DecisionOutput
    from edge.research.replay import run_deterministic_replay
except ImportError:
    from research.safety import StrategyState, SafetyConfig
    from research.decision import make_decision, DecisionOutput
    from research.replay import run_deterministic_replay


def test_make_decision_deterministic_reproducibility():
    """Verify that repeated calls to make_decision with identical inputs produce byte-identical outputs."""
    state = StrategyState(cash_ledger=100_000.0, position_ledger={"AAPL": 0.05})
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")

    snapshot = {
        "features": {"pred_AAPL": 0.08, "pred_MSFT": 0.03},
        "symbols": ["AAPL", "MSFT"],
        "adv_usd": {"AAPL": 20_000_000.0, "MSFT": 20_000_000.0},
    }

    model_bundle = {"version": "v90_meta_confidence", "predict_fn": None}
    config = {}

    res1 = make_decision(state, decision_ts, snapshot, model_bundle, config)
    res2 = make_decision(state, decision_ts, snapshot, model_bundle, config)

    assert res1.as_dict() == res2.as_dict()


def test_replay_parity():
    """Verify that deterministic historical replay produces identical decision series across multiple runs."""
    dates = pd.bdate_range("2026-01-01", periods=10)
    events_df = pd.DataFrame({"timestamps": dates, "close": 150.0 + np.arange(10)})

    initial_state = StrategyState(cash_ledger=100_000.0, position_ledger={"AAPL": 0.0})
    model_bundle = {"version": "v90_meta_confidence", "predict_fn": None}
    config = {}

    run1 = run_deterministic_replay(events_df, initial_state, model_bundle, config)
    run2 = run_deterministic_replay(events_df, initial_state, model_bundle, config)

    assert len(run1) == len(run2) == 10
    for d1, d2 in zip(run1, run2):
        assert d1.as_dict() == d2.as_dict()
