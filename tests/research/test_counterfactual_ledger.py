"""Unit tests for Counterfactual Ledger module."""
import pytest
from pathlib import Path
import tempfile

try:
    from edge.research.counterfactual_ledger import DecisionRecord, CounterfactualLedger
except ImportError:
    from research.counterfactual_ledger import DecisionRecord, CounterfactualLedger


def test_counterfactual_ledger_append_and_load(tmp_path):
    ledger_file = tmp_path / "test_ledger.jsonl"
    ledger = CounterfactualLedger(ledger_file)

    rec1 = DecisionRecord(
        decision_id="dec_001",
        timestamp="2026-08-07T14:00:00Z",
        symbol="NVDA",
        portfolio_before_weight=0.08,
        quant_action="HOLD",
        quant_target_weight=0.08,
        agent_action="REDUCE",
        agent_target_weight=0.04,
        agent_reason="semiconductor regime deterioration",
        agent_confidence=0.71,
        signals={"momentum": -0.82, "volatility": 1.21},
        llm_model="gpt-4o",
        tokens_used={"prompt": 8000, "completion": 340},
        llm_cost_usd=0.082,
        execution_cost_usd=2.41,
    )

    ledger.append_decision(rec1)
    loaded = ledger.load_records()
    assert len(loaded) == 1
    assert loaded[0].decision_id == "dec_001"
    assert loaded[0].agent_action == "REDUCE"

    # Record realization outcome
    success = ledger.record_horizon_outcome(
        decision_id="dec_001",
        horizon_days="5d",
        realized_agent_pnl=150.0,
        counterfactual_pnl=-300.0,
    )

    assert success is True
    reloaded = ledger.load_records()
    assert "5d" in reloaded[0].horizon_outcomes
    assert reloaded[0].horizon_outcomes["5d"]["delta_pnl"] == 450.0
