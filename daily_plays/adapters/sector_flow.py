"""Sector-money-flow discovery for the bounded daily-plays model scan.

The existing TradingAlgoWork heatmap is descriptive routing evidence. It may
choose where expensive model work is spent, but it never changes a model
probability, makes a symbol promotion-eligible, or bypasses execution gates.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

from .promoted_models import EQUITY_WINNER_BAG


ROOT = Path(__file__).resolve().parents[3]
TAW_ROOT = ROOT / "TradingAlgoWork"
DEFAULT_TARGET_LIMIT = 25


def _symbols(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    return [
        symbol
        for symbol in (str(value or "").strip().upper().replace(".US", "") for value in values)
        if symbol and not (symbol in seen or seen.add(symbol))
    ]


def _configured_universe(path: str | Path) -> list[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _symbols(raw.get("symbols", []) if isinstance(raw, Mapping) else [])


def _row_symbols(row: Mapping[str, Any]) -> list[str]:
    return _symbols([row.get("etf"), *(row.get("focus_names") or row.get("names") or [])])


def _compact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "etf": row.get("etf"),
        "name": row.get("name") or row.get("sector"),
        "direction": row.get("flow_direction") or row.get("day_direction"),
        "rs_1d": row.get("rs_1d"),
        "rs_5d": row.get("rs_5d"),
        "definitive": bool(row.get("definitive")),
        "definitive_score": row.get("definitive_score"),
    }


def _round_robin(rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    queues = [_row_symbols(row) for row in rows]
    ordered: list[str] = []
    context: dict[str, dict[str, Any]] = {}
    for row, queue in zip(rows, queues):
        for symbol in queue:
            context.setdefault(
                symbol,
                {
                    "sector_etf": row.get("etf"),
                    "sector_name": row.get("name") or row.get("sector"),
                    "flow_direction": row.get("flow_direction") or row.get("day_direction"),
                    "flow_score": row.get("flow_score"),
                    "rs_1d": row.get("rs_1d"),
                    "rs_5d": row.get("rs_5d"),
                    "definitive": bool(row.get("definitive")),
                },
            )
    cursor = 0
    while any(queues):
        queue = queues[cursor % len(queues)] if queues else []
        if queue:
            ordered.append(queue.pop(0))
        cursor += 1
    return _symbols(ordered), context


def select_sector_targets(
    report: Mapping[str, Any],
    *,
    universe_symbols: Sequence[str],
    limit: int = DEFAULT_TARGET_LIMIT,
    promotion_symbols: Iterable[str] = EQUITY_WINNER_BAG,
) -> dict[str, Any]:
    """Create a sector-balanced model target list from a money-flow report."""
    bounded_limit = max(1, min(int(limit), 50))
    money_in = [row for row in report.get("money_in", []) if isinstance(row, Mapping)]
    money_out = [row for row in report.get("money_out", []) if isinstance(row, Mapping)]
    # Alternate leaders and laggards so one hot sleeve cannot consume the scan.
    directional_rows: list[Mapping[str, Any]] = []
    for index in range(max(len(money_in), len(money_out))):
        if index < len(money_in):
            directional_rows.append(money_in[index])
        if index < len(money_out):
            directional_rows.append(money_out[index])
    routed, symbol_context = _round_robin(directional_rows)

    universe = _symbols(universe_symbols)
    universe_set = set(universe)
    promotion = set(_symbols(promotion_symbols))
    # Existing promotion coverage is always inspected, ordered by sector flow
    # when available. The rest of the budget is descriptive research routing.
    promoted = [symbol for symbol in routed if symbol in promotion]
    promoted.extend(symbol for symbol in universe if symbol in promotion and symbol not in promoted)
    promoted.extend(symbol for symbol in sorted(promotion) if symbol not in promoted)
    promoted = _symbols(promoted)
    # Route only names the configured broad-market model/research universe can
    # actually score.  Sector ETFs still drive the heatmap, but allowing every
    # ETF/theme proxy to consume the bounded target budget left several routed
    # slots with no model data while supported focus names were pushed out.
    routed_supported = [symbol for symbol in routed if symbol in universe_set]
    research = _symbols([*routed_supported, *universe])
    research = [symbol for symbol in research if symbol not in promotion]
    targets = _symbols([*promoted, *research])[:bounded_limit]
    model_covered = [symbol for symbol in targets if symbol in promotion]

    rotation = report.get("rotation") if isinstance(report.get("rotation"), Mapping) else {}
    market_map = {
        "asof": report.get("asof"),
        "asof_bar": report.get("asof_bar"),
        "source": report.get("source"),
        "rotation": {
            "kind": rotation.get("kind"),
            "confidence": rotation.get("confidence"),
            "is_definitive": bool(rotation.get("is_definitive")),
        },
        "money_in": [_compact_row(row) for row in money_in[:4]],
        "money_out": [_compact_row(row) for row in money_out[:4]],
        "missing_themes": list(report.get("missing_themes") or []),
    }
    return {
        "schema_version": "daily-plays-sector-discovery-v1",
        "market_map": market_map,
        "target_symbols": targets,
        "model_covered_symbols": model_covered,
        "research_symbols": [symbol for symbol in targets if symbol not in promotion],
        "routed_but_unsupported_symbols": [
            symbol for symbol in routed if symbol not in universe_set and symbol not in promotion
        ],
        "symbol_context": {symbol: symbol_context.get(symbol, {}) for symbol in targets},
        "sector_books_scored": len(report.get("sectors_ranked") or []),
        "broad_universe_count": len(_symbols([*universe, *routed])),
        "targeted_count": len(targets),
        "model_covered_count": len(model_covered),
    }


def _live_lse_sector_report(
    *,
    context: Any,
    build_report: Any,
    sector_meta: Mapping[str, Mapping[str, Any]],
    fallback_loader: Any | None = None,
) -> Mapping[str, Any]:
    """Fetch a fresh daily sector panel with one SDK request per book."""
    if str(TAW_ROOT) not in sys.path:
        sys.path.insert(0, str(TAW_ROOT))
    from services.market_runtime import LSEAdapter  # type: ignore[import-not-found]
    from .promoted_models import _frame

    client = LSEAdapter(api_key=os.environ["LSE_API_KEY"]).client
    symbols = _symbols([*sector_meta.keys(), "SPY"])
    panel: dict[str, Any] = {}
    start = (context.asof_utc - timedelta(days=180)).strftime("%Y-%m-%d")
    end = (context.asof_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    # Benchmark first guarantees the report can still be built if an optional
    # theme ETF is absent from the LSE catalog.
    ordered = ["SPY", *[symbol for symbol in symbols if symbol != "SPY"]]
    for symbol in ordered:
        try:
            frame = _frame(client.candles(
                symbol, "1d", start=start, end=end, limit=200, order="desc"
            ))
            if not frame.empty:
                if getattr(frame.index, "tz", None) is not None:
                    frame.index = frame.index.tz_localize(None)
                panel[symbol] = frame
        except Exception:
            continue
    lse_count = len(panel)
    missing = [symbol for symbol in symbols if symbol not in panel]
    if fallback_loader and missing:
        try:
            for symbol, frame in fallback_loader(missing, period="6mo").items():
                if frame is not None and not frame.empty:
                    panel[symbol] = frame
        except Exception:
            pass
    fallback_used = any(symbol in panel for symbol in missing)
    source_used = (
        "lse_live_daily+yfinance_missing"
        if lse_count and fallback_used
        else "yfinance"
        if fallback_used
        else "lse_live_daily"
    )
    return build_report(
        panel,
        benchmark="SPY",
        source_used=source_used,
        sector_meta=sector_meta,
    )


def load_sector_flow_discovery(*, context: Any, config: Any, **_: Any) -> Mapping[str, Any]:
    """Run the existing heatmap and normalize it into model-routing evidence."""
    if str(TAW_ROOT) not in sys.path:
        sys.path.insert(0, str(TAW_ROOT))
    try:
        from tools.sector_money_flow import (  # type: ignore[import-not-found]
            SECTOR_META,
            build_report,
            load_ohlcv_yfinance,
            run_scan,
        )

        source = os.environ.get("DAILY_PLAYS_SECTOR_SOURCE", "auto").strip().lower()
        if source not in {"auto", "local", "yfinance"}:
            source = "auto"
        if os.environ.get("LSE_API_KEY") and source == "auto":
            report = _live_lse_sector_report(
                context=context,
                build_report=build_report,
                sector_meta=SECTOR_META,
                fallback_loader=load_ohlcv_yfinance,
            )
            if not report.get("ok"):
                report = run_scan(source="yfinance")
        else:
            report = run_scan(source=source)
    except Exception as exc:
        return {"_evidence_warning": f"sector_flow_unavailable:{type(exc).__name__}"}
    if not isinstance(report, Mapping) or not report.get("ok"):
        return {"_evidence_warning": "sector_flow_report_unavailable"}

    asof_bar = report.get("asof_bar")
    try:
        observed = date.fromisoformat(str(asof_bar))
        requested = context.asof_utc.date()
        stale = (requested - observed).days > 4
    except (TypeError, ValueError):
        stale = True
    if stale:
        return {"_evidence_warning": "sector_flow_report_stale"}

    try:
        requested_limit = int(os.environ.get("DAILY_PLAYS_DISCOVERY_LIMIT", DEFAULT_TARGET_LIMIT))
    except ValueError:
        requested_limit = DEFAULT_TARGET_LIMIT
    universe = _configured_universe(config.universe_path)
    result = select_sector_targets(report, universe_symbols=universe, limit=requested_limit)
    return {**result, "sector_report": dict(report)}
