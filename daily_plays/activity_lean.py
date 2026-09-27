"""Desk activity lean: bullish/bearish signs that never authorize a trade.

Priority:
1. provider-signed premium (aggressor known)
2. model / PEAD context side
3. call/put premium mix, optionally vs price impulse
4. price impulse alone

Call-heavy tape is a *bullish activity sign*, not a bought-call. Put-heavy
tape is a *bearish activity sign*, not a bought-put. ``decision_authorized``
stays false wherever this helper is used.
"""
from __future__ import annotations

from typing import Any


def describe_activity_lean(
    *,
    signed_net_premium: float | None = None,
    signed_print_count: int = 0,
    context_side: str | None = None,
    call_premium: float | None = None,
    put_premium: float | None = None,
    call_put_imbalance: float | None = None,
    price_impulse: str | None = None,
    ret_1d: float | None = None,
) -> dict[str, Any]:
    """Describe whether detected activity leans bullish or bearish.

    This is an activity sign for the desk — not a trade authorization.
    """
    signed_count = max(0, int(signed_print_count or 0))
    if signed_count > 0 and signed_net_premium is not None:
        net = float(signed_net_premium)
        if abs(net) < 1e-9:
            lean = "mixed"
        else:
            lean = "bullish" if net > 0 else "bearish"
        return {
            "activity_lean": lean,
            "activity_lean_source": "signed_flow",
            "activity_lean_label": lean.upper(),
            "decision_authorized": False,
        }

    ctx = str(context_side or "").strip().lower()
    if ctx in {"long", "bullish"}:
        return {
            "activity_lean": "bullish",
            "activity_lean_source": "model_context",
            "activity_lean_label": "BULLISH",
            "decision_authorized": False,
        }
    if ctx in {"short", "bearish"}:
        return {
            "activity_lean": "bearish",
            "activity_lean_source": "model_context",
            "activity_lean_label": "BEARISH",
            "decision_authorized": False,
        }
    if ctx == "mixed":
        return {
            "activity_lean": "mixed",
            "activity_lean_source": "model_context",
            "activity_lean_label": "MIXED",
            "decision_authorized": False,
        }

    imbalance = call_put_imbalance
    if imbalance is None:
        call_p = float(call_premium or 0.0)
        put_p = float(put_premium or 0.0)
        total = call_p + put_p
        if total > 0:
            imbalance = (call_p - put_p) / total

    prem_lean: str | None = None
    if imbalance is not None and abs(float(imbalance)) >= 0.15:
        prem_lean = "bullish" if float(imbalance) > 0 else "bearish"

    impulse = str(price_impulse or "").strip().lower()
    price_lean: str | None = None
    if impulse == "up" or (ret_1d is not None and float(ret_1d) > 0):
        price_lean = "bullish"
    elif impulse == "down" or (ret_1d is not None and float(ret_1d) < 0):
        price_lean = "bearish"

    if prem_lean and price_lean:
        if prem_lean == price_lean:
            return {
                "activity_lean": prem_lean,
                "activity_lean_source": "premium_and_price",
                "activity_lean_label": prem_lean.upper(),
                "decision_authorized": False,
            }
        return {
            "activity_lean": prem_lean,
            "activity_lean_source": "call_put_premium_vs_price",
            "activity_lean_label": prem_lean.upper(),
            "decision_authorized": False,
        }
    if prem_lean:
        return {
            "activity_lean": prem_lean,
            "activity_lean_source": "call_put_premium",
            "activity_lean_label": prem_lean.upper(),
            "decision_authorized": False,
        }
    if price_lean:
        return {
            "activity_lean": price_lean,
            "activity_lean_source": "price_impulse",
            "activity_lean_label": price_lean.upper(),
            "decision_authorized": False,
        }
    return {
        "activity_lean": "neutral",
        "activity_lean_source": "none",
        "activity_lean_label": "NEUTRAL",
        "decision_authorized": False,
    }


# Back-compat alias used by live_activity and its tests.
_activity_lean = describe_activity_lean
