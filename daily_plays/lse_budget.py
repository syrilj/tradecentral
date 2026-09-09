"""Count LSE provider requests against the account's daily allowance.

The London Strategic Edge account is capped at a *request count* per UTC day
(``{"detail":"daily request limit reached (15000/day)"}``), separate from the
monthly byte quota on the ``/iso`` tables. When background scans spend that
allowance, every interactive surface -- the market-wide tape, the chain, the
regime warm -- goes blank at once, and nothing in the response says why: the
provider answers 429, ``lse_provider``'s breaker trips, and the desk shows an
empty tape that looks exactly like a quiet session.

This module makes the spend observable and, optionally, bounded:

* every request to the provider host is counted, by route family, HTTP status
  and calling module, into a ledger that survives a server restart;
* once ``LSE_DAILY_REQUEST_BUDGET`` is reached the next call raises rather than
  spending an allowance the operator may want for the desk. Set the budget
  below the account's real limit to hold a reserve back.

Install once, as early as possible, from whichever process talks to LSE.
"""
from __future__ import annotations

import json
import os
import threading
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LSE_HOST = "api.londonstrategicedge.com"

# The provider's own cap. Overridable because it is a plan attribute, not a
# constant of nature -- an upgraded account should not need a code change.
ACCOUNT_DAILY_LIMIT = int(os.getenv("LSE_ACCOUNT_DAILY_LIMIT", "15000") or 15000)

# 0 disables local enforcement and leaves the ledger purely observational,
# which is the right default: a cap that silently starves a surface is the same
# failure this module exists to expose.
LOCAL_BUDGET = int(os.getenv("LSE_DAILY_REQUEST_BUDGET", "0") or 0)

_LEDGER_PATH = Path(
    os.getenv("LSE_BUDGET_LEDGER")
    or (Path(__file__).resolve().parents[1] / "runs" / "lse_request_ledger.json")
)

# Once /iso answers 402 the monthly byte quota is spent until the 1st, and every
# further /iso attempt is a guaranteed 402 that still costs one of the day's
# 15,000 requests before the caller's ladder falls through to the vault. On a
# cold boot roughly a third of the spend was buying that same answer over and
# over. Remember the 402 and answer it locally instead.
SKIP_EXHAUSTED_ISO = (os.getenv("LSE_ISO_SKIP_WHEN_QUOTA_EXHAUSTED", "1") or "1") != "0"

_LOCK = threading.RLock()
_INSTALLED = False
_STATE: dict[str, Any] = {
    "day": "",
    "total": 0,
    "routes": {},
    "statuses": {},
    "callers": {},
    # UTC month ("2026-09") whose /iso byte quota is known spent.
    "iso_quota_exhausted_month": "",
    "iso_requests_skipped": 0,
}


class LSEDailyBudgetExceeded(RuntimeError):
    """Raised instead of spending a request past the locally configured budget."""


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _route_family(url: str) -> str:
    if "/iso/" in url:
        return "iso"
    if "/vault/" in url:
        return "vault"
    return "other"


def _caller() -> str:
    """Coarse attribution: the innermost frame in our own source tree.

    Attribution is the whole point of the ledger -- "15000 requests" is not
    actionable, "11400 of them from promoted_models" is.
    """
    for frame in reversed(traceback.extract_stack()[:-2]):
        path = frame.filename
        if "/lse_budget.py" in path or "/requests/" in path or "/urllib3/" in path:
            continue
        if "/edge/" in path or "/TradingWork/" in path:
            return f"{Path(path).stem}:{frame.name}"
    return "unknown"


def _utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _roll_day_locked() -> None:
    today = _utc_day()
    if _STATE.get("day") != today:
        # The byte quota is monthly, so it must survive the daily roll.
        _STATE.update({"day": today, "total": 0, "routes": {}, "statuses": {}, "callers": {}})
    if _STATE.get("iso_quota_exhausted_month") not in ("", _utc_month()):
        _STATE["iso_quota_exhausted_month"] = ""
        _STATE["iso_requests_skipped"] = 0


def iso_quota_exhausted() -> bool:
    with _LOCK:
        _roll_day_locked()
        return bool(_STATE.get("iso_quota_exhausted_month")) and SKIP_EXHAUSTED_ISO


def _note_iso_quota_exhausted_locked() -> None:
    _STATE["iso_quota_exhausted_month"] = _utc_month()
    _persist_locked()


def _cached_iso_402():
    """The provider's own last answer, replayed without spending a request.

    Shaped as a real 402 Response so every existing ISO->vault ladder --
    raise_for_status(), _should_mark_down(), _provider_status() -- behaves
    exactly as it does against the live provider. Flagged in a header so it is
    never mistaken for a fresh read.
    """
    import requests

    response = requests.Response()
    response.status_code = 402
    response.reason = "Payment Required"
    response._content = (
        b'{"error":"quota_exceeded","message":"Monthly data limit reached. '
        b'Cached locally by lse_budget; no request was sent.","cached":true}'
    )
    response.headers["Content-Type"] = "application/json"
    response.headers["X-Edge-Lse-Budget"] = "iso-quota-cached"
    response.url = "local-cache://iso-quota-exhausted"
    return response


def _load_locked() -> None:
    try:
        raw = json.loads(_LEDGER_PATH.read_text())
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    if raw.get("day") == _utc_day():
        for key in ("day", "total", "routes", "statuses", "callers"):
            if key in raw:
                _STATE[key] = raw[key]
    # The byte quota outlives the day the ledger was written.
    if raw.get("iso_quota_exhausted_month") == _utc_month():
        _STATE["iso_quota_exhausted_month"] = raw["iso_quota_exhausted_month"]
        _STATE["iso_requests_skipped"] = int(raw.get("iso_requests_skipped") or 0)


def _persist_locked() -> None:
    try:
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LEDGER_PATH.write_text(json.dumps(_STATE, indent=2, sort_keys=True))
    except Exception:
        # A ledger that cannot be written must never break the request it is
        # only observing.
        pass


def _record(route: str, caller: str, status: Any) -> None:
    with _LOCK:
        _roll_day_locked()
        _STATE["total"] = int(_STATE.get("total") or 0) + 1
        for bucket, key in (("routes", route), ("callers", caller), ("statuses", f"{route}:{status}")):
            table = _STATE.setdefault(bucket, {})
            table[key] = int(table.get(key) or 0) + 1
        if int(_STATE["total"]) % 25 == 0:
            _persist_locked()


def snapshot() -> dict[str, Any]:
    """Today's spend, newest-first by caller. Safe to call from any thread."""
    with _LOCK:
        _roll_day_locked()
        total = int(_STATE.get("total") or 0)
        callers = Counter(_STATE.get("callers") or {})
        return {
            "day": _STATE.get("day") or _utc_day(),
            "requests_today": total,
            "account_daily_limit": ACCOUNT_DAILY_LIMIT,
            "local_budget": LOCAL_BUDGET or None,
            "remaining_estimate": max(0, ACCOUNT_DAILY_LIMIT - total),
            "iso_quota_exhausted_month": _STATE.get("iso_quota_exhausted_month") or None,
            "iso_requests_skipped": int(_STATE.get("iso_requests_skipped") or 0),
            "routes": dict(_STATE.get("routes") or {}),
            "statuses": dict(_STATE.get("statuses") or {}),
            "top_callers": [
                {"caller": name, "requests": count} for name, count in callers.most_common(12)
            ],
            "ledger_path": str(_LEDGER_PATH),
            "note": (
                "Counted locally by this process tree since the ledger's day began. "
                "The provider keeps its own count; a restart mid-day or another "
                "client on the same key makes this a floor, not the truth."
            ),
        }


def install() -> bool:
    """Wrap requests.Session.request once. Returns whether it wrapped now."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return False
        try:
            import requests
        except Exception:
            return False
        original = requests.sessions.Session.request

        def counted(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
            if LSE_HOST not in str(url):
                return original(self, method, url, *args, **kwargs)
            route = _route_family(str(url))
            caller = _caller()
            if LOCAL_BUDGET:
                with _LOCK:
                    _roll_day_locked()
                    if int(_STATE.get("total") or 0) >= LOCAL_BUDGET:
                        raise LSEDailyBudgetExceeded(
                            f"local LSE budget reached ({LOCAL_BUDGET}/day); "
                            f"raise LSE_DAILY_REQUEST_BUDGET to spend more"
                        )
            if route == "iso" and iso_quota_exhausted():
                with _LOCK:
                    _STATE["iso_requests_skipped"] = int(_STATE.get("iso_requests_skipped") or 0) + 1
                    table = _STATE.setdefault("statuses", {})
                    table["iso:402_cached"] = int(table.get("iso:402_cached") or 0) + 1
                return _cached_iso_402()
            try:
                response = original(self, method, url, *args, **kwargs)
            except Exception:
                _record(route, caller, "exception")
                raise
            status = getattr(response, "status_code", "?")
            _record(route, caller, status)
            if route == "iso" and status == 402:
                with _LOCK:
                    _note_iso_quota_exhausted_locked()
            return response

        requests.sessions.Session.request = counted  # type: ignore[assignment]
        _load_locked()
        _INSTALLED = True
        return True


def flush() -> None:
    with _LOCK:
        _persist_locked()
