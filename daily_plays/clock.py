"""Single New York session clock used by all pipeline adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from zoneinfo import ZoneInfo

from .contracts import MarketSession, RunManifest, RunMode, stable_hash, utc_datetime

NEW_YORK = ZoneInfo("America/New_York")


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return next_month - timedelta(days=(next_month.weekday() - weekday) % 7 + 1)


def _easter(year: int) -> date:
    """Gregorian computus; Good Friday is an NYSE holiday."""
    a, b = year % 19, year // 100
    c, d, e = year % 100, b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(year, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def is_us_equity_holiday(day: date) -> bool:
    """NYSE full-day holidays sufficient for deterministic operational gating."""
    year = day.year
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    return day in holidays


def classify_session(asof_utc: datetime, *, replay: bool = False) -> MarketSession:
    if replay:
        return MarketSession.REPLAY
    local = utc_datetime(asof_utc).astimezone(NEW_YORK)
    if local.weekday() >= 5 or is_us_equity_holiday(local.date()):
        return MarketSession.CLOSED
    value = local.timetz().replace(tzinfo=None)
    if time(4, 0) <= value < time(9, 30):
        return MarketSession.PREMARKET
    if time(9, 30) <= value < time(16, 0):
        return MarketSession.REGULAR
    if time(16, 0) <= value < time(20, 0):
        return MarketSession.AFTER_HOURS
    return MarketSession.CLOSED


@dataclass(frozen=True)
class RunContext:
    requested_for: date
    asof_utc: datetime
    market_session: MarketSession
    mode: RunMode

    @classmethod
    def create(cls, *, asof_utc: datetime | None = None, requested_for: date | None = None,
               mode: RunMode = RunMode.LIVE) -> "RunContext":
        now = utc_datetime(asof_utc or datetime.now(timezone.utc))
        target = requested_for or now.astimezone(NEW_YORK).date()
        return cls(target, now, classify_session(now, replay=mode is RunMode.REPLAY), mode)

    def run_id(self, *, account: float, config_hash: str) -> str:
        stamp = self.asof_utc.strftime("%Y%m%dT%H%M%SZ")
        digest = stable_hash({"requested_for": self.requested_for, "asof_utc": self.asof_utc,
                              "account": account, "config_hash": config_hash, "mode": self.mode})[:12]
        return f"{stamp}-{digest}"

    def manifest(self, *, account: float, config_hash: str, mode: RunMode | None = None) -> RunManifest:
        effective_mode = mode or self.mode
        return RunManifest(run_id=self.run_id(account=account, config_hash=config_hash),
                           requested_for=self.requested_for, asof_utc=self.asof_utc,
                           market_session=self.market_session, account=account, mode=effective_mode,
                           config_hash=config_hash)
