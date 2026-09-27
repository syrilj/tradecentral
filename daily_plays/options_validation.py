"""Fail-closed execution validation for normalized option legs and structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from typing import Any, Mapping, Sequence

OCC_RE = re.compile(r"^[A-Z0-9]{1,6}\d{6}[CP]\d{8}$")


@dataclass(frozen=True)
class OptionsPolicy:
    max_quote_age_seconds: int = 30
    min_dte: int = 30
    max_dte: int = 60
    max_spread_pct: float = 0.10
    min_open_interest: int = 500
    min_volume: int = 50
    multiplier: int = 100
    min_abs_delta: float = 0.40
    max_abs_delta: float = 0.60
    max_position_risk_pct: float = 0.005
    max_underlying_risk_pct: float = 0.01
    max_aggregate_open_risk_pct: float = 0.03
    shadow_only: bool = True


@dataclass(frozen=True)
class ValidationResult:
    eligible: bool
    state: str
    failed_checks: tuple[str, ...]
    leg: Mapping[str, Any] | None = None
    max_loss_dollars: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "failed_checks": list(self.failed_checks)}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value)
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def validate_underlying_quote(
    snapshot: Mapping[str, Any], *, asof_utc: datetime, max_age_seconds: int
) -> tuple[str, ...]:
    """Require an independently timestamped, positive underlying quote."""
    failures: list[str] = []
    underlying = snapshot.get("underlying")
    if not isinstance(underlying, Mapping):
        return ("missing_underlying_quote",)
    price = _finite_float(underlying.get("price"))
    if price is None or price <= 0:
        failures.append("missing_underlying_price")
    observed = _parse_time(underlying.get("quote_asof_utc"))
    if observed is None:
        failures.append("missing_underlying_quote_timestamp")
    else:
        age = (asof_utc.astimezone(timezone.utc) - observed).total_seconds()
        if age < 0 or age > max_age_seconds:
            failures.append("stale_underlying_quote")
    return tuple(failures)


def generate_occ_symbol(*, underlying: Any, expiry: Any, right: Any, strike: Any) -> str | None:
    """Build an OCC symbol only from explicit listed fields, never estimates."""
    root = str(underlying or "").upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{1,6}", root):
        return None
    try:
        expiry_date = date.fromisoformat(str(expiry)[:10])
        strike_int = (Decimal(str(strike)) * Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation):
        return None
    if strike_int < 0 or strike_int > 99_999_999:
        return None
    code = {"call": "C", "c": "C", "put": "P", "p": "P"}.get(str(right or "").lower())
    return f"{root}{expiry_date:%y%m%d}{code}{int(strike_int):08d}" if code else None


def validate_occ_identity(leg: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    generated = generate_occ_symbol(underlying=leg.get("underlying"), expiry=leg.get("expiry"),
                                    right=leg.get("right"), strike=leg.get("strike"))
    supplied = str(leg.get("occ_symbol") or "").upper().strip()
    failures: list[str] = []
    if not generated:
        failures.append("missing_or_invalid_listed_identity")
    if supplied and not OCC_RE.fullmatch(supplied):
        failures.append("invalid_occ_symbol")
    if supplied and generated and supplied != generated:
        failures.append("occ_symbol_does_not_match_listed_fields")
    # A syntactically generated OSI/OCC string is useful only as a consistency
    # check.  Execution requires the exact identifier supplied by the listing
    # or quote provider; strike and expiry are not enough to prove identity.
    if not supplied:
        failures.append("missing_occ_symbol")
    return supplied or None, tuple(failures)


def validate_leg(leg: Mapping[str, Any], *, asof_utc: datetime, policy: OptionsPolicy = OptionsPolicy(),
                 require_live_primary: bool = True) -> ValidationResult:
    """Validate one executable leg. Any uncertainty is a failed execution gate."""
    failures = list(validate_occ_identity(leg)[1])
    normalized = dict(leg)
    occ, _ = validate_occ_identity(leg)
    if occ:
        normalized["occ_symbol"] = occ
    quote_time = _parse_time(leg.get("quote_asof_utc"))
    if quote_time is None:
        failures.append("missing_quote_timestamp")
    else:
        age = (asof_utc.astimezone(timezone.utc) - quote_time).total_seconds()
        if age < 0 or age > policy.max_quote_age_seconds:
            failures.append("stale_quote")
    try:
        bid, ask = float(leg.get("bid")), float(leg.get("ask"))
    except (TypeError, ValueError):
        bid = ask = -1.0
        failures.append("missing_bid_or_ask")
    if bid <= 0:
        failures.append("zero_or_negative_bid")
    if ask <= 0:
        failures.append("zero_or_negative_ask")
    if bid > ask:
        failures.append("crossed_market")
    mid = (bid + ask) / 2 if bid >= 0 and ask >= 0 else 0.0
    if mid <= 0:
        failures.append("nonpositive_mid")
    elif (ask - bid) / mid > policy.max_spread_pct:
        failures.append("excessive_spread")
    try:
        expiry = date.fromisoformat(str(leg.get("expiry"))[:10])
        dte = (expiry - asof_utc.date()).days
        normalized["dte"] = dte
        # Expiry is authoritative.  A provider-supplied DTE is only a
        # convenience field and must not silently override the run clock.
        if leg.get("dte") is not None and int(leg["dte"]) != dte:
            failures.append("dte_mismatch")
        if not policy.min_dte <= dte <= policy.max_dte:
            failures.append("dte_out_of_range")
    except (TypeError, ValueError):
        failures.append("invalid_expiry")
    for field, minimum, code in (("open_interest", policy.min_open_interest, "insufficient_open_interest"),
                                 ("volume", policy.min_volume, "insufficient_volume")):
        try:
            if int(leg.get(field)) < minimum:
                failures.append(code)
        except (TypeError, ValueError):
            failures.append(code)
    if require_live_primary and (leg.get("provider") != "lse" or bool(leg.get("degraded"))):
        failures.append("non_live_or_degraded_provider")
    # Adjusted contracts can have non-standard deliverables.  Their economics
    # cannot be inferred from a standard OCC option contract, so shadow policy
    # deliberately abstains until an explicit corporate-action model exists.
    adjustment_values = [
        leg.get(field)
        for field in ("split_adjusted", "adjusted", "is_adjusted", "corporate_action_adjusted")
        if leg.get(field) is not None
    ]
    if not adjustment_values and leg.get("deliverable") is None:
        failures.append("missing_contract_adjustment_metadata")
    if any(bool(value) for value in adjustment_values):
        failures.append("split_adjusted_contract")
    try:
        multiplier = int(leg.get("multiplier"))
        if multiplier != policy.multiplier:
            failures.append("nonstandard_contract_multiplier")
    except (TypeError, ValueError):
        failures.append("nonstandard_contract_multiplier")
    failures = tuple(dict.fromkeys(failures))
    return ValidationResult(not failures, "ENTER" if not failures else "ABSTAIN", failures, normalized)


def validate_structure(legs: Sequence[Mapping[str, Any]], *, asof_utc: datetime, max_loss_dollars: float,
                       policy: OptionsPolicy = OptionsPolicy(), degraded: bool = False) -> ValidationResult:
    """Validate all legs using conservative executable prices, never midpoint fills."""
    failures: list[str] = ["degraded_provider" ] if degraded else []
    normalized: list[Mapping[str, Any]] = []
    debit = 0.0
    for leg in legs:
        result = validate_leg(leg, asof_utc=asof_utc, policy=policy, require_live_primary=True)
        failures.extend(result.failed_checks)
        normalized.append(result.leg or leg)
        try:
            # Long entries pay the offer; credits receive the bid.  Midpoint
            # calculations are diagnostic only and must never pass a gate.
            debit += float(leg["ask"]) if str(leg.get("side", "buy")).lower() == "buy" else -float(leg["bid"])
        except (KeyError, TypeError, ValueError):
            failures.append("cannot_recompute_debit")
    computed_loss = debit * policy.multiplier
    if not legs:
        failures.append("no_legs")
    if computed_loss <= 0:
        failures.append("nonpositive_or_undefined_debit")
    if computed_loss > max_loss_dollars:
        failures.append("risk_budget_exceeded")
    failures = tuple(dict.fromkeys(failures))
    return ValidationResult(not failures, "ENTER" if not failures else "ABSTAIN", failures,
                            {"legs": normalized, "debit_per_share": debit}, computed_loss)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _selection_failures(leg: Mapping[str, Any], *, policy: OptionsPolicy,
                        promotion_eligible: bool) -> tuple[str, ...]:
    """Return requirements that apply specifically to a directional long option."""
    failures: list[str] = []
    delta = _finite_float(leg.get("delta"))
    if delta is None or not policy.min_abs_delta <= abs(delta) <= policy.max_abs_delta:
        failures.append("missing_or_out_of_range_delta")
    # A promotion-eligible option record requires a usable IV observation.  We
    # do not synthesize Greeks or IV from a quote because that hides provider
    # outages and changes the meaning of the recorded decision.
    if promotion_eligible:
        iv = _finite_float(leg.get("iv"))
        if iv is None or iv <= 0:
            failures.append("missing_or_invalid_iv")
        gamma = _finite_float(leg.get("gamma"))
        if gamma is None or gamma < 0:
            failures.append("missing_or_invalid_gamma")
    return tuple(failures)


def select_directional_contract(
    contracts: Sequence[Mapping[str, Any]], *, direction: str, asof_utc: datetime,
    account_value: float, existing_underlying_risk_dollars: float = 0.0,
    aggregate_open_risk_dollars: float = 0.0, policy: OptionsPolicy = OptionsPolicy(),
    promotion_eligible: bool = True,
) -> ValidationResult:
    """Select exactly one listed long call/put using frozen shadow-risk gates.

    This function only evaluates normalized contract mappings; it intentionally
    has no provider or broker dependency.  A selected contract represents one
    long option, whose defined maximum loss is its offer price times multiplier.
    """
    wanted = {"long": "call", "short": "put"}.get(str(direction).lower())
    if wanted is None:
        return ValidationResult(False, "ABSTAIN", ("invalid_direction",))
    account = _finite_float(account_value)
    underlying_risk = _finite_float(existing_underlying_risk_dollars)
    aggregate_risk = _finite_float(aggregate_open_risk_dollars)
    if account is None or account <= 0 or underlying_risk is None or underlying_risk < 0 or aggregate_risk is None or aggregate_risk < 0:
        return ValidationResult(False, "ABSTAIN", ("invalid_risk_inputs",))

    candidates: list[tuple[tuple[float, float, str], Mapping[str, Any], float]] = []
    failures: list[str] = []
    matching = [leg for leg in contracts if str(leg.get("right") or "").lower() == wanted]
    if not matching:
        return ValidationResult(False, "ABSTAIN", ("no_listed_contract_for_direction",))
    for raw in matching:
        result = validate_leg(raw, asof_utc=asof_utc, policy=policy, require_live_primary=True)
        candidate_failures = [*result.failed_checks, *_selection_failures(raw, policy=policy,
                                                                            promotion_eligible=promotion_eligible)]
        ask = _finite_float(raw.get("ask"))
        multiplier = _finite_float(raw.get("multiplier"))
        premium_risk = ask * multiplier if ask is not None and multiplier is not None else None
        if premium_risk is None or premium_risk <= 0:
            candidate_failures.append("cannot_compute_premium_risk")
        else:
            if premium_risk > account * policy.max_position_risk_pct:
                candidate_failures.append("position_risk_budget_exceeded")
            if underlying_risk + premium_risk > account * policy.max_underlying_risk_pct:
                candidate_failures.append("underlying_risk_budget_exceeded")
            if aggregate_risk + premium_risk > account * policy.max_aggregate_open_risk_pct:
                candidate_failures.append("aggregate_risk_budget_exceeded")
        candidate_failures = list(dict.fromkeys(candidate_failures))
        if candidate_failures:
            failures.extend(candidate_failures)
            continue
        delta = abs(_finite_float(raw.get("delta")) or 0.0)
        occ, _ = validate_occ_identity(raw)
        candidates.append(((abs(delta - 0.50), ask or float("inf"), occ or ""), result.leg or raw, premium_risk))

    if not candidates:
        return ValidationResult(False, "ABSTAIN", tuple(dict.fromkeys(failures or ["no_eligible_contract_for_direction"])))
    _, selected, premium_risk = min(candidates, key=lambda row: row[0])
    return ValidationResult(True, "ENTER", (), selected, premium_risk)
