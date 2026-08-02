"""Shadow-only option lifecycle evidence and conservative replay accounting.

The module records hypothetical positions only.  It deliberately exposes no
broker, order, account, or routing integration.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .contracts import canonical_json
from .options_validation import generate_occ_symbol


DEFAULT_QUOTE_MAX_AGE_SECONDS = 30
_ADJUSTMENT_FIELDS = ("split_adjusted", "adjusted", "is_adjusted", "corporate_action_adjusted")
_EXIT_REASONS = {"expiration", "time_horizon", "signal_invalidation", "risk_limit", "manual_shadow_close"}


class OptionQuoteProvider(Protocol):
    def quote_for(self, *, position: Mapping[str, Any], asof_utc: datetime) -> Mapping[str, Any] | None: ...


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("missing_quote_timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("missing_quote_timestamp")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any, *, code: str, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(code)
    return result


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            result.append(row)
    return result


def _append_unique(path: Path, rows: Sequence[Mapping[str, Any]], *, key: str) -> int:
    existing = {str(row.get(key)) for row in _rows(path) if row.get(key) is not None}
    fresh = [dict(row) for row in rows if str(row.get(key)) not in existing]
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(canonical_json(row) + "\n")
    return len(fresh)


def _adjustment_status(quote: Mapping[str, Any], *, multiplier: int) -> dict[str, Any]:
    if any(bool(quote.get(field)) for field in _ADJUSTMENT_FIELDS):
        raise ValueError("split_adjusted_contract")
    if multiplier != 100:
        raise ValueError("nonstandard_contract_multiplier")
    return {"adjustment_status": "standard", "split_adjusted": False, "multiplier": multiplier}


def _quote_evidence(quote: Mapping[str, Any], *, asof_utc: datetime, max_quote_age_seconds: int,
                    identity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate a mark without estimating unavailable market fields."""
    required_identity = identity or quote
    occ = str(quote.get("occ_symbol") or "").upper().strip()
    generated = generate_occ_symbol(underlying=required_identity.get("underlying"), expiry=required_identity.get("expiry"),
                                    right=required_identity.get("right"), strike=required_identity.get("strike"))
    if not occ or not generated or occ != generated:
        raise ValueError("invalid_or_mismatched_occ_identity")
    if identity is not None and occ != str(identity.get("occ_symbol") or "").upper().strip():
        raise ValueError("occ_symbol_does_not_match_open_position")
    if quote.get("provider") != "lse" or bool(quote.get("degraded")):
        raise ValueError("non_live_or_degraded_provider")
    quote_time = _timestamp(quote.get("quote_asof_utc"))
    age = (asof_utc - quote_time).total_seconds()
    if age < 0 or age > max_quote_age_seconds:
        raise ValueError("stale_quote")
    bid = _number(quote.get("bid"), code="missing_bid_or_ask", positive=True)
    ask = _number(quote.get("ask"), code="missing_bid_or_ask", positive=True)
    if bid > ask:
        raise ValueError("crossed_market")
    mid = (bid + ask) / 2
    delta = _number(quote.get("delta"), code="unavailable_greeks")
    gamma = _number(quote.get("gamma"), code="unavailable_greeks")
    if not -1 <= delta <= 1 or gamma < 0:
        raise ValueError("unavailable_greeks")
    iv = _number(quote.get("iv"), code="missing_or_invalid_iv", positive=True)
    try:
        multiplier = int(quote.get("multiplier"))
    except (TypeError, ValueError) as exc:
        raise ValueError("nonstandard_contract_multiplier") from exc
    adjustment = _adjustment_status(quote, multiplier=multiplier)
    greeks = {"delta": delta, "gamma": gamma}
    for field in ("theta", "vega", "rho"):
        if quote.get(field) is not None:
            greeks[field] = _number(quote.get(field), code="unavailable_greeks")
    return {"occ_symbol": occ, "bid": bid, "ask": ask, "mid": mid, "iv": iv, "greeks": greeks,
            "quote_asof_utc": _iso(quote_time), "provider": "lse", "corporate_action": adjustment}


def build_option_entry(play: Mapping[str, Any], *, asof_utc: datetime,
                       max_quote_age_seconds: int = DEFAULT_QUOTE_MAX_AGE_SECONDS) -> dict[str, Any] | None:
    """Create an immutable one-contract shadow entry from an ENTER play."""
    if str(play.get("state")) != "ENTER":
        return None
    legs = play.get("legs")
    if not isinstance(legs, list) or len(legs) != 1:
        raise ValueError("option_entry_requires_exactly_one_leg")
    leg = legs[0]
    if not isinstance(leg, Mapping) or str(leg.get("side") or "").lower() != "buy":
        raise ValueError("unsupported_non_long_option")
    play_id = str(play.get("play_id") or "")
    if not play_id:
        raise ValueError("missing_play_id")
    evidence = _quote_evidence(leg, asof_utc=asof_utc, max_quote_age_seconds=max_quote_age_seconds)
    expiry = str(leg.get("expiry") or "")[:10]
    try:
        date.fromisoformat(expiry)
        strike = _number(leg.get("strike"), code="invalid_or_mismatched_occ_identity", positive=True)
    except ValueError as exc:
        raise ValueError("invalid_or_mismatched_occ_identity") from exc
    premium = evidence["ask"] * evidence["corporate_action"]["multiplier"]
    return {"schema_version": "shadow-option-position-v1", "position_id": play_id, "play_id": play_id,
            "status": "OPEN_SHADOW", "shadow_only": True, "broker_order_id": None,
            "occ_symbol": evidence["occ_symbol"], "underlying": str(leg.get("underlying") or "").upper(),
            "right": str(leg.get("right") or "").lower(), "expiry": expiry, "strike": strike,
            "multiplier": evidence["corporate_action"]["multiplier"], "entry_nbbo": evidence,
            "entry_fill_per_share": evidence["ask"], "entry_premium_dollars": premium,
            "entry_asof_utc": evidence["quote_asof_utc"], "corporate_action": evidence["corporate_action"]}


def append_option_entries(*, output_root: str | Path, plays: Sequence[Mapping[str, Any]], asof_utc: datetime,
                          max_quote_age_seconds: int = DEFAULT_QUOTE_MAX_AGE_SECONDS) -> dict[str, Any]:
    """Persist valid shadow entries once and make invalid tickets auditable abstentions."""
    root = Path(output_root)
    entries: list[dict[str, Any]] = []; errors: list[dict[str, Any]] = []
    for play in plays:
        if not isinstance(play, Mapping) or not play.get("legs"):
            continue
        play_id = str(play.get("play_id") or "")
        try:
            entry = build_option_entry(play, asof_utc=asof_utc, max_quote_age_seconds=max_quote_age_seconds)
            if entry is not None:
                entries.append(entry)
        except ValueError as exc:
            errors.append({"event_id": f"entry:{play_id}:{exc}", "play_id": play_id, "event": "ENTRY_ABSTAIN",
                           "status": "UNRESOLVED", "reason": str(exc), "asof_utc": _iso(asof_utc)})
    written = _append_unique(root / "shadow_option_positions.jsonl", entries, key="position_id")
    _append_unique(root / "shadow_option_lifecycle.jsonl", errors, key="event_id")
    return {"entered": written, "entry_abstentions": len(errors)}


def _provider_quote(provider: OptionQuoteProvider | Any, position: Mapping[str, Any], asof_utc: datetime) -> Mapping[str, Any] | None:
    if hasattr(provider, "quote_for"):
        return provider.quote_for(position=position, asof_utc=asof_utc)
    if callable(provider):
        return provider(position=position, asof_utc=asof_utc)
    raise TypeError("option quote provider must implement quote_for or be callable")


def _pnl_dollars(position: Mapping[str, Any], bid: float) -> float:
    return (bid - float(position["entry_fill_per_share"])) * int(position["multiplier"])


def mark_open_option_positions(*, output_root: str | Path, provider: OptionQuoteProvider | Any,
                               asof_utc: datetime, max_quote_age_seconds: int = DEFAULT_QUOTE_MAX_AGE_SECONDS) -> dict[str, Any]:
    """Append one daily conservative mark per open shadow option and close valid expiries."""
    if asof_utc.tzinfo is None or asof_utc.utcoffset() is None:
        raise ValueError("asof_utc must be timezone-aware")
    now = asof_utc.astimezone(timezone.utc)
    root = Path(output_root); positions = _rows(root / "shadow_option_positions.jsonl")
    outcomes = _rows(root / "shadow_option_outcomes.jsonl")
    closed = {str(row.get("position_id")) for row in outcomes if row.get("status") == "CLOSED"}
    prior_marks = _rows(root / "shadow_option_marks.jsonl")
    marks: list[dict[str, Any]] = []; lifecycle: list[dict[str, Any]] = []; new_outcomes: list[dict[str, Any]] = []
    marked = unresolved = closed_count = 0
    for position in positions:
        position_id = str(position.get("position_id") or "")
        if not position_id or position_id in closed:
            continue
        day = now.date().isoformat(); mark_id = f"{position_id}:{day}"
        try:
            quote = _provider_quote(provider, position, now)
            if not isinstance(quote, Mapping):
                raise ValueError("provider_outage_or_quote_unavailable")
            evidence = _quote_evidence(quote, asof_utc=now, max_quote_age_seconds=max_quote_age_seconds, identity=position)
            mark = {"schema_version": "shadow-option-mark-v1", "mark_id": mark_id, "position_id": position_id,
                    "play_id": position["play_id"], "status": "MARKED", "mark_asof_utc": _iso(now),
                    "nbbo": evidence, "conservative_value_dollars": evidence["bid"] * int(position["multiplier"]),
                    "unrealized_pnl_dollars": _pnl_dollars(position, evidence["bid"])}
            marks.append(mark); marked += 1
            requested_exit = str(quote.get("exit_reason") or "")
            expired = now.date() >= date.fromisoformat(str(position["expiry"]))
            exit_reason = "expiration" if expired else requested_exit
            if exit_reason:
                if exit_reason not in _EXIT_REASONS:
                    raise ValueError("invalid_exit_reason")
                pnl_values = [_pnl_dollars(position, float(row.get("nbbo", {}).get("bid")))
                              for row in prior_marks if row.get("position_id") == position_id]
                pnl_values.append(mark["unrealized_pnl_dollars"])
                new_outcomes.append({"schema_version": "shadow-option-outcome-v1", "outcome_id": position_id,
                    "position_id": position_id, "play_id": position["play_id"], "status": "CLOSED", "shadow_only": True,
                    "instrument": "option", "occ_symbol": position["occ_symbol"], "exit_reason": exit_reason,
                    "exit_nbbo": evidence, "exit_fill_per_share": evidence["bid"], "entry_fill_per_share": position["entry_fill_per_share"],
                    "realized_pnl_dollars": mark["unrealized_pnl_dollars"], "gross_return_pct": mark["unrealized_pnl_dollars"] / float(position["entry_premium_dollars"]) * 100,
                    "outcome": mark["unrealized_pnl_dollars"] > 0, "mae_dollars": min(0.0, min(pnl_values)),
                    "mfe_dollars": max(0.0, max(pnl_values)), "outcome_asof_utc": evidence["quote_asof_utc"],
                    "corporate_action": evidence["corporate_action"]})
                closed_count += 1
        except (ValueError, TypeError, KeyError) as exc:
            unresolved += 1
            lifecycle.append({"event_id": f"unresolved:{mark_id}:{exc}", "position_id": position_id,
                              "play_id": position.get("play_id"), "event": "MARK_UNRESOLVED", "status": "UNRESOLVED",
                              "reason": str(exc), "asof_utc": _iso(now)})
    written_marks = _append_unique(root / "shadow_option_marks.jsonl", marks, key="mark_id")
    _append_unique(root / "shadow_option_lifecycle.jsonl", lifecycle, key="event_id")
    written_outcomes = _append_unique(root / "shadow_option_outcomes.jsonl", new_outcomes, key="outcome_id")
    return {"status": "COMPLETE", "marked": written_marks, "closed": written_outcomes, "unresolved": unresolved,
            "positions": len(positions), "marks_path": str(root / "shadow_option_marks.jsonl"),
            "outcomes_path": str(root / "shadow_option_outcomes.jsonl")}
