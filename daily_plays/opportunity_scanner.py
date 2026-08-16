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


def _observed_contract_rejections(focus: Mapping[str, Any], spot: Any) -> list[str]:
    strike = _finite(focus.get("strike"))
    focus_spot = _finite(focus.get("underlying_price")) or _finite(spot)
    dte = _finite(focus.get("dte"))
    reasons: list[str] = []
    if not focus.get("expiry") or dte is None or not 0 <= dte <= 60:
        reasons.append("observed Flow contract is outside the 0–60 DTE review window")
    if strike is None or focus_spot is None or focus_spot <= 0:
        reasons.append("moneyness cannot be validated without strike and underlying spot")
    elif abs(strike / focus_spot - 1.0) > 0.25:
        reasons.append("observed strike is more than 25% from underlying spot")
    return reasons


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


LEVEL_SOURCE_SUPPORT = "resistance/support"
LEVEL_SOURCE_GEX = "options GEX"
LEVEL_SOURCE_POSITIONS = "positions"
LEVEL_SOURCE_TA = "technical analysis"
LEVEL_SOURCES = (
    LEVEL_SOURCE_SUPPORT,
    LEVEL_SOURCE_GEX,
    LEVEL_SOURCE_POSITIONS,
    LEVEL_SOURCE_TA,
)


def _first_level(*values: Any) -> float | None:
    for value in values:
        measured = _level(value)
        if measured is not None:
            return measured
    return None


def _append_level(
    bucket: list[dict[str, Any]],
    price: Any,
    source: str,
    *,
    side: str | None,
    spot: float | None,
) -> None:
    measured = _level(price)
    if measured is None or source not in LEVEL_SOURCES:
        return
    if side == "below" and spot is not None and measured >= spot:
        return
    if side == "above" and spot is not None and measured <= spot:
        return
    key = round(measured, 4)
    if any(round(float(item["price"]), 4) == key for item in bucket):
        return
    bucket.append({"price": measured, "source": source})


def _focus_contract_strike(focus: Any, right: str | None) -> float | None:
    if not isinstance(focus, Mapping):
        return None
    if right in {"call", "put"} and isinstance(focus.get(right), Mapping):
        return _level(focus[right].get("strike"))
    return _level(focus.get("strike"))


def _row_open_interest(row: Mapping[str, Any]) -> float | None:
    total = _finite(row.get("open_interest"))
    if total is not None and total > 0:
        return total
    call_oi = _finite(row.get("call_oi")) or 0.0
    put_oi = _finite(row.get("put_oi")) or 0.0
    combined = call_oi + put_oi
    return combined if combined > 0 else None


def _notable_gex_rows(rows: Any) -> list[Mapping[str, Any]]:
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if isinstance(row, Mapping) and _level(row.get("strike")) is not None]


def setup_inputs_from_rows(
    board: Mapping[str, Any] | None,
    flow: Mapping[str, Any] | None,
    *,
    direction: str | None,
) -> dict[str, Any]:
    """Pull already-measured S/R, GEX, positions, and TA fields from board/flow."""
    board_map: Mapping[str, Any] = board or {}
    flow_map: Mapping[str, Any] = flow or {}
    right = "call" if direction == "long" else "put" if direction == "short" else None
    return {
        "support": _first_level(
            board_map.get("support"), board_map.get("support_price"), board_map.get("next_support"),
            flow_map.get("support"), flow_map.get("support_price"), flow_map.get("next_support"),
        ),
        "resistance": _first_level(
            board_map.get("resistance"), board_map.get("resistance_price"), board_map.get("next_resistance"),
            flow_map.get("resistance"), flow_map.get("resistance_price"), flow_map.get("next_resistance"),
        ),
        "call_wall": _first_level(board_map.get("call_wall"), flow_map.get("call_wall")),
        "put_wall": _first_level(board_map.get("put_wall"), flow_map.get("put_wall")),
        "gamma_flip": _first_level(board_map.get("gamma_flip"), flow_map.get("gamma_flip")),
        "pin_strike": _first_level(board_map.get("pin_strike"), flow_map.get("pin_strike")),
        "position_strike": _first_level(
            _focus_contract_strike(board_map.get("contract_focus"), right),
            _focus_contract_strike(flow_map.get("flow_focus"), right),
            board_map.get("position_strike"),
            flow_map.get("position_strike"),
        ),
        "ta_support": _first_level(
            board_map.get("ta_support"), board_map.get("swing_low"),
            flow_map.get("ta_support"), flow_map.get("swing_low"),
        ),
        "ta_resistance": _first_level(
            board_map.get("ta_resistance"), board_map.get("swing_high"),
            flow_map.get("ta_resistance"), flow_map.get("swing_high"),
        ),
        "gex_rows": (
            board_map.get("gex_by_strike")
            or board_map.get("gex_rows")
            or flow_map.get("gex_by_strike")
            or flow_map.get("gex_rows")
        ),
        "expected_move": _first_level(board_map.get("expected_move"), flow_map.get("expected_move")),
        "spot": _first_level(board_map.get("spot"), flow_map.get("spot")),
    }


def setup_level_model(
    *,
    direction: str | None,
    spot: Any,
    support: Any = None,
    resistance: Any = None,
    call_wall: Any = None,
    put_wall: Any = None,
    gamma_flip: Any = None,
    pin_strike: Any = None,
    position_strike: Any = None,
    ta_support: Any = None,
    ta_resistance: Any = None,
    gex_rows: Any = None,
    expected_move: Any = None,
) -> dict[str, Any]:
    """Source-attributed strike, supports, invalidation, and take-profit zones.

    Uses only already-measured resistance/support, options GEX, positions, and
    technical analysis. Expected-move is accepted so callers can prove it never
    fills a level. Missing or wrong-side inputs stay unmeasured.
    """
    del expected_move  # never a strike, support, invalidation, or take-profit zone
    spot_n = _level(spot)
    supports: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    resistances: list[dict[str, Any]] = []

    _append_level(supports, support, LEVEL_SOURCE_SUPPORT, side="below", spot=spot_n)
    _append_level(resistances, resistance, LEVEL_SOURCE_SUPPORT, side="above", spot=spot_n)
    _append_level(supports, put_wall, LEVEL_SOURCE_GEX, side="below", spot=spot_n)
    _append_level(resistances, call_wall, LEVEL_SOURCE_GEX, side="above", spot=spot_n)
    _append_level(supports, ta_support, LEVEL_SOURCE_TA, side="below", spot=spot_n)
    _append_level(resistances, ta_resistance, LEVEL_SOURCE_TA, side="above", spot=spot_n)
    _append_level(supports, gamma_flip, LEVEL_SOURCE_TA, side="below", spot=spot_n)
    _append_level(resistances, gamma_flip, LEVEL_SOURCE_TA, side="above", spot=spot_n)

    best_oi_below: tuple[float, float] | None = None
    best_oi_above: tuple[float, float] | None = None
    best_put_gex: tuple[float, float] | None = None
    best_call_gex: tuple[float, float] | None = None
    best_oi_strike: tuple[float, float] | None = None
    for row in _notable_gex_rows(gex_rows):
        strike = _level(row.get("strike"))
        if strike is None:
            continue
        oi = _row_open_interest(row)
        if oi is not None and (best_oi_strike is None or oi > best_oi_strike[0]):
            best_oi_strike = (oi, strike)
        if spot_n is None:
            continue
        put_gex = _finite(row.get("put_gex_m") if row.get("put_gex_m") is not None else row.get("put_gex"))
        call_gex = _finite(row.get("call_gex_m") if row.get("call_gex_m") is not None else row.get("call_gex"))
        if strike < spot_n:
            if oi is not None and (best_oi_below is None or oi > best_oi_below[0]):
                best_oi_below = (oi, strike)
            if put_gex is not None and put_gex < 0 and (best_put_gex is None or put_gex < best_put_gex[0]):
                best_put_gex = (put_gex, strike)
        elif strike > spot_n:
            if oi is not None and (best_oi_above is None or oi > best_oi_above[0]):
                best_oi_above = (oi, strike)
            if call_gex is not None and call_gex > 0 and (best_call_gex is None or call_gex > best_call_gex[0]):
                best_call_gex = (call_gex, strike)

    if best_oi_below is not None:
        _append_level(supports, best_oi_below[1], LEVEL_SOURCE_POSITIONS, side="below", spot=spot_n)
    if best_put_gex is not None:
        _append_level(supports, best_put_gex[1], LEVEL_SOURCE_GEX, side="below", spot=spot_n)
    if best_oi_above is not None:
        _append_level(resistances, best_oi_above[1], LEVEL_SOURCE_POSITIONS, side="above", spot=spot_n)
    if best_call_gex is not None:
        _append_level(resistances, best_call_gex[1], LEVEL_SOURCE_GEX, side="above", spot=spot_n)

    strike = _first_level(position_strike, pin_strike, best_oi_strike[1] if best_oi_strike else None)
    strike_source = None
    if strike is not None:
        if position_strike is not None and _level(position_strike) == strike:
            strike_source = LEVEL_SOURCE_POSITIONS
        elif pin_strike is not None and _level(pin_strike) == strike:
            strike_source = LEVEL_SOURCE_POSITIONS
        else:
            strike_source = LEVEL_SOURCE_POSITIONS

    supports.sort(key=lambda item: item["price"], reverse=True)
    resistances.sort(key=lambda item: item["price"])
    if direction == "long":
        zones = list(resistances)
        invalidation = supports[0]["price"] if supports else None
        invalidation_source = supports[0]["source"] if supports else None
    elif direction == "short":
        zones = list(supports)
        invalidation = resistances[0]["price"] if resistances else None
        invalidation_source = resistances[0]["source"] if resistances else None
    else:
        zones = []
        invalidation = None
        invalidation_source = None

    gex_target = None
    gex_invalidation = None
    if direction == "long":
        gex_target = call_wall if _level(call_wall) is not None and (spot_n is None or _level(call_wall) > spot_n) else None
        gex_invalidation = put_wall if _level(put_wall) is not None and (spot_n is None or _level(put_wall) < spot_n) else None
    elif direction == "short":
        gex_target = put_wall if _level(put_wall) is not None and (spot_n is None or _level(put_wall) < spot_n) else None
        gex_invalidation = call_wall if _level(call_wall) is not None and (spot_n is None or _level(call_wall) > spot_n) else None

    source_status = {
        LEVEL_SOURCE_SUPPORT: "measured" if any(
            item["source"] == LEVEL_SOURCE_SUPPORT for item in (*supports, *resistances)
        ) else "unmeasured",
        LEVEL_SOURCE_GEX: "measured" if any(
            item["source"] == LEVEL_SOURCE_GEX for item in (*supports, *resistances)
        ) or gex_target is not None or gex_invalidation is not None else "unmeasured",
        LEVEL_SOURCE_POSITIONS: "measured" if strike_source == LEVEL_SOURCE_POSITIONS or any(
            item["source"] == LEVEL_SOURCE_POSITIONS for item in (*supports, *resistances)
        ) else "unmeasured",
        LEVEL_SOURCE_TA: "measured" if any(
            item["source"] == LEVEL_SOURCE_TA for item in (*supports, *resistances)
        ) else "unmeasured",
    }
    if source_status[LEVEL_SOURCE_SUPPORT] == "unmeasured" and (
        _level(support) is not None or _level(resistance) is not None
    ):
        source_status[LEVEL_SOURCE_SUPPORT] = "wrong-side"
    if source_status[LEVEL_SOURCE_GEX] == "unmeasured" and (
        _level(call_wall) is not None or _level(put_wall) is not None
    ):
        source_status[LEVEL_SOURCE_GEX] = "wrong-side"

    missing_fields = [
        label for label, value in (
            ("strike", strike),
            ("supports", supports[0]["price"] if supports else None),
            ("invalidation", invalidation),
            ("take profit zones", zones[0]["price"] if zones else None),
            ("GEX take-profit target", _level(gex_target)),
            ("GEX invalidation", _level(gex_invalidation)),
        ) if value is None
    ]
    complete = bool(strike is not None and supports and invalidation is not None and zones)
    return {
        "strike": strike,
        "strike_source": strike_source,
        "supports": supports,
        "invalidation": invalidation,
        "invalidation_source": invalidation_source,
        "take_profit_zones": zones,
        "gex_target": _level(gex_target),
        "gex_invalidation": _level(gex_invalidation),
        "source_status": source_status,
        "missing_sources": [name for name, state in source_status.items() if state != "measured"],
        "risk_missing_fields": missing_fields,
        "complete": complete,
        "risk_levels_complete": complete,
        "spot": spot_n,
    }


def gex_relative_sell(
    *,
    direction: str | None,
    spot: Any,
    call_wall: Any,
    put_wall: Any,
) -> dict[str, Any]:
    """Take-profit / sell relative to spot from measured GEX walls only.

    Longs sell into a call wall above spot. Shorts sell into a put/support
    wall below spot. Missing or wrong-side walls stay unmeasured — never
    invented from expected-move or any other proxy.
    """
    spot_n = _level(spot)
    call_n = _level(call_wall)
    put_n = _level(put_wall)
    empty = {
        "sell": None,
        "sell_source": None,
        "sell_rel_pct": None,
        "invalidation": None,
        "invalidation_source": None,
        "spot": spot_n,
        "measured": False,
    }
    if direction == "long":
        sell = call_n if call_n is not None and (spot_n is None or call_n > spot_n) else None
        source = "call_wall" if sell is not None else None
        invalidation = put_n if put_n is not None and (spot_n is None or put_n < spot_n) else None
        inv_source = "put_wall" if invalidation is not None else None
    elif direction == "short":
        sell = put_n if put_n is not None and (spot_n is None or put_n < spot_n) else None
        source = "put_wall" if sell is not None else None
        invalidation = call_n if call_n is not None and (spot_n is None or call_n > spot_n) else None
        inv_source = "call_wall" if invalidation is not None else None
    else:
        return empty
    rel = None
    if sell is not None and spot_n is not None and spot_n != 0:
        rel = round((sell - spot_n) / spot_n, 6)
    return {
        "sell": sell,
        "sell_source": source,
        "sell_rel_pct": rel,
        "invalidation": invalidation,
        "invalidation_source": inv_source,
        "spot": spot_n,
        "measured": sell is not None,
    }


def qlib_alignment(
    direction: str | None,
    rank: int | None,
    n_symbols: int | None,
) -> str:
    """Map a published qlib rank onto the suggested right without inventing one."""
    if direction not in {"long", "short"} or rank is None or n_symbols is None or n_symbols < 3:
        return "unmeasured"
    if rank < 1 or rank > n_symbols:
        return "unmeasured"
    third = n_symbols / 3.0
    top = rank <= third
    bottom = rank > n_symbols - third
    if direction == "long":
        if top:
            return "confirms"
        if bottom:
            return "conflicts"
        return "neutral"
    if top:
        return "conflicts"
    if bottom:
        return "confirms"
    return "neutral"


def qlib_rows_from_panel(panel: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten a published deep-scan/qlib panel. Empty when the panel is missing."""
    if not isinstance(panel, Mapping):
        return []
    by_symbol = panel.get("by_symbol") if isinstance(panel.get("by_symbol"), Mapping) else {}
    coverage = panel.get("coverage") if isinstance(panel.get("coverage"), Mapping) else {}
    scored = _finite(coverage.get("scored"))
    n_symbols = int(scored) if scored is not None else len(by_symbol)
    rows: list[dict[str, Any]] = []
    for symbol, rec in by_symbol.items():
        if not isinstance(rec, Mapping):
            continue
        clean = _clean_symbol(rec.get("symbol") or symbol)
        if not clean:
            continue
        rank = _finite(rec.get("qlib_rank"))
        rows.append({
            "symbol": clean,
            "qlib_score": _finite(rec.get("qlib_score")),
            "qlib_rank": int(rank) if rank is not None else None,
            "n_symbols": n_symbols,
            "source": rec.get("source") or panel.get("source"),
            "score_kind": rec.get("score_kind") or panel.get("score_kind"),
            "asof": rec.get("asof") or panel.get("asof"),
        })
    return rows


def _qlib_overlay(row: Mapping[str, Any] | None) -> dict[str, Any]:
    rec = row or {}
    score = _finite(rec.get("qlib_score"))
    rank_n = _finite(rec.get("qlib_rank"))
    n_symbols = _finite(rec.get("n_symbols"))
    rank = int(rank_n) if rank_n is not None else None
    n = int(n_symbols) if n_symbols is not None else None
    measured = score is not None or rank is not None
    return {
        "score": score,
        "rank": rank,
        "n_symbols": n,
        "source": rec.get("source"),
        "score_kind": rec.get("score_kind"),
        "asof": rec.get("asof"),
        "alignment": "unmeasured",
        "measured": measured,
    }


def build_suggestion(
    *,
    direction: str | None,
    playbook_status: str,
    blockers: list[str] | tuple[str, ...] | None,
    spot: Any,
    call_wall: Any,
    put_wall: Any,
    qlib: Mapping[str, Any] | None = None,
    activity_lean: str | None = None,
    activity_lean_source: str | None = None,
    chain_focus: Mapping[str, Any] | None = None,
    flow_focus: Mapping[str, Any] | None = None,
    flow_focus_rejections: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Flow+board suggestion: a call or put, or an explicit watch/blocked reason.

    Qlib/deep-scan ranks participate when published. Missing scores stay
    unmeasured. Conflicting ranks warn; they do not flip the suggested right.
    """
    reasons = [str(item) for item in (blockers or ()) if item]
    lean = str(activity_lean or "").strip().lower()
    lean_source = str(activity_lean_source or "").strip().lower()
    bias_direction = "long" if lean == "bullish" else "short" if lean == "bearish" else None
    # Unsigned premium mix cannot authorize an entry, but suppressing its right
    # entirely makes the research surface useless. It may name a paper-review
    # right while the separate entry, quote, liquidity, and stability gates
    # remain fail-closed.
    lean_direction_confirmed = lean_source in {"signed_flow", "model_context"}
    planning_direction = bias_direction if lean_direction_confirmed else None
    effective_direction = direction or planning_direction or bias_direction
    risk = gex_relative_sell(
        direction=effective_direction, spot=spot, call_wall=call_wall, put_wall=put_wall,
    )
    qlib_block = _qlib_overlay(qlib)
    if qlib_block["measured"]:
        qlib_block["alignment"] = qlib_alignment(
            effective_direction, qlib_block["rank"], qlib_block["n_symbols"],
        )

    if direction == "long":
        right = "call"
        reason = None
        status = "plan" if playbook_status == "blocked" else (playbook_status or "research_only")
        evidence_kind = "directional_context"
    elif direction == "short":
        right = "put"
        reason = None
        status = "plan" if playbook_status == "blocked" else (playbook_status or "research_only")
        evidence_kind = "directional_context"
    elif planning_direction is not None:
        right = "call" if planning_direction == "long" else "put"
        status = "plan"
        evidence_kind = "signed_activity"
        source = str(activity_lean_source or "unsigned options activity").replace("_", " ")
        reason = (
            f"Directional planning context from {lean} {source}. This names a right "
            "for review; entry eligibility remains a separate gate."
        )
    elif bias_direction is not None:
        right = "call" if bias_direction == "long" else "put"
        status = "paper_candidate"
        evidence_kind = "activity_lean"
        source = str(activity_lean_source or "unsigned options activity").replace("_", " ")
        reason = (
            f"{lean.title()} activity bias from {source}, but the provider did not "
            f"confirm aggressor direction. Paper {right.upper()} candidate only; "
            "live-entry sizing remains locked."
        )
    elif playbook_status == "blocked":
        right = "blocked"
        reason = reasons[0] if reasons else "No long/short price or model context."
        status = "blocked"
        evidence_kind = "none"
    else:
        right = "watch"
        reason = reasons[0] if reasons else (
            "No long/short price or model context; call/put identity is not direction."
        )
        status = "watch"
        evidence_kind = "none"

    warnings: list[str] = []
    if qlib_block["alignment"] == "conflicts":
        warnings.append("qlib/deep-scan rank conflicts with the suggested right.")

    chain_map = chain_focus if isinstance(chain_focus, Mapping) else {}
    flow_map = flow_focus if isinstance(flow_focus, Mapping) else {}
    rejected_flow_map = flow_focus_rejections if isinstance(flow_focus_rejections, Mapping) else {}
    chain_contract = chain_map.get(right) if right in {"call", "put"} else None
    observed_contract = flow_map.get(right) if right in {"call", "put"} else None
    if not isinstance(chain_contract, Mapping) and isinstance(observed_contract, Mapping):
        rejected_observed = _observed_contract_rejections(observed_contract, spot)
        if rejected_observed:
            warnings.append(
                "Observed Flow contract was rejected before planning: "
                + "; ".join(rejected_observed)
                + "."
            )
            observed_contract = None
    if not isinstance(chain_contract, Mapping) and not isinstance(observed_contract, Mapping):
        excluded = rejected_flow_map.get(right)
        if isinstance(excluded, (list, tuple)) and excluded:
            warnings.append(
                "Observed Flow contracts were excluded from planning: "
                + "; ".join(str(item) for item in excluded if item)
                + "."
            )
    focus = chain_contract if isinstance(chain_contract, Mapping) else observed_contract
    contract_plan = None
    if isinstance(focus, Mapping):
        from_chain = isinstance(chain_contract, Mapping)
        bid = _finite(focus.get("bid")) if from_chain else None
        ask = _finite(focus.get("ask")) if from_chain else None
        midpoint = _finite(focus.get("midpoint")) if from_chain else None
        observed_price = _finite(focus.get("price")) if not from_chain else None
        quote_complete = bool(
            from_chain
            and focus.get("quote_complete")
            and bid is not None and ask is not None and midpoint is not None
        )
        quote_reference_only = bool(from_chain and focus.get("quote_reference_only"))
        reference_debit = (
            midpoint if from_chain and (quote_complete or quote_reference_only) else observed_price
        )
        multiplier = _finite(focus.get("contract_multiplier")) or 100.0
        strike = _finite(focus.get("strike"))
        focus_spot = _finite(focus.get("underlying_price")) or _finite(spot)
        moneyness_pct = (
            abs(strike / focus_spot - 1.0)
            if strike is not None and focus_spot is not None and focus_spot > 0 else None
        )
        dte_value = int(dte) if (dte := _finite(focus.get("dte"))) is not None else None
        flow_identity_ok = bool(
            not from_chain
            and strike is not None
            and focus.get("expiry")
            and dte_value is not None and 0 <= dte_value <= 60
            and moneyness_pct is not None and moneyness_pct <= 0.25
        )
        contract_complete = bool(from_chain and focus.get("contract_complete"))
        entry_eligible = bool(playbook_status == "candidate" and direction in {"long", "short"})
        sizing_eligible = bool(entry_eligible and contract_complete and quote_complete)
        rejection_reasons = list(focus.get("rejection_reasons") or ()) if from_chain else []
        if not from_chain:
            if dte_value is None or not 0 <= dte_value <= 60:
                rejection_reasons.append("observed Flow contract is outside the 0–60 DTE review window")
            if moneyness_pct is None:
                rejection_reasons.append("moneyness cannot be validated without strike and underlying spot")
            elif moneyness_pct > 0.25:
                rejection_reasons.append("observed strike is more than 25% from underlying spot")
            rejection_reasons.append("live chain quote has not been matched")
        if sizing_eligible:
            action = "BUY_TO_OPEN"
            contract_stage = "entry_candidate"
        elif from_chain and quote_reference_only:
            action = "WAIT_FOR_LIVE_QUOTE"
            contract_stage = "chain_matched_delayed_reference"
        elif from_chain and not quote_complete:
            action = "WAIT_FOR_QUOTE"
            contract_stage = "chain_matched_quote_missing"
        elif from_chain and not contract_complete:
            action = "REVIEW_ONLY"
            contract_stage = "chain_quote_failed_quality"
        elif from_chain:
            action = "REVIEW_ONLY"
            contract_stage = "chain_matched_setup_gated"
        else:
            action = "REVIEW_FLOW_PRINT"
            contract_stage = "flow_observed_unmatched"
        reference_max_loss = (
            round(reference_debit * multiplier, 2)
            if reference_debit is not None else None
        )
        play = None
        if strike is not None and focus_spot is not None and reference_debit is not None:
            from .options_calculator import summarize_setup_play

            try:
                play = summarize_setup_play(
                    right=right,
                    spot=focus_spot,
                    strike=strike,
                    premium=reference_debit,
                    dte=dte_value,
                    expiry=str(focus.get("expiry") or "") or None,
                    vol=_finite(focus.get("implied_volatility")),
                    sell=risk.get("sell"),
                    invalidation=risk.get("invalidation"),
                    multiplier=multiplier,
                )
            except (TypeError, ValueError):
                play = None
        contract_plan = {
            "kind": "chain_selected_contract" if from_chain else "observed_long_option",
            "right": right,
            "action": action,
            "contract_stage": contract_stage,
            "occ_symbol": focus.get("occ_symbol"),
            "strike": strike,
            "expiry": focus.get("expiry"),
            "dte": dte_value,
            "moneyness_pct": moneyness_pct,
            "reference_debit": reference_debit,
            "sizing_debit": reference_debit if sizing_eligible else None,
            "reference_debit_estimated": bool(focus.get("price_estimated")) if not from_chain else False,
            "bid": bid,
            "ask": ask,
            "midpoint": midpoint,
            "spread_pct": _finite(focus.get("spread_pct")) if from_chain else None,
            "volume": (
                int(volume) if (volume := _finite(focus.get("volume"))) is not None else None
            ) if from_chain else None,
            "open_interest": (
                int(oi) if (oi := _finite(focus.get("open_interest"))) is not None else None
            ) if from_chain else None,
            "implied_volatility": _finite(focus.get("implied_volatility")) if from_chain else None,
            "delta": _finite(focus.get("delta")) if from_chain else None,
            "contract_multiplier": int(multiplier),
            "reference_max_loss": reference_max_loss,
            "play": play,
            "take_profit_debit": (
                round(reference_debit * 1.5, 2)
                if sizing_eligible and reference_debit is not None else None
            ),
            "review_exit_debit": (
                round(reference_debit * 0.5, 2)
                if sizing_eligible and reference_debit is not None else None
            ),
            "observed_contracts": (
                int(count) if (count := _finite(focus.get("contracts"))) is not None else None
            ) if not from_chain else None,
            "observed_premium": _finite(focus.get("premium")) if not from_chain else None,
            "observed_at": focus.get("observed_at") if from_chain else focus.get("timestamp"),
            "source": (
                focus.get("quote_source") or "selected_chain_quote"
            ) if from_chain else "observed_flow_print",
            "quote_status": (
                str(focus.get("quote_status") or (
                    "chain_two_sided" if quote_complete else "chain_quote_missing"
                ))
            ) if from_chain else "flow_reference_only",
            "quote_complete": quote_complete,
            "quote_live": bool(from_chain and focus.get("quote_live")),
            "quote_reference_only": quote_reference_only,
            "quote_source": focus.get("quote_source") if from_chain else None,
            "contract_complete": contract_complete if from_chain else flow_identity_ok,
            "sizing_eligible": sizing_eligible,
            "stability_observations": 0,
            "stability_required": 3,
            "stable": False,
            "rejection_reasons": list(dict.fromkeys(str(item) for item in rejection_reasons if item)),
            "selection_method": focus.get("selection_method") if from_chain else (
                "Highest-premium observed Flow print with matching CALL/PUT identity."
            ),
            "missing_fields": [
                label for label, value in (
                    ("live bid" if quote_reference_only else "bid", None if quote_reference_only else bid),
                    ("live ask" if quote_reference_only else "ask", None if quote_reference_only else ask),
                    ("open interest", focus.get("open_interest") if from_chain else None),
                    ("implied volatility", focus.get("implied_volatility") if from_chain else None),
                    ("delta", focus.get("delta") if from_chain else None),
                )
                if value is None
            ],
            "note": (
                "Exact contract identity and delayed bid/ask matched for paper review. "
                "Sizing stays locked until a live two-sided quote and every gate pass."
                if quote_reference_only else
                "Contract identity matched to the available chain. It remains wait-only until "
                "a two-sided quote, liquidity, stability, and every setup gate pass."
                if from_chain else
                "Observed Flow print only. It is not a selected contract and cannot feed sizing "
                "until the exact live chain identity and two-sided quote are matched."
            ),
        }
        warnings.append(
            "Delayed exact-contract quote is a paper reference, not execution authorization."
            if quote_reference_only else
            "Chain identity is matched, but a point-in-time quote is not execution authorization."
            if from_chain else
            "Observed Flow price is excluded from sizing until an exact live chain quote is matched."
        )

    return {
        "right": right,
        "reason": reason,
        "status": status,
        "entry_eligible": bool(playbook_status == "candidate" and direction in {"long", "short"}),
        "setup_tier": (
            "ready" if playbook_status == "candidate" and direction in {"long", "short"}
            else "paper" if right in {"call", "put"}
            else "watch" if right == "watch"
            else "blocked"
        ),
        "bias_right": "call" if bias_direction == "long" else "put" if bias_direction == "short" else None,
        "bias_confirmed": bool(planning_direction is not None),
        "evidence_kind": evidence_kind,
        "direction_source": (
            "signed_activity" if evidence_kind == "signed_activity" else
            "activity_lean" if evidence_kind == "activity_lean" else
            "directional_context" if evidence_kind == "directional_context" else "unavailable"
        ),
        "spot": risk["spot"],
        "sell": risk["sell"],
        "sell_source": risk["sell_source"],
        "sell_rel_pct": risk["sell_rel_pct"],
        "invalidation": risk["invalidation"],
        "invalidation_source": risk["invalidation_source"],
        "qlib": qlib_block,
        "warnings": warnings,
        "blockers": reasons,
        "contract_plan": contract_plan,
    }


def _empty_suggestion_payload(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "decision_authorized": False,
        "suggestion": {
            "right": "blocked",
            "reason": reason,
            "spot": None,
            "sell": None,
            "sell_source": None,
            "sell_rel_pct": None,
        },
    }


def _playbook(
    *, board: Mapping[str, Any], direction: str | None, direction_source: str,
    gate_pass: bool, gate_reasons: list[str], freshness_pass: bool,
    freshness_reason: str, confidence: Mapping[str, Any], costs: Mapping[str, Any],
    level_model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spot = _level(board.get("spot"))
    expected_move = _level(board.get("expected_move"))
    call_wall = _level(board.get("call_wall"))
    put_wall = _level(board.get("put_wall"))
    gamma_flip = _level(board.get("gamma_flip"))
    expiry = board.get("selected_expiry")
    model = dict(level_model or {})

    trigger = None
    target = None
    invalidation = None
    if direction == "long":
        trigger = gamma_flip if gamma_flip is not None and (spot is None or gamma_flip >= spot * 0.98) else spot
        target = call_wall if call_wall is not None and (spot is None or call_wall > spot) else None
        invalidation = put_wall if put_wall is not None and (spot is None or put_wall < spot) else None
        structure = "call_debit_spread"
        structure_label = "Call debit spread"
        long_leg = "Buy a liquid call near the trigger/spot reference"
        short_leg = "Sell a liquid call near the upside target/barrier"
    elif direction == "short":
        trigger = gamma_flip if gamma_flip is not None and (spot is None or gamma_flip <= spot * 1.02) else spot
        target = put_wall if put_wall is not None and (spot is None or put_wall < spot) else None
        invalidation = call_wall if call_wall is not None and (spot is None or call_wall > spot) else None
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
    direction_confirmed = direction_source != "unsigned_activity_bias"
    if direction is None:
        blockers.append("No long/short price or model context; call/put identity is not direction.")
    elif not direction_confirmed:
        blockers.append(
            "Direction is an unsigned activity bias; paper review only until signed or model context confirms it."
        )
    if not confidence.get("is_high"):
        blockers.append(
            confidence.get("reason")
            or f"Calibrated probability is below {HIGH_CONFIDENCE_THRESHOLD:.0%}."
        )
    if confidence.get("setup_ok") is False:
        blockers.append(
            f"Directional model state is {confidence.get('state') or 'WATCH'}; setup gate is not active."
        )

    modeled_complete = bool(model.get("risk_levels_complete")) if model else None
    risk_levels_complete = bool(
        modeled_complete
        if modeled_complete is not None
        else (target is not None and invalidation is not None)
    )
    if model:
        if model.get("strike") is None:
            blockers.append("No measured strike to watch.")
        if not model.get("supports"):
            blockers.append("No measured support to watch.")
    if direction == "long":
        if target is None:
            blockers.append("No measured call wall above spot for the take-profit target.")
        if invalidation is None:
            blockers.append("No measured put wall below spot for invalidation.")
    elif direction == "short":
        if target is None:
            blockers.append("No measured put wall below spot for the take-profit target.")
        if invalidation is None:
            blockers.append("No measured call wall above spot for invalidation.")

    confidence_ready = confidence.get("is_high") and confidence.get("setup_ok") is not False
    if (
        gate_pass and freshness_pass and direction is not None and direction_confirmed
        and confidence_ready and risk_levels_complete
    ):
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
        "risk_levels_complete": risk_levels_complete,
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
    qlib_rows: list[dict] | None = None,
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
    qlib_rows = list(qlib_rows or ())
    board_by_symbol = _index_by_symbol(board_rows)
    flow_by_symbol = _index_by_symbol(flow_rows)
    calibrated_by_symbol = _index_by_symbol(calibrated_rows)
    qlib_by_symbol = _index_by_symbol(qlib_rows)
    symbols = list(dict.fromkeys([*board_by_symbol, *flow_by_symbol]))

    if not symbols:
        return _empty_suggestion_payload("No board or unusual-flow rows were supplied.")

    board_scores = {
        symbol: score for symbol, row in board_by_symbol.items()
        if (score := _finite(row.get("squeeze_score"))) is not None
    }
    flow_scores = {
        symbol: score for symbol, row in flow_by_symbol.items()
        if (score := _finite(row.get("unusual_score"))) is not None
    }
    qlib_scores = {
        symbol: score for symbol, row in qlib_by_symbol.items()
        if (score := _finite(row.get("qlib_score"))) is not None
    }
    board_z = _zscores(board_scores)
    flow_z = _zscores(flow_scores)
    qlib_z = _zscores(qlib_scores)

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

        components = [
            z for z in (board_z.get(symbol), flow_z.get(symbol), qlib_z.get(symbol))
            if z is not None
        ]
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
        activity_lean = str(flow_map.get("activity_lean") or "").strip().lower()
        bias_direction = (
            "long" if activity_lean == "bullish"
            else "short" if activity_lean == "bearish"
            else None
        )
        review_direction = direction or bias_direction
        review_direction_source = direction_source if direction is not None else (
            "unsigned_activity_bias" if bias_direction is not None else direction_source
        )
        costs = _cost_estimate(spread_pct, filters)
        setup_inputs = setup_inputs_from_rows(board_map, flow_map, direction=review_direction)
        level_model = setup_level_model(direction=review_direction, **setup_inputs)
        playbook = _playbook(
            board=board_map,
            direction=review_direction,
            direction_source=review_direction_source,
            gate_pass=gate_pass,
            gate_reasons=gate_reasons,
            freshness_pass=freshness_pass,
            freshness_reason=freshness_reason,
            confidence=confidence,
            costs=costs,
            level_model=level_model,
        )
        qlib_map: Mapping[str, Any] = qlib_by_symbol.get(symbol) or {}
        suggestion = build_suggestion(
            direction=direction,
            playbook_status=str(playbook.get("status") or ""),
            blockers=list(playbook.get("blockers") or []),
            spot=board_map.get("spot") if board_map.get("spot") is not None else flow_map.get("spot"),
            call_wall=board_map.get("call_wall"),
            put_wall=board_map.get("put_wall"),
            qlib=qlib_map,
            activity_lean=activity_lean,
            activity_lean_source=str(flow_map.get("activity_lean_source") or ""),
            chain_focus=(
                board_map.get("contract_focus")
                if isinstance(board_map.get("contract_focus"), Mapping) else None
            ),
            flow_focus=flow_map.get("flow_focus") if isinstance(flow_map.get("flow_focus"), Mapping) else None,
            flow_focus_rejections=(
                flow_map.get("flow_focus_rejections")
                if isinstance(flow_map.get("flow_focus_rejections"), Mapping) else None
            ),
        )
        playbook_target = _finite(playbook.get("target"))
        playbook_invalidation = _finite(playbook.get("invalidation"))
        if review_direction == "long":
            target_source = (
                "call_wall" if playbook_target is not None and playbook_target == _finite(board_map.get("call_wall"))
                else None
            )
            invalidation_source = (
                "put_wall" if playbook_invalidation is not None and playbook_invalidation == _finite(board_map.get("put_wall"))
                else None
            )
        elif review_direction == "short":
            target_source = (
                "put_wall" if playbook_target is not None and playbook_target == _finite(board_map.get("put_wall"))
                else None
            )
            invalidation_source = (
                "call_wall" if playbook_invalidation is not None and playbook_invalidation == _finite(board_map.get("call_wall"))
                else None
            )
        else:
            target_source = invalidation_source = None
        suggestion.update({
            "plan_target": playbook_target,
            "plan_target_source": target_source,
            "plan_invalidation": playbook_invalidation,
            "plan_invalidation_source": invalidation_source,
            "strike": level_model.get("strike"),
            "strike_source": level_model.get("strike_source"),
            "supports": list(level_model.get("supports") or ()),
            "take_profit_zones": list(level_model.get("take_profit_zones") or ()),
            "source_status": dict(level_model.get("source_status") or {}),
            "missing_sources": list(level_model.get("missing_sources") or ()),
            "risk_levels_complete": bool(playbook.get("risk_levels_complete")),
            "risk_missing_fields": list(level_model.get("risk_missing_fields") or [
                label for label, value in (
                    ("GEX take-profit target", playbook_target),
                    ("GEX invalidation", playbook_invalidation),
                ) if value is None
            ]),
        })
        if suggestion.get("invalidation") is None and level_model.get("invalidation") is not None:
            suggestion["invalidation"] = level_model["invalidation"]
            suggestion["invalidation_source"] = level_model["invalidation_source"]
        highlighted = bool(playbook.get("status") == "candidate")
        suggestion_plan = (
            suggestion.get("contract_plan")
            if isinstance(suggestion.get("contract_plan"), Mapping) else None
        )
        live_ready = bool(
            suggestion.get("entry_eligible")
            and suggestion_plan
            and suggestion_plan.get("sizing_eligible")
            and suggestion_plan.get("quote_complete")
        )

        rows.append({
            "symbol": symbol,
            "signal_basis": signal_basis,
            "composite_score": composite_score,
            "board_squeeze_score": board_scores.get(symbol),
            "board_squeeze_z": round(board_z[symbol], 4) if symbol in board_z else None,
            "flow_unusual_score": flow_scores.get(symbol),
            "flow_unusual_z": round(flow_z[symbol], 4) if symbol in flow_z else None,
            "qlib_score": qlib_scores.get(symbol),
            "qlib_rank": (
                int(rank) if (rank := _finite((qlib_map or {}).get("qlib_rank"))) is not None else None
            ),
            "qlib_z": round(qlib_z[symbol], 4) if symbol in qlib_z else None,
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
            "live_ready": live_ready,
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
            "suggestion": suggestion,
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
            "qlib_symbols": len(qlib_by_symbol),
            "qlib_measured": sum(1 for row in rows if row["suggestion"]["qlib"]["measured"]),
            "suggested_call": sum(1 for row in rows if row["suggestion"]["right"] == "call"),
            "suggested_put": sum(1 for row in rows if row["suggestion"]["right"] == "put"),
            "suggested_watch": sum(1 for row in rows if row["suggestion"]["right"] == "watch"),
            "suggested_blocked": sum(1 for row in rows if row["suggestion"]["right"] == "blocked"),
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
            "suggestion.sell is the measured GEX wall on the correct side of spot "
            "(call wall for longs, put/support wall for shorts). Missing or wrong-side "
            "walls stay unmeasured and are never filled from expected-move.",
            "Published qlib/deep-scan ranks overlay the same union when present; "
            "missing scores stay unmeasured and never invent a right.",
        ],
    }
