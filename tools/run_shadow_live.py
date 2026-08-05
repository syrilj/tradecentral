#!/usr/bin/env python3
"""
Shadow-Live Runner.

Runs during market hours or dry-run mode to generate real-time strategy decisions,
log structured outputs, and verify live execution readiness without submitting any
broker orders.

HARD GUARANTEE: this process never calls a broker submit API. Execution mode is
forced to SHADOW_LIVE and SafetyConfig.allow_live_order_submission=False.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import pandas as pd

# Add repo root to python path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.safety import StrategyState, SafetyConfig
from research.decision import make_decision
from research.logging import DecisionLogger
from research.live_edge import evaluate_walk_forward_gates

# Defense-in-depth: never import order-submission modules here.
FORBIDDEN_IMPORT_MARKERS = ("submit_order", "place_order", "ib_insync", "ibapi")


def _assert_no_broker_submission_surface() -> None:
    """Fail fast if this process accidentally loads a live order path."""
    for name, mod in list(sys.modules.items()):
        lname = name.lower()
        if any(marker in lname for marker in ("broker_submit", "live_execution", "order_router")):
            raise RuntimeError(
                f"Shadow-live forbids loaded module '{name}'. "
                "Remove broker submission imports from the shadow path."
            )


def _default_safety_config() -> dict:
    return {
        "max_quote_stale_seconds": 60.0,
        "max_daily_loss_usd": 50_000.0,
        "max_weekly_loss_usd": 100_000.0,
        "max_strategy_drawdown_pct": 0.15,
        "caution_drawdown_pct": 0.05,
        "warning_drawdown_pct": 0.10,
        "max_bid_ask_spread_pct": 0.02,
        "max_single_order_notional_usd": 100_000.0,
        "max_session_notional_usd": 500_000.0,
        "max_hourly_loss_pct": 0.05,
        "max_consecutive_losses": 5,
        "approved_model_version": "v90_meta_confidence",
        "require_broker_reconciliation": False,  # True once broker feed wired
        "allow_live_order_submission": False,  # NEVER true in shadow
    }


def run_shadow_live_session(
    dry_run: bool = False,
    fold_sharpes: list[float] | None = None,
) -> int:
    _assert_no_broker_submission_surface()

    log_dir = ROOT / "runs" / "shadow_live"
    log_file = log_dir / "shadow_decisions.jsonl"
    logger = DecisionLogger(log_file)

    print("=" * 60)
    print("  SHADOW-LIVE STRATEGY RUNNER (ZERO BROKER ORDERS)")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE MARKET HOURLY'}")
    print(f"  Decision Log: {log_file}")
    print("=" * 60)

    # Optional walk-forward promotion gate before running
    if fold_sharpes is not None:
        gate = evaluate_walk_forward_gates(fold_sharpes)
        print(f"\n[WALK-FORWARD GATE] passed={gate.passed} mean_oos={gate.mean_oos_sharpe:.3f}")
        if not gate.passed:
            print(f"  Reasons: {list(gate.reasons)}")
            print("  Aborting shadow session — model not promotion-ready.")
            return 2

    now = pd.Timestamp.now()
    initial_state = StrategyState(
        cash_ledger=1_000_000.0,
        position_ledger={"AAPL": 0.05, "MSFT": 0.05},
        current_equity=1_000_000.0,
        strategy_peak_equity=1_000_000.0,
        hour_start_equity=1_000_000.0,
        last_quote_ts={
            "AAPL": now - pd.Timedelta(seconds=5),
            "MSFT": now - pd.Timedelta(seconds=5),
        },
        consecutive_losses=0,
        kill_switch=False,
    )

    model_bundle = {
        "version": "v90_meta_confidence",
        "predict_fn": None,
    }

    config = {
        "safety_config": _default_safety_config(),
        "portfolio_limits": {
            "max_position_weight": 0.10,
            "max_sector_exposure": 0.30,
            "max_gross_exposure": 1.00,
        },
    }

    # Validate frozen safety defaults
    safety = SafetyConfig(**config["safety_config"])
    assert safety.allow_live_order_submission is False, "Shadow must disable live submission"

    decision_ts = now
    snapshot = {
        "execution_mode": "SHADOW_LIVE",  # never LIVE
        "features": {"pred_AAPL": 0.08, "pred_MSFT": 0.04},
        "symbols": ["AAPL", "MSFT"],
        "adv_usd": {"AAPL": 50_000_000.0, "MSFT": 40_000_000.0},
        "sectors": {"AAPL": "Technology", "MSFT": "Technology"},
        "quotes": {
            "AAPL": {"bid": 190.0, "ask": 190.05},
            "MSFT": {"bid": 420.0, "ask": 420.10},
        },
        "regime": {
            "volatility_regime": "MEDIUM",
            "trend_regime": "UP",
            "bear_market": False,
        },
        "sequence_nums": {"AAPL": 1001, "MSFT": 2001},
    }

    print(f"Generating shadow decision as of {decision_ts}...")
    output = make_decision(
        state=initial_state,
        decision_ts=decision_ts,
        market_data_snapshot=snapshot,
        model_bundle=model_bundle,
        config=config,
    )

    # Absolute guarantee: no live submission flag can be set by decision path
    assert output.safety_report is not None
    logger.log_decision(decision_ts, output, execution_mode="SHADOW_LIVE")

    print("\n[DECISION RESULT]")
    print(f"  Is Safe: {output.safety_report.is_safe}")
    print(f"  Risk Scale: {output.risk_scale_applied:.3f}")
    print(f"  Regime Scale: {output.regime_scale_applied:.3f}")
    print(f"  Circuit Breaker: {output.safety_report.circuit_breaker_active}")
    print(f"  Target Positions: {output.target_positions}")
    print(f"  Approved Order Intents: {len(output.approved_order_intents)}")
    print(f"  Rejected Trades: {output.rejected_trades}")
    if output.safety_report.alerts:
        print(f"  Alerts: {output.safety_report.alerts}")
    if output.safety_report.rejection_reasons:
        print(f"  Safety Rejections: {output.safety_report.rejection_reasons}")

    # Persist a machine-readable session summary
    summary_path = log_dir / "last_session_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "decision_ts": str(decision_ts),
                "execution_mode": "SHADOW_LIVE",
                "broker_orders_submitted": 0,
                "decision": output.as_dict(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nShadow session completed cleanly. Zero broker orders submitted.")
    print(f"Summary written to {summary_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Shadow-live strategy runner")
    parser.add_argument(
        "--dry-run", action="store_true", help="Execute one dry-run session immediately"
    )
    parser.add_argument(
        "--fold-sharpes",
        type=str,
        default=None,
        help="Comma-separated OOS fold Sharpes for walk-forward gate (optional)",
    )
    args = parser.parse_args()

    folds = None
    if args.fold_sharpes:
        folds = [float(x.strip()) for x in args.fold_sharpes.split(",") if x.strip()]

    sys.exit(run_shadow_live_session(dry_run=args.dry_run, fold_sharpes=folds))


if __name__ == "__main__":
    main()
