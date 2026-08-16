"""
Deterministic Strategy Trading Decision Interface.

Provides a pure, deterministic entry point shared across historical backtest,
event replay, shadow-live trading, and live execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np
import pandas as pd

from .temporal import OrderIntent
from .portfolio import PortfolioLimitsConfig, apply_cost_aware_sizing
from .safety import (
    StrategyState,
    SafetyConfig,
    ValidationReport,
    validate_live_safety_state,
    regime_risk_multiplier,
)


@dataclass
class DecisionOutput:
    features: Dict[str, float]
    predictions: Dict[str, float]
    target_positions: Dict[str, float]
    rejected_trades: Dict[str, str]
    approved_order_intents: List[OrderIntent]
    safety_report: ValidationReport
    risk_scale_applied: float = 1.0
    regime_scale_applied: float = 1.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "features": self.features,
            "predictions": self.predictions,
            "target_positions": self.target_positions,
            "rejected_trades": self.rejected_trades,
            "approved_order_intents": [
                {
                    "symbol": o.symbol,
                    "target_weight": o.target_weight,
                    "order_type": o.order_type,
                    "limit_price": o.limit_price,
                    "signal_ts": str(o.signal_ts),
                    "submission_ts": str(o.submission_ts),
                }
                for o in self.approved_order_intents
            ],
            "is_safe": self.safety_report.is_safe,
            "rejection_reasons": self.safety_report.rejection_reasons,
            "alerts": self.safety_report.alerts,
            "risk_scale_applied": self.risk_scale_applied,
            "regime_scale_applied": self.regime_scale_applied,
            "circuit_breaker_active": self.safety_report.circuit_breaker_active,
        }


def _normalize_prediction_keys(predictions: Dict[str, float]) -> Dict[str, float]:
    """Map pred_AAPL / alpha_AAPL keys to bare symbols for portfolio sizing."""
    out: Dict[str, float] = {}
    for key, val in predictions.items():
        if key.startswith("pred_"):
            out[key[len("pred_") :]] = float(val)
        elif key.startswith("alpha_"):
            out[key[len("alpha_") :]] = float(val)
        else:
            out[key] = float(val)
    return out


def make_decision(
    state: StrategyState,
    decision_ts: pd.Timestamp,
    market_data_snapshot: Dict[str, Any],
    model_bundle: Dict[str, Any],
    config: Dict[str, Any],
) -> DecisionOutput:
    """
    Pure, deterministic strategy decision function.

    Inputs must be passed explicitly:
    - state: Immutable current strategy ledgers & state
    - decision_ts: Fixed forecast origin timestamp
    - market_data_snapshot: Available historical data strictly <= decision_ts
    - model_bundle: Trained model weights & parameters
    - config: Strategy configuration

    Returns DecisionOutput without side effects or network calls.
    """
    if isinstance(decision_ts, str):
        decision_ts = pd.Timestamp(decision_ts)

    # 1. Feature Extraction (from available data <= decision_ts)
    raw_features: Dict[str, float] = dict(market_data_snapshot.get("features", {}) or {})

    # 2. Safety & Risk Validation (pre-sizing; notional checked after intents)
    model_version = model_bundle.get("version", "v90_meta_confidence")
    safety_cfg = SafetyConfig(**config.get("safety_config", {}))

    safety_report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version=model_version,
        market_data=market_data_snapshot,
        features=raw_features,
        config=safety_cfg,
    )

    if not safety_report.is_safe:
        # Fail safe: Block new orders, retain current position
        return DecisionOutput(
            features=raw_features,
            predictions={},
            target_positions=dict(state.position_ledger),
            rejected_trades={"ALL_NEW_ORDERS": "; ".join(safety_report.rejection_reasons)},
            approved_order_intents=[],
            safety_report=safety_report,
            risk_scale_applied=0.0,
            regime_scale_applied=0.0,
        )

    # 3. Model Prediction
    model_predict_fn = model_bundle.get("predict_fn")
    if model_predict_fn is not None:
        predictions_raw: Dict[str, float] = model_predict_fn(raw_features)
    else:
        # Default baseline prediction logic (momentum/confidence)
        predictions_raw = {
            sym: float(val)
            for sym, val in raw_features.items()
            if sym.startswith("pred_") or sym.startswith("alpha_")
        }
        if not predictions_raw:
            predictions_raw = {sym: 0.0 for sym in market_data_snapshot.get("symbols", [])}

    predictions = _normalize_prediction_keys(predictions_raw)

    # 4. Regime-aware + drawdown risk scaling (capital preservation before growth)
    regime_info = market_data_snapshot.get("regime", {}) or {}
    regime_scale = regime_risk_multiplier(
        volatility_regime=regime_info.get("volatility_regime"),
        trend_regime=regime_info.get("trend_regime"),
        bear_market=regime_info.get("bear_market"),
    )
    combined_scale = float(np.clip(safety_report.risk_scale * regime_scale, 0.0, 1.0))

    limits_cfg = PortfolioLimitsConfig(**config.get("portfolio_limits", {}))
    raw_target_weights = {
        sym: float(
            np.clip(
                pred * combined_scale,
                -limits_cfg.max_position_weight,
                limits_cfg.max_position_weight,
            )
        )
        for sym, pred in predictions.items()
    }

    forecast_stds = market_data_snapshot.get(
        "forecast_stds", {sym: 0.01 for sym in predictions}
    )
    adv_usd = market_data_snapshot.get(
        "adv_usd", {sym: 10_000_000.0 for sym in predictions}
    )
    sectors = market_data_snapshot.get("sectors", {})

    final_target_weights, rejected_trades = apply_cost_aware_sizing(
        target_weights=raw_target_weights,
        current_weights=state.position_ledger,
        alphas=predictions,
        forecast_stds=forecast_stds,
        adv_usd=adv_usd,
        sectors=sectors,
        portfolio_value_usd=state.current_equity,
        limits=limits_cfg,
    )

    # 5. Order Generation (Pure OrderIntent creation, NO broker submission)
    order_intents: List[OrderIntent] = []
    intended_notional: Dict[str, float] = {}
    for sym, target_w in final_target_weights.items():
        curr_w = state.position_ledger.get(sym, 0.0)
        delta_w = target_w - curr_w
        if abs(delta_w) > 1e-4:
            notional = abs(delta_w) * float(state.current_equity)
            intended_notional[sym] = notional
            order_intents.append(
                OrderIntent(
                    symbol=sym,
                    target_weight=target_w,
                    order_type="MARKET",
                    signal_ts=decision_ts,
                    submission_ts=decision_ts,
                )
            )

    # 6. Post-sizing notional re-validation (spend limits independent of model)
    if intended_notional:
        notional_report = validate_live_safety_state(
            state=state,
            decision_ts=decision_ts,
            model_version=model_version,
            market_data=market_data_snapshot,
            features=raw_features,
            config=safety_cfg,
            intended_orders_notional_usd=intended_notional,
        )
        if not notional_report.is_safe:
            # Keep only intents under single-order limit; block rest
            allowed: List[OrderIntent] = []
            for intent in order_intents:
                n = intended_notional.get(intent.symbol, 0.0)
                if n <= safety_cfg.max_single_order_notional_usd:
                    projected = state.session_notional_traded_usd + n
                    if projected <= safety_cfg.max_session_notional_usd:
                        allowed.append(intent)
                    else:
                        rejected_trades[intent.symbol] = "Session notional limit"
                else:
                    rejected_trades[intent.symbol] = (
                        f"Order notional ${n:,.0f} exceeds max "
                        f"${safety_cfg.max_single_order_notional_usd:,.0f}"
                    )
            # If session would still breach after filtering all, fail closed
            session_add = sum(
                intended_notional[i.symbol] for i in allowed if i.symbol in intended_notional
            )
            if state.session_notional_traded_usd + session_add > safety_cfg.max_session_notional_usd:
                rejected_trades["ALL_NEW_ORDERS"] = "; ".join(notional_report.rejection_reasons)
                order_intents = []
                final_target_weights = dict(state.position_ledger)
            else:
                order_intents = allowed
                # Re-align targets for rejected symbols to current weights
                kept = {i.symbol for i in order_intents}
                for sym in list(final_target_weights.keys()):
                    if sym not in kept and abs(
                        final_target_weights[sym] - state.position_ledger.get(sym, 0.0)
                    ) > 1e-4:
                        final_target_weights[sym] = state.position_ledger.get(sym, 0.0)
            safety_report = notional_report
            # If we still have some allowed intents, mark safe for those
            if order_intents:
                safety_report = ValidationReport(
                    is_safe=True,
                    rejection_reasons=[],
                    alerts=notional_report.alerts
                    + ["Partial order approval after notional filtering"],
                    risk_scale=combined_scale,
                    circuit_breaker_active=False,
                )

    return DecisionOutput(
        features=raw_features,
        predictions=predictions,
        target_positions=final_target_weights,
        rejected_trades=rejected_trades,
        approved_order_intents=order_intents,
        safety_report=safety_report,
        risk_scale_applied=combined_scale,
        regime_scale_applied=regime_scale,
    )
