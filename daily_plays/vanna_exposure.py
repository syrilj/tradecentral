"""Dealer vanna exposure surface for the Vanna tab (GET /api/vanna).

Units: every ``*_vanna_flow`` figure is dollars of dealer DELTA change per
+1 implied-vol POINT — vanna (``_bs_vanna``, per vol point) x open interest x
contract multiplier x spot — signed with the repo's dealer convention:
calls positive (dealer long calls / dealers buy dips into vol spikes), puts
negative (dealer short puts / IV up forces dealer selling).

Aggregation reuses ``options_intelligence._stacked_theta_vanna`` — the exact
Black-Scholes vanna engine behind /api/options — so the numbers the vanna tab
draws reconcile one-to-one with the options tab's theta/vanna bars.

Never fabricates: a missing chain, an empty filtered chain, no trustworthy
spot, or a chain where every contract is unmeasurable all return ``None``
(the endpoint then 404s with an explicit error) — never a plausible literal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Sequence

from .macro_calendar import event_context
from .options_intelligence import (
    OptionsFilters,
    _filter_chain,
    _first,
    _integer,
    _latest_chain,
    _number,
    _stacked_theta_vanna,
)

# Matches OptionsFilters.risk_free_rate default (and /api/options' default).
DEFAULT_RATE = 0.045


def aggregate_vanna_by_expiry(
    contract_rows: Sequence[Mapping[str, Any]],
    asof_day: date,
) -> list[dict[str, Any]]:
    """Pure: group ``_stacked_theta_vanna`` per-contract rows into expiries.

    The per-contract rows carry ``dte`` but not the expiry date; ``dte`` is
    ``(expiry - chain_asof).days`` by construction in ``_normalize_chain_row``,
    so ``expiry = asof_day + dte`` is an exact round-trip, not an estimate.
    ``call_vanna_flow`` sums call contracts' signed flows, ``put_vanna_flow``
    sums put contracts' signed flows (already negative under the dealer
    convention), ``net_vanna_flow`` is their sum.
    """
    by_expiry: dict[date, dict[str, float]] = {}
    for row in contract_rows:
        dte = _integer(row.get("dte"))
        right = row.get("right")
        flow = _number(row.get("vanna_flow"))
        if dte is None or right not in {"call", "put"} or flow is None:
            continue
        expiry = asof_day + timedelta(days=dte)
        cell = by_expiry.setdefault(expiry, {"call": 0.0, "put": 0.0})
        cell[right] += flow
    out: list[dict[str, Any]] = []
    for expiry in sorted(by_expiry):
        cell = by_expiry[expiry]
        out.append(
            {
                "expiry": expiry.isoformat(),
                "dte": (expiry - asof_day).days,
                "call_vanna_flow": round(cell["call"], 4),
                "put_vanna_flow": round(cell["put"], 4),
                "net_vanna_flow": round(cell["call"] + cell["put"], 4),
            }
        )
    return out


def compute_vanna_pivot(
    by_strike: Sequence[Mapping[str, Any]],
    spot: float,
) -> float | None:
    """Strike where cumulative net vanna (low → high strike) crosses zero.

    The crossing bracket is linearly interpolated between the two straddling
    strikes. When the book is entirely one-sided (cumulative never crosses),
    the pivot falls back to the strike with the largest ``|net_vanna_flow|``,
    tie-broken toward spot — the level dealers defend hardest.
    """
    rows = sorted(
        (
            {"strike": float(r["strike"]), "net": float(r["net_vanna_flow"])}
            for r in by_strike
            if _number(r.get("strike")) is not None
            and _number(r.get("net_vanna_flow")) is not None
        ),
        key=lambda r: r["strike"],
    )
    if not rows:
        return None
    cum = 0.0
    prev_strike: float | None = None
    prev_cum = 0.0
    for row in rows:
        new_cum = cum + row["net"]
        crossed = prev_strike is not None and (
            prev_cum == 0.0 or new_cum == 0.0 or (prev_cum > 0) != (new_cum > 0)
        )
        if crossed:
            denom = prev_cum - new_cum
            pivot = (
                prev_strike
                if denom == 0.0
                else prev_strike + (row["strike"] - prev_strike) * prev_cum / denom
            )
            return round(pivot, 4)
        prev_strike, prev_cum, cum = row["strike"], new_cum, new_cum
    dominant = max(
        rows,
        key=lambda r: (abs(r["net"]), -abs(r["strike"] - spot)),
    )
    return round(dominant["strike"], 4)


def _load_cached_chain(symbol: str) -> tuple[list[dict], str | None]:
    """Load the symbol's latest cached chain via the exact helper /api/options
    uses for its cached/history path (``_historical_option_rows`` over
    ``data/option_chains/date=<day>/<SYMBOL>.parquet``, including its
    unreadable-file eviction).

    Deferred import: ``tools.api_server`` imports this module at startup, so
    importing back at module scope would be circular; by call time the server
    module is already in ``sys.modules``.
    """
    try:
        from edge.tools.api_server import _historical_option_rows
    except ImportError:  # pragma: no cover - repo-root invocation style
        from tools.api_server import _historical_option_rows

    rows, selected, _available = _historical_option_rows(symbol, all_days=False)
    return rows, selected


def compute_vanna_surface(
    symbol: str,
    asof: datetime | None = None,
    *,
    rate: float = DEFAULT_RATE,
) -> dict | None:
    """Vanna exposure surface for ``symbol``'s latest cached options chain.

    Returns the /api/vanna JSON contract, or ``None`` when the chain is
    unavailable, empty, has no trustworthy spot, or no measurable contracts.
    """
    eval_asof = asof or datetime.now(timezone.utc)
    if eval_asof.tzinfo is None:
        eval_asof = eval_asof.replace(tzinfo=timezone.utc)

    chain_rows, _selected = _load_cached_chain(symbol.upper())
    if not chain_rows:
        return None
    latest_rows, chain_observed = _latest_chain(chain_rows)
    if not latest_rows:
        return None
    # A dated chain is read against the spot captured WITH that chain — the
    # same observation-clock rule build_options_intelligence documents.
    chain_asof = chain_observed or eval_asof
    observed_spots = [
        value
        for row in latest_rows
        for value in (_number(_first(row, "spot", "underlying_price")),)
        if value is not None and value > 0
    ]
    spot = median(observed_spots) if observed_spots else None
    if spot is None or spot <= 0:
        return None

    # expiry="all" so every expiry feeds the by_expiry lens (the /api/options
    # default "nearest" would collapse the surface to one expiry). Liquidity
    # hygiene (min open interest / spread / plausible IV) keeps the defaults
    # the options tab uses, and _stacked_theta_vanna skips — never clamps —
    # contracts with no IV or T < 1 day.
    filters = OptionsFilters(expiry="all", max_dte=365, risk_free_rate=rate)
    filtered_chain, _rejected, _chain_context = _filter_chain(
        latest_rows,
        asof=chain_asof,
        spot=spot,
        filters=filters,
        selection_date=eval_asof.date(),
    )
    if not filtered_chain:
        return None

    by_strike_rows, _theta_summary, contract_rows, vanna_summary, contracts_skipped = (
        _stacked_theta_vanna(chain_rows=filtered_chain, spot=spot, rate=rate)
    )
    by_strike = [
        {
            "strike": row["strike"],
            "call_vanna_flow": row["call_vanna_flow"],
            "put_vanna_flow": row["put_vanna_flow"],
            "net_vanna_flow": row["net_vanna_flow"],
        }
        for row in by_strike_rows
    ]
    if not by_strike:
        # Every contract unmeasurable (e.g. a 0DTE-only chain): an honest
        # "unavailable" beats a plausible-looking empty surface.
        return None

    return {
        "symbol": symbol.upper(),
        "asof": chain_asof.isoformat(),
        "spot": round(spot, 4),
        "vanna_summary": {
            "net_vanna_flow": vanna_summary["net_vanna_flow"],
            "call_vanna_flow": vanna_summary["call_vanna_flow"],
            "put_vanna_flow": vanna_summary["put_vanna_flow"],
            "direction": vanna_summary["regime"],
            "source": vanna_summary["source"],
            "contracts_skipped": contracts_skipped,
        },
        "by_strike": by_strike,
        "by_expiry": aggregate_vanna_by_expiry(contract_rows, chain_asof.date()),
        "vanna_pivot": compute_vanna_pivot(by_strike, spot),
        "event_context": event_context(eval_asof.date()),
    }
