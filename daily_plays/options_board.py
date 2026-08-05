"""Route the scan's highest-ranked candidates into the options engine.

Background
----------
Until now the options-intelligence engine (``build_options_intelligence``) only
ever ran on a symbol a human typed into the Options view. Every producer of
candidates — the PEAD gap/volume pass, the deep live-flow pass, the activity
board, the frozen-domain directional model — stopped at a symbol list. Nothing
carried those names into a chain fetch, so structure (GEX, walls, squeeze) was
invisible for exactly the names the scan had just surfaced.

This module supplies the missing selection layer. It is deliberately split from
the HTTP/fetch plumbing so the ranking is pure and testable: given a dashboard
status payload, it decides *which* symbols earn an expensive chain request and
*why*, and it compacts a finished intelligence payload into one board row.

What this is not
----------------
None of the inputs are calibrated probabilities. PEAD emits an ordinal score,
the activity board emits an ordinal attention rank, and the qlib cross-section
is research-only. Selecting the top N of an ordinal ranking is a *routing*
decision about where to spend a rate-limited chain request. It is not an edge,
and the squeeze/GEX numbers that come back are diagnostics, not forecasts.

The multiple-testing surface is real and is reported rather than hidden: every
payload carries ``candidates_considered`` alongside ``requested``, so the reader
can see how wide the search was before the top slice was taken. A board that
scores 25 names on 2 sides has not found 50 setups; it has run 50 tests.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

BOARD_SCHEMA_VERSION = "edge-options-board-v1"

#: Selection tiers, highest priority first. A symbol keeps the basis of the
#: first tier that claimed it; later tiers only contribute extra ``sources``.
SELECTION_BASIS_ORDER = (
    "pead_ordinal",
    "live_options_flow",
    "activity_ordinal",
    "directional_model",
)

#: Human-readable justification for each tier, surfaced in the payload so the
#: board can never imply a stronger claim than the input supports.
SELECTION_BASIS_NOTES = {
    "pead_ordinal": "PEAD gap/volume ordinal flag — not a calibrated probability.",
    "live_options_flow": "Live LSE option prints observed on the deep pass — unsigned tape.",
    "activity_ordinal": "Ordinal price/volume attention rank — not a direction.",
    "directional_model": "Frozen-domain model probability — the only calibrated input.",
}

#: ``_merge_activity_rows`` appends this when a row has no real flag, so it must
#: not count as evidence of anything.
_FILLER_FLAG = "ACTIVITY RANK"


def _clean_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text.split()[0] if text else ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class BoardCandidate:
    """One symbol that earned a chain request, and the reason it earned it."""

    symbol: str
    selection_basis: str
    selection_score: float | None
    score_kind: str
    context_side: str | None = None
    sources: list[str] = field(default_factory=list)
    rank: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rank": self.rank,
            "selection_basis": self.selection_basis,
            "selection_basis_note": SELECTION_BASIS_NOTES.get(self.selection_basis, ""),
            "selection_score": self.selection_score,
            "score_kind": self.score_kind,
            "context_side": self.context_side,
            "sources": list(dict.fromkeys(self.sources)),
        }


def _pead_rows(status: Mapping[str, Any]) -> list[BoardCandidate]:
    rows: list[BoardCandidate] = []
    for row in status.get("pead_candidates") or ():
        if not isinstance(row, Mapping):
            continue
        symbol = _clean_symbol(row.get("symbol"))
        if not symbol:
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
        score = _finite(evidence.get("pead_score"))
        side = str(row.get("side") or "").strip().lower() or None
        rows.append(BoardCandidate(
            symbol=symbol,
            selection_basis="pead_ordinal",
            selection_score=round(abs(score), 6) if score is not None else None,
            score_kind="ordinal_score",
            context_side=side,
            sources=["PEAD ordinal flag"],
        ))
    rows.sort(key=lambda c: (-(c.selection_score or 0.0), c.symbol))
    return rows


def _activity_rows(status: Mapping[str, Any]) -> tuple[list[BoardCandidate], list[BoardCandidate]]:
    """Split the activity board into (live-flow tier, flagged-activity tier)."""
    scan = status.get("activity_scan")
    rows = scan.get("rows") if isinstance(scan, Mapping) else None
    live: list[BoardCandidate] = []
    flagged: list[BoardCandidate] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        symbol = _clean_symbol(row.get("symbol"))
        if not symbol:
            continue
        score = _finite(row.get("activity_score"))
        side = str(row.get("context_side") or "").strip().lower() or None
        flags = [str(f) for f in (row.get("flags") or ()) if str(f) != _FILLER_FLAG]
        sources = [str(s) for s in (row.get("sources") or ())]
        has_prints = bool(row.get("live")) and int(row.get("print_count") or 0) > 0
        candidate = BoardCandidate(
            symbol=symbol,
            selection_basis="live_options_flow" if has_prints else "activity_ordinal",
            selection_score=score,
            score_kind="ordinal_activity",
            context_side=side,
            sources=sources or (["LSE live flow"] if has_prints else []),
        )
        if has_prints:
            live.append(candidate)
        elif flags:
            flagged.append(candidate)
    live.sort(key=lambda c: (-(c.selection_score or 0.0), c.symbol))
    flagged.sort(key=lambda c: (-(c.selection_score or 0.0), c.symbol))
    return live, flagged


def _directional_rows(status: Mapping[str, Any]) -> list[BoardCandidate]:
    rows: list[BoardCandidate] = []
    for row in status.get("directional_signals") or ():
        if not isinstance(row, Mapping):
            continue
        symbol = _clean_symbol(row.get("symbol"))
        if not symbol:
            continue
        probability = _finite(row.get("probability"))
        rows.append(BoardCandidate(
            symbol=symbol,
            selection_basis="directional_model",
            # This is the one genuinely calibrated input on the board; keep the
            # kind distinct so the UI never renders it in the same column as an
            # ordinal score.
            selection_score=probability,
            score_kind="calibrated_probability",
            context_side=str(row.get("side") or "").strip().lower() or None,
            sources=["frozen-domain model"],
        ))
    rows.sort(key=lambda c: (-(c.selection_score or 0.0), c.symbol))
    return rows


def select_board_candidates(
    *, status: Mapping[str, Any], limit: int = 25, require_live_flow: bool = False,
) -> tuple[list[BoardCandidate], int]:
    """Rank scan output into the symbols worth an option-chain request.

    Returns ``(selected, considered)`` where ``considered`` is the number of
    distinct symbols the scan offered before the top-``limit`` slice. Reporting
    both is the point: the ratio is the search width behind every board score.

    Tiers are applied in ``SELECTION_BASIS_ORDER``. A symbol claimed by an
    earlier tier keeps that basis and simply accumulates the later tier's
    ``sources``, so a name that is both a PEAD flag and a live-flow print shows
    as PEAD with both provenances attached.
    """
    limit = max(0, int(limit))
    live, flagged = _activity_rows(status)
    tiers: dict[str, list[BoardCandidate]] = {
        "pead_ordinal": _pead_rows(status),
        "live_options_flow": live,
        "activity_ordinal": [] if require_live_flow else flagged,
        "directional_model": [] if require_live_flow else _directional_rows(status),
    }

    merged: dict[str, BoardCandidate] = {}
    order: list[str] = []
    for basis in SELECTION_BASIS_ORDER:
        for candidate in tiers.get(basis, ()):
            existing = merged.get(candidate.symbol)
            if existing is None:
                merged[candidate.symbol] = candidate
                order.append(candidate.symbol)
                continue
            existing.sources.extend(candidate.sources)
            if existing.context_side in (None, "neutral") and candidate.context_side:
                existing.context_side = candidate.context_side

    considered = len(order)
    selected = [merged[symbol] for symbol in order[:limit]]
    for rank, candidate in enumerate(selected, start=1):
        candidate.rank = rank
        candidate.sources = list(dict.fromkeys(candidate.sources))
    return selected, considered


#: A live chain paired with a price series older than this many calendar days is
#: reported as a clock mismatch. The squeeze blend multiplies a chain-derived
#: gamma term by a price-derived momentum term; if those two come from different
#: sessions the product is not a measurement of anything.
CLOCK_SKEW_WARN_DAYS = 2


def clock_skew_days(chain_asof: str | None, price_asof: str | None) -> int | None:
    """Calendar days between the chain observation and the last price bar."""
    if not chain_asof or not price_asof:
        return None
    try:
        chain_day = date.fromisoformat(str(chain_asof)[:10])
        price_day = date.fromisoformat(str(price_asof)[:10])
    except ValueError:
        return None
    return (chain_day - price_day).days


def summarize_board_row(
    candidate: BoardCandidate,
    intel: Mapping[str, Any] | None,
    *,
    error: str | None = None,
    price_asof: str | None = None,
) -> dict[str, Any]:
    """Compact one options-intelligence payload into a single board row.

    A failed or spot-less fetch produces a row with ``available: false`` and the
    reason attached. Dropping the symbol instead would silently narrow the board
    and make coverage look better than it was.

    ``price_asof`` is the timestamp of the last local price bar. It is compared
    against the chain observation so a live chain scored against stale bars is
    flagged rather than rendered as a clean number.
    """
    row = candidate.as_dict()
    row["decision_authorized"] = False

    if error is not None:
        row.update({"available": False, "error": error})
        return row
    if not isinstance(intel, Mapping) or intel.get("error"):
        reason = (
            str(intel.get("error")) if isinstance(intel, Mapping) and intel.get("error")
            else "No options intelligence payload was produced."
        )
        row.update({"available": False, "error": reason})
        return row

    summary = intel.get("summary") if isinstance(intel.get("summary"), Mapping) else {}
    squeeze = summary.get("squeeze") if isinstance(summary.get("squeeze"), Mapping) else {}
    levels = squeeze.get("key_levels") if isinstance(squeeze.get("key_levels"), Mapping) else {}
    probability = intel.get("probability") if isinstance(intel.get("probability"), Mapping) else {}
    quality = intel.get("quality") if isinstance(intel.get("quality"), Mapping) else {}
    provider = intel.get("provider") if isinstance(intel.get("provider"), Mapping) else {}
    freshness = intel.get("freshness") if isinstance(intel.get("freshness"), Mapping) else {}
    context = intel.get("chain_context") if isinstance(intel.get("chain_context"), Mapping) else {}

    row.update({
        "available": True,
        "spot": _finite(summary.get("spot")),
        "squeeze_score": _finite(squeeze.get("score")),
        "squeeze_label": squeeze.get("label"),
        "squeeze_primary": squeeze.get("primary"),
        "structure_score": _finite(squeeze.get("structure_score")),
        "long_gamma_dampened": bool(squeeze.get("long_gamma_dampened")),
        "net_gex_m": _finite(summary.get("total_gex_m")),
        "gex_regime": summary.get("regime"),
        "call_wall": _finite(levels.get("call_wall")),
        "call_wall_pct": _finite(summary.get("call_wall_pct")),
        "put_wall": _finite(levels.get("put_wall")),
        "put_wall_pct": _finite(summary.get("put_wall_pct")),
        "gamma_flip": _finite(levels.get("gamma_flip")),
        "pin_strike": _finite(levels.get("pin_strike")),
        "call_premium": _finite(summary.get("call_premium")),
        "put_premium": _finite(summary.get("put_premium")),
        "activity_imbalance": _finite(summary.get("activity_imbalance")),
        "expected_move": _finite(probability.get("expected_move")),
        "atm_iv": _finite(probability.get("atm_iv")),
        "selected_expiry": context.get("selected_expiry"),
        "selected_dte": context.get("selected_dte"),
        "contracts_included": quality.get("chain_contracts_included"),
        "chain_source": provider.get("chain"),
        "activity_basis": provider.get("activity_basis"),
        "mode_resolved": intel.get("mode_resolved"),
        "observed_at": intel.get("observed_at"),
        "age_seconds": _finite(freshness.get("age_seconds")),
        # Cap the per-row warning list; the detail view carries the full set.
        "warnings": [str(w) for w in (intel.get("warnings") or ())][:3],
    })

    # A GEX of zero because open interest was never observed is NOT a quiet
    # reading — it is an unmeasured one, and rendering it as "quiet 0.0" invents
    # an observation. LSE live quotes omit OI, and the cached-snapshot backfill
    # only covers names with a dated chain folder, so this is the common case on
    # mid-caps. Null the structural fields instead of reporting a false zero.
    # The engine decides measurability; the board only reports it. Falling back
    # to a local recomputation keeps older payloads working.
    oi_source = str(provider.get("open_interest") or "")
    row["open_interest_source"] = oi_source or None
    if "gex_measurable" in quality:
        row["gex_measurable"] = bool(quality.get("gex_measurable"))
    else:
        total_oi = int(summary.get("call_oi") or 0) + int(summary.get("put_oi") or 0)
        row["gex_measurable"] = bool(total_oi > 0 and oi_source != "unavailable")
    if not row["gex_measurable"]:
        for field_name in (
            "net_gex_m", "gex_regime", "call_wall", "call_wall_pct", "put_wall",
            "put_wall_pct", "gamma_flip", "pin_strike", "squeeze_score",
            "squeeze_label", "squeeze_primary", "structure_score",
        ):
            row[field_name] = None
        row["warnings"] = ([
            "Open interest unavailable for this name, so gamma exposure and the "
            "squeeze score are unmeasured — not zero. Back-fill a dated chain "
            "snapshot before reading structure here."
        ] + row["warnings"])[:4]

    skew = clock_skew_days(intel.get("observed_at"), price_asof)
    row["price_asof"] = price_asof
    row["clock_skew_days"] = skew
    row["clock_mismatch"] = bool(skew is not None and skew > CLOCK_SKEW_WARN_DAYS)
    if row["clock_mismatch"]:
        row["warnings"] = ([
            f"Chain is {skew} calendar days newer than the last price bar "
            f"({price_asof}). Momentum and ADV terms in the squeeze score are stale; "
            "refresh market data before reading this row."
        ] + row["warnings"])[:4]
    return row


def board_payload(
    *,
    rows: Sequence[Mapping[str, Any]],
    candidates_considered: int,
    requested: int,
    depth: str,
    scan_asof: str | None,
    asof_utc: str,
    limit: int,
    require_live_flow: bool,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble the wire payload with honest coverage and caveats."""
    priced = [row for row in rows if row.get("available")]
    scored = [row for row in priced if row.get("squeeze_score") is not None]
    mismatched = [row for row in priced if row.get("clock_mismatch")]
    unmeasured = [row for row in priced if not row.get("gex_measurable")]
    warnings = list(warnings)
    if unmeasured:
        warnings.append(
            f"{len(unmeasured)}/{len(priced)} rows have no open-interest source, so their "
            "gamma structure is unmeasured rather than quiet. Only "
            f"{len(scored)} row(s) carry a real squeeze score."
        )
    if mismatched:
        worst = max(int(row.get("clock_skew_days") or 0) for row in mismatched)
        warnings.append(
            f"{len(mismatched)}/{len(priced)} rows score a live chain against price bars "
            f"up to {worst} days old. This is a market-data ingestion gap, not a cache: "
            "re-run the universe fetch before trusting momentum-weighted scores."
        )
    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "asof_utc": asof_utc,
        "scan_asof": scan_asof,
        "depth": depth,
        "limit": limit,
        "require_live_flow": require_live_flow,
        "rows": list(rows),
        "coverage": {
            # candidates_considered vs requested IS the search width. Never drop
            # it from the payload — a top-25 board hides how wide the net was.
            "candidates_considered": int(candidates_considered),
            "requested": int(requested),
            "chain_fetched": len(priced),
            "chain_failed": len(rows) - len(priced),
            "squeeze_scored": len(scored),
            "tests_run": len(scored) * 2,
            "clock_mismatched": len(mismatched),
            "gex_unmeasured": len(unmeasured),
        },
        "selection_basis_notes": dict(SELECTION_BASIS_NOTES),
        "decision_authorized": False,
        "score_kind": "ordinal_structure",
        "warnings": list(dict.fromkeys(str(w) for w in warnings)),
        "caveats": [
            "Selection ranks ordinal scan output. Being on this board is a routing "
            "decision about where to spend a chain request, not an edge.",
            f"{len(scored)} names scored on 2 sides is {len(scored) * 2} tests; treat the "
            "top of the board as a search result, not a discovery.",
            "Squeeze and GEX are uncalibrated structural diagnostics. Only the "
            "frozen-domain model may display a calibrated probability.",
            "Open interest is generally a prior-session observation, so dealer "
            "positioning here is an estimate, not a live ledger.",
        ],
    }
