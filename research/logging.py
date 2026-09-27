"""
Structured JSONL Decision Log Manager.

Persists every strategy decision, timestamp, input feature vector, prediction,
proposed position/order intent, expected fill/cost, and safety/rejection reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd

from .decision import DecisionOutput


class DecisionLogger:
    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(
        self,
        decision_ts: pd.Timestamp,
        output: DecisionOutput,
        execution_mode: str = "SHADOW",
    ) -> None:
        record = {
            "decision_ts": str(decision_ts),
            "execution_mode": execution_mode,
            "decision_output": output.as_dict(),
        }

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def read_logged_decisions(self) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        records = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line.strip()))
        return records
