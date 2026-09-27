"""TDD for the zero-fit desk ranker (regime-conditioned rev5 + mom12_1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.qlib_scan_score import score_cross_section_asof
from edge.daily_plays.desk_ranker import (
    ENTER_PERCENTILE,
    EXIT_PERCENTILE,
    HORIZON_DAYS,
    REGIME_WEIGHTS,
    SOURCE_ID,
    hysteresis_holdings,
    literature_features,
    regime_weights,
    score_feature_table,
    skip_day_forward_return,
)


def _close_series(values: list[float], start: str = "2022-01-03") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_regime_weights_are_frozen_and_sum_to_one():
    for regime, weights in REGIME_WEIGHTS.items():
        assert set(weights) == {"rev5", "mom12_1"}
        assert abs(sum(weights.values()) - 1.0) < 1e-12
        assert weights["rev5"] > 0 and weights["mom12_1"] > 0
    assert REGIME_WEIGHTS["HIGH"]["rev5"] > REGIME_WEIGHTS["LOW"]["rev5"]
    assert REGIME_WEIGHTS["LOW"]["mom12_1"] > REGIME_WEIGHTS["HIGH"]["mom12_1"]
    assert regime_weights("MEDIUM") == REGIME_WEIGHTS["MEDIUM"]
    assert regime_weights("unknown") == REGIME_WEIGHTS["MEDIUM"]


def test_literature_features_use_predicted_positive_signs():
    # 5-session drop then flat: rev5 must be positive (loser → bounce prior).
    closes = [100.0] * 260
    for i in range(1, 6):
        closes[-i] = 100.0 - i  # last 5 days sold off
    # 12-month winner excluding last month: close[-22] >> close[-253]
    closes[-253] = 50.0
    closes[-22] = 90.0
    feats = literature_features(_close_series(closes))
    assert feats["rev5"] is not None and feats["rev5"] > 0
    assert feats["mom12_1"] is not None and feats["mom12_1"] > 0


def test_score_feature_table_ranks_losers_above_winners_in_high_vol():
    table = {
        "LOSER": {"rev5": 0.08, "mom12_1": -0.10},
        "WINNER": {"rev5": -0.08, "mom12_1": 0.10},
        "MID": {"rev5": 0.0, "mom12_1": 0.0},
    }
    high = score_feature_table(table, vol_regime="HIGH")
    low = score_feature_table(table, vol_regime="LOW")
    assert high["LOSER"] > high["WINNER"]
    # Calm regime must lean more on momentum than the stress regime.
    assert (low["WINNER"] - low["LOSER"]) > (high["WINNER"] - high["LOSER"])
    assert high["source"] == SOURCE_ID


def test_cross_section_uses_rank_then_z_so_fat_tails_do_not_flip_order():
    """GATE_DESK_RANKER freezes rank → z. A 100σ loser must score like a 1σ loser."""
    mild = {
        "EXTREME": {"rev5": 0.09, "mom12_1": 0.0},
        "HIGH": {"rev5": 0.08, "mom12_1": 0.0},
        "LOW": {"rev5": -0.08, "mom12_1": 0.0},
    }
    wild = {
        "EXTREME": {"rev5": 10.0, "mom12_1": 0.0},
        "HIGH": {"rev5": 0.08, "mom12_1": 0.0},
        "LOW": {"rev5": -0.08, "mom12_1": 0.0},
    }
    mild_scores = score_feature_table(mild, vol_regime="MEDIUM").scores
    wild_scores = score_feature_table(wild, vol_regime="MEDIUM").scores
    assert mild_scores["EXTREME"] == pytest.approx(wild_scores["EXTREME"])
    assert mild_scores["HIGH"] == pytest.approx(wild_scores["HIGH"])
    assert mild_scores["LOW"] == pytest.approx(wild_scores["LOW"])
    assert wild_scores["EXTREME"] > wild_scores["HIGH"] > wild_scores["LOW"]


def test_skip_day_forward_return_ignores_decision_bar_and_needs_horizon():
    close = _close_series([10, 11, 12, 13, 14, 15, 16, 17])
    decision = close.index[0]
    # Entry is next bar (11), exit is the 5th bar after entry (16) → 16/11 - 1.
    got = skip_day_forward_return(close, decision, horizon=HORIZON_DAYS)
    assert got == pytest.approx(16 / 11 - 1.0)
    short = close.iloc[:3]
    assert skip_day_forward_return(short, short.index[0], horizon=HORIZON_DAYS) is None


def test_hysteresis_enters_top_quintile_and_does_not_churn_the_border():
    scores = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4, "E": 0.2}
    first = hysteresis_holdings(scores, held=set())
    # 5 names → enter percentile ≥ 0.80 means the top name only? 
    # percentile rank: A=1.0, B=0.8, C=0.6, D=0.4, E=0.2 → A and B at/above 0.80.
    assert first == {"A", "B"}
    assert ENTER_PERCENTILE == 0.80
    assert EXIT_PERCENTILE == 0.65
    # C is 0.60 < 0.65, so a prior hold of C is dropped; B stays.
    stayed = hysteresis_holdings(scores, held={"B", "C"})
    assert "B" in stayed
    assert "C" not in stayed
    assert "A" in stayed


def _ranker_bars(*, last_ret: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=280)
    rets = rng.normal(0.0004, 0.012, size=280)
    rets[-1] = last_ret
    close = 80.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(280, 1_000_000.0),
        },
        index=dates,
    )


def test_scan_engine_desk_ranker_does_not_use_lightgbm_source():
    frames = {
        "LOSER": _ranker_bars(last_ret=-0.07, seed=1),
        "WINNER": _ranker_bars(last_ret=0.07, seed=2),
        "MID": _ranker_bars(last_ret=0.0, seed=3),
        "SPY": _ranker_bars(last_ret=0.0, seed=4),
    }
    panel = score_cross_section_asof(
        symbols=list(frames),
        asof=frames["LOSER"].index[-1],
        candle_loader=frames.__getitem__,
        engine="desk_ranker",
    )
    assert panel["quality"] == "ok"
    assert panel["source"] == SOURCE_ID
    assert panel["decision_authorized"] is False
    assert panel["by_symbol"]["LOSER"]["qlib_rank"] < panel["by_symbol"]["WINNER"]["qlib_rank"]
