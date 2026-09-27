from __future__ import annotations

import numpy as np
import pandas as pd

from edge.daily_plays.adapters import pead_adapter


def test_pead_gap_score_is_ordinal_and_never_fabricates_confidence(monkeypatch):
    dates = pd.date_range("2026-06-01", periods=40, freq="B")
    close = np.full(len(dates), 100.0)
    open_ = close.copy()
    open_[-1] = 110.0
    volume = np.full(len(dates), 1_000_000.0)
    volume[-1] = 5_000_000.0
    frame = pd.DataFrame({
        "Open": open_,
        "High": np.maximum(open_, close) + 1.0,
        "Low": np.minimum(open_, close) - 1.0,
        "Close": close,
        "Volume": volume,
    }, index=dates)
    monkeypatch.setattr(pead_adapter, "_load_symbol_df", lambda _symbol: frame)

    rows = pead_adapter.generate_pead_candidates(symbols=["AAA"])

    assert len(rows) == 1
    assert rows[0]["model"]["confidence_kind"] == "ordinal_score"
    assert rows[0]["model"]["probability"] is None
    assert rows[0]["model"]["state"] == "FLAG"
    assert rows[0]["model"]["promotion_authorized"] is False
    assert rows[0]["decision_authorized"] is False
    assert "pead_gate_no_go" in rows[0]["model"]["reasons"]
