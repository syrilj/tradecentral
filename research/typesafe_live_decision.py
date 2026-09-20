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
SCHEMA_VERSION = "typesafe-live-decision-v2"
DEFAULT_MODEL = "jev-latest"
_ACTIONS = ("buy", "sell")
_ACTION_SET = set(_ACTIONS)

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


def _risk_label(score: float) -> str:
    if score >= 3.5:
        return "EXTREME"
    if score >= 2.5:
        return "HIGH"
    if score >= 1.5:
        return "MODERATE"
    if score >= 0.5:
        return "LOW"
    return "NONE"


def _binary_probabilities(buy: float) -> dict[str, float]:
    buy_r = round(max(0.0, min(1.0, buy)), 4)
    return {"buy": buy_r, "sell": round(1.0 - buy_r, 4)}


def _normalize_binary(raw: Mapping[str, Any]) -> dict[str, float]:
    buy = _clamp01(raw.get("buy"))
    sell = _clamp01(raw.get("sell"))
    total = buy + sell
    if total <= 0:
        return {"buy": 0.5, "sell": 0.5}
    return _binary_probabilities(buy / total)


def _directional_sign(value: Any) -> float:
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    if text in {"up", "buy", "long"}:
        return 1.0
    if text in {"down", "sell", "short"}:
        return -1.0
    if any(token in text for token in ("bear", "short", "markdown", "distribut", "supply")):
        return -1.0
    if any(token in text for token in ("bull", "long", "markup", "accumul", "demand")):
        return 1.0
    return 0.0


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
                    "Judge the next directional action for `symbol` from the measured evidence. "
                    "Use source timestamps and freshness. Reconcile options flow, market regime, "
                    "dealer microstructure, and VPA. Missing, stale, or conflicting evidence must "
                    "lower confidence and raise risk; it must not produce a wait. Ignore the "
                    "execution gate for this choice — code applies stay-out policy separately. "
                    "If evidence is absent or balanced, still pick buy or sell with coin-flip "
                    "confidence. This is decision support, not permission to place an order."
                ),
                "criteria": {
                    "buy": (
                        "The next directional action is to buy: usable evidence favors rising "
                        "prices, including a weak or contested bullish lean."
                    ),
                    "sell": (
                        "The next directional action is to sell: usable evidence favors falling "
                        "prices, including a weak or contested bearish lean."
                    ),
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
                    "Unusable moment: closed gate, stale inputs, or no trigger",
                    "Poor timing: confirmation or a better level is still missing",
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
            "vpa_direction": {
                "type": "choice",
                "instructions": (
                    "Using only the VPA fields (`vpa.bias`, `vpa.scenario_direction`, "
                    "`vpa.market_phase`, `vpa.effort_result`, `vpa.sentiment`), which "
                    "directional action does volume-price analysis support? Ignore the "
                    "execution gate and all non-VPA sources. Do not replace VPA math; "
                    "judge the supplied fields. If VPA is missing, mixed, or neutral, "
                    "still choose buy or sell with low confidence."
                ),
                "criteria": {
                    "buy": (
                        "VPA bias, phase, sentiment, or scenario direction favors buying "
                        "(LONG, BULLISH, markup, accumulation)."
                    ),
                    "sell": (
                        "VPA bias, phase, sentiment, or scenario direction favors selling "
                        "(SHORT, BEARISH, markdown, distribution)."
                    ),
                },
            },
            "vpa_claim_support": {
                "type": "score",
                "instructions": (
                    "How well does the measured VPA evidence support the stated VPA bias "
                    "and market phase? Judge only the VPA fields. Do not replace VPA math; "
                    "assess whether those supplied fields hang together."
                ),
                "criteria": [
                    (
                        "Unsupported: VPA fields are missing, failed, or empty, so the "
                        "stated bias or phase has no measured backing."
                    ),
                    (
                        "Weakly supported: a stated VPA bias or phase is present but almost "
                        "no corroborating VPA field agrees with it."
                    ),
                    (
                        "Mixed: some VPA fields back the stated bias or phase while others "
                        "contradict it or read as congestion/neutral."
                    ),
                    (
                        "Well supported: several independent VPA fields agree with the "
                        "stated bias and phase, with only minor tension."
                    ),
                    (
                        "Tightly supported: bias, scenario direction, market phase, "
                        "sentiment, and effort-result all agree without contradiction."
                    ),
                ],
            },
        },
    }


def _vpa_local_answers(state: Mapping[str, Any]) -> dict[str, Any]:
    status = _mapping(state.get("source_status"))
    ready = str(status.get("vpa") or "").lower() == "ready"
    if not ready:
        return {
            "vpa_direction": {
                "choice": "buy",
                "confidence": 0.5,
                "probabilities": {"buy": 0.5, "sell": 0.5},
            },
            "vpa_claim_support": {"score": 0.0, "confidence": 0.35},
        }

    vpa = _mapping(state.get("vpa"))
    votes = [
        _directional_sign(vpa.get("bias")),
        _directional_sign(vpa.get("scenario_direction")),
        _directional_sign(vpa.get("market_phase")),
        _directional_sign(vpa.get("sentiment")),
    ]
    net = sum(votes)
    nonzero = [vote for vote in votes if vote]
    effort = str(vpa.get("effort_result") or "").lower()
    effort_ok = "valid" in effort
    effort_bad = "anoma" in effort or "mixed" in effort
    present = any(
        str(vpa.get(key) or "").strip()
        for key in ("bias", "scenario_direction", "market_phase", "sentiment", "effort_result")
    )
    if not present:
        support = 0.0
    elif not nonzero:
        support = 1.0
    elif net == 0:
        support = 2.0
    else:
        sign = 1.0 if net > 0 else -1.0
        agree = sum(1 for vote in nonzero if vote == sign)
        contradict = sum(1 for vote in nonzero if vote == -sign)
        if contradict:
            support = 2.0
        elif agree >= 3 and effort_ok:
            support = 4.0
        elif agree >= 2:
            support = 2.0 if effort_bad else 3.0
        else:
            support = 1.0

    direction = "buy" if net > 0 else "sell" if net < 0 else "buy"
    confidence = 0.5 if net == 0 else min(0.82, 0.42 + abs(net) * 0.12)
    buy_p = 0.5 if net == 0 else max(0.05, min(0.95, 0.5 + net * 0.15))
    return {
        "vpa_direction": {
            "choice": direction,
            "confidence": confidence,
            "probabilities": _binary_probabilities(buy_p),
        },
        "vpa_claim_support": {"score": support, "confidence": min(0.82, 0.35 + support * 0.12)},
    }


def _compute_model_votes(state: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], float]:
    """Extract continuous directional signals and weights from the four model lenses."""
    status = _mapping(state.get("source_status"))
    options = _mapping(state.get("options"))
    regime = _mapping(state.get("regime"))
    micro = _mapping(state.get("microstructure"))
    vpa = _mapping(state.get("vpa"))

    # 1. Flow model
    flow = _number(options.get("signed_flow_imbalance"))
    activity_lean = str(options.get("activity_lean") or "").lower()
    gex_regime = str(options.get("gex_regime") or "").lower()
    flow_ready = status.get("options") == "ready"
    if not flow_ready:
        flow_sig = 0.0
        flow_label = "neutral"
        flow_summary = "Options source unavailable or unmeasured"
    elif flow is not None:
        flow_sig = max(-1.0, min(1.0, flow * 2.0))
        if "neg" in gex_regime and flow_sig != 0:
            flow_sig = max(-1.0, min(1.0, flow_sig * 1.2))
        flow_label = "bullish" if flow_sig > 0.10 else "bearish" if flow_sig < -0.10 else "neutral"
        flow_summary = f"Signed flow imbalance {flow:+.2f} ({flow_label})"
        if gex_regime:
            flow_summary += f", {gex_regime} GEX"
    else:
        flow_sig = 0.8 if "bull" in activity_lean else -0.8 if "bear" in activity_lean else 0.0
        flow_label = "bullish" if flow_sig > 0 else "bearish" if flow_sig < 0 else "neutral"
        flow_summary = f"Activity lean {activity_lean or 'unmeasured'}"

    # 2. Regime model
    regime_ready = status.get("regime") == "ready"
    primary = str(regime.get("primary") or "").lower()
    bull_p = _number(regime.get("bullish_probability"))
    bear_p = _number(regime.get("bearish_probability"))
    if not regime_ready:
        regime_sig = 0.0
        regime_label = "neutral"
        regime_summary = "Regime classifier unavailable"
    elif bull_p is not None and bear_p is not None:
        diff = bull_p - bear_p
        regime_sig = max(-1.0, min(1.0, diff * 2.0))
        regime_label = (
            "bullish" if regime_sig > 0.10 else "bearish" if regime_sig < -0.10 else "neutral"
        )
        regime_summary = f"P(bull)={bull_p:.0%} vs P(bear)={bear_p:.0%} ({primary or 'measured'})"
    else:
        regime_sig = 0.85 if "bull" in primary else -0.85 if "bear" in primary else 0.0
        regime_label = "bullish" if regime_sig > 0 else "bearish" if regime_sig < 0 else "neutral"
        regime_summary = f"Regime {primary or 'unmeasured'}"

    # 3. Microstructure model
    micro_ready = status.get("microstructure") == "ready"
    dealer_regime = str(micro.get("regime") or "").lower()
    hedging = str(micro.get("dealer_hedging_action") or "").lower()
    if not micro_ready:
        micro_sig = 0.0
        micro_label = "neutral"
        micro_summary = "Dealer microstructure unavailable"
    elif any(w in hedging for w in ("bull", "buy", "bid", "stabilizing_long", "up")):
        micro_sig = 0.8
        micro_label = "bullish"
        micro_summary = f"Dealer hedging supportive ({hedging})"
    elif any(w in hedging for w in ("bear", "sell", "ask", "accelerating_down", "down")):
        micro_sig = -0.8
        micro_label = "bearish"
        micro_summary = f"Dealer hedging pressing ({hedging})"
    elif "pos" in dealer_regime:
        micro_sig = 0.25 if flow_sig > 0.1 else -0.25 if flow_sig < -0.1 else 0.0
        micro_label = "bullish" if micro_sig > 0 else "bearish" if micro_sig < 0 else "neutral"
        micro_summary = f"Positive gamma pin/stabilization ({dealer_regime})"
    elif "neg" in dealer_regime:
        micro_sig = 0.45 if flow_sig > 0.1 else -0.45 if flow_sig < -0.1 else 0.0
        micro_label = "bullish" if micro_sig > 0 else "bearish" if micro_sig < 0 else "neutral"
        micro_summary = f"Negative gamma acceleration ({dealer_regime})"
    else:
        micro_sig = 0.0
        micro_label = "neutral"
        micro_summary = f"Dealer regime {dealer_regime or 'unmeasured'}"

    # 4. VPA model
    vpa_ready = status.get("vpa") == "ready"
    vpa_bias = str(vpa.get("bias") or vpa.get("scenario_direction") or "").lower()
    market_phase = str(vpa.get("market_phase") or "").lower()
    vpa_sentiment = str(vpa.get("sentiment") or "").lower()
    if not vpa_ready:
        vpa_sig = 0.0
        vpa_label = "neutral"
        vpa_summary = "VPA engine unavailable"
    else:
        v_score = 0.0
        if any(w in vpa_bias for w in ("long", "bull", "up")):
            v_score += 0.7
        elif any(w in vpa_bias for w in ("short", "bear", "down")):
            v_score -= 0.7
        if "markup" in market_phase or "accum" in market_phase:
            v_score += 0.35
        elif "markdown" in market_phase or "distrib" in market_phase:
            v_score -= 0.35
        if "bull" in vpa_sentiment:
            v_score += 0.15
        elif "bear" in vpa_sentiment:
            v_score -= 0.15
        vpa_sig = max(-1.0, min(1.0, v_score))
        vpa_label = "bullish" if vpa_sig > 0.10 else "bearish" if vpa_sig < -0.10 else "neutral"
        vpa_summary = (
            f"VPA bias {vpa_bias.upper() or 'neutral'} · {market_phase or 'phase unmeasured'}"
        )

    models = {
        "options_flow": {
            "signal": flow_label,
            "score": round(flow_sig, 3),
            "weight": 1.0 if flow_ready else 0.0,
            "summary": flow_summary,
        },
        "regime": {
            "signal": regime_label,
            "score": round(regime_sig, 3),
            "weight": 1.0 if regime_ready else 0.0,
            "summary": regime_summary,
        },
        "microstructure": {
            "signal": micro_label,
            "score": round(micro_sig, 3),
            "weight": 0.85 if micro_ready else 0.0,
            "summary": micro_summary,
        },
        "vpa": {
            "signal": vpa_label,
            "score": round(vpa_sig, 3),
            "weight": 1.0 if vpa_ready else 0.0,
            "summary": vpa_summary,
        },
    }
    total_w = sum(m["weight"] for m in models.values())
    c_score = (
        sum(m["score"] * m["weight"] for m in models.values()) / total_w if total_w > 0 else 0.0
    )
    c_score = max(-1.0, min(1.0, c_score))
    return models, c_score


def _build_brain(
    state: Mapping[str, Any],
    action: str,
    confidence: float,
    lean: str,
    consensus_score: float | None = None,
) -> dict[str, Any]:
    models, computed_score = _compute_model_votes(state)
    c_score = consensus_score if consensus_score is not None else computed_score
    c_score = max(-1.0, min(1.0, c_score))

    target_label = "bullish" if action == "buy" else "bearish"
    agreeing = sum(1 for m in models.values() if m["weight"] > 0 and m["signal"] == target_label)
    opposing = sum(
        1
        for m in models.values()
        if m["weight"] > 0 and m["signal"] not in {target_label, "neutral"}
    )
    total_active = sum(1 for m in models.values() if m["weight"] > 0)

    if agreeing >= 3 and opposing <= 1:
        confluence = "HIGH"
    elif agreeing >= 2 and opposing <= 1:
        confluence = "MODERATE"
    elif opposing >= 2:
        confluence = "CONTESTED"
    else:
        confluence = "BALANCED"

    if agreeing >= 3:
        rationale = (
            f"Broad confluence: {agreeing} of {total_active} models strongly agree on "
            f"{action.upper()} posture with high stability."
        )
    elif agreeing >= 2:
        rationale = (
            f"Directional alignment: {agreeing} of {total_active} models favor "
            f"{action.upper()} while {opposing} oppose; noise filtered."
        )
    elif total_active == 0:
        rationale = "No active model inputs available; operating in cautious standby posture."
    else:
        rationale = (
            f"Contested signals ({agreeing} {action.upper()} vs {opposing} opposing); "
            "brain anchors to conservative risk threshold."
        )

    return {
        "consensus_score": round(c_score, 3),
        "confluence": confluence,
        "stabilized": True,
        "agreeing_models": agreeing,
        "total_models": total_active,
        "models": models,
        "rationale": rationale,
    }


def _local_judgments(state: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic outage fallback; multi-model consensus brain with hysteresis."""
    models, c_score = _compute_model_votes(state)
    total_active = sum(1 for m in models.values() if m["weight"] > 0)

    if total_active == 0:
        action = "buy"
        confidence = 0.55
        probabilities = {"buy": 0.55, "sell": 0.45}
        answers = {
            "lean": {"choice": "unknown", "confidence": 0.0, "probabilities": {}},
            "action": {"choice": action, "confidence": confidence, "probabilities": probabilities},
            "setup": {"choice": "no_setup", "confidence": 0.0, "probabilities": {}},
            "alignment": {"score": 0.0, "confidence": confidence},
            "timing": {"score": 1.0, "confidence": confidence},
            "risk": {"score": 3.5, "confidence": confidence},
        }
        answers.update(_vpa_local_answers(state))
        answers["brain"] = _build_brain(state, action, confidence, "unknown", 0.0)
        return answers

    # Deadband hysteresis around zero to prevent second-guessing and jitter
    if c_score > 0.035:
        action = "buy"
    elif c_score < -0.035:
        action = "sell"
    else:
        # Tie-breaker when consensus is within neutral deadband [-0.035, +0.035]
        regime = _mapping(state.get("regime"))
        bull_p = _number(regime.get("bullish_probability"))
        bear_p = _number(regime.get("bearish_probability"))
        reg_diff = (bull_p - bear_p) if (bull_p is not None and bear_p is not None) else 0.0
        options = _mapping(state.get("options"))
        flow_val = _number(options.get("signed_flow_imbalance"))
        vpa = _mapping(state.get("vpa"))
        market_phase = str(vpa.get("market_phase") or "").lower()

        if reg_diff > 0.02:
            action = "buy"
        elif reg_diff < -0.02:
            action = "sell"
        elif flow_val is not None and flow_val > 0.01:
            action = "buy"
        elif flow_val is not None and flow_val < -0.01:
            action = "sell"
        elif "markup" in market_phase or "accum" in market_phase:
            action = "buy"
        elif "markdown" in market_phase or "distrib" in market_phase:
            action = "sell"
        else:
            action = "buy"

    agreeing_bull = sum(1 for m in models.values() if m["weight"] > 0 and m["signal"] == "bullish")
    agreeing_bear = sum(1 for m in models.values() if m["weight"] > 0 and m["signal"] == "bearish")
    agreeing = agreeing_bull if action == "buy" else agreeing_bear
    opposing = agreeing_bear if action == "buy" else agreeing_bull

    if agreeing >= 3 and opposing <= 1:
        confluence = "HIGH"
        confidence = round(min(0.90, 0.76 + 0.14 * abs(c_score)), 4)
        alignment = 3.5
    elif agreeing >= 2 and opposing <= 1:
        confluence = "MODERATE"
        confidence = round(min(0.82, 0.68 + 0.12 * abs(c_score)), 4)
        alignment = 2.6
    elif opposing >= 2:
        confluence = "CONTESTED"
        confidence = round(max(0.60, min(0.70, 0.62 + 0.08 * abs(c_score))), 4)
        alignment = 1.2
    else:  # BALANCED
        confluence = "BALANCED"
        confidence = round(max(0.60, min(0.68, 0.62 + 0.08 * abs(c_score))), 4)
        alignment = 1.5

    lean = "bullish" if c_score > 0.08 else "bearish" if c_score < -0.08 else "neutral"

    if action == "buy":
        probabilities = {"buy": confidence, "sell": round(1.0 - confidence, 4)}
    else:
        probabilities = {"sell": confidence, "buy": round(1.0 - confidence, 4)}

    timing = round(
        min(
            4.0,
            max(
                1.0,
                2.2
                + 1.2 * abs(c_score)
                + (0.5 if agreeing >= 3 else 0.0)
                - (0.5 if opposing >= 2 else 0.0),
            ),
        ),
        3,
    )
    risk = round(max(1.0, min(3.8, 2.2 - abs(c_score) * 0.8 + opposing * 0.6)), 3)

    options = _mapping(state.get("options"))
    regime = _mapping(state.get("regime"))
    micro = _mapping(state.get("microstructure"))
    vpa = _mapping(state.get("vpa"))
    gex_regime = str(options.get("gex_regime") or "").lower()
    primary = str(regime.get("primary") or "").lower()
    dealer_regime = str(micro.get("regime") or "").lower()

    if "neg" in gex_regime or "break" in primary:
        setup = "breakout"
    elif "pos" in dealer_regime and abs(c_score) < 0.4:
        setup = "mean_reversion"
    elif "revers" in str(vpa.get("scenario_direction") or "").lower():
        setup = "pullback_reversal"
    elif abs(c_score) >= 0.25:
        setup = "trend_continuation"
    else:
        setup = "no_setup"

    brain_data = _build_brain(state, action, confidence, lean, c_score)

    answers = {
        "lean": {
            "choice": lean,
            "confidence": round(confidence, 4),
            "probabilities": {},
        },
        "action": {"choice": action, "confidence": confidence, "probabilities": probabilities},
        "setup": {"choice": setup, "confidence": confidence, "probabilities": {}},
        "alignment": {"score": alignment, "confidence": confidence},
        "timing": {"score": timing, "confidence": confidence},
        "risk": {"score": risk, "confidence": confidence},
        "brain": brain_data,
    }
    answers.update(_vpa_local_answers(state))
    return answers


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
    binary = allowed == _ACTION_SET
    confidence = _clamp01(answer.get("confidence"))
    probabilities = {
        str(name): _clamp01(probability)
        for name, probability in _mapping(answer.get("probabilities")).items()
        if str(name) in allowed
    }
    if binary:
        probabilities = _normalize_binary(probabilities)
    reported = str(answer.get("choice") or "")
    value = reported or default
    if value not in allowed:
        if binary:
            value = "buy" if probabilities["buy"] >= probabilities["sell"] else "sell"
        elif probabilities:
            value = max(probabilities, key=probabilities.get)
            if value not in allowed:
                value = default
        else:
            value = default
        if reported == "wait":
            confidence = min(confidence, 0.5)
    return value, confidence, probabilities


def _score(answers: Mapping[str, Any], key: str, default: float) -> tuple[float, float]:
    answer = _mapping(answers.get(key))
    value = _number(answer.get("score"))
    return max(0.0, min(4.0, value if value is not None else default)), _clamp01(
        answer.get("confidence")
    )


def _compose_reasons(state: Mapping[str, Any], action: str, keep_out: bool) -> list[str]:
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
    if keep_out:
        note = f"Policy keeps the operator out while the directional call remains {action}."
        reasons = reasons[:4] + [note]
    return reasons[:5]


def _policy(answers: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    raw_action, confidence, probabilities = _choice(answers, "action", _ACTION_SET, "buy")
    action = raw_action if raw_action in _ACTION_SET else "buy"
    probabilities = _normalize_binary(probabilities)
    setup, setup_confidence, _ = _choice(
        answers,
        "setup",
        {"trend_continuation", "pullback_reversal", "mean_reversion", "breakout", "no_setup"},
        "no_setup",
    )
    alignment, alignment_confidence = _score(answers, "alignment", 0.0)
    timing, timing_confidence = _score(answers, "timing", 0.0)
    risk, risk_confidence = _score(answers, "risk", 4.0)
    vpa_direction, vpa_confidence, vpa_probabilities = _choice(
        answers, "vpa_direction", _ACTION_SET, "buy"
    )
    vpa_support, vpa_support_confidence = _score(answers, "vpa_claim_support", 0.0)

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

    keep_out = bool(blockers) or risk >= 3.5 or confidence < 0.55 or alignment < 2.0 or timing < 2.0
    risk_reasons = list(blockers)
    if keep_out:
        risk_reasons.append(f"Stay-out policy is active; directional call remains {action}.")
    if vpa_support < 1.5:
        risk_reasons.append("VPA claim is weakly supported by measured VPA fields.")
    if vpa_direction != action:
        risk_reasons.append(
            f"VPA next action is {vpa_direction} while the composite call is {action}."
        )
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
        "risk_assessment": {
            "score": round(risk, 3),
            "label": _risk_label(risk),
            "reasons": risk_reasons,
            "keep_out": keep_out,
        },
        "vpa_judgment": {
            "direction": vpa_direction,
            "confidence": round(vpa_confidence, 4),
            "probabilities": _normalize_binary(vpa_probabilities),
            "claim_support": {
                "score": round(vpa_support, 3),
                "confidence": round(vpa_support_confidence, 4),
            },
        },
        "brain": answers.get("brain") or _build_brain(state, action, confidence, lean),
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
        "reasons": _compose_reasons(state, policy["action"], policy["risk_assessment"]["keep_out"]),
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
