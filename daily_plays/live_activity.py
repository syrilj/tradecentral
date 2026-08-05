"""Broad market activity scan with an optional live LSE flow pass.

This module deliberately keeps three different ideas separate:

* local price/volume activity is an ordinal ranking, not a probability;
* LSE options prints are live evidence, but unsigned call/put prints are not a
  directional trade recommendation;
* model probabilities are attached only as context when another adapter has
  already produced a calibrated value inside its frozen serving domain.

The separation lets the dashboard flag interesting names without inventing
confidence or applying a 59-name model to a much larger symbol catalog.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .adapters.flow import load_live_flow_activity
from .qlib_scan_score import (
    SCORE_KIND as QLIB_SCORE_KIND,
    SOURCE_ID as QLIB_SOURCE_ID,
    merge_qlib_into_activity_rows,
    publish_shared_qlib_panel,
    qlib_priority_symbols,
    score_cross_section_asof,
)


QUICK_LOCAL_LIMIT = 175
DEEP_LIVE_TARGET_LIMIT = 100
ACTIVITY_ROW_LIMIT = 40
# How many top qlib ranks to promote into live-target routing (deep only).
QLIB_LIVE_PRIORITY_LIMIT = 40


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().removesuffix(".US")


def load_market_symbol_catalog(*, data_dirs: Sequence[str | Path]) -> list[str]:
    """Return the unique locally searchable symbol catalog."""
    symbols = {
        path.stem.upper()
        for raw_dir in data_dirs
        for path in Path(raw_dir).glob("*.parquet")
        if path.is_file()
    }
    return sorted(symbols)


def _frame(raw: Any) -> pd.DataFrame:
    if not hasattr(raw, "copy") or not hasattr(raw, "columns"):
        return pd.DataFrame()
    frame = raw.copy()
    frame = frame.rename(columns={str(column): str(column).lower() for column in frame.columns})
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame.sort_index()
    frame.loc[:, list(required)] = frame.loc[:, list(required)].apply(
        pd.to_numeric, errors="coerce",
    )
    return frame.dropna(subset=["open", "close"]).tail(90)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _zscore(history: pd.Series, value: float) -> float | None:
    clean = pd.to_numeric(history, errors="coerce").dropna()
    if len(clean) < 10:
        return None
    scale = float(clean.std(ddof=1))
    if not math.isfinite(scale) or scale <= 1e-12:
        return 0.0
    return (value - float(clean.mean())) / scale


def _local_activity_row(symbol: str, raw: Any) -> dict[str, Any] | None:
    frame = _frame(raw)
    if len(frame) < 30:
        return None

    close = frame["close"].astype(float)
    open_ = frame["open"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change()
    ret_1d = _finite(returns.iloc[-1])
    ret_5d = _finite(close.iloc[-1] / close.iloc[-6] - 1.0)
    gap_open = _finite(open_.iloc[-1] / close.iloc[-2] - 1.0)
    ret_z = _zscore(returns.iloc[-61:-1], ret_1d) if ret_1d is not None else None

    prior_volume = volume.iloc[-21:-1].dropna()
    prior_median = _finite(prior_volume.median()) if not prior_volume.empty else None
    last_volume = _finite(volume.iloc[-1])
    volume_ratio = (
        last_volume / prior_median
        if last_volume is not None and prior_median is not None and prior_median > 0
        else None
    )
    volume_z = (
        _zscore(volume.iloc[-61:-1], last_volume)
        if last_volume is not None
        else None
    )

    components = {
        "return": min(abs(ret_z or 0.0) / 4.0, 1.0),
        "volume": min(max((volume_ratio or 1.0) - 1.0, 0.0) / 4.0, 1.0),
        "gap": min(abs(gap_open or 0.0) / 0.08, 1.0),
        "move_5d": min(abs(ret_5d or 0.0) / 0.15, 1.0),
    }
    activity_score = round(100.0 * (
        0.35 * components["return"]
        + 0.30 * components["volume"]
        + 0.20 * components["gap"]
        + 0.15 * components["move_5d"]
    ), 1)

    flags: list[str] = []
    if ret_z is not None and abs(ret_z) >= 2.5:
        flags.append("RETURN EXTREME")
    if volume_ratio is not None and volume_ratio >= 2.5:
        flags.append("VOLUME SPIKE")
    if gap_open is not None and abs(gap_open) >= 0.03:
        flags.append("OPEN GAP")
    if ret_5d is not None and abs(ret_5d) >= 0.08:
        flags.append("5D MOVE")

    impulse_value = ret_1d if ret_1d is not None and ret_1d != 0 else gap_open
    impulse = "up" if (impulse_value or 0) > 0 else "down" if (impulse_value or 0) < 0 else "flat"
    last_index = pd.Timestamp(frame.index[-1])
    return {
        "symbol": symbol,
        "asof": last_index.isoformat(),
        "last": round(float(close.iloc[-1]), 2),
        "ret_1d": round(ret_1d, 5) if ret_1d is not None else None,
        "ret_5d": round(ret_5d, 5) if ret_5d is not None else None,
        "ret_1d_z_60d": round(ret_z, 2) if ret_z is not None else None,
        "volume_vs_20d_median": round(volume_ratio, 2) if volume_ratio is not None else None,
        "volume_z_60d": round(volume_z, 2) if volume_z is not None else None,
        "gap_open": round(gap_open, 5) if gap_open is not None else None,
        "activity_score": activity_score,
        "score_kind": "ordinal_activity",
        "price_impulse": impulse,
        "flags": flags,
        "source": "local_daily_ohlcv",
    }


def scan_local_market_activity(
    *,
    symbols: Sequence[str],
    data_dirs: Sequence[str | Path] = (),
    candle_loader: Callable[[str], Any] | None = None,
    row_limit: int = 160,
) -> dict[str, Any]:
    """Rank every requested local name by observed price/volume activity."""
    requested = list(dict.fromkeys(_symbol(value) for value in symbols if _symbol(value)))
    paths = [Path(value) for value in data_dirs]

    def load(symbol: str) -> Any:
        if candle_loader is not None:
            return candle_loader(symbol)
        for base in paths:
            path = base / f"{symbol}.parquet"
            if path.is_file():
                return pd.read_parquet(path)
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    failures = 0
    for symbol in requested:
        try:
            row = _local_activity_row(symbol, load(symbol))
        except Exception:
            row = None
        if row is None:
            failures += 1
        else:
            rows.append(row)

    rows.sort(key=lambda row: (-float(row.get("activity_score") or 0), row["symbol"]))
    flagged = sum(bool(row.get("flags")) for row in rows)
    for rank, row in enumerate(rows, start=1):
        row["market_activity_rank"] = rank
    asof = max((str(row.get("asof") or "") for row in rows), default=None)
    return {
        "schema_version": "market-local-activity-v1",
        "quality": "ok" if rows else "missing",
        "asof": asof,
        "source": "local daily OHLCV parquet",
        "rows": rows[:max(1, int(row_limit))],
        "coverage": {
            "requested": len(requested),
            "scanned": len(rows),
            "failed": failures,
            "flagged": flagged,
        },
        "caveat": "Ordinal activity rank from completed daily bars; not a probability or entry signal.",
    }


def _context_side(row: Mapping[str, Any] | None) -> str | None:
    side = str((row or {}).get("side") or "").strip().lower()
    return side if side in {"long", "short"} else None


def _sector_watch_symbols(sector_flow: Mapping[str, Any] | None) -> list[str]:
    flow = sector_flow if isinstance(sector_flow, Mapping) else {}
    values: list[Any] = []
    for row in flow.get("watch_names") or []:
        values.append(row.get("symbol") if isinstance(row, Mapping) else row)
    values.extend(flow.get("money_in") or [])
    for row in flow.get("sectors_ranked") or []:
        if isinstance(row, Mapping) and float(row.get("flow_score") or 0) >= 0:
            values.append(row.get("etf"))
            values.extend(row.get("focus_names") or [])
    return [_symbol(value).split()[0] for value in values if _symbol(value)]


def _select_live_targets(
    *,
    local_rows: Sequence[Mapping[str, Any]],
    pead_candidates: Sequence[Mapping[str, Any]],
    directional_signals: Sequence[Mapping[str, Any]],
    sector_flow: Mapping[str, Any] | None,
    allowed_symbols: set[str],
    limit: int,
    qlib_priority: Sequence[str] = (),
) -> list[str]:
    """Route the strongest observable setups into the expensive live pass."""
    ranked: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        symbol = _symbol(value).split()[0]
        if symbol and symbol in allowed_symbols and symbol not in seen:
            ranked.append(symbol)
            seen.add(symbol)

    # Actual setup flags get priority, then qlib cross-sectional research ranks
    # (ordinal only), then market-wide activity. Sector/model context fills any
    # remaining live request slots.
    for row in pead_candidates:
        add(row.get("symbol"))
    for symbol in qlib_priority:
        add(symbol)
    for row in local_rows:
        if row.get("flags"):
            add(row.get("symbol"))
    for row in local_rows:
        add(row.get("symbol"))
    for symbol in _sector_watch_symbols(sector_flow):
        add(symbol)
    for row in directional_signals:
        add(row.get("symbol"))
    return ranked[:max(0, int(limit))]


def _merge_activity_rows(
    *,
    local_rows: Sequence[Mapping[str, Any]],
    live_flow: Mapping[str, Any],
    pead_candidates: Sequence[Mapping[str, Any]],
    directional_signals: Sequence[Mapping[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    local = {_symbol(row.get("symbol")): dict(row) for row in local_rows}
    flow = {_symbol(row.get("symbol")): dict(row) for row in live_flow.get("rows") or []}
    pead = {_symbol(row.get("symbol")): row for row in pead_candidates}
    models = {_symbol(row.get("symbol")): row for row in directional_signals}
    max_premium = max(
        (float((row.get("evidence") or {}).get("premium") or 0) for row in flow.values()),
        default=0.0,
    )
    symbols = list(dict.fromkeys([*flow, *local]))
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        local_row = local.get(symbol, {})
        flow_row = flow.get(symbol, {})
        evidence = flow_row.get("evidence") if isinstance(flow_row.get("evidence"), Mapping) else {}
        premium = _finite(evidence.get("premium"))
        local_score = float(local_row.get("activity_score") or 0)
        flow_component = math.sqrt(max(premium or 0.0, 0.0) / max_premium) if max_premium > 0 else 0.0
        activity_score = round(
            min(100.0, 0.65 * local_score + 35.0 * flow_component)
            if max_premium > 0
            else local_score,
            1,
        )

        flags = list(local_row.get("flags") or [])
        if int(evidence.get("alert_count") or 0) > 0:
            flags.insert(0, "LIVE OPTIONS FLOW")
        if (premium or 0) >= 1_000_000:
            flags.insert(0, "$1M+ PREMIUM")
        if not flags:
            flags.append("ACTIVITY RANK")

        pead_side = _context_side(pead.get(symbol))
        model_side = _context_side(models.get(symbol))
        context_side = (
            "mixed" if pead_side and model_side and pead_side != model_side
            else pead_side or model_side or "neutral"
        )
        probability = (models.get(symbol) or {}).get("probability")
        calibrated_probability = (
            float(probability)
            if isinstance(probability, (int, float)) and math.isfinite(float(probability))
            else None
        )
        sources = ["daily OHLCV"] if local_row else []
        if flow_row:
            sources.insert(0, "LSE live flow")
        if symbol in pead:
            sources.append("PEAD ordinal flag")
        if symbol in models:
            sources.append("frozen-domain model")

        rows.append({
            "symbol": symbol,
            "activity_score": activity_score,
            "score_kind": "ordinal_activity",
            "activity_rank": 0,
            "flags": flags,
            "context_side": context_side,
            "calibrated_probability": calibrated_probability,
            "live": bool(flow_row),
            "live_asof": flow_row.get("asof_utc"),
            "premium": round(premium, 2) if premium is not None else None,
            "print_count": int(evidence.get("alert_count") or 0),
            "call_print_count": int(evidence.get("call_print_count") or 0),
            "put_print_count": int(evidence.get("put_print_count") or 0),
            "ret_1d": local_row.get("ret_1d"),
            "volume_vs_20d_median": local_row.get("volume_vs_20d_median"),
            "price_impulse": local_row.get("price_impulse"),
            "sources": sources,
            "decision_authorized": False,
            "note": "Activity flag only; inspect the chain, catalyst, and risk before any trade.",
        })

    rows.sort(key=lambda row: (-float(row["activity_score"]), not row["live"], row["symbol"]))
    for rank, row in enumerate(rows, start=1):
        row["activity_rank"] = rank
    return rows[:max(1, int(limit))]


# Liquid majors always included in the unusual-flow pass so the board is never
# empty solely because local activity ranks thin names first.
_UNUSUAL_FLOW_SEED = (
    "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL",
    "TSLA", "AMD", "AVGO", "NFLX", "JPM", "XOM", "UNH", "V", "MA", "COST",
    "MRVL", "SMCI", "ARM", "PLTR", "COIN", "MSTR", "HOOD", "SOFI", "IONQ",
)


def build_unusual_options_flow(
    *,
    symbols: Sequence[str] = (),
    data_dirs: Sequence[str | Path] = (),
    candle_loader: Callable[[str], Any] | None = None,
    flow_fetcher: Callable[..., Any] | None = None,
    live_target_limit: int = 48,
    row_limit: int = 40,
    min_premium: float = 25_000.0,
    per_symbol_timeout_seconds: float = 3.0,
    max_workers: int = 12,
) -> dict[str, Any]:
    """Market-wide unusual options-flow board (attention rank, not a signal).

    Ranks local price/volume activity, then pulls live LSE tape on the hottest
    targets + liquid seeds. Rows with live premium / alerts surface as
    unusual flow across the market for the Options Drift desk.
    """
    catalog = list(dict.fromkeys(
        [_symbol(s) for s in symbols if _symbol(s)]
        or load_market_symbol_catalog(data_dirs=data_dirs)
        or list(_UNUSUAL_FLOW_SEED)
    ))
    local_scan = scan_local_market_activity(
        symbols=catalog[:QUICK_LOCAL_LIMIT],
        data_dirs=data_dirs,
        candle_loader=candle_loader,
        row_limit=max(len(catalog[:QUICK_LOCAL_LIMIT]), row_limit),
    )
    seeds = [s for s in _UNUSUAL_FLOW_SEED if s in set(catalog) or not symbols]
    live_targets = _select_live_targets(
        local_rows=local_scan["rows"],
        pead_candidates=(),
        directional_signals=(),
        sector_flow=None,
        allowed_symbols=set(catalog) | set(seeds),
        limit=live_target_limit,
    )
    for seed in seeds:
        if seed not in live_targets and len(live_targets) < live_target_limit:
            live_targets.append(seed)

    live_flow = load_live_flow_activity(
        symbols=live_targets,
        fetcher=flow_fetcher,
        per_symbol_timeout_seconds=per_symbol_timeout_seconds,
        max_workers=max_workers,
    )
    local_by = {_symbol(r.get("symbol")): r for r in local_scan["rows"]}
    flow_rows = list(live_flow.get("rows") or [])
    max_premium = max(
        (float((r.get("evidence") or {}).get("premium") or 0) for r in flow_rows),
        default=0.0,
    )

    board: list[dict[str, Any]] = []
    for flow_row in flow_rows:
        symbol = _symbol(flow_row.get("symbol"))
        if not symbol:
            continue
        evidence = flow_row.get("evidence") if isinstance(flow_row.get("evidence"), Mapping) else {}
        premium = _finite(evidence.get("premium")) or 0.0
        alerts = int(evidence.get("alert_count") or 0)
        if premium < min_premium and alerts <= 0:
            continue
        call_n = int(evidence.get("call_print_count") or 0)
        put_n = int(evidence.get("put_print_count") or 0)
        total_n = max(call_n + put_n, 1)
        call_share = call_n / total_n
        put_share = put_n / total_n
        imbalance = call_share - put_share  # + call heavy, − put heavy
        local = local_by.get(symbol, {})
        premium_component = math.sqrt(premium / max_premium) if max_premium > 0 else 0.0
        local_score = float(local.get("activity_score") or 0.0)
        unusual_score = round(min(100.0, 55.0 * premium_component + 0.45 * local_score), 1)

        flags: list[str] = ["LIVE OPTIONS FLOW"]
        if premium >= 1_000_000:
            flags.insert(0, "$1M+ PREMIUM")
        elif premium >= 250_000:
            flags.insert(0, "$250K+ PREMIUM")
        if abs(imbalance) >= 0.45:
            flags.append("CALL HEAVY" if imbalance > 0 else "PUT HEAVY")
        if alerts >= 8:
            flags.append("PRINT CLUSTER")
        for flag in local.get("flags") or []:
            if flag not in flags:
                flags.append(flag)

        board.append({
            "symbol": symbol,
            "unusual_score": unusual_score,
            "activity_score": local_score or unusual_score,
            "score_kind": "ordinal_unusual_flow",
            "activity_rank": 0,
            "flags": flags[:5],
            "context_side": (
                "long" if imbalance >= 0.25 else "short" if imbalance <= -0.25 else "neutral"
            ),
            "calibrated_probability": None,
            "live": True,
            "live_asof": flow_row.get("asof_utc"),
            "premium": round(premium, 2),
            "print_count": alerts,
            "call_print_count": call_n,
            "put_print_count": put_n,
            "call_put_imbalance": round(imbalance, 4),
            "ret_1d": local.get("ret_1d"),
            "volume_vs_20d_median": local.get("volume_vs_20d_median"),
            "price_impulse": local.get("price_impulse") or "flat",
            "sources": ["LSE live flow"] + (["daily OHLCV"] if local else []),
            "decision_authorized": False,
            "note": "Unusual flow attention rank — not a directional trade recommendation.",
        })

    # If live returned nothing, still surface hottest local activity so the
    # board is never a silent empty shell (user can open those names for GEX).
    if not board:
        for local in local_scan["rows"][:row_limit]:
            if not local.get("flags"):
                continue
            board.append({
                "symbol": local["symbol"],
                "unusual_score": float(local.get("activity_score") or 0),
                "activity_score": float(local.get("activity_score") or 0),
                "score_kind": "ordinal_unusual_flow",
                "activity_rank": 0,
                "flags": list(local.get("flags") or ["ACTIVITY RANK"]),
                "context_side": "neutral",
                "calibrated_probability": None,
                "live": False,
                "live_asof": None,
                "premium": None,
                "print_count": 0,
                "call_print_count": 0,
                "put_print_count": 0,
                "call_put_imbalance": None,
                "ret_1d": local.get("ret_1d"),
                "volume_vs_20d_median": local.get("volume_vs_20d_median"),
                "price_impulse": local.get("price_impulse") or "flat",
                "sources": ["daily OHLCV"],
                "decision_authorized": False,
                "note": "Local price/volume activity only — live options tape unavailable.",
            })

    board.sort(key=lambda r: (-float(r.get("unusual_score") or 0), -(r.get("premium") or 0), r["symbol"]))
    for rank, row in enumerate(board, start=1):
        row["activity_rank"] = rank

    coverage = live_flow.get("coverage") if isinstance(live_flow.get("coverage"), Mapping) else {}
    return {
        "schema_version": "unusual-options-flow-v1",
        "asof": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "rows": board[:max(1, int(row_limit))],
        "coverage": {
            "market_universe": len(catalog),
            "local_scanned": int(local_scan["coverage"]["scanned"]),
            "local_flagged": int(local_scan["coverage"]["flagged"]),
            "live_requested": int(coverage.get("requested") or 0),
            "live_completed": int(coverage.get("completed") or 0),
            "live_with_activity": int(coverage.get("with_activity") or 0),
            "unusual_shown": min(len(board), int(row_limit)),
        },
        "warnings": list(live_flow.get("warnings") or []),
        "min_premium": min_premium,
        "decision_authorized": False,
        "score_kind": "ordinal_unusual_flow",
        "caveats": [
            "Unusual score ranks live premium + local activity; not win probability.",
            "Call/put print counts are identity only — not bought/sold direction.",
            "Click a row to open Options Drift / GEX for that symbol.",
        ],
    }


def build_market_activity_scan(
    *,
    symbols: Sequence[str],
    depth: str,
    pead_candidates: Sequence[Mapping[str, Any]] = (),
    directional_signals: Sequence[Mapping[str, Any]] = (),
    sector_flow: Mapping[str, Any] | None = None,
    data_dirs: Sequence[str | Path] = (),
    candle_loader: Callable[[str], Any] | None = None,
    flow_fetcher: Callable[..., Any] | None = None,
    live_target_limit: int = DEEP_LIVE_TARGET_LIMIT,
    per_symbol_timeout_seconds: float = 2.0,
    max_workers: int = 12,
    row_limit: int = ACTIVITY_ROW_LIMIT,
    qlib_asof: str | None = None,
    enable_qlib_score: bool | None = None,
) -> dict[str, Any]:
    """Build the dashboard activity board; Deep adds live per-symbol flow.

    Deep mode also attaches a qlib-style cross-sectional research rank over the
    scanned catalog and uses top ranks as a live-target priority tier. Quick
    mode skips full-universe qlib inference (bounded work).
    """
    mode = "deep" if str(depth).lower() == "deep" else "quick"
    requested = list(dict.fromkeys(_symbol(value) for value in symbols if _symbol(value)))
    local_symbols = requested if mode == "deep" else requested[:QUICK_LOCAL_LIMIT]
    local_scan = scan_local_market_activity(
        symbols=local_symbols,
        data_dirs=data_dirs,
        candle_loader=candle_loader,
        row_limit=max(len(local_symbols), row_limit),
    )

    run_qlib = bool(enable_qlib_score) if enable_qlib_score is not None else mode == "deep"
    qlib_panel: dict[str, Any]
    if run_qlib:
        try:
            qlib_panel = score_cross_section_asof(
                symbols=local_symbols,
                asof=qlib_asof,
                data_dirs=data_dirs,
                candle_loader=candle_loader,
            )
            # Publish so Market trajectory/analyze reuse the same cross-section
            # (ranks/asof/source match deep scan for the same as-of bar set).
            if qlib_panel.get("quality") == "ok":
                publish_shared_qlib_panel(qlib_panel)
        except Exception as exc:  # noqa: BLE001 - fail closed
            qlib_panel = {
                "quality": "missing",
                "score_kind": QLIB_SCORE_KIND,
                "source": QLIB_SOURCE_ID,
                "asof": qlib_asof,
                "rows": [],
                "by_symbol": {},
                "coverage": {
                    "requested": len(local_symbols),
                    "attempted": 0,
                    "scored": 0,
                    "failed": len(local_symbols),
                    "skipped_insufficient_history": 0,
                },
                "warnings": [f"qlib_score_exception: {type(exc).__name__}: {exc}"],
                "decision_authorized": False,
            }
    else:
        qlib_panel = {
            "quality": "skipped",
            "score_kind": QLIB_SCORE_KIND,
            "source": QLIB_SOURCE_ID,
            "asof": None,
            "rows": [],
            "by_symbol": {},
            "coverage": {
                "requested": 0,
                "attempted": 0,
                "scored": 0,
                "failed": 0,
                "skipped_insufficient_history": 0,
            },
            "warnings": ["qlib_score_skipped_quick_scan"] if mode == "quick" else [],
            "decision_authorized": False,
        }

    qlib_priority = (
        qlib_priority_symbols(
            qlib_panel,
            limit=QLIB_LIVE_PRIORITY_LIMIT,
            allowed_symbols=set(requested),
        )
        if mode == "deep" and qlib_panel.get("quality") == "ok"
        else []
    )

    live_targets = _select_live_targets(
        local_rows=local_scan["rows"],
        pead_candidates=pead_candidates,
        directional_signals=directional_signals,
        sector_flow=sector_flow,
        allowed_symbols=set(requested),
        limit=live_target_limit if mode == "deep" else 0,
        qlib_priority=qlib_priority,
    )
    live_flow = load_live_flow_activity(
        symbols=live_targets,
        fetcher=flow_fetcher,
        per_symbol_timeout_seconds=per_symbol_timeout_seconds,
        max_workers=max_workers,
    )
    rows = _merge_activity_rows(
        local_rows=local_scan["rows"],
        live_flow=live_flow,
        pead_candidates=pead_candidates,
        directional_signals=directional_signals,
        limit=row_limit,
    )
    rows = merge_qlib_into_activity_rows(rows, qlib_panel)

    # When qlib ranks are available, re-order the board so high research ranks
    # surface alongside activity without overwriting activity_score or
    # calibrated probabilities. Primary sort remains activity_score; qlib rank
    # is a secondary key so discovery routing is visible.
    if qlib_panel.get("quality") == "ok" and any(r.get("qlib_rank") is not None for r in rows):
        rows.sort(
            key=lambda r: (
                -float(r.get("activity_score") or 0),
                int(r.get("qlib_rank") or 10**9),
                not r.get("live"),
                r.get("symbol") or "",
            ),
        )
        for rank, row in enumerate(rows, start=1):
            row["activity_rank"] = rank

    coverage = live_flow.get("coverage") if isinstance(live_flow.get("coverage"), Mapping) else {}
    qlib_cov = qlib_panel.get("coverage") if isinstance(qlib_panel.get("coverage"), Mapping) else {}
    warnings = list(live_flow.get("warnings") or []) + list(qlib_panel.get("warnings") or [])
    return {
        "schema_version": "market-activity-board-v1",
        "asof": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "depth": mode,
        "rows": rows,
        "qlib_scan": {
            "quality": qlib_panel.get("quality"),
            "score_kind": qlib_panel.get("score_kind") or QLIB_SCORE_KIND,
            "source": qlib_panel.get("source") or QLIB_SOURCE_ID,
            "asof": qlib_panel.get("asof"),
            "coverage": qlib_cov,
            "warnings": list(qlib_panel.get("warnings") or []),
            "decision_authorized": False,
            # Compact top of book for Desk / API consumers (not full universe).
            "top_rows": list(qlib_panel.get("rows") or [])[:row_limit],
        },
        "coverage": {
            "market_universe": len(requested),
            "local_requested": len(local_symbols),
            "local_scanned": int(local_scan["coverage"]["scanned"]),
            "local_failed": int(local_scan["coverage"]["failed"]),
            "local_flagged": int(local_scan["coverage"]["flagged"]),
            "local_asof": local_scan.get("asof"),
            "live_requested": int(coverage.get("requested") or 0),
            "live_completed": int(coverage.get("completed") or 0),
            "live_with_activity": int(coverage.get("with_activity") or 0),
            "qlib_attempted": int(qlib_cov.get("attempted") or 0),
            "qlib_scored": int(qlib_cov.get("scored") or 0),
            "qlib_failed": int(qlib_cov.get("failed") or 0),
            "qlib_priority_routed": len(qlib_priority),
        },
        "warnings": warnings,
        "decision_authorized": False,
        "score_kind": "ordinal_activity",
        "qlib_score_kind": QLIB_SCORE_KIND,
        "caveats": [
            "Activity score is an ordinal attention rank, not win probability.",
            "Qlib cross-sectional score is research/ordinal only — not calibrated confidence.",
            "Unsigned LSE call/put prints do not create a directional trade.",
            "Only the separate frozen-domain model may display calibrated confidence.",
        ],
    }
