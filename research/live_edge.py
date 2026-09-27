"""
Live / shadow edge helpers: walk-forward gate checks and regime-aware signal shaping.

These helpers are pure (no I/O, no broker) and are safe to call from make_decision
paths, bakeoffs, and shadow-live runners.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Any

import numpy as np
import pandas as pd

from .safety import regime_risk_multiplier


@dataclass(frozen=True)
class WalkForwardGateResult:
    """Pass/fail for promoting a model to shadow or live based on OOS folds."""

    passed: bool
    n_folds: int
    mean_oos_sharpe: float
    min_oos_sharpe: float
    positive_fold_fraction: float
    reasons: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "n_folds": self.n_folds,
            "mean_oos_sharpe": self.mean_oos_sharpe,
            "min_oos_sharpe": self.min_oos_sharpe,
            "positive_fold_fraction": self.positive_fold_fraction,
            "reasons": list(self.reasons),
        }


def evaluate_walk_forward_gates(
    fold_sharpes: Sequence[float],
    *,
    min_folds: int = 3,
    min_mean_oos_sharpe: float = 0.5,
    min_positive_fold_fraction: float = 0.60,
    min_fold_sharpe: float = -0.25,
) -> WalkForwardGateResult:
    """
    Honest OOS promotion gate (walk-forward validation skill).

    A model may enter shadow-live only if:
      - enough folds
      - mean OOS Sharpe above threshold
      - most folds positive
      - no catastrophic single-fold collapse below min_fold_sharpe
    """
    arr = np.asarray([float(x) for x in fold_sharpes if np.isfinite(x)], dtype=float)
    reasons: List[str] = []

    if arr.size < min_folds:
        reasons.append(f"Insufficient OOS folds: {arr.size} < {min_folds}")
        return WalkForwardGateResult(
            passed=False,
            n_folds=int(arr.size),
            mean_oos_sharpe=float(arr.mean()) if arr.size else float("nan"),
            min_oos_sharpe=float(arr.min()) if arr.size else float("nan"),
            positive_fold_fraction=float((arr > 0).mean()) if arr.size else 0.0,
            reasons=tuple(reasons),
        )

    mean_s = float(arr.mean())
    min_s = float(arr.min())
    pos_frac = float((arr > 0).mean())

    if mean_s < min_mean_oos_sharpe:
        reasons.append(f"Mean OOS Sharpe {mean_s:.3f} < {min_mean_oos_sharpe:.3f}")
    if pos_frac < min_positive_fold_fraction:
        reasons.append(
            f"Positive fold fraction {pos_frac:.2%} < {min_positive_fold_fraction:.2%}"
        )
    if min_s < min_fold_sharpe:
        reasons.append(f"Worst fold Sharpe {min_s:.3f} < {min_fold_sharpe:.3f}")

    return WalkForwardGateResult(
        passed=len(reasons) == 0,
        n_folds=int(arr.size),
        mean_oos_sharpe=mean_s,
        min_oos_sharpe=min_s,
        positive_fold_fraction=pos_frac,
        reasons=tuple(reasons),
    )


def apply_regime_to_predictions(
    predictions: Dict[str, float],
    *,
    volatility_regime: Optional[str] = None,
    trend_regime: Optional[str] = None,
    bear_market: Optional[bool] = None,
    per_symbol_regime: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[Dict[str, float], float]:
    """
    Scale raw predictions by global (and optional per-symbol) regime multipliers.

    Returns (scaled_predictions, global_regime_scale).
    """
    global_scale = regime_risk_multiplier(
        volatility_regime=volatility_regime,
        trend_regime=trend_regime,
        bear_market=bear_market,
    )
    per_symbol_regime = per_symbol_regime or {}
    scaled: Dict[str, float] = {}
    for sym, pred in predictions.items():
        local = per_symbol_regime.get(sym, {})
        if local:
            local_scale = regime_risk_multiplier(
                volatility_regime=local.get("volatility_regime", volatility_regime),
                trend_regime=local.get("trend_regime", trend_regime),
                bear_market=local.get("bear_market", bear_market),
            )
        else:
            local_scale = global_scale
        scaled[sym] = float(pred) * float(local_scale)
    return scaled, global_scale


def regime_stability_score(
    performance_by_regime: pd.DataFrame,
    *,
    return_col: str = "mean_return",
    n_col: str = "n",
    min_obs_per_regime: int = 20,
) -> Dict[str, Any]:
    """
    Summarise whether edge is concentrated in one regime (overfit risk).

    Expects output shaped like research.regimes.performance_by_regime.
    """
    if performance_by_regime is None or performance_by_regime.empty:
        return {
            "stable": False,
            "n_regimes_with_data": 0,
            "positive_regimes": 0,
            "reason": "empty performance table",
        }

    frame = performance_by_regime.copy()
    if n_col not in frame.columns or return_col not in frame.columns:
        return {"stable": False, "reason": f"missing columns {n_col}/{return_col}"}

    usable = frame.loc[frame[n_col] >= min_obs_per_regime]
    n_regimes = int(len(usable))
    if n_regimes < 2:
        return {
            "stable": False,
            "n_regimes_with_data": n_regimes,
            "positive_regimes": 0,
            "reason": f"need >=2 regimes with n>={min_obs_per_regime}",
        }

    pos = int((usable[return_col] > 0).sum())
    # Require majority of sufficiently-sampled regimes positive
    stable = pos >= max(2, int(np.ceil(0.5 * n_regimes)))
    return {
        "stable": stable,
        "n_regimes_with_data": n_regimes,
        "positive_regimes": pos,
        "mean_return_across_regimes": float(usable[return_col].mean()),
        "reason": "ok" if stable else "edge concentrated or weak across regimes",
    }


def select_approved_model_version(
    candidates: Iterable[Dict[str, Any]],
    *,
    fold_sharpe_key: str = "fold_sharpes",
    version_key: str = "version",
) -> Optional[str]:
    """
    Pick the first candidate that passes walk-forward gates.
    candidates: iterable of dicts with version + fold_sharpes.
    """
    for cand in candidates:
        folds = cand.get(fold_sharpe_key, [])
        gate = evaluate_walk_forward_gates(folds)
        if gate.passed:
            return str(cand[version_key])
    return None
