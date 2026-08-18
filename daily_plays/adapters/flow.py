"""Normalize TradingWork unusual-options / forward-flow evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import sys
from threading import Thread
from typing import Any, Callable, Mapping

from ..activity_lean import describe_activity_lean
from ..options_intelligence import _annotate_tape_anomalies, _normalize_flow_row, _parse_occ_symbol


FLOW_TIMEOUT_SECONDS = 2.0
FLOW_ACTIVITY_TIMEOUT_SECONDS = 6.0
FLOW_ACTIVITY_WORKERS = 8

# After this many consecutive timeouts, skip remaining LSE calls for the process
# lifetime (or until a success). Stops multi-minute deep-scan hangs + log spam
# when api.londonstrategicedge.com is unreachable.
_LSE_TIMEOUT_STREAK = 0
_LSE_CIRCUIT_OPEN = False
_LSE_CIRCUIT_THRESHOLD = 3


def reset_lse_circuit() -> None:
    """Test helper — re-enable LSE after injected failures."""
    global _LSE_TIMEOUT_STREAK, _LSE_CIRCUIT_OPEN
    _LSE_TIMEOUT_STREAK = 0
    _LSE_CIRCUIT_OPEN = False


def lse_circuit_is_open() -> bool:
    return bool(_LSE_CIRCUIT_OPEN) or bool(os.getenv("EDGE_SKIP_LSE_FLOW"))


def _canonical_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol.startswith("EQ."):
        symbol = symbol[3:]
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    return symbol


def _alert_underlying(alert: Mapping[str, Any]) -> str:
    """Return explicit underlying identifier or extract from OCC option ticker."""
    for key in ("underlying", "underlying_symbol", "root_symbol", "symbol", "ticker", "occ_symbol", "contract_symbol"):
        raw = alert.get(key)
        value = _canonical_symbol(raw)
        if value and not any(ch.isdigit() for ch in value):
            return value
        if raw:
            occ = _parse_occ_symbol(raw)
            if occ.get("symbol"):
                return occ["symbol"]
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
                           min_premium: float = 50_000.0,
                           fetcher: Callable[..., Any] | None = None, **_: Any) -> Mapping[str, Any]:
    """Use TradingWork's live flow seam only; this does not fetch a chain."""
    global _LSE_TIMEOUT_STREAK, _LSE_CIRCUIT_OPEN

    if not os.getenv("LSE_API_KEY") and fetcher is None:
        return {"_evidence_warning": "flow_lse_credential_missing"}
    if lse_circuit_is_open():
        return {"_evidence_warning": "flow_lse_circuit_open"}
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
                return fetch_lse_options_flow(
                    symbol,
                    min_premium=max(0.0, float(min_premium)),
                    timeout=max(1, int(timeout)),
                )
        rows = _bounded_call(
            lambda: fetcher(symbol=symbol.upper(), timeout=timeout_seconds),
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        _LSE_TIMEOUT_STREAK += 1
        if _LSE_TIMEOUT_STREAK >= _LSE_CIRCUIT_THRESHOLD:
            _LSE_CIRCUIT_OPEN = True
        return {"_evidence_warning": "flow_timeout"}
    except Exception as exc:
        # Provider read-timeouts often arrive as requests exceptions, not our
        # TimeoutError wrapper — still trip the circuit on timeout-like errors.
        msg = f"{type(exc).__name__}: {exc}".lower()
        if "timeout" in msg or "timed out" in msg:
            _LSE_TIMEOUT_STREAK += 1
            if _LSE_TIMEOUT_STREAK >= _LSE_CIRCUIT_THRESHOLD:
                _LSE_CIRCUIT_OPEN = True
            return {"_evidence_warning": "flow_timeout"}
        return {"_evidence_warning": f"flow_unavailable:{type(exc).__name__}"}
    if rows is None:
        return {"_evidence_warning": "flow_no_live_prints_or_unavailable"}
    # Success resets the timeout streak so a flaky window can recover.
    _LSE_TIMEOUT_STREAK = 0
    _LSE_CIRCUIT_OPEN = False
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


def _weighted_average(rows: list[dict[str, Any]], key: str) -> float | None:
    """Contract-weighted mean for a print field, with a safe unweighted fallback."""
    observed = [row for row in rows if _number(row.get(key)) is not None]
    if not observed:
        return None
    weighted = [row for row in observed if int(row.get("contracts") or 0) > 0]
    if weighted:
        weight = sum(int(row.get("contracts") or 0) for row in weighted)
        if weight > 0:
            return sum(float(row[key]) * int(row.get("contracts") or 0) for row in weighted) / weight
    return sum(float(row[key]) for row in observed) / len(observed)


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
    normalized_prints: list[dict[str, Any]] = []
    seen_prints: set[tuple[Any, ...]] = set()
    for alert in alerts:
        normalized = _normalize_flow_row(alert)
        if normalized is None:
            continue
        provider_id = _first_present(alert, "id", "trade_id", "print_id", "execution_id")
        identity = (
            "provider", str(provider_id)
        ) if provider_id is not None else (
            normalized["timestamp"], normalized["right"], normalized["strike"],
            normalized["expiry"], round(float(normalized["premium"]), 2),
            normalized["contracts"], normalized["aggressor"],
        )
        if identity in seen_prints:
            continue
        seen_prints.add(identity)
        normalized_prints.append(normalized)
    _annotate_tape_anomalies(normalized_prints)
    normalized_prints.sort(key=lambda row: row["timestamp"], reverse=True)

    symbol = str(raw.get("symbol") or first.get("underlying") or first.get("symbol") or "").upper() or None
    prints: list[dict[str, Any]] = []
    for row in normalized_prints:
        rendered = dict(row)
        rendered["timestamp"] = row["timestamp"].isoformat()
        rendered["expiry"] = row["expiry"].isoformat() if row.get("expiry") else None
        rendered["symbol"] = symbol
        prints.append(rendered)

    call_premium = sum(float(row["premium"]) for row in normalized_prints if row["right"] == "call")
    put_premium = sum(float(row["premium"]) for row in normalized_prints if row["right"] == "put")
    observed_premium = call_premium + put_premium
    total_premium = (
        sum(float(row["premium"]) for row in normalized_prints)
        if normalized_prints
        else sum(premiums)
    )
    contracts = sum(int(row.get("contracts") or 0) for row in normalized_prints)
    otm_rows = [row for row in normalized_prints if float(row.get("otm_pct") or 0.0) > 0]
    otm_premium = sum(float(row["premium"]) for row in otm_rows)
    otm_observed = [row for row in normalized_prints if row.get("otm_pct") is not None]
    otm_distance_denominator = sum(float(row["premium"]) for row in otm_observed)
    average_otm_pct = (
        sum(float(row["otm_pct"]) * float(row["premium"]) for row in otm_observed)
        / otm_distance_denominator
        if otm_distance_denominator > 0
        else None
    )
    sweep_rows = [row for row in normalized_prints if row.get("is_sweep") or row.get("trade_class") == "sweep"]
    sweep_otm_rows = [row for row in sweep_rows if float(row.get("otm_pct") or 0.0) > 0]
    unusual_rows = [row for row in normalized_prints if row.get("is_unusual")]
    flagged_rows = [row for row in normalized_prints if row.get("anomaly_flags")]
    momentum_rows = [row for row in normalized_prints if row.get("is_momentum")]
    moonshot_rows = [row for row in normalized_prints if row.get("is_moonshot")]
    top_position_rows = [row for row in normalized_prints if row.get("is_top_position")]
    signed_rows = [row for row in normalized_prints if row.get("signed_premium") is not None]
    if signed_rows:
        signed_net = sum(float(row["signed_premium"]) for row in signed_rows)
        side = "long" if signed_net > 0 else "short" if signed_net < 0 else "neutral"
        sentiment = "bullish" if signed_net > 0 else "bearish" if signed_net < 0 else "mixed"
    elif normalized_prints:
        # A fully normalized unsigned tape must not inherit direction from C/P.
        side = "neutral"
        sentiment = "neutral"
    activity_lean = describe_activity_lean(
        signed_net_premium=(
            sum(float(row["signed_premium"]) for row in signed_rows) if signed_rows else None
        ),
        signed_print_count=len(signed_rows),
        call_premium=call_premium,
        put_premium=put_premium,
    )
    weighted_price = _weighted_average(normalized_prints, "price")
    weighted_dte = _weighted_average(normalized_prints, "dte")
    observed_asof = _first_present(
        first, "asof_utc", "ts", "timestamp", "last_trade_at", "updated_at"
    )
    if normalized_prints:
        observed_asof = max(row["timestamp"] for row in normalized_prints).isoformat().replace("+00:00", "Z")
    return {
        "source": "trading_work_flow",
        "symbol": symbol,
        # Do not turn the caller's run clock into a provider-observation time.
        "asof_utc": raw.get("asof_utc") or observed_asof,
        "direction": side,
        "evidence": {
            "alert_count": len(normalized_prints) if normalized_prints else len(alerts),
            "score": _number(first.get("score")),
            "premium": total_premium if (normalized_prints or premiums) else None,
            "premium_estimated": any(bool(row.get("premium_estimated")) for row in normalized_prints),
            "premium_basis": "provider_contract_tape" if normalized_prints else "provider_symbol_aggregate",
            "volume": contracts if normalized_prints else sum(volumes) if volumes else None,
            "call_print_count": sum(row["right"] == "call" for row in normalized_prints) if normalized_prints else call_count,
            "put_print_count": sum(row["right"] == "put" for row in normalized_prints) if normalized_prints else put_count,
            "contract_count": contracts,
            "call_premium": round(call_premium, 2) if normalized_prints else None,
            "put_premium": round(put_premium, 2) if normalized_prints else None,
            "call_flow_pct": round(call_premium / observed_premium, 6) if observed_premium > 0 else None,
            "put_flow_pct": round(put_premium / observed_premium, 6) if observed_premium > 0 else None,
            "otm_premium": round(otm_premium, 2) if normalized_prints else None,
            "otm_flow_pct": round(otm_premium / observed_premium, 6) if observed_premium > 0 else None,
            "average_otm_pct": round(average_otm_pct, 6) if average_otm_pct is not None else None,
            "sweep_count": len(sweep_rows),
            "sweep_contracts": sum(int(row.get("contracts") or 0) for row in sweep_rows),
            "sweep_premium": round(sum(float(row["premium"]) for row in sweep_rows), 2),
            "sweep_otm_contracts": sum(int(row.get("contracts") or 0) for row in sweep_otm_rows),
            "sweep_otm_premium": round(sum(float(row["premium"]) for row in sweep_otm_rows), 2),
            "unusual_contracts": sum(int(row.get("contracts") or 0) for row in unusual_rows),
            "flagged_contracts": sum(int(row.get("contracts") or 0) for row in flagged_rows),
            "momentum_contracts": sum(int(row.get("contracts") or 0) for row in momentum_rows),
            "moonshot_contracts": sum(int(row.get("contracts") or 0) for row in moonshot_rows),
            "top_position_contracts": sum(int(row.get("contracts") or 0) for row in top_position_rows),
            "average_heat": (
                round(sum(float(row.get("heat") or 0.0) for row in normalized_prints) / len(normalized_prints), 4)
                if normalized_prints else None
            ),
            "average_price": round(weighted_price, 4) if weighted_price is not None else None,
            "average_dte": round(weighted_dte, 2) if weighted_dte is not None else None,
            "signed_print_count": len(signed_rows),
            "direction_signed": bool(signed_rows),
            "signed_net_premium": round(sum(float(row["signed_premium"]) for row in signed_rows), 2) if signed_rows else None,
            "signed_premium_coverage": round(
                sum(abs(float(row["signed_premium"])) for row in signed_rows) / observed_premium,
                6,
            ) if observed_premium > 0 else None,
            "activity_lean": activity_lean["activity_lean"],
            "activity_lean_source": activity_lean["activity_lean_source"],
            "activity_lean_label": activity_lean["activity_lean_label"],
            "sentiment": sentiment,
            "flow_confidence": first.get("confidence") or first.get("aggressor_label"),
            "data_source": data_source,
            "delayed_or_proxy": delayed,
        },
        "prints": prints,
        "provenance": {"raw_source": "TradingWork/src/uoa_scanner.py"},
    }


def _timestamp_in_window(value: Any, since: str | None, until: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return not since and not until
    if since:
        since_s = since.strip()
        if len(since_s) == 10 and len(text) >= 10:
            if text[:10] < since_s:
                return False
        elif text < since_s:
            return False
    if until:
        until_s = until.strip()
        if len(until_s) == 10 and len(text) >= 10:
            if text[:10] > until_s:
                return False
        elif text > until_s:
            return False
    return True


def load_symbol_flow_tape(
    symbol: str,
    *,
    min_premium: float = 25_000.0,
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
    timeout_seconds: float = 12.0,
    fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """On-demand classified tape for one underlier, optionally time-sliced.

    Uses the same LSE symbol window as live per-name flow. Date bounds are
    sent to the provider when we own the request, and always applied again
    after normalize so injected fixtures stay honest.
    """
    requested = _canonical_symbol(symbol)
    since_s = str(since).strip() if since else None
    until_s = str(until).strip() if until else None
    empty = {
        "schema_version": "symbol-flow-tape-v1",
        "symbol": requested,
        "from": since_s,
        "to": until_s,
        "tape": [],
        "print_count": 0,
        "feed_status": "unavailable",
        "source": "lse_symbol_window",
        "decision_authorized": False,
        "warnings": [],
    }
    if not requested:
        return {**empty, "warnings": ["flow_symbol_required"]}
    if not os.getenv("LSE_API_KEY") and fetcher is None:
        return {**empty, "warnings": ["flow_lse_credential_missing"]}
    if fetcher is None and lse_circuit_is_open():
        return {**empty, "warnings": ["flow_lse_circuit_open"]}

    try:
        if fetcher is None:
            source = Path(__file__).resolve().parents[3] / "TradingWork" / "src"
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            from lse_provider import LSE_ISO_BASE, get_api_key  # type: ignore[import-not-found]
            import requests

            api_key = get_api_key()
            if not api_key:
                return {**empty, "warnings": ["flow_lse_credential_missing"]}

            def fetcher(
                *,
                symbol: str,
                min_premium: float,
                limit: int,
                timeout: float,
                since: str | None,
                until: str | None,
            ) -> Any:
                params: dict[str, str] = {
                    "underlying": f"eq.{symbol}",
                    "premium": f"gte.{max(0.0, float(min_premium))}",
                    "order": "ts.desc",
                    "limit": str(max(1, min(int(limit), 2_000))),
                }
                clauses: list[str] = []
                if since:
                    s_val = f"{since}T00:00:00Z" if len(since) == 10 and "-" in since else since
                    clauses.append(f"ts.gte.{s_val}")
                if until:
                    u_val = f"{until}T23:59:59Z" if len(until) == 10 and "-" in until else until
                    clauses.append(f"ts.lte.{u_val}")
                if clauses:
                    params["and"] = f"({','.join(clauses)})"
                response = requests.get(
                    f"{LSE_ISO_BASE}/x_options_flow",
                    headers={"x-api-key": api_key, "Accept": "application/json"},
                    params=params,
                    timeout=max(1.0, float(timeout)),
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("flow_symbol_invalid_payload")
                return payload

        fetched = _bounded_call(
            lambda: fetcher(
                symbol=requested,
                min_premium=max(0.0, float(min_premium)),
                limit=max(1, min(int(limit), 2_000)),
                timeout=timeout_seconds,
                since=since_s,
                until=until_s,
            ),
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        return {**empty, "warnings": ["flow_timeout"]}
    except Exception as exc:
        return {**empty, "warnings": [f"flow_unavailable:{type(exc).__name__}"]}

    raw_rows = [dict(row) for row in fetched or [] if isinstance(row, Mapping)]
    normalized = normalize_flow_payload({
        "symbol": requested,
        "alerts": raw_rows,
        "data_source": "lse_symbol_window",
    })
    tape = [
        row
        for row in (normalized.get("prints") or [])
        if isinstance(row, Mapping) and _timestamp_in_window(row.get("timestamp"), since_s, until_s)
    ]
    return {
        "schema_version": "symbol-flow-tape-v1",
        "symbol": requested,
        "from": since_s,
        "to": until_s,
        "tape": tape,
        "print_count": len(tape),
        "feed_status": "live" if tape else "no_prints",
        "source": "lse_symbol_window",
        "min_premium": float(min_premium),
        "decision_authorized": False,
        "warnings": [],
        "evidence": normalized.get("evidence") if isinstance(normalized, Mapping) else {},
    }


def load_market_flow_activity(
    *,
    min_premium: float = 25_000.0,
    limit: int = 500,
    timeout_seconds: float = 15.0,
    fetcher: Callable[..., Any] | None = None,
    allowed_symbols: set[str] | None = None,
) -> Mapping[str, Any]:
    """Fetch one market-wide provider tape and normalize it by underlying.

    This is the standalone Flow feed. It intentionally does not inherit the
    Deep scan's routed-symbol coverage or fan out one request per symbol.
    """
    if not os.getenv("LSE_API_KEY") and fetcher is None:
        return {
            "schema_version": "market-options-flow-v1",
            "rows": [],
            "coverage": {
                "request_completed": 0,
                "provider_prints": 0,
                "observed_symbols": 0,
                "with_activity": 0,
            },
            "warnings": ["flow_lse_credential_missing"],
        }

    try:
        if fetcher is None:
            source = Path(__file__).resolve().parents[3] / "TradingWork" / "src"
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            from lse_provider import LSE_ISO_BASE, get_api_key  # type: ignore[import-not-found]
            import requests

            api_key = get_api_key()
            if not api_key:
                raise RuntimeError("flow_lse_credential_missing")

            def fetcher(*, min_premium: float, limit: int, timeout: float) -> Any:
                response = requests.get(
                    f"{LSE_ISO_BASE}/x_options_flow",
                    headers={"x-api-key": api_key, "Accept": "application/json"},
                    params={
                        "premium": f"gte.{max(0.0, float(min_premium))}",
                        "order": "ts.desc",
                        "limit": str(max(1, min(int(limit), 2_000))),
                    },
                    timeout=max(1.0, float(timeout)),
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("flow_market_invalid_payload")
                return payload

        fetched = _bounded_call(
            lambda: fetcher(
                min_premium=max(0.0, float(min_premium)),
                limit=max(1, min(int(limit), 2_000)),
                timeout=timeout_seconds,
            ),
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        return {
            "schema_version": "market-options-flow-v1",
            "rows": [],
            "coverage": {
                "request_completed": 0,
                "provider_prints": 0,
                "observed_symbols": 0,
                "with_activity": 0,
            },
            "warnings": ["flow_market_timeout"],
        }
    except Exception as exc:
        return {
            "schema_version": "market-options-flow-v1",
            "rows": [],
            "coverage": {
                "request_completed": 0,
                "provider_prints": 0,
                "observed_symbols": 0,
                "with_activity": 0,
            },
            "warnings": [f"flow_market_unavailable:{type(exc).__name__}"],
        }

    raw_rows = [dict(row) for row in fetched or [] if isinstance(row, Mapping)]
    allowed = {_canonical_symbol(symbol) for symbol in allowed_symbols or set()}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        symbol = _alert_underlying(row)
        if not symbol or (allowed and symbol not in allowed):
            continue
        grouped.setdefault(symbol, []).append(row)

    rows: list[dict[str, Any]] = []
    for symbol, alerts in grouped.items():
        normalized = normalize_flow_payload({
            "symbol": symbol,
            "alerts": alerts,
            "data_source": "lse_market_flow",
        })
        evidence = normalized.get("evidence")
        if (
            isinstance(evidence, Mapping)
            and (
                int(evidence.get("alert_count") or 0) > 0
                or float(evidence.get("premium") or 0.0) > 0
            )
        ):
            rows.append(normalized)
    rows.sort(key=lambda row: -float((row.get("evidence") or {}).get("premium") or 0.0))

    return {
        "schema_version": "market-options-flow-v1",
        "rows": rows,
        "coverage": {
            "request_completed": 1,
            "provider_prints": len(raw_rows),
            "observed_symbols": len(grouped),
            "with_activity": len(rows),
        },
        "warnings": [],
    }


def load_live_flow_activity(
    *,
    symbols: list[str] | tuple[str, ...],
    fetcher: Callable[..., Any] | None = None,
    per_symbol_timeout_seconds: float = FLOW_ACTIVITY_TIMEOUT_SECONDS,
    min_premium: float = 50_000.0,
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
    if lse_circuit_is_open() and fetcher is None:
        return {
            "schema_version": "daily-plays-flow-activity-v1",
            "rows": [],
            "requested_symbols": requested,
            "coverage": {
                "requested": len(requested),
                "completed": 0,
                "with_activity": 0,
                "direction_signed": 0,
            },
            "warnings": ["flow_lse_circuit_open"],
        }

    observed: dict[str, Mapping[str, Any]] = {}
    # When LSE is healthy keep parallelism; circuit already short-circuits above.
    worker_count = max(1, min(int(max_workers), len(requested), 16))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="flow-activity") as pool:
        pending = {
            pool.submit(
                load_live_forward_flow,
                symbol,
                timeout_seconds=per_symbol_timeout_seconds,
                min_premium=min_premium,
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
            # Mid-batch circuit: cancel remaining work once open.
            if lse_circuit_is_open() and fetcher is None:
                for fut, sym in pending.items():
                    if fut is not future and not fut.done() and sym not in observed:
                        fut.cancel()
                        observed[sym] = {"_evidence_warning": "flow_lse_circuit_open"}
                break

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
