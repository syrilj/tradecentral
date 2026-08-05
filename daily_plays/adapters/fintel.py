"""Fintel Public Data API client (https://api.fintel.io).

Auth: send the key from env ``FINTEL_API_KEY`` as header ``X-API-KEY``.
Never expose the raw key to the browser — only the local api_server proxies.

Responses are normalized for desk analysis (short interest, borrow, ownership,
insiders, unusual options flow, squeeze leaderboard). Analysis-only; never
trade-authorized.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import ssl
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


FINTEL_BASE = os.getenv("FINTEL_API_BASE", "https://api.fintel.io").rstrip("/")
DEFAULT_TIMEOUT_S = float(os.getenv("FINTEL_TIMEOUT_S", "20"))
DEFAULT_COUNTRY = "US"


class FintelAuthError(RuntimeError):
    """Missing or invalid FINTEL_API_KEY."""


class FintelQuotaError(RuntimeError):
    """HTTP 429 — monthly weight / rate limit exceeded on this API key."""


# Human message reused in API payloads and UI.
QUOTA_MESSAGE = (
    "Fintel monthly API key weight limit exceeded (HTTP 429). "
    "Symbol intel and boards will stay empty until the quota resets or you upgrade the plan. "
    "This is a Fintel billing/quota limit, not an EDGE bug. "
    "Reduce polling, reuse cache, or check usage at https://fintel.io/u/dev."
)


def _ssl_context() -> ssl.SSLContext:
    """
    Build a verifying TLS context that works on stock macOS Python installs.

    Python.org builds often ship without a usable system CA store, which yields:
      SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate
    Prefer certifi's CA bundle when available; fall back to the default context.
    Never disables verification unless FINTEL_SSL_INSECURE=1 (dev-only escape hatch).
    """
    insecure = os.getenv("FINTEL_SSL_INSECURE", "").strip().lower() in {"1", "true", "yes"}
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    cafile = os.getenv("FINTEL_CA_BUNDLE", "").strip() or os.getenv("SSL_CERT_FILE", "").strip()
    if not cafile:
        try:
            import certifi  # type: ignore

            cafile = certifi.where()
        except Exception:
            cafile = ""

    if cafile and os.path.isfile(cafile):
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


class FintelClient:
    """Thin REST client. Prefer snake_case fields from Fintel when present."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = FINTEL_BASE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        ssl_context: Optional[ssl.SSLContext] = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("FINTEL_API_KEY", "")).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.ssl_context = ssl_context if ssl_context is not None else _ssl_context()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise FintelAuthError(
                "FINTEL_API_KEY is not set. Add it to edge/.env "
                "(get a key at https://fintel.io/u/dev)."
            )
        return {
            "Accept": "application/json",
            "X-API-KEY": self.api_key,
            "User-Agent": "edge-dashboard/fintel-proxy",
        }

    def get(
        self,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url = f"{url}?{urlencode(clean)}"
        req = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(req, timeout=self.timeout_s, context=self.ssl_context) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200)
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
            snippet = detail[:300]
            if e.code == 401:
                raise FintelAuthError(
                    "Fintel returned 401 Unauthorized — check FINTEL_API_KEY "
                    f"(revoked/invalid). {snippet}"
                ) from e
            if e.code == 429 or "quota_exceeded" in detail.lower() or "rate limit" in detail.lower():
                raise FintelQuotaError(QUOTA_MESSAGE) from e
            raise RuntimeError(f"Fintel HTTP {e.code} on {path}: {snippet}") from e
        except URLError as e:
            reason = e.reason
            msg = f"Fintel network error on {path}: {reason}"
            if "CERTIFICATE_VERIFY_FAILED" in str(reason):
                msg += (
                    " — TLS CA bundle missing. Install certifi "
                    "(`pip install certifi`) or set FINTEL_CA_BUNDLE=/path/to/cacert.pem. "
                    "Dev-only: FINTEL_SSL_INSECURE=1 disables verification (not recommended)."
                )
            raise RuntimeError(msg) from e

        if not body.strip():
            return {"data": None, "meta": {"http_status": status}}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Fintel non-JSON response on {path}: {body[:200]}") from e
        if isinstance(payload, dict):
            return payload
        return {"data": payload, "meta": {"http_status": status}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(payload: Mapping[str, Any]) -> Any:
    if "data" in payload:
        return payload.get("data")
    return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "entries", "results", "rows", "transactions", "owners"):
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    return []


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


def status_payload(client: Optional[FintelClient] = None) -> dict[str, Any]:
    """Config probe — never returns the raw key."""
    c = client or FintelClient()
    return {
        "provider": "fintel",
        "base_url": c.base_url,
        "configured": c.configured,
        "auth_header": "X-API-KEY",
        "env_var": "FINTEL_API_KEY",
        "key_setup_url": "https://fintel.io/u/dev",
        "docs_url": "https://api.fintel.io/",
        "decision_authorized": False,
        "live_capital_authorized": False,
        "hint": (
            "Put your Fintel secret in edge/.env as FINTEL_API_KEY=<key>. "
            "Generate the key at https://fintel.io/u/dev (Developer Dashboard → Generate Key). "
            "Swagger Authorize expects the same value in the X-API-KEY header. "
            "Default depth is 'core' (few weighted calls) to conserve monthly quota."
        ),
    }


def _intel_endpoints(
    base: str,
    *,
    depth: str = "core",
    include_options_flow: bool = False,
) -> dict[str, tuple[str, dict[str, Any] | None]]:
    """
    Endpoint sets by weight budget.

    core  — short + borrow + last price (3 weighted calls)
    full  — owners/insiders/FTD/targets + optional options (many weighted calls)
    """
    depth = (depth or "core").strip().lower()
    endpoints: dict[str, tuple[str, dict[str, Any] | None]] = {
        "last_price": (f"{base}/last-price", None),
        "short_interest": (f"{base}/short-interest", None),
        "borrow_rate": (f"{base}/borrow-rate", None),
    }
    if depth in {"full", "deep", "all"}:
        endpoints.update(
            {
                "short_volume": (f"{base}/short-volume", None),
                "fails_to_deliver": (f"{base}/fails-to-deliver", None),
                "owners": (f"{base}/owners", None),
                "insiders": (f"{base}/insiders", {"count": 15}),
                "price_targets": (f"{base}/price-targets", None),
                "analyst_ratings": (f"{base}/analyst-ratings", None),
            }
        )
        if include_options_flow:
            endpoints["options_flow_unusual"] = (f"{base}/options/flow/unusual", None)
            endpoints["options_flow_summary"] = (f"{base}/options/flow/summary", None)
    return endpoints


def _friendly_err(exc: BaseException) -> tuple[str, bool, bool]:
    """Return (message, is_auth, is_quota)."""
    if isinstance(exc, FintelAuthError):
        return str(exc), True, False
    if isinstance(exc, FintelQuotaError):
        return str(exc), False, True
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "quota" in low or "429" in low:
        return QUOTA_MESSAGE, False, True
    return text, False, False


def fetch_security_intel(
    symbol: str,
    *,
    country: str = DEFAULT_COUNTRY,
    client: Optional[FintelClient] = None,
    include_options_flow: bool = False,
    depth: str = "core",
) -> dict[str, Any]:
    """
    Fetch analysis slices for one security.

    Sequential (not parallel) and stops immediately on quota so we do not
    burn remaining monthly weight on failed sibling calls.
    Default depth=core uses only last-price / short-interest / borrow-rate.
    """
    c = client or FintelClient()
    sym = symbol.strip().upper()
    ctry = (country or DEFAULT_COUNTRY).strip().upper()
    base = f"/v1/securities/{quote(ctry)}/{quote(sym)}"
    depth = (depth or os.getenv("FINTEL_INTEL_DEPTH", "core")).strip().lower()

    endpoints = _intel_endpoints(
        base,
        depth=depth,
        include_options_flow=include_options_flow
        or os.getenv("FINTEL_INCLUDE_OPTIONS", "").strip().lower() in {"1", "true", "yes"},
    )

    blocks: dict[str, Any] = {}
    errors: dict[str, str] = {}
    auth_error: str | None = None
    quota_error: str | None = None

    # Sequential — first 429 aborts the rest of the pack.
    for name, (path, params) in endpoints.items():
        if quota_error:
            errors[name] = "skipped: monthly quota already exceeded"
            blocks[name] = None
            continue
        try:
            raw = c.get(path, params)
            blocks[name] = _data(raw)
        except Exception as e:  # noqa: BLE001 - partial slice failures are expected
            msg, is_auth, is_quota = _friendly_err(e)
            errors[name] = msg
            blocks[name] = None
            if is_auth and auth_error is None:
                auth_error = msg
            if is_quota and quota_error is None:
                quota_error = msg

    if auth_error and len(errors) == len(endpoints) and not any(blocks.values()):
        return {
            "available": False,
            "configured": c.configured,
            "error": auth_error,
            "error_kind": "auth",
            "symbol": sym,
            "country": ctry,
            "depth": depth,
            "generated_at": _utc_now(),
            "decision_authorized": False,
            "live_capital_authorized": False,
        }

    if quota_error and not any(blocks.values()):
        return {
            "available": False,
            "configured": c.configured,
            "error": quota_error,
            "error_kind": "quota",
            "quota_exceeded": True,
            "symbol": sym,
            "country": ctry,
            "depth": depth,
            "blocks": blocks,
            "errors": errors,
            "generated_at": _utc_now(),
            "decision_authorized": False,
            "live_capital_authorized": False,
            "hint": (
                "Owners/insiders/options need depth=full and burn more monthly weight. "
                "Wait for reset, upgrade Fintel plan, or keep depth=core."
            ),
        }

    analysis = _build_analysis_summary(sym, blocks)
    if quota_error:
        analysis["notes"] = list(analysis.get("notes") or []) + [quota_error]

    return {
        "available": True,
        "configured": c.configured,
        "provider": "fintel",
        "symbol": sym,
        "country": ctry,
        "depth": depth,
        "generated_at": _utc_now(),
        "blocks": blocks,
        "errors": errors,
        "analysis": analysis,
        "quota_exceeded": bool(quota_error),
        "error_kind": "quota" if quota_error else None,
        "error": quota_error,
        "decision_authorized": False,
        "live_capital_authorized": False,
        "caveat": (
            "Fintel institutional/short/options intel is for research attention only. "
            "Not a trade signal; not live-capital authorized. "
            f"depth={depth}; prefer Refresh sparingly to conserve monthly quota."
        ),
    }


def fetch_market_stream(
    *,
    client: Optional[FintelClient] = None,
    squeeze_limit: int = 25,
    short_interest_limit: int = 25,
    boards: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Market-wide Fintel boards (polled). Defaults to two boards only to save quota.
    """
    c = client or FintelClient()
    board_data: dict[str, Any] = {}
    errors: dict[str, str] = {}

    catalog: dict[str, tuple[str, dict[str, Any] | None]] = {
        "short_squeeze": ("/v1/leaderboards/short-squeeze", {"limit": squeeze_limit}),
        "short_interest": ("/v1/leaderboards/short-interest", {"limit": short_interest_limit}),
        "gainers": ("/v1/leaderboards/gainers", {"limit": 15}),
        "losers": ("/v1/leaderboards/losers", {"limit": 15}),
        "volume": ("/v1/leaderboards/volume", {"limit": 15}),
        "earnings_calendar": ("/v1/calendar/earnings", None),
        "dividend_calendar": ("/v1/calendar/dividends", None),
    }
    # Default: only the two highest-signal boards (not 7 at once).
    wanted = boards or ["short_squeeze", "short_interest"]
    jobs = {k: catalog[k] for k in wanted if k in catalog}

    auth_error: str | None = None
    quota_error: str | None = None

    # Sequential + stop on quota.
    for name, (path, params) in jobs.items():
        if quota_error:
            errors[name] = "skipped: monthly quota already exceeded"
            board_data[name] = []
            continue
        try:
            raw = c.get(path, params)
            data = _data(raw)
            board_data[name] = _as_list(data) if not isinstance(data, dict) else data
        except Exception as e:  # noqa: BLE001
            msg, is_auth, is_quota = _friendly_err(e)
            errors[name] = msg
            board_data[name] = []
            if is_auth and auth_error is None:
                auth_error = msg
            if is_quota and quota_error is None:
                quota_error = msg

    if (auth_error or quota_error) and not any(
        board_data.get(k) for k in board_data
    ):
        return {
            "available": False,
            "configured": c.configured,
            "error": quota_error or auth_error,
            "error_kind": "quota" if quota_error else "auth",
            "quota_exceeded": bool(quota_error),
            "generated_at": _utc_now(),
            "boards": board_data,
            "errors": errors,
            "decision_authorized": False,
            "live_capital_authorized": False,
        }

    return {
        "available": True,
        "configured": c.configured,
        "provider": "fintel",
        "generated_at": _utc_now(),
        "boards": board_data,
        "errors": errors,
        "quota_exceeded": bool(quota_error),
        "error": quota_error,
        "error_kind": "quota" if quota_error else None,
        "decision_authorized": False,
        "live_capital_authorized": False,
        "poll_hint_seconds": 600,
        "caveat": (
            "Polled Fintel leaderboards — not a live websocket. "
            "Default boards: short_squeeze + short_interest only (quota-aware). "
            "Ordinal attention only; not trade-authorized."
        ),
    }


def search_securities(
    query: str,
    *,
    country: str | None = "US",
    limit: int = 25,
    client: Optional[FintelClient] = None,
) -> dict[str, Any]:
    c = client or FintelClient()
    params: dict[str, Any] = {"query": query, "limit": limit}
    if country:
        params["country"] = country
    try:
        raw = c.get("/v1/securities", params)
    except (FintelAuthError, FintelQuotaError) as e:
        kind = "quota" if isinstance(e, FintelQuotaError) else "auth"
        return {
            "available": False,
            "configured": c.configured,
            "error": str(e),
            "error_kind": kind,
            "quota_exceeded": kind == "quota",
            "query": query,
            "results": [],
        }
    data = _data(raw)
    return {
        "available": True,
        "configured": c.configured,
        "query": query,
        "results": _as_list(data),
        "generated_at": _utc_now(),
    }


def _build_analysis_summary(symbol: str, blocks: Mapping[str, Any]) -> dict[str, Any]:
    """Human-readable desk takeaways from raw Fintel slices."""
    notes: list[str] = []
    metrics: dict[str, Any] = {"symbol": symbol}

    short = blocks.get("short_interest")
    if isinstance(short, dict):
        si = (
            _num(short.get("short_interest_shares"))
            or _num(short.get("shortInterest"))
            or _num(short.get("shares_short"))
        )
        si_pct = (
            _num(short.get("short_interest_percent_of_float"))
            or _num(short.get("shortPercentOfFloat"))
            or _num(short.get("short_pct_float"))
        )
        days = (
            _num(short.get("days_to_cover"))
            or _num(short.get("daysToCover"))
            or _num(short.get("short_ratio"))
        )
        metrics["short_interest_shares"] = si
        metrics["short_pct_float"] = si_pct
        metrics["days_to_cover"] = days
        if si_pct is not None and si_pct >= 10:
            notes.append(f"Elevated short interest: {si_pct:.1f}% of float")
        if days is not None and days >= 5:
            notes.append(f"Days to cover elevated: {days:.1f}")

    borrow = blocks.get("borrow_rate")
    if isinstance(borrow, dict):
        fee = (
            _num(borrow.get("borrow_fee_rate_percent"))
            or _num(borrow.get("fee_rate"))
            or _num(borrow.get("borrowFee"))
        )
        avail = (
            _num(borrow.get("shares_available"))
            or _num(borrow.get("available"))
            or _num(borrow.get("sharesAvailable"))
        )
        metrics["borrow_fee_pct"] = fee
        metrics["borrow_shares_available"] = avail
        if fee is not None and fee >= 5:
            notes.append(f"Hard-to-borrow / high fee: {fee:.2f}%")
        if avail is not None and avail < 100_000:
            notes.append(f"Thin borrow availability: {avail:,.0f} shares")

    owners = blocks.get("owners")
    owner_rows = _as_list(owners)
    metrics["institutional_owner_count"] = len(owner_rows)
    if owner_rows:
        notes.append(f"{len(owner_rows)} institutional owner records returned")

    insiders = _as_list(blocks.get("insiders"))
    metrics["insider_txn_count"] = len(insiders)
    buys = 0
    sells = 0
    for row in insiders:
        if not isinstance(row, dict):
            continue
        side = str(
            row.get("transaction_type")
            or row.get("type")
            or row.get("transactionType")
            or ""
        ).lower()
        if "buy" in side or "purchase" in side or side in {"p", "a"}:
            buys += 1
        elif "sell" in side or "sale" in side or side in {"s", "d"}:
            sells += 1
    metrics["insider_buys"] = buys
    metrics["insider_sells"] = sells
    if buys or sells:
        notes.append(f"Recent insiders: {buys} buy / {sells} sell (raw classification)")

    flow_u = blocks.get("options_flow_unusual")
    flow_rows = _as_list(flow_u)
    metrics["unusual_options_prints"] = len(flow_rows)
    if flow_rows:
        notes.append(f"{len(flow_rows)} unusual options prints on feed")

    last = blocks.get("last_price")
    if isinstance(last, dict):
        px = _num(last.get("price")) or _num(last.get("last")) or _num(last.get("close"))
        metrics["last_price"] = px

    if not notes:
        notes.append("No elevated short/borrow/insider flags from available slices")

    return {
        "headline": notes[0] if notes else f"{symbol}: no flags",
        "notes": notes,
        "metrics": metrics,
        "attention_score": _attention_score(metrics),
    }


def _attention_score(metrics: Mapping[str, Any]) -> float:
    """Ordinal 0–100 desk attention score (not a probability)."""
    score = 0.0
    si_pct = metrics.get("short_pct_float")
    if isinstance(si_pct, (int, float)):
        score += min(35.0, max(0.0, float(si_pct)))
    days = metrics.get("days_to_cover")
    if isinstance(days, (int, float)):
        score += min(20.0, max(0.0, float(days) * 2.5))
    fee = metrics.get("borrow_fee_pct")
    if isinstance(fee, (int, float)):
        score += min(25.0, max(0.0, float(fee) * 2.0))
    prints = metrics.get("unusual_options_prints") or 0
    score += min(15.0, float(prints) * 1.5)
    buys = metrics.get("insider_buys") or 0
    sells = metrics.get("insider_sells") or 0
    if buys > sells:
        score += 5.0
    return round(min(100.0, score), 1)
