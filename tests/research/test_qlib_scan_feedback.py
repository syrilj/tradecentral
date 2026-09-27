"""Unit tests for deep-scan feedback gates and OOS iteration helpers."""
from __future__ import annotations

from edge.research.qlib_scan_feedback import (
    FeedbackGates,
    OosSnapshot,
    decide_promotion,
    expanding_oos_windows,
    snapshot_from_eval,
    summarize_window_ics,
)


def _snap(
    *,
    source_id: str = "challenger",
    mean_rank_ic: float | None = 0.02,
    activity_mean_rank_ic: float | None = 0.01,
    augmented_mean_rank_ic: float | None = 0.025,
    non_worse: bool | None = True,
    pure_non_worse: bool | None = True,
    n_ic_days: int = 5,
    paper_net_mean: float | None = 0.002,
    paper_n_periods: int = 5,
) -> OosSnapshot:
    return OosSnapshot(
        source_id=source_id,
        mean_rank_ic=mean_rank_ic,
        activity_mean_rank_ic=activity_mean_rank_ic,
        augmented_mean_rank_ic=augmented_mean_rank_ic,
        non_worse_than_activity=non_worse,
        pure_non_worse_than_activity=pure_non_worse,
        n_ic_days=n_ic_days,
        paper_net_mean=paper_net_mean,
        paper_n_periods=paper_n_periods,
        asofs=("2025-06-30", "2025-09-30", "2025-12-31"),
    )


def test_decide_promotion_passes_when_all_gates_clear():
    decision = decide_promotion(
        challenger=_snap(),
        champion=_snap(source_id="champion", mean_rank_ic=0.018, paper_net_mean=0.0015),
        gates=FeedbackGates(),
    )
    assert decision.promote is True
    assert "all_gates_passed" in decision.reasons
    assert decision.to_dict()["decision_authorized"] is False


def test_decide_promotion_fails_closed_on_missing_ic():
    decision = decide_promotion(
        challenger=_snap(mean_rank_ic=None),
        champion=None,
        gates=FeedbackGates(min_oos_ic_days=3, min_paper_periods=3),
    )
    assert decision.promote is False
    assert any(r.startswith("challenger_rank_ic_missing") for r in decision.reasons)


def test_decide_promotion_rejects_worse_than_activity():
    decision = decide_promotion(
        challenger=_snap(non_worse=False),
        champion=None,
        gates=FeedbackGates(),
    )
    assert decision.promote is False
    assert "worse_than_activity:augmented" in decision.reasons


def test_decide_promotion_rejects_ic_regression_vs_champion():
    decision = decide_promotion(
        challenger=_snap(mean_rank_ic=0.010),
        champion=_snap(source_id="champ", mean_rank_ic=0.025),
        gates=FeedbackGates(max_rank_ic_regression_vs_champion=0.005),
    )
    assert decision.promote is False
    assert any("rank_ic_regressed_vs_champion" in r for r in decision.reasons)


def test_decide_promotion_rejects_thin_oos_sample():
    decision = decide_promotion(
        challenger=_snap(n_ic_days=1, paper_n_periods=1),
        champion=None,
        gates=FeedbackGates(min_oos_ic_days=3, min_paper_periods=3),
    )
    assert decision.promote is False
    assert any("insufficient_oos_ic_days" in r for r in decision.reasons)
    assert any("insufficient_paper_periods" in r for r in decision.reasons)


def test_expanding_oos_windows_and_summary():
    asofs = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
    windows = expanding_oos_windows(asofs, window=3, step=1)
    assert len(windows) == 3
    assert windows[0] == ("2025-03-31", "2025-06-30", "2025-09-30")
    summary = summarize_window_ics([0.01, -0.005, 0.02, None])
    assert summary["n_windows"] == 3
    assert summary["frac_positive"] == 2 / 3
    assert summary["mean"] is not None


def test_snapshot_from_eval_maps_eval_payload():
    result = {
        "source_id": "qlib_scan_lgb_v2",
        "qlib_mean_rank_ic": 0.02,
        "activity_mean_rank_ic": 0.01,
        "augmented_mean_rank_ic": 0.015,
        "qlib_augmented_non_worse_than_activity": True,
        "qlib_pure_non_worse_than_activity": False,
        "n_ic_days_qlib": 4,
        "asofs": ["2025-06-30", "2025-09-30"],
        "horizon_days": 5,
        "symbols_loaded": 100,
        "schema_version": "qlib-scan-accuracy-v1",
        "paper_portfolio": {
            "augmented": {"net": {"mean": 0.003, "n_periods": 4}},
        },
    }
    snap = snapshot_from_eval(result)
    assert snap.source_id == "qlib_scan_lgb_v2"
    assert snap.mean_rank_ic == 0.02
    assert snap.non_worse_than_activity is True
    assert snap.pure_non_worse_than_activity is False
    assert snap.paper_net_mean == 0.003
    assert snap.paper_n_periods == 4
    assert snap.n_ic_days == 4
