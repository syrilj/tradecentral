"""Conservative fill-price accounting for options plays.

``edge/research/costs.py`` accounts for underlying directional exposure only,
and its module docstring says plainly that it "does not consume option
chains and must never be used to infer option P&L." This module is the
missing counterpart. The repo ships options plays
(``daily_plays/options_intelligence.py``) but has no fill model, so option
decisions are implicitly scored at mid. Mid is not a fill: it is the average
of two prices nobody offered you. On a wide options spread the gap between
mid and an achievable fill is frequently larger than the entire edge a play
claims, so leaving it implicit is a way of manufacturing an edge that is not
there.

The model here is "patient-then-cross": a retail/small account rests a
passive limit somewhere inside the spread, waits a bounded number of bars,
and -- if unfilled -- crosses to the touch to guarantee a fill. Every
accounting function in this module charges the crossed price (the far
touch), never the passive price, because assuming the passive fill is
exactly the optimism this module exists to remove. See
``OptionsFillModel.patience_fraction`` for why the passive price is still
exposed as configuration even though the conservative functions never use it
to produce a return.

Mirrors ``research/costs.py`` in structure: frozen dataclasses, hard
validation, explicit normalize functions, no silent coercion. On degenerate
input this module returns a clearly-flagged no-fill result (or raises for a
caller-programming error like an invalid side string) rather than
substituting mid, or any other invented price, for a fill that did not
happen. That silent-fallback failure mode -- a number that looks like data
but was manufactured by a default -- is exactly what
``research/features.py::assert_no_degenerate_feature_columns`` and
``edge/docs/LOOKAHEAD_CORRECTION.md`` document elsewhere in this repo: a
feature silently collapsing to a constant while the report that used it kept
looking normal. No I/O, no paths, no network. Pure functions only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OptionsFillModel:
    """Parameters of a "patient-then-cross" retail limit-order policy.

    A retail account does not get filled at mid. It rests a passive limit
    somewhere inside the spread (``patience_fraction``: 0.0 sits at mid, 1.0
    sits at the far touch, i.e. immediately crossing) and waits
    ``cross_after_bars`` bars before giving up on the passive price and
    crossing to guarantee a fill. Both are kept as explicit configuration so
    a caller can reason about or sensitivity-test the passive leg, but the
    conservative accounting functions in this module (``entry_fill_price``
    and everything built on it) never use the passive price to produce a
    return -- they charge the crossed price on every fill. That is the
    price actually available on demand, and it is the price this policy
    converges to whenever the passive order does not fill in time.

    ``stale_quote_bars`` documents how old a quote may be before it is not a
    valid fill basis. This module has no bar clock and performs no I/O, so
    it cannot check a quote's age itself; the caller is responsible for
    comparing a quote's observed age (in bars) to this threshold *before*
    calling into this module. Passing a stale quote to ``entry_fill_price``
    silently prices it as if it were fresh -- staleness is a freshness
    concern the caller owns, not a spread-width concern this module can
    infer from bid/ask alone.
    """

    patience_fraction: float = 0.5
    cross_after_bars: int = 1
    max_spread_pct: float = 0.25
    fee_per_contract: float = 0.65
    stale_quote_bars: int = 2

    def __post_init__(self) -> None:
        if not math.isfinite(self.patience_fraction) or not 0.0 <= self.patience_fraction <= 1.0:
            raise ValueError(
                f"patience_fraction must be a finite value in [0, 1]; got {self.patience_fraction!r}"
            )
        if isinstance(self.cross_after_bars, bool) or not isinstance(self.cross_after_bars, int) \
                or self.cross_after_bars < 0:
            raise ValueError(
                f"cross_after_bars must be a non-negative integer; got {self.cross_after_bars!r}"
            )
        if not math.isfinite(self.max_spread_pct) or self.max_spread_pct <= 0:
            raise ValueError(
                f"max_spread_pct must be a finite positive number; got {self.max_spread_pct!r}"
            )
        if not math.isfinite(self.fee_per_contract) or self.fee_per_contract < 0:
            raise ValueError(
                f"fee_per_contract must be a finite non-negative number; got {self.fee_per_contract!r}"
            )
        if isinstance(self.stale_quote_bars, bool) or not isinstance(self.stale_quote_bars, int) \
                or self.stale_quote_bars < 0:
            raise ValueError(
                f"stale_quote_bars must be a non-negative integer; got {self.stale_quote_bars!r}"
            )


@dataclass(frozen=True)
class FillResult:
    """Outcome of pricing one conservative fill; a no-fill is never a price.

    ``filled=False`` always pairs with ``price=None`` -- there is no code
    path in this module that returns ``filled=False`` alongside a numeric
    ``price``, and no code path that returns ``filled=True`` with
    ``price=None``. ``reason`` is populated exactly when ``filled=False`` and
    names what specifically was wrong (too wide, inverted, non-finite,
    non-positive), so a caller aggregating many rejected fills can see why
    without re-deriving it from the raw quote.
    """

    filled: bool
    price: float | None
    reference_mid: float | None
    slippage_vs_mid: float | None
    spread_pct: float | None
    reason: str | None
    fee: float


_SIDE_MAP = {
    "buy": "buy", "debit": "buy", "long": "buy", "b": "buy",
    "sell": "sell", "credit": "sell", "short": "sell", "s": "sell",
}


def normalize_side(value: Any) -> str:
    """Map an explicit entry side to {"buy", "sell"}; reject ambiguity.

    Mirrors ``edge/research/costs.py::normalize_position``: a small explicit
    vocabulary, hard failure on anything not in it. There is no
    guess-from-context path. Buying an option is a debit (you pay up to the
    touch); selling is a credit (you receive down to the touch). A wrong
    side silently flips which touch is charged, so this raises rather than
    defaulting -- an option fill model that can be silently pointed the
    wrong way is worse than no fill model at all.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"side is missing or invalid: {value!r}")
    if not isinstance(value, str):
        raise ValueError(f"side must be a string, got {type(value).__name__}: {value!r}")
    normalized = value.strip().lower()
    if normalized not in _SIDE_MAP:
        raise ValueError(
            f"side must be one of {sorted(set(_SIDE_MAP))}, got {value!r}"
        )
    return _SIDE_MAP[normalized]


def _as_finite_float(value: Any) -> float | None:
    """Best-effort numeric coercion that never raises; None means unusable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def entry_fill_price(
    *, bid: Any, ask: Any, side: Any, model: OptionsFillModel = OptionsFillModel(),
) -> FillResult:
    """Price a single-leg fill under the conservative crossed-price rule.

    Buying: the passive limit a patient order might rest at is
    ``mid + patience_fraction * (ask - mid)``; this function does not use
    that price. It charges ``ask`` -- the price actually available on
    demand -- because assuming the passive fill is exactly the optimism this
    module exists to remove from a backtest. Selling is symmetric: the
    passive limit would sit inside the spread from the bid side, and this
    function charges ``bid``.

    Refuses to manufacture a fill -- returns ``filled=False``, ``price=None``
    -- when the quote cannot support one: ``bid <= 0``, ``ask <= bid``,
    either input is non-finite/non-numeric, or
    ``spread_pct > model.max_spread_pct``. It never substitutes mid, or any
    other value, for a fill that could not happen; a wide-spread contract is
    not tradeable at a "close enough" price, it is simply not tradeable at
    this model's standard of conservatism.

    ``side`` is validated first and raises ``ValueError`` on anything
    outside ``normalize_side``'s explicit vocabulary -- a malformed side is
    a caller bug, not a market condition, and deserves a hard failure rather
    than a silently-empty result mixed in with genuine no-fills.
    """
    side_n = normalize_side(side)
    fee = float(model.fee_per_contract)

    bid_f = _as_finite_float(bid)
    ask_f = _as_finite_float(ask)
    if bid_f is None or ask_f is None:
        return FillResult(False, None, None, None, None,
                          f"bid/ask must be finite numbers; got bid={bid!r}, ask={ask!r}", fee)
    if bid_f <= 0:
        return FillResult(False, None, None, None, None,
                          f"bid must be positive; got {bid_f!r}", fee)
    if ask_f <= bid_f:
        return FillResult(False, None, None, None, None,
                          f"ask ({ask_f!r}) must be strictly greater than bid ({bid_f!r})", fee)

    mid = (bid_f + ask_f) / 2.0
    spread_pct = (ask_f - bid_f) / mid
    if spread_pct > model.max_spread_pct:
        return FillResult(False, None, mid, None, spread_pct,
                          f"spread_pct {spread_pct:.4f} exceeds max_spread_pct {model.max_spread_pct:.4f}", fee)

    if side_n == "buy":
        price = ask_f
        slippage = price - mid  # >= 0: paying up from mid to the ask
    else:
        price = bid_f
        slippage = mid - price  # >= 0: receiving down from mid to the bid

    return FillResult(True, price, mid, slippage, spread_pct, None, fee)


@dataclass(frozen=True)
class OptionRoundTrip:
    """Entry-and-exit accounting; unfilled legs never contribute a price.

    ``gross_return``/``net_return`` are per-contract percentage returns on
    the entry price (contract count cancels out of a percentage return by
    construction; it only scales ``total_fees``, the dollar figure).
    ``mid_to_mid_return`` is the same round trip priced naively at mid on
    both legs -- reported purely so a caller can see exactly how much of
    that naive number was fiction, never used to compute the honest return.
    """

    filled: bool
    gross_return: float | None
    net_return: float | None
    entry_price: float | None
    exit_price: float | None
    total_fees: float | None
    mid_to_mid_return: float | None
    entry_fill: FillResult
    exit_fill: FillResult
    reason: str | None


def round_trip_option_return(
    *, entry_bid: Any, entry_ask: Any, exit_bid: Any, exit_ask: Any, side: Any,
    contracts: int = 1, model: OptionsFillModel = OptionsFillModel(),
) -> OptionRoundTrip:
    """Price both legs of an option trade under the conservative fill model.

    Exiting at mid while entering at the touch is a classic half-honest
    backtest: it charges the pessimistic price to get in but hands back the
    optimistic price to get out, netting an edge that no achievable pair of
    fills would have produced. Both legs here go through
    ``entry_fill_price``, so both are charged their own crossed price.

    ``side`` names the *opening* trade only. Opening ``buy`` (a debit)
    closes with a ``sell`` (you receive the bid on the way out); opening
    ``sell`` (a credit) closes with a ``buy`` (you pay the ask on the way
    out). The closing side is derived, never re-specified by the caller, so
    it is not possible to accidentally price both legs as if the position
    were opened twice in the same direction.

    On an unchanged quote (identical bid/ask both legs) ``net_return`` is
    always strictly negative: the trade pays the entry spread, pays the exit
    spread, and pays ``fee_per_contract`` on both legs, for zero underlying
    movement. That is the entire point of this module -- it makes the
    round-trip cost of a static, unmoved options quote explicit instead of
    invisible.

    If either leg cannot fill (see ``entry_fill_price``), the round trip is
    unfilled: ``filled=False``, every return/price field is ``None``, and
    ``reason`` names which leg failed and why. No price is ever substituted
    for the leg that could not fill.
    """
    if isinstance(contracts, bool) or not isinstance(contracts, int) or contracts <= 0:
        raise ValueError(f"contracts must be a positive integer; got {contracts!r}")

    side_n = normalize_side(side)
    exit_side = "sell" if side_n == "buy" else "buy"

    entry_fill = entry_fill_price(bid=entry_bid, ask=entry_ask, side=side_n, model=model)
    exit_fill = entry_fill_price(bid=exit_bid, ask=exit_ask, side=exit_side, model=model)

    total_fees = model.fee_per_contract * contracts * 2

    if not entry_fill.filled or not exit_fill.filled:
        leg, failing = ("entry", entry_fill) if not entry_fill.filled else ("exit", exit_fill)
        reason = f"{leg} leg unfilled: {failing.reason}"
        return OptionRoundTrip(False, None, None, None, None, None, None,
                               entry_fill, exit_fill, reason)

    if side_n == "buy":
        pnl_per_contract = exit_fill.price - entry_fill.price
        mid_pnl = exit_fill.reference_mid - entry_fill.reference_mid
    else:
        pnl_per_contract = entry_fill.price - exit_fill.price
        mid_pnl = entry_fill.reference_mid - exit_fill.reference_mid

    gross_return = pnl_per_contract / entry_fill.price
    net_return = (pnl_per_contract * contracts - total_fees) / (entry_fill.price * contracts)
    mid_to_mid_return = mid_pnl / entry_fill.reference_mid

    return OptionRoundTrip(True, gross_return, net_return, entry_fill.price, exit_fill.price,
                           total_fees, mid_to_mid_return, entry_fill, exit_fill, None)


def spread_fill(
    *, legs: Sequence[Mapping[str, Any]], side: Any, model: OptionsFillModel = OptionsFillModel(),
) -> FillResult:
    """Price a multi-leg credit/debit spread as the sum of conservative legs.

    Each leg is ``{"bid": ..., "ask": ..., "ratio": +1 | -1}`` (+1 long,
    -1 short). ``side`` names whether this call is opening the structure as
    the ratios describe it (``"buy"``) or closing/unwinding a previously
    opened structure (``"sell"``), exactly as in ``round_trip_option_return``
    -- so a long leg (``ratio=+1``) is bought at the ask while opening
    (``side="buy"``) but sold at the bid while closing (``side="sell"``),
    and a short leg (``ratio=-1``) mirrors it. This lets the same function
    price both the entry and the exit of a spread; the ratio never changes
    between those two calls, only ``side`` does.

    The net price is ``sum(ratio_i * leg_price_i)``: positive is a net
    debit (you pay to enter), negative is a net credit (you receive). Each
    leg's own crossing cost (``entry_fill_price``'s ``slippage_vs_mid``,
    always >= 0) is *summed directly*, not derived from
    ``net_price - net_reference_mid`` -- that derived difference can go
    negative for a closing trade even though every individual leg still
    cost its own half-spread, and this module's invariant is that
    ``slippage_vs_mid`` reported in cost terms is never negative at any
    level, single-leg or composite.

    Rejects the whole spread if ANY leg fails to fill (too wide, inverted,
    non-finite, non-positive) -- returns ``filled=False``, ``price=None``,
    with ``reason`` naming every failing leg. A partially-filled multi-leg
    spread is a different position with a different risk profile than the
    one that was intended, not a discounted version of it, so it is never
    priced as though the filled subset stands in for the whole.
    """
    side_n = normalize_side(side)
    if not isinstance(legs, Sequence) or isinstance(legs, (str, bytes)) or len(legs) == 0:
        raise ValueError("legs must be a non-empty sequence of {bid, ask, ratio} mappings")

    priced_legs: list[tuple[int, FillResult]] = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, Mapping):
            raise ValueError(f"leg {index} must be a mapping with bid/ask/ratio; got {type(leg).__name__}")
        if "ratio" not in leg:
            raise ValueError(f"leg {index} is missing required key 'ratio'")
        ratio = leg["ratio"]
        if isinstance(ratio, bool) or ratio not in (1, -1, 1.0, -1.0):
            raise ValueError(f"leg {index} ratio must be +1 (long) or -1 (short); got {ratio!r}")
        ratio_i = int(ratio)
        is_buy_leg = (ratio_i > 0) == (side_n == "buy")
        leg_side = "buy" if is_buy_leg else "sell"
        fill = entry_fill_price(bid=leg.get("bid"), ask=leg.get("ask"), side=leg_side, model=model)
        priced_legs.append((ratio_i, fill))

    total_fee = model.fee_per_contract * len(legs)
    failures = [f"leg {i} ({fill.reason})" for i, (_, fill) in enumerate(priced_legs) if not fill.filled]
    if failures:
        return FillResult(False, None, None, None, None,
                          "spread rejected, leg(s) unfilled: " + "; ".join(failures), total_fee)

    net_price = sum(ratio_i * fill.price for ratio_i, fill in priced_legs)
    net_mid = sum(ratio_i * fill.reference_mid for ratio_i, fill in priced_legs)
    total_slippage = sum(fill.slippage_vs_mid for _, fill in priced_legs)

    return FillResult(True, net_price, net_mid, total_slippage, None, None, total_fee)
