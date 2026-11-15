"""Pre-trade gamma reads: call resistance, absolute gamma, zero gamma, nearby support.

Charting sign matches the rest of the desk (call dollar-gamma positive, put
dollar-gamma negative). That is the display convention, not a claim about
true dealer inventory.

Dollar gamma for a 1% spot move on one contract:

    OI · multiplier · Γ · S² · 0.01

Γ is Black–Scholes with the dividend yield when the chain carries one
(``options_intelligence._bs_gamma``). A vendor gamma is used only when IV
cannot reprice the contract, and those contracts are left out of the
zero-gamma search: gamma at a hypothetical spot is not the gamma the vendor
quoted at the current spot.

Missing open interest, missing gamma, or a book that never crosses zero
comes back as ``None`` with a reason. A zero in those fields would read as
a flat book.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Sequence

from .options_intelligence import (
    _best_observation_time,
    _bs_gamma,
    _expiry,
    _first,
    _latest_chain,
    _number,
    _timestamp,
)

# A same-day contract has no positive year-fraction. Flooring at half a day
# keeps Γ finite; the quality block records how often that floor was used.
TENOR_FLOOR_DAYS = 0.5
TENOR_FLOOR_YEARS = TENOR_FLOOR_DAYS / 365.0

# Nearby support is the closest material put shelf inside this band.
# A heavier wall further away stays on ``put_wall`` and is not relabeled support.
NEARBY_BAND_PCT = 0.08
MATERIAL_SHARE_OF_PEAK = 0.20
# Puts that are a rounding share of the whole book are not a shelf.
PUT_BOOK_SHARE_MIN = 0.02

# Zero gamma is withheld when less than half the absolute dollar-gamma can
# be repriced from IV. A root fit on the remainder would be a different book.
REVALUE_COVERAGE_MIN = 0.50
# A call node this small, relative to every call above spot, is not a wall.
CONCENTRATED_SHARE_MIN = 0.15

# Net gamma inside 1% of absolute gamma is a balanced book, not a sign.
REGIME_DEADBAND = 0.01
# Crossings smaller than 1% of the peak grid value are numerical dust.
CROSSING_FLOOR_SHARE = 0.01
ZERO_SEARCH_SPAN = 0.25
STALE_AFTER = timedelta(hours=20)

DEFAULT_RATE = 0.045
DEFAULT_MAX_DTE = 365
DEFAULT_MIN_DTE = 0


def parse_dte_param(
    raw: str | None,
    *,
    default: int,
    lo: int,
    hi: int,
) -> tuple[int | None, str | None]:
    """Parse a DTE query value. Blank uses ``default``. Out of range is an error."""
    if raw is None or str(raw).strip() == "":
        return default, None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None, "must be an integer"
    if value < lo or value > hi:
        return None, f"must be between {lo} and {hi}"
    return value, None


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _usable_iv(raw: Any) -> tuple[float | None, bool]:
    """Return (iv, rescaled). Percents above 5.0 are scaled once (20 → 0.20)."""
    iv = _number(raw)
    if iv is None:
        return None, False
    rescaled = False
    if iv > 5.0:
        scaled = iv / 100.0
        if 0.005 <= scaled <= 5.0:
            return scaled, True
        return None, False
    if 0.005 <= iv <= 5.0:
        return iv, rescaled
    return None, False


def _usable_yield(raw: Any) -> float:
    value = _number(raw)
    if value is None or not 0.0 <= value <= 1.0:
        return 0.0
    return value


def _provider_gamma(raw: Any) -> float | None:
    """Vendor gamma. Non-positive or implausibly large values are blanks, not zeros."""
    gamma = _number(raw)
    if gamma is None or gamma <= 0.0 or gamma > 5.0:
        return None
    return gamma


def _row_dte(row: Mapping[str, Any], asof: datetime | None) -> int | None:
    expiry = _expiry(_first(row, "expiry", "expiration", "expiration_date"))
    if expiry is not None and asof is not None:
        return (expiry - asof.date()).days
    number = _number(_first(row, "dte", "days_to_expiration"))
    if number is None:
        return None
    return int(number)


def _dollar_gamma(oi: float, gamma: float, spot: float, multiplier: float) -> float:
    return oi * multiplier * gamma * spot * spot * 0.01


class _Leg:
    __slots__ = (
        "strike",
        "right",
        "oi",
        "gamma",
        "iv",
        "years",
        "yield_rate",
        "multiplier",
        "revaluable",
        "dollar",
    )

    def __init__(
        self,
        *,
        strike: float,
        right: str,
        oi: float,
        gamma: float,
        iv: float | None,
        years: float | None,
        yield_rate: float,
        multiplier: float,
        revaluable: bool,
    ) -> None:
        self.strike = strike
        self.right = right
        self.oi = oi
        self.gamma = gamma
        self.iv = iv
        self.years = years
        self.yield_rate = yield_rate
        self.multiplier = multiplier
        self.revaluable = revaluable
        self.dollar = 0.0


def _net_revalued(legs: Sequence[_Leg], test_spot: float, rate: float) -> float | None:
    """Signed dollar-gamma at ``test_spot``, using only contracts with an IV."""
    if test_spot <= 0:
        return None
    total = 0.0
    any_leg = False
    for leg in legs:
        if not leg.revaluable or leg.iv is None or leg.years is None:
            continue
        gamma = _bs_gamma(
            spot=test_spot,
            strike=leg.strike,
            years=leg.years,
            iv=leg.iv,
            rate=rate,
            yield_rate=leg.yield_rate,
        )
        if gamma is None or gamma <= 0:
            continue
        sign = 1.0 if leg.right == "call" else -1.0
        total += sign * _dollar_gamma(leg.oi, gamma, test_spot, leg.multiplier)
        any_leg = True
    return total if any_leg else None


def _zero_gamma(
    legs: Sequence[_Leg],
    spot: float,
    rate: float,
) -> tuple[float | None, str | None]:
    lo = spot * (1.0 - ZERO_SEARCH_SPAN)
    hi = spot * (1.0 + ZERO_SEARCH_SPAN)
    steps = 200
    grid: list[tuple[float, float]] = []
    for i in range(steps + 1):
        test = lo + (hi - lo) * i / steps
        net = _net_revalued(legs, test, rate)
        if net is None:
            return None, "not_revaluable"
        grid.append((test, net))
    peak = max(abs(y) for _, y in grid)
    if peak <= 0:
        return None, "no_sign_change"
    floor = peak * CROSSING_FLOOR_SHARE
    brackets: list[tuple[float, float, float, float]] = []
    for (x0, y0), (x1, y1) in zip(grid, grid[1:]):
        if max(abs(y0), abs(y1)) < floor:
            continue
        if y0 == 0.0 or y1 == 0.0 or (y0 < 0.0 < y1) or (y1 < 0.0 < y0):
            brackets.append((x0, y0, x1, y1))
    if not brackets:
        return None, "no_sign_change"

    def _interp(x0: float, y0: float, x1: float, y1: float) -> float:
        if y0 == 0.0:
            return x0
        if y1 == 0.0:
            return x1
        denom = abs(y0) + abs(y1)
        if denom <= 0:
            return (x0 + x1) / 2.0
        return x0 + (x1 - x0) * abs(y0) / denom

    x0, y0, x1, y1 = min(brackets, key=lambda b: abs(_interp(*b) - spot))
    root = _bisect_root(legs, rate, x0, y0, x1, y1, spot)
    return root, None


def _bisect_root(
    legs: Sequence[_Leg],
    rate: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    spot: float,
) -> float:
    if y0 == 0.0:
        return x0
    if y1 == 0.0:
        return x1
    lo, hi = x0, x1
    y_lo, y_hi = y0, y1
    tolerance = max(spot * 1e-6, 1e-4)
    for _ in range(48):
        if abs(hi - lo) <= tolerance:
            break
        mid = (lo + hi) / 2.0
        y_mid = _net_revalued(legs, mid, rate)
        if y_mid is None:
            break
        if y_mid == 0.0:
            return mid
        # Same sign as the left end: the root is still to the right.
        if (y_lo < 0.0) == (y_mid < 0.0):
            lo, y_lo = mid, y_mid
        else:
            hi, y_hi = mid, y_mid
    denom = abs(y_lo) + abs(y_hi)
    if denom <= 0:
        return (lo + hi) / 2.0
    return lo + (hi - lo) * abs(y_lo) / denom


def _level(
    strike: float,
    spot: float,
    dollar: float,
    *,
    signed: float,
) -> dict[str, Any]:
    distance = strike - spot
    return {
        "level": _round(strike, 4),
        "distance": _round(distance, 4),
        "distance_pct": _round(distance / spot, 6) if spot > 0 else None,
        "dollar_gamma_m": _round(signed / 1_000_000.0, 6),
        "abs_dollar_gamma_m": _round(dollar / 1_000_000.0, 6),
    }


def _bump(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def gamma_resistance_from_chain(
    rows: Sequence[Mapping[str, Any]],
    *,
    spot: float | None = None,
    asof: datetime | None = None,
    now: datetime | None = None,
    max_dte: int = DEFAULT_MAX_DTE,
    min_dte: int = DEFAULT_MIN_DTE,
    rate: float = DEFAULT_RATE,
) -> dict[str, Any]:
    """Build the four reads from one chain snapshot.

    ``spot`` overrides the chain. When it is omitted the spot is the median
    of positive per-row underlying prices. No trustworthy spot, or a book
    with no measurable contract, returns the reads as null.
    """
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    observed = asof
    if observed is None:
        observed = _best_observation_time(
            [
                _timestamp(
                    _first(
                        row,
                        "quote_asof_utc",
                        "captured_utc",
                        "asof_utc",
                        "timestamp",
                        "updated_at",
                        "asof_date",
                    )
                )
                for row in rows
            ]
        )
    if observed is not None and observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)

    if spot is None:
        spots = [
            value
            for row in rows
            if (value := _number(_first(row, "spot", "underlying_price"))) is not None and value > 0
        ]
        spot = float(median(spots)) if spots else None

    stale, stale_reason = _staleness(observed, clock)
    base = _envelope(
        spot=spot,
        asof=observed,
        stale=stale,
        stale_reason=stale_reason,
        max_dte=max_dte,
        min_dte=min_dte,
        rate=rate,
    )
    if spot is None or spot <= 0:
        base["measurable"] = False
        base["reason"] = "spot_missing"
        return base
    if min_dte > max_dte:
        base["measurable"] = False
        base["reason"] = "invalid_dte_window"
        return base

    skips: dict[str, int] = {}
    legs: list[_Leg] = []
    bs_rows = 0
    provider_rows = 0
    iv_rescaled = 0
    tenor_floored = 0
    for row in rows:
        leg, skip, flags = _parse_leg(
            row,
            spot=spot,
            asof=observed,
            min_dte=min_dte,
            max_dte=max_dte,
            rate=rate,
        )
        if skip:
            _bump(skips, skip)
            continue
        assert leg is not None
        if flags.get("iv_rescaled"):
            iv_rescaled += 1
        if flags.get("tenor_floored"):
            tenor_floored += 1
        if leg.revaluable:
            bs_rows += 1
        else:
            provider_rows += 1
        legs.append(leg)

    if not legs:
        base["measurable"] = False
        base["reason"] = _empty_reason(skips)
        base["quality"] = _quality(
            rows=len(rows),
            measured=0,
            skips=skips,
            bs_rows=0,
            provider_rows=0,
            iv_rescaled=iv_rescaled,
            tenor_floored=tenor_floored,
            coverage=None,
        )
        return base

    by_strike = _aggregate(legs)
    total_abs = sum(cell["abs"] for cell in by_strike.values())
    total_call = sum(cell["call"] for cell in by_strike.values())
    total_put = sum(cell["put"] for cell in by_strike.values())
    net = total_call - total_put
    revalue_abs = sum(leg.dollar for leg in legs if leg.revaluable)
    coverage = (revalue_abs / total_abs) if total_abs > 0 else None

    peak_cell = max(
        by_strike.values(),
        key=lambda cell: (cell["abs"], -abs(cell["strike"] - spot)),
    )
    call_resistance, call_reason = _call_resistance(by_strike, spot)
    support, support_reason, put_wall = _nearby_support(by_strike, spot, total_abs)
    if coverage is None or coverage < REVALUE_COVERAGE_MIN:
        zero, zero_reason = None, "iv_coverage_insufficient"
    else:
        zero, zero_reason = _zero_gamma(legs, spot, rate)

    regime = _regime(net, total_abs)
    side = _flip_side(spot, zero)
    base.update(
        {
            "measurable": True,
            "reason": None,
            "absolute_gamma_m": _round(total_abs / 1_000_000.0, 6),
            "absolute_gamma_strike": _round(peak_cell["strike"], 4),
            "absolute_gamma_strike_m": _round(peak_cell["abs"] / 1_000_000.0, 6),
            "net_gamma_m": _round(net / 1_000_000.0, 6),
            "call_gamma_m": _round(total_call / 1_000_000.0, 6),
            "put_gamma_m": _round(-total_put / 1_000_000.0, 6),
            "regime": regime,
            "call_resistance": call_resistance,
            "call_resistance_reason": call_reason,
            "zero_gamma": _round(zero, 4),
            "zero_gamma_distance": _round(zero - spot, 4) if zero is not None else None,
            "zero_gamma_distance_pct": (
                _round((zero - spot) / spot, 6) if zero is not None else None
            ),
            "zero_gamma_side": side,
            "zero_gamma_reason": zero_reason,
            "nearby_support": support,
            "nearby_support_reason": support_reason,
            "put_wall": put_wall,
            "by_strike": _strike_rows(by_strike),
            "quality": _quality(
                rows=len(rows),
                measured=len(legs),
                skips=skips,
                bs_rows=bs_rows,
                provider_rows=provider_rows,
                iv_rescaled=iv_rescaled,
                tenor_floored=tenor_floored,
                coverage=coverage,
            ),
        }
    )
    return base


def _parse_leg(
    row: Mapping[str, Any],
    *,
    spot: float,
    asof: datetime | None,
    min_dte: int,
    max_dte: int,
    rate: float,
) -> tuple[_Leg | None, str | None, dict[str, bool]]:
    flags = {"iv_rescaled": False, "tenor_floored": False}
    right = str(_first(row, "right", "contract_type", "option_type", "type") or "").strip().lower()
    if right in {"c", "call", "calls"}:
        right = "call"
    elif right in {"p", "put", "puts"}:
        right = "put"
    else:
        return None, "invalid_right", flags
    strike = _number(_first(row, "strike", "strike_price"))
    if strike is None or strike <= 0:
        return None, "invalid_strike", flags
    raw_oi = _first(row, "open_interest", "openInterest", "oi")
    if raw_oi is None or (isinstance(raw_oi, str) and not raw_oi.strip()):
        return None, "open_interest_missing", flags
    oi = _number(raw_oi)
    if oi is None or oi < 0:
        return None, "open_interest_invalid", flags
    if oi == 0:
        return None, "open_interest_zero", flags
    dte = _row_dte(row, asof)
    if dte is None:
        years: float | None = None
    elif dte < 0:
        return None, "expired", flags
    elif dte < min_dte or dte > max_dte:
        return None, "outside_dte", flags
    elif dte == 0:
        years = TENOR_FLOOR_YEARS
        flags["tenor_floored"] = True
    else:
        years = dte / 365.0
    iv, rescaled = _usable_iv(_first(row, "iv", "implied_vol", "impliedVolatility"))
    flags["iv_rescaled"] = rescaled
    yield_rate = _usable_yield(_first(row, "dividend_yield", "yield_rate", "q"))
    multiplier = _number(_first(row, "multiplier", "contract_multiplier"))
    if multiplier is None:
        multiplier = 100.0
    if multiplier <= 0:
        return None, "invalid_multiplier", flags
    gamma: float | None = None
    revaluable = False
    if iv is not None and years is not None and years > 0:
        gamma = _bs_gamma(
            spot=spot,
            strike=strike,
            years=years,
            iv=iv,
            rate=rate,
            yield_rate=yield_rate,
        )
        if gamma is not None and gamma > 0:
            revaluable = True
        else:
            gamma = None
    if gamma is None:
        gamma = _provider_gamma(_first(row, "gamma"))
        iv = None
        revaluable = False
    if gamma is None:
        return None, "gamma_unavailable", flags
    leg = _Leg(
        strike=strike,
        right=right,
        oi=oi,
        gamma=gamma,
        iv=iv,
        years=years,
        yield_rate=yield_rate,
        multiplier=multiplier,
        revaluable=revaluable,
    )
    leg.dollar = _dollar_gamma(oi, gamma, spot, multiplier)
    return leg, None, flags


def _aggregate(legs: Sequence[_Leg]) -> dict[float, dict[str, float]]:
    cells: dict[float, dict[str, float]] = {}
    for leg in legs:
        cell = cells.setdefault(
            leg.strike,
            {
                "strike": leg.strike,
                "call": 0.0,
                "put": 0.0,
                "abs": 0.0,
                "call_oi": 0.0,
                "put_oi": 0.0,
            },
        )
        cell[leg.right] += leg.dollar
        cell["abs"] += leg.dollar
        cell[f"{leg.right}_oi"] += leg.oi
    return cells


def _call_resistance(
    by_strike: Mapping[float, Mapping[str, float]],
    spot: float,
) -> tuple[dict[str, Any] | None, str | None]:
    above = [cell for cell in by_strike.values() if cell["strike"] > spot and cell["call"] > 0]
    if not above:
        return None, "no_calls_above_spot"
    best = max(above, key=lambda cell: (cell["call"], -abs(cell["strike"] - spot)))
    total = sum(cell["call"] for cell in above)
    share = best["call"] / total if total > 0 else None
    level = _level(best["strike"], spot, best["call"], signed=best["call"])
    level["share"] = _round(share, 6)
    level["concentrated"] = bool(share is not None and share >= CONCENTRATED_SHARE_MIN)
    return level, None


def _nearby_support(
    by_strike: Mapping[float, Mapping[str, float]],
    spot: float,
    total_abs: float,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    below = [cell for cell in by_strike.values() if cell["strike"] < spot and cell["put"] > 0]
    if not below:
        return None, "no_puts_below_spot", None
    wall_cell = max(below, key=lambda cell: (cell["put"], -abs(cell["strike"] - spot)))
    put_wall = _level(wall_cell["strike"], spot, wall_cell["put"], signed=-wall_cell["put"])
    put_total = sum(cell["put"] for cell in below)
    if total_abs <= 0 or put_total / total_abs < PUT_BOOK_SHARE_MIN:
        return None, "put_gamma_immaterial", put_wall
    peak = max(cell["put"] for cell in below)
    material = [
        cell
        for cell in below
        if cell["put"] >= MATERIAL_SHARE_OF_PEAK * peak
        and (spot - cell["strike"]) / spot <= NEARBY_BAND_PCT
    ]
    if not material:
        return None, "no_put_gamma_inside_band", put_wall
    nearest = min(material, key=lambda cell: (spot - cell["strike"], -cell["put"]))
    level = _level(nearest["strike"], spot, nearest["put"], signed=-nearest["put"])
    level["share_of_peak"] = _round(nearest["put"] / peak, 6) if peak > 0 else None
    return level, None, put_wall


def _regime(net: float, total_abs: float) -> str:
    if total_abs <= 0:
        return "unmeasured"
    if abs(net) / total_abs < REGIME_DEADBAND:
        return "neutral"
    return "positive" if net > 0 else "negative"


def _flip_side(spot: float, zero: float | None) -> str | None:
    if zero is None or spot <= 0:
        return None
    if abs(spot - zero) / spot <= 0.001:
        return "at"
    return "above" if spot > zero else "below"


def _empty_reason(skips: Mapping[str, int]) -> str:
    if skips.get("open_interest_missing") and sum(skips.values()) == skips["open_interest_missing"]:
        return "open_interest_unavailable"
    if skips.get("outside_dte") and sum(skips.values()) == skips["outside_dte"]:
        return "outside_dte"
    if skips.get("gamma_unavailable"):
        return "gamma_unavailable"
    return "unmeasured"


def _staleness(asof: datetime | None, now: datetime) -> tuple[bool, str | None]:
    if asof is None:
        return True, "asof_missing"
    age = now - asof
    if age > STALE_AFTER:
        return True, "chain_older_than_20h"
    return False, None


def _quality(
    *,
    rows: int,
    measured: int,
    skips: Mapping[str, int],
    bs_rows: int,
    provider_rows: int,
    iv_rescaled: int,
    tenor_floored: int,
    coverage: float | None,
) -> dict[str, Any]:
    return {
        "contracts_in": rows,
        "contracts_measured": measured,
        "contracts_skipped": rows - measured,
        "skip_reasons": dict(sorted(skips.items())),
        "gamma_black_scholes": bs_rows,
        "gamma_provider": provider_rows,
        "iv_rescaled": iv_rescaled,
        "tenor_floored": tenor_floored,
        "revalue_coverage": _round(coverage, 6),
        "tenor_floor_days": TENOR_FLOOR_DAYS,
        "nearby_band_pct": NEARBY_BAND_PCT,
        "revalue_coverage_min": REVALUE_COVERAGE_MIN,
    }


def _strike_rows(by_strike: Mapping[float, Mapping[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for strike in sorted(by_strike):
        cell = by_strike[strike]
        call = cell["call"]
        put = cell["put"]
        rows.append(
            {
                "strike": _round(strike, 4),
                "call_gex_m": _round(call / 1_000_000.0, 6),
                "put_gex_m": _round(-put / 1_000_000.0, 6),
                "net_gex_m": _round((call - put) / 1_000_000.0, 6),
                "abs_gex_m": _round(cell["abs"] / 1_000_000.0, 6),
                "call_oi": int(cell["call_oi"]),
                "put_oi": int(cell["put_oi"]),
            }
        )
    return rows


def _envelope(
    *,
    spot: float | None,
    asof: datetime | None,
    stale: bool,
    stale_reason: str | None,
    max_dte: int,
    min_dte: int,
    rate: float,
) -> dict[str, Any]:
    return {
        "asof": asof.isoformat() if asof is not None else None,
        "stale": stale,
        "stale_reason": stale_reason,
        "spot": _round(spot, 4) if spot is not None and spot > 0 else None,
        "max_dte": max_dte,
        "min_dte": min_dte,
        "rate": rate,
        "measurable": False,
        "reason": None,
        "absolute_gamma_m": None,
        "absolute_gamma_strike": None,
        "absolute_gamma_strike_m": None,
        "net_gamma_m": None,
        "call_gamma_m": None,
        "put_gamma_m": None,
        "regime": "unmeasured",
        "call_resistance": None,
        "call_resistance_reason": None,
        "zero_gamma": None,
        "zero_gamma_distance": None,
        "zero_gamma_distance_pct": None,
        "zero_gamma_side": None,
        "zero_gamma_reason": None,
        "nearby_support": None,
        "nearby_support_reason": None,
        "put_wall": None,
        "by_strike": [],
        "quality": None,
        "unit": "usd_millions_per_1pct",
        "sign_convention": "call_positive_put_negative",
    }


def _load_cached_chain(symbol: str) -> tuple[list[dict[str, Any]], str | None]:
    """Latest cached chain, same snapshot path ``/api/vanna`` uses."""
    try:
        from edge.tools.api_server import _historical_option_rows
    except ImportError:  # pragma: no cover - repo-root invocation
        from tools.api_server import _historical_option_rows

    rows, selected, _available = _historical_option_rows(symbol, all_days=False)
    return rows, selected


def compute_gamma_resistance(
    symbol: str,
    *,
    max_dte: int = DEFAULT_MAX_DTE,
    min_dte: int = DEFAULT_MIN_DTE,
    rate: float = DEFAULT_RATE,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """JSON payload for ``GET /api/gamma/resistance``.

    ``None`` means there is no chain snapshot. A chain that cannot be greeked
    still returns a payload with ``measurable`` false so the screen can show
    an empty state instead of a fabricated flat book.
    """
    rows, _selected = _load_cached_chain(symbol.upper())
    if not rows:
        return None
    latest, observed = _latest_chain(rows)
    if not latest:
        return None
    payload = gamma_resistance_from_chain(
        latest,
        asof=observed,
        now=now,
        max_dte=max_dte,
        min_dte=min_dte,
        rate=rate,
    )
    payload["symbol"] = symbol.upper()
    return payload
