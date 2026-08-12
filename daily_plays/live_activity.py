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

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .adapters.flow import load_live_flow_activity, load_market_flow_activity
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

    def evaluate(symbol: str) -> dict[str, Any] | None:
        try:
            return _local_activity_row(symbol, load(symbol))
        except Exception:
            return None

    # Parquet decoding is native Arrow work and releases the GIL. A small pool
    # overlaps file reads/decodes without creating the dozens of workers used
    # by the genuinely network-bound live-flow pass. Custom loaders remain
    # serial because tests and caller-provided SDK seams are not guaranteed to
    # be thread-safe.
    if candle_loader is None and len(requested) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(requested)), thread_name_prefix="flow-local") as pool:
            evaluated = list(pool.map(evaluate, requested))
    else:
        evaluated = [evaluate(symbol) for symbol in requested]

    rows: list[dict[str, Any]] = []
    failures = 0
    for row in evaluated:
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


def _signal_alignment(pead_side: str | None, directional_side: str | None) -> str:
    """Classify two differently-timed signals without pretending they are peers.

    PEAD describes the observed opening-gap impulse.  The directional model is
    a multi-session forecast.  They are allowed to disagree, but that conflict
    must be explicit so a consumer never treats two opposing labels as two
    independent trade recommendations.
    """
    if pead_side and directional_side:
        return "agree" if pead_side == directional_side else "conflict"
    if pead_side:
        return "pead_only"
    if directional_side:
        return "directional_only"
    return "none"


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
        signal_alignment = _signal_alignment(pead_side, model_side)
        context_side = (
            "mixed" if signal_alignment == "conflict"
            else model_side or pead_side or "neutral"
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
            "pead_side": pead_side,
            "pead_horizon": "session_open" if pead_side else None,
            "directional_side": model_side,
            "directional_horizon": (models.get(symbol) or {}).get("horizon"),
            "signal_alignment": signal_alignment,
            "calibrated_probability": calibrated_probability,
            "live": bool(flow_row),
            "live_asof": flow_row.get("asof_utc"),
            "premium": round(premium, 2) if premium is not None else None,
            "print_count": int(evidence.get("alert_count") or 0),
            "call_print_count": int(evidence.get("call_print_count") or 0),
            "put_print_count": int(evidence.get("put_print_count") or 0),
            "contract_count": int(evidence.get("contract_count") or 0),
            "call_premium": _finite(evidence.get("call_premium")),
            "put_premium": _finite(evidence.get("put_premium")),
            "put_flow_pct": _finite(evidence.get("put_flow_pct")),
            "otm_premium": _finite(evidence.get("otm_premium")),
            "otm_flow_pct": _finite(evidence.get("otm_flow_pct")),
            "average_otm_pct": _finite(evidence.get("average_otm_pct")),
            "sweep_count": int(evidence.get("sweep_count") or 0),
            "sweep_contracts": int(evidence.get("sweep_contracts") or 0),
            "sweep_premium": _finite(evidence.get("sweep_premium")) or 0.0,
            "sweep_otm_contracts": int(evidence.get("sweep_otm_contracts") or 0),
            "sweep_otm_premium": _finite(evidence.get("sweep_otm_premium")) or 0.0,
            "unusual_contracts": int(evidence.get("unusual_contracts") or 0),
            "average_price": _finite(evidence.get("average_price")),
            "average_dte": _finite(evidence.get("average_dte")),
            "signed_print_count": int(evidence.get("signed_print_count") or 0),
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


# Fallback local catalog used only when symbol files are unavailable. Provider
# coverage for standalone Flow is market-wide and does not use this list.
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
    """Build the standalone Flow board from one market-wide provider tape.

    Local price/volume remains optional ranking context, but it no longer
    decides which symbols the provider is allowed to return. ``live_target_limit``
    and ``max_workers`` remain accepted for API compatibility and are ignored.
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
    live_flow = load_market_flow_activity(
        fetcher=flow_fetcher,
        min_premium=min_premium,
        limit=500,
        timeout_seconds=max(10.0, float(per_symbol_timeout_seconds)),
        allowed_symbols={_symbol(value) for value in symbols} if symbols else None,
    )
    local_by = {_symbol(r.get("symbol")): r for r in local_scan["rows"]}
    flow_rows = list(live_flow.get("rows") or [])
    qualified_flow_rows = [
        row
        for row in flow_rows
        if float(((row.get("evidence") or {}).get("premium") or 0.0)) >= float(min_premium)
    ]
    board: list[dict[str, Any]] = []
    for flow_row in qualified_flow_rows:
        symbol = _symbol(flow_row.get("symbol"))
        if not symbol:
            continue
        evidence = flow_row.get("evidence") if isinstance(flow_row.get("evidence"), Mapping) else {}
        premium = _finite(evidence.get("premium")) or 0.0
        alerts = int(evidence.get("alert_count") or 0)
        # The public threshold is a symbol-level aggregate premium floor.
        # Missing/zero premium cannot prove that a row cleared the floor.
        if premium < min_premium:
            continue
        call_n = int(evidence.get("call_print_count") or 0)
        put_n = int(evidence.get("put_print_count") or 0)
        total_n = max(call_n + put_n, 1)
        call_share = call_n / total_n
        put_share = put_n / total_n
        imbalance = call_share - put_share  # + call heavy, − put heavy
        local = local_by.get(symbol, {})
        # Absolute, cohort-invariant premium transform: adding an unrelated
        # whale must not change every existing row's score. $1M saturates the
        # premium component; the result remains an attention rank, not a
        # historical unusualness estimate or probability.
        premium_component = min(
            math.log1p(max(premium, 0.0)) / math.log1p(1_000_000.0),
            1.0,
        )
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

        direction_signed = bool(evidence.get("direction_signed"))
        signed_side = _context_side(flow_row) if direction_signed else None
        board.append({
            "symbol": symbol,
            "unusual_score": unusual_score,
            "activity_score": local_score or unusual_score,
            "score_kind": "ordinal_unusual_flow",
            "activity_rank": 0,
            "flags": flags[:5],
            # Call/put identity is not aggressor side.  Only an explicitly
            # signed provider observation may supply directional context.
            "context_side": signed_side or "neutral",
            "calibrated_probability": None,
            "live": True,
            "live_asof": flow_row.get("asof_utc"),
            "premium": round(premium, 2),
            "print_count": alerts,
            "call_print_count": call_n,
            "put_print_count": put_n,
            "call_put_imbalance": round(imbalance, 4),
            "contract_count": int(evidence.get("contract_count") or 0),
            "call_premium": _finite(evidence.get("call_premium")),
            "put_premium": _finite(evidence.get("put_premium")),
            "put_flow_pct": _finite(evidence.get("put_flow_pct")),
            "otm_premium": _finite(evidence.get("otm_premium")),
            "otm_flow_pct": _finite(evidence.get("otm_flow_pct")),
            "average_otm_pct": _finite(evidence.get("average_otm_pct")),
            "sweep_count": int(evidence.get("sweep_count") or 0),
            "sweep_contracts": int(evidence.get("sweep_contracts") or 0),
            "sweep_premium": _finite(evidence.get("sweep_premium")) or 0.0,
            "sweep_otm_contracts": int(evidence.get("sweep_otm_contracts") or 0),
            "sweep_otm_premium": _finite(evidence.get("sweep_otm_premium")) or 0.0,
            "unusual_contracts": int(evidence.get("unusual_contracts") or 0),
            "average_price": _finite(evidence.get("average_price")),
            "average_dte": _finite(evidence.get("average_dte")),
            "signed_print_count": int(evidence.get("signed_print_count") or 0),
            "premium_basis": str(evidence.get("premium_basis") or "provider_symbol_aggregate"),
            "ret_1d": local.get("ret_1d"),
            "volume_vs_20d_median": local.get("volume_vs_20d_median"),
            "price_impulse": local.get("price_impulse") or "flat",
            "sources": ["LSE market flow"] + (["daily OHLCV"] if local else []),
            "decision_authorized": False,
            "note": "Unusual flow attention rank — not a directional trade recommendation.",
        })

    board.sort(key=lambda r: (-float(r.get("unusual_score") or 0), -(r.get("premium") or 0), r["symbol"]))
    for rank, row in enumerate(board, start=1):
        row["activity_rank"] = rank

    included_symbols = {str(row.get("symbol") or "") for row in board[:max(1, int(row_limit))]}
    tape = [
        dict(print_row)
        for flow_row in flow_rows
        if str(flow_row.get("symbol") or "") in included_symbols
        for print_row in (flow_row.get("prints") or [])
        if isinstance(print_row, Mapping)
    ]
    tape.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
    tape_print_count = len(tape)
    tape = tape[:max(100, min(500, int(row_limit) * 10))]

    visible_board = board[:max(1, int(row_limit))]
    total_premium = sum(float(row.get("premium") or 0.0) for row in board)
    call_premium = sum(float(row.get("call_premium") or 0.0) for row in board)
    put_premium = sum(float(row.get("put_premium") or 0.0) for row in board)
    classified_premium = call_premium + put_premium
    total_contracts = sum(int(row.get("contract_count") or 0) for row in board)
    signed_prints = sum(int(row.get("signed_print_count") or 0) for row in board)
    board_prints = sum(int(row.get("print_count") or 0) for row in board)
    unusual_contracts = sum(int(row.get("unusual_contracts") or 0) for row in board)
    premium_bases = {str(row.get("premium_basis") or "provider_symbol_aggregate") for row in board}
    summary = {
        "total_premium": round(total_premium, 2),
        "call_premium": round(call_premium, 2),
        "put_premium": round(put_premium, 2),
        "unclassified_premium": round(max(0.0, total_premium - classified_premium), 2),
        # Premium share, not print-count share. Unknown when the provider did
        # not retain contract rights for the premium denominator.
        "put_flow_pct": round(put_premium / classified_premium, 6) if classified_premium > 0 else None,
        "call_flow_pct": round(call_premium / classified_premium, 6) if classified_premium > 0 else None,
        "total_contracts": total_contracts,
        "unusual_contracts": unusual_contracts,
        "sweep_contracts": sum(int(row.get("sweep_contracts") or 0) for row in board),
        "sweep_premium": round(sum(float(row.get("sweep_premium") or 0.0) for row in board), 2),
        "tape_print_count": tape_print_count,
        "visible_tape_print_count": len(tape),
        "signed_print_count": signed_prints,
        "signed_print_pct": round(signed_prints / board_prints, 6) if board_prints > 0 else None,
        "tape_detail_available": bool(tape),
        "premium_basis": (
            next(iter(premium_bases))
            if len(premium_bases) == 1
            else "mixed_provider_basis"
            if premium_bases
            else "unavailable"
        ),
        "scope": "market_wide_provider_window",
        "qualified_symbol_count": len(board),
        "visible_symbol_count": len(visible_board),
    }

    coverage = live_flow.get("coverage") if isinstance(live_flow.get("coverage"), Mapping) else {}
    request_completed = int(coverage.get("request_completed") or 0)
    provider_prints = int(coverage.get("provider_prints") or 0)
    observed_symbols = int(coverage.get("observed_symbols") or 0)
    live_with_activity = int(coverage.get("with_activity") or 0)
    feed_status = (
        "live"
        if board
        else "no_prints"
        if request_completed > 0
        else "unavailable"
    )
    warnings = list(live_flow.get("warnings") or [])
    feed_reason = (
        None
        if feed_status == "live"
        else "The market-wide provider request completed but no prints cleared the premium threshold."
        if feed_status == "no_prints"
        else "The market-wide provider request did not complete."
    )
    provider_asof = max(
        (str(row.get("live_asof") or "") for row in board),
        default="",
    ) or None
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schema_version": "unusual-options-flow-v1",
        # `asof` is the newest retained provider observation, never the request
        # completion time. `generated_at` separately records snapshot creation.
        "asof": provider_asof or generated_at,
        "generated_at": generated_at,
        "rows": visible_board,
        "tape": tape,
        "summary": summary,
        "feed_status": feed_status,
        "feed_reason": feed_reason,
        "coverage": {
            "market_universe": len(catalog),
            "local_scanned": int(local_scan["coverage"]["scanned"]),
            "local_flagged": int(local_scan["coverage"]["flagged"]),
            # Legacy counters stay binary for older consumers. The standalone
            # feed performs one request, not a routed per-symbol fan-out.
            "live_requested": 1,
            "live_completed": request_completed,
            "live_with_activity": live_with_activity,
            "unusual_shown": min(len(board), int(row_limit)),
            "provider_requests": 1,
            "provider_requests_completed": request_completed,
            "provider_prints": provider_prints,
            "observed_symbols": observed_symbols,
        },
        "warnings": warnings,
        "min_premium": min_premium,
        "decision_authorized": False,
        "score_kind": "ordinal_unusual_flow",
        "caveats": [
            "The provider window is one market-wide recent-print request, not a routed symbol scan.",
            "Attention score blends a fixed log-premium scale with optional local activity; it is not historical unusualness or win probability.",
            "Call/put print counts are identity only — not bought/sold direction.",
            "Put flow percentage is put premium divided by classified call + put premium.",
            "OTM distance is max(strike/spot−1, 0) for calls and max(1−strike/spot, 0) for puts.",
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
    progress: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    """Build the dashboard activity board; Deep adds live per-symbol flow.

    Deep mode also attaches a qlib-style cross-sectional research rank over the
    scanned catalog and uses top ranks as a live-target priority tier. Quick
    mode skips full-universe qlib inference (bounded work).
    """
    def report(stage: str, percent: int, message: str) -> None:
        if progress is not None:
            progress(stage, max(0, min(100, int(percent))), message)

    mode = "deep" if str(depth).lower() == "deep" else "quick"
    requested = list(dict.fromkeys(_symbol(value) for value in symbols if _symbol(value)))
    local_symbols = requested if mode == "deep" else requested[:QUICK_LOCAL_LIMIT]
    local_scan = scan_local_market_activity(
        symbols=local_symbols,
        data_dirs=data_dirs,
        candle_loader=candle_loader,
        row_limit=max(len(local_symbols), row_limit),
    )
    report(
        "local_activity",
        25,
        f"Ranked {local_scan['coverage']['scanned']}/{len(local_symbols)} local histories.",
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
    qlib_coverage = qlib_panel.get("coverage") or {}
    report(
        "qlib" if run_qlib else "local_activity",
        55,
        (
            f"Qlib ranked {int(qlib_coverage.get('scored') or 0)} cross-sectional names."
            if run_qlib
            else "Quick mode skipped full-catalog qlib inference."
        ),
    )

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
    live_coverage = live_flow.get("coverage") or {}
    report(
        "live_flow" if mode == "deep" else "local_activity",
        82,
        (
            f"Live flow completed {int(live_coverage.get('completed') or 0)}/"
            f"{int(live_coverage.get('requested') or 0)} routed checks."
            if mode == "deep"
            else "Quick activity pass complete."
        ),
    )
    rows = _merge_activity_rows(
        local_rows=local_scan["rows"],
        live_flow=live_flow,
        pead_candidates=pead_candidates,
        directional_signals=directional_signals,
        limit=row_limit,
    )
    rows = merge_qlib_into_activity_rows(rows, qlib_panel)
    report("merge", 96, f"Merged {len(rows)} ranked activity rows with model context.")

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
