"""
Statistical Agent Gating Engine for TradeLens++.

Evaluates P(ΔPnL_agent > 0 | X_t) using historical counterfactual records.
Determines whether an LLM Agent is permitted to intervene or if the system
should execute the pure quantitative signal without calling the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

try:
    from edge.research.counterfactual_ledger import DecisionRecord, CounterfactualLedger
except ImportError:
    from research.counterfactual_ledger import DecisionRecord, CounterfactualLedger


@dataclass
class AgentGatingConfig:
    min_prob_threshold: float = 0.70
    min_records_required: int = 10
    horizon_key: str = "5d"
    features_to_use: Tuple[str, ...] = ("volatility", "momentum", "spread_bps", "confidence")


class AgentGate:
    """Statistical model gating agent intervention on P(ΔPnL > 0 | X_t)."""

    def __init__(self, config: Optional[AgentGatingConfig] = None):
        self.cfg = config or AgentGatingConfig()
        self.model: Optional[LogisticRegression] = None
        self.is_calibrated: bool = False
        self.historical_records: List[DecisionRecord] = []

    def fit_from_ledger(self, records: List[DecisionRecord]) -> bool:
        """Fits the gating probability model on completed counterfactual outcomes."""
        self.historical_records = records

        X_rows: List[List[float]] = []
        y_rows: List[int] = []

        for rec in records:
            if self.cfg.horizon_key not in rec.horizon_outcomes:
                continue

            outcome = rec.horizon_outcomes[self.cfg.horizon_key]
            delta_pnl = outcome.get("delta_pnl", 0.0)

            # Feature vector X_t
            feat_vec = [float(rec.signals.get(k, 0.0)) for k in self.cfg.features_to_use]
            X_rows.append(feat_vec)
            y_rows.append(1 if delta_pnl > 0.0 else 0)

        if len(y_rows) < self.cfg.min_records_required or len(set(y_rows)) < 2:
            self.is_calibrated = False
            self.model = None
            return False

        X_mat = np.array(X_rows, dtype=float)
        y_vec = np.array(y_rows, dtype=int)

        clf = LogisticRegression(C=1.0, max_iter=1000)
        clf.fit(X_mat, y_vec)
        self.model = clf
        self.is_calibrated = True
        return True

    def evaluate_gate(self, market_state: Dict[str, float]) -> Dict[str, Any]:
        """
        Evaluates whether agent intervention is permitted given market state X_t.
        Returns dict with `should_invoke_agent`, `win_probability`, and `reason`.
        """
        if not self.is_calibrated or self.model is None:
            return {
                "should_invoke_agent": False,
                "win_probability": 0.50,
                "reason": f"Insufficient historical counterfactual records (< {self.cfg.min_records_required}). Defaulting to Pure Quant Engine.",
                "is_calibrated": False,
            }

        feat_vec = np.array([[float(market_state.get(k, 0.0)) for k in self.cfg.features_to_use]], dtype=float)
        probs = self.model.predict_proba(feat_vec)[0]
        p_win = float(probs[1])

        should_invoke = p_win >= self.cfg.min_prob_threshold
        reason = (
            f"Estimated P(ΔPnL > 0) = {p_win:.3f} >= threshold {self.cfg.min_prob_threshold:.2f}. Agent intervention permitted."
            if should_invoke
            else f"Estimated P(ΔPnL > 0) = {p_win:.3f} < threshold {self.cfg.min_prob_threshold:.2f}. Agent intervention bypassed to save cost & noise."
        )

        return {
            "should_invoke_agent": should_invoke,
            "win_probability": p_win,
            "reason": reason,
            "is_calibrated": True,
        }
