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
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


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
        if not 1 <= self.tape_limit <= 500:
            raise ValueError("tape_limit must be in [1, 500]")
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


def _bs_gamma(*, spot: float, strike: float, years: float, iv: float, rate: float) -> float | None:
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi) / (spot * iv * root_t)


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
    observed = _timestamp(_first(row, "captured_utc", "asof_utc", "timestamp", "updated_at"))
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
    for row in included:
        expiry = row["expiry"]
        expiry_counts[expiry] = expiry_counts.get(expiry, 0) + 1

    available = sorted(expiry_counts)
    selection_day = selection_date or asof.date()
    selected: date | None = None
    if filters.expiry == "nearest":
        unexpired = [expiry for expiry in available if expiry >= selection_day]
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
        "available_expiries": [
            {
                "expiry": expiry.isoformat(),
                "dte": (expiry - selection_day).days,
                "snapshot_dte": (expiry - asof.date()).days,
                "contracts": expiry_counts[expiry],
            }
            for expiry in available
        ],
    }
    return included, rejected, context


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


def _normalize_flow_row(row: Mapping[str, Any], fallback_spot: float | None = None) -> dict[str, Any] | None:
    right = _right(_first(row, "contract_type", "option_type", "right", "type"))
    observed = _timestamp(_first(row, "ts", "timestamp", "datetime", "time", "last_trade_at", "updated_at"))
    volume = _integer(_first(row, "volume", "volume_today", "size", "contracts", "quantity")) or 0
    price = _number(_first(row, "price", "last_price", "trade_price", "fill_price", "mid"))
    premium = _number(_first(row, "premium", "total_premium", "est_premium", "notional"))
    multiplier = _integer(_first(row, "multiplier", "contract_multiplier"))
    estimated = False
    price_estimated = False
    if premium is None and price is not None and volume > 0 and multiplier is not None:
        premium = price * volume * multiplier
        estimated = True
    if price is None and premium is not None and volume > 0 and multiplier is not None:
        # Back out per-contract fill only when the contract multiplier is known.
        price = premium / (volume * multiplier)
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
    expiry = _expiry(_first(row, "expiry", "expiration", "expiration_date"))
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
    return {
        "timestamp": observed,
        "right": right,
        "premium": premium,
        "volume": volume,
        # contracts == volume for options tape (lot size = contract count).
        "contracts": volume,
        "contract_multiplier": multiplier,
        "price": round(price, 4) if price is not None else None,
        "price_estimated": price_estimated,
        "strike": strike,
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
    volumes = [float(row["volume"]) for row in tape]
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
        volume = float(row["volume"])
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


def _flow_series(
    flow_rows: Sequence[Mapping[str, Any]],
    *,
    filters: OptionsFilters,
    asof: datetime,
    selected_expiry: str | None,
    mode_requested: str = "live",
    spot: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
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
    for row in tape_rows:
        row["timestamp"] = row["timestamp"].isoformat()
        row["expiry"] = row["expiry"].isoformat() if row["expiry"] else None
    return series, tape_rows[: filters.tape_limit], rejected


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
        grid: list[tuple[float, float]] = []
        # ±20% in 0.5% steps — same band used for zero-gamma search; also the
        # IF-style "gamma price profile" (projected net GEX at each test spot).
        for i in range(81):
            test_spot = spot * (0.80 + i * 0.005)
            total = 0.0
            for row in enriched:
                gamma = _bs_gamma(
                    spot=test_spot, strike=float(row["strike"]), years=float(row["years"]),
                    iv=float(row["iv"] or 0), rate=rate,
                )
                if gamma is not None:
                    total += row["sign"] * gamma * row["oi"] * row["multiplier"] * test_spot * test_spot * 0.01
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
        if crossings:
            flip = min(crossings, key=lambda value: abs(value - spot))

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
        "pin_strike": pin["strike"] if pin else None,
    }
    return mapped, summary, gamma_source, gex_by_expiry, price_profile


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


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
    """
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
        # Contribution for this side: only count when signed with side.
        # Components are already in point units matching factor maxes; clamp.
        contrib = max(0.0, raw_c * side_sign)
        if key == "regime_score":
            # regime_score is signed fuel contribution (~0..20); map onto 0..max_pts.
            pts = int(round(min(max_pts, abs(contrib) * (max_pts / 20.0))))
        else:
            pts = int(round(min(max_pts, abs(contrib))))
        factors.append({
            "id": key,
            "label": label,
            "score": pts,
            "max": max_pts,
            "detail": f"{detail} · raw={raw_c:+.1f}",
        })
        factor_sum += pts
        max_sum += max_pts

    # Board score = factor fill ratio → 0..100 (IF-style probability board).
    score = int(round(100.0 * factor_sum / max_sum)) if max_sum else 0
    score = max(0, min(100, score))
    likelihood = _likelihood(score)

    setup_analysis = [
        f"Near-spot net GEX ${near_net:.2f}M · total ${net_dealer:.2f}M · fuel {fuel:.0%}",
    ]
    if wall_level is not None:
        setup_analysis.append(
            f"{'Call' if side == 'bullish' else 'Put'} wall ${wall_level:,.2f}"
            + (f" ({wall_pct:+.2%})" if wall_pct is not None else "")
        )
    if dampened or fuel <= 0:
        setup_analysis.append("Long / flat gamma environment — dampens squeeze (structure still shown)")
    if abs(signed_score) >= 20:
        setup_analysis.append(f"gex_core signed score supports {side} ({signed_score:+.1f})")
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
    if near_net == 0.0:
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
    }
    scored_components = dict(structure["squeeze_components"])
    fuel = float(theory.get("squeeze_risk") or 0.0)
    # Dampened only when charting near-spot GEX is positive *and* theory fuel is weak
    dampened = bool(structure.get("long_gamma_dampened")) and fuel < 1e-6
    short_gex = theory.get("short_premium_gex_m") or {}

    bullish = _clamp01(float(theory.get("bullish_ui") or 0.0) / 100.0)
    bearish = _clamp01(float(theory.get("bearish_ui") or 0.0) / 100.0)

    core_label = str(theory["squeeze_label"])
    if core_label == "bullish_squeeze":
        label = "bullish_squeeze" if signed >= 40 else "bullish_lean"
        primary = "bullish"
    elif core_label == "bearish_squeeze":
        label = "bearish_squeeze" if signed <= -40 else "bearish_lean"
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
    if abs(call_imb) >= 0.1:
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
        fuel=min(1.0, fuel * 10.0) if fuel > 0 else float(structure.get("negative_fuel") or 0.0),
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
        fuel=min(1.0, fuel * 10.0) if fuel > 0 else float(structure.get("negative_fuel") or 0.0),
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
            "bullish_score_raw": theory.get("bullish_score_raw"),
            "bearish_score_raw": theory.get("bearish_score_raw"),
            "bullish_ui": theory.get("bullish_ui"),
            "bearish_ui": theory.get("bearish_ui"),
            "short_premium_gex_m": short_gex,
            "adv_m": theory.get("adv_m"),
            "adv_available": theory.get("adv_available"),
            "measurable": theory.get("measurable"),
            "directional_flow_imbalance": theory.get("directional_flow_imbalance"),
            "momentum": theory.get("momentum"),
            "momentum_fresh": momentum_fresh,
            "momentum_price_age_days": price_age_days,
            "label": theory.get("squeeze_label"),
        },
        "structure_score": structure.get("squeeze_score"),
        "structure_label": structure.get("squeeze_label"),
        "long_gamma_dampened": dampened,
        "negative_fuel": round(min(1.0, fuel * 10.0), 4) if fuel > 0 else float(structure.get("negative_fuel") or 0.0),
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


def build_options_intelligence(
    *, symbol: str, chain_rows: Sequence[Mapping[str, Any]], flow_rows: Sequence[Mapping[str, Any]],
    price_series: Sequence[Mapping[str, Any]], spot: float | None, filters: OptionsFilters,
    mode_requested: str, mode_resolved: str, chain_source: str, flow_source: str,
    asof_utc: datetime | None = None, warnings: Iterable[str] = (),
    open_interest_source: str = "provider",
    history_chain_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create the dashboard payload without manufacturing missing observations."""
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
    filtered_chain, chain_rejected, chain_context = _filter_chain(
        latest_rows,
        asof=chain_asof,
        spot=resolved_spot,
        filters=filters,
        selection_date=now.date() if mode_requested == "live" else chain_asof.date(),
    )
    spread_samples = [row["spread_pct"] for row in filtered_chain if row["spread_pct"] is not None]
    median_spread_pct = median(spread_samples) if spread_samples else None
    flow_series, tape, flow_rejected = _flow_series(
        flow_rows,
        filters=filters,
        asof=now,
        selected_expiry=chain_context["selected_expiry"],
        mode_requested=mode_requested,
        spot=resolved_spot,
    )
    activity_basis = "trade_tape"
    if not flow_series:
        flow_series = _chain_activity_series(chain_rows, filters=filters, asof=now)
        activity_basis = "chain_activity_proxy" if flow_series else "unavailable"

    gex, gex_summary, gamma_source, gex_by_expiry, gex_price_profile = _gex_map(
        filtered_chain, spot=resolved_spot, asof=chain_asof, rate=filters.risk_free_rate,
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
    observed_times = [
        value for value in [chain_observed, *(
            _timestamp(row.get("timestamp")) for row in tape
        )] if value is not None
    ]
    observed_at = max(observed_times, default=chain_observed)
    age_seconds = max(0.0, (now - observed_at).total_seconds()) if observed_at else None

    caveats = [
        "Call/put activity is not bought/sold direction. Signed net flow requires an explicit provider aggressor.",
        "Charting GEX uses call-positive/put-negative wall convention; squeeze theory uses short-premium dealer inventory (q=−OI). True dealer inventory is not public.",
        "Gamma squeeze direction uses explicitly signed flow and/or price momentum; unsigned call/put identity never supplies trade direction.",
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
    # mix. The squeeze direction uses only signed premium and shrinks a thin
    # signed sample toward neutral.
    imbalance_confidence = _imbalance_confidence(signed_prints)
    signed_flow_imbalance = (
        round((float(signed_net) / signed_gross) * imbalance_confidence, 6)
        if signed_net is not None and signed_gross > 0
        else None
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
        "freshness": {"age_seconds": round(age_seconds, 3) if age_seconds is not None else None},
        "filters": asdict(filters),
        "chain_context": chain_context,
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
            "activity_imbalance": round((call_premium - put_premium) / total_premium, 6) if total_premium > 0 else None,
            "signed_net_premium": round(signed_net, 2) if signed_net is not None else None,
            "signed_gross_premium": round(signed_gross, 2) if signed_gross > 0 else None,
            "signed_flow_imbalance": signed_flow_imbalance,
            "signed_flow_confidence": round(imbalance_confidence, 6),
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
