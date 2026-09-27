"""Closed-loop feedback for the deep-scan ordinal ranker (qlib_scan_lgb).

What this is
------------
The shipped ranker was trained once (train ≤ 2023-12-29, val = 2024) and
evaluated ad hoc on 2025+ as-ofs.  That is *not* a feedback loop: OOS metrics
never gate a retrain, never compare champion vs challenger, and never decide
whether to keep or roll back the artifact.

This module supplies the missing research MLOps pieces:

1. **Preregistered promotion gates** — fixed before looking at challenger OOS.
2. **OOS / drift report** — Rank IC + paper book from ``eval_qlib_scan_accuracy``.
3. **Champion vs challenger decision** — promote only if gates pass; never
   auto-authorize ENTER.

What this is not
----------------
* Not continuous online retrain of a live trading model.
* Not a calibrated probability or capital authorization.
* Not hyperparameter search on the terminal holdout (forbidden).

Quant protocol
--------------
* Label horizon purge applies to any retrain window (see ``splits.py``).
* Terminal holdout is scored once for the gate; it is never used to retune
  leaves / LR / feature set.
* Soft stream reweighting lives in ``adaptive_signal``; weight adaptation is
  orthogonal to *model* iteration handled here.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "qlib-scan-feedback-v1"
SCORE_KIND = "ordinal_qlib_xs"


@dataclass(frozen=True)
class FeedbackGates:
    """Preregistered thresholds — set *before* reading challenger OOS metrics.

    All Rank-IC comparisons are *mean* cross-sectional Spearman over the
    evaluation as-of dates.  Paper book is equal-weight long top-N net of RT
    costs (see ``eval_qlib_scan_accuracy.paper_long_topn``).
    """

    # Challenger pure-qlib mean Rank IC must clear this floor on OOS as-ofs.
    min_oos_rank_ic: float = 0.0
    # Challenger must beat activity baseline (augmented or pure, configurable).
    require_non_worse_than_activity: bool = True
    # Prefer augmented (activity+qlib blend) for routing quality; pure for ML claim.
    activity_compare_mode: str = "augmented"  # "augmented" | "pure"
    # Challenger must not regress vs champion Rank IC by more than this (absolute).
    max_rank_ic_regression_vs_champion: float = 0.005
    # If champion paper net mean is finite, challenger net mean must not fall
    # more than this absolute return gap (e.g. 10 bps per period).
    max_paper_net_regression: float = 0.001
    # Minimum number of OOS IC days / paper periods for a decision.
    min_oos_ic_days: int = 3
    min_paper_periods: int = 3
    # Optional absolute floor on paper net mean (None = no floor).
    min_paper_net_mean: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OosSnapshot:
    """Metrics pulled from one evaluation of a ranker artifact."""

    source_id: str
    mean_rank_ic: float | None
    activity_mean_rank_ic: float | None
    augmented_mean_rank_ic: float | None
    non_worse_than_activity: bool | None
    pure_non_worse_than_activity: bool | None
    n_ic_days: int
    paper_net_mean: float | None
    paper_n_periods: int
    asofs: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["extra"] = dict(self.extra)
        return d


def snapshot_from_eval(result: Mapping[str, Any], *, source_id: str | None = None) -> OosSnapshot:
    """Normalize ``eval_qlib_scan_accuracy.evaluate`` output into an OosSnapshot."""
    paper = result.get("paper_portfolio") or {}
    aug = paper.get("augmented") or {}
    net = aug.get("net") or {}
    asofs = tuple(str(x) for x in (result.get("asofs") or ()))
    return OosSnapshot(
        source_id=str(source_id or result.get("source_id") or "unknown"),
        mean_rank_ic=_f(result.get("qlib_mean_rank_ic")),
        activity_mean_rank_ic=_f(result.get("activity_mean_rank_ic")),
        augmented_mean_rank_ic=_f(result.get("augmented_mean_rank_ic")),
        non_worse_than_activity=_b(result.get("qlib_augmented_non_worse_than_activity")),
        pure_non_worse_than_activity=_b(result.get("qlib_pure_non_worse_than_activity")),
        n_ic_days=int(result.get("n_ic_days_qlib") or 0),
        paper_net_mean=_f(net.get("mean")),
        paper_n_periods=int((net.get("n_periods") if isinstance(net, Mapping) else None) or 0),
        asofs=asofs,
        extra={
            "horizon_days": result.get("horizon_days"),
            "symbols_loaded": result.get("symbols_loaded"),
            "schema_version": result.get("schema_version"),
        },
    )


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _b(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


@dataclass(frozen=True)
class PromoteDecision:
    promote: bool
    reasons: tuple[str, ...]
    gates: FeedbackGates
    champion: OosSnapshot | None
    challenger: OosSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "score_kind": SCORE_KIND,
            "promote": self.promote,
            "reasons": list(self.reasons),
            "gates": self.gates.to_dict(),
            "champion": None if self.champion is None else self.champion.to_dict(),
            "challenger": self.challenger.to_dict(),
            "decision_authorized": False,
            "note": (
                "Research promotion of ordinal deep-scan ranker only — never ENTER "
                "or live-capital authorization."
            ),
        }


def decide_promotion(
    *,
    challenger: OosSnapshot,
    champion: OosSnapshot | None = None,
    gates: FeedbackGates | None = None,
) -> PromoteDecision:
    """Return a hard promote / no-promote decision against preregistered gates.

    Missing metrics fail closed (no promote).  Champion may be omitted for the
    first artifact (only absolute floors + activity baseline apply).
    """
    g = gates or FeedbackGates()
    reasons: list[str] = []

    if challenger.n_ic_days < g.min_oos_ic_days:
        reasons.append(
            f"insufficient_oos_ic_days:{challenger.n_ic_days}<{g.min_oos_ic_days}"
        )
    if challenger.paper_n_periods < g.min_paper_periods:
        reasons.append(
            f"insufficient_paper_periods:{challenger.paper_n_periods}<{g.min_paper_periods}"
        )

    ic = challenger.mean_rank_ic
    if ic is None:
        reasons.append("challenger_rank_ic_missing")
    elif ic < g.min_oos_rank_ic:
        reasons.append(f"rank_ic_below_floor:{ic:.6f}<{g.min_oos_rank_ic:.6f}")

    if g.require_non_worse_than_activity:
        if g.activity_compare_mode == "pure":
            flag = challenger.pure_non_worse_than_activity
            tag = "pure"
        else:
            flag = challenger.non_worse_than_activity
            tag = "augmented"
        if flag is None:
            reasons.append(f"activity_compare_missing:{tag}")
        elif not flag:
            reasons.append(f"worse_than_activity:{tag}")

    if g.min_paper_net_mean is not None:
        pnm = challenger.paper_net_mean
        if pnm is None:
            reasons.append("paper_net_mean_missing")
        elif pnm < g.min_paper_net_mean:
            reasons.append(
                f"paper_net_below_floor:{pnm:.6f}<{g.min_paper_net_mean:.6f}"
            )

    if champion is not None:
        c_ic = champion.mean_rank_ic
        if ic is not None and c_ic is not None:
            if ic + 1e-12 < c_ic - g.max_rank_ic_regression_vs_champion:
                reasons.append(
                    f"rank_ic_regressed_vs_champion:{ic:.6f}<{c_ic:.6f}"
                    f"-tol{g.max_rank_ic_regression_vs_champion:.6f}"
                )
        c_net = champion.paper_net_mean
        ch_net = challenger.paper_net_mean
        if c_net is not None and ch_net is not None:
            if ch_net + 1e-12 < c_net - g.max_paper_net_regression:
                reasons.append(
                    f"paper_net_regressed_vs_champion:{ch_net:.6f}<{c_net:.6f}"
                    f"-tol{g.max_paper_net_regression:.6f}"
                )

    promote = len(reasons) == 0
    if promote:
        reasons.append("all_gates_passed")
    return PromoteDecision(
        promote=promote,
        reasons=tuple(reasons),
        gates=g,
        champion=champion,
        challenger=challenger,
    )


def expanding_oos_windows(
    asofs: Sequence[str],
    *,
    window: int = 4,
    step: int = 1,
) -> list[tuple[str, ...]]:
    """Sliding OOS windows over sorted as-of dates for drift / stability checks.

    Each window is a tuple of as-of strings.  Used to detect whether Rank IC is
    concentrated in one regime or stable across time.  Does not retrain.
    """
    dates = sorted({str(a).strip() for a in asofs if str(a).strip()})
    if window < 1:
        raise ValueError("window must be >= 1")
    if step < 1:
        raise ValueError("step must be >= 1")
    if len(dates) < window:
        return [tuple(dates)] if dates else []
    out: list[tuple[str, ...]] = []
    for start in range(0, len(dates) - window + 1, step):
        out.append(tuple(dates[start : start + window]))
    return out


def summarize_window_ics(
    window_means: Sequence[float | None],
) -> dict[str, float | int | None]:
    """Stability stats over sliding-window mean Rank ICs."""
    vals = [float(v) for v in window_means if v is not None and math.isfinite(float(v))]
    if not vals:
        return {"n_windows": 0, "mean": None, "std": None, "min": None, "max": None, "frac_positive": None}
    arr_mean = sum(vals) / len(vals)
    var = sum((v - arr_mean) ** 2 for v in vals) / max(1, len(vals) - 1) if len(vals) > 1 else 0.0
    return {
        "n_windows": len(vals),
        "mean": arr_mean,
        "std": math.sqrt(var) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
        "frac_positive": sum(1 for v in vals if v > 0) / len(vals),
    }


def build_iteration_report(
    *,
    champion_eval: Mapping[str, Any] | None,
    challenger_eval: Mapping[str, Any] | None,
    decision: PromoteDecision | None,
    window_summary: Mapping[str, Any] | None = None,
    train_meta: Mapping[str, Any] | None = None,
    iteration_id: str,
) -> dict[str, Any]:
    """Assemble one append-only iteration artifact for ``runs/qlib_scan_iterate/``."""
    return {
        "schema_version": SCHEMA_VERSION,
        "score_kind": SCORE_KIND,
        "iteration_id": iteration_id,
        "champion_eval": dict(champion_eval) if champion_eval else None,
        "challenger_eval": dict(challenger_eval) if challenger_eval else None,
        "window_stability": dict(window_summary) if window_summary else None,
        "train_meta": dict(train_meta) if train_meta else None,
        "promotion": None if decision is None else decision.to_dict(),
        "decision_authorized": False,
        "note": (
            "Feedback iteration for deep-scan ordinal ranker. OOS metrics drive "
            "promote/hold; never used as ENTER authorization."
        ),
    }
