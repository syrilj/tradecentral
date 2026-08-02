"""Pure candidate fusion for daily plays.

Fusion ranks research and model evidence; it is not a meta-model.  In
particular, Kronos and flow can never modify a model's calibrated probability.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_SUPPORTED_HORIZONS = {5, 10, 20}
_UNDERLYING_TARGET = "underlying_directional_return"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _horizon_days(value: Any) -> int | None:
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and result not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _direction_agrees(left: str | None, right: str | None) -> bool | None:
    if not left or not right or "neutral" in (left, right):
        return None
    return left == right


def entry_authorization_failures(confidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the frozen operating point that authorizes execution work."""
    failures: list[str] = []
    probability = _finite_number(confidence.get("calibrated_probability"))
    threshold = _finite_number(confidence.get("entry_threshold"))
    if threshold is None or not 0.5 <= threshold <= 1.0 or not confidence.get("threshold_version"):
        failures.append("calibrated_probability_operating_point_missing")
    elif probability is None or probability < threshold:
        failures.append("model_probability_below_entry_threshold")
    artifact = str(confidence.get("model_artifact_sha256") or "").lower()
    if not _SHA256_RE.fullmatch(artifact) or confidence.get("promotion_authorized") is not True:
        failures.append("model_artifact_not_promotion_authorized")
    return tuple(failures)


def fuse_candidate(
    internal: Mapping[str, Any],
    *,
    kronos: Mapping[str, Any] | None = None,
    flow: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine normalized records into a ranking candidate.

    ``state`` here is preliminary: downstream live option/risk gates can only
    downgrade it.  Ordinal and missing model confidence are always WATCH.
    """
    internal = dict(internal)
    model = dict(internal.get("model") or {})
    kronos = dict(kronos or {})
    flow = dict(flow or {})
    side = internal.get("side") or "neutral"
    model_kind = model.get("confidence_kind") or "unavailable"
    calibrated = model.get("probability") if model_kind == "calibrated_probability" else None
    probability_target = model.get("probability_target")
    horizon_days = _horizon_days(model.get("horizon_days"))
    entry_threshold = _finite_number(model.get("entry_threshold"))
    threshold_version = model.get("threshold_version")
    model_artifact_sha256 = model.get("artifact_sha256")
    promotion_authorized = model.get("promotion_authorized") is True
    kronos_agreement = _direction_agrees(side, kronos.get("direction"))
    flow_agreement = _direction_agrees(side, flow.get("direction"))
    contradictions = []
    if kronos_agreement is False:
        contradictions.append("kronos_direction_contradiction")
    if flow_agreement is False:
        contradictions.append("flow_direction_contradiction")
    research_support = sum(value is True for value in (kronos_agreement, flow_agreement))
    evidence_grade = "A" if research_support == 2 else "B" if research_support == 1 else "C" if not contradictions else "F"
    reasons = list(model.get("reasons") or [])
    reasons.extend(contradictions)
    setup_ok = bool(internal.get("setup_ok")) and side != "neutral"
    if not setup_ok:
        state = "ABSTAIN"
        reasons.append("no_directional_model_setup")
    elif model_kind != "calibrated_probability" or calibrated is None:
        state = "WATCH"
        reasons.append("model_probability_not_calibrated")
    elif probability_target != _UNDERLYING_TARGET or horizon_days not in _SUPPORTED_HORIZONS:
        # Do not infer target semantics from a probability or from an option
        # contract.  An old/unknown calibration can inform a WATCH record but
        # cannot be promoted through an execution gate.
        state = "WATCH"
        reasons.append("calibrated_probability_target_semantics_missing")
    elif authorization_failures := entry_authorization_failures({
        "calibrated_probability": calibrated,
        "entry_threshold": entry_threshold,
        "threshold_version": threshold_version,
        "model_artifact_sha256": model_artifact_sha256,
        "promotion_authorized": promotion_authorized,
    }):
        state = "WATCH"
        reasons.extend(authorization_failures)
    elif contradictions:
        state = "WATCH"
    else:
        # Execution validation is intentionally absent in fusion; callers must
        # not treat this as permission to enter an order.
        state = "WATCH"
        reasons.append("awaiting_live_execution_validation")
    calibrated_value = _finite_number(calibrated)
    ordinal_strength = abs(_finite_number(model.get("raw_score")) or 0.0)
    # An ordinal score is allowed to prioritize otherwise-equivalent baseline
    # research candidates, but is never promoted or labelled as a probability.
    model_component = calibrated_value if calibrated_value is not None else ordinal_strength
    rank_score = model_component
    # Research agreement is a tie-break only: it never changes the forecast.
    rank_score += 0.01 * research_support - 0.02 * len(contradictions)
    return {
        "symbol": internal.get("symbol"),
        "side": side,
        "state": state,
        "rank_score": round(rank_score, 6),
        "ranking": {
            "model_component": round(model_component, 6),
            "model_component_kind": "calibrated_probability" if calibrated_value is not None else "ordinal_strength",
            "ordinal_strength": round(ordinal_strength, 6) if calibrated_value is None else None,
        },
        "confidence": {
            "state": state,
            "model_probability": calibrated,
            "calibrated_probability": calibrated,
            "confidence_kind": model_kind,
            "calibration_version": model.get("calibration_version"),
            "probability_target": probability_target,
            "horizon_days": horizon_days,
            "entry_threshold": entry_threshold,
            "threshold_version": threshold_version,
            "model_artifact_sha256": model_artifact_sha256,
            "promotion_authorized": promotion_authorized,
            "evidence_grade": evidence_grade,
            "reasons": reasons,
            "failed_checks": contradictions,
        },
        "evidence": {"internal_model": internal, "kronos": kronos, "flow": flow},
    }


def rank_candidates(
    internal_models: Iterable[Mapping[str, Any]],
    *,
    kronos_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    flow_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fuse and return a bounded deterministic shortlist."""
    kronos_by_symbol = kronos_by_symbol or {}
    flow_by_symbol = flow_by_symbol or {}
    candidates = []
    for internal in internal_models:
        symbol = str(internal.get("symbol") or "").upper()
        candidates.append(fuse_candidate(
            internal,
            kronos=kronos_by_symbol.get(symbol),
            flow=flow_by_symbol.get(symbol),
        ))
    candidates.sort(key=lambda row: (-row["rank_score"], str(row.get("symbol") or ""),
                                     int((row.get("confidence") or {}).get("horizon_days") or 0)))
    # One underlying is one option-chain request.  The adapter intentionally
    # retains all horizons for offline research; this execution shortlist keeps
    # only the strongest score per symbol.  Equal scores resolve to the shorter
    # frozen horizon through the sort key above.
    unique: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        if symbol and symbol not in seen_symbols:
            unique.append(candidate)
            seen_symbols.add(symbol)
    for rank, candidate in enumerate(unique[:max(0, limit)], start=1):
        candidate["rank"] = rank
    return unique[:max(0, limit)]
