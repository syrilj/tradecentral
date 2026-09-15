"""Truth-preserving options-flow, gamma, and implied-range analytics.

The module is deliberately provider-agnostic.  It accepts normalized chain and
trade-tape mappings and returns JSON-safe diagnostics for the dashboard.  Call
versus put activity is always observable; bought versus sold flow is only
signed when the source includes an explicit aggressor field.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
import math
import re
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .activity_lean import describe_activity_lean


@dataclass(frozen=True)
class OptionsFilters:
    range: str = "1d"
    min_premium: float = 50_000.0
    min_volume: int = 10
    min_open_interest: int = 100
    max_spread_pct: float = 0.25
    min_dte: int = 0
    max_dte: int = 60
    expiry: str = "nearest"
    tape_limit: int = 100
    date_from: str | None = None
    date_to: str | None = None
    risk_free_rate: float = 0.045

    def __post_init__(self) -> None:
        if self.range not in {"1d", "5d", "1m", "3m"}:
            raise ValueError("unsupported options range")
        if self.min_premium < 0 or self.min_volume < 0 or self.min_open_interest < 0:
            raise ValueError("liquidity filters must be non-negative")
        if not 0 < self.max_spread_pct <= 2:
            raise ValueError("max_spread_pct must be in (0, 2]")
        if self.min_dte < 0 or self.max_dte < self.min_dte or self.max_dte > 730:
            raise ValueError("invalid DTE range")
        if self.expiry != "nearest" and self.expiry != "all":
            try:
                date.fromisoformat(self.expiry)
            except ValueError as exc:
                raise ValueError("expiry must be nearest, all, or YYYY-MM-DD") from exc
        if not 1 <= self.tape_limit <= 5000:
            raise ValueError("tape_limit must be in [1, 5000]")
        if not -0.05 <= self.risk_free_rate <= 0.25:
            raise ValueError("risk_free_rate outside supported range")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def _first(row: Mapping[str, Any], *names: str) -> Any:
    return next((row.get(name) for name in names if row.get(name) is not None), None)


def _right(value: Any) -> str | None:
    return {
        "c": "call", "call": "call", "calls": "call",
        "p": "put", "put": "put", "puts": "put",
    }.get(str(value or "").strip().lower())


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # Provider timestamps may be seconds, milliseconds, or nanoseconds.
            observed = float(value)
            if observed > 1e17:
                observed /= 1e9
            elif observed > 1e12:
                observed /= 1e3
            return datetime.fromtimestamp(observed, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_date_only_timestamp(value: datetime) -> bool:
    """True when the provider only stamped the calendar day (midnight UTC)."""
    return value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0


def _best_observation_time(values: Sequence[datetime | None]) -> datetime | None:
    """Newest observation, preferring real clock times over midnight day-buckets.

    LSE sometimes emits session prints as ``YYYY-MM-DDT00:00:00Z``. Using those
    as "last observation" makes a live feed look 12–20h stale mid-session even
    while sub-premium prints arrive with proper timestamps.
    """
    stamps = [value for value in values if value is not None]
    if not stamps:
        return None
    precise = [value for value in stamps if not _is_date_only_timestamp(value)]
    return max(precise or stamps)


def _expiry(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_gamma(
    *, spot: float, strike: float, years: float, iv: float, rate: float, yield_rate: float = 0.0,
) -> float | None:
    """Black-Scholes gamma (dividend-adjusted).

    Γ = e^{-qT}·φ(d1) / (S·σ·√T). The dividend terms were previously dropped
    here while ``_bs_d1`` / ``_bs_delta`` carried them, so a non-zero yield made
    delta and gamma disagree on the same contract. q = 0 for single names today,
    but the drift is a live trap for index/ETF chains.
    """
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - yield_rate + 0.5 * iv * iv) * years) / (iv * root_t)
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return math.exp(-yield_rate * years) * pdf_d1 / (spot * iv * root_t)


def _bs_d1(*, spot: float, strike: float, years: float, iv: float, rate: float, yield_rate: float = 0.0) -> float | None:
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    root_t = math.sqrt(years)
    return (math.log(spot / strike) + (rate - yield_rate + 0.5 * iv * iv) * years) / (iv * root_t)


def _bs_delta(*, spot: float, strike: float, years: float, iv: float, rate: float, yield_rate: float = 0.0, is_call: bool = True) -> float | None:
    """Black-Scholes delta (dividend-adjusted)."""
    d1 = _bs_d1(spot=spot, strike=strike, years=years, iv=iv, rate=rate, yield_rate=yield_rate)
    if d1 is None:
        return None
    eq_t = math.exp(-yield_rate * years)
    delta = eq_t * _normal_cdf(d1)
    return delta if is_call else delta - eq_t


def _bs_charm_per_day(*, spot: float, strike: float, years: float, iv: float, rate: float, yield_rate: float = 0.0, is_call: bool = True) -> float | None:
    """Charm = ∂Δ/∂t in delta-per-day (standard −∂Δ/∂τ convention, /365).

    Charmcall = e^{-qT} [ q·N(d1) − φ(d1)·(2(r−q)T − d2·σ√T) / (2σT√T) ]
    Charmput  = Charmcall − q·e^{-qT}

    With q = 0 (single-stock approximation) charm is identical for calls and
    puts, like gamma. Near-expiry contracts (T < 1 day) and implausible IV
    return None so the exposure never explodes into a fake reading.
    """
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    if years < 1.0 / 365.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - yield_rate + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    eq_t = math.exp(-yield_rate * years)
    nd1 = _normal_cdf(d1)
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    charm_year = eq_t * (
        yield_rate * nd1
        - pdf_d1 * (2.0 * (rate - yield_rate) * years - d2 * iv * root_t)
        / (2.0 * iv * years * root_t)
    )
    if not is_call:
        charm_year -= yield_rate * eq_t
    return charm_year / 365.0


def _bs_theta_per_day(*, spot: float, strike: float, years: float, iv: float, rate: float, is_call: bool = True) -> float | None:
    """Theta = ∂V/∂t in option-price-points-per-day (standard −∂V/∂τ, /365).
    Theta_call = −S·φ(d1)·σ / (2√T) − r·K·e^{−rT}·N(d2)
    Theta_put  = −S·φ(d1)·σ / (2√T) + r·K·e^{−rT}·N(−d2)
    Near-expiry contracts (T < 1 day) and implausible IV return None so decay
    never explodes into a fake reading.
    """
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    if years < 1.0 / 365.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    common = -spot * pdf_d1 * iv / (2.0 * root_t)
    if is_call:
        theta_year = common - rate * strike * math.exp(-rate * years) * _normal_cdf(d2)
    else:
        theta_year = common + rate * strike * math.exp(-rate * years) * _normal_cdf(-d2)
    return theta_year / 365.0


def _bs_vanna(*, spot: float, strike: float, years: float, iv: float, rate: float) -> float | None:
    """Vanna = ∂Δ/∂σ in delta per +1.00 IV move (per vol point /100).
    Vanna = −φ(d1)·d2 / σ   (q = 0 single-stock approximation)
    Identical for calls and puts. Sign: OTM calls gain delta as IV rises,
    OTM puts lose delta as IV rises. Near-expiry contracts (T < 1 day) and
    implausible IV return None so exposure never explodes into a fake reading.
    """
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    if years < 1.0 / 365.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    d2 = d1 - iv * root_t
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return -pdf_d1 * d2 / iv / 100.0


def _date_bounds(filters: OptionsFilters, asof: datetime) -> tuple[datetime, datetime]:
    """Calendar window for price series / history chain selection."""
    window_days = {"1d": 1, "5d": 5, "1m": 31, "3m": 93}[filters.range]
    lower = asof - timedelta(days=window_days)
    upper = asof
    parsed_from = _timestamp(filters.date_from)
    parsed_to = _timestamp(filters.date_to)
    if parsed_from:
        lower = parsed_from
    if parsed_to:
        upper = parsed_to + timedelta(days=1) - timedelta(microseconds=1)
    return lower, upper


def _flow_date_bounds(
    filters: OptionsFilters,
    asof: datetime,
    *,
    mode_requested: str = "live",
) -> tuple[datetime, datetime]:
    """
    Window for trade-tape acceptance.

    Live mode must NOT inherit history chain-day filters (`date_to` / `date_from`).
    Those fields select which cached chain parquet day to load — applying them
    to the live tape zeroes every print as ``outside_range`` (classic desk bug).
    """
    window_days = {"1d": 1, "5d": 5, "1m": 31, "3m": 93}[filters.range]
    # Small pads: exchange clocks / delayed prints can sit slightly outside `asof`.
    lower = asof - timedelta(days=window_days) - timedelta(hours=6)
    upper = asof + timedelta(hours=6)
    if str(mode_requested).lower() != "live":
        parsed_from = _timestamp(filters.date_from)
        parsed_to = _timestamp(filters.date_to)
        if parsed_from:
            lower = parsed_from - timedelta(hours=6)
        if parsed_to:
            upper = parsed_to + timedelta(days=1) + timedelta(hours=6)
    return lower, upper


def _bucket_time(observed: datetime, selected_range: str) -> datetime:
    if selected_range == "1d":
        minute = observed.minute - observed.minute % 15
        return observed.replace(minute=minute, second=0, microsecond=0)
    if selected_range == "5d":
        return observed.replace(minute=0, second=0, microsecond=0)
    return observed.replace(hour=0, minute=0, second=0, microsecond=0)


def _normalize_chain_row(row: Mapping[str, Any], *, asof: datetime, spot: float | None) -> dict[str, Any]:
    expiry = _expiry(_first(row, "expiry", "expiration", "expiration_date"))
    observed = _timestamp(_first(
        row, "quote_asof_utc", "captured_utc", "asof_utc", "timestamp", "updated_at",
    ))
    bid = _number(_first(row, "bid", "best_bid"))
    ask = _number(_first(row, "ask", "best_ask"))
    mid = ((bid + ask) / 2.0) if bid is not None and ask is not None and ask >= bid >= 0 else None
    row_spot = _number(_first(row, "spot", "underlying_price")) or spot
    dte = (expiry - asof.date()).days if expiry else _integer(row.get("dte"))
    return {
        "right": _right(_first(row, "right", "contract_type", "option_type", "type")),
        "expiry": expiry,
        "dte": dte,
        "strike": _number(_first(row, "strike", "strike_price")),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": ((ask - bid) / mid) if mid and bid is not None and ask is not None else None,
        "volume": _integer(_first(row, "volume", "volume_today")) or 0,
        "open_interest": _integer(_first(row, "open_interest", "openInterest", "oi")) or 0,
        "iv": _number(_first(row, "iv", "implied_vol", "impliedVolatility")),
        "delta": _number(row.get("delta")),
        "gamma": _number(row.get("gamma")),
        "multiplier": _integer(_first(row, "multiplier", "contract_multiplier")) or 100,
        "observed_at": observed,
        "spot": row_spot,
        "occ_symbol": _first(row, "occ_symbol", "contract_symbol", "contractSymbol", "ticker"),
        "quote_live": bool(row.get("quote_live")),
        "quote_source": _first(row, "quote_source", "provider"),
    }


def _filter_chain(
    rows: Sequence[Mapping[str, Any]], *, asof: datetime, spot: float, filters: OptionsFilters,
    selection_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    included: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for raw in rows:
        row = _normalize_chain_row(raw, asof=asof, spot=spot)
        reason: str | None = None
        if row["right"] is None or row["strike"] is None or row["expiry"] is None:
            reason = "invalid_identity"
        elif row["dte"] is None or not filters.min_dte <= row["dte"] <= filters.max_dte:
            reason = "outside_dte"
        elif row["open_interest"] < filters.min_open_interest:
            reason = "low_open_interest"
        elif row["spread_pct"] is not None and row["spread_pct"] > filters.max_spread_pct:
            reason = "wide_spread"
        elif row["iv"] is not None and not 0.005 <= row["iv"] <= 5.0:
            reason = "implausible_iv"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
        else:
            included.append(row)
    expiry_counts: dict[date, int] = {}
    expiry_oi: dict[date, int] = {}
    for row in included:
        expiry = row["expiry"]
        expiry_counts[expiry] = expiry_counts.get(expiry, 0) + 1
        expiry_oi[expiry] = expiry_oi.get(expiry, 0) + int(row["open_interest"] or 0)

    available = sorted(expiry_counts)
    selection_day = selection_date or asof.date()
    selected: date | None = None
    skipped_unmeasurable: list[date] = []
    if filters.expiry == "nearest":
        unexpired = [expiry for expiry in available if expiry >= selection_day]
        # Every structural figure downstream — GEX, the walls, the squeeze
        # board — is open-interest weighted. An expiry whose whole slice has
        # zero OI is unmeasurable, and scoring it renders a fake-flat "quiet"
        # structure. That happens whenever the live feed lists a nearer expiry
        # than the delayed OI reference carries (LSE quotes a Monday weekly the
        # yfinance snapshot never listed). Measure the nearest expiry that can
        # actually be measured, and only fall back to the literal nearest when
        # no expiry carries OI at all — then "unmeasured" is the honest answer.
        measurable = [expiry for expiry in unexpired if expiry_oi.get(expiry, 0) > 0]
        if measurable:
            selected = measurable[0]
            skipped_unmeasurable = [
                expiry for expiry in unexpired if expiry < selected
            ]
        else:
            selected = unexpired[0] if unexpired else (available[-1] if available else None)
    elif filters.expiry != "all":
        selected = _expiry(filters.expiry)

    if selected is not None:
        before = len(included)
        included = [row for row in included if row["expiry"] == selected]
        outside = before - len(included)
        if outside:
            rejected["outside_expiry"] = rejected.get("outside_expiry", 0) + outside

    context = {
        "selection": filters.expiry,
        "selected_expiry": selected.isoformat() if selected else None,
        "selected_dte": (selected - selection_day).days if selected else None,
        "snapshot_dte": (selected - asof.date()).days if selected else None,
        "selection_asof": selection_day.isoformat(),
        # Nearer expiries the feed listed but no OI reference covers. Named so
        # the desk can see the structure is scored one expiry out, not silently.
        "skipped_unmeasurable_expiries": [
            expiry.isoformat() for expiry in skipped_unmeasurable
        ],
        "available_expiries": [
            {
                "expiry": expiry.isoformat(),
                "dte": (expiry - selection_day).days,
                "snapshot_dte": (expiry - asof.date()).days,
                "contracts": expiry_counts[expiry],
                "open_interest": expiry_oi.get(expiry, 0),
            }
            for expiry in available
        ],
    }
    return included, rejected, context


def _contract_focus(
    rows: Sequence[Mapping[str, Any]], *, asof: datetime, spot: float,
) -> dict[str, dict[str, Any]]:
    """Choose one inspectable long-option contract for each right.

    This is a deterministic contract router, not a directional signal.  It
    prefers an executable two-sided quote, roughly 30 DTE, approximately
    0.45 absolute delta, a tight spread, and observed liquidity.  When delta
    is absent, distance from spot is the explicit fallback.
    """
    normalized = [
        _normalize_chain_row(raw, asof=asof, spot=spot)
        for raw in rows
    ]
    valid = [
        row for row in normalized
        if row.get("right") in {"call", "put"}
        and row.get("strike") is not None
        and row.get("expiry") is not None
        and row.get("dte") is not None
        and 0 <= int(row["dte"]) <= 60
        # Corporate-action/provider normalization failures showed up live as
        # absurd deep-ITM strikes. Keep them out of the contract router.
        and 0.70 <= float(row["strike"]) / spot <= 1.30
    ]

    def score(row: Mapping[str, Any]) -> tuple[float, ...]:
        bid = _number(row.get("bid"))
        ask = _number(row.get("ask"))
        mid = _number(row.get("mid"))
        delta = _number(row.get("delta"))
        strike = _number(row.get("strike")) or spot
        dte = int(row.get("dte") or 0)
        spread = _number(row.get("spread_pct"))
        open_interest = max(0, int(row.get("open_interest") or 0))
        volume = max(0, int(row.get("volume") or 0))
        liquidity = open_interest + volume
        quote_observed = bool(
            bid is not None and ask is not None and ask >= bid >= 0 and mid is not None and mid > 0
        )
        live_quote_penalty = 0.0 if quote_observed and row.get("quote_live") else 1.0
        reference_quote_penalty = 0.0 if quote_observed else 1.0
        delta_missing = 0.0 if delta is not None and 0.05 <= abs(delta) <= 0.95 else 1.0
        delta_distance = abs(abs(delta) - 0.45) if delta_missing == 0.0 else abs(strike / spot - 1.0)
        delta_band_penalty = 0.0 if delta is not None and 0.25 <= abs(delta) <= 0.65 else 1.0
        preferred_dte_penalty = 0.0 if 7 <= dte <= 45 else 1.0
        liquidity_penalty = 0.0 if open_interest >= 100 and volume >= 10 else 1.0
        dte_distance = abs(dte - 30) / 30.0
        spread_penalty = spread if spread is not None and spread >= 0 else 1.5
        # A log transform keeps one giant OI print from overwhelming quote
        # quality and strike/expiry suitability.
        liquidity_reward = -math.log1p(liquidity)
        return (
            live_quote_penalty,
            reference_quote_penalty,
            preferred_dte_penalty,
            delta_missing,
            delta_band_penalty,
            liquidity_penalty,
            round(spread_penalty, 8),
            round(delta_distance, 8),
            round(dte_distance, 8),
            liquidity_reward,
            strike,
        )

    selected: dict[str, dict[str, Any]] = {}
    for right in ("call", "put"):
        candidates = [row for row in valid if row.get("right") == right]
        if not candidates:
            continue
        row = min(candidates, key=score)
        expiry = row.get("expiry")
        bid = _number(row.get("bid"))
        ask = _number(row.get("ask"))
        midpoint = _number(row.get("mid"))
        spread_pct = _number(row.get("spread_pct"))
        volume = int(row.get("volume") or 0)
        open_interest = int(row.get("open_interest") or 0)
        dte = int(row["dte"]) if row.get("dte") is not None else None
        quote_observed = bool(
            bid is not None and ask is not None and midpoint is not None
            and midpoint > 0 and ask >= bid >= 0
        )
        quote_live = bool(row.get("quote_live"))
        quote_complete = bool(
            quote_observed and quote_live
            and spread_pct is not None and spread_pct <= 0.25
        )
        liquidity_complete = bool(open_interest >= 100 and volume >= 10)
        tenor_complete = bool(dte is not None and 7 <= dte <= 45)
        rejection_reasons = [
            label for failed, label in (
                (not quote_observed, "two-sided quote missing"),
                (quote_observed and not quote_live, "quote is delayed reference only; live two-sided quote required"),
                (quote_observed and quote_live and not quote_complete, "live spread is above 25%"),
                (not liquidity_complete, "requires volume >= 10 and open interest >= 100"),
                (not tenor_complete, "preferred contract tenor is 7–45 DTE"),
            )
            if failed
        ]
        selected[right] = {
            "right": right,
            "occ_symbol": row.get("occ_symbol"),
            "strike": _number(row.get("strike")),
            "expiry": expiry.isoformat() if isinstance(expiry, date) else str(expiry or "") or None,
            "dte": dte,
            "bid": bid,
            "ask": ask,
            "midpoint": midpoint,
            "spread_pct": spread_pct,
            "volume": volume,
            "open_interest": open_interest,
            "implied_volatility": _number(row.get("iv")),
            "delta": _number(row.get("delta")),
            "contract_multiplier": int(row.get("multiplier") or 100),
            "observed_at": (
                row["observed_at"].isoformat()
                if isinstance(row.get("observed_at"), datetime)
                else str(row.get("observed_at") or "") or None
            ),
            "quote_complete": quote_complete,
            "quote_observed": quote_observed,
            "quote_live": quote_live,
            "quote_reference_only": bool(quote_observed and not quote_live),
            "quote_source": row.get("quote_source"),
            "quote_status": (
                "live_two_sided" if quote_complete
                else "delayed_reference" if quote_observed and not quote_live
                else "live_spread_failed" if quote_observed
                else "missing"
            ),
            "liquidity_complete": liquidity_complete,
            "tenor_complete": tenor_complete,
            "contract_complete": bool(quote_complete and liquidity_complete and tenor_complete),
            "rejection_reasons": rejection_reasons,
            "selection_method": (
                "Prefer a live or delayed exact quote, 7–45 DTE, |delta| 0.25–0.65, "
                "and volume/OI gates before fine delta distance. Delayed quotes are "
                "paper references only and can never unlock sizing."
            ),
        }
    return selected


def _latest_chain(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], datetime | None]:
    observed = [
        _timestamp(_first(row, "captured_utc", "asof_utc", "timestamp", "updated_at", "asof_date"))
        for row in rows
    ]
    latest = max((value for value in observed if value is not None), default=None)
    if latest is None:
        return list(rows), None
    latest_day = latest.date()
    return [row for row, ts in zip(rows, observed) if ts and ts.date() == latest_day], latest


def _normalize_aggressor(row: Mapping[str, Any]) -> str | None:
    """Explicit buy/sell only — never invent from call/put identity alone.

    Stale quote proxies (``_stale_quote_side``) are excluded so delayed
    bid/ask position cannot become fake signed edge.
    """
    raw = _first(
        row,
        "aggressor", "trade_side", "order_side", "buy_sell", "aggressor_side",
        "aggressor_label", "side", "bs",
    )
    value = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if value in {
        "B", "BUY", "BOUGHT", "BUYER", "AT_ASK", "ASK", "ASK_BUY", "BUY_TO_OPEN",
        "BUY_TO_CLOSE", "BOT", "HIT_ASK", "LIFT", "LIFTED",
    }:
        return "buy"
    if value in {
        "S", "SELL", "SOLD", "SELLER", "AT_BID", "BID", "BID_SELL", "SELL_TO_OPEN",
        "SELL_TO_CLOSE", "SLD", "HIT_BID", "HIT",
    }:
        return "sell"
    # Free-text aggressor labels from some scanners.
    if "AT_ASK" in value or value.endswith("_BUY") or value.startswith("BUY"):
        return "buy"
    if "AT_BID" in value or value.endswith("_SELL") or value.startswith("SELL"):
        return "sell"
    return None


def _vendor_sentiment_bias(row: Mapping[str, Any]) -> str | None:
    """Optional vendor lean string (bullish/bearish) when present — not call/put."""
    raw = _first(row, "sentiment", "direction", "lean", "bias", "flow_bias")
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if "bull" in value or value in {"long", "up", "call_buy", "put_sell"}:
        return "bullish"
    if "bear" in value or value in {"short", "down", "put_buy", "call_sell"}:
        return "bearish"
    return None


def _normalize_trade_class(row: Mapping[str, Any], *, volume: int, premium: float) -> tuple[str, str]:
    """Classify print as sweep / block / single when the vendor does not tag it.

    LSE does not emit an explicit sweep flag. Vendor strings (if present) win;
    otherwise size heuristics only — never a directional inference.
    """
    raw = _first(
        row,
        "trade_class", "trade_type", "order_type", "condition", "print_type",
        "execution_type", "tag", "tags",
    )
    text = str(raw or "").strip().lower()
    if text:
        if "sweep" in text:
            return "sweep", "vendor"
        if "block" in text or "cross" in text:
            return "block", "vendor"
        if "split" in text or "multi" in text:
            return "sweep", "vendor"
        if "single" in text or "auto" in text or "regular" in text:
            return "single", "vendor"
    # A large print is observable, but calling it a block would imply venue /
    # execution knowledge the provider did not supply.
    if premium >= 500_000.0 or volume >= 500:
        return "large", "size_heuristic"
    return "single", "unclassified"


_OCC_RE = re.compile(r"^([A-Za-z.]{1,6})([0-9]{2})([0-9]{2})([0-9]{2})([CPcp])([0-9]{8})$")


def _parse_occ_symbol(value: Any) -> dict[str, Any]:
    """Extract symbol, expiry, right, and strike from standard OCC ticker."""
    if not value:
        return {}
    text = str(value).strip().upper()
    match = _OCC_RE.match(text)
    if not match:
        return {}
    sym, yy, mm, dd, cp, strike_raw = match.groups()
    try:
        exp = date(2000 + int(yy), int(mm), int(dd))
        strike = int(strike_raw) / 1000.0
        right = "call" if cp == "C" else "put"
        return {"symbol": sym, "expiry": exp, "right": right, "strike": strike}
    except (ValueError, OverflowError):
        return {}


def _normalize_flow_row(row: Mapping[str, Any], fallback_spot: float | None = None) -> dict[str, Any] | None:
    occ_symbol = _first(row, "occ_symbol", "contract_symbol", "contractSymbol", "ticker", "option_symbol")
    occ_info = _parse_occ_symbol(occ_symbol)

    right = _right(_first(row, "contract_type", "option_type", "right", "type")) or occ_info.get("right")
    observed = _timestamp(_first(row, "ts", "timestamp", "datetime", "time", "last_trade_at", "updated_at"))
    volume_raw = _integer(_first(row, "volume", "volume_today", "size", "contracts", "quantity"))
    volume = int(volume_raw) if volume_raw is not None else 0
    price = _number(_first(row, "price", "last_price", "trade_price", "fill_price", "mid"))
    premium = _number(_first(row, "premium", "total_premium", "est_premium", "notional"))
    multiplier = _integer(_first(row, "multiplier", "contract_multiplier"))
    eff_multiplier = multiplier if multiplier is not None else 100
    estimated = False
    price_estimated = False
    effective_mult = multiplier if multiplier is not None else (100 if occ_info else None)
    if premium is None and price is not None and volume > 0 and effective_mult is not None:
        premium = price * volume * effective_mult
        estimated = True
    if price is None and premium is not None and volume > 0 and effective_mult is not None:
        price = premium / (volume * effective_mult)
        price_estimated = True
    if right is None or observed is None or premium is None or premium < 0:
        return None
    aggressor = _normalize_aggressor(row)
    vendor_bias = _vendor_sentiment_bias(row)
    signed: float | None = None
    bias: str | None = None
    bias_source: str = "none"
    if aggressor:
        bullish = (right == "call" and aggressor == "buy") or (right == "put" and aggressor == "sell")
        signed = premium if bullish else -premium
        bias = "bullish" if bullish else "bearish"
        bias_source = "aggressor"
    elif vendor_bias:
        # Vendor already labeled the print; still not inventing from C/P alone.
        bias = vendor_bias
        bias_source = "vendor_sentiment"
        signed = premium if bias == "bullish" else -premium
    # Extract stock/underlying price when trade occurred, falling back to session spot.
    # OTM distance is a contract-identity measurement, not directional evidence:
    # calls are OTM above spot and puts are OTM below spot. ITM/ATM contracts are
    # reported as 0 rather than a negative "OTM" percentage.
    underlying_price = _number(_first(row, "underlying_price", "spot", "underlying_spot", "stock_price"))
    if underlying_price is None and fallback_spot is not None:
        underlying_price = fallback_spot
    strike = _number(row.get("strike"))
    if strike is None:
        strike = occ_info.get("strike")
    expiry = _expiry(_first(row, "expiry", "expiration", "expiration_date"))
    if expiry is None:
        expiry = occ_info.get("expiry")
    if expiry is not None and expiry < observed.date():
        return None
    dte = (expiry - observed.date()).days if expiry is not None else None
    otm_pct: float | None = None
    if strike is not None and underlying_price is not None and underlying_price > 0:
        raw_otm = (
            strike / underlying_price - 1.0
            if right == "call"
            else 1.0 - strike / underlying_price
        )
        otm_pct = max(0.0, raw_otm)

    # Always expose contract identity for the tape (CALL/PUT activity scan).
    activity_side = "call" if right == "call" else "put"
    trade_class, trade_class_source = _normalize_trade_class(row, volume=volume, premium=float(premium))
    symbol = _underlying_from_row(row) or occ_info.get("symbol")
    return {
        "timestamp": observed,
        "symbol": symbol,
        "right": right,
        "premium": premium,
        "volume": volume_raw,
        # contracts == volume for options tape (lot size = contract count).
        "contracts": volume_raw,
        "contract_multiplier": multiplier,
        "price": round(price, 4) if price is not None else None,
        "price_estimated": price_estimated,
        "strike": strike,
        "occ_symbol": occ_symbol,
        "underlying_price": round(underlying_price, 4) if underlying_price is not None else None,
        "expiry": expiry,
        "dte": dte,
        "otm_pct": round(otm_pct, 6) if otm_pct is not None else None,
        "open_interest": _integer(_first(row, "open_interest", "oi")),
        "implied_volatility": _number(_first(row, "implied_volatility", "iv")),
        "aggressor": aggressor,
        "signed_premium": signed,
        "bias": bias,
        "bias_source": bias_source,
        "activity_side": activity_side,
        "trade_class": trade_class,
        "trade_class_source": trade_class_source,
        "premium_estimated": estimated,
    }


def _percentile_rank(values: Sequence[float], value: float) -> float:
    """Empirical percentile with ties kept together; descriptive, not predictive."""
    if not values:
        return 0.0
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return (below + 0.5 * equal) / len(values)


def _robust_score(values: Sequence[float], value: float) -> float | None:
    """MAD z-score. Small samples deliberately produce no anomaly verdict."""
    if len(values) < 8:
        return None
    center = median(values)
    mad = median(abs(item - center) for item in values)
    if mad <= 0:
        return None
    return 0.67448975 * (value - center) / mad


def _annotate_tape_anomalies(tape: list[dict[str, Any]]) -> None:
    """Mark observable statistical outliers without inferring trade intent."""
    premiums = [float(row["premium"]) for row in tape]
    volumes = [
        float(row["volume"]) if row.get("volume") is not None else 0.0
        for row in tape
    ]
    premium_center = median(premiums) if premiums else 0.0

    clusters: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in tape:
        key = (row["right"], row["strike"], row["expiry"])
        clusters.setdefault(key, []).append(row)

    clustered_ids: set[int] = set()
    # Tight burst clusters (same contract, ≤3s gaps, multi-print) → sweep tier.
    sweep_ids: set[int] = set()
    for rows in clusters.values():
        ordered = sorted(rows, key=lambda row: row["timestamp"])
        if len(ordered) >= 3:
            span = (ordered[-1]["timestamp"] - ordered[0]["timestamp"]).total_seconds()
            cluster_premium = sum(float(row["premium"]) for row in ordered)
            if span <= 15 * 60 and cluster_premium >= max(250_000.0, premium_center * 3.0):
                clustered_ids.update(id(row) for row in ordered)
        # Sweep: ≥2 prints on same contract with consecutive gap ≤ 3s and
        # combined premium ≥ $100k (app-side tape burst, not vendor-certified).
        if len(ordered) >= 2:
            run: list[dict[str, Any]] = [ordered[0]]
            for nxt in ordered[1:]:
                gap = (nxt["timestamp"] - run[-1]["timestamp"]).total_seconds()
                if 0 <= gap <= 3.0:
                    run.append(nxt)
                else:
                    if len(run) >= 2 and sum(float(r["premium"]) for r in run) >= 100_000.0:
                        sweep_ids.update(id(r) for r in run)
                    run = [nxt]
            if len(run) >= 2 and sum(float(r["premium"]) for r in run) >= 100_000.0:
                sweep_ids.update(id(r) for r in run)

    for row in tape:
        premium = float(row["premium"])
        volume = float(row["volume"]) if row.get("volume") is not None else 0.0
        premium_score = _robust_score(premiums, premium)
        volume_score = _robust_score(volumes, volume)
        flags: list[str] = []
        if premium_score is not None and premium_score >= 3.5:
            flags.append("premium_outlier")
        if volume_score is not None and volume_score >= 3.5:
            flags.append("volume_outlier")
        if id(row) in clustered_ids:
            flags.append("repeat_cluster")
        if id(row) in sweep_ids:
            flags.append("sweep_burst")
            # Preserve explicit vendor execution classes. The inferred burst is
            # still exposed as an anomaly flag and labeled by its own source.
            if row.get("trade_class_source") != "vendor":
                row["trade_class"] = "sweep"
                row["trade_class_source"] = "burst_heuristic"
        row["anomaly_flags"] = flags
        row["anomaly_score"] = round(max(
            0.0,
            premium_score or 0.0,
            volume_score or 0.0,
            3.5 if id(row) in clustered_ids or id(row) in sweep_ids else 0.0,
        ), 3)
        row["premium_percentile"] = round(_percentile_rank(premiums, premium), 6)
        # Human-readable lean: signed BULL/BEAR when known, else CALL/PUT activity.
        if row.get("bias") == "bullish":
            row["edge_label"] = "BULL"
        elif row.get("bias") == "bearish":
            row["edge_label"] = "BEAR"
        elif row.get("activity_side") == "call":
            row["edge_label"] = "CALL"
        elif row.get("activity_side") == "put":
            row["edge_label"] = "PUT"
        else:
            row["edge_label"] = "—"
        # Aggressor display for UI (never empty dash that looks broken).
        if row.get("aggressor") == "buy":
            row["aggressor_label"] = "BUY"
        elif row.get("aggressor") == "sell":
            row["aggressor_label"] = "SELL"
        else:
            row["aggressor_label"] = "NO SIDE"
        row["volume_percentile"] = round(_percentile_rank(volumes, volume), 6)
    _label_if_classifications(tape)


UNUSUAL_MAX_DTE = 35
UNUSUAL_MIN_OTM = 0.10
MOONSHOT_MAX_PRICE = 2.50
MOONSHOT_MIN_OTM = 0.20
MOMENTUM_REL_VOLUME = 0.50
FLOW_PRESETS = ("unusual", "sweeps", "momentum", "moonshot")
TOP_TICKER_CATEGORIES = (
    "unusual_otm",
    "unusual_volume",
    "unusual_premium",
    "sweeps",
    "momentum",
    "call_premium",
    "put_premium",
)


def print_heat_score(
    *,
    size: float,
    premium: float,
    open_interest: float | None,
    dte: float | None,
    volume: float,
) -> float:
    """Transparent aggression/heat in [0, 100] from published print inputs.

    Monotonic in size and premium when the other arguments stay fixed.
    Smaller open interest versus size, shorter DTE, and larger volume raise heat.
    """
    size_f = max(0.0, float(size or 0.0))
    premium_f = max(0.0, float(premium or 0.0))
    volume_f = max(0.0, float(volume or 0.0))
    size_term = math.log1p(size_f)
    premium_term = math.log1p(premium_f)
    volume_term = math.log1p(volume_f)
    if open_interest is None:
        oi_term = 0.0
    else:
        oi_term = math.log1p(size_f / max(float(open_interest), 1.0))
    if dte is None:
        dte_term = 0.0
    else:
        dte_f = max(0.0, float(dte))
        dte_term = 1.0 / (1.0 + dte_f / float(UNUSUAL_MAX_DTE))
    raw = (
        0.30 * size_term
        + 0.30 * premium_term
        + 0.15 * volume_term
        + 0.15 * oi_term
        + 0.10 * dte_term * math.log1p(100.0)
    )
    return round(100.0 * (1.0 - math.exp(-raw / 6.0)), 4)


def _print_why(row: Mapping[str, Any]) -> list[str]:
    """Human-readable reasons a print was flagged. Empty when nothing unusual."""
    reasons: list[str] = []
    flags = [str(flag) for flag in (row.get("anomaly_flags") or ())]
    dte = row.get("dte")
    otm = row.get("otm_pct")
    if row.get("is_unusual"):
        if dte is not None:
            reasons.append(f"{int(float(dte))}d expiry")
        if otm is not None:
            reasons.append(f"{float(otm) * 100:.0f}% OTM")
    if row.get("is_sweep") or "sweep_burst" in flags:
        source = str(row.get("trade_class_source") or "")
        reasons.append("vendor sweep" if source == "vendor" else "burst sweep ≤3s")
    if "premium_outlier" in flags:
        pct = row.get("premium_percentile")
        if isinstance(pct, (int, float)):
            reasons.append(f"premium {float(pct) * 100:.0f}th pct")
        else:
            reasons.append("premium outlier")
    if "volume_outlier" in flags:
        pct = row.get("volume_percentile")
        if isinstance(pct, (int, float)):
            reasons.append(f"size {float(pct) * 100:.0f}th pct")
        else:
            reasons.append("size outlier")
    if "repeat_cluster" in flags:
        reasons.append("repeat cluster same contract")
    rel = row.get("relative_volume")
    if row.get("is_momentum") and isinstance(rel, (int, float)) and rel > 0:
        reasons.append(f"{float(rel):.1f}x OI")
    elif row.get("is_momentum"):
        reasons.append("high tape-relative volume")
    if row.get("is_moonshot"):
        reasons.append("cheap far-OTM")
    if row.get("is_top_position"):
        reasons.append("size > open interest")
    return reasons


def _underlying_from_row(row: Mapping[str, Any]) -> str | None:
    for key in ("underlying", "underlying_symbol", "root_symbol", "symbol"):
        value = str(row.get(key) or "").strip().upper()
        if value.startswith("EQ."):
            value = value[3:]
        if value.endswith(".US"):
            value = value[:-3]
        if value and not any(ch.isdigit() for ch in value):
            return value
    return None


def _label_if_classifications(tape: list[dict[str, Any]]) -> None:
    """Tag Unusual / sweep / block / top-position / heat / IF presets in place."""
    volumes = [float(row.get("volume") or 0.0) for row in tape]
    for row in tape:
        dte = row.get("dte")
        otm = row.get("otm_pct")
        contracts = int(row.get("contracts") or row.get("volume") or 0)
        oi = row.get("open_interest")
        price = row.get("price")
        trade_class = str(row.get("trade_class") or "").strip().lower()
        is_unusual = (
            dte is not None
            and otm is not None
            and float(dte) <= UNUSUAL_MAX_DTE
            and float(otm) >= UNUSUAL_MIN_OTM
        )
        is_sweep = trade_class == "sweep"
        is_block = trade_class == "block"
        is_top_position = oi is not None and contracts > int(oi)
        if oi is not None:
            is_momentum = (contracts / max(float(oi), 1.0)) >= MOMENTUM_REL_VOLUME
        elif len(tape) >= 4:
            is_momentum = _percentile_rank(volumes, float(row.get("volume") or 0.0)) >= 0.75
        else:
            is_momentum = False
        is_moonshot = (
            price is not None
            and float(price) <= MOONSHOT_MAX_PRICE
            and otm is not None
            and float(otm) >= MOONSHOT_MIN_OTM
        )
        presets = [
            name
            for name, flag in (
                ("unusual", is_unusual),
                ("sweeps", is_sweep),
                ("momentum", is_momentum),
                ("moonshot", is_moonshot),
            )
            if flag
        ]
        row["is_unusual"] = is_unusual
        row["is_sweep"] = is_sweep
        row["is_block"] = is_block
        row["is_top_position"] = is_top_position
        row["is_momentum"] = is_momentum
        row["is_moonshot"] = is_moonshot
        row["presets"] = presets
        row["relative_volume"] = (
            round(contracts / max(float(oi), 1.0), 6) if oi is not None else None
        )
        row["heat"] = print_heat_score(
            size=float(contracts),
            premium=float(row.get("premium") or 0.0),
            open_interest=float(oi) if oi is not None else None,
            dte=float(dte) if dte is not None else None,
            volume=float(row.get("volume") or contracts),
        )
        row["why"] = _print_why(row)


def classify_options_tape(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback_spot: float | None = None,
) -> list[dict[str, Any]]:
    """Normalize, annotate anomalies, and apply IF labels. Public test/API entry."""
    tape: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in rows:
        row = _normalize_flow_row(raw, fallback_spot=fallback_spot)
        if row is None:
            continue
        symbol = _underlying_from_row(raw)
        if symbol:
            row["symbol"] = symbol
        identity = (
            row["timestamp"], row["right"], row["strike"], row["expiry"],
            round(row["premium"], 2), row["volume"], row["aggressor"], row.get("symbol"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        tape.append(row)
    _annotate_tape_anomalies(tape)
    return tape


def filter_tape_preset(tape: Sequence[Mapping[str, Any]], preset: str) -> list[dict[str, Any]]:
    key = str(preset or "").strip().lower()
    if key in {"", "all"}:
        return [dict(row) for row in tape]
    return [dict(row) for row in tape if key in (row.get("presets") or ())]


def _ticker_direction_share(prints: Sequence[Mapping[str, Any]]) -> tuple[float | None, float | None, str]:
    signed = [row for row in prints if row.get("signed_premium") is not None]
    if signed:
        bull = sum(float(row["signed_premium"]) for row in signed if float(row["signed_premium"]) > 0)
        bear = sum(-float(row["signed_premium"]) for row in signed if float(row["signed_premium"]) < 0)
        classified = bull + bear
        basis = "signed_premium"
        if classified <= 0:
            return None, None, basis
        return round(bull / classified, 6), round(bear / classified, 6), basis
    call_prem = sum(float(row["premium"]) for row in prints if row.get("right") == "call")
    put_prem = sum(float(row["premium"]) for row in prints if row.get("right") == "put")
    classified = call_prem + put_prem
    if classified <= 0:
        return None, None, "call_put_premium"
    # Call/put premium mix is identity share, not bull/bear.
    return round(call_prem / classified, 6), round(put_prem / classified, 6), "call_put_premium"


def build_options_top_tickers(tape: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rank underliers on Unusual OTM/volume/premium, sweeps, momentum, call/put premium."""
    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for row in tape:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(row)

    tickers: list[dict[str, Any]] = []
    for symbol, prints in by_symbol.items():
        unusual = [row for row in prints if row.get("is_unusual")]
        sweeps = [row for row in prints if row.get("is_sweep")]
        momentum = [row for row in prints if row.get("is_momentum") or "momentum" in (row.get("presets") or ())]
        bull, bear, basis = _ticker_direction_share(prints)
        signed_basis = basis == "signed_premium"
        call_share = None if signed_basis else bull
        put_share = None if signed_basis else bear
        bullish_share = bull if signed_basis else None
        bearish_share = bear if signed_basis else None
        metrics = {
            "unusual_otm": (
                sum(float(row.get("otm_pct") or 0.0) * float(row.get("premium") or 0.0) for row in unusual)
                / sum(float(row.get("premium") or 0.0) for row in unusual)
                if unusual and sum(float(row.get("premium") or 0.0) for row in unusual) > 0
                else 0.0
            ),
            "unusual_volume": float(sum(int(row.get("contracts") or row.get("volume") or 0) for row in unusual)),
            "unusual_premium": sum(float(row.get("premium") or 0.0) for row in unusual),
            "sweeps": sum(float(row.get("premium") or 0.0) for row in sweeps),
            "momentum": sum(float(row.get("premium") or 0.0) for row in momentum),
            "call_premium": sum(float(row.get("premium") or 0.0) for row in prints if row.get("right") == "call"),
            "put_premium": sum(float(row.get("premium") or 0.0) for row in prints if row.get("right") == "put"),
        }
        tickers.append({
            "symbol": symbol,
            "bullish_share": bullish_share,
            "bearish_share": bearish_share,
            "call_share": call_share,
            "put_share": put_share,
            "share_basis": basis,
            "print_count": len(prints),
            "metrics": metrics,
        })

    categories: dict[str, list[dict[str, Any]]] = {}
    for name in TOP_TICKER_CATEGORIES:
        ranked = sorted(tickers, key=lambda row: (-float(row["metrics"][name]), row["symbol"]))
        categories[name] = [
            {
                "symbol": row["symbol"],
                "score": round(float(row["metrics"][name]), 6),
                "bullish_share": row["bullish_share"],
                "bearish_share": row["bearish_share"],
                "call_share": row.get("call_share"),
                "put_share": row.get("put_share"),
                "share_basis": row["share_basis"],
                "print_count": row["print_count"],
            }
            for row in ranked
            if float(row["metrics"][name]) > 0
        ]
    return {
        "categories": categories,
        "tickers": tickers,
        "category_labels": {
            "unusual_otm": "Unusual OTM",
            "unusual_volume": "Unusual Volume",
            "unusual_premium": "Unusual Premium",
            "sweeps": "Sweeps",
            "momentum": "Momentum",
            "call_premium": "Call Premium",
            "put_premium": "Put Premium",
        },
    }


def _aggregate_sweep_bursts(tape_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse same-contract sweep-burst fills into one aggregate row per burst.

    The LSE live flow emits each exchange fill as a separate row.  When
    ``_annotate_tape_anomalies`` tags fills from the same ≤3-second burst as
    ``sweep_burst``, the tape shows multiple low-contract rows rather than one
    recognisable sweep.  This collapses them so the tape looks like the
    standard ``SWEEP 1,063 @ ~$5.22`` display that users expect from platforms
    that aggregate exchange fills into order-level rows.

    Aggregation key: ``(right, strike, expiry_str)`` within the same burst.
    A "burst" here is a consecutive run of rows with ``sweep_burst`` in their
    ``anomaly_flags`` for that key, all within 10 seconds of the earliest print.

    The aggregate row uses:
    - ``timestamp``: earliest fill timestamp (datetime or isoformat string)
    - ``premium``: sum of all fills
    - ``contracts`` / ``volume``: sum of all fills
    - ``price``: premium-weighted average fill price (marked with ``price_estimated=True``)
    - ``sweep_fill_count``: number of fills merged (new field)
    - ``sweep_fills``: list of individual fill dicts (new field, for drill-down)
    - All other fields: copied from the fill with the highest premium
    """
    if not tape_rows:
        return tape_rows

    # Work in reverse-chronological order (already sorted that way by caller)
    # but process in chronological order for burst detection.
    chrono = sorted(tape_rows, key=lambda r: str(r.get("timestamp") or ""))

    # Group consecutive sweep_burst fills by contract identity.
    BURST_WINDOW_S = 10.0
    result_chrono: list[dict[str, Any]] = []
    consumed: set[int] = set()

    for i, row in enumerate(chrono):
        if id(row) in consumed:
            continue
        if "sweep_burst" not in (row.get("anomaly_flags") or []):
            result_chrono.append(row)
            continue

        # This row starts a potential burst group.
        key = (row.get("right"), row.get("strike"), str(row.get("expiry") or ""))
        burst_rows = [row]
        consumed.add(id(row))

        # Determine anchor timestamp for window calculation.
        ts0_raw = row.get("timestamp")
        try:
            ts0 = (
                ts0_raw if isinstance(ts0_raw, datetime)
                else datetime.fromisoformat(str(ts0_raw).replace("Z", "+00:00"))
            )
        except (ValueError, AttributeError):
            ts0 = None

        # Collect subsequent rows within the burst window.
        for j in range(i + 1, len(chrono)):
            other = chrono[j]
            if id(other) in consumed:
                continue
            if "sweep_burst" not in (other.get("anomaly_flags") or []):
                continue
            other_key = (other.get("right"), other.get("strike"), str(other.get("expiry") or ""))
            if other_key != key:
                continue
            if ts0 is not None:
                ts_raw = other.get("timestamp")
                try:
                    ts_other = (
                        ts_raw if isinstance(ts_raw, datetime)
                        else datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    )
                    gap = abs((ts_other - ts0).total_seconds())
                except (ValueError, AttributeError):
                    gap = 0.0
                if gap > BURST_WINDOW_S:
                    continue
            burst_rows.append(other)
            consumed.add(id(other))

        if len(burst_rows) == 1:
            # Only one fill in this "burst" — emit as-is without aggregation.
            result_chrono.append(burst_rows[0])
            continue

        # Aggregate the burst into one representative row.
        anchor = max(burst_rows, key=lambda r: float(r.get("premium") or 0.0))
        total_contracts = sum(int(r.get("contracts") or r.get("volume") or 0) for r in burst_rows)
        total_premium = sum(float(r.get("premium") or 0.0) for r in burst_rows)
        wt_price: float | None = None
        wt_num = sum(
            float(r.get("price") or 0.0) * int(r.get("contracts") or r.get("volume") or 0)
            for r in burst_rows
            if r.get("price") is not None
        )
        if total_contracts > 0 and wt_num > 0:
            wt_price = wt_num / total_contracts

        # Build the aggregate fill list (preserve order, convert timestamps).
        def _fill_snapshot(r: dict[str, Any]) -> dict[str, Any]:
            out = {
                "timestamp": r["timestamp"] if isinstance(r["timestamp"], str)
                             else r["timestamp"].isoformat(),
                "contracts": int(r.get("contracts") or r.get("volume") or 0),
                "price": round(float(r.get("price") or 0.0), 4) if r.get("price") is not None else None,
                "premium": round(float(r.get("premium") or 0.0), 2),
                "anomaly_flags": list(r.get("anomaly_flags") or []),
            }
            return out

        # Use the earliest timestamp as the sweep's reported time.
        earliest_ts = min(
            burst_rows,
            key=lambda r: str(r.get("timestamp") or ""),
        ).get("timestamp")

        agg = dict(anchor)
        agg["timestamp"] = earliest_ts  # chronologically first fill
        agg["contracts"] = total_contracts
        agg["volume"] = total_contracts
        agg["premium"] = round(total_premium, 2)
        agg["price"] = round(wt_price, 4) if wt_price is not None else None
        agg["price_estimated"] = True  # weighted average, not a single fill price
        agg["is_sweep"] = True
        agg["trade_class"] = "sweep"
        agg["trade_class_source"] = "burst_aggregate"
        # Merge anomaly flags from all fills (union, deduplicated).
        all_flags: list[str] = []
        seen_flags: set[str] = set()
        for flag in (anchor.get("anomaly_flags") or []):
            if flag not in seen_flags:
                all_flags.append(flag)
                seen_flags.add(flag)
        for r in burst_rows:
            for flag in (r.get("anomaly_flags") or []):
                if flag not in seen_flags:
                    all_flags.append(flag)
                    seen_flags.add(flag)
        agg["anomaly_flags"] = all_flags
        agg["sweep_fill_count"] = len(burst_rows)
        agg["sweep_fills"] = [_fill_snapshot(r) for r in burst_rows]
        # Recompute heat score for the combined order size
        oi = agg.get("open_interest")
        agg["heat"] = print_heat_score(
            size=float(total_contracts),
            premium=float(total_premium),
            open_interest=float(oi) if oi is not None else None,
            dte=float(agg.get("dte")) if agg.get("dte") is not None else None,
            volume=float(total_contracts),
        )
        if oi is not None and float(oi) > 0:
            agg["relative_volume"] = round(total_contracts / float(oi), 2)
        # Why tag: combine aggregate summary with underlying fill reasons.
        fill_word = "fill" if len(burst_rows) == 1 else "fills"
        why_list: list[str] = [f"sweep {len(burst_rows)} {fill_word} ≤{int(BURST_WINDOW_S)}s · burst aggregate"]
        seen_why = set(why_list)
        for r in burst_rows:
            for w in (r.get("why") or []):
                if w not in seen_why:
                    why_list.append(w)
                    seen_why.add(w)
        agg["why"] = why_list
        result_chrono.append(agg)

    # Restore reverse-chronological order expected by callers.
    result_chrono.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    return result_chrono


#: Side-inference weights. A vendor-reported aggressor is the real thing; the
#: quote rule against a live two-sided quote is the standard Lee-Ready read;
#: the same rule against a same-day delayed reference quote is a hint; the
#: tick test (price vs the previous print on the same contract, Lee-Ready's
#: own fallback when no quote is available) is the weakest but still observed.
PRESSURE_SIDE_WEIGHTS = {
    "vendor": 1.0, "quote_rule_live": 0.8, "quote_rule_delayed": 0.5, "tick_rule": 0.4,
}


def _tick_rule_sides(tape_rows: Sequence[dict[str, Any]]) -> None:
    """Sign still-unresolved prints by the tick test, per contract, in place.

    Chronologically per (right, strike, expiry): an uptick vs the previous
    print's price is a buy, a downtick a sell, a zero tick inherits the last
    non-zero tick's direction, and the first print (or a run of zero ticks
    with no prior direction) stays unresolved. Estimated prices (premium ÷
    contracts) never participate. Only rows with no side yet are written.
    """
    by_contract: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in tape_rows:
        if row.get("price_estimated") or _number(row.get("price")) is None:
            continue
        key = (row.get("right"), row.get("strike"), str(row.get("expiry") or ""))
        by_contract.setdefault(key, []).append(row)
    for rows in by_contract.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: str(r.get("timestamp") or ""))
        last_price: float | None = None
        last_dir: str | None = None
        for row in rows:
            price = float(row["price"])
            if last_price is not None:
                if price > last_price:
                    tick = "buy"
                elif price < last_price:
                    tick = "sell"
                else:
                    tick = last_dir
                if tick and not row.get("side_source"):
                    row["inferred_side"] = tick
                    row["side_source"] = "tick_rule"
                    row["side_weight"] = PRESSURE_SIDE_WEIGHTS["tick_rule"]
                    direction = _flow_direction(row.get("right"), tick)
                    row["flow_direction"] = direction
                    row["flow_signed_premium"] = (
                        round(direction * float(row["premium"]), 2) if direction else None
                    )
                if tick:
                    last_dir = tick
            last_price = price


def _infer_print_side(
    row: Mapping[str, Any], quote: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, float]:
    """(side, source, weight) for one print: who was the aggressor?

    Precedence:
      1. explicit vendor aggressor on the print (``aggressor`` = buy/sell);
      2. quote rule against the matched chain contract: a live two-sided quote
         classifies by position inside the spread (upper 40% = lifted the ask,
         lower 40% = hit the bid, the middle 20% stays unresolved);
      3. the same rule on a delayed reference quote only counts prints AT or
         THROUGH the touch, because a 15-minute-old spread cannot place a
         print inside itself honestly.

    Returns ``(None, None, 0.0)`` when nothing resolves. Estimated prices
    (premium ÷ contracts) are never compared against a quote.
    """
    aggressor = row.get("aggressor")
    if aggressor in {"buy", "sell"}:
        return aggressor, "vendor", PRESSURE_SIDE_WEIGHTS["vendor"]
    if not quote or row.get("price_estimated"):
        return None, None, 0.0
    price = _number(row.get("price"))
    bid = _number(quote.get("bid"))
    ask = _number(quote.get("ask"))
    if price is None or bid is None or ask is None or bid < 0 or ask <= bid:
        return None, None, 0.0
    position = (price - bid) / (ask - bid)
    if quote.get("quote_live"):
        if position >= 0.6:
            return "buy", "quote_rule_live", PRESSURE_SIDE_WEIGHTS["quote_rule_live"]
        if position <= 0.4:
            return "sell", "quote_rule_live", PRESSURE_SIDE_WEIGHTS["quote_rule_live"]
        return None, None, 0.0
    # A delayed reference quote must come from the print's own session day; an
    # 11-day-old snapshot says nothing about where today's spread was.
    quote_ts = quote.get("observed_at")
    print_ts = row.get("timestamp")
    if not isinstance(quote_ts, datetime) or not isinstance(print_ts, datetime):
        return None, None, 0.0
    if quote_ts.date() != print_ts.date():
        return None, None, 0.0
    if position >= 0.999:
        return "buy", "quote_rule_delayed", PRESSURE_SIDE_WEIGHTS["quote_rule_delayed"]
    if position <= 0.001:
        return "sell", "quote_rule_delayed", PRESSURE_SIDE_WEIGHTS["quote_rule_delayed"]
    return None, None, 0.0


def _flow_direction(right: Any, side: str | None) -> int | None:
    """Underlying direction implied by an options print: buy call / sell put
    → +1 (buying), buy put / sell call → −1 (selling)."""
    if side == "buy":
        return 1 if right == "call" else -1
    if side == "sell":
        return -1 if right == "call" else 1
    return None


def _tape_channel_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate side-resolved prints into one buyer/seller imbalance input.

    ``signed_premium`` and ``gross_premium`` are side-weight adjusted, so a
    delayed-quote print moves the needle half as much as a vendor-signed one.
    ``resolved_premium`` / ``total_premium`` is the unweighted coverage: how
    much of the tape actually had a side.
    """
    mix = {"vendor": 0, "quote_rule_live": 0, "quote_rule_delayed": 0, "tick_rule": 0, "unresolved": 0}
    signed = gross = resolved = total = buy = sell = 0.0
    n_signed = 0
    for row in rows:
        premium = float(row.get("premium") or 0.0)
        total += premium
        source = row.get("side_source")
        direction = row.get("flow_direction")
        if not source or not direction:
            mix["unresolved"] += 1
            continue
        mix[source] = mix.get(source, 0) + 1
        n_signed += 1
        weight = float(row.get("side_weight") or 0.0)
        signed += direction * premium * weight
        gross += premium * weight
        resolved += premium
        if direction > 0:
            buy += premium * weight
        else:
            sell += premium * weight
    return {
        "signed_premium": round(signed, 2),
        "gross_premium": round(gross, 2),
        "resolved_premium": round(resolved, 2),
        "total_premium": round(total, 2),
        "n_signed": n_signed,
        "n_total": len(rows),
        "source_mix": mix,
        "buy_premium": round(buy, 2),
        "sell_premium": round(sell, 2),
    }


def _flow_series(
    flow_rows: Sequence[Mapping[str, Any]],
    *,
    filters: OptionsFilters,
    asof: datetime,
    selected_expiry: str | None,
    mode_requested: str = "live",
    spot: float | None = None,
    chain_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[float], list[float], dict[str, Any],
]:
    lower, upper = _flow_date_bounds(filters, asof, mode_requested=mode_requested)
    normalized: list[dict[str, Any]] = []
    rejected: dict[str, Any] = {
        "invalid": 0,
        "below_premium": 0,
        "below_volume": 0,
        "outside_range": 0,
        "outside_expiry": 0,
        "window_lower": lower.isoformat(),
        "window_upper": upper.isoformat(),
        "window_relaxed": False,
        "print_ts_min": None,
        "print_ts_max": None,
    }
    seen: set[tuple[Any, ...]] = set()
    for raw in flow_rows:
        row = _normalize_flow_row(raw, fallback_spot=spot)
        if row is None:
            rejected["invalid"] += 1
            continue
        identity = (
            row["timestamp"], row["right"], row["strike"], row["expiry"],
            round(row["premium"], 2), row["volume"], row["aggressor"],
        )
        if identity in seen:
            rejected["invalid"] += 1
            continue
        seen.add(identity)
        normalized.append(row)

    if normalized:
        rejected["print_ts_min"] = min(r["timestamp"] for r in normalized).isoformat()
        rejected["print_ts_max"] = max(r["timestamp"] for r in normalized).isoformat()

    def _accept(row: dict[str, Any], lo: datetime, hi: datetime) -> str | None:
        if row["premium"] < filters.min_premium:
            return "below_premium"
        if row["volume"] < filters.min_volume:
            return "below_volume"
        if not lo <= row["timestamp"] <= hi:
            return "outside_range"
        explicit_expiry_filter = selected_expiry if filters.expiry not in ("all", "nearest") else None
        if explicit_expiry_filter and row["expiry"] is not None and row["expiry"].isoformat() != explicit_expiry_filter:
            return "outside_expiry"
        return None

    tape_rows: list[dict[str, Any]] = []
    for row in normalized:
        reason = _accept(row, lower, upper)
        if reason:
            rejected[reason] += 1
            continue
        tape_rows.append(row)

    # Live recovery: if every liquid print failed only on the calendar window
    # (stale UI date_to / provider clock skew), expand to the print span once.
    if (
        not tape_rows
        and normalized
        and rejected["outside_range"] > 0
        and rejected["below_premium"] == 0
        and rejected["below_volume"] == 0
        and str(mode_requested).lower() == "live"
    ):
        ts_min = min(r["timestamp"] for r in normalized)
        ts_max = max(r["timestamp"] for r in normalized)
        span_days = max(1.0, (ts_max - ts_min).total_seconds() / 86400.0)
        if span_days <= 45:
            lower = ts_min - timedelta(hours=1)
            upper = ts_max + timedelta(hours=1)
            rejected = {
                **rejected,
                "outside_range": 0,
                "outside_expiry": 0,
                "below_premium": 0,
                "below_volume": 0,
                "window_lower": lower.isoformat(),
                "window_upper": upper.isoformat(),
                "window_relaxed": True,
            }
            tape_rows = []
            for row in normalized:
                reason = _accept(row, lower, upper)
                if reason:
                    rejected[reason] += 1
                    continue
                tape_rows.append(row)

    buckets: dict[datetime, dict[str, Any]] = {}
    for row in tape_rows:
        key = _bucket_time(row["timestamp"], filters.range)
        bucket = buckets.setdefault(key, {
            "t": key.isoformat(), "call_premium": 0.0, "put_premium": 0.0,
            "signed_net_premium": 0.0, "signed_premium_observations": 0,
            "signed_gross_premium": 0.0,
            "print_count": 0, "unresolved_premium": 0.0,
        })
        bucket[f"{row['right']}_premium"] += row["premium"]
        bucket["print_count"] += 1
        if row["signed_premium"] is None:
            bucket["unresolved_premium"] += row["premium"]
        else:
            bucket["signed_net_premium"] += row["signed_premium"]
            bucket["signed_gross_premium"] += abs(float(row["signed_premium"]))
            bucket["signed_premium_observations"] += 1

    series = []
    for bucket in sorted(buckets.values(), key=lambda value: value["t"]):
        total = bucket["call_premium"] + bucket["put_premium"]
        bucket["activity_imbalance"] = (
            (bucket["call_premium"] - bucket["put_premium"]) / total if total > 0 else None
        )
        if bucket["signed_premium_observations"] == 0:
            bucket["signed_net_premium"] = None
        series.append(bucket)

    # Enrich tape rows with Open Interest and Implied Volatility from the chain
    # before running anomaly annotation so relative volume (Vol/OI) and the
    # 0-100 heat score can be computed accurately from genuine contract OI.
    # The same contract match supplies the bid/ask the quote rule needs to
    # infer which side of the market each print hit.
    chain_by_key: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    chain_by_occ: dict[str, Mapping[str, Any]] = {}
    for cr in chain_rows:
        norm_c = _normalize_chain_row(cr, asof=asof, spot=spot or 0.0)
        c_right = norm_c.get("right")
        c_strike = norm_c.get("strike")
        c_exp = norm_c.get("expiry")
        if c_right and c_strike is not None and c_exp:
            exp_str = c_exp.isoformat() if hasattr(c_exp, "isoformat") else str(c_exp)
            chain_by_key[(c_right, round(float(c_strike), 4), exp_str)] = norm_c
        occ = norm_c.get("occ_symbol")
        if occ:
            chain_by_occ[str(occ).upper().strip()] = norm_c

    for row in tape_rows:
        matched = None
        occ = row.get("occ_symbol")
        if occ and str(occ).upper().strip() in chain_by_occ:
            matched = chain_by_occ[str(occ).upper().strip()]
        elif row.get("right") and row.get("strike") is not None and row.get("expiry"):
            exp_str = row["expiry"].isoformat() if hasattr(row["expiry"], "isoformat") else str(row["expiry"])
            matched = chain_by_key.get((row["right"], round(float(row["strike"]), 4), exp_str))
        if matched:
            if (row.get("open_interest") is None or row.get("open_interest") == 0) and matched.get("open_interest"):
                row["open_interest"] = matched["open_interest"]
            if row.get("implied_volatility") is None and matched.get("iv"):
                row["implied_volatility"] = matched["iv"]
        side, side_source, side_weight = _infer_print_side(row, matched)
        direction = _flow_direction(row.get("right"), side)
        row["inferred_side"] = side
        row["side_source"] = side_source
        row["side_weight"] = side_weight
        row["flow_direction"] = direction
        row["flow_signed_premium"] = (
            round(direction * float(row["premium"]), 2) if direction else None
        )
    # Whatever the quote rule could not place gets the tick test against the
    # previous print on the same contract (the only side evidence a quoteless
    # live chain leaves us), at the lowest weight.
    _tick_rule_sides(tape_rows)
    # Buyer/seller imbalance on the underlying, measured on the raw fills
    # before sweep-burst aggregation changes the row count.
    tape_channel = _tape_channel_from_rows(tape_rows)

    _annotate_tape_anomalies(tape_rows)
    series_by_time = {row["t"]: row for row in series}
    for row in tape_rows:
        if not row["anomaly_flags"]:
            continue
        bucket = series_by_time.get(_bucket_time(row["timestamp"], filters.range).isoformat())
        if bucket is not None:
            bucket["anomaly_count"] = bucket.get("anomaly_count", 0) + 1
            bucket["anomaly_premium"] = bucket.get("anomaly_premium", 0.0) + row["premium"]
    for bucket in series:
        bucket.setdefault("anomaly_count", 0)
        bucket.setdefault("anomaly_premium", 0.0)

    tape_rows.sort(key=lambda row: row["timestamp"], reverse=True)
    chronological = sorted(tape_rows, key=lambda row: row["timestamp"])
    signed_observations = [
        float(row["signed_premium"])
        for row in chronological
        if row.get("signed_premium") is not None
    ]
    # Call + / put − is contract-activity persistence, not buy/sell direction.
    activity_observations = [
        float(row["premium"]) if row.get("right") == "call" else -float(row["premium"])
        for row in chronological
        if row.get("right") in {"call", "put"} and row.get("premium") is not None
    ]
    # Collapse same-contract sweep-burst fills into one aggregate row per burst.
    # Done after signed/activity extraction so the financial signals (which use
    # raw fill timestamps) are not affected by the display-level grouping.
    tape_rows = _aggregate_sweep_bursts(tape_rows)
    for row in tape_rows:
        ts = row["timestamp"]
        row["timestamp"] = ts if isinstance(ts, str) else ts.isoformat()
        exp = row.get("expiry")
        if exp is not None and not isinstance(exp, str):
            row["expiry"] = exp.isoformat()
    return (
        series, tape_rows[: filters.tape_limit], rejected, signed_observations,
        activity_observations, tape_channel,
    )



def _chain_activity_series(
    rows: Sequence[Mapping[str, Any]], *, filters: OptionsFilters, asof: datetime,
) -> list[dict[str, Any]]:
    """Fallback activity from daily cumulative chain volume, never signed flow."""
    lower, upper = _date_bounds(filters, asof)
    buckets: dict[datetime, dict[str, Any]] = {}
    for raw in rows:
        observed = _timestamp(_first(
            raw, "captured_utc", "asof_utc", "asof_date", "timestamp", "last_trade_asof_utc",
        ))
        right = _right(_first(raw, "right", "contract_type", "option_type", "type"))
        volume = _integer(_first(raw, "volume", "volume_today")) or 0
        bid, ask = _number(raw.get("bid")), _number(raw.get("ask"))
        last = _number(_first(raw, "last_price", "lastPrice", "price"))
        mid = (bid + ask) / 2.0 if bid is not None and ask is not None and ask >= bid >= 0 else last
        premium = _number(_first(raw, "premium_today", "session_premium"))
        if premium is None and mid:
            premium = mid * volume * 100.0
        if not observed or not right or premium is None or volume < filters.min_volume or not lower <= observed <= upper:
            continue
        if premium < filters.min_premium:
            continue
        key = _bucket_time(observed, "1m")
        bucket = buckets.setdefault(key, {
            "t": key.isoformat(), "call_premium": 0.0, "put_premium": 0.0,
            "signed_net_premium": None, "signed_premium_observations": 0,
            "signed_gross_premium": 0.0,
            "print_count": 0, "unresolved_premium": 0.0,
        })
        bucket[f"{right}_premium"] += premium
        bucket["unresolved_premium"] += premium
        bucket["print_count"] += 1
    result = []
    for bucket in sorted(buckets.values(), key=lambda value: value["t"]):
        total = bucket["call_premium"] + bucket["put_premium"]
        bucket["activity_imbalance"] = (
            (bucket["call_premium"] - bucket["put_premium"]) / total if total > 0 else None
        )
        bucket["anomaly_count"] = 0
        bucket["anomaly_premium"] = 0.0
        result.append(bucket)
    return result


def _gex_map(
    rows: Sequence[Mapping[str, Any]], *, spot: float, asof: datetime, rate: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build strike GEX, summary levels, gamma source counts, by-expiry totals, and price profile.

    Wall convention (InsiderFinance / SpotGamma):
      - Call wall = max call GEX *above* spot (resistance)
      - Put wall  = max put GEX *below* spot (support; most-negative put_gex)
    Global argmax/argmin can pin both walls on the same ATM strike when that
    strike carries both large call and put mass — which is not how the desk
    or IF read walls.
    """
    from edge.daily_plays.gex_core import directional_walls

    by_strike: dict[float, dict[str, float]] = {}
    by_expiry: dict[date, dict[str, float]] = {}
    gamma_source = {"provider": 0, "black_scholes": 0, "unavailable": 0}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        strike = _number(row.get("strike"))
        dte = _integer(row.get("dte"))
        iv = _number(row.get("iv"))
        gamma = _number(row.get("gamma"))
        source = "provider"
        years = max(float(dte or 0), 0.5) / 365.0
        if gamma is None or gamma <= 0:
            gamma = _bs_gamma(spot=spot, strike=strike or 0, years=years, iv=iv or 0, rate=rate)
            source = "black_scholes"
        right = row.get("right")
        if not strike or gamma is None or right not in {"call", "put"}:
            gamma_source["unavailable"] += 1
            continue
        gamma_source[source] += 1
        oi = _integer(row.get("open_interest")) or 0
        multiplier = _integer(row.get("multiplier")) or 100
        sign = 1.0 if right == "call" else -1.0
        exposure = sign * gamma * oi * multiplier * spot * spot * 0.01 / 1_000_000.0
        cell = by_strike.setdefault(strike, {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0.0, "put_oi": 0.0})
        cell[f"{right}_gex"] += exposure
        cell[f"{right}_oi"] += oi
        expiry = row.get("expiry")
        if isinstance(expiry, date):
            exp_cell = by_expiry.setdefault(
                expiry, {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0.0, "put_oi": 0.0, "contracts": 0.0},
            )
            exp_cell[f"{right}_gex"] += exposure
            exp_cell[f"{right}_oi"] += oi
            exp_cell["contracts"] += 1
        enriched.append({
            **row, "iv": iv, "years": years, "sign": sign, "oi": oi,
            "multiplier": multiplier, "strike": strike,
        })

    mapped = []
    for strike, value in sorted(by_strike.items()):
        net = value["call_gex"] + value["put_gex"]
        mapped.append({
            "strike": strike,
            "call_gex_m": round(value["call_gex"], 6),
            "put_gex_m": round(value["put_gex"], 6),
            "net_gex_m": round(net, 6),
            "call_oi": int(value["call_oi"]),
            "put_oi": int(value["put_oi"]),
        })
    raw_call_wall = max(mapped, key=lambda row: row["call_gex_m"], default=None)
    raw_put_wall = min(mapped, key=lambda row: row["put_gex_m"], default=None)
    pin = max(mapped, key=lambda row: abs(row["net_gex_m"]), default=None)
    call_wall_strike, put_wall_strike = directional_walls(
        mapped,
        spot=spot,
        call_wall=raw_call_wall["strike"] if raw_call_wall else None,
        put_wall=raw_put_wall["strike"] if raw_put_wall else None,
    )

    flip: float | None = None
    price_profile: list[dict[str, Any]] = []
    if enriched:
        def _calc_net_gex_at(test_spot: float) -> float:
            tot = 0.0
            for r in enriched:
                gm = _bs_gamma(
                    spot=test_spot, strike=float(r["strike"]), years=float(r["years"]),
                    iv=float(r["iv"] or 0), rate=rate,
                )
                if gm is not None:
                    tot += r["sign"] * gm * r["oi"] * r["multiplier"] * test_spot * test_spot * 0.01
            return tot

        grid: list[tuple[float, float]] = []
        # ±20% in 0.5% steps — standard band used for zero-gamma search; also the
        # IF-style "gamma price profile" (projected net GEX at each test spot).
        for i in range(81):
            test_spot = spot * (0.80 + i * 0.005)
            total = _calc_net_gex_at(test_spot)
            grid.append((test_spot, total))
            price_profile.append({
                "spot": round(test_spot, 4),
                "net_gex_m": round(total / 1_000_000.0, 6),
            })
        crossings: list[float] = []
        for (x0, y0), (x1, y1) in zip(grid, grid[1:]):
            if y0 == 0:
                crossings.append(x0)
            elif y0 * y1 < 0:
                crossings.append(x0 + (x1 - x0) * abs(y0) / (abs(y0) + abs(y1)))

        # If no zero crossing was found in the initial ±20% band, expand the search
        # across the active strikes range so large structural imbalances or high-vol
        # names still locate their hedging boundary.
        if not crossings and enriched:
            strikes = [float(r["strike"]) for r in enriched if r.get("strike") is not None]
            min_k = min(strikes) if strikes else spot * 0.5
            max_k = max(strikes) if strikes else spot * 2.0
            search_lo = max(spot * 0.20, min_k * 0.90)
            search_hi = min(spot * 3.00, max_k * 1.10)
            if search_hi > search_lo:
                extended_steps = 120
                step_size = (search_hi - search_lo) / extended_steps
                ext_grid = []
                for s_i in range(extended_steps + 1):
                    ts = search_lo + s_i * step_size
                    tot = _calc_net_gex_at(ts)
                    ext_grid.append((ts, tot))
                for (x0, y0), (x1, y1) in zip(ext_grid, ext_grid[1:]):
                    if y0 == 0:
                        crossings.append(x0)
                    elif y0 * y1 < 0:
                        crossings.append(x0 + (x1 - x0) * abs(y0) / (abs(y0) + abs(y1)))

        if crossings:
            flip = min(crossings, key=lambda value: abs(value - spot))
            # If the flip sits outside the standard ±20% window, expand price_profile
            # so the zero crossing is visible on the profile chart.
            if price_profile and (flip < price_profile[0]["spot"] or flip > price_profile[-1]["spot"]):
                profile_lo = min(spot * 0.80, flip * 0.95)
                profile_hi = max(spot * 1.20, flip * 1.05)
                price_profile = []
                for s_i in range(81):
                    ts = profile_lo + s_i * ((profile_hi - profile_lo) / 80)
                    tot = _calc_net_gex_at(ts)
                    price_profile.append({
                        "spot": round(ts, 4),
                        "net_gex_m": round(tot / 1_000_000.0, 6),
                    })

    gex_by_expiry = []
    asof_day = asof.date() if isinstance(asof, datetime) else asof
    for expiry, value in sorted(by_expiry.items()):
        net = value["call_gex"] + value["put_gex"]
        gex_by_expiry.append({
            "expiry": expiry.isoformat(),
            "dte": (expiry - asof_day).days if isinstance(asof_day, date) else None,
            "call_gex_m": round(value["call_gex"], 6),
            "put_gex_m": round(value["put_gex"], 6),
            "net_gex_m": round(net, 6),
            "abs_gex_m": round(abs(value["call_gex"]) + abs(value["put_gex"]), 6),
            "call_oi": int(value["call_oi"]),
            "put_oi": int(value["put_oi"]),
            "contracts": int(value["contracts"]),
        })

    total_gex = sum(row["net_gex_m"] for row in mapped)
    call_gex = sum(row["call_gex_m"] for row in mapped)
    put_gex = sum(row["put_gex_m"] for row in mapped)
    call_oi = sum(int(row["call_oi"]) for row in mapped)
    put_oi = sum(int(row["put_oi"]) for row in mapped)
    call_wall_pct = (
        round((call_wall_strike - spot) / spot, 6)
        if call_wall_strike is not None and spot > 0 else None
    )
    put_wall_pct = (
        round((put_wall_strike - spot) / spot, 6)
        if put_wall_strike is not None and spot > 0 else None
    )
    flip_pct = (
        round((flip - spot) / spot, 6) if flip is not None and spot > 0 else None
    )
    summary = {
        "total_gex_m": round(total_gex, 4),
        "call_gex_m": round(call_gex, 4),
        "put_gex_m": round(put_gex, 4),
        "abs_gex_m": round(abs(call_gex) + abs(put_gex), 4),
        "call_oi": call_oi,
        "put_oi": put_oi,
        "regime": "positive" if total_gex > 0 else "negative" if total_gex < 0 else "neutral",
        "gamma_flip": round(flip, 4) if flip is not None else None,
        "gamma_flip_pct": flip_pct,
        "call_wall": call_wall_strike,
        "call_wall_pct": call_wall_pct,
        "put_wall": put_wall_strike,
        "put_wall_pct": put_wall_pct,
        "zero_gamma": round(flip, 4) if flip is not None else None,
        "pin_strike": pin["strike"] if pin else None,
    }
    return mapped, summary, gamma_source, gex_by_expiry, price_profile


def _charm_map(
    rows: Sequence[Mapping[str, Any]], *, spot: float, rate: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Charm flow by strike + chain-level pressure diagnostics.

    Charm = ∂Δ/∂t (delta decay per day). Charm flow = charm × OI × 100, the
    shares/day dealers must trade to stay delta-hedged purely from time decay.
    Same dealer sign convention as GEX: calls positive, puts negative.

    Heuristic (dealer-long-calls / short-puts convention):
      · Net charm flow > 0 → dealer net delta rises over time → dealers sell
        underlying to stay neutral → selling pressure builds.
      · Net charm flow < 0 → dealers buy → buying pressure builds.

    This is a positioning proxy, not observed flow; the payload labels it as
    such. All valid chain contracts are preserved in chain_rows with Black-Scholes
    or provider Greeks so the strike table remains complete.
    """
    by_strike: dict[float, dict[str, float]] = {}
    chain_rows: list[dict[str, Any]] = []
    charm_source = {"black_scholes": 0, "unavailable": 0}
    # Why each contract could not be charmed — surfaced so the UI can say
    # "12 contracts expiring today" instead of a blank chart.
    skipped: dict[str, int] = {
        "malformed_row": 0, "missing_dte": 0, "expiring_within_one_day": 0,
        "missing_or_implausible_iv": 0,
    }
    for row in rows:
        strike = _number(row.get("strike"))
        dte = _integer(row.get("dte"))
        iv = _number(row.get("iv"))
        right = row.get("right")
        if not strike or right not in {"call", "put"}:
            charm_source["unavailable"] += 1
            skipped["malformed_row"] += 1
            continue
        # Display greeks (delta/gamma) are bounded, so a 1-day floor keeps the
        # strike table complete. Charm is NOT bounded that way: at T→0 it scales
        # like τ^-3/2, so a contract with an unknown or same-day expiry priced as
        # 1DTE carried ~60x the weight of a real 30DTE contract and dominated the
        # chain total. Charm therefore uses the honest tenor and declines to
        # answer below the model's documented one-day validity floor.
        greek_years = max(float(dte or 0), 1.0) / 365.0
        charm_years = (float(dte) / 365.0) if dte is not None else None
        if charm_years is None:
            charm = None
            skipped["missing_dte"] += 1
        elif charm_years < 1.0 / 365.0:
            charm = None
            skipped["expiring_within_one_day"] += 1
        else:
            charm = _bs_charm_per_day(
                spot=spot, strike=strike, years=charm_years, iv=iv or 0, rate=rate,
                is_call=(right == "call"),
            )
            if charm is None:
                skipped["missing_or_implausible_iv"] += 1
        oi = _integer(row.get("open_interest")) or 0
        vol = _integer(row.get("volume")) or 0
        multiplier = _integer(row.get("multiplier")) or 100
        sign = 1.0 if right == "call" else -1.0

        # Calculate Delta and Gamma with BS or provider fallback
        bs_delta_val = _bs_delta(spot=spot, strike=strike, years=greek_years, iv=iv or 0, rate=rate, is_call=(right == "call")) if (iv and iv > 0) else None
        delta_val = bs_delta_val if bs_delta_val is not None else _number(row.get("delta"))

        bs_gamma_val = _bs_gamma(spot=spot, strike=strike, years=greek_years, iv=iv or 0, rate=rate) if (iv and iv > 0) else None
        gamma_val = bs_gamma_val if bs_gamma_val is not None else _number(row.get("gamma"))

        if charm is not None:
            charm_source["black_scholes"] += 1
            flow = sign * charm * oi * multiplier
        else:
            charm_source["unavailable"] += 1
            flow = 0.0

        cell = by_strike.setdefault(strike, {"call_flow": 0.0, "put_flow": 0.0, "call_oi": 0.0, "put_oi": 0.0})
        cell[f"{right}_flow"] += flow
        cell[f"{right}_oi"] += oi

        chain_rows.append({
            "strike": strike,
            "right": right,
            "dte": dte,
            "iv": iv,
            "open_interest": oi,
            "volume": vol,
            "delta": delta_val,
            "gamma": gamma_val,
            "charm_per_day": charm,
            "charm_flow": flow,
        })

    mapped = []
    for strike, value in sorted(by_strike.items()):
        net = value["call_flow"] + value["put_flow"]
        mapped.append({
            "strike": strike,
            "call_charm_flow": round(value["call_flow"], 4),
            "put_charm_flow": round(value["put_flow"], 4),
            "net_charm_flow": round(net, 4),
            "call_oi": int(value["call_oi"]),
            "put_oi": int(value["put_oi"]),
        })

    net_charm_flow = sum(row["net_charm_flow"] for row in mapped)
    call_flow = sum(row["call_charm_flow"] for row in mapped)
    put_flow = sum(row["put_charm_flow"] for row in mapped)
    # Gross magnitude must sum the per-strike absolutes. Taking |Σcalls| + |Σputs|
    # let opposite-signed strikes (charm flips sign either side of spot) cancel
    # first, understating gross flow by ~80% on a symmetric chain and making this
    # useless as a normalizer for the pressure gauge.
    abs_flow = sum(
        abs(row["call_charm_flow"]) + abs(row["put_charm_flow"]) for row in mapped
    )
    summary = {
        "net_charm_flow": round(net_charm_flow, 4),
        "call_charm_flow": round(call_flow, 4),
        "put_charm_flow": round(put_flow, 4),
        "abs_charm_flow": round(abs_flow, 4),
        # Contracts that actually produced a charm value; measured + skipped now
        # reconciles to the chain size instead of double counting.
        "contracts_measured": charm_source["black_scholes"],
        "contracts_skipped": charm_source["unavailable"],
        "skipped_reasons": {key: value for key, value in skipped.items() if value},
        "pressure": (
            "selling" if net_charm_flow > 0 else "buying" if net_charm_flow < 0 else "balanced"
        ),
        "source": "black_scholes_charm",
    }
    return mapped, summary, chain_rows


#: Tape channel evidence floors: fewer side-resolved prints than this, or a
#: smaller share of premium with a side, and the channel abstains rather than
#: pretending three prints are an order-flow read.
PRESSURE_TAPE_MIN_PRINTS = 5
PRESSURE_TAPE_MIN_COVERAGE = 0.10
PRESSURE_TAPE_FULL_PRINTS = 20
#: |imbalance| above this reads as a direction; below PRESSURE_NEUTRAL_BAND a
#: channel is treated as neutral when scoring agreement.
PRESSURE_DIRECTION_THRESHOLD = 0.25
PRESSURE_NEUTRAL_BAND = 0.10
PRESSURE_UNDERLYING_BARS = 7


def _underlying_pressure(
    bars: Sequence[Mapping[str, Any]],
    *,
    asof: datetime | None = None,
    n_bars: int = PRESSURE_UNDERLYING_BARS,
    baseline_bars: int = 35,
) -> dict[str, Any] | None:
    """Volume-weighted close-location read of the underlying's last ``n_bars``.

    CLV = ((close − low) − (high − close)) / (high − low) per bar, weighted by
    that bar's volume: closes near the high on volume read as buying, near the
    low as selling. This is a PROXY for signed order flow built from OHLCV
    (there is no tick or quote data for the underlying here), so it is
    labelled as such, carries half a channel's weight, and abstains below
    three usable bars.
    """
    parsed: list[tuple[str, float, float, float, float, float]] = []
    for row in bars or ():
        o = _number(row.get("open") or row.get("o"))
        h = _number(row.get("high") or row.get("h"))
        lo = _number(row.get("low") or row.get("l"))
        c = _number(row.get("close") or row.get("c"))
        v = _number(row.get("volume") or row.get("v"))
        if h is None or lo is None or c is None or h < lo:
            continue
        parsed.append((str(row.get("t") or row.get("timestamp") or ""), o if o is not None else c, h, lo, c, v or 0.0))
    if len(parsed) < 3:
        return None
    window = parsed[-n_bars:]
    numerator = denominator = 0.0
    for _, _, h, lo, c, v in window:
        if v <= 0:
            continue
        clv = ((c - lo) - (h - c)) / (h - lo) if h > lo else 0.0
        numerator += clv * v
        denominator += v
    if denominator <= 0:
        return None
    ratio = max(-1.0, min(1.0, numerator / denominator))
    prior = parsed[-(n_bars + baseline_bars):-n_bars] if len(parsed) > n_bars else []
    prior_vols = [v for *_, v in prior if v > 0]
    rvol = (
        (denominator / len(window)) / (sum(prior_vols) / len(prior_vols))
        if prior_vols else None
    )
    first_open = window[0][1]
    last_close = window[-1][4]
    change_pct = ((last_close / first_open) - 1.0) * 100.0 if first_open and first_open > 0 else None
    timestamps = [_timestamp(t) for t, *_ in window]
    timestamps = [t for t in timestamps if t is not None]
    timeframe = None
    if len(timestamps) >= 2:
        gaps = sorted((b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:]))
        median_gap = gaps[len(gaps) // 2]
        timeframe = "1h" if median_gap < 12 * 3600 else "1d"
    last_ts = timestamps[-1] if timestamps else None
    stale = bool(asof and last_ts and (asof - last_ts).total_seconds() > 3 * 86400)
    return {
        "ratio": round(ratio, 6),
        "rvol": round(rvol, 4) if rvol is not None else None,
        "bars_used": len(window),
        "timeframe": timeframe,
        "close_change_pct": round(change_pct, 4) if change_pct is not None else None,
        "last_bar": last_ts.isoformat() if last_ts else None,
        "stale": stale,
        "method": "clv_volume_proxy",
        "note": (
            "Close-location-value × volume on the underlying's bars. A proxy for "
            "signed order flow built from OHLCV, not tick-level aggressor data."
        ),
    }


def _pressure_gauge(
    *, net_charm_flow: float, net_gex_m: float = 0.0, delta_weighted_call_vol: float = 0.0,
    delta_weighted_put_vol: float = 0.0, abs_charm_flow: float | None = None,
    abs_gex_m: float | None = None, tape: Mapping[str, Any] | None = None,
    underlying: Mapping[str, Any] | None = None, charm_coverage: float | None = None,
    mode_resolved: str = "live", spot_stale: bool = False,
    alpha: float = 1.0, beta: float = 0.5,
) -> dict[str, Any]:
    """Pressure read in [−1, +1] with the confidence to trade on it (or not).

    Only SIGNED evidence votes on direction. Each voting channel is first
    reduced to its own net/gross ratio in [−1, +1], then blended by weight:

        charm      = −NetCharmFlow / GrossCharmFlow        weight 1.0
                     dealer re-hedging from time decay — a positioning proxy
        tape       = Σ dir·premium·w / Σ premium·w         weight 1.0
                     buyer/seller imbalance of side-resolved option prints
                     (buy call / sell put → +, buy put / sell call → −)
        underlying = Σ CLV·volume / Σ volume               weight 0.5
                     close-location proxy on the underlying's own bars
        imbalance  = Σ w·r / Σ w over ACTIVE channels only

    Two inputs the old gauge blended are deliberately context now, not votes:

        call/put mix  (ΔWCall − ΔWPut)/(ΔWCall + ΔWPut) — contract identity,
                      not aggressor side. A bought put and a sold put look
                      identical here, so it cannot say who is pressing.
        GEX sign      NetGEX / GrossGEX — a regime. Positive gamma DAMPENS a
                      move, negative gamma AMPLIFIES it; neither is a direction,
                      and blending it in biased every large cap toward "buying".

    Confidence (0–1, banded) scores how much the read deserves to be acted on:
    weighted sign agreement across active channels (40%), evidence quality and
    breadth (25%), magnitude (15%) and data freshness (20%). A single channel
    can never corroborate itself, so a charm-only read is capped at "low";
    history/delayed data is capped at "medium" and never actionable.

    ``actionable`` is the one flag a live trader should key off: |imbalance|
    beyond the direction threshold, medium-or-better confidence, live data and
    no channel of full weight reading the opposite way.

    The charm term is negated so the gauge agrees with the §5.5 dealer hedge
    convention: positive net charm flow → dealers sell → selling pressure.
    """
    eps = 1e-9
    gross_charm = abs(abs_charm_flow) if abs_charm_flow is not None else abs(net_charm_flow)
    gross_gex = abs(abs_gex_m) if abs_gex_m is not None else abs(net_gex_m)
    gross_vol = delta_weighted_call_vol + delta_weighted_put_vol

    def _ratio(net: float, gross: float) -> float | None:
        """Signed share of a channel's gross magnitude, or None when it has none."""
        if gross <= eps:
            return None
        return max(-1.0, min(1.0, net / gross))

    def _sign(value: float) -> int:
        if value >= PRESSURE_NEUTRAL_BAND:
            return 1
        if value <= -PRESSURE_NEUTRAL_BAND:
            return -1
        return 0

    reasons: list[str] = []
    # (name, weight, ratio, evidence quality in [0, 1])
    channels: list[tuple[str, float, float, float]] = []

    charm_ratio = _ratio(-net_charm_flow, gross_charm)
    if charm_ratio is not None:
        charm_quality = _clamp01(charm_coverage) if charm_coverage is not None else 1.0
        channels.append(("charm", 1.0, charm_ratio, charm_quality))
        if charm_coverage is not None and charm_coverage < 0.5:
            reasons.append(f"charm: only {charm_coverage:.0%} of the chain could be charmed")
    else:
        reasons.append("charm: no measurable charm flow on this chain")

    tape_ratio: float | None = None
    tape_out: dict[str, Any] | None = None
    if tape:
        n_signed = int(tape.get("n_signed") or 0)
        n_total = int(tape.get("n_total") or 0)
        gross_tape = float(tape.get("gross_premium") or 0.0)
        resolved = float(tape.get("resolved_premium") or 0.0)
        total = float(tape.get("total_premium") or 0.0)
        coverage = resolved / total if total > eps else 0.0
        quality = _clamp01(gross_tape / resolved) if resolved > eps else 0.0
        raw_ratio = _ratio(float(tape.get("signed_premium") or 0.0), gross_tape)
        tape_out = {
            **dict(tape),
            "coverage": round(coverage, 6),
            "quality": round(quality, 6),
            "ratio": None if raw_ratio is None else round(raw_ratio, 6),
            "min_prints": PRESSURE_TAPE_MIN_PRINTS,
            "min_coverage": PRESSURE_TAPE_MIN_COVERAGE,
        }
        if n_total == 0:
            reasons.append("tape: no prints in the window")
        elif raw_ratio is None or n_signed < PRESSURE_TAPE_MIN_PRINTS or coverage < PRESSURE_TAPE_MIN_COVERAGE:
            reasons.append(
                f"tape: {n_signed} of {n_total} prints side-resolved ({coverage:.0%} of premium) — "
                f"below the {PRESSURE_TAPE_MIN_PRINTS}-print / {PRESSURE_TAPE_MIN_COVERAGE:.0%} floor, so it abstains"
            )
        else:
            tape_ratio = raw_ratio
            evidence = min(1.0, n_signed / PRESSURE_TAPE_FULL_PRINTS) * math.sqrt(coverage) * quality
            channels.append(("tape", 1.0, tape_ratio, evidence))
            mix = tape.get("source_mix") or {}
            delayed = int(mix.get("quote_rule_delayed") or 0)
            ticks = int(mix.get("tick_rule") or 0)
            if ticks and ticks >= n_signed / 2:
                reasons.append(
                    "tape: most sides come from the tick test (price vs previous print, 0.4 weight) — "
                    "the live chain carries no bid/ask to apply the quote rule"
                )
            elif delayed and delayed >= n_signed / 2:
                reasons.append("tape: most sides come from a delayed reference quote (half weight)")
    else:
        reasons.append("tape: no flow prints available")

    underlying_ratio: float | None = None
    underlying_out: dict[str, Any] | None = None
    if underlying and underlying.get("ratio") is not None:
        underlying_ratio = max(-1.0, min(1.0, float(underlying["ratio"])))
        underlying_out = dict(underlying)
        bars_used = int(underlying.get("bars_used") or 0)
        stale = bool(underlying.get("stale"))
        quality = min(1.0, bars_used / PRESSURE_UNDERLYING_BARS) * (0.4 if stale else 0.6)
        channels.append(("underlying", 0.5, underlying_ratio, quality))
        if stale:
            reasons.append("underlying: bars are stale")
    else:
        reasons.append("underlying: no bars supplied — volume corroboration unavailable")

    # Context, never a vote.
    call_put_mix = _ratio(delta_weighted_call_vol - delta_weighted_put_vol, gross_vol)
    gex_ratio = _ratio(net_gex_m, gross_gex)
    gex_regime = "amplifying" if net_gex_m < -eps else "dampening" if net_gex_m > eps else "neutral"

    weight_total = sum(weight for _, weight, _, _ in channels)
    imbalance = (
        sum(weight * ratio for _, weight, ratio, _ in channels) / weight_total
        if weight_total > eps else 0.0
    )
    imbalance = max(-1.0, min(1.0, imbalance))
    if imbalance > PRESSURE_DIRECTION_THRESHOLD:
        direction = "buying"
    elif imbalance < -PRESSURE_DIRECTION_THRESHOLD:
        direction = "selling"
    else:
        direction = "balanced"

    head_sign = _sign(imbalance)
    conflicts: list[dict[str, Any]] = []
    agreement = 0.0
    n_active = len(channels)
    if channels:
        agree_weight = 0.0
        for name, weight, ratio, _ in channels:
            channel_sign = _sign(ratio)
            if head_sign == 0:
                agree = 1.0 if channel_sign == 0 else 0.0
                if abs(ratio) >= PRESSURE_DIRECTION_THRESHOLD:
                    conflicts.append({
                        "channel": name, "ratio": round(ratio, 6),
                        "note": f"{name} reads {'buying' if ratio > 0 else 'selling'} but the blend is balanced",
                    })
            elif channel_sign == 0:
                agree = 0.5
            elif channel_sign == head_sign:
                agree = 1.0
            else:
                agree = 0.0
                conflicts.append({
                    "channel": name, "ratio": round(ratio, 6),
                    "note": f"{name} reads {'buying' if ratio > 0 else 'selling'} against the {direction} headline",
                })
            agree_weight += weight * agree
        agreement = agree_weight / weight_total
    if n_active == 1:
        agreement = 0.5
        reasons.append("uncorroborated: only one directional channel is active")
    if n_active == 0:
        reasons.append("no signed evidence: nothing here votes on direction")

    evidence_score = (
        0.6 * (sum(quality for *_, quality in channels) / n_active) + 0.4 * min(1.0, n_active / 3.0)
        if channels else 0.0
    )
    magnitude = min(1.0, abs(imbalance) / 0.5)
    live = str(mode_resolved or "").lower() == "live"
    freshness = 1.0 if live else 0.4
    if spot_stale:
        freshness = max(0.0, freshness - 0.3)
        reasons.append("spot is stale")
    if not live:
        reasons.append(f"{mode_resolved or 'history'} mode: delayed data caps confidence; not for live entries")
    score = (
        0.40 * agreement + 0.25 * evidence_score + 0.15 * magnitude + 0.20 * freshness
        if channels else 0.0
    )
    if score >= 0.70:
        band = "high"
    elif score >= 0.50:
        band = "medium"
    elif score >= 0.30:
        band = "low"
    else:
        band = "unmeasurable"
    if n_active < 2 and band in {"high", "medium"}:
        band = "low"
    if not live and band == "high":
        band = "medium"
    if conflicts and band == "high":
        band = "medium"
    # Sides that come only from the tick test (mean weight < 0.5) are real but
    # weak evidence; they can confirm a read, not make it "high".
    if tape_ratio is not None and tape_out is not None and float(tape_out["quality"]) < 0.5 and band == "high":
        band = "medium"
        reasons.append("tape: side evidence is tick-test only, so confidence is capped at medium")

    hard_conflict = any(
        weight >= 1.0 and abs(ratio) >= PRESSURE_DIRECTION_THRESHOLD and _sign(ratio) == -head_sign
        for _, weight, ratio, _ in channels
    ) if head_sign else False
    actionable = bool(
        direction != "balanced" and band in {"high", "medium"} and live and not hard_conflict
    )
    if hard_conflict:
        reasons.append("a full-weight channel reads the opposite way — no trade")

    word = {"buying": "BUYING PRESSURE", "selling": "SELLING PRESSURE", "balanced": "BALANCED"}[direction]
    if actionable:
        verdict = f"{word} · {band.upper()} CONFIDENCE"
    elif direction != "balanced":
        verdict = f"LEAN {direction.upper()} · UNCONFIRMED ({band.upper()})"
    else:
        verdict = f"BALANCED · {band.upper()}"

    return {
        "imbalance": round(imbalance, 6),
        "label": direction,
        "direction": direction,
        "actionable": actionable,
        "verdict": verdict,
        "confidence": {
            "score": round(score, 4),
            "band": band,
            "agreement": round(agreement, 4),
            "evidence": round(evidence_score, 4),
            "magnitude": round(magnitude, 4),
            "freshness": round(freshness, 4),
            "channels_active": n_active,
        },
        "conflicts": conflicts,
        "reasons": reasons,
        "components": {
            "net_charm_flow": round(net_charm_flow, 4),
            "delta_weighted_call_vol": round(delta_weighted_call_vol, 4),
            "delta_weighted_put_vol": round(delta_weighted_put_vol, 4),
            "net_gex_m": round(net_gex_m, 4),
        },
        # Per-channel ratio, so the UI can show WHY the gauge reads the way it
        # does. None = abstained (no data / below floor), never 0. `volume` and
        # `gex` are kept for payload compatibility but are always None: they
        # do not vote any more (see `context`).
        "channels": {
            "charm": None if charm_ratio is None else round(charm_ratio, 6),
            "tape": None if tape_ratio is None else round(tape_ratio, 6),
            "underlying": None if underlying_ratio is None else round(underlying_ratio, 6),
            "volume": None,
            "gex": None,
        },
        "weights": {"charm": 1.0, "tape": 1.0, "underlying": 0.5, "alpha": alpha, "beta": beta},
        "context": {
            "call_put_mix": None if call_put_mix is None else round(call_put_mix, 6),
            "gex_ratio": None if gex_ratio is None else round(gex_ratio, 6),
            "gex_regime": gex_regime,
            "follow_through": (
                "moves extend (dealers hedge with the move)" if gex_regime == "amplifying"
                else "moves fade (dealers hedge against the move)" if gex_regime == "dampening"
                else "no gamma read"
            ),
        },
        "tape": tape_out,
        "underlying": underlying_out,
        "thresholds": {
            "direction": PRESSURE_DIRECTION_THRESHOLD,
            "neutral": PRESSURE_NEUTRAL_BAND,
        },
        "convention_note": (
            "Charm-flow sign follows the dealer-long-calls/short-puts convention; "
            "positive net charm flow maps to selling pressure. Only signed evidence "
            "(charm, side-resolved tape, underlying close-location) votes on direction; "
            "call/put mix and GEX sign are context."
        ),
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _usd_millions(value: float, dp: int = 2) -> str:
    """Signed USD-millions label with the sign ahead of the currency symbol.

    ``f"${-6.55:.2f}M"`` renders ``"$-6.55M"``, which reads as a malformed
    amount rather than a negative one. Net GEX is negative for most of the
    short-gamma tape this text describes, so the sign placement matters.
    """
    return f"{'-' if value < 0 else ''}${abs(value):.{dp}f}M"


def _pct_from_spot(level: float | None, spot: float) -> float | None:
    if level is None or spot <= 0:
        return None
    return round((level - spot) / spot, 6)


def _likelihood(score: int) -> str:
    if score >= 75:
        return "imminent"
    if score >= 55:
        return "likely"
    if score >= 35:
        return "possible"
    return "unlikely"


def _setup_from_gex_score(
    *,
    side: str,
    signed_score: float,
    components: Mapping[str, float],
    wall_level: float | None,
    wall_pct: float | None,
    spot: float,
    near_net: float,
    net_dealer: float,
    fuel: float,
    dampened: bool = False,
) -> dict[str, Any]:
    """Map gex_core structure into a one-sided setup board for the UI.

    Factor meters use unscaled structure so long-gamma names still show
    wall proximity / OTM concentration. Board score is the sum of factor
    points (0–100), not a hard-zero when squeeze fuel is absent.

    Each factor is normalised by the *true* output range of its gex_core
    component (``STRUCTURE_COMPONENT_RANGES``) before being scaled onto its
    display weight. Clamping the raw component against the display max instead
    made two meters permanently unfillable — ``call_conc_score`` caps at 15 against
    a display max of 20 and ``wall_asym_score`` at 10 against 15 — so a perfect
    structure topped out at 90/100, while ``call_prox_score`` (range 30) saturated
    its 25-point meter at 5/6 of the way in and lost the top of its range.
    """
    from edge.daily_plays.gex_core import STRUCTURE_COMPONENT_RANGES

    side_sign = 1.0 if side == "bullish" else -1.0
    factor_specs = [
        ("regime_score", "Gamma Regime", 25, "Short-gamma fuel near spot (required for true squeeze)"),
        ("call_prox_score" if side == "bullish" else "put_prox_score",
         "Call Wall Proximity" if side == "bullish" else "Put Wall Proximity", 25,
         "Distance to directional wall vs expected-move band"),
        ("call_conc_score" if side == "bullish" else "put_conc_score",
         "OTM Concentration", 20, "OTM call/put OI share of book"),
        ("wall_asym_score", "Wall Asymmetry", 15, "Call-wall vs put-wall |GEX| ratio"),
        ("em_score", "Expected-Move Reach", 10, "Active wall inside 1σ band"),
        ("flip_score", "Flip Proximity", 5, "Spot near zero-gamma with aligned direction"),
    ]
    factors = []
    factor_sum = 0
    max_sum = 0
    for key, label, max_pts, detail in factor_specs:
        raw_c = float(components.get(key, 0.0))
        if key == "regime_score":
            # Fuel is direction-neutral: short dealer gamma amplifies whichever way
            # price is already moving. Both boards see the same fuel; direction comes
            # from the five structure factors below, not from re-signing the fuel.
            fill = min(1.0, max(0.0, float(fuel)))
            detail_txt = (
                f"{detail} · fuel={fill:.0%}"
                if fill > 0
                else f"{detail} · fuel unmeasured (needs ADV + ATM strikes)"
            )
        else:
            # Contribution for this side: only count when signed with side.
            contrib = max(0.0, raw_c * side_sign)
            # Normalise by the component's own range, then scale onto the display
            # weight, so every meter can genuinely reach its stated max.
            span = float(STRUCTURE_COMPONENT_RANGES.get(key) or max_pts)
            fill = min(1.0, contrib / span) if span > 0 else 0.0
            detail_txt = f"{detail} · raw={raw_c:+.1f}"
        pts = int(round(max_pts * fill))
        factors.append({
            "id": key,
            "label": label,
            "score": pts,
            "max": max_pts,
            "detail": detail_txt,
        })
        factor_sum += pts
        max_sum += max_pts

    # Board score = factor fill ratio → 0..100 (IF-style probability board).
    score = int(round(100.0 * factor_sum / max_sum)) if max_sum else 0
    score = max(0, min(100, score))
    likelihood = _likelihood(score)

    setup_analysis = [
        f"Near-spot net GEX {_usd_millions(near_net)} · total {_usd_millions(net_dealer)}"
        f" · fuel {fuel:.0%}",
    ]
    if wall_level is not None:
        setup_analysis.append(
            f"{'Call' if side == 'bullish' else 'Put'} wall ${wall_level:,.2f}"
            + (f" ({wall_pct:+.2%})" if wall_pct is not None else "")
        )
    if dampened or fuel <= 0:
        setup_analysis.append("Long / flat gamma environment — dampens squeeze (structure still shown)")
    if signed_score * side_sign >= 20:
        setup_analysis.append(f"gex_core signed score supports {side} ({signed_score:+.1f})")
    elif abs(signed_score) >= 20:
        setup_analysis.append(
            f"gex_core signed score opposes {side} ({signed_score:+.1f}) — structure only"
        )
    else:
        setup_analysis.append(f"gex_core squeeze score quiet ({signed_score:+.1f}) — board is structure only")

    for_stronger: list[str] = []
    if fuel < 0.35:
        for_stronger.append("Deeper negative near-spot GEX would unlock real squeeze fuel")
    if side == "bullish" and abs(float(components.get("call_prox_score") or 0)) < 5:
        for_stronger.append("Spot nearer the call wall (inside EM band) would raise score")
    if side == "bearish" and abs(float(components.get("put_prox_score") or 0)) < 5:
        for_stronger.append("Spot nearer the put wall (inside EM band) would raise score")
    if dampened:
        for_stronger.append("Long gamma dampens — wait for flip below zero-gamma or short-gamma pocket")
    if not for_stronger:
        for_stronger.append("Structure is set by gex_core — wait for price acceptance at walls")

    if score >= 75 and fuel > 0.3:
        implication = f"Strong {side} squeeze structure with fuel. Diagnostic only."
    elif score >= 55:
        implication = f"Elevated {side} structure. Needs short-gamma fuel + price confirmation."
    elif score >= 35:
        implication = f"Partial {side} structure. Not a squeeze alone."
    else:
        implication = f"Low {side} structure score. Stable / no squeeze setup."

    return {
        "side": side,
        "score": score,
        "score_01": round(score / 100.0, 4),
        "likelihood": likelihood,
        "factors": factors,
        "setup_analysis": setup_analysis,
        "for_stronger": for_stronger,
        "trading_implication": implication,
        "spot": round(spot, 4),
        "wall": wall_level,
        "wall_pct": wall_pct,
    }


def _build_signals(
    *,
    spot: float,
    total_gex: float,
    regime: str,
    call_wall: float | None,
    put_wall: float | None,
    gamma_flip: float | None,
    call_wall_pct: float | None,
    put_wall_pct: float | None,
) -> list[dict[str, Any]]:
    """Level-anchored diagnostic signals (volatility / support / resistance)."""
    signals: list[dict[str, Any]] = []
    if regime == "negative":
        strength = "STRONG" if total_gex <= -5 else "MODERATE"
        signals.append({
            "kind": "volatility",
            "strength": strength,
            "title": "Volatility amplification",
            "detail": "Price movements likely to be amplified — good backdrop for long volatility, poor for mean-reversion fades.",
            "level": round(spot, 4),
            "level_pct": 0.0,
        })
    elif regime == "positive":
        signals.append({
            "kind": "volatility",
            "strength": "MODERATE" if total_gex >= 5 else "WEAK",
            "title": "Volatility suppression",
            "detail": "Positive dealer gamma tends to dampen moves; pinning near high-GEX strikes is more common.",
            "level": round(spot, 4),
            "level_pct": 0.0,
        })

    if put_wall is not None and put_wall < spot:
        dist = abs(put_wall_pct or 0)
        strength = "STRONG" if dist <= 0.03 else "MODERATE" if dist <= 0.06 else "WEAK"
        signals.append({
            "kind": "support",
            "strength": strength,
            "title": "Put wall support",
            "detail": "Expect increased volatility / hedging demand if price falls through this put-gamma cluster.",
            "level": round(put_wall, 4),
            "level_pct": put_wall_pct,
        })

    if call_wall is not None and call_wall > spot:
        dist = abs(call_wall_pct or 0)
        strength = "STRONG" if dist <= 0.03 else "MODERATE" if dist <= 0.06 else "WEAK"
        signals.append({
            "kind": "resistance",
            "strength": strength,
            "title": "Call wall resistance",
            "detail": "Call-gamma concentration may act as resistance; dealer hedging can slow advances into the wall.",
            "level": round(call_wall, 4),
            "level_pct": call_wall_pct,
        })

    if gamma_flip is not None:
        flip_pct = _pct_from_spot(gamma_flip, spot)
        signals.append({
            "kind": "regime_flip",
            "strength": "MODERATE",
            "title": "Zero-gamma level",
            "detail": "Crossing zero gamma can change character from pinned to volatile (or vice versa).",
            "level": round(gamma_flip, 4),
            "level_pct": flip_pct,
        })

    return signals[:4]


def _price_momentum(price_series: Sequence[Mapping[str, Any]], *, lookback: int = 5) -> float:
    """Simple close-to-close momentum over ``lookback`` observations (0 if sparse)."""
    closes: list[float] = []
    for row in price_series:
        c = _number(row.get("close") if isinstance(row, Mapping) else None)
        if c is None and isinstance(row, Mapping):
            c = _number(row.get("c") or row.get("price"))
        if c is not None and c > 0:
            closes.append(float(c))
    if len(closes) < 2:
        return 0.0
    n = min(max(int(lookback), 1), len(closes) - 1)
    base = closes[-(n + 1)]
    if base <= 0:
        return 0.0
    return closes[-1] / base - 1.0


def _adv_notional(price_series: Sequence[Mapping[str, Any]], *, window: int = 20) -> float:
    """Average daily dollar volume from price series (volume × close)."""
    notionals: list[float] = []
    for row in price_series:
        if not isinstance(row, Mapping):
            continue
        c = _number(row.get("close") or row.get("c") or row.get("price"))
        v = _number(row.get("volume") or row.get("v"))
        if c is not None and v is not None and c > 0 and v > 0:
            notionals.append(float(c) * float(v))
    if not notionals:
        return 0.0
    tail = notionals[-max(1, int(window)) :]
    return sum(tail) / len(tail)


def _enrich_chain_for_theory(
    chain_rows: Sequence[Mapping[str, Any]],
    *,
    spot: float,
    rate: float,
    asof: datetime,
) -> list[dict[str, Any]]:
    """Attach BS gamma when provider gamma is missing (same as GEX map)."""
    out: list[dict[str, Any]] = []
    for row in chain_rows:
        strike = _number(row.get("strike"))
        right = row.get("right")
        if right in {"C", "c"}:
            right = "call"
        elif right in {"P", "p"}:
            right = "put"
        if not strike or right not in {"call", "put"}:
            continue
        dte = _integer(row.get("dte"))
        if dte is None:
            expiry = row.get("expiry")
            if isinstance(expiry, date):
                dte = (expiry - asof.date()).days
            elif isinstance(expiry, str):
                try:
                    dte = (date.fromisoformat(expiry[:10]) - asof.date()).days
                except ValueError:
                    dte = None
        iv = _number(row.get("iv") or row.get("impliedVolatility") or row.get("implied_vol"))
        gamma = _number(row.get("gamma"))
        years = max(float(dte or 0), 0.5) / 365.0
        if gamma is None or gamma <= 0:
            gamma = _bs_gamma(spot=spot, strike=float(strike), years=years, iv=iv or 0, rate=rate)
        if gamma is None or gamma <= 0:
            continue
        oi = _integer(row.get("open_interest") or row.get("openInterest") or row.get("oi")) or 0
        mult = _integer(row.get("multiplier")) or 100
        out.append({
            "right": right,
            "strike": float(strike),
            "gamma": float(gamma),
            "open_interest": float(oi),
            "multiplier": float(mult),
            "dte": float(dte) if dte is not None else 30.0,
            "iv": iv,
        })
    return out


# A signed tape imbalance is only as trustworthy as the number of signed prints
# behind it. Shrink toward neutral until the sample can carry information.
IMBALANCE_FULL_CONFIDENCE_PRINTS = 8
MOMENTUM_MAX_AGE_DAYS = 4
# Below this fuel_ui a long-gamma charting regime is reported as dampening the
# squeeze rather than merely coexisting with it.
DAMPENED_MAX_FUEL_UI = 0.2
# Conviction weight on signed flow when the tape is signed; momentum gets the rest.
SQUEEZE_FLOW_WEIGHT = 0.5
# Signed-score bands the readout labels against: |score| ≥ lean → *_lean,
# |score| ≥ squeeze → *_squeeze. Shipped to the UI so it never re-hardcodes them.
SQUEEZE_LEAN_THRESHOLD = 20.0
SQUEEZE_FIRE_THRESHOLD = 40.0


def _imbalance_confidence(print_count: int) -> float:
    """Linear confidence ramp in [0, 1] over the included-print count."""
    return min(1.0, max(0, int(print_count)) / float(IMBALANCE_FULL_CONFIDENCE_PRINTS))


def _squeeze_readout(
    *,
    spot: float,
    gex_summary: Mapping[str, Any],
    gex_rows: Sequence[Mapping[str, Any]],
    expected_move: float | None = None,
    expected_low: float | None = None,
    expected_high: float | None = None,
    atm_iv: float | None = None,
    horizon_days: float | None = None,
    chain_rows: Sequence[Mapping[str, Any]] | None = None,
    price_series: Sequence[Mapping[str, Any]] | None = None,
    directional_flow_imbalance: float | None = None,
    imbalance_confidence: float | None = None,
    asof: datetime | None = None,
    rate: float = 0.045,
) -> dict[str, Any]:
    """Squeeze readout: theory scores primary, structure boards secondary.

    Theory (primary):
      short dealer gamma (customer-long premium) × ATM/expiry urgency / ADV
      × explicitly signed directional flow and/or return momentum.

    Structure (secondary UI): wall proximity / OTM concentration factor boards.
    Diagnostic only — not a live trade ticket.
    """
    from edge.daily_plays.gex_core import (
        compute_squeeze_score,
        compute_theory_squeeze,
        directional_walls,
        near_spot_net_gex,
    )

    total_gex = float(gex_summary.get("total_gex_m") or 0.0)
    regime = str(gex_summary.get("regime") or "neutral")
    raw_call_wall = _number(gex_summary.get("call_wall"))
    raw_put_wall = _number(gex_summary.get("put_wall"))
    gamma_flip = _number(gex_summary.get("gamma_flip"))

    rows = list(gex_rows)
    call_wall, put_wall = directional_walls(
        rows, spot=spot, call_wall=raw_call_wall, put_wall=raw_put_wall,
    )
    call_wall_pct = _pct_from_spot(call_wall, spot)
    put_wall_pct = _pct_from_spot(put_wall, spot)

    near_net = near_spot_net_gex(rows, spot=spot, band_pct=0.05)
    # Fall back to the whole-chain total only when the ±5% band holds no strikes at
    # all. A band that genuinely nets to zero (calls cancelling puts) is a real
    # measurement of a flat regime and must not be overwritten by the full book.
    near_band_populated = any(
        spot * 0.95 <= float(r.get("strike") or 0) <= spot * 1.05 for r in rows
    ) if spot > 0 else False
    if not near_band_populated:
        near_net = total_gex

    # OTM OI weights for concentration terms
    otm_call_oi = sum(
        float(r.get("call_oi") or 0) for r in rows if float(r.get("strike") or 0) > spot
    )
    otm_put_oi = sum(
        float(r.get("put_oi") or 0) for r in rows if float(r.get("strike") or 0) < spot
    )
    total_oi = sum(
        float(r.get("call_oi") or 0) + float(r.get("put_oi") or 0) for r in rows
    )

    by_strike = [
        {
            "strike": float(r.get("strike") or 0),
            "call_gex": float(r.get("call_gex_m") or 0),
            "put_gex": float(r.get("put_gex_m") or 0),
            "net_gex": float(r.get("net_gex_m") or 0),
        }
        for r in rows
    ]

    em_pct: float | None = None
    em_low, em_high = expected_low, expected_high
    if expected_move is not None and spot > 0:
        em_pct = float(expected_move) / spot * 100.0
        if em_low is None:
            em_low = spot - expected_move
        if em_high is None:
            em_high = spot + expected_move
    elif atm_iv is not None and horizon_days is not None and spot > 0:
        move = spot * float(atm_iv) * math.sqrt(max(float(horizon_days), 1.0) / 365.0)
        em_pct = move / spot * 100.0
        em_low = spot - move
        em_high = spot + move

    structure = compute_squeeze_score(
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        flip=gamma_flip,
        near_net=near_net,
        net_dealer=total_gex if total_gex != 0 else near_net or 1.0,
        otm_call_weight=otm_call_oi,
        otm_put_weight=otm_put_oi,
        total_weight=total_oi if total_oi > 0 else 1.0,
        by_strike=by_strike,
        expected_move_pct=em_pct,
        expected_move_low=em_low,
        expected_move_high=em_high,
    )

    # --- Theory squeeze (primary direction) ---
    prices = list(price_series or [])
    asof_dt = asof or datetime.now(timezone.utc)
    price_times = [
        observed
        for row in prices
        if isinstance(row, Mapping)
        for observed in (_timestamp(_first(row, "t", "timestamp", "date", "d")),)
        if observed is not None
    ]
    price_age_days = (
        max(0, (asof_dt.date() - max(price_times).date()).days)
        if price_times else None
    )
    momentum_fresh = price_age_days is not None and price_age_days <= MOMENTUM_MAX_AGE_DAYS
    momentum = _price_momentum(prices, lookback=5) if momentum_fresh else 0.0
    adv = _adv_notional(prices, window=20)
    # Contract right is identity, not trade direction. Only an aggressor- or
    # vendor-signed premium imbalance can move the directional flow term.
    # Momentum may still identify the direction of an already-moving squeeze.
    call_imb = (
        float(directional_flow_imbalance)
        if directional_flow_imbalance is not None
        else 0.0
    )
    # An unmeasured input must not vote. When the tape carries no aggressor side
    # (no signed prints, or zero confidence) the flow term used to enter the
    # conviction blend as a hard 0.0 at weight 0.5 — silently capping every
    # directional leg at half of fuel and reading "no flow" as "neutral flow".
    # Drop the term instead so direction comes from momentum alone, and say so.
    flow_measured = directional_flow_imbalance is not None and (
        imbalance_confidence is None or float(imbalance_confidence) > 0
    )
    flow_weight = SQUEEZE_FLOW_WEIGHT if flow_measured else 0.0

    theory_chain = _enrich_chain_for_theory(
        chain_rows or [], spot=spot, rate=rate, asof=asof_dt,
    )
    theory = compute_theory_squeeze(
        chain_rows=theory_chain,
        spot=spot,
        adv_notional=adv,
        call_imbalance=call_imb,
        momentum=momentum,
        score_scale=40.0,
        flow_weight=flow_weight,
    )

    signed = float(theory["squeeze_score"])
    components = dict(structure.get("structure_components") or structure["squeeze_components"])
    # Merge theory diagnostics into component board
    theory_components = dict(theory.get("components") or {})
    components = {
        **components,
        "theory_squeeze_risk": theory_components.get("squeeze_risk"),
        "theory_momentum": theory_components.get("momentum"),
        "theory_momentum_fresh": momentum_fresh,
        "theory_momentum_price_age_days": price_age_days,
        "theory_directional_flow_imbalance": theory_components.get("directional_flow_imbalance"),
        "theory_atm_share": theory_components.get("atm_share"),
        "theory_weighted_dte": theory_components.get("weighted_dte"),
        "theory_liquidity_ratio": theory_components.get("liquidity_ratio"),
        "theory_call_short_gex_m": theory_components.get("call_short_gex_m"),
        "theory_put_short_gex_m": theory_components.get("put_short_gex_m"),
        "theory_conviction_bull": theory_components.get("conviction_bull"),
        "theory_conviction_bear": theory_components.get("conviction_bear"),
        "theory_imbalance_confidence": imbalance_confidence,
        "theory_flow_measured": flow_measured,
        "theory_mom_up_gate": theory_components.get("mom_up_gate"),
        "theory_mom_dn_gate": theory_components.get("mom_dn_gate"),
        "theory_urgency": theory_components.get("urgency"),
        "flow_weight": theory_components.get("flow_weight"),
    }
    scored_components = dict(structure["squeeze_components"])
    # ``fuel`` is reported on the theory's own calibration — tanh(fuel_scale · SR),
    # the same transform the directional scores use. The previous UI scale
    # (min(1, 10 · SR)) saturated at SR = 0.10 while the theory saturated at ≈0.05,
    # so the tab showed "FUEL 25%" on books the model already treated as ~76% fuelled.
    fuel = float(theory_components.get("fuel_ui") or 0.0)
    # Dampened means "long-gamma regime with too little short-gamma fuel to overcome
    # it". The old test (raw SR < 1e-6) could never fire on a real chain: under the
    # short-premium assumption dealer GEX is ≤ 0 by construction, so SR is positive
    # for any book with OI. That inverted the flag into "chain is unmeasurable" and
    # left the LONG Γ tag dead. Compare against the fuel scale the UI actually shows.
    dampened = bool(structure.get("long_gamma_dampened")) and fuel < DAMPENED_MAX_FUEL_UI
    short_gex = theory.get("short_premium_gex_m") or {}

    bullish = _clamp01(float(theory.get("bullish_ui") or 0.0) / 100.0)
    bearish = _clamp01(float(theory.get("bearish_ui") or 0.0) / 100.0)

    core_label = str(theory["squeeze_label"])
    if core_label == "bullish_squeeze":
        label = "bullish_squeeze" if signed >= SQUEEZE_FIRE_THRESHOLD else "bullish_lean"
        primary = "bullish"
    elif core_label == "bearish_squeeze":
        label = "bearish_squeeze" if signed <= -SQUEEZE_FIRE_THRESHOLD else "bearish_lean"
        primary = "bearish"
    else:
        label = "quiet"
        primary = "quiet"
        if (
            float(theory.get("bullish_ui") or 0) > 8
            and float(theory.get("bearish_ui") or 0) > 8
        ):
            label = "two_way"
            primary = "two_way"

    drivers: list[str] = []
    if float(short_gex.get("total_gex_m") or 0) < 0:
        drivers.append("short_premium_dealer_gamma")
    if near_net < 0:
        drivers.append("negative_charting_near_gex")
    elif dampened:
        drivers.append("long_gamma_dampens")
    if flow_measured and abs(call_imb) >= 0.1:
        drivers.append("signed_bullish_flow" if call_imb > 0 else "signed_bearish_flow")
    if momentum > 0.005:
        drivers.append("up_momentum")
    elif momentum < -0.005:
        drivers.append("down_momentum")
    if abs(float(components.get("call_prox_score") or 0)) >= 5:
        drivers.append("call_wall_proximity")
    if abs(float(components.get("put_prox_score") or 0)) >= 5:
        drivers.append("put_wall_proximity")
    if float(theory_components.get("atm_share") or 0) >= 0.25:
        drivers.append("atm_gamma_concentration")
    if float(theory_components.get("weighted_dte") or 99) <= 7:
        drivers.append("short_dated_urgency")
    if abs(float(components.get("flip_score") or 0)) > 0:
        drivers.append("near_gamma_flip")

    # Factor boards still use structure meters; score bias from theory signed score
    bullish_setup = _setup_from_gex_score(
        side="bullish",
        signed_score=signed,
        components=structure.get("structure_components") or structure["squeeze_components"],
        wall_level=call_wall,
        wall_pct=call_wall_pct,
        spot=spot,
        near_net=near_net,
        net_dealer=total_gex,
        fuel=fuel,
        dampened=dampened,
    )
    bearish_setup = _setup_from_gex_score(
        side="bearish",
        signed_score=signed,
        components=structure.get("structure_components") or structure["squeeze_components"],
        wall_level=put_wall,
        wall_pct=put_wall_pct,
        spot=spot,
        near_net=near_net,
        net_dealer=total_gex,
        fuel=fuel,
        dampened=dampened,
    )

    signals = _build_signals(
        spot=spot,
        total_gex=total_gex,
        regime=regime if near_net == 0 else ("negative" if near_net < 0 else "positive"),
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        call_wall_pct=call_wall_pct,
        put_wall_pct=put_wall_pct,
    )

    return {
        "bullish": round(bullish, 4),
        "bearish": round(bearish, 4),
        "score": signed,
        "label": label,
        "primary": primary,
        "drivers": drivers,
        "method": (
            "theory: short-premium dealer GEX × ATM/expiry urgency / ADV × "
            "signed directional flow / return momentum; structure boards secondary"
        ),
        "components": components,
        "scored_components": scored_components,
        "theory": {
            "squeeze_risk": theory.get("squeeze_risk"),
            "fuel_ui": fuel,
            "bullish_score_raw": theory.get("bullish_score_raw"),
            "bearish_score_raw": theory.get("bearish_score_raw"),
            "bullish_ui": theory.get("bullish_ui"),
            "bearish_ui": theory.get("bearish_ui"),
            "short_premium_gex_m": short_gex,
            "adv_m": theory.get("adv_m"),
            "adv_available": theory.get("adv_available"),
            "measurable": theory.get("measurable"),
            # None, not 0.0, when the tape carried no aggressor side.
            "directional_flow_imbalance": (
                theory.get("directional_flow_imbalance") if flow_measured else None
            ),
            "flow_measured": flow_measured,
            "flow_weight": theory_components.get("flow_weight"),
            "imbalance_confidence": imbalance_confidence,
            "momentum": theory.get("momentum"),
            "momentum_fresh": momentum_fresh,
            "momentum_price_age_days": price_age_days,
            "mom_ref": theory_components.get("mom_ref"),
            "mom_up_gate": theory_components.get("mom_up_gate"),
            "mom_dn_gate": theory_components.get("mom_dn_gate"),
            "conviction_bull": theory_components.get("conviction_bull"),
            "conviction_bear": theory_components.get("conviction_bear"),
            "liquidity_ratio": theory_components.get("liquidity_ratio"),
            "urgency": theory_components.get("urgency"),
            "fuel_scale": theory_components.get("fuel_scale"),
            "lean_threshold": SQUEEZE_LEAN_THRESHOLD,
            "squeeze_threshold": SQUEEZE_FIRE_THRESHOLD,
            "label": theory.get("squeeze_label"),
        },
        "structure_score": structure.get("squeeze_score"),
        "structure_label": structure.get("squeeze_label"),
        "long_gamma_dampened": dampened,
        "negative_fuel": round(fuel, 4),
        "structure_negative_fuel": float(structure.get("negative_fuel") or 0.0),
        "key_levels": {
            "spot": round(spot, 4),
            "call_wall": call_wall,
            "call_wall_pct": call_wall_pct,
            "put_wall": put_wall,
            "put_wall_pct": put_wall_pct,
            "gamma_flip": gamma_flip,
            "gamma_flip_pct": _pct_from_spot(gamma_flip, spot),
            "pin_strike": _number(gex_summary.get("pin_strike")),
            "near_spot_net_gex_m": round(near_net, 4),
            "short_premium_gex_m": round(float(short_gex.get("total_gex_m") or 0.0), 4),
        },
        "signals": signals,
        "bullish_setup": bullish_setup,
        "bearish_setup": bearish_setup,
    }


def _weighted_iv(rows: Sequence[Mapping[str, Any]], *, spot: float, expiry: date) -> float | None:
    candidates = []
    for row in rows:
        if row.get("expiry") != expiry:
            continue
        strike, iv = _number(row.get("strike")), _number(row.get("iv"))
        if not strike or iv is None or not 0.005 <= iv <= 5.0:
            continue
        distance = abs(math.log(strike / spot))
        if distance > 0.15:
            continue
        weight = max(1, _integer(row.get("open_interest")) or 0) / (1.0 + distance * 20.0)
        candidates.append((iv, weight))
    if not candidates:
        return None
    return sum(iv * weight for iv, weight in candidates) / sum(weight for _, weight in candidates)


def _probability_context(
    rows: Sequence[Mapping[str, Any]], *, spot: float, asof: datetime, rate: float,
    call_wall: float | None, put_wall: float | None,
) -> dict[str, Any]:
    expiries = sorted({row.get("expiry") for row in rows if isinstance(row.get("expiry"), date)})
    if not expiries:
        return {"available": False, "method": "risk-neutral lognormal; unavailable without expiry and IV"}
    target = min(expiries, key=lambda value: abs((value - asof.date()).days - 30))
    horizon = max((target - asof.date()).days, 1)
    iv = _weighted_iv(rows, spot=spot, expiry=target)
    if iv is None:
        return {"available": False, "expiry": target.isoformat(), "horizon_days": horizon,
                "method": "risk-neutral lognormal; unavailable without usable IV"}
    years = horizon / 365.0
    sigma = iv * math.sqrt(years)
    expected_move = spot * sigma

    def prob_above(target_price: float | None) -> float | None:
        if target_price is None or target_price <= 0 or sigma <= 0:
            return None
        z = (math.log(target_price / spot) - (rate - 0.5 * iv * iv) * years) / sigma
        return max(0.0, min(1.0, 1.0 - _normal_cdf(z)))

    def prob_below(target_price: float | None) -> float | None:
        above = prob_above(target_price)
        return None if above is None else 1.0 - above

    above_call, below_put = prob_above(call_wall), prob_below(put_wall)
    inside = None
    if call_wall is not None and put_wall is not None and put_wall < call_wall:
        inside = max(0.0, 1.0 - (above_call or 0.0) - (below_put or 0.0))
    return {
        "available": True,
        "method": "risk-neutral lognormal from near-ATM IV; diagnostic, not a directional forecast",
        "expiry": target.isoformat(),
        "horizon_days": horizon,
        "atm_iv": round(iv, 6),
        "expected_move": round(expected_move, 4),
        "expected_low": round(max(0.0, spot - expected_move), 4),
        "expected_high": round(spot + expected_move, 4),
        "prob_above_call_wall": round(above_call, 6) if above_call is not None else None,
        "prob_below_put_wall": round(below_put, 6) if below_put is not None else None,
        "prob_between_walls": round(inside, 6) if inside is not None else None,
    }


def _gex_history(
    rows: Sequence[Mapping[str, Any]], *, filters: OptionsFilters, asof: datetime,
    selected_expiry: str | None,
) -> list[dict[str, Any]]:
    """Rebuild GEX independently at each captured snapshot; never backfill missing days."""
    lower, upper = _date_bounds(filters, asof)
    by_day: dict[date, list[tuple[datetime, Mapping[str, Any]]]] = {}
    for row in rows:
        observed = _timestamp(_first(
            row, "captured_utc", "asof_utc", "timestamp", "updated_at", "asof_date",
        ))
        if observed is None or not lower <= observed <= upper:
            continue
        by_day.setdefault(observed.date(), []).append((observed, row))

    history: list[dict[str, Any]] = []
    history_filters = (
        replace(filters, expiry=selected_expiry)
        if selected_expiry and filters.expiry != "all"
        else filters
    )
    for day, observations in sorted(by_day.items()):
        latest = max(observed for observed, _ in observations)
        snapshot = [row for observed, row in observations if observed == latest]
        if not snapshot:
            continue
        spots = [
            value for row in snapshot
            for value in (_number(_first(row, "spot", "underlying_price")),)
            if value is not None and value > 0
        ]
        if not spots:
            continue
        spot = median(spots)
        filtered, _, context = _filter_chain(
            snapshot, asof=latest, spot=spot, filters=history_filters,
        )
        if not filtered:
            continue
        _, summary, _, _, _ = _gex_map(
            filtered, spot=spot, asof=latest, rate=filters.risk_free_rate,
        )
        history.append({
            "t": day.isoformat(),
            "observed_at": latest.isoformat(),
            "spot": round(spot, 4),
            "expiry": context["selected_expiry"],
            "contracts": len(filtered),
            **summary,
        })
    return history


def _stacked_theta_vanna(
    *, chain_rows: Sequence[Mapping[str, Any]], spot: float, rate: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any], int]:
    """Theta and vanna exposure by strike + per-contract BS diagnostics.
    Theta flow = theta × OI × 100: option-price points/day decaying out of
    every strike (always negative for long premium — the sign carries which
    SIDE of the book bleeds). Vanna flow = vanna × OI × 100 × spot: delta
    shares dealers must trade per +1 vol-point move, signed call + / put −
    like GEX/charm so a positive bar is dealer delta that RISES with IV.
    Same skip-don't-clamp rule as _charm_map: no IV or T < 1 day → None.
    """
    by_strike: dict[float, dict[str, float]] = {}
    chain_rows_out: list[dict[str, Any]] = []
    source_counts = {"black_scholes": 0, "unavailable": 0}
    for row in chain_rows:
        strike = _number(row.get("strike"))
        dte = _integer(row.get("dte"))
        iv = _number(row.get("iv"))
        right = row.get("right")
        if not strike or right not in {"call", "put"}:
            source_counts["unavailable"] += 1
            continue
        years = max(float(dte or 0), 0.5) / 365.0
        theta = _bs_theta_per_day(
            spot=spot, strike=strike, years=years, iv=iv or 0, rate=rate, is_call=(right == "call"),
        )
        vanna = _bs_vanna(spot=spot, strike=strike, years=years, iv=iv or 0, rate=rate)
        if theta is None or vanna is None:
            source_counts["unavailable"] += 1
            continue
        source_counts["black_scholes"] += 1
        oi = _integer(row.get("open_interest")) or 0
        multiplier = _integer(row.get("multiplier")) or 100
        sign = 1.0 if right == "call" else -1.0
        theta_flow = theta * oi * multiplier
        vanna_flow = sign * vanna * oi * multiplier * spot
        cell = by_strike.setdefault(strike, {
            "call_theta": 0.0, "put_theta": 0.0, "call_vanna": 0.0, "put_vanna": 0.0,
            "call_oi": 0.0, "put_oi": 0.0,
        })
        cell[f"{right}_theta"] += theta_flow
        cell[f"{right}_vanna"] += vanna_flow
        cell[f"{right}_oi"] += oi
        chain_rows_out.append({
            "strike": strike,
            "right": right,
            "dte": dte,
            "iv": iv,
            "open_interest": oi,
            "volume": _integer(row.get("volume")) or 0,
            "theta_per_day": theta,
            "theta_flow": theta_flow,
            "vanna": vanna,
            "vanna_flow": vanna_flow,
        })
    mapped = []
    for strike, value in sorted(by_strike.items()):
        mapped.append({
            "strike": strike,
            "call_theta_flow": round(value["call_theta"], 4),
            "put_theta_flow": round(value["put_theta"], 4),
            "net_theta_flow": round(value["call_theta"] + value["put_theta"], 4),
            "call_vanna_flow": round(value["call_vanna"], 4),
            "put_vanna_flow": round(value["put_vanna"], 4),
            "net_vanna_flow": round(value["call_vanna"] + value["put_vanna"], 4),
            "call_oi": int(value["call_oi"]),
            "put_oi": int(value["put_oi"]),
        })
    net_theta = sum(row["net_theta_flow"] for row in mapped)
    call_theta = sum(row["call_theta_flow"] for row in mapped)
    put_theta = sum(row["put_theta_flow"] for row in mapped)
    net_vanna = sum(row["net_vanna_flow"] for row in mapped)
    call_vanna = sum(row["call_vanna_flow"] for row in mapped)
    put_vanna = sum(row["put_vanna_flow"] for row in mapped)
    theta_summary = {
        "net_theta_flow": round(net_theta, 4),
        "call_theta_flow": round(call_theta, 4),
        "put_theta_flow": round(put_theta, 4),
        "abs_theta_flow": round(abs(call_theta) + abs(put_theta), 4),
        "decay_side": (
            "calls" if abs(call_theta) > abs(put_theta)
            else "puts" if abs(put_theta) > abs(call_theta)
            else "balanced"
        ) if mapped else None,
        "source": "black_scholes_theta",
    }
    # Vanna regime: net dealer delta sensitivity to a parallel IV shift.
    # Positive → rising IV lifts dealer delta (dealers buy dips into vol spikes);
    # negative → rising IV forces dealer selling (vol spiral fuel).
    vanna_summary = {
        "net_vanna_flow": round(net_vanna, 4),
        "call_vanna_flow": round(call_vanna, 4),
        "put_vanna_flow": round(put_vanna, 4),
        "regime": (
            "iv_up_supportive" if net_vanna > 0 else "iv_up_pressuring" if net_vanna < 0 else "neutral"
        ) if mapped else None,
        "source": "black_scholes_vanna",
    }
    return mapped, theta_summary, chain_rows_out, vanna_summary, source_counts["unavailable"]


def _stacked_iv_surface(
    *, chain_rows: Sequence[Mapping[str, Any]], spot: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """IV smile by strike + IV walls (where the options market prices uncertainty).
    An IV wall is the strike with peak quoted open interest AND elevated IV on
    its side of the smile — where positioning and priced volatility agree.
    Skew = call IV − put IV at matched strikes (negative = put skew).
    """
    by_strike: dict[float, dict[str, float]] = {}
    for row in chain_rows:
        strike = _number(row.get("strike"))
        iv = _number(row.get("iv"))
        right = row.get("right")
        if not strike or iv is None or not 0.005 <= iv <= 5.0 or right not in {"call", "put"}:
            continue
        oi = _integer(row.get("open_interest")) or 0
        vol = _integer(row.get("volume")) or 0
        cell = by_strike.setdefault(strike, {"call_iv_sum": 0.0, "call_iv_w": 0.0, "put_iv_sum": 0.0, "put_iv_w": 0.0})
        key_sum, key_w = f"{right}_iv_sum", f"{right}_iv_w"
        # OI-weighted mean IV per side; volume as tiebreaker weight keeps a
        # dead-but-huge OI line from fully masking today's active quoting.
        weight = oi + vol * 0.25
        cell[key_sum] += iv * weight
        cell[key_w] += weight
    rows_out = []
    for strike, value in sorted(by_strike.items()):
        call_iv = value["call_iv_sum"] / value["call_iv_w"] if value["call_iv_w"] > 0 else None
        put_iv = value["put_iv_sum"] / value["put_iv_w"] if value["put_iv_w"] > 0 else None
        rows_out.append({
            "strike": strike,
            "call_iv": round(call_iv, 6) if call_iv is not None else None,
            "put_iv": round(put_iv, 6) if put_iv is not None else None,
            "skew": round(call_iv - put_iv, 6) if call_iv is not None and put_iv is not None else None,
            "distance_pct": round((strike - spot) / spot, 6) if spot > 0 else None,
        })
    atm_iv: float | None = None
    if spot > 0 and rows_out:
        atm_row = min(rows_out, key=lambda row: abs(row["strike"] - spot))
        atm_candidates = [atm_row["call_iv"], atm_row["put_iv"]]
        atm_values = [value for value in atm_candidates if value is not None]
        atm_iv = sum(atm_values) / len(atm_values) if atm_values else None
    def peak(side: str) -> float | None:
        values = [row for row in rows_out if row[side] is not None]
        if not values:
            return None
        return max(values, key=lambda row: row[side])["strike"]
    def iv_wall(side: str) -> float | None:
        """Peak-OI strike on each side whose IV also sits above ATM IV."""
        candidates = [
            row for row in rows_out
            if row[side] is not None and atm_iv is not None and row[side] >= atm_iv
            and ((side == "call_iv" and row["strike"] >= spot) or (side == "put_iv" and row["strike"] <= spot))
        ]
        if not candidates:
            return None
        # OI proxy: pick the candidate nearest the peak-IV strike among the
        # top quartile of distance — walls are where size and IV coexist.
        top = sorted(candidates, key=lambda row: row[side] or 0.0, reverse=True)[: max(len(candidates) // 4, 3)]
        return max(top, key=lambda row: abs(row["strike"] - spot))["strike"] if top else None
    summary = {
        "available": bool(rows_out),
        "atm_iv": round(atm_iv, 6) if atm_iv is not None else None,
        "peak_call_iv_strike": peak("call_iv"),
        "peak_put_iv_strike": peak("put_iv"),
        "call_iv_wall": iv_wall("call_iv"),
        "put_iv_wall": iv_wall("put_iv"),
        "method": "OI+volume weighted mean IV per strike; walls = peak IV above ATM on each side",
    }
    return rows_out, summary


def _iv_surface_by_expiry(
    *, chain_rows: Sequence[Mapping[str, Any]], spot: float, asof: datetime,
) -> list[dict[str, Any]]:
    """One IV smile per expiry — the input a risk-neutral density actually needs.

    `_stacked_iv_surface` above collapses the whole chain into a single
    per-strike IV by averaging across every expiry. That is the right shape for
    a skew/wall lens, and the wrong shape for Breeden-Litzenberger: a 0DTE wing
    and a 90DTE wing at the same strike carry very different implied vols, so
    the blended curve is not the smile of any traded expiry. Repricing calls off
    it produces a non-convex call curve, whose second derivative goes negative
    over wide stretches -- which is exactly the "density not reliable, N% of its
    mass was negative before clipping" state that left the regime page's
    probability panel blank most of the time.

    Each entry here is a single expiry's own smile, so the density built from it
    is the density of a distribution the market actually quotes, at a horizon
    the operator can name.
    """
    asof_day = asof.date() if isinstance(asof, datetime) else asof
    by_expiry: dict[date, dict[float, dict[str, float]]] = {}
    for row in chain_rows:
        expiry = row.get("expiry")
        strike = _number(row.get("strike"))
        iv = _number(row.get("iv"))
        right = row.get("right")
        if not isinstance(expiry, date) or not strike or iv is None:
            continue
        if not 0.005 <= iv <= 5.0 or right not in {"call", "put"}:
            continue
        oi = _integer(row.get("open_interest")) or 0
        vol = _integer(row.get("volume")) or 0
        weight = oi + vol * 0.25
        if weight <= 0:
            # A contract with neither OI nor volume has a quote nobody stands
            # behind; including it lets a stale mark set the wing.
            continue
        cell = by_expiry.setdefault(expiry, {}).setdefault(
            strike, {"call_iv_sum": 0.0, "call_iv_w": 0.0, "put_iv_sum": 0.0, "put_iv_w": 0.0},
        )
        cell[f"{right}_iv_sum"] += iv * weight
        cell[f"{right}_iv_w"] += weight

    out: list[dict[str, Any]] = []
    for expiry, strikes in sorted(by_expiry.items()):
        points = []
        for strike, value in sorted(strikes.items()):
            call_iv = value["call_iv_sum"] / value["call_iv_w"] if value["call_iv_w"] > 0 else None
            put_iv = value["put_iv_sum"] / value["put_iv_w"] if value["put_iv_w"] > 0 else None
            if call_iv is None and put_iv is None:
                continue
            points.append({
                "strike": strike,
                "call_iv": round(call_iv, 6) if call_iv is not None else None,
                "put_iv": round(put_iv, 6) if put_iv is not None else None,
            })
        # PCHIP needs four nodes; fewer is not a smile, it is a few quotes.
        if len(points) < 4:
            continue
        atm_row = min(points, key=lambda row: abs(row["strike"] - spot)) if spot > 0 else None
        atm_values = [
            v for v in ((atm_row or {}).get("call_iv"), (atm_row or {}).get("put_iv")) if v is not None
        ]
        dte = (expiry - asof_day).days if isinstance(asof_day, date) else None
        out.append({
            "expiry": expiry.isoformat(),
            "dte": dte,
            # A 0DTE expiry still has real intraday life; floor the horizon at a
            # few hours rather than zero so sigma*sqrt(T) does not collapse.
            "years": round(max(float(dte if dte is not None else 1), 0.25) / 365.0, 8),
            "atm_iv": round(sum(atm_values) / len(atm_values), 6) if atm_values else None,
            "strikes_measured": len(points),
            "points": points,
        })
    return out


def _stacked_volume_profile(
    *, price_series: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Volume-by-price histogram from the chart's own daily bars.
    POC = highest-volume price bin. Value area = standard 70% expansion around
    the POC. LVNs = local-minima bins under 35% of peak volume — prices where
    real trading thinned out and price tends to slip through rather than stall.
    Daily bars are an approximation of intrabar tape; the summary says so.
    """
    bars = [
        (float(row["close"]), float(row.get("volume") or 0.0))
        for row in price_series
        if _number(row.get("close")) is not None and _number(row.get("close")) > 0
    ]
    if len(bars) < 5 or sum(volume for _, volume in bars) <= 0:
        return [], {"available": False, "method": "needs ≥5 priced bars with volume"}
    closes = [price for price, _ in bars]
    low, high = min(closes), max(closes)
    if high <= low:
        return [], {"available": False, "method": "degenerate price range"}
    bin_count = min(48, max(12, len(bars) // 2))
    width = (high - low) / bin_count
    volumes = [0.0] * bin_count
    for price, volume in bars:
        idx = min(int((price - low) / width), bin_count - 1)
        volumes[idx] += volume
    total_volume = sum(volumes)
    peak_volume = max(volumes)
    poc_idx = volumes.index(peak_volume)
    # Value area: expand outward from POC until ≥70% of volume is enclosed.
    lo_idx = hi_idx = poc_idx
    enclosed = volumes[poc_idx]
    target = 0.70 * total_volume
    while enclosed < target and (lo_idx > 0 or hi_idx < bin_count - 1):
        below = volumes[lo_idx - 1] if lo_idx > 0 else -1.0
        above = volumes[hi_idx + 1] if hi_idx < bin_count - 1 else -1.0
        if above >= below:
            hi_idx += 1
            enclosed += volumes[hi_idx]
        else:
            lo_idx -= 1
            enclosed += volumes[lo_idx]
    profile = []
    for idx, volume in enumerate(volumes):
        bin_lo = low + idx * width
        profile.append({
            "price": round(bin_lo + width / 2.0, 4),
            "low": round(bin_lo, 4),
            "high": round(bin_lo + width, 4),
            "volume": round(volume, 2),
            "pct_of_peak": round(volume / peak_volume, 4) if peak_volume > 0 else None,
            "in_value_area": lo_idx <= idx <= hi_idx,
        })
    # LVNs: interior local minima below 35% of peak, ignoring one-bin noise
    # by requiring both neighbours to be heavier.
    lvn_bins = [
        idx for idx in range(1, bin_count - 1)
        if volumes[idx] < 0.35 * peak_volume
        and volumes[idx] <= volumes[idx - 1] and volumes[idx] <= volumes[idx + 1]
    ]
    lvn_levels = [
        {
            "low": round(low + idx * width, 4),
            "high": round(low + (idx + 1) * width, 4),
            "mid": round(profile[idx]["price"], 4),
            "volume_pct_of_peak": profile[idx]["pct_of_peak"],
        }
        for idx in lvn_bins
    ]
    extremes = {
        "high": round(high, 4),
        "low": round(low, 4),
    }
    summary = {
        "available": True,
        "bars": len(bars),
        "bin_count": bin_count,
        "poc": round(profile[poc_idx]["price"], 4),
        "value_area_low": round(profile[lo_idx]["price"], 4),
        "value_area_high": round(profile[hi_idx]["price"], 4),
        "lvn_count": len(lvn_levels),
        "extremes": extremes,
        "method": "daily-bar volume-by-price approximation of intrabar tape",
    }
    return profile, {**summary, "lvns": lvn_levels}


def _stacked_confluence(
    *,
    spot: float | None,
    call_wall: float | None, put_wall: float | None, gamma_flip: float | None, pin_strike: float | None,
    theta_decay_strike: float | None, vanna_pivot: float | None,
    call_iv_wall: float | None, put_iv_wall: float | None,
    poc: float | None, value_area_low: float | None, value_area_high: float | None,
) -> list[dict[str, Any]]:
    """Level confluence: which price zones multiple independent lenses name.
    A level named by ≥2 lenses is where the stacked picture gets its edge —
    e.g. a GEX call wall that is ALSO the IV wall and near the POC. Purely
    descriptive clustering (±0.75% band); never a probability or a signal score.
    """
    lenses: list[tuple[str, str, float]] = []
    if call_wall is not None:
        lenses.append(("gamma", "GEX call wall", call_wall))
    if put_wall is not None:
        lenses.append(("gamma", "GEX put wall", put_wall))
    if gamma_flip is not None:
        lenses.append(("gamma", "Gamma flip", gamma_flip))
    if pin_strike is not None:
        lenses.append(("gamma", "Pin (max |net GEX|)", pin_strike))
    if theta_decay_strike is not None:
        lenses.append(("theta", "Max theta decay", theta_decay_strike))
    if vanna_pivot is not None:
        lenses.append(("vanna", "Vanna pivot", vanna_pivot))
    if call_iv_wall is not None:
        lenses.append(("iv", "Call IV wall", call_iv_wall))
    if put_iv_wall is not None:
        lenses.append(("iv", "Put IV wall", put_iv_wall))
    if poc is not None:
        lenses.append(("volume", "Volume POC", poc))
    if value_area_high is not None:
        lenses.append(("volume", "Value area high", value_area_high))
    if value_area_low is not None:
        lenses.append(("volume", "Value area low", value_area_low))
    clusters: list[dict[str, Any]] = []
    used = [False] * len(lenses)
    band = 0.0075
    for i, (family, label, level) in enumerate(lenses):
        if used[i]:
            continue
        members = [(family, label, level)]
        used[i] = True
        for j in range(i + 1, len(lenses)):
            if used[j]:
                continue
            other_level = lenses[j][2]
            ref = sum(value for _, _, value in members) / len(members)
            if abs(other_level - ref) / ref <= band:
                members.append(lenses[j])
                used[j] = True
        avg = sum(value for _, _, value in members) / len(members)
        families = sorted({family for family, _, _ in members})
        clusters.append({
            "level": round(avg, 4),
            "distance_pct": round((avg - spot) / spot, 6) if spot else None,
            "supporting_lenses": families,
            "lens_count": len(families),
            "labels": [label for _, label, _ in members],
            "above_spot": bool(spot and avg > spot),
        })
    clusters.sort(key=lambda cluster: (-cluster["lens_count"], abs(cluster["distance_pct"] or 9)))
    return clusters


def build_options_intelligence(
    *, symbol: str, chain_rows: Sequence[Mapping[str, Any]], flow_rows: Sequence[Mapping[str, Any]],
    price_series: Sequence[Mapping[str, Any]], spot: float | None, filters: OptionsFilters,
    mode_requested: str, mode_resolved: str, chain_source: str, flow_source: str,
    asof_utc: datetime | None = None, warnings: Iterable[str] = (),
    open_interest_source: str = "provider",
    history_chain_rows: Sequence[Mapping[str, Any]] = (),
    underlying_bars: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create the dashboard payload without manufacturing missing observations.

    ``underlying_bars`` (chronological OHLCV dicts, typically the last few
    sessions of 1h bars) feeds the pressure read's underlying corroboration
    channel. Omit it and that channel abstains and says so.
    """
    now = asof_utc or datetime.now(timezone.utc)
    latest_rows, chain_observed = _latest_chain(chain_rows)
    observed_spots = [
        value for row in latest_rows
        for value in (_number(_first(row, "spot", "underlying_price")),)
        if value is not None and value > 0
    ]
    resolved_spot = _number(spot) or (median(observed_spots) if observed_spots else None)
    if resolved_spot is None or resolved_spot <= 0:
        return {
            "schema_version": "edge-options-intelligence-v1", "symbol": symbol.upper(),
            "mode_requested": mode_requested, "mode_resolved": "unavailable",
            "asof_utc": now.isoformat(), "filters": asdict(filters),
            "error": "No trustworthy underlying spot was available.",
            "warnings": list(dict.fromkeys(warnings)),
        }

    chain_asof = chain_observed or now
    eval_asof = now if (mode_requested == "live" and mode_resolved == "live") else chain_asof
    contract_focus = _contract_focus(
        latest_rows,
        # Contract expiry is selected against the current session in live
        # mode, even when the provider's quote timestamp is delayed.
        asof=eval_asof,
        spot=resolved_spot,
    )
    filtered_chain, chain_rejected, chain_context = _filter_chain(
        latest_rows,
        asof=chain_asof,
        spot=resolved_spot,
        filters=filters,
        selection_date=eval_asof.date(),
    )
    spread_samples = [row["spread_pct"] for row in filtered_chain if row["spread_pct"] is not None]
    median_spread_pct = median(spread_samples) if spread_samples else None
    (
        flow_series, tape, flow_rejected, signed_observations, activity_observations, tape_channel,
    ) = _flow_series(
        flow_rows,
        filters=filters,
        asof=now,
        selected_expiry=chain_context["selected_expiry"],
        mode_requested=mode_requested,
        spot=resolved_spot,
        chain_rows=latest_rows,
    )
    # Keep an exact expiry as the structural/GEX focus, but do not let it turn
    # a live tape into an unsigned chain proxy when every otherwise-qualified
    # print is in another expiry. In that narrow case only, widen the tape to
    # all expiries and label the relaxation explicitly.
    if (
        not tape
        and flow_rows
        and filters.expiry not in {"all", "nearest"}
        and int(flow_rejected.get("outside_expiry") or 0) > 0
    ):
        requested_expiry = chain_context["selected_expiry"]
        original_outside_expiry = int(flow_rejected.get("outside_expiry") or 0)
        (
            relaxed_series,
            relaxed_tape,
            relaxed_rejected,
            relaxed_signed_observations,
            relaxed_activity_observations,
            relaxed_tape_channel,
        ) = _flow_series(
            flow_rows,
            filters=filters,
            asof=now,
            selected_expiry=None,
            mode_requested=mode_requested,
            spot=resolved_spot,
            chain_rows=latest_rows,
        )
        if relaxed_tape:
            flow_series = relaxed_series
            tape = relaxed_tape
            flow_rejected = {
                **relaxed_rejected,
                "expiry_filter_relaxed": True,
                "requested_expiry": requested_expiry,
                "selected_expiry_rejected": original_outside_expiry,
            }
            signed_observations = relaxed_signed_observations
            activity_observations = relaxed_activity_observations
            tape_channel = relaxed_tape_channel
    activity_basis = "trade_tape"
    if not flow_series:
        flow_series = _chain_activity_series(chain_rows, filters=filters, asof=now)
        activity_basis = "chain_activity_proxy" if flow_series else "unavailable"

    gex, gex_summary, gamma_source, gex_by_expiry, gex_price_profile = _gex_map(
        filtered_chain, spot=resolved_spot, asof=chain_asof, rate=filters.risk_free_rate,
    )
    charm_by_strike, charm_summary, charm_chain_rows = _charm_map(
        filtered_chain, spot=resolved_spot, rate=filters.risk_free_rate,
    )
    # Stacked-signals lenses: theta/vanna exposure, IV surface, volume profile.
    theta_rows, theta_summary, tv_chain_rows, vanna_summary, tv_skipped = _stacked_theta_vanna(
        chain_rows=filtered_chain, spot=resolved_spot, rate=filters.risk_free_rate,
    )
    iv_surface, iv_summary = _stacked_iv_surface(
        chain_rows=filtered_chain, spot=resolved_spot,
    )
    iv_surface_by_expiry = _iv_surface_by_expiry(
        # Same clock `_gex_map` dates its by-expiry totals from, so DTE is
        # consistent across every per-expiry block in the payload.
        chain_rows=filtered_chain, spot=resolved_spot, asof=chain_asof,
    )
    volume_profile, volume_profile_summary = _stacked_volume_profile(
        price_series=price_series,
    )
    # Strongest single-strike decay and vanna pivots feed the confluence map.
    max_theta_strike = (
        max(theta_rows, key=lambda row: abs(row["net_theta_flow"]))["strike"]
        if theta_rows else None
    )
    vanna_pivot = (
        max(theta_rows, key=lambda row: abs(row["net_vanna_flow"]))["strike"]
        if theta_rows else None
    )
    confluence = _stacked_confluence(
        spot=resolved_spot,
        call_wall=gex_summary.get("call_wall"),
        put_wall=gex_summary.get("put_wall"),
        gamma_flip=gex_summary.get("gamma_flip"),
        pin_strike=gex_summary.get("pin_strike"),
        theta_decay_strike=max_theta_strike,
        vanna_pivot=vanna_pivot,
        call_iv_wall=iv_summary.get("call_iv_wall"),
        put_iv_wall=iv_summary.get("put_iv_wall"),
        poc=volume_profile_summary.get("poc") if volume_profile_summary.get("available") else None,
        value_area_low=volume_profile_summary.get("value_area_low") if volume_profile_summary.get("available") else None,
        value_area_high=volume_profile_summary.get("value_area_high") if volume_profile_summary.get("available") else None,
    )
    # Delta-weighted live volume (supporting context for the pressure gauge).
    # Uses the same BS delta as charm so the gauge components share one model.
    delta_weighted_call_vol = 0.0
    delta_weighted_put_vol = 0.0
    for row in charm_chain_rows:
        delta = row.get("delta")
        volume = float(row.get("volume") or 0.0)
        if delta is None or volume <= 0:
            continue
        if row.get("right") == "call":
            delta_weighted_call_vol += max(0.0, float(delta)) * volume
        else:
            delta_weighted_put_vol += abs(float(delta)) * volume
    charm_contracts = int(charm_summary["contracts_measured"]) + int(charm_summary["contracts_skipped"])
    pressure = _pressure_gauge(
        net_charm_flow=charm_summary["net_charm_flow"],
        net_gex_m=gex_summary["total_gex_m"],
        delta_weighted_call_vol=delta_weighted_call_vol,
        delta_weighted_put_vol=delta_weighted_put_vol,
        # Gross magnitudes normalize each channel onto a common [-1, 1] scale;
        # without them the charm term's raw units swamp everything else.
        abs_charm_flow=charm_summary["abs_charm_flow"],
        abs_gex_m=gex_summary.get("abs_gex_m"),
        # Signed order flow from the tape and the underlying's own bars are the
        # corroboration a positioning proxy needs before anyone trades on it.
        tape=tape_channel if activity_basis == "trade_tape" else None,
        underlying=_underlying_pressure(underlying_bars, asof=now) if underlying_bars else None,
        charm_coverage=(
            int(charm_summary["contracts_measured"]) / charm_contracts if charm_contracts else None
        ),
        mode_resolved=mode_resolved,
    )
    probability = _probability_context(
        filtered_chain, spot=resolved_spot, asof=chain_asof, rate=filters.risk_free_rate,
        call_wall=gex_summary["call_wall"], put_wall=gex_summary["put_wall"],
    )
    gex_history = _gex_history(
        history_chain_rows,
        filters=filters,
        asof=now,
        selected_expiry=chain_context["selected_expiry"],
    )
    # Always anchor history with the active chain snapshot so the strip is not
    # empty when only one dated folder exists under data/option_chains.
    active_day = (chain_asof.date() if chain_asof else now.date()).isoformat()
    if gex_summary and not any(str(point.get("t")) == active_day for point in gex_history):
        gex_history = list(gex_history) + [{
            "t": active_day,
            "observed_at": (chain_asof or now).isoformat(),
            "spot": round(resolved_spot, 4),
            "expiry": chain_context.get("selected_expiry"),
            "contracts": len(filtered_chain),
            "source": "active_snapshot",
            **gex_summary,
        }]
    call_premium = sum(float(row["call_premium"]) for row in flow_series)
    put_premium = sum(float(row["put_premium"]) for row in flow_series)
    total_premium = call_premium + put_premium
    signed_values = [row["signed_net_premium"] for row in flow_series if row["signed_net_premium"] is not None]
    signed_net = sum(float(value) for value in signed_values) if signed_values else None
    signed_gross = sum(float(row.get("signed_gross_premium") or 0.0) for row in flow_series)
    signed_prints = sum(int(row.get("signed_premium_observations") or 0) for row in flow_series)
    unresolved = sum(float(row["unresolved_premium"]) for row in flow_series)
    activity_imbalance = (
        (call_premium - put_premium) / total_premium if total_premium > 0 else None
    )
    activity_lean = describe_activity_lean(
        signed_net_premium=signed_net,
        signed_print_count=signed_prints,
        call_premium=call_premium,
        put_premium=put_premium,
        call_put_imbalance=activity_imbalance,
    )
    # Tape age = newest *qualifying* print (what the desk list shows).
    # Feed age = newest provider print before min-premium/volume filters so a
    # live underlier is not marked TAPE STALE just because $25k+ whales are rare.
    tape_asof = _best_observation_time(
        [_timestamp(row.get("timestamp")) for row in tape]
    )
    feed_asof = _best_observation_time([
        _timestamp(flow_rejected.get("print_ts_max")),
        _timestamp(flow_rejected.get("print_ts_min")),
        tape_asof,
    ])
    # Prefer the true max feed stamp even when it is a day-bucket if that is
    # all the provider sent; _best_observation_time already prefers precise.
    if feed_asof is None:
        feed_asof = _timestamp(flow_rejected.get("print_ts_max")) or tape_asof
    # Overall observed_at prefers live tape/feed clocks over chain capture time
    # (chain OI snapshots are often multi-day and should not drive tape lag).
    observed_at = feed_asof or tape_asof or chain_observed
    tape_age_seconds = (
        max(0.0, (now - tape_asof).total_seconds()) if tape_asof is not None else None
    )
    feed_age_seconds = (
        max(0.0, (now - feed_asof).total_seconds()) if feed_asof is not None else None
    )
    # Live lamp should follow the feed when we have trade-tape evidence at all.
    if activity_basis == "trade_tape":
        age_seconds = feed_age_seconds if feed_age_seconds is not None else tape_age_seconds
    elif tape_age_seconds is not None:
        age_seconds = tape_age_seconds
    elif observed_at is not None:
        age_seconds = max(0.0, (now - observed_at).total_seconds())
    else:
        age_seconds = None

    caveats = [
        "Call/put activity is not bought/sold direction. Signed net flow requires an explicit provider aggressor.",
        "Charting GEX uses call-positive/put-negative wall convention; squeeze theory uses short-premium dealer inventory (q=−OI). True dealer inventory is not public.",
        "Gamma squeeze direction uses post-shift signed flow and/or price momentum; unsigned call/put identity never supplies trade direction.",
        "A mid-tape flow reversal rebuilds the directional imbalance from the post-shift window; thin, stale, or just-shifted samples cannot be high-confidence.",
        "Open interest is generally a prior-session observation, so GEX is a positioning estimate rather than a live position ledger.",
        "Implied probabilities are risk-neutral diagnostics from IV, not calibrated forecasts of where the stock will trade.",
    ]
    if activity_basis == "chain_activity_proxy":
        caveats.insert(0, "No qualifying trade tape was available; activity uses provider session premium or cumulative chain volume × price and is unsigned.")

    output_warnings = list(dict.fromkeys(warnings))
    selected_dte = chain_context["selected_dte"]
    if selected_dte is not None and selected_dte < 0:
        output_warnings.append(
            f"Selected expiry passed {abs(selected_dte)} calendar day"
            f"{'s' if abs(selected_dte) != 1 else ''} ago; values are historical diagnostics only."
        )
    elif selected_dte is not None and selected_dte <= 3:
        output_warnings.append(
            f"Near-expiry ({selected_dte}D) — gamma can reprice quickly; OI is prior-session."
        )
    if filters.expiry not in {"nearest", "all"} and chain_context["selected_expiry"] and not filtered_chain:
        output_warnings.append("The selected expiry has no contracts that pass the active quality filters.")
    if flow_rejected.get("expiry_filter_relaxed"):
        output_warnings.append(
            f"The selected expiry {flow_rejected.get('requested_expiry')} had no qualified trade prints; "
            "the Flow tape widened to all expiries while GEX remained on the selected expiry."
        )
    if open_interest_source == "unavailable":
        # Say this before anything renders a zero. An OI-less chain fails the
        # min_oi floor on every contract, so the map empties and the squeeze
        # reads 0 — an artifact of a missing input, not a market observation.
        output_warnings.append(
            f"No open-interest source for this name: {len(latest_rows)} contracts were "
            "fetched but gamma exposure cannot be computed, so GEX and the squeeze "
            "score are unmeasured rather than zero. Back-fill a dated chain snapshot "
            "(tools/backfill_option_oi.py) or set the OI filter to 0 to inspect quotes only."
        )
    if flow_rejected.get("window_relaxed"):
        output_warnings.append(
            "Live tape window was auto-expanded to match provider print timestamps "
            f"({flow_rejected.get('print_ts_min')} → {flow_rejected.get('print_ts_max')}). "
            "Clear any leftover From/To history dates if this persists."
        )
    elif (
        int(flow_rejected.get("outside_range") or 0) > 0
        and not tape
        and len(flow_rows) > 0
        and activity_basis != "trade_tape"
    ):
        output_warnings.append(
            f"All {flow_rejected.get('outside_range')} trade prints fell outside the tape window "
            f"[{flow_rejected.get('window_lower')} → {flow_rejected.get('window_upper')}]. "
            f"Provider print span: {flow_rejected.get('print_ts_min')} → {flow_rejected.get('print_ts_max')}. "
            "In live mode, clear From/To dates; they are only for history chain days."
        )

    anomaly_count = sum(bool(row.get("anomaly_flags")) for row in tape)
    # summary.activity_imbalance below remains the observable call/put identity
    # mix. Squeeze direction uses post-shift signed premium, not the stale
    # full-window cumulative that stays locked after a mid-tape reversal.
    from edge.research.flow_shift import current_flow_after_shift

    flow_shift_readout = None
    if signed_observations:
        flow_shift_readout = current_flow_after_shift(
            signed_observations,
            last_age=tape_age_seconds,
            max_fresh_age=24.0 * 3600.0,
        )
        imbalance_confidence = float(flow_shift_readout.confidence)
        signed_flow_imbalance = round(float(flow_shift_readout.effective_imbalance), 6)
    else:
        imbalance_confidence = _imbalance_confidence(signed_prints)
        signed_flow_imbalance = None
    activity_shift_readout = (
        current_flow_after_shift(
            activity_observations,
            last_age=tape_age_seconds,
            max_fresh_age=24.0 * 3600.0,
        )
        if activity_observations else None
    )
    squeeze = _squeeze_readout(
        spot=resolved_spot,
        gex_summary=gex_summary,
        gex_rows=gex,
        expected_move=_number(probability.get("expected_move")),
        expected_low=_number(probability.get("expected_low")),
        expected_high=_number(probability.get("expected_high")),
        atm_iv=_number(probability.get("atm_iv")),
        horizon_days=_number(probability.get("horizon_days")),
        chain_rows=filtered_chain,
        price_series=price_series,
        directional_flow_imbalance=signed_flow_imbalance,
        imbalance_confidence=imbalance_confidence,
        asof=chain_asof,
        rate=filters.risk_free_rate,
    )
    if flow_shift_readout is not None:
        shift_payload = flow_shift_readout.to_dict()
        squeeze["flow_shift"] = shift_payload
        if isinstance(squeeze.get("theory"), dict):
            squeeze["theory"]["flow_shift"] = shift_payload
        if isinstance(squeeze.get("components"), dict):
            squeeze["components"]["flow_shift_last_index"] = flow_shift_readout.last_shift_index
            squeeze["components"]["flow_shift_kind"] = flow_shift_readout.last_shift_kind
            squeeze["components"]["flow_confidence_band"] = flow_shift_readout.confidence_band
            squeeze["components"]["flow_n_post_shift"] = flow_shift_readout.n_post_shift
    squeeze_theory = squeeze.get("theory") if isinstance(squeeze.get("theory"), Mapping) else {}
    if squeeze_theory.get("momentum_fresh") is False:
        price_age = squeeze_theory.get("momentum_price_age_days")
        output_warnings.append(
            "Price momentum is stale"
            + (f" ({price_age} calendar days old)" if price_age is not None else "")
            + "; the squeeze direction excludes momentum until fresh bars arrive."
        )
    if squeeze_theory.get("adv_available") is False:
        output_warnings.append(
            "Average dollar volume is unavailable; squeeze fuel is unmeasured and "
            "the theory score is held neutral instead of using a liquidity proxy."
        )

    return {
        "schema_version": "edge-options-intelligence-v1",
        "symbol": symbol.upper(),
        "mode_requested": mode_requested,
        "mode_resolved": mode_resolved,
        "asof_utc": now.isoformat(),
        "observed_at": observed_at.isoformat() if observed_at else None,
        "freshness": {
            # age_seconds = feed liveness for trade_tape (not filtered-whale lag).
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "feed_asof": feed_asof.isoformat() if feed_asof is not None else None,
            "feed_age_seconds": round(feed_age_seconds, 3) if feed_age_seconds is not None else None,
            "tape_asof": tape_asof.isoformat() if tape_asof is not None else None,
            "tape_age_seconds": round(tape_age_seconds, 3) if tape_age_seconds is not None else None,
        },
        "filters": asdict(filters),
        "chain_context": chain_context,
        "contract_focus": contract_focus,
        "provider": {
            "chain": chain_source, "flow": flow_source,
            "open_interest": open_interest_source,
            "activity_basis": activity_basis,
            "signed_flow_available": bool(signed_values),
        },
        "summary": {
            "spot": round(resolved_spot, 4),
            "call_premium": round(call_premium, 2),
            "put_premium": round(put_premium, 2),
            "call_put_ratio": round(call_premium / put_premium, 4) if put_premium > 0 else None,
            "activity_imbalance": round(activity_imbalance, 6) if activity_imbalance is not None else None,
            "activity_lean": activity_lean["activity_lean"],
            "activity_lean_source": activity_lean["activity_lean_source"],
            "activity_lean_label": activity_lean["activity_lean_label"],
            "decision_authorized": False,
            "signed_net_premium": round(signed_net, 2) if signed_net is not None else None,
            "signed_gross_premium": round(signed_gross, 2) if signed_gross > 0 else None,
            "signed_flow_imbalance": signed_flow_imbalance,
            "signed_flow_confidence": round(imbalance_confidence, 6),
            "signed_flow_confidence_band": (
                flow_shift_readout.confidence_band if flow_shift_readout is not None else (
                    "low" if signed_prints < 2 else "medium"
                )
            ),
            "flow_shift": flow_shift_readout.to_dict() if flow_shift_readout is not None else None,
            "activity_shift": (
                {
                    **activity_shift_readout.to_dict(),
                    "kind": "contract_activity",
                    "note": "call_plus_put_minus_persistence_not_aggressor",
                }
                if activity_shift_readout is not None else None
            ),
            "unresolved_premium": round(unresolved, 2),
            "median_spread_pct": round(median_spread_pct, 6) if median_spread_pct is not None else None,
            **gex_summary,
            "squeeze": squeeze,
        },
        "quality": {
            # Open interest is the input every gamma number depends on. LSE live
            # quotes omit it, and the cached-snapshot backfill only covers names
            # with a dated chain folder. Without it, GEX is zero because nothing
            # was observed — NOT because the market is flat — and the min_oi
            # filter then drops the whole chain. Consumers must read this flag
            # before rendering any structural figure, or a total absence of data
            # renders identically to a measured calm market.
            "gex_measurable": bool(
                (gex_summary.get("call_oi") or 0) + (gex_summary.get("put_oi") or 0) > 0
                and open_interest_source != "unavailable"
            ),
            "chain_contracts_raw": len(latest_rows),
            "chain_contracts_included": len(filtered_chain),
            "chain_rejected": chain_rejected,
            "flow_prints_raw": len(flow_rows),
            "flow_prints_included": sum(int(row["print_count"]) for row in flow_series)
            if activity_basis == "trade_tape" else 0,
            "signed_flow_prints": signed_prints,
            "flow_rejected": flow_rejected,
            "gamma_source": gamma_source,
            "anomaly_sample_size": len(tape),
        },
        "price_series": list(price_series),
        "flow_series": flow_series,
        "flow_tape": tape,
        "gex_by_strike": gex,
        "charm_by_strike": charm_by_strike,
        "chain_by_strike": charm_chain_rows,
        "charm_summary": charm_summary,
        "pressure": pressure,
        # Stacked-signals lenses — each an independent read on the same tape.
        "stacked_signals": {
            "theta_by_strike": theta_rows,
            "theta_summary": theta_summary,
            "vanna_summary": vanna_summary,
            "iv_surface": iv_surface,
            "iv_summary": iv_summary,
            # Per-expiry smiles. The blended `iv_surface` above stays as the
            # skew/wall lens; anything building a density must use this instead.
            "iv_surface_by_expiry": iv_surface_by_expiry,
            "volume_profile": volume_profile,
            "volume_profile_summary": volume_profile_summary,
            "confluence": confluence,
            "quality": {
                "theta_vanna_contracts_measured": len(tv_chain_rows),
                "theta_vanna_contracts_skipped": tv_skipped,
                "iv_strikes_measured": len(iv_surface),
                "iv_expiries_measured": len(iv_surface_by_expiry),
                "volume_profile_available": bool(volume_profile_summary.get("available")),
            },
        },
        "delta_weighted_volume": {
            "call": round(delta_weighted_call_vol, 4),
            "put": round(delta_weighted_put_vol, 4),
        },
        "oi_by_strike": [
            {
                "strike": row["strike"],
                "call_oi": int(row["call_oi"]),
                "put_oi": int(row["put_oi"]),
                "total_oi": int(row["call_oi"]) + int(row["put_oi"]),
            }
            for row in gex
        ],
        "gex_by_expiry": gex_by_expiry,
        "gex_price_profile": gex_price_profile,
        "gex_history": gex_history,
        "anomalies": {
            "count": anomaly_count,
            "method": (
                "MAD z-score ≥ 3.5 for premium/volume (minimum 8 prints); "
                "repeat cluster = ≥3 same-contract prints within 15 minutes and ≥$250K aggregate"
            ),
        },
        "probability": probability,
        "warnings": list(dict.fromkeys(output_warnings)),
        "caveats": caveats,
    }
