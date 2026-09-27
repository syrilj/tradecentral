"""Offline reliability, shadow-readiness, and fail-closed promotion reporting."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .ledger import DEFAULT_OUTPUT_ROOT
from .promotion import PromotionPolicy, evaluate_promotion_gate


READINESS_POLICY = PromotionPolicy()


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict): records.append(row)
        except json.JSONDecodeError: pass
    return records


def _bucket(probability: float) -> str:
    low = int(probability * 10) / 10
    if low >= 0.9: return "0.9-1.0"
    return f"{low:.1f}-{low + .1:.1f}"


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo and parsed.utcoffset() is not None else None


def _regime(play: Mapping[str, Any], outcome: Mapping[str, Any]) -> str | None:
    """Return a recorded volatility/trend regime pair; missing metadata fails closed."""
    sources = (outcome, play.get("evidence") or {}, play.get("provenance") or {}, play)
    for source in sources:
        regime = source.get("regime") if isinstance(source, Mapping) else None
        if isinstance(regime, Mapping):
            vol, trend = regime.get("volatility"), regime.get("trend")
        elif isinstance(source, Mapping):
            vol, trend = source.get("volatility_regime"), source.get("trend_regime")
        else:
            continue
        if isinstance(vol, str) and vol and isinstance(trend, str) and trend:
            return f"{vol}|{trend}"
    return None


def _stable_drift(outcomes: list[Mapping[str, Any]]) -> tuple[bool, int]:
    """Require an explicit stable drift assessment for every completed option trade."""
    observed = 0
    for outcome in outcomes:
        value = outcome.get("drift_stable")
        if value is None and isinstance(outcome.get("drift"), Mapping):
            value = outcome["drift"].get("stable")
        if not isinstance(value, bool):
            return False, observed
        observed += 1
        if not value:
            return False, observed
    return bool(outcomes), observed


def _has_exact_option_identity(play: Mapping[str, Any]) -> bool:
    """Only a recorded listed OCC leg counts as a completed shadow option trade."""
    legs = play.get("legs")
    return isinstance(legs, list) and any(
        isinstance(leg, Mapping) and isinstance(leg.get("occ_symbol"), str) and bool(leg["occ_symbol"])
        for leg in legs
    )


def shadow_report(*, output_root: str | Path | None = None, spread_bps: float = 0.0,
                  slippage_bps: float = 0.0, required_sessions: int = READINESS_POLICY.min_sessions,
                  recorded_trial_count: int | None = None) -> dict[str, Any]:
    if spread_bps < 0 or slippage_bps < 0: raise ValueError("costs must be non-negative")
    if required_sessions != READINESS_POLICY.min_sessions:
        raise ValueError(f"required_sessions is frozen at {READINESS_POLICY.min_sessions}")
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    decisions = _rows(root / "shadow_decisions.jsonl"); outcomes = _rows(root / "shadow_outcomes.jsonl")
    realization_errors = _rows(root / "shadow_realization_errors.jsonl")
    plays = [play for d in decisions for play in (d.get("plays") or []) if isinstance(play, dict)]
    outcome_by_id = {row.get("play_id"): row for row in outcomes if isinstance(row.get("play_id"), str)}
    calibrated = []; buckets: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    returns = []
    for row in outcomes:
        probability, observed = row.get("calibrated_probability"), row.get("outcome")
        if row.get("confidence_kind") == "calibrated_probability" and isinstance(probability, (int, float)) and 0 <= probability <= 1 and isinstance(observed, bool):
            calibrated.append((float(probability), observed)); buckets[_bucket(float(probability))].append((float(probability), observed))
        if isinstance(row.get("gross_return_pct"), (int, float)):
            returns.append(float(row["gross_return_pct"]) - (spread_bps + slippage_bps) / 100.0)
    reliability = [{"bucket": key, "count": len(values), "mean_probability": sum(p for p, _ in values)/len(values),
                    "observed_rate": sum(y for _, y in values)/len(values)} for key, values in sorted(buckets.items())]
    n = len(calibrated)
    brier = sum((p - int(y)) ** 2 for p, y in calibrated) / n if n else None
    ece = sum(abs(item["mean_probability"] - item["observed_rate"]) * item["count"] / n for item in reliability) if n else None
    state_counts = Counter(str(play.get("state", "INVALID")) for play in plays)
    session_dates = {str(d.get("requested_for")) for d in decisions if isinstance(d.get("requested_for"), str)}
    warnings = [str(w) for d in decisions for w in (d.get("warnings") or [])]
    provider_failures = sum("provider" in w or "options_unavailable" in w for w in warnings) + sum("provider" in str(row.get("error")) for row in realization_errors)
    model_failures = sum("model" in w or "internal_models_unavailable" in w for w in warnings)
    unresolved = [p for p in plays if not isinstance(p.get("play_id"), str) or p.get("play_id") not in outcome_by_id]
    timestamp_violations = sum("invalid" in str(row.get("error")) or "timestamp" in str(row.get("error")) for row in realization_errors)
    decision_time_by_play: dict[str, datetime | None] = {}
    for decision in decisions:
        decision_time = _aware_timestamp(decision.get("asof_utc"))
        if decision_time is None:
            timestamp_violations += 1
        for recorded_play in decision.get("plays") or []:
            if isinstance(recorded_play, Mapping) and isinstance(recorded_play.get("play_id"), str):
                decision_time_by_play.setdefault(recorded_play["play_id"], decision_time)
    completed_trades: list[dict[str, Any]] = []
    completed_outcomes: list[Mapping[str, Any]] = []
    for play in plays:
        outcome = outcome_by_id.get(play.get("play_id"))
        if str(play.get("state")) != "ENTER" or not isinstance(outcome, Mapping):
            continue
        if not _has_exact_option_identity(play):
            continue
        decision_time = decision_time_by_play.get(play.get("play_id"))
        outcome_time = _aware_timestamp(outcome.get("outcome_asof_utc"))
        due_time = _aware_timestamp(outcome.get("due_utc"))
        if decision_time is None or outcome_time is None or due_time is None or outcome_time < due_time or due_time < decision_time:
            timestamp_violations += 1
        symbol = play.get("symbol") or play.get("underlying")
        regime = _regime(play, outcome)
        completed_trades.append({
            "play_id": play.get("play_id"), "symbol": symbol if isinstance(symbol, str) else None,
            "regime": regime, "outcome_date": outcome_time.date().isoformat() if outcome_time else None,
            "ask_to_bid_net_return_pct": outcome.get("ask_to_bid_net_return_pct"),
        })
        completed_outcomes.append(outcome)
    regimes = {trade["regime"] for trade in completed_trades if isinstance(trade.get("regime"), str)}
    drift_stable, drift_observations = _stable_drift(completed_outcomes)
    calibration_acceptable = bool(n and ece is not None and ece <= READINESS_POLICY.max_expected_calibration_error)
    checklist = {"required_sessions": READINESS_POLICY.min_sessions, "distinct_sessions": len(session_dates),
                 "required_completed_shadow_option_trades": READINESS_POLICY.min_completed_trades,
                 "completed_shadow_option_trades": len(completed_trades),
                 "required_regimes": READINESS_POLICY.min_regimes, "observed_regimes": len(regimes),
                 "all_decisions_realized": not unresolved, "unresolved_decisions": len(unresolved),
                 "timestamp_violations": timestamp_violations, "provider_failure_rate": provider_failures / len(decisions) if decisions else None,
                 "model_failure_rate": model_failures / len(decisions) if decisions else None,
                 "calibration_acceptable": calibration_acceptable, "drift_stable": drift_stable,
                 "drift_observations": drift_observations}
    checklist["ready"] = (checklist["distinct_sessions"] >= READINESS_POLICY.min_sessions
                           and checklist["completed_shadow_option_trades"] >= READINESS_POLICY.min_completed_trades
                           and checklist["observed_regimes"] >= READINESS_POLICY.min_regimes
                           and checklist["all_decisions_realized"] and not checklist["timestamp_violations"])
    promotion = evaluate_promotion_gate(checklist, completed_trades, recorded_trial_count=recorded_trial_count,
                                        calibration_acceptable=calibration_acceptable, drift_stable=drift_stable)
    return {"schema_version": "daily-plays-shadow-report-v1", "decisions": len(decisions), "plays": len(plays),
            "realized": len(outcomes), "reliability": reliability, "brier_score": brier, "expected_calibration_error": ece,
            "state_counts": dict(state_counts), "state_rates": {k: v / len(plays) for k, v in state_counts.items()} if plays else {},
            "abstention_rate": state_counts["ABSTAIN"] / len(plays) if plays else None,
            "realized_expectancy_pct": sum(returns) / len(returns) if returns else None,
            "cost_inputs": {"spread_bps": spread_bps, "slippage_bps": slippage_bps},
            "provider_failure_rate": checklist["provider_failure_rate"], "model_failure_rate": checklist["model_failure_rate"],
            "readiness_checklist": checklist, "promotion_gate": promotion}


def render_shadow_report(report: Mapping[str, Any]) -> str:
    checklist = report["readiness_checklist"]
    return "\n".join(["Shadow operations report", f"Decisions: {report['decisions']} | realized: {report['realized']}",
        f"Brier: {report['brier_score']} | ECE: {report['expected_calibration_error']}",
        f"Expectancy after {report['cost_inputs']['spread_bps']}bps spread + {report['cost_inputs']['slippage_bps']}bps slippage: {report['realized_expectancy_pct']}%",
        f"Shadow readiness: {'READY' if checklist['ready'] else 'NOT READY'} ({checklist['distinct_sessions']}/{checklist['required_sessions']} sessions; {checklist['completed_shadow_option_trades']}/{checklist['required_completed_shadow_option_trades']} completed; regimes={checklist['observed_regimes']}/{checklist['required_regimes']}; unresolved={checklist['unresolved_decisions']})",
        f"Promotion: {report['promotion_gate']['status']} (live capital remains disabled)"])
