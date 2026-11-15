"""One live options read: the gamma levels, and whether the chart agrees.

The gamma figures come from ``gamma_resistance``. This module only places
spot against those levels and reads the recent closes. A missing chart, a
missing spot, or a level the book withheld stays blank. Nothing here routes
an order.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .gamma_resistance import NEARBY_BAND_PCT

CHART_BARS = 5
MOVE_DEADBAND = 0.0025
_PRICE_MATCH = 0.009

_STANCES = ("agrees", "opposite", "stretched")
_REGIMES = ("positive", "negative", "neutral")
_ROLE_ORDER = {
    "nearby_support": 0,
    "put_wall": 1,
    "zero_gamma": 2,
    "absolute_gamma": 3,
    "call_resistance": 4,
}
_ROLE_LABEL = {
    "call_resistance": "Call resistance",
    "absolute_gamma": "Absolute gamma",
    "zero_gamma": "Zero gamma",
    "nearby_support": "Nearby support",
    "put_wall": "Put wall",
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _price(value: Any) -> float | None:
    number = _finite(value)
    if number is None or number <= 0:
        return None
    return number


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _blank(reason: str, sentence: str) -> dict[str, Any]:
    return {
        "stance": None,
        "reason": reason,
        "sentence": sentence,
        "move_pct": None,
        "reference_role": None,
        "reference_level": None,
    }


def _named_levels(
    *,
    call_resistance: float | None,
    nearby_support: float | None,
    zero_gamma: float | None,
    absolute_gamma_strike: float | None,
) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for role, level in (
        ("call_resistance", call_resistance),
        ("absolute_gamma", absolute_gamma_strike),
        ("zero_gamma", zero_gamma),
        ("nearby_support", nearby_support),
    ):
        if level is not None:
            found.append((role, level))
    return found


def _target_name(role: str | None) -> str:
    if role == "absolute_gamma":
        return "the gamma pin"
    if role == "midpoint":
        return "the middle of the band"
    if role == "zero_gamma":
        return "zero gamma"
    return "the level"


def chart_stance(
    *,
    spot: float | None,
    closes: Sequence[float] | None,
    call_resistance: float | None,
    nearby_support: float | None,
    zero_gamma: float | None,
    absolute_gamma_strike: float | None,
    regime: str | None,
) -> dict[str, Any]:
    """``agrees``, ``opposite``, ``stretched``, or a blank with a reason.

    Stretched means spot has left the shelves the book named. Agrees and
    opposite need a local close path: positive gamma should pin, negative
    gamma should extend. A flat chart is a real reading, not a filled-in zero
    for a missing level.
    """
    spot_price = _price(spot)
    if spot_price is None:
        return _blank("spot_missing", "The chain has no underlying price.")

    call_level = _price(call_resistance)
    support_level = _price(nearby_support)
    zero_level = _price(zero_gamma)
    pin_level = _price(absolute_gamma_strike)
    levels = _named_levels(
        call_resistance=call_level,
        nearby_support=support_level,
        zero_gamma=zero_level,
        absolute_gamma_strike=pin_level,
    )

    if call_level is not None and spot_price > call_level:
        return _stance(
            "stretched",
            "Spot is above call resistance.",
            reference_role="call_resistance",
            reference_level=call_level,
        )
    if support_level is not None and spot_price < support_level:
        return _stance(
            "stretched",
            "Spot is below nearby support.",
            reference_role="nearby_support",
            reference_level=support_level,
        )
    if levels:
        _role, nearest = min(levels, key=lambda item: abs(item[1] - spot_price))
        if abs(nearest - spot_price) / spot_price > NEARBY_BAND_PCT:
            return _stance(
                "stretched",
                "Spot is outside the nearby band.",
                reference_role=_role,
                reference_level=nearest,
            )

    if regime not in _REGIMES:
        return _blank(
            "regime_unmeasured",
            "Gamma at spot is unmeasured, so the chart has nothing to agree with.",
        )

    finite = [price for price in (closes or ()) if _price(price) is not None]
    if len(finite) < 2:
        return _blank("chart_missing", "No local price chart, so this does not call the move.")

    earlier = finite[-(CHART_BARS + 1)] if len(finite) > CHART_BARS else finite[0]
    last = finite[-1]
    move_pct = (last - earlier) / spot_price
    reference_role, reference = _reference(
        regime=regime,
        call_resistance=call_level,
        nearby_support=support_level,
        zero_gamma=zero_level,
        absolute_gamma_strike=pin_level,
    )
    if reference is None or reference_role is None:
        return _blank("no_reference_level", "No level is close enough to judge the chart.")

    name = _target_name(reference_role)
    toward = reference - spot_price
    flat = abs(move_pct) <= MOVE_DEADBAND
    moving_toward = (not flat) and toward != 0 and ((move_pct > 0) == (toward > 0))

    if regime == "negative":
        if flat:
            picked = "opposite"
            sentence = "The chart is flat while negative gamma says the move should extend."
        elif moving_toward:
            picked = "opposite"
            sentence = f"The chart is moving back toward {name}."
        else:
            picked = "agrees"
            sentence = f"The chart is extending away from {name}."
    elif flat:
        picked = "agrees"
        sentence = f"The chart is holding near {name}."
    elif moving_toward:
        picked = "agrees"
        sentence = f"The chart is moving back toward {name}."
    else:
        picked = "opposite"
        sentence = f"The chart is moving away from {name}."

    return _stance(
        picked,
        sentence,
        move_pct=move_pct,
        reference_role=reference_role,
        reference_level=reference,
    )


def _reference(
    *,
    regime: str,
    call_resistance: float | None,
    nearby_support: float | None,
    zero_gamma: float | None,
    absolute_gamma_strike: float | None,
) -> tuple[str | None, float | None]:
    if regime == "negative":
        if zero_gamma is not None:
            return "zero_gamma", zero_gamma
        if absolute_gamma_strike is not None:
            return "absolute_gamma", absolute_gamma_strike
        return None, None
    if absolute_gamma_strike is not None:
        return "absolute_gamma", absolute_gamma_strike
    if call_resistance is not None and nearby_support is not None:
        return "midpoint", (call_resistance + nearby_support) / 2.0
    if zero_gamma is not None:
        return "zero_gamma", zero_gamma
    if call_resistance is not None:
        return "call_resistance", call_resistance
    if nearby_support is not None:
        return "nearby_support", nearby_support
    return None, None


def _stance(
    stance: str,
    sentence: str,
    *,
    move_pct: float | None = None,
    reference_role: str | None = None,
    reference_level: float | None = None,
) -> dict[str, Any]:
    if stance not in _STANCES:
        raise ValueError(stance)
    return {
        "stance": stance,
        "reason": None,
        "sentence": sentence,
        "move_pct": _round(move_pct, 6),
        "reference_role": reference_role,
        "reference_level": _round(reference_level, 4),
    }


def _same_price(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) < _PRICE_MATCH


def levels_to_watch(gamma: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Named shelves that exist. A withheld level is omitted, not listed at zero."""
    spot = _price(gamma.get("spot"))
    if spot is None:
        return []
    call = gamma.get("call_resistance") if isinstance(gamma.get("call_resistance"), Mapping) else {}
    support = (
        gamma.get("nearby_support") if isinstance(gamma.get("nearby_support"), Mapping) else {}
    )
    wall = gamma.get("put_wall") if isinstance(gamma.get("put_wall"), Mapping) else {}
    candidates: list[tuple[str, float]] = []
    call_level = _price(call.get("level") if isinstance(call, Mapping) else None)
    support_level = _price(support.get("level") if isinstance(support, Mapping) else None)
    wall_level = _price(wall.get("level") if isinstance(wall, Mapping) else None)
    pin = _price(gamma.get("absolute_gamma_strike"))
    zero = _price(gamma.get("zero_gamma"))
    if call_level is not None:
        candidates.append(("call_resistance", call_level))
    if pin is not None:
        candidates.append(("absolute_gamma", pin))
    if zero is not None:
        candidates.append(("zero_gamma", zero))
    if support_level is not None:
        candidates.append(("nearby_support", support_level))
    if wall_level is not None and not _same_price(wall_level, support_level):
        candidates.append(("put_wall", wall_level))
    candidates.sort(key=lambda item: (item[1], _ROLE_ORDER.get(item[0], 9)))
    levels: list[dict[str, Any]] = []
    for role, level in candidates:
        levels.append(
            {
                "role": role,
                "label": _ROLE_LABEL[role],
                "level": level,
                "distance_pct": _round((level - spot) / spot, 6),
            }
        )
    return levels


def _close_values(closes: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in closes or ():
        if not isinstance(row, Mapping):
            continue
        close = _price(row.get("close"))
        if close is None:
            continue
        date = row.get("date")
        rows.append({"date": date if isinstance(date, str) and date else None, "close": close})
    return rows


def build_live_options(
    gamma: Mapping[str, Any],
    closes: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Panel payload. ``decision_authorized`` stays false. There is no order."""
    chart_rows = _close_values(closes)
    call = gamma.get("call_resistance") if isinstance(gamma.get("call_resistance"), Mapping) else {}
    support = (
        gamma.get("nearby_support") if isinstance(gamma.get("nearby_support"), Mapping) else {}
    )
    stance = chart_stance(
        spot=_finite(gamma.get("spot")),
        closes=[row["close"] for row in chart_rows],
        call_resistance=_finite(call.get("level")) if isinstance(call, Mapping) else None,
        nearby_support=_finite(support.get("level")) if isinstance(support, Mapping) else None,
        zero_gamma=_finite(gamma.get("zero_gamma")),
        absolute_gamma_strike=_finite(gamma.get("absolute_gamma_strike")),
        regime=gamma.get("regime") if isinstance(gamma.get("regime"), str) else None,
    )
    return {
        "symbol": gamma.get("symbol"),
        "decision_authorized": False,
        "gamma": dict(gamma),
        "chart": {
            "closes": chart_rows,
            **stance,
        },
        "levels": levels_to_watch(gamma),
    }
