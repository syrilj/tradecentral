"""TypeSafe-backed live decision synthesis for the operator dashboard.

The market engines remain authoritative for measurements.  This module only
turns their compact, typed snapshot into semantic judgments, then applies
hard policy in code.  It never routes orders and never converts model
confidence into trading authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
SCHEMA_VERSION = "typesafe-live-decision-v1"
DEFAULT_MODEL = "jev-latest"

_REQUEST_LOCKS = [threading.Lock() for _ in range(64)]
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value == value and value not in {float("inf"), float("-inf")}:
            return value
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clamp01(value: Any, default: float = 0.0) -> float:
    number = _number(value)
    if number is None:
        return default
    return max(0.0, min(1.0, number))


def _clean_symbol(value: Any) -> str:
    symbol = "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum() or ch in ".-")
    if not symbol or len(symbol) > 10:
        raise ValueError("symbol must contain 1-10 ticker characters")
    return symbol


def _compact_state(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only the small decision contract; discard arbitrary client data."""

    symbol = _clean_symbol(raw.get("symbol"))
    source_status = {
        str(key)[:32]: str(value)[:160]
        for key, value in _mapping(raw.get("source_status")).items()
        if key in {"options", "regime", "microstructure", "vpa", "execution_gate"}
    }
    state: dict[str, Any] = {
        "symbol": symbol,
        "observed_at": str(raw.get("observed_at") or datetime.now(timezone.utc).isoformat())[:64],
        "source_status": source_status,
    }
    allowed: dict[str, tuple[str, ...]] = {
        "options": (
            "asof",
            "feed_age_seconds",
            "activity_lean",
            "signed_flow_imbalance",
            "signed_flow_confidence",
            "pressure_imbalance",
            "gex_regime",
            "net_gex_m",
            "spot",
            "call_wall",
            "put_wall",
            "gamma_flip",
        ),
        "regime": (
            "asof",
            "primary",
            "confidence",
            "bullish_probability",
            "bearish_probability",
            "neutral_probability",
            "transition_risk",
            "trend",
            "volatility",
            "flow",
        ),
        "microstructure": (
            "asof",
            "measurable",
            "regime",
            "regime_strength",
            "topography",
            "expected_behavior",
            "dealer_hedging_action",
        ),
        "vpa": (
            "asof",
            "market_phase",
            "sentiment",
            "confidence",
            "bias",
            "scenario_direction",
            "effort_result",
            "entry_trigger",
            "invalidation",
        ),
        "execution_gate": (
            "asof",
            "phase",
            "may_enter",
            "must_be_flat",
            "reason",
            "permitted_setups",
        ),
    }
    for section, keys in allowed.items():
        src = _mapping(raw.get(section))
        state[section] = {key: src[key] for key in keys if key in src}
    return state


def build_typesafe_request(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build one parallel System One request from the normalized snapshot."""

    return {
        "model": os.environ.get("TYPESAFE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "state": {key: value for key, value in state.items() if key != "observed_at"},
        "questions": {
            "lean": {
                "type": "choice",
                "instructions": (
                    "Which direction does the available measured market evidence lean? "
                    "Judge direction independently of entry permission or timing: a closed gate "
                    "can coexist with a bullish or bearish lean. Do not count dealer structure "
                    "and options flow as independent confirmations. Ignore stale or failed sources."
                ),
                "criteria": {
                    "bullish": "Usable evidence favors rising prices.",
                    "bearish": "Usable evidence favors falling prices.",
                    "neutral": "Usable evidence is balanced or conflicting.",
                    "unknown": "Insufficient usable evidence to judge direction.",
                },
            },
            "action": {
                "type": "choice",
                "instructions": (
                    "What is the best directional posture for `symbol` using the source timestamps and freshness? "
                    "Reconcile options flow, market regime, dealer microstructure, VPA, and the "
                    "execution gate. Missing or conflicting evidence should favor wait. This is "
                    "decision support, not permission to place an order."
                ),
                "criteria": {
                    "buy": "Fresh, measurable evidence aligns bullishly across multiple independent lenses.",
                    "sell": "Fresh, measurable evidence aligns bearishly across multiple independent lenses.",
                    "wait": "Evidence is mixed, stale, missing, low quality, transitional, or the gate is closed.",
                },
            },
            "setup": {
                "type": "choice",
                "instructions": "Which bounded setup best describes the current snapshot?",
                "criteria": {
                    "trend_continuation": "Direction and participation support continuation.",
                    "pullback_reversal": "VPA or flow shows rejection and a reversal from a defined level.",
                    "mean_reversion": "Long-gamma or balanced structure favors rotation toward value.",
                    "breakout": "Short-gamma or expanding volatility supports range escape.",
                    "no_setup": "No coherent setup is sufficiently supported.",
                },
            },
            "alignment": {
                "type": "score",
                "instructions": "How strongly do the independent directional lenses agree?",
                "criteria": [
                    "They conflict or most are unavailable",
                    "Weak agreement with material contradictions",
                    "Mixed but slightly directional",
                    "Clear agreement across several independent lenses",
                    "Broad, strong agreement with no material contradiction",
                ],
            },
            "timing": {
                "type": "score",
                "instructions": "How favorable is this exact moment for acting on the directional posture?",
                "criteria": [
                    "Do not act: closed gate, stale inputs, or no trigger",
                    "Poor timing: wait for confirmation or a better level",
                    "Neutral timing: watch closely",
                    "Good timing: current structure and trigger are supportive",
                    "Exceptional timing: fresh trigger, aligned structure, and open gate",
                ],
            },
            "risk": {
                "type": "score",
                "instructions": "How high is near-term execution risk in this snapshot?",
                "criteria": [
                    "Low: stable, liquid, measured, and well aligned",
                    "Contained: ordinary uncertainty with clear invalidation",
                    "Moderate: meaningful conflict, transition, or volatility",
                    "High: unstable structure, weak measurement, or poor timing",
                    "Extreme: closed gate, stale/failed sources, or disorderly conditions",
                ],
            },
        },
    }


def _local_judgments(state: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic outage fallback; explicit and deliberately conservative."""

    score = 0.0
    status = _mapping(state.get("source_status"))
    options = _mapping(state.get("options")) if status.get("options") == "ready" else {}
    regime = _mapping(state.get("regime")) if status.get("regime") == "ready" else {}
    vpa = _mapping(state.get("vpa")) if status.get("vpa") == "ready" else {}

    flow = _number(options.get("signed_flow_imbalance"))
    if flow is not None:
        score += 1.0 if flow >= 0.15 else -1.0 if flow <= -0.15 else 0.0
    else:
        lean = str(options.get("activity_lean") or "").lower()
        score += 0.75 if "bull" in lean else -0.75 if "bear" in lean else 0.0

    primary = str(regime.get("primary") or "").lower()
    score += 1.0 if "bull" in primary else -1.0 if "bear" in primary else 0.0
    bias = str(vpa.get("bias") or vpa.get("scenario_direction") or "").lower()
    score += 1.0 if "long" in bias or "bull" in bias or bias == "up" else 0.0
    score -= 1.0 if "short" in bias or "bear" in bias or bias == "down" else 0.0

    action = "buy" if score >= 2 else "sell" if score <= -2 else "wait"
    confidence = min(0.82, 0.38 + abs(score) * 0.12) if action != "wait" else 0.45
    probabilities = {
        "buy": max(0.05, min(0.9, 0.33 + score * 0.14)),
        "sell": max(0.05, min(0.9, 0.33 - score * 0.14)),
        "wait": 0.34,
    }
    total = sum(probabilities.values())
    probabilities = {key: round(value / total, 4) for key, value in probabilities.items()}
    return {
        "lean": {
            "choice": ("bullish" if score > 0 else "bearish" if score < 0 else
                       "neutral" if options or regime or vpa else "unknown"),
            "confidence": 0.0,
            "probabilities": {},
        },
        "action": {"choice": action, "confidence": confidence, "probabilities": probabilities},
        "setup": {"choice": "no_setup", "confidence": 0.0, "probabilities": {}},
        "alignment": {"score": min(4.0, abs(score)), "confidence": confidence},
        "timing": {"score": 2.0 if action != "wait" else 1.0, "confidence": confidence},
        "risk": {"score": 3.0 if action == "wait" else 2.0, "confidence": confidence},
    }


def _call_typesafe(payload: Mapping[str, Any], api_key: str) -> tuple[dict[str, Any], str, int]:
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    timeout = max(1.0, min(20.0, float(os.environ.get("TYPESAFE_TIMEOUT_S", "8") or 8)))
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(2):
        request = Request(
            TYPESAFE_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "TradeCentral/1 typesafe-live-decision",
            },
        )
        try:
            with urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - fixed HTTPS endpoint
                decoded = json.loads(response.read().decode("utf-8"))
            answers = decoded.get("answers")
            if not isinstance(answers, dict):
                raise ValueError("TypeSafe response did not contain an answers map")
            latency_ms = round((time.perf_counter() - started) * 1000)
            return (
                answers,
                str(decoded.get("model") or payload.get("model") or DEFAULT_MODEL),
                latency_ms,
            )
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 529} or attempt == 1:
                break
            time.sleep(0.2 * (2**attempt))
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            break
    detail = (
        f"HTTP {last_error.code}"
        if isinstance(last_error, HTTPError)
        else type(last_error).__name__
    )
    raise RuntimeError(f"TypeSafe request failed: {detail}") from last_error


def _choice(
    answers: Mapping[str, Any], key: str, allowed: set[str], default: str
) -> tuple[str, float, dict[str, float]]:
    answer = _mapping(answers.get(key))
    value = str(answer.get("choice") or default)
    if value not in allowed:
        value = default
    confidence = _clamp01(answer.get("confidence"))
    probabilities = {
        str(name): _clamp01(probability)
        for name, probability in _mapping(answer.get("probabilities")).items()
        if str(name) in allowed
    }
    return value, confidence, probabilities


def _score(answers: Mapping[str, Any], key: str, default: float) -> tuple[float, float]:
    answer = _mapping(answers.get(key))
    value = _number(answer.get("score"))
    return max(0.0, min(4.0, value if value is not None else default)), _clamp01(
        answer.get("confidence")
    )


def _compose_reasons(state: Mapping[str, Any], action: str) -> list[str]:
    reasons: list[str] = []
    options = _mapping(state.get("options"))
    regime = _mapping(state.get("regime"))
    micro = _mapping(state.get("microstructure"))
    vpa = _mapping(state.get("vpa"))
    flow_lean = options.get("activity_lean")
    if flow_lean:
        reasons.append(f"Options activity lean: {flow_lean}.")
    if regime.get("primary"):
        reasons.append(f"Regime: {regime['primary']}.")
    if micro.get("regime"):
        reasons.append(f"Dealer microstructure: {micro['regime']}.")
    if vpa.get("bias") or vpa.get("scenario_direction"):
        reasons.append(f"VPA: {vpa.get('bias') or vpa.get('scenario_direction')}.")
    if not reasons:
        reasons.append("No directional source supplied a usable read.")
    if action == "wait":
        reasons.append("Policy requires more alignment before taking directional risk.")
    return reasons[:5]


def _policy(answers: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    raw_action, confidence, probabilities = _choice(
        answers, "action", {"buy", "sell", "wait"}, "wait"
    )
    setup, setup_confidence, _ = _choice(
        answers,
        "setup",
        {"trend_continuation", "pullback_reversal", "mean_reversion", "breakout", "no_setup"},
        "no_setup",
    )
    alignment, alignment_confidence = _score(answers, "alignment", 0.0)
    timing, timing_confidence = _score(answers, "timing", 0.0)
    risk, risk_confidence = _score(answers, "risk", 4.0)

    gate = _mapping(state.get("execution_gate"))
    source_status = _mapping(state.get("source_status"))
    ready_sources = sum(1 for value in source_status.values() if str(value).lower() == "ready")
    blockers: list[str] = []
    if gate.get("must_be_flat") is True:
        blockers.append("Session policy requires positions to be flat.")
    elif gate.get("may_enter") is not True:
        blockers.append(str(gate.get("reason") or "Execution gate is not open."))
    if ready_sources < 3:
        blockers.append(f"Only {ready_sources} of 5 source lenses are ready.")
    if confidence < 0.55:
        blockers.append("Directional confidence is below the 55% display threshold.")
    if alignment < 2.0:
        blockers.append("Independent lenses are not sufficiently aligned.")
    if timing < 2.0:
        blockers.append("Timing judgment has not reached a usable trigger.")
    if risk >= 3.5:
        blockers.append("Near-term execution risk is extreme.")

    action = "wait" if blockers else raw_action
    if action == "wait" and raw_action == "wait" and not blockers:
        blockers.append("The synthesized posture is wait.")
    lean, lean_confidence, lean_probabilities = _choice(
        answers, "lean", {"bullish", "bearish", "neutral", "unknown"}, "unknown"
    )
    return {
        "lean": lean,
        "lean_confidence": lean_confidence,
        "lean_probabilities": lean_probabilities,
        "action": action,
        "raw_action": raw_action,
        "confidence": round(confidence, 4),
        "probabilities": probabilities,
        "setup": setup,
        "setup_confidence": round(setup_confidence, 4),
        "alignment": {"score": round(alignment, 3), "confidence": round(alignment_confidence, 4)},
        "timing": {"score": round(timing, 3), "confidence": round(timing_confidence, 4)},
        "risk": {"score": round(risk, 3), "confidence": round(risk_confidence, 4)},
        "blockers": blockers,
    }


def evaluate_live_decision(raw_state: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a live snapshot, using TypeSafe when configured.

    Identical snapshots are cached briefly so several open dashboard tabs do
    not spend tokens evaluating the same market instant.
    """

    if not isinstance(raw_state, Mapping):
        raise ValueError("request body must be a JSON object")
    state = _compact_state(raw_state)
    request_payload = build_typesafe_request(state)
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    fingerprint = hashlib.sha256(
        (
            hashlib.sha256(api_key.encode()).hexdigest()
            + json.dumps(request_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        ).encode()
    ).hexdigest()
    # Coalesce simultaneous tabs for the same evidence; bounded lock storage.
    with _REQUEST_LOCKS[int(fingerprint[:8], 16) % len(_REQUEST_LOCKS)]:
        return _evaluate_snapshot(state, request_payload, fingerprint, api_key)


def _evaluate_snapshot(
    state: dict[str, Any], request_payload: dict[str, Any], fingerprint: str, api_key: str
) -> dict[str, Any]:
    ttl = max(0.0, min(60.0, float(os.environ.get("TYPESAFE_CACHE_TTL_S", "15") or 15)))
    with _CACHE_LOCK:
        cached = _CACHE.get(fingerprint)
        if cached and time.monotonic() - cached[0] <= ttl:
            result = json.loads(json.dumps(cached[1]))
            result["observed_at"] = state["observed_at"]
            result["cache"] = {"hit": True, "ttl_seconds": ttl}
            return result

    engine_mode = "typesafe"
    engine_error: str | None = None
    latency_ms = 0
    model = str(request_payload["model"])
    if api_key:
        try:
            answers, model, latency_ms = _call_typesafe(request_payload, api_key)
        except RuntimeError as exc:
            engine_mode = "deterministic_fallback"
            engine_error = str(exc)
            answers = _local_judgments(state)
    else:
        engine_mode = "deterministic_fallback"
        engine_error = "TYPESAFE_API_KEY is not configured"
        answers = _local_judgments(state)

    policy = _policy(answers, state)
    result = {
        "schema_version": SCHEMA_VERSION,
        "symbol": state["symbol"],
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "observed_at": state["observed_at"],
        "engine": {
            "provider": "typesafe",
            "mode": engine_mode,
            "model": model if engine_mode == "typesafe" else None,
            "configured": bool(api_key),
            "latency_ms": latency_ms,
            "error": engine_error,
        },
        **policy,
        "reasons": _compose_reasons(state, policy["action"]),
        "source_status": state["source_status"],
        "decision_authorized": False,
        "notice": "Decision support only. No order is placed or authorized.",
        "cache": {"hit": False, "ttl_seconds": ttl},
    }
    with _CACHE_LOCK:
        _CACHE[fingerprint] = (time.monotonic(), result)
        if len(_CACHE) > 128:
            oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
            _CACHE.pop(oldest, None)
    return json.loads(json.dumps(result))


__all__ = ["build_typesafe_request", "evaluate_live_decision", "SCHEMA_VERSION"]
