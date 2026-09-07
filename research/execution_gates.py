"""Execution gates: session phase, expiry policy, contract routing, sizing.

The structural half of the intraday options model (dealer gamma, walls, the
flip) already lives in `microstructure_regime.py`; the auction half (POC, value
area, LVN) lives in `volume_profile.py` and `amt_engine.py`. What neither
covers is the last mile between "a level is in play" and "this many of that
contract" -- the time-of-day gate, the expiry policy, the delta corridor, the
spread the fill has to cross, and the position size. That is this module.

Everything here is a pure function over plain values. Nothing fetches, and
nothing guesses: a gate that cannot be evaluated from the inputs handed in
returns a refusal carrying `reason` rather than a permissive default, because
the failure mode this module exists to prevent is a trade being sized and
routed off a number nobody measured.

See `docs/INTRADAY_OPTIONS_MODEL_SPEC.md` sections 5, 6, 8 and 9 for the
parameters and the reasoning behind them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
import math
from typing import Any, Mapping, Sequence

from edge.research.zero_dte import EXCHANGE_TZ

# ---------------------------------------------------------------------------
# Session phases (spec section 9)
# ---------------------------------------------------------------------------

#: Regular-hours boundaries, US equity cash session, exchange-local.
_OPEN = time(9, 30)
_IB_END = time(9, 45)
_MORNING_END = time(11, 30)
_LUNCH_END = time(13, 30)
_AFTERNOON_END = time(15, 30)
_FLATTEN_BY = time(15, 45)
_CLOSE = time(16, 0)

#: phase -> (may_enter, what is permitted). The strings are the operator-facing
#: reason text; they are the whole point of the gate refusing rather than
#: silently returning False.
_PHASE_RULES: dict[str, tuple[bool, str]] = {
    "pre_market": (False, "before the cash open -- no intraday structure exists yet"),
    "opening_auction": (
        False,
        "09:30-09:45 opening auction: spreads are wide and dealer inventory is "
        "still rebalancing; observe the Initial Balance instead of trading it",
    ),
    "morning_initiative": (True, "09:45-11:30 prime window: deepest liquidity, both setups live"),
    "lunch_consolidation": (
        True,
        "11:30-13:30 lunch: mean reversion only, and only at +/-2 sigma with "
        "absorption -- breakout failure rate rises through this window",
    ),
    "afternoon_acceleration": (
        True,
        "13:30-15:30: expansion setups active; SPY 0DTE is closed off by theta",
    ),
    "liquidation": (
        False,
        "15:30-16:00: no new entries; open options must be flat by 15:45",
    ),
    "post_market": (False, "after the cash close"),
}

#: Phases in which a mean-reversion setup may fire at all.
_REVERSION_PHASES = frozenset({"morning_initiative", "lunch_consolidation"})
#: Phases in which a breakout / expansion setup may fire at all.
_EXPANSION_PHASES = frozenset({"morning_initiative", "afternoon_acceleration"})


@dataclass(frozen=True)
class SessionGate:
    """Whether the clock permits an entry, and what it permits."""

    phase: str
    may_enter: bool
    reason: str
    #: True once every open option position must already be closed (>= 15:45).
    must_be_flat: bool
    #: Setup families the clock allows right now, e.g. {"mean_reversion"}.
    permitted_setups: frozenset[str]
    exchange_time: str


def classify_session_phase(moment: datetime) -> str:
    """Name the session phase for `moment`, converted to exchange time.

    A naive datetime is rejected rather than assumed to be exchange-local: the
    whole gate turns on time of day, and silently reading a UTC timestamp as
    New York time shifts every boundary by four or five hours and produces a
    confident, wrong answer.
    """
    if moment.tzinfo is None:
        raise ValueError(
            "classify_session_phase needs an aware datetime; a naive one would "
            "be read as exchange-local and shift every session boundary"
        )
    local = moment.astimezone(EXCHANGE_TZ)
    if local.weekday() >= 5:
        return "post_market"
    t = local.time()
    if t < _OPEN:
        return "pre_market"
    if t < _IB_END:
        return "opening_auction"
    if t < _MORNING_END:
        return "morning_initiative"
    if t < _LUNCH_END:
        return "lunch_consolidation"
    if t < _AFTERNOON_END:
        return "afternoon_acceleration"
    if t < _CLOSE:
        return "liquidation"
    return "post_market"


def session_gate(moment: datetime) -> SessionGate:
    """Full clock verdict for `moment` (spec section 9)."""
    phase = classify_session_phase(moment)
    may_enter, reason = _PHASE_RULES[phase]
    local = moment.astimezone(EXCHANGE_TZ)

    permitted: set[str] = set()
    if phase in _REVERSION_PHASES:
        permitted.add("mean_reversion")
    if phase in _EXPANSION_PHASES:
        permitted.add("expansion")
        permitted.add("reflexive_squeeze")

    must_be_flat = local.weekday() < 5 and _FLATTEN_BY <= local.time() < _CLOSE
    return SessionGate(
        phase=phase,
        may_enter=may_enter,
        reason=reason,
        must_be_flat=must_be_flat,
        permitted_setups=frozenset(permitted),
        exchange_time=local.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )


# ---------------------------------------------------------------------------
# Initial Balance (spec section 9, stage 2)
# ---------------------------------------------------------------------------


def _bar_moment(bar: Mapping[str, Any]) -> datetime | None:
    """Aware timestamp for a bar, or None if it carries nothing usable."""
    raw = bar.get("ts") or bar.get("timestamp") or bar.get("time") or bar.get("date")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


@dataclass(frozen=True)
class InitialBalance:
    """The 09:30-09:45 opening range, or an honest miss."""

    measurable: bool
    high: float | None
    low: float | None
    bar_count: int
    session_date: str | None
    reason: str | None = None

    @property
    def width(self) -> float | None:
        if self.high is None or self.low is None:
            return None
        return self.high - self.low


def initial_balance(
    bars: Sequence[Mapping[str, Any]],
    *,
    session_day: date | None = None,
) -> InitialBalance:
    """High/low of the first fifteen minutes of the cash session.

    Bars must carry aware timestamps. Bars whose timestamp cannot be read are
    skipped rather than assumed to land in the window -- an IB widened by a
    misplaced bar is worse than no IB, because it silently loosens every
    breakout test measured against it.

    With no bar inside 09:30-09:45 the result is `measurable=False`. This is
    the normal state before 09:45 and on a feed whose first bar of the day
    arrives late; neither is an error, and neither may be papered over with the
    session's first available bar.
    """
    if not bars:
        return InitialBalance(False, None, None, 0, None, "no bars supplied")

    dated: list[tuple[datetime, Mapping[str, Any]]] = []
    for bar in bars:
        moment = _bar_moment(bar)
        if moment is not None:
            dated.append((moment.astimezone(EXCHANGE_TZ), bar))

    if not dated:
        return InitialBalance(
            False, None, None, 0, None,
            "no bar carried an aware timestamp, so none could be placed in the session",
        )

    target = session_day or max(m.date() for m, _ in dated)
    window = [
        (m, b) for m, b in dated
        if m.date() == target and _OPEN <= m.time() < _IB_END
    ]
    if not window:
        return InitialBalance(
            False, None, None, 0, target.isoformat(),
            f"no bar fell inside 09:30-09:45 ET on {target.isoformat()}",
        )

    highs = [float(b["high"]) for _, b in window if b.get("high") is not None]
    lows = [float(b["low"]) for _, b in window if b.get("low") is not None]
    if not highs or not lows:
        return InitialBalance(
            False, None, None, len(window), target.isoformat(),
            "opening-range bars carried no high/low",
        )

    return InitialBalance(
        measurable=True,
        high=max(highs),
        low=min(lows),
        bar_count=len(window),
        session_date=target.isoformat(),
    )


# ---------------------------------------------------------------------------
# Expiry policy (spec section 6)
# ---------------------------------------------------------------------------

#: Symbols liquid enough at same-day expiry to trade 0DTE at all. Everything
#: else is routed to weeklies regardless of what the chain offers, because the
#: spread on a single-name 0DTE eats the move the setup is trying to capture.
_ZERO_DTE_ELIGIBLE = frozenset({"SPY", "SPX", "QQQ", "XSP", "NDX", "IWM", "RUT"})

#: After this time, a 0DTE ATM option's theta is steep enough that a stalled
#: trade loses more to decay than the setup's edge is worth (spec section 6).
_ZERO_DTE_CUTOFF = _LUNCH_END  # 13:30 ET


@dataclass(frozen=True)
class ExpiryPolicy:
    """Which expiry this symbol may be traded at, right now, and why."""

    symbol: str
    max_dte: int
    min_dte: int
    rationale: str
    zero_dte_permitted: bool

    def admits(self, dte: int) -> bool:
        return self.min_dte <= dte <= self.max_dte


def expiry_policy(symbol: str, moment: datetime) -> ExpiryPolicy:
    """Permitted days-to-expiry window for `symbol` at `moment`.

    Index products run 0DTE only inside the morning window and switch to 1DTE
    after 13:30 ET. Single names never run 0DTE, and get a longer floor when
    the entry lands on a Thursday or Friday so the position is not handed
    straight into a weekend of decay.
    """
    sym = symbol.strip().upper()
    local = moment.astimezone(EXCHANGE_TZ)

    if sym in _ZERO_DTE_ELIGIBLE:
        if local.time() < _ZERO_DTE_CUTOFF:
            return ExpiryPolicy(
                sym, max_dte=0, min_dte=0,
                rationale="index product before 13:30 ET: 0DTE permitted",
                zero_dte_permitted=True,
            )
        # "1DTE" in the spec means the next expiry, not an expiry exactly one
        # calendar day out. Enforcing dte == 1 literally would route nothing on
        # a Friday afternoon, when the next expiry is Monday and three calendar
        # days away -- the exact session the rule exists to serve. The ceiling
        # is 3 so a Friday reaches Monday and no further.
        return ExpiryPolicy(
            sym, max_dte=3, min_dte=1,
            rationale=(
                "index product after 13:30 ET: 0DTE theta exceeds ~1% of premium "
                "per 15 minutes of consolidation, so route to the next expiry"
            ),
            zero_dte_permitted=False,
        )

    # Single name. Thursday (3) and Friday (4) entries reach past the weekend.
    # Tested for membership, not `>= 3`: that also caught Saturday and Sunday
    # and had the policy assert "entered Thu/Fri" on a weekend. No entry is
    # permitted then anyway -- `session_gate` blocks it -- but the rationale
    # string is rendered on the desk, and a false reason is still false.
    if local.weekday() in (3, 4):
        return ExpiryPolicy(
            sym, max_dte=14, min_dte=7,
            rationale="single name entered Thu/Fri: 7-14 DTE to clear the weekend",
            zero_dte_permitted=False,
        )
    return ExpiryPolicy(
        sym, max_dte=5, min_dte=2,
        rationale="single name: nearest weekly at 2-5 DTE; 0DTE spreads are prohibitive",
        zero_dte_permitted=False,
    )


# ---------------------------------------------------------------------------
# Spread friction (spec sections 5, 6)
# ---------------------------------------------------------------------------

#: Per-symbol ceiling on (ask - bid) / mid, in percent. Calibrated to what each
#: book actually quotes: SPY trades a penny wide, MSTR's IV pushes market
#: makers out to $0.40-$1.20. A single global cap would either bar MSTR
#: entirely or wave through a SPY fill that has already lost its edge.
SPREAD_FRICTION_CAPS: dict[str, float] = {
    "SPY": 1.0,
    "SPX": 1.0,
    "QQQ": 1.0,
    "IWM": 1.5,
    "TSLA": 2.5,
    "MSTR": 5.0,
}
#: Applied to any symbol not in the table above. Deliberately near the
#: single-name figure rather than the index one: an unlisted symbol is far more
#: likely to quote like TSLA than like SPY.
DEFAULT_SPREAD_FRICTION_CAP = 2.5


@dataclass(frozen=True)
class SpreadCheck:
    """Whether a contract's quoted spread is crossable."""

    measurable: bool
    ratio_pct: float | None
    cap_pct: float
    passes: bool
    mid: float | None
    reason: str | None = None


def spread_friction(
    symbol: str,
    bid: float | None,
    ask: float | None,
) -> SpreadCheck:
    """(ask - bid) / mid as a percentage, against the symbol's cap.

    Returns `measurable=False` and `passes=False` when either side of the book
    is missing. That is the live case on this app's primary option feed, which
    carries last price, volume and greeks but no bid/ask at all -- so the
    honest answer is "not checked, do not route", never "no spread found,
    therefore zero spread".
    """
    cap = SPREAD_FRICTION_CAPS.get(symbol.strip().upper(), DEFAULT_SPREAD_FRICTION_CAP)
    if bid is None or ask is None:
        return SpreadCheck(
            False, None, cap, False, None,
            "no bid/ask on this contract, so execution friction is unmeasured",
        )
    try:
        b, a = float(bid), float(ask)
    except (TypeError, ValueError):
        return SpreadCheck(False, None, cap, False, None, "bid/ask not numeric")
    if not (math.isfinite(b) and math.isfinite(a)) or b <= 0 or a <= 0 or a < b:
        return SpreadCheck(
            False, None, cap, False, None,
            f"bid/ask pair is not a usable quote (bid={b}, ask={a})",
        )

    mid = (a + b) / 2.0
    ratio = (a - b) / mid * 100.0
    return SpreadCheck(
        measurable=True,
        ratio_pct=round(ratio, 3),
        cap_pct=cap,
        passes=ratio <= cap,
        mid=round(mid, 4),
        reason=None if ratio <= cap else f"spread {ratio:.2f}% exceeds the {cap:.1f}% cap for {symbol.upper()}",
    )


# ---------------------------------------------------------------------------
# Contract routing (spec section 6)
# ---------------------------------------------------------------------------

#: The scalping corridor. Gamma peaks at the money, so delta accelerates
#: fastest here; below 0.20 the contract is decay with no convexity, above 0.70
#: it is intrinsic value with no leverage.
DELTA_CORRIDOR = (0.35, 0.50)

#: Slack on the corridor's upper bound. A struck-at-the-money call does not
#: have delta 0.50 -- the drift term puts d1 at (r + sigma^2/2) * sqrt(tau) /
#: sigma, so N(d1) sits just above a half. Testing `<= 0.50` therefore rejects
#: the exact at-the-money strike: the most gamma-dense contract on the board
#: and the one the corridor exists to select. The tolerance admits it without
#: reaching the next strike out, which on any liquid chain differs by far more
#: than this.
_CORRIDOR_TOLERANCE = 0.02


@dataclass(frozen=True)
class ContractChoice:
    """A routed contract, or the reason nothing could be routed."""

    measurable: bool
    strike: float | None
    right: str | None
    expiry: str | None
    delta: float | None
    dte: int | None
    spread: SpreadCheck | None
    considered: int
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def select_contract(
    *,
    symbol: str,
    direction: str,
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
    moment: datetime,
    corridor: tuple[float, float] = DELTA_CORRIDOR,
    require_spread: bool = True,
) -> ContractChoice:
    """Pick the contract closest to the middle of the delta corridor.

    `chain_rows` are the app's usual chain dicts. Each row needs `strike`,
    `right`, `expiry` and enough to establish delta -- either a `delta` the
    feed quotes, or an `iv` this function can price one from. Rows missing both
    are skipped and counted, never assigned a nominal delta.

    When `require_spread` is set (the default) a contract whose spread cannot
    be measured is rejected. Callers running against a feed with no bid/ask can
    pass `require_spread=False` to route anyway; the returned `spread` still
    reports `measurable=False`, so the caller cannot lose track of the fact
    that friction went unchecked.
    """
    want_right = "call" if direction.lower() in ("long", "call", "bullish", "up") else "put"
    policy = expiry_policy(symbol, moment)
    today = moment.astimezone(EXCHANGE_TZ).date()
    lo, hi = corridor
    target = (lo + hi) / 2.0

    considered = 0
    skipped_no_delta = 0
    out_of_policy = 0
    out_of_corridor = 0
    spread_rejected = 0
    best: tuple[float, dict[str, Any]] | None = None

    for row in chain_rows:
        right = str(row.get("right") or row.get("contract_type") or row.get("type") or "").lower()
        right = "call" if right.startswith("c") else "put" if right.startswith("p") else ""
        if right != want_right:
            continue
        considered += 1

        resolved = _row_expiry_dte(row, today=today)
        if resolved is None:
            continue
        exp_date, dte = resolved
        if not policy.admits(dte):
            out_of_policy += 1
            continue

        try:
            strike = float(row.get("strike") or row.get("strike_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if strike <= 0:
            continue

        delta = _row_delta(row, spot=spot, strike=strike, dte=dte, right=right)
        if delta is None:
            skipped_no_delta += 1
            continue

        mag = abs(delta)
        if not lo <= mag <= hi + _CORRIDOR_TOLERANCE:
            out_of_corridor += 1
            continue

        check = spread_friction(symbol, row.get("bid"), row.get("ask"))
        if require_spread and not check.passes:
            spread_rejected += 1
            continue

        distance = abs(mag - target)
        if best is None or distance < best[0]:
            best = (
                distance,
                {
                    "strike": strike,
                    "right": right,
                    "expiry": None if exp_date is None else exp_date.isoformat(),
                    "delta": round(delta, 4),
                    "dte": dte,
                    "spread": check,
                },
            )

    if best is None:
        detail = (
            f"{considered} {want_right}s seen; {out_of_policy} outside the "
            f"{policy.min_dte}-{policy.max_dte} DTE policy, {out_of_corridor} outside the "
            f"{lo:.2f}-{hi:.2f} delta corridor, {skipped_no_delta} with no delta and no IV to "
            f"derive one, {spread_rejected} rejected on spread"
        )
        return ContractChoice(
            measurable=False,
            strike=None,
            right=None,
            expiry=None,
            delta=None,
            dte=None,
            spread=None,
            considered=considered,
            reason=f"no contract satisfied the router ({detail}). Policy: {policy.rationale}",
        )

    chosen = best[1]
    warnings: list[str] = []
    check: SpreadCheck = chosen["spread"]
    if not check.measurable:
        warnings.append(
            "execution friction unchecked: this chain carries no bid/ask, so the "
            "Spread Friction Ratio could not be evaluated for this contract"
        )
    return ContractChoice(
        measurable=True,
        strike=chosen["strike"],
        right=chosen["right"],
        expiry=chosen["expiry"],
        delta=chosen["delta"],
        dte=chosen["dte"],
        spread=check,
        considered=considered,
        warnings=warnings,
    )


def _row_expiry_dte(
    row: Mapping[str, Any], *, today: date
) -> tuple[date | None, int] | None:
    """(expiry date, days-to-expiry) for a chain row, or None if neither reads.

    Two row shapes reach this router. The 0DTE chain fetch carries a dated
    `expiry` string; the main options payload carries an integer `dte` and no
    expiry at all. The policy is written in DTE, so an explicit `dte` is taken
    at face value and the date is left None rather than back-solved into a
    calendar day the feed never asserted -- adding `dte` to today would land on
    a weekend or holiday and print an expiry that does not trade.
    """
    raw_dte = row.get("dte")
    if raw_dte is not None:
        try:
            return None, int(raw_dte)
        except (TypeError, ValueError):
            pass

    raw_expiry = row.get("expiry") or row.get("expiration") or row.get("exp")
    try:
        exp_date = date.fromisoformat(str(raw_expiry))
    except (TypeError, ValueError):
        return None
    return exp_date, (exp_date - today).days


def _row_delta(
    row: Mapping[str, Any],
    *,
    spot: float,
    strike: float,
    dte: int,
    right: str,
) -> float | None:
    """Delta from the feed if it quotes one, else priced from the row's IV.

    Returns None when neither is available. `years` follows `zero_dte.py`: a
    same-day expiry is a fraction of a session, not a calendar day, and pricing
    0DTE at 1/365 understates ATM gamma (and so overstates how far delta has
    left to travel) by roughly 3x at the open.
    """
    from edge.research.microstructure_regime import calculate_option_greeks

    quoted = row.get("delta")
    if quoted is not None:
        try:
            value = float(quoted)
            if math.isfinite(value) and 0.0 < abs(value) <= 1.0:
                return value
        except (TypeError, ValueError):
            pass

    iv_raw = row.get("iv") or row.get("impliedVolatility") or row.get("implied_volatility")
    if iv_raw is None:
        return None
    try:
        iv = float(iv_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(iv) or iv <= 0:
        return None

    years = max(dte, 0.25) / 365.0
    greeks = calculate_option_greeks(
        spot=spot, strike=strike, years=years, iv=iv, right=right
    )
    return None if greeks is None else greeks.delta


# ---------------------------------------------------------------------------
# Position sizing (spec section 8)
# ---------------------------------------------------------------------------

#: One-fifth Kelly. Full Kelly maximises long-run growth on a *known* edge;
#: these win rates are estimated from a finite sample, and the penalty for
#: overestimating p is geometric, so the fraction is throttled hard.
KELLY_FRACTION = 0.20
#: Hard ceiling on risk capital per setup, as a fraction of equity.
MAX_RISK_FRACTION = 0.015


def fractional_kelly(
    win_rate: float,
    payoff_ratio: float,
    *,
    fraction: float = KELLY_FRACTION,
) -> float:
    """f* = ((p*b - q) / b) * fraction, floored at zero.

    A negative raw Kelly means the setup has no edge at these statistics; it is
    returned as 0.0 (do not trade), never as a short of the setup, because the
    inverse of a losing long setup is not a winning short one.
    """
    if not 0.0 < win_rate < 1.0:
        raise ValueError(f"win_rate must be a probability in (0, 1); got {win_rate}")
    if payoff_ratio <= 0:
        raise ValueError(f"payoff_ratio must be positive; got {payoff_ratio}")
    raw = (win_rate * payoff_ratio - (1.0 - win_rate)) / payoff_ratio
    return max(0.0, raw * fraction)


@dataclass(frozen=True)
class PositionSize:
    """Contract count and the risk arithmetic behind it."""

    contracts: int
    risk_fraction: float
    risk_dollars: float
    risk_per_contract: float
    kelly_fraction: float
    capped: bool
    reason: str | None = None


def position_size(
    *,
    equity: float,
    win_rate: float,
    payoff_ratio: float,
    entry_premium: float,
    premium_at_stop: float,
    max_risk_fraction: float = MAX_RISK_FRACTION,
    multiplier: float = 100.0,
) -> PositionSize:
    """Contracts to trade, sized off the loss at the *underlying* stop.

    `premium_at_stop` is the contract's theoretical value priced at the
    underlying's invalidation tick -- not a percentage haircut on the entry
    premium. The distinction is the whole point: an option that loses 40% of
    its premium on a move that never violated the structural level has not
    invalidated the thesis, and sizing off a premium-percentage stop
    systematically over-sizes trades whose structural stop is close and
    under-sizes trades whose structural stop is far.

    Returns zero contracts with a `reason` when the edge is nil or the risk per
    contract exceeds the whole budget, rather than rounding up to one.
    """
    if equity <= 0:
        raise ValueError(f"equity must be positive; got {equity}")
    if entry_premium <= 0:
        raise ValueError(f"entry_premium must be positive; got {entry_premium}")
    if premium_at_stop < 0:
        raise ValueError(f"premium_at_stop cannot be negative; got {premium_at_stop}")
    if premium_at_stop >= entry_premium:
        raise ValueError(
            "premium_at_stop must be below entry_premium; a stop that is not a "
            f"loss cannot size a position (entry={entry_premium}, stop={premium_at_stop})"
        )

    kelly = fractional_kelly(win_rate, payoff_ratio)
    capped = kelly > max_risk_fraction
    risk_fraction = min(kelly, max_risk_fraction)
    risk_dollars = equity * risk_fraction
    risk_per_contract = (entry_premium - premium_at_stop) * multiplier

    if risk_fraction <= 0.0:
        return PositionSize(
            0, 0.0, 0.0, risk_per_contract, kelly, capped,
            "fractional Kelly is zero at these statistics: the setup shows no edge",
        )
    contracts = int(risk_dollars // risk_per_contract)
    if contracts < 1:
        return PositionSize(
            0, risk_fraction, round(risk_dollars, 2), round(risk_per_contract, 2), kelly, capped,
            f"one contract risks ${risk_per_contract:,.2f}, above the "
            f"${risk_dollars:,.2f} budget for this setup",
        )
    return PositionSize(
        contracts=contracts,
        risk_fraction=round(risk_fraction, 5),
        risk_dollars=round(risk_dollars, 2),
        risk_per_contract=round(risk_per_contract, 2),
        kelly_fraction=round(kelly, 5),
        capped=capped,
    )
