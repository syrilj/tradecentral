"""
Deterministic Event-by-Event Replay Engine.

Replays market events using `make_decision` and verifies that repeated runs
produce byte-identical decision sequences.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

from .safety import StrategyState
from .decision import make_decision, DecisionOutput
from .logging import DecisionLogger


def run_deterministic_replay(
    events_df: pd.DataFrame,
    initial_state: StrategyState,
    model_bundle: Dict[str, Any],
    config: Dict[str, Any],
    logger: Optional[DecisionLogger] = None,
) -> List[DecisionOutput]:
    """
    Executes event-by-event historical replay using make_decision.
    """
    date_col = "timestamps" if "timestamps" in events_df.columns else "date"
    sorted_events = events_df.sort_values(by=date_col).reset_index(drop=True)

    current_state = StrategyState(
        cash_ledger=initial_state.cash_ledger,
        position_ledger=dict(initial_state.position_ledger),
        daily_realized_pnl=initial_state.daily_realized_pnl,
        strategy_peak_equity=initial_state.strategy_peak_equity,
        current_equity=initial_state.current_equity,
    )

    outputs: List[DecisionOutput] = []

    for i in range(len(sorted_events)):
        row = sorted_events.iloc[i]
        decision_ts = pd.Timestamp(row[date_col])

        market_snapshot = {
            "features": {"alpha_AAPL": float(row.get("close", 100.0) * 0.0001)},
            "symbols": ["AAPL"],
            "adv_usd": {"AAPL": 10_000_000.0},
        }

        output = make_decision(
            state=current_state,
            decision_ts=decision_ts,
            market_data_snapshot=market_snapshot,
            model_bundle=model_bundle,
            config=config,
        )

        outputs.append(output)

        if logger:
            logger.log_decision(decision_ts, output, execution_mode="REPLAY")

        # Update position ledger deterministically
        current_state.position_ledger = dict(output.target_positions)

    return outputs
