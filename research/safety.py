"""
Live Trading Safety & Risk Reconciler Engine.

Prevents strategy execution under state ambiguity, sequence gaps, stale market data,
broker position mismatches, drawdown limit breaches, circuit breakers, wide spreads,
notional overshoots, or feature distribution anomalies.

Priority order (risk-management hierarchy):
  1. Survival — hard halts on kill switch / circuit breakers / broker mismatch
  2. Capital preservation — daily/weekly loss, drawdown, size reduction
  3. Growth — only when is_safe and risk_scale > 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd


@dataclass
class StrategyState:
    cash_ledger: float
    position_ledger: Dict[str, float]
    broker_positions: Optional[Dict[str, float]] = None
    unresolved_orders: List[str] = field(default_factory=list)
    daily_realized_pnl: float = 0.0
    weekly_realized_pnl: float = 0.0
    strategy_peak_equity: float = 1_000_000.0
    current_equity: float = 1_000_000.0
    hour_start_equity: Optional[float] = None
    consecutive_losses: int = 0
    last_sequence_num: Dict[str, int] = field(default_factory=dict)
    last_quote_ts: Dict[str, pd.Timestamp] = field(default_factory=dict)
    kill_switch: bool = False
    halted_reason: Optional[str] = None
    session_notional_traded_usd: float = 0.0


@dataclass(frozen=True)
class SafetyConfig:
    max_quote_stale_seconds: float = 60.0
    max_daily_loss_usd: float = 50_000.0
    max_weekly_loss_usd: float = 100_000.0
    max_strategy_drawdown_pct: float = 0.15
    # Soft drawdown bands: reduce size before hard halt
    caution_drawdown_pct: float = 0.05
    warning_drawdown_pct: float = 0.10
    caution_risk_scale: float = 0.75
    warning_risk_scale: float = 0.50
    max_bid_ask_spread_pct: float = 0.02
    max_single_order_notional_usd: float = 100_000.0
    max_session_notional_usd: float = 500_000.0
    max_hourly_loss_pct: float = 0.05
    max_consecutive_losses: int = 5
    approved_model_version: str = "v90_meta_confidence"
    require_broker_reconciliation: bool = False
    # When True, missing quotes for symbols with positions are hard rejects
    require_quotes_for_open_positions: bool = True
    max_sequence_gap: int = 1
    # Feature anomaly: reject if |z| exceeds threshold when baselines present
    max_feature_zscore: float = 8.0
    # Shadow mode never authorizes live order submission
    allow_live_order_submission: bool = False


@dataclass
class ValidationReport:
    is_safe: bool
    rejection_reasons: List[str]
    alerts: List[str]
    risk_scale: float = 1.0
    circuit_breaker_active: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "rejection_reasons": list(self.rejection_reasons),
            "alerts": list(self.alerts),
            "risk_scale": self.risk_scale,
            "circuit_breaker_active": self.circuit_breaker_active,
        }


def _drawdown_pct(state: StrategyState) -> float:
    peak = state.strategy_peak_equity
    if peak <= 0:
        return 0.0
    return (peak - state.current_equity) / peak


def _risk_scale_for_drawdown(dd: float, cfg: SafetyConfig) -> float:
    """Progressive de-risking before the hard drawdown halt."""
    if dd >= cfg.max_strategy_drawdown_pct:
        return 0.0
    if dd >= cfg.warning_drawdown_pct:
        return cfg.warning_risk_scale
    if dd >= cfg.caution_drawdown_pct:
        return cfg.caution_risk_scale
    return 1.0


def validate_live_safety_state(
    state: StrategyState,
    decision_ts: pd.Timestamp,
    model_version: str,
    market_data: Dict[str, Any],
    features: Dict[str, float],
    config: Optional[SafetyConfig] = None,
    intended_orders_notional_usd: Optional[Dict[str, float]] = None,
) -> ValidationReport:
    """
    Validates state and market conditions prior to decision execution.
    If any hard safety check fails, returns is_safe=False with rejection reasons.
    Soft risk reduction is reported via risk_scale even when is_safe=True.
    """
    cfg = config or SafetyConfig()
    if isinstance(decision_ts, str):
        decision_ts = pd.Timestamp(decision_ts)

    rejections: List[str] = []
    alerts: List[str] = []
    circuit_breaker = False
    risk_scale = 1.0

    # 0. Kill switch / explicit halt
    if state.kill_switch:
        rejections.append(
            f"Kill switch engaged{f': {state.halted_reason}' if state.halted_reason else ''}"
        )
        circuit_breaker = True

    if state.halted_reason and not state.kill_switch:
        rejections.append(f"Strategy halted: {state.halted_reason}")
        circuit_breaker = True

    # 1. Model Version Authorization
    if model_version != cfg.approved_model_version:
        rejections.append(
            f"Unapproved model version '{model_version}' (approved: '{cfg.approved_model_version}')"
        )

    # 2. Financial Ledger & Broker State Reconciliation
    if state.cash_ledger <= 0:
        rejections.append(f"Invalid cash ledger state ({state.cash_ledger:,.2f})")

    if state.current_equity <= 0:
        rejections.append(f"Invalid equity state ({state.current_equity:,.2f})")
        circuit_breaker = True

    if state.unresolved_orders:
        rejections.append(
            f"Unresolved broker orders exist ({len(state.unresolved_orders)} pending)"
        )

    if cfg.require_broker_reconciliation:
        if state.broker_positions is None:
            rejections.append("Broker reconciliation required but broker_positions is missing")
        else:
            all_syms = set(state.position_ledger) | set(state.broker_positions)
            for sym in all_syms:
                internal_qty = state.position_ledger.get(sym, 0.0)
                broker_qty = state.broker_positions.get(sym, 0.0)
                if abs(internal_qty - broker_qty) > 1e-4:
                    rejections.append(
                        f"Position discrepancy for {sym}: ledger={internal_qty}, broker={broker_qty}"
                    )

    # 3. Risk & Loss Limit Enforcement (hard)
    if state.daily_realized_pnl < -cfg.max_daily_loss_usd:
        rejections.append(
            f"Daily loss limit breached: {state.daily_realized_pnl:,.2f} < -{cfg.max_daily_loss_usd:,.2f}"
        )
        circuit_breaker = True

    if state.weekly_realized_pnl < -cfg.max_weekly_loss_usd:
        rejections.append(
            f"Weekly loss limit breached: {state.weekly_realized_pnl:,.2f} < -{cfg.max_weekly_loss_usd:,.2f}"
        )
        circuit_breaker = True

    dd = _drawdown_pct(state)
    risk_scale = min(risk_scale, _risk_scale_for_drawdown(dd, cfg))
    if dd > cfg.max_strategy_drawdown_pct:
        rejections.append(
            f"Strategy drawdown limit breached: {dd:.2%} > {cfg.max_strategy_drawdown_pct:.2%}"
        )
        circuit_breaker = True
    elif dd >= cfg.warning_drawdown_pct:
        alerts.append(
            f"Drawdown warning: {dd:.2%} — risk_scale reduced to {risk_scale:.2f}"
        )
    elif dd >= cfg.caution_drawdown_pct:
        alerts.append(
            f"Drawdown caution: {dd:.2%} — risk_scale reduced to {risk_scale:.2f}"
        )

    # 3b. Circuit breakers: consecutive losses & hourly loss
    if state.consecutive_losses >= cfg.max_consecutive_losses:
        rejections.append(
            f"Circuit breaker: consecutive losses {state.consecutive_losses} >= {cfg.max_consecutive_losses}"
        )
        circuit_breaker = True

    if state.hour_start_equity is not None and state.hour_start_equity > 0:
        hourly_pnl = (state.current_equity - state.hour_start_equity) / state.hour_start_equity
        if hourly_pnl < -cfg.max_hourly_loss_pct:
            rejections.append(
                f"Circuit breaker: hourly PnL {hourly_pnl:.2%} < -{cfg.max_hourly_loss_pct:.2%}"
            )
            circuit_breaker = True

    # 4. Feature Sanity Check (finite + optional z-score vs baselines)
    feature_baselines: Dict[str, Dict[str, float]] = market_data.get("feature_baselines", {}) or {}
    for f_name, f_val in features.items():
        if not np.isfinite(f_val):
            rejections.append(f"Non-finite feature value for '{f_name}': {f_val}")
            continue
        baseline = feature_baselines.get(f_name)
        if baseline and baseline.get("std", 0.0) > 0:
            z = (float(f_val) - float(baseline.get("mean", 0.0))) / float(baseline["std"])
            if abs(z) > cfg.max_feature_zscore:
                rejections.append(
                    f"Feature anomaly '{f_name}': z={z:.2f} exceeds |{cfg.max_feature_zscore}|"
                )

    # 5. Stale Quotes & open-position quote coverage
    for sym, last_ts in state.last_quote_ts.items():
        if last_ts is None:
            continue
        last_ts = pd.Timestamp(last_ts)
        stale_sec = (decision_ts - last_ts).total_seconds()
        if stale_sec > cfg.max_quote_stale_seconds:
            rejections.append(
                f"Quote for {sym} is stale ({stale_sec:.1f}s > {cfg.max_quote_stale_seconds}s)"
            )

    if cfg.require_quotes_for_open_positions:
        for sym, qty in state.position_ledger.items():
            if abs(qty) > 1e-8 and sym not in state.last_quote_ts:
                # Allow missing quotes only when market_data provides fresh quotes
                quotes = market_data.get("quotes", {}) or {}
                if sym not in quotes:
                    rejections.append(f"Missing quote timestamp for open position {sym}")

    # 6. Sequence gap validation (market data feed integrity)
    current_sequences: Dict[str, int] = market_data.get("sequence_nums", {}) or {}
    for sym, seq in current_sequences.items():
        prev = state.last_sequence_num.get(sym)
        if prev is not None and seq < prev:
            rejections.append(f"Sequence regression for {sym}: {seq} < {prev}")
        elif prev is not None and (seq - prev) > cfg.max_sequence_gap:
            rejections.append(
                f"Sequence gap for {sym}: {prev} -> {seq} exceeds max_gap={cfg.max_sequence_gap}"
            )

    # 7. Bid-ask spread checks
    quotes: Dict[str, Any] = market_data.get("quotes", {}) or {}
    for sym, q in quotes.items():
        if not isinstance(q, dict):
            continue
        bid = q.get("bid")
        ask = q.get("ask")
        if bid is None or ask is None:
            continue
        try:
            bid_f = float(bid)
            ask_f = float(ask)
        except (TypeError, ValueError):
            rejections.append(f"Non-numeric quote for {sym}")
            continue
        mid = 0.5 * (bid_f + ask_f)
        if mid <= 0 or ask_f < bid_f:
            rejections.append(f"Invalid quote book for {sym}: bid={bid_f}, ask={ask_f}")
            continue
        spread_pct = (ask_f - bid_f) / mid
        if spread_pct > cfg.max_bid_ask_spread_pct:
            rejections.append(
                f"Spread too wide for {sym}: {spread_pct:.2%} > {cfg.max_bid_ask_spread_pct:.2%}"
            )

    # 8. Notional / spend limits on intended orders (when provided)
    if intended_orders_notional_usd:
        session_add = 0.0
        for sym, notional in intended_orders_notional_usd.items():
            n = abs(float(notional))
            if n > cfg.max_single_order_notional_usd:
                rejections.append(
                    f"Order notional for {sym} ${n:,.0f} exceeds max ${cfg.max_single_order_notional_usd:,.0f}"
                )
            session_add += n
        projected = state.session_notional_traded_usd + session_add
        if projected > cfg.max_session_notional_usd:
            rejections.append(
                f"Session notional ${projected:,.0f} would exceed max ${cfg.max_session_notional_usd:,.0f}"
            )

    # 9. Live submission policy (defense in depth for shadow path)
    execution_mode = str(market_data.get("execution_mode", "SHADOW")).upper()
    if execution_mode in {"LIVE", "PROD", "PRODUCTION"} and not cfg.allow_live_order_submission:
        rejections.append(
            "Live order submission disabled by SafetyConfig.allow_live_order_submission=False"
        )
        circuit_breaker = True

    is_safe = len(rejections) == 0
    if not is_safe:
        alerts.append(
            "SAFETY GATE ACTIVATED: New orders blocked, preserving current portfolio state."
        )
        risk_scale = 0.0

    return ValidationReport(
        is_safe=is_safe,
        rejection_reasons=rejections,
        alerts=alerts,
        risk_scale=risk_scale,
        circuit_breaker_active=circuit_breaker,
    )


def regime_risk_multiplier(
    volatility_regime: Optional[str] = None,
    trend_regime: Optional[str] = None,
    bear_market: Optional[bool] = None,
) -> float:
    """
    Causal regime-aware risk scaling for live/shadow decisions.

    High-vol and bear regimes de-risk; low-vol can run full size.
    Multipliers are deliberately conservative (capital preservation first).
    """
    scale = 1.0
    vol = (volatility_regime or "").upper()
    trend = (trend_regime or "").upper()

    if vol == "HIGH":
        scale *= 0.50
    elif vol == "MEDIUM":
        scale *= 0.85
    elif vol == "LOW":
        scale *= 1.0

    if bear_market is True:
        scale *= 0.60
    elif trend == "DOWN":
        scale *= 0.80

    return float(np.clip(scale, 0.0, 1.0))
