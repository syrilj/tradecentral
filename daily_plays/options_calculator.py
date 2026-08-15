"""Closed-form options P/L and Greeks. No broker path, no order routing."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence


MULTIPLIER = 100.0
DAYS_PER_YEAR = 365.0


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _right(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"c", "call", "calls"}:
        return "call"
    if token in {"p", "put", "puts"}:
        return "put"
    raise ValueError("right must be call or put")


def _years(*, years: float | None, dte: float | None, expiry: str | None) -> float:
    if years is not None:
        return max(0.0, float(years))
    if dte is not None:
        return max(0.0, float(dte)) / DAYS_PER_YEAR
    if expiry:
        day = date.fromisoformat(str(expiry)[:10])
        today = datetime.now(timezone.utc).date()
        return max(0.0, (day - today).days) / DAYS_PER_YEAR
    return 30.0 / DAYS_PER_YEAR


def black_scholes(
    *,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    vol: float,
    right: str,
) -> dict[str, float]:
    """European Black–Scholes price and Greeks (theta per day, vega per 1 vol point)."""
    right_n = _right(right)
    if years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        intrinsic = max(spot - strike, 0.0) if right_n == "call" else max(strike - spot, 0.0)
        if right_n == "call":
            delta = 1.0 if spot > strike else 0.0 if spot < strike else 0.5
        else:
            delta = -1.0 if spot < strike else 0.0 if spot > strike else -0.5
        return {
            "price": intrinsic,
            "delta": delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
        }
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * root_t)
    d2 = d1 - vol * root_t
    discount = math.exp(-rate * years)
    density = _norm_pdf(d1)
    if right_n == "call":
        price = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_year = -(spot * density * vol) / (2.0 * root_t) - rate * strike * discount * _norm_cdf(d2)
    else:
        price = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_year = -(spot * density * vol) / (2.0 * root_t) + rate * strike * discount * _norm_cdf(-d2)
    gamma = density / (spot * vol * root_t)
    vega_point = spot * density * root_t * 0.01
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta_year / DAYS_PER_YEAR,
        "vega": vega_point,
    }


def expiry_intrinsic(*, spot: float, strike: float, right: str, multiplier: float = MULTIPLIER) -> float:
    if _right(right) == "call":
        return max(float(spot) - float(strike), 0.0) * float(multiplier)
    return max(float(strike) - float(spot), 0.0) * float(multiplier)


def expiry_pnl(
    *,
    spot: float,
    strike: float,
    right: str,
    debit: float,
    multiplier: float = MULTIPLIER,
    quantity: float = 1.0,
) -> float:
    """Long-option expiry P/L: max(S−K,0)*100 − debit for a call (put mirrored)."""
    return expiry_intrinsic(spot=spot, strike=strike, right=right, multiplier=multiplier) * float(quantity) - float(debit)


def _leg_debit(leg: Mapping[str, Any], *, multiplier: float) -> float:
    quantity = float(leg.get("quantity") or 1.0)
    if leg.get("debit") is not None:
        return float(leg["debit"])
    premium = float(leg.get("premium") or 0.0)
    return premium * float(multiplier) * quantity


def _normalize_legs(
    *,
    strategy: str,
    strike: float | None,
    premium: float | None,
    debit: float | None,
    quantity: float,
    legs: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if legs:
        normalized = []
        for raw in legs:
            right = _right(raw.get("right") or raw.get("option_type"))
            qty = float(raw.get("quantity") or 1.0)
            normalized.append({
                "right": right,
                "strike": float(raw["strike"]),
                "quantity": qty,
                "premium": None if raw.get("premium") is None else float(raw["premium"]),
                "debit": None if raw.get("debit") is None else float(raw["debit"]),
                "vol": None if raw.get("vol") is None else float(raw["vol"]),
            })
        return normalized
    name = str(strategy or "long_call").strip().lower()
    if strike is None:
        raise ValueError("strike is required")
    if name in {"long_call", "call"}:
        return [{"right": "call", "strike": float(strike), "quantity": quantity, "premium": premium, "debit": debit, "vol": None}]
    if name in {"long_put", "put"}:
        return [{"right": "put", "strike": float(strike), "quantity": quantity, "premium": premium, "debit": debit, "vol": None}]
    if name in {"long_straddle", "straddle"}:
        share = None if debit is None else float(debit) / 2.0
        return [
            {"right": "call", "strike": float(strike), "quantity": quantity, "premium": premium, "debit": share, "vol": None},
            {"right": "put", "strike": float(strike), "quantity": quantity, "premium": premium, "debit": share, "vol": None},
        ]
    raise ValueError("unsupported strategy")


def evaluate_strategy(
    *,
    strategy: str = "long_call",
    spot: float,
    strike: float | None = None,
    years: float | None = None,
    dte: float | None = None,
    expiry: str | None = None,
    vol: float = 0.30,
    rate: float = 0.045,
    premium: float | None = None,
    debit: float | None = None,
    quantity: float = 1.0,
    multiplier: float = MULTIPLIER,
    legs: Sequence[Mapping[str, Any]] | None = None,
    spot_grid: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Price a long call, long put, or multi-leg book. P/L is the sum of legs."""
    spot_f = float(spot)
    if not math.isfinite(spot_f) or spot_f <= 0:
        raise ValueError("spot must be a positive finite number")
    tenor = _years(years=years, dte=dte, expiry=expiry)
    book = _normalize_legs(
        strategy=strategy,
        strike=strike,
        premium=premium,
        debit=debit,
        quantity=float(quantity),
        legs=legs,
    )
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "theo": 0.0}
    priced_legs: list[dict[str, Any]] = []
    for leg in book:
        qty = float(leg["quantity"])
        leg_vol = float(leg["vol"]) if leg.get("vol") is not None else float(vol)
        model = black_scholes(
            spot=spot_f,
            strike=float(leg["strike"]),
            years=tenor,
            rate=float(rate),
            vol=leg_vol,
            right=leg["right"],
        )
        cash_debit = _leg_debit(leg, multiplier=multiplier)
        if cash_debit == 0.0:
            cash_debit = model["price"] * float(multiplier) * qty
        priced = {
            **leg,
            "debit": cash_debit,
            "theo": model["price"],
            "delta": model["delta"] * qty,
            "gamma": model["gamma"] * qty,
            "theta": model["theta"] * qty * float(multiplier),
            "vega": model["vega"] * qty * float(multiplier),
        }
        priced_legs.append(priced)
        greeks["delta"] += priced["delta"]
        greeks["gamma"] += priced["gamma"]
        greeks["theta"] += priced["theta"]
        greeks["vega"] += priced["vega"]
        greeks["theo"] += model["price"] * qty

    if spot_grid is None:
        lo = max(0.01, spot_f * 0.70)
        hi = spot_f * 1.30
        spots = [round(lo + (hi - lo) * i / 40.0, 4) for i in range(41)]
        if all(abs(value - spot_f) > 1e-9 for value in spots):
            spots.append(round(spot_f, 4))
            spots.sort()
    else:
        spots = [float(value) for value in spot_grid]

    pnl_at_expiry: list[dict[str, float]] = []
    for test_spot in spots:
        total = 0.0
        for leg in priced_legs:
            total += expiry_pnl(
                spot=test_spot,
                strike=float(leg["strike"]),
                right=str(leg["right"]),
                debit=float(leg["debit"]),
                multiplier=float(multiplier),
                quantity=float(leg["quantity"]),
            )
        pnl_at_expiry.append({"spot": test_spot, "pnl": round(total, 6)})

    return {
        "strategy": str(strategy or "custom"),
        "spot": spot_f,
        "years": tenor,
        "vol": float(vol),
        "rate": float(rate),
        "multiplier": float(multiplier),
        "legs": priced_legs,
        "greeks": {key: round(value, 8) for key, value in greeks.items()},
        "pnl_at_expiry": pnl_at_expiry,
        "decision_authorized": False,
    }


def summarize_setup_play(
    *,
    right: str,
    spot: float,
    strike: float,
    premium: float,
    dte: float | None = None,
    expiry: str | None = None,
    vol: float | None = None,
    sell: float | None = None,
    invalidation: float | None = None,
    multiplier: float = MULTIPLIER,
) -> dict[str, Any]:
    """Attach a closed-form play card to a setup. Never authorizes entry.

    Expiry P/L and breakeven need only spot, strike, right, and debit.
    Greeks require a measured vol; otherwise they stay unavailable.
    """
    right_n = _right(right)
    spot_f = float(spot)
    strike_f = float(strike)
    premium_f = float(premium)
    if spot_f <= 0 or strike_f <= 0 or premium_f < 0:
        raise ValueError("spot, strike, and premium must be usable numbers")
    mult = float(multiplier or MULTIPLIER)
    debit = premium_f * mult
    strategy = "long_call" if right_n == "call" else "long_put"
    breakeven = strike_f + premium_f if right_n == "call" else strike_f - premium_f
    vol_used = float(vol) if vol is not None and float(vol) > 0 else None
    greeks: dict[str, float] | None = None
    theo: float | None = None
    if vol_used is not None:
        priced = evaluate_strategy(
            strategy=strategy,
            spot=spot_f,
            strike=strike_f,
            dte=dte,
            expiry=expiry,
            vol=vol_used,
            premium=premium_f,
            multiplier=mult,
        )
        greeks = dict(priced["greeks"])
        theo = float(greeks["theo"])

    def _level_pnl(level: float | None) -> float | None:
        if level is None:
            return None
        return round(expiry_pnl(
            spot=float(level),
            strike=strike_f,
            right=right_n,
            debit=debit,
            multiplier=mult,
        ), 2)

    return {
        "strategy": strategy,
        "right": right_n,
        "spot": round(spot_f, 6),
        "strike": round(strike_f, 6),
        "premium": round(premium_f, 6),
        "debit": round(debit, 4),
        "multiplier": mult,
        "dte": None if dte is None else float(dte),
        "expiry": expiry,
        "breakeven": round(breakeven, 6),
        "max_loss": round(debit, 4),
        "vol": vol_used,
        "vol_source": "contract_iv" if vol_used is not None else "unmeasured",
        "greeks": greeks,
        "theo": None if theo is None else round(theo, 6),
        "pnl_at_spot": _level_pnl(spot_f),
        "pnl_at_sell": _level_pnl(sell),
        "pnl_at_invalidation": _level_pnl(invalidation),
        "sell": None if sell is None else float(sell),
        "invalidation": None if invalidation is None else float(invalidation),
        "method": "black_scholes_plus_expiry_pnl" if vol_used is not None else "expiry_intrinsic_only",
        "decision_authorized": False,
    }
