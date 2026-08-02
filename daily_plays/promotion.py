"""Fail-closed shadow-readiness and promotion gates.

These functions only assess recorded shadow evidence.  Neither a passing gate
nor this module grants broker connectivity, order-routing, or live-capital
permission.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

import numpy as np

from edge.research.statistics import bonferroni_deflated_sharpe_approximation, date_block_bootstrap_ci


@dataclass(frozen=True)
class PromotionPolicy:
    """Frozen thresholds for the first options promotion decision."""

    min_sessions: int = 120
    min_completed_trades: int = 200
    min_regimes: int = 2
    bootstrap_confidence: float = 0.95
    bootstrap_block_size: int = 5
    bootstrap_samples: int = 2_000
    max_symbol_profit_share: float = 0.50
    max_regime_profit_share: float = 0.50
    max_drawdown: float = 0.08
    max_expected_calibration_error: float = 0.05


def underlying_gate_authorization(underlying_gate_passed: bool) -> dict[str, Any]:
    """Authorize only forward shadow collection after an underlying signal gate.

    A successful underlying gate says nothing about option profitability and is
    deliberately incapable of authorizing a broker or live capital.
    """
    return {
        "underlying_gate_passed": bool(underlying_gate_passed),
        "shadow_collection_authorized": bool(underlying_gate_passed),
        "live_capital_authorized": False,
        "broker_connectivity_authorized": False,
        "reason": (
            "underlying_gate_passed_shadow_collection_only"
            if underlying_gate_passed
            else "underlying_gate_not_passed_shadow_only"
        ),
    }


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _profit_concentration(trades: Iterable[Mapping[str, Any]], key: str) -> float | None:
    positive: dict[str, float] = {}
    for trade in trades:
        value = _finite(trade.get("ask_to_bid_net_return_pct"))
        group = trade.get(key)
        if value is None or not isinstance(group, str) or not group:
            return None
        if value > 0:
            positive[group] = positive.get(group, 0.0) + value
    total = sum(positive.values())
    return max(positive.values(), default=0.0) / total if total > 0 else None


def _maximum_drawdown(trades: Iterable[Mapping[str, Any]]) -> float | None:
    dated: list[tuple[str, float]] = []
    for trade in trades:
        day, value = trade.get("outcome_date"), _finite(trade.get("ask_to_bid_net_return_pct"))
        if not isinstance(day, str) or value is None:
            return None
        dated.append((day, value / 100.0))
    if not dated:
        return None
    # Group same-session positions so a large cross-section is not treated as a
    # fictitious sequence of intraday exits.
    grouped: dict[str, list[float]] = {}
    for day, value in dated:
        grouped.setdefault(day, []).append(value)
    equity = 1.0
    high_water = 1.0
    worst = 0.0
    for day in sorted(grouped):
        equity *= 1.0 + float(np.mean(grouped[day]))
        high_water = max(high_water, equity)
        worst = max(worst, 1.0 - equity / high_water)
    return worst


def evaluate_promotion_gate(
    readiness: Mapping[str, Any],
    completed_trades: Iterable[Mapping[str, Any]],
    *,
    recorded_trial_count: int | None,
    calibration_acceptable: bool,
    drift_stable: bool,
    policy: PromotionPolicy = PromotionPolicy(),
) -> dict[str, Any]:
    """Evaluate a pre-registered options promotion gate, always fail-closed.

    ``ask_to_bid_net_return_pct`` must be independently recorded for each
    completed trade; midpoint results are intentionally ignored.  The recorded
    model-trial count is mandatory, preventing a post-hoc search adjustment of
    one simply because only a winner is being reported.
    """
    trades = tuple(dict(trade) for trade in completed_trades)
    returns = [_finite(trade.get("ask_to_bid_net_return_pct")) for trade in trades]
    dates = [trade.get("outcome_date") for trade in trades]
    usable = all(value is not None and isinstance(day, str) for value, day in zip(returns, dates))
    metrics: dict[str, Any] = {
        "trial_count": recorded_trial_count,
        "ask_to_bid_net_expectancy_pct": None,
        "bootstrap_lower_bound_pct": None,
        "deflated_sharpe_lower_bound": None,
        "symbol_profit_concentration": _profit_concentration(trades, "symbol"),
        "regime_profit_concentration": _profit_concentration(trades, "regime"),
        "simulated_max_drawdown": _maximum_drawdown(trades),
    }
    if usable and returns:
        normalized = [float(value) / 100.0 for value in returns if value is not None]
        metrics["ask_to_bid_net_expectancy_pct"] = float(np.mean(normalized) * 100.0)
        if len(set(dates)) >= 2:
            bootstrap = date_block_bootstrap_ci(
                normalized,
                dates,
                confidence=policy.bootstrap_confidence,
                block_size=policy.bootstrap_block_size,
                n_bootstrap=policy.bootstrap_samples,
                seed=0,
            )
            metrics["bootstrap_lower_bound_pct"] = bootstrap.lower * 100.0
        if isinstance(recorded_trial_count, int) and not isinstance(recorded_trial_count, bool) and recorded_trial_count >= 1:
            try:
                adjustment = bonferroni_deflated_sharpe_approximation(normalized, trial_count=recorded_trial_count)
                metrics["deflated_sharpe_lower_bound"] = adjustment.lower_bound_sharpe
                metrics["observed_sharpe"] = adjustment.observed_sharpe
            except ValueError:
                pass

    checks = {
        "shadow_readiness_passed": bool(readiness.get("ready")),
        "ask_to_bid_data_complete": bool(usable and len(trades) == int(readiness.get("completed_shadow_option_trades", -1))),
        "positive_ask_to_bid_expectancy": bool((metrics["ask_to_bid_net_expectancy_pct"] or 0.0) > 0.0),
        "positive_date_block_bootstrap_lower_bound": bool((metrics["bootstrap_lower_bound_pct"] or 0.0) > 0.0),
        "positive_deflated_sharpe": bool((metrics["deflated_sharpe_lower_bound"] or 0.0) > 0.0),
        "recorded_trial_count": isinstance(recorded_trial_count, int) and not isinstance(recorded_trial_count, bool) and recorded_trial_count >= 1,
        "symbol_profit_not_dominated": metrics["symbol_profit_concentration"] is not None and metrics["symbol_profit_concentration"] <= policy.max_symbol_profit_share,
        "regime_profit_not_dominated": metrics["regime_profit_concentration"] is not None and metrics["regime_profit_concentration"] <= policy.max_regime_profit_share,
        "max_drawdown_within_limit": metrics["simulated_max_drawdown"] is not None and metrics["simulated_max_drawdown"] <= policy.max_drawdown,
        "calibration_acceptable": bool(calibration_acceptable),
        "drift_stable": bool(drift_stable),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "daily-plays-promotion-gate-v1",
        "status": "PASS_SHADOW_ONLY" if not failed else "FAIL_SHADOW_ONLY",
        "passed": not failed,
        "live_capital_authorized": False,
        "broker_connectivity_authorized": False,
        "checks": checks,
        "failed_checks": failed,
        "metrics": metrics,
        "policy": asdict(policy),
    }
