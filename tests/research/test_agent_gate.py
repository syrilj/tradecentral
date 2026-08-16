"""Unit tests for AgentGate module."""

try:
    from edge.research.counterfactual_ledger import DecisionRecord
    from edge.research.agent_gate import AgentGate, AgentGatingConfig
except ImportError:
    from research.counterfactual_ledger import DecisionRecord
    from research.agent_gate import AgentGate, AgentGatingConfig


def test_agent_gate_uncalibrated_fallback():
    gate = AgentGate(AgentGatingConfig(min_records_required=5))

    # Evaluate without enough records
    res = gate.evaluate_gate({"volatility": 1.0, "momentum": 0.5})
    assert res["should_invoke_agent"] is False
    assert res["is_calibrated"] is False


def test_agent_gate_calibration_and_evaluation():
    gate = AgentGate(AgentGatingConfig(min_records_required=6, min_prob_threshold=0.60))

    records = []
    # Create 10 synthetic historical records with high momentum predicting positive ΔPnL
    for i in range(10):
        mom = float(i)
        win = 1.0 if i >= 4 else -1.0
        rec = DecisionRecord(
            decision_id=f"dec_{i}",
            timestamp="2026-08-07T12:00:00Z",
            symbol="AAPL",
            portfolio_before_weight=0.05,
            quant_action="BUY",
            quant_target_weight=0.05,
            agent_action="ADJUST",
            agent_target_weight=0.08,
            agent_reason="momentum",
            agent_confidence=0.8,
            signals={"volatility": 0.02, "momentum": mom, "spread_bps": 5.0, "confidence": 0.8},
            horizon_outcomes={"5d": {"realized_agent_pnl": win * 100, "counterfactual_pnl": 0.0, "delta_pnl": win * 100}},
        )
        records.append(rec)

    fitted = gate.fit_from_ledger(records)
    assert fitted is True
    assert gate.is_calibrated is True

    # High momentum -> high P(ΔPnL > 0) -> should pass gate
    pass_res = gate.evaluate_gate({"volatility": 0.02, "momentum": 9.0, "spread_bps": 5.0, "confidence": 0.8})
    assert pass_res["should_invoke_agent"] is True

    # Low momentum -> low P(ΔPnL > 0) -> should fail gate
    fail_res = gate.evaluate_gate({"volatility": 0.02, "momentum": 0.0, "spread_bps": 5.0, "confidence": 0.8})
    assert fail_res["should_invoke_agent"] is False
