"""Normalize TradingWork unusual-options / forward-flow evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import sys
from threading import Thread
from typing import Any, Callable, Mapping


FLOW_TIMEOUT_SECONDS = 2.0
FLOW_ACTIVITY_TIMEOUT_SECONDS = 6.0
FLOW_ACTIVITY_WORKERS = 8


def _canonical_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol.startswith("EQ."):
        symbol = symbol[3:]
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    return symbol


def _alert_underlying(alert: Mapping[str, Any]) -> str:
    """Return only an explicit underlying identifier.

    The live provider has previously returned an unfiltered 500-row page for
    multiple requested names.  A contract/OCC identifier must not be guessed
    into an underlying here; unverifiable rows are discarded.
    """
    for key in ("underlying", "underlying_symbol", "root_symbol", "ticker", "symbol"):
        value = _canonical_symbol(alert.get(key))
        if value:
            return value
    return ""


def _matching_alerts(alerts: Any, requested_symbol: Any) -> list[Mapping[str, Any]]:
    requested = _canonical_symbol(requested_symbol)
    if not requested or not isinstance(alerts, list):
        return []
    return [
        alert
        for alert in alerts
        if isinstance(alert, Mapping) and _alert_underlying(alert) == requested
    ]


def _bounded_call(call: Callable[[], Any], *, timeout_seconds: float) -> Any:
    """Bound optional evidence retrieval even if its SDK does not timeout."""
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            result["value"] = call()
        except BaseException as exc:
            result["error"] = exc

    worker = Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=max(0.01, float(timeout_seconds)))
    if worker.is_alive():
        raise TimeoutError("flow_provider_timeout")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def load_live_forward_flow(symbol: str, *, timeout_seconds: float = FLOW_TIMEOUT_SECONDS,
                           fetcher: Callable[..., Any] | None = None, **_: Any) -> Mapping[str, Any]:
    """Use TradingWork's live flow seam only; this does not fetch a chain."""
    if not os.getenv("LSE_API_KEY") and fetcher is None:
        return {"_evidence_warning": "flow_lse_credential_missing"}
    try:
        if fetcher is None:
            source = Path(__file__).resolve().parents[3] / "TradingWork" / "src"
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            from lse_provider import fetch_lse_options_flow  # type: ignore[import-not-found]

            def fetcher(*, symbol: str, timeout: float) -> Any:
                # Do not redirect process-global stdout inside the timeout
                # worker. If the daemon outlives the timeout it could swallow
                # the CLI's final report.
                return fetch_lse_options_flow(symbol, timeout=max(1, int(timeout)))
        rows = _bounded_call(lambda: fetcher(symbol=symbol.upper(), timeout=timeout_seconds), timeout_seconds=timeout_seconds)
    except TimeoutError:
        return {"_evidence_warning": "flow_timeout"}
    except Exception as exc:
        return {"_evidence_warning": f"flow_unavailable:{type(exc).__name__}"}
    if rows is None:
        return {"_evidence_warning": "flow_no_live_prints_or_unavailable"}
    raw_rows = list(rows) if isinstance(rows, list) else []
    matched = _matching_alerts(raw_rows, symbol)
    if raw_rows and not matched:
        return {"_evidence_warning": "flow_symbol_mismatch"}
    return normalize_flow_payload(
        {"symbol": symbol.upper(), "alerts": matched, "data_source": "lse_live"}
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_present(row: Mapping[str, Any], *names: str) -> Any:
    return next((row.get(name) for name in names if row.get(name) is not None), None)


def normalize_flow_payload(payload: Mapping[str, Any] | None, *, asof_utc: str | None = None) -> dict[str, Any]:
    """Normalize one ``uoa_scanner`` symbol result or alert into evidence only."""
    raw = dict(payload or {})
    alerts = _matching_alerts(raw.get("alerts"), raw.get("symbol"))
    first = next((a for a in alerts if isinstance(a, Mapping)), raw)
    sentiments = {
        str(value).lower()
        for row in alerts
        for value in (_first_present(row, "sentiment", "direction"),)
        if value is not None and str(value).strip()
    }
    # Actual LSE prints currently have no aggressor or sentiment. Call/put
    # identity alone is not a directional trade, so unsigned activity remains
    # neutral instead of defaulting puts bearish and calls bullish.
    sentiment = next(iter(sentiments)) if len(sentiments) == 1 else "neutral"
    side = "long" if "bull" in sentiment else "short" if "bear" in sentiment else "neutral"
    data_source = raw.get("data_source") or first.get("data_source")
    delayed = bool(data_source and ("DELAY" in str(data_source).upper() or "YAHOO" in str(data_source).upper()))
    premiums = [
        value
        for row in alerts
        for value in (_number(_first_present(row, "premium", "est_premium", "total_premium")),)
        if value is not None
    ]
    volumes = [
        value
        for row in alerts
        for value in (_number(_first_present(row, "volume_today", "volume")),)
        if value is not None
    ]
    call_count = sum(
        "call" in str(_first_present(row, "contract_type", "option_type", "type") or "").lower()
        for row in alerts
    )
    put_count = sum(
        "put" in str(_first_present(row, "contract_type", "option_type", "type") or "").lower()
        for row in alerts
    )
    observed_asof = _first_present(
        first, "asof_utc", "ts", "timestamp", "last_trade_at", "updated_at"
    )
    return {
        "source": "trading_work_flow",
        "symbol": str(raw.get("symbol") or first.get("symbol") or "").upper() or None,
        # Do not turn the caller's run clock into a provider-observation time.
        "asof_utc": raw.get("asof_utc") or observed_asof,
        "direction": side,
        "evidence": {
            "alert_count": len(alerts),
            "score": _number(first.get("score")),
            "premium": sum(premiums) if premiums else None,
            "volume": sum(volumes) if volumes else None,
            "call_print_count": call_count,
            "put_print_count": put_count,
            "direction_signed": side != "neutral",
            "sentiment": sentiment,
            "flow_confidence": first.get("confidence") or first.get("aggressor_label"),
            "data_source": data_source,
            "delayed_or_proxy": delayed,
        },
        "provenance": {"raw_source": "TradingWork/src/uoa_scanner.py"},
    }


def load_live_flow_activity(
    *,
    symbols: list[str] | tuple[str, ...],
    fetcher: Callable[..., Any] | None = None,
    per_symbol_timeout_seconds: float = FLOW_ACTIVITY_TIMEOUT_SECONDS,
    max_workers: int = FLOW_ACTIVITY_WORKERS,
    **_: Any,
) -> Mapping[str, Any]:
    """Scan the heatmap-routed names for direction-neutral live tape activity.

    This board can reprioritize expensive model work.  It cannot create a
    direction, inherit a legacy chain-snapshot calibration, or authorize an
    option-chain request.
    """
    requested = list(dict.fromkeys(
        _canonical_symbol(symbol) for symbol in symbols if _canonical_symbol(symbol)
    ))
    if not requested:
        return {
            "schema_version": "daily-plays-flow-activity-v1",
            "rows": [],
            "requested_symbols": [],
            "coverage": {"requested": 0, "completed": 0, "with_activity": 0, "direction_signed": 0},
            "warnings": [],
        }
    if not os.getenv("LSE_API_KEY") and fetcher is None:
        return {
            "schema_version": "daily-plays-flow-activity-v1",
            "rows": [],
            "requested_symbols": requested,
            "coverage": {"requested": len(requested), "completed": 0, "with_activity": 0, "direction_signed": 0},
            "warnings": ["flow_activity_lse_credential_missing"],
        }

    observed: dict[str, Mapping[str, Any]] = {}
    worker_count = max(1, min(int(max_workers), len(requested), 16))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="flow-activity") as pool:
        pending = {
            pool.submit(
                load_live_forward_flow,
                symbol,
                timeout_seconds=per_symbol_timeout_seconds,
                fetcher=fetcher,
            ): symbol
            for symbol in requested
        }
        for future in as_completed(pending):
            symbol = pending[future]
            try:
                value = future.result()
            except Exception as exc:
                value = {"_evidence_warning": f"flow_activity_unavailable:{type(exc).__name__}"}
            observed[symbol] = value if isinstance(value, Mapping) else {
                "_evidence_warning": "flow_activity_invalid_payload"
            }

    warnings = sorted({
        str(row["_evidence_warning"])
        for row in observed.values()
        if row.get("_evidence_warning")
    })
    rows = [
        dict(row)
        for symbol in requested
        for row in (observed.get(symbol, {}),)
        if not row.get("_evidence_warning")
        and isinstance(row.get("evidence"), Mapping)
        and (
            int((row.get("evidence") or {}).get("alert_count") or 0) > 0
            or float((row.get("evidence") or {}).get("premium") or 0) > 0
        )
    ]
    rows.sort(
        key=lambda row: (
            -float((row.get("evidence") or {}).get("premium") or 0),
            str(row.get("symbol") or ""),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["activity_rank"] = rank
        row["decision_authorized"] = False
        row["directional_calibration_transferred"] = False
    return {
        "schema_version": "daily-plays-flow-activity-v1",
        "rows": rows,
        "requested_symbols": requested,
        "coverage": {
            "requested": len(requested),
            "completed": sum(not row.get("_evidence_warning") for row in observed.values()),
            "with_activity": len(rows),
            "direction_signed": sum(row.get("direction") in {"long", "short"} for row in rows),
        },
        "warnings": warnings,
        "routing_order": list(dict.fromkeys([
            *(str(row.get("symbol") or "") for row in rows),
            *requested,
        ])),
    }
