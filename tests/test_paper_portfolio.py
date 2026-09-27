"""Paper portfolio evaluation drives the shipped scorer (not a reimplementation)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.daily_plays.qlib_scan_score import score_cross_section_asof
from edge.tools.eval_qlib_scan_accuracy import evaluate, paper_long_topn


def _frames(n: int = 40, periods: int = 300) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    dates = pd.bdate_range("2024-01-02", periods=periods)
    for i in range(n):
        rng = np.random.default_rng(50 + i)
        rets = rng.normal(0.0003, 0.015, size=periods)
        rets[-1] = rng.normal(0, 0.04)
        close = 30.0 * np.cumprod(1.0 + rets)
        out[f"P{i:02d}"] = pd.DataFrame(
            {
                "open": np.r_[close[0], close[:-1]],
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": rng.integers(1e5, 2e6, size=periods).astype(float),
            },
            index=dates,
        )
    return out


def test_paper_long_topn_uses_score_maps_and_subtracts_costs():
    scores = {
        "2024-06-07": {"A": 2.0, "B": 1.0, "C": 0.0, "D": -1.0},
        "2024-06-14": {"A": 0.5, "B": 2.0, "C": 1.5, "D": -0.5},
    }
    # A is best score day1 → high fwd; B best day2
    fwd = {
        "2024-06-07": {"A": 0.05, "B": -0.01, "C": 0.0, "D": 0.02},
        "2024-06-14": {"A": -0.02, "B": 0.04, "C": 0.01, "D": 0.0},
    }
    book = paper_long_topn(scores, fwd, top_n=1, one_way_cost_bps=5.0, min_names=2)
    assert book["periods"][0]["names"] == ["A"]
    assert book["periods"][1]["names"] == ["B"]
    # Gross day1 = 0.05, RT cost = 10 bps = 0.001 → net 0.049
    assert abs(book["periods"][0]["gross_return"] - 0.05) < 1e-12
    assert abs(book["periods"][0]["net_return"] - (0.05 - 0.001)) < 1e-12
    assert book["decision_authorized"] is False
    assert book["net"]["n_periods"] == 2
    assert book["net"]["mean"] is not None


def test_evaluate_paper_portfolio_drives_shipped_scorer(monkeypatch, tmp_path):
    frames = _frames()
    asof = frames["P00"].index[-8].strftime("%Y-%m-%d")

    import edge.tools.eval_qlib_scan_accuracy as mod

    monkeypatch.setattr(mod, "load_market_symbol_catalog", lambda **_: list(frames))
    monkeypatch.setattr(
        mod,
        "_load_close_panel",
        lambda symbols, data_dirs: {s: frames[s] for s in symbols if s in frames},
    )

    result = evaluate(
        asofs=[asof],
        max_symbols=len(frames),
        horizon=5,
        data_dirs=(tmp_path,),
        top_n=5,
        one_way_cost_bps=5.0,
    )
    assert "paper_portfolio" in result
    paper = result["paper_portfolio"]
    assert paper["top_n"] == 5
    assert "activity" in paper and "qlib" in paper and "augmented" in paper
    # Scorer must have produced names for the paper book path.
    assert result["days"][0]["qlib_scored"] > 0
    # Direct scorer call still works (same entry deep scan uses).
    panel = score_cross_section_asof(
        symbols=list(frames),
        asof=asof,
        candle_loader=frames.__getitem__,
    )
    assert panel["quality"] == "ok"
    assert panel["coverage"]["scored"] == len(frames)
