"""Union options-board structure and unusual-flow attention into one ranked list.

Pure computation: callers supply already-computed board/flow rows (from the
cached `/api/options/board` and `/api/unusual-flow` payload builders) and get
back a gated, ordinally-ranked union. No network or filesystem I/O here.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import math
from statistics import fmean, pstdev
from typing import Any, Mapping

from .options_intelligence import OptionsFilters

SCHEMA_VERSION = "edge-live-opportunities-v1"
SCORE_KIND = "ordinal_composite"
MAX_LIVE_AGE_SECONDS = 180.0
HIGH_CONFIDENCE_THRESHOLD = 0.65
MODERATE_CONFIDENCE_THRESHOLD = 0.55
MAX_ACCOUNT_RISK_PCT = 0.005
MAX_PORTFOLIO_HEAT_PCT = 0.02


def _clean_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text.split()[0] if text else ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _index_by_symbol(rows: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = _clean_symbol(row.get("symbol"))
        if symbol:
            indexed.setdefault(symbol, row)
    return indexed


def _zscores(values: Mapping[str, float]) -> dict[str, float]:
    """Cross-sectional z-score over the symbols where this signal is present.

    Fewer than two observations (or a degenerate zero-spread set) cannot
    support a spread estimate, so every member reports 0 rather than an
    inflated or fabricated deviation.
    """
    if len(values) < 2:
        return {symbol: 0.0 for symbol in values}
    mean = fmean(values.values())
    spread = pstdev(values.values())
    if spread <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (value - mean) / spread for symbol, value in values.items()}


def _age_seconds(value: Any, now_utc: datetime) -> float | None:
    """Age of an ISO timestamp, or ``None`` when freshness is unknowable."""
    if not value:
        return None
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0.0, (now_utc - observed.astimezone(timezone.utc)).total_seconds())


def _effective_age(
    *, observed_at: Any, reported_age: Any, cache_age_seconds: float, now_utc: datetime,
) -> float | None:
    observed_age = _age_seconds(observed_at, now_utc)
    reported = _finite(reported_age)
    if reported is not None:
        reported = max(0.0, reported + max(0.0, cache_age_seconds))
    measured = [value for value in (observed_age, reported) if value is not None]
    return max(measured) if measured else None


def _confidence(
    board: Mapping[str, Any], flow: Mapping[str, Any], calibrated: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose confidence only when an upstream source explicitly calibrated it.

    The cross-sectional composite is deliberately excluded: a z-score rank is
    not a probability, no matter how large it looks on a dashboard.
    """
    probability = None
    source = None
    setup_ok = None
    state = None
    calibration_version = None
    model = None
    if str(calibrated.get("confidence_kind") or "") == "calibrated_probability":
        probability = _finite(calibrated.get("probability"))
        source = "frozen_directional_model"
        setup_ok = calibrated.get("setup_ok") if isinstance(calibrated.get("setup_ok"), bool) else None
        state = calibrated.get("state")
        calibration_version = calibrated.get("calibration_version")
        model = calibrated.get("model")
    if probability is None and str(board.get("score_kind") or "") == "calibrated_probability":
        probability = _finite(board.get("selection_score"))
        source = "frozen_directional_model"
    if probability is None:
        probability = _finite(flow.get("calibrated_probability"))
        if probability is not None:
            source = "flow_context_model"
    if probability is None or not 0.0 <= probability <= 1.0:
        return {
            "kind": "unavailable",
            "probability": None,
            "band": "UNCALIBRATED",
            "source": None,
            "is_high": False,
            "setup_ok": None,
            "state": None,
            "calibration_version": None,
            "model": None,
            "reason": "No validated calibrated probability is attached to this row.",
        }
    if probability >= HIGH_CONFIDENCE_THRESHOLD:
        band = "HIGH"
    elif probability >= MODERATE_CONFIDENCE_THRESHOLD:
        band = "MODERATE"
    else:
        band = "LOW"
    return {
        "kind": "calibrated_probability",
        "probability": round(probability, 6),
        "band": band,
        "source": source,
        "is_high": band == "HIGH",
        "setup_ok": setup_ok,
        "state": state,
        "calibration_version": calibration_version,
        "model": model,
        "reason": None,
    }


def _direction(
    board: Mapping[str, Any], flow: Mapping[str, Any], calibrated: Mapping[str, Any],
) -> tuple[str | None, str]:
    """Use price/model context, never call/put identity, as direction evidence."""
    for source, row in (
        ("calibrated_directional_model", calibrated),
        ("board_price_context", board),
        ("flow_price_context", flow),
    ):
        value = str(row.get("side") or row.get("context_side") or "").strip().lower()
        if value in {"long", "short"}:
            return value, source
    return None, "unavailable"


def _cost_estimate(spread_pct: float | None, filters: OptionsFilters) -> dict[str, Any]:
    half = spread_pct / 2.0 if spread_pct is not None else None
    return {
        "method": "quoted_spread_only",
        "observed_spread_pct": spread_pct,
        "one_way_half_spread_pct": round(half, 6) if half is not None else None,
        "one_way_half_spread_bps": round(half * 10_000, 1) if half is not None else None,
        "round_trip_spread_pct": spread_pct,
        "spread_gate_max_pct": filters.max_spread_pct,
        "spread_gate_pass": bool(spread_pct is not None and spread_pct <= filters.max_spread_pct),
        "market_impact": None,
        "commission": None,
        "complete": False,
        "note": (
            "Half-spread is a quote-cost proxy, not a fill forecast. Market impact, "
            "commissions, and legging risk are unmeasured until an order size and live quotes exist."
        ),
    }


def _level(value: Any) -> float | None:
    number = _finite(value)
    return round(number, 4) if number is not None and number > 0 else None


def _playbook(
    *, board: Mapping[str, Any], direction: str | None, direction_source: str,
    gate_pass: bool, gate_reasons: list[str], freshness_pass: bool,
    freshness_reason: str, confidence: Mapping[str, Any], costs: Mapping[str, Any],
) -> dict[str, Any]:
    spot = _level(board.get("spot"))
    expected_move = _level(board.get("expected_move"))
    call_wall = _level(board.get("call_wall"))
    put_wall = _level(board.get("put_wall"))
    gamma_flip = _level(board.get("gamma_flip"))
    expiry = board.get("selected_expiry")

    trigger = None
    target = None
    invalidation = None
    if direction == "long":
        trigger = gamma_flip if gamma_flip is not None and (spot is None or gamma_flip >= spot * 0.98) else spot
        target = call_wall if call_wall is not None and (spot is None or call_wall > spot) else (
            round(spot + expected_move, 4) if spot is not None and expected_move is not None else None
        )
        invalidation = put_wall if put_wall is not None and (spot is None or put_wall < spot) else (
            round(spot - expected_move, 4) if spot is not None and expected_move is not None else None
        )
        structure = "call_debit_spread"
        structure_label = "Call debit spread"
        long_leg = "Buy a liquid call near the trigger/spot reference"
        short_leg = "Sell a liquid call near the upside target/barrier"
    elif direction == "short":
        trigger = gamma_flip if gamma_flip is not None and (spot is None or gamma_flip <= spot * 1.02) else spot
        target = put_wall if put_wall is not None and (spot is None or put_wall < spot) else (
            round(spot - expected_move, 4) if spot is not None and expected_move is not None else None
        )
        invalidation = call_wall if call_wall is not None and (spot is None or call_wall > spot) else (
            round(spot + expected_move, 4) if spot is not None and expected_move is not None else None
        )
        structure = "put_debit_spread"
        structure_label = "Put debit spread"
        long_leg = "Buy a liquid put near the trigger/spot reference"
        short_leg = "Sell a liquid put near the downside target/barrier"
    else:
        structure = "watch_only"
        structure_label = "Wait for directional confirmation"
        long_leg = None
        short_leg = None

    blockers = list(gate_reasons)
    if not freshness_pass:
        blockers.append(freshness_reason)
    if direction is None:
        blockers.append("No long/short price or model context; call/put identity is not direction.")
    if not confidence.get("is_high"):
        blockers.append(
            confidence.get("reason")
            or f"Calibrated probability is below {HIGH_CONFIDENCE_THRESHOLD:.0%}."
        )
    if confidence.get("setup_ok") is False:
        blockers.append(
            f"Directional model state is {confidence.get('state') or 'WATCH'}; setup gate is not active."
        )

    confidence_ready = confidence.get("is_high") and confidence.get("setup_ok") is not False
    if gate_pass and freshness_pass and direction is not None and confidence_ready:
        status = "candidate"
    elif gate_pass and freshness_pass and direction is not None:
        status = "research_only"
    else:
        status = "blocked"

    return {
        "status": status,
        "direction": direction or "watch",
        "direction_source": direction_source,
        "structure": structure,
        "structure_label": structure_label,
        "expiry": expiry,
        "trigger": trigger,
        "target": target,
        "invalidation": invalidation,
        "levels": {
            "spot": spot,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gamma_flip": gamma_flip,
            "expected_move": expected_move,
        },
        "legs": [leg for leg in (
            {"action": "BUY_TO_OPEN", "instruction": long_leg} if long_leg else None,
            {"action": "SELL_TO_OPEN", "instruction": short_leg} if short_leg else None,
        ) if leg is not None],
        "risk": {
            "max_account_risk_pct": MAX_ACCOUNT_RISK_PCT,
            "max_portfolio_heat_pct": MAX_PORTFOLIO_HEAT_PCT,
            "max_loss": "Net debit × 100 × contracts; never increase size after entry.",
            "sizing_formula": (
                "floor(account_equity × 0.005 / (net_debit × 100)); zero contracts "
                "until a live net debit is entered."
            ),
            "entry_order": "Limit order at midpoint or better; never use an unbounded market order.",
            "exit_rule": "Exit on invalidation, 50% of maximum spread value, or before expiry—whichever comes first.",
            "quote_cost": dict(costs),
        },
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": [
            "Contract strikes and net debit must be confirmed on the live chain before sizing.",
            "This is a defined-risk research template, not execution authorization.",
        ],
    }


def _gate(
    *, spread_pct: float | None, open_interest: float | None, dte: float | None,
    filters: OptionsFilters,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if spread_pct is None:
        reasons.append("spread unmeasured (no chain data for this symbol)")
    elif spread_pct > filters.max_spread_pct:
        reasons.append(f"spread {spread_pct:.0%} > max {filters.max_spread_pct:.0%}")
    if open_interest is None:
        reasons.append("open interest unmeasured (no chain data for this symbol)")
    elif open_interest < filters.min_open_interest:
        reasons.append(f"open interest {int(open_interest)} < min {filters.min_open_interest}")
    if dte is None:
        reasons.append("dte unmeasured (no chain data for this symbol)")
    elif not filters.min_dte <= dte <= filters.max_dte:
        reasons.append(f"dte {int(dte)} outside [{filters.min_dte}, {filters.max_dte}]")
    return not reasons, reasons


def build_live_opportunities(
    *,
    board_rows: list[dict] | None = None,
    flow_rows: list[dict] | None = None,
    calibrated_rows: list[dict] | None = None,
    filters: OptionsFilters,
    asof_utc: datetime | None = None,
    board_cache_age_seconds: float = 0.0,
    flow_cache_age_seconds: float = 0.0,
) -> dict[str, Any]:
    asof_utc = asof_utc or datetime.now(timezone.utc)
    if asof_utc.tzinfo is None:
        asof_utc = asof_utc.replace(tzinfo=timezone.utc)
    else:
        asof_utc = asof_utc.astimezone(timezone.utc)
    board_rows = list(board_rows or ())
    flow_rows = list(flow_rows or ())
    calibrated_rows = list(calibrated_rows or ())
    board_by_symbol = _index_by_symbol(board_rows)
    flow_by_symbol = _index_by_symbol(flow_rows)
    calibrated_by_symbol = _index_by_symbol(calibrated_rows)
    symbols = list(dict.fromkeys([*board_by_symbol, *flow_by_symbol]))

    if not symbols:
        return {"available": False, "reason": "No board or unusual-flow rows were supplied."}

    board_scores = {
        symbol: score for symbol, row in board_by_symbol.items()
        if (score := _finite(row.get("squeeze_score"))) is not None
    }
    flow_scores = {
        symbol: score for symbol, row in flow_by_symbol.items()
        if (score := _finite(row.get("unusual_score"))) is not None
    }
    board_z = _zscores(board_scores)
    flow_z = _zscores(flow_scores)

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        board = board_by_symbol.get(symbol)
        flow = flow_by_symbol.get(symbol)
        if board is not None and flow is not None:
            signal_basis = "both"
        elif board is not None:
            signal_basis = "structure_only"
        else:
            signal_basis = "flow_only"

        components = [z for z in (board_z.get(symbol), flow_z.get(symbol)) if z is not None]
        composite_score = round(fmean(components), 4) if components else None

        spread_pct = _finite((board or {}).get("spread_pct"))
        open_interest = _finite((board or {}).get("open_interest"))
        dte = _finite((board or {}).get("selected_dte"))
        gate_pass, gate_reasons = _gate(
            spread_pct=spread_pct, open_interest=open_interest, dte=dte, filters=filters,
        )

        board_map: Mapping[str, Any] = board or {}
        flow_map: Mapping[str, Any] = flow or {}
        calibrated_map: Mapping[str, Any] = calibrated_by_symbol.get(symbol) or {}
        chain_age = _effective_age(
            observed_at=board_map.get("observed_at"),
            reported_age=board_map.get("age_seconds"),
            cache_age_seconds=board_cache_age_seconds,
            now_utc=asof_utc,
        )
        flow_age = _effective_age(
            observed_at=flow_map.get("live_asof"),
            reported_age=None,
            cache_age_seconds=flow_cache_age_seconds,
            now_utc=asof_utc,
        )
        chain_live = str(board_map.get("mode_resolved") or "").lower() == "live" or "live" in str(
            board_map.get("chain_source") or ""
        ).lower()
        chain_fresh = bool(
            chain_live and chain_age is not None and chain_age <= MAX_LIVE_AGE_SECONDS
            and not board_map.get("clock_mismatch")
        )
        uses_flow = flow is not None
        flow_live = bool(flow_map.get("live"))
        flow_fresh = bool(
            flow_live and flow_age is not None and flow_age <= MAX_LIVE_AGE_SECONDS
        ) if uses_flow else True
        freshness_pass = chain_fresh and flow_fresh
        freshness_reasons: list[str] = []
        if not chain_live:
            freshness_reasons.append("chain is not a live observation")
        elif chain_age is None:
            freshness_reasons.append("chain freshness is unmeasured")
        elif chain_age > MAX_LIVE_AGE_SECONDS:
            freshness_reasons.append(
                f"chain age {int(chain_age)}s > max {int(MAX_LIVE_AGE_SECONDS)}s"
            )
        if board_map.get("clock_mismatch"):
            freshness_reasons.append("chain and price-bar clocks are mismatched")
        if uses_flow and not flow_live:
            freshness_reasons.append("flow input is an activity proxy, not live tape")
        elif uses_flow and flow_age is None:
            freshness_reasons.append("live-flow freshness is unmeasured")
        elif uses_flow and flow_age > MAX_LIVE_AGE_SECONDS:
            freshness_reasons.append(
                f"live-flow age {int(flow_age)}s > max {int(MAX_LIVE_AGE_SECONDS)}s"
            )
        freshness_reason = "; ".join(freshness_reasons) or "fresh live inputs"

        confidence = _confidence(board_map, flow_map, calibrated_map)
        direction, direction_source = _direction(board_map, flow_map, calibrated_map)
        costs = _cost_estimate(spread_pct, filters)
        playbook = _playbook(
            board=board_map,
            direction=direction,
            direction_source=direction_source,
            gate_pass=gate_pass,
            gate_reasons=gate_reasons,
            freshness_pass=freshness_pass,
            freshness_reason=freshness_reason,
            confidence=confidence,
            costs=costs,
        )
        highlighted = bool(
            gate_pass and freshness_pass and confidence["is_high"]
            and confidence.get("setup_ok") is not False and direction is not None
        )

        rows.append({
            "symbol": symbol,
            "signal_basis": signal_basis,
            "composite_score": composite_score,
            "board_squeeze_score": board_scores.get(symbol),
            "board_squeeze_z": round(board_z[symbol], 4) if symbol in board_z else None,
            "flow_unusual_score": flow_scores.get(symbol),
            "flow_unusual_z": round(flow_z[symbol], 4) if symbol in flow_z else None,
            "gate_pass": gate_pass,
            "gate_reasons": gate_reasons,
            "spread_pct": spread_pct,
            "open_interest": int(open_interest) if open_interest is not None else None,
            "selected_dte": int(dte) if dte is not None else None,
            "call_put_imbalance": _finite((flow or {}).get("call_put_imbalance")),
            "ret_1d": _finite((flow or {}).get("ret_1d")),
            "premium": _finite((flow or {}).get("premium")),
            "confidence": confidence,
            "highlighted": highlighted,
            "live_ready": bool(gate_pass and freshness_pass),
            "freshness": {
                "pass": freshness_pass,
                "status": "FRESH" if freshness_pass else "STALE_OR_PROXY",
                "max_age_seconds": MAX_LIVE_AGE_SECONDS,
                "chain_live": chain_live,
                "chain_age_seconds": round(chain_age, 1) if chain_age is not None else None,
                "flow_required": uses_flow,
                "flow_live": flow_live if uses_flow else None,
                "flow_age_seconds": round(flow_age, 1) if flow_age is not None else None,
                "reasons": freshness_reasons,
            },
            "costs": costs,
            "barriers": {
                "spot": _level(board_map.get("spot")),
                "call_wall": _level(board_map.get("call_wall")),
                "put_wall": _level(board_map.get("put_wall")),
                "gamma_flip": _level(board_map.get("gamma_flip")),
                "expected_move": _level(board_map.get("expected_move")),
            },
            "playbook": playbook,
        })

    def _sort_key(row: dict[str, Any]) -> tuple[float, str]:
        score = row["composite_score"]
        return (-(score if score is not None else float("-inf")), row["symbol"])

    highlighted_rows = sorted((r for r in rows if r["highlighted"]), key=_sort_key)
    passing = sorted((r for r in rows if r["gate_pass"] and not r["highlighted"]), key=_sort_key)
    failing = sorted((r for r in rows if not r["gate_pass"]), key=_sort_key)

    warnings: list[str] = []
    if not board_rows:
        warnings.append("No board_rows supplied; every row is flow_only for this pull.")
    if not flow_rows:
        warnings.append("No flow_rows supplied; every row is structure_only for this pull.")

    return {
        "schema_version": SCHEMA_VERSION,
        "asof_utc": asof_utc.isoformat(),
        "available": True,
        "decision_authorized": False,
        "score_kind": SCORE_KIND,
        "method": (
            "composite_score is the mean of z-scored board squeeze_score and flow "
            "unusual_score, computed across symbols where each signal is present in "
            "this pull; ordinal only, never a probability or expected value."
        ),
        "filters": asdict(filters),
        "rows": highlighted_rows + passing + failing,
        "coverage": {
            "board_symbols": len(board_by_symbol),
            "flow_symbols": len(flow_by_symbol),
            "union_symbols": len(symbols),
            "gate_pass": len(highlighted_rows) + len(passing),
            "gate_fail": len(failing),
            "high_confidence": len(highlighted_rows),
            "live_ready": sum(1 for row in rows if row["live_ready"]),
            "uncalibrated": sum(1 for row in rows if row["confidence"]["kind"] == "unavailable"),
            "stale_or_proxy": sum(1 for row in rows if not row["freshness"]["pass"]),
        },
        "warnings": warnings,
        "caveats": [
            "composite_score is an ordinal z-score blend, not a probability or expected value.",
            "gate_pass checks OptionsFilters thresholds against measured chain fields only; "
            "missing fields fail closed and are never assumed tradable.",
            "flow_only rows carry no chain-derived spread/open interest/DTE, so they cannot "
            "pass the tradability gate on flow evidence alone.",
            "HIGH requires a calibrated probability >=65% plus fresh live inputs and all "
            "tradability gates; ordinal composite magnitude never creates confidence.",
            "Quote-cost estimates include spread only. Market impact, commissions, and "
            "multi-leg execution risk remain unmeasured until live order details exist.",
        ],
    }
