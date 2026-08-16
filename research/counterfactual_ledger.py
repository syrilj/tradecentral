"""
Counterfactual Decision Ledger for Agentic Trading Systems.

Provides an append-only, auditable journal recording every agent trade decision,
its paired counterfactual non-agent baseline trajectory, and realized horizon returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
from typing import Dict, List, Any, Union


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: str
    symbol: str
    portfolio_before_weight: float
    quant_action: str
    quant_target_weight: float
    agent_action: str  # NO_OP, ADJUST, OVERRIDE, VETO
    agent_target_weight: float
    agent_reason: str
    agent_confidence: float
    signals: Dict[str, float] = field(default_factory=dict)
    llm_model: str = "gpt-4o"
    tokens_used: Dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0})
    llm_cost_usd: float = 0.0
    execution_cost_usd: float = 0.0
    horizon_outcomes: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DecisionRecord:
        return cls(**data)


class CounterfactualLedger:
    """Append-only JSON-L storage for agent decisions and counterfactual realizations."""

    def __init__(self, ledger_path: Union[str, Path]):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def append_decision(self, record: DecisionRecord) -> None:
        """Appends a new decision record to the JSON-L ledger."""
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def load_records(self) -> List[DecisionRecord]:
        """Loads all decision records from the ledger."""
        if not self.ledger_path.exists():
            return []

        records: List[DecisionRecord] = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        records.append(DecisionRecord.from_dict(data))
                    except (json.JSONDecodeError, TypeError, KeyError):
                        continue
        return records

    def record_horizon_outcome(
        self,
        decision_id: str,
        horizon_days: str,
        realized_agent_pnl: float,
        counterfactual_pnl: float,
    ) -> bool:
        """
        Updates the realization outcome for a decision record.
        Re-writes ledger safely with updated realization values.
        """
        records = self.load_records()
        updated = False

        for rec in records:
            if rec.decision_id == decision_id:
                delta_pnl = float(realized_agent_pnl - counterfactual_pnl)
                rec.horizon_outcomes[str(horizon_days)] = {
                    "realized_agent_pnl": float(realized_agent_pnl),
                    "counterfactual_pnl": float(counterfactual_pnl),
                    "delta_pnl": delta_pnl,
                }
                updated = True
                break

        if updated:
            with open(self.ledger_path, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec.to_dict()) + "\n")

        return updated
