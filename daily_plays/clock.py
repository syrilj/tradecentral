"""Single New York session clock used by all pipeline adapters.

``exchange_calendars`` is the authoritative calendar when installed.  A small
conservative fallback keeps the decision-support CLI usable in stripped-down
environments, but callers can see which source produced every clock snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import MarketSession, RunManifest, RunMode, stable_hash, utc_datetime

NEW_YORK = ZoneInfo("America/New_York")
EXCHANGE = "XNYS"


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
        # New Year's Day can be observed on December 31 of the prior year.
        _observed(date(year, 1, 1)),
        _observed(date(year + 1, 1, 1)),
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


def _is_fallback_early_close(day: date) -> bool:
    """Known recurring XNYS 13:00 closes used only without the dependency.

    The fallback deliberately covers the recurring modern rules rather than
    pretending to be a complete historical exchange calendar.
    """
    if day.weekday() >= 5 or is_us_equity_holiday(day):
        return False
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    return day in {
        thanksgiving + timedelta(days=1),
        date(day.year, 7, 3),
        date(day.year, 12, 24),
    }


def _at_local(day: date, value: time) -> datetime:
    return datetime.combine(day, value, tzinfo=NEW_YORK).astimezone(timezone.utc)


def _next_fallback_session(day: date) -> date:
    candidate = day
    for _ in range(370):
        if candidate.weekday() < 5 and not is_us_equity_holiday(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError("could not resolve the next XNYS session")


@lru_cache(maxsize=1)
def _xnys_calendar() -> tuple[Any | None, str, str | None]:
    """Load the optional calendar once without making the core CLI depend on it."""
    try:
        import exchange_calendars as xcals
    except ImportError:
        return None, "builtin_fallback", (
            "exchange_calendars is unavailable; recurring XNYS rules are in use"
        )
    return xcals.get_calendar(EXCHANGE), f"exchange_calendars:{xcals.__version__}", None


@dataclass(frozen=True)
class MarketClockStatus:
    asof_utc: datetime
    exchange: str
    market_session: MarketSession
    is_trading_day: bool
    is_early_close: bool
    regular_open_utc: datetime | None
    regular_close_utc: datetime | None
    next_regular_open_utc: datetime | None
    next_transition_utc: datetime | None
    next_transition: str | None
    calendar_source: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value else None

        return {
            "asof_utc": iso(self.asof_utc),
            "exchange": self.exchange,
            "market_session": self.market_session.value,
            "is_trading_day": self.is_trading_day,
            "is_early_close": self.is_early_close,
            "regular_open_utc": iso(self.regular_open_utc),
            "regular_close_utc": iso(self.regular_close_utc),
            "next_regular_open_utc": iso(self.next_regular_open_utc),
            "next_transition_utc": iso(self.next_transition_utc),
            "next_transition": self.next_transition,
            "calendar_source": self.calendar_source,
            "warning": self.warning,
        }


def _calendar_day(day: date) -> tuple[bool, datetime | None, datetime | None, bool, str, str | None]:
    calendar, source, warning = _xnys_calendar()
    if calendar is not None:
        # exchange_calendars accepts date-like values and returns UTC-aware
        # pandas Timestamps. Convert at this boundary so the rest of the app
        # stays pandas-independent.
        if not calendar.is_session(day):
            return False, None, None, False, source, warning
        opened = calendar.session_open(day).to_pydatetime().astimezone(timezone.utc)
        closed = calendar.session_close(day).to_pydatetime().astimezone(timezone.utc)
        # Comparing the actual close is more robust than membership against a
        # pandas DatetimeIndex (``date`` and ``Timestamp`` do not compare as
        # equal on every supported pandas version).
        early = closed.astimezone(NEW_YORK).timetz().replace(tzinfo=None) < time(16, 0)
        return True, opened, closed, early, source, warning

    is_session = day.weekday() < 5 and not is_us_equity_holiday(day)
    if not is_session:
        return False, None, None, False, source, warning
    early = _is_fallback_early_close(day)
    return (
        True,
        _at_local(day, time(9, 30)),
        _at_local(day, time(13 if early else 16, 0)),
        early,
        source,
        warning,
    )


def _next_session_open(day: date, *, include_day: bool) -> datetime:
    calendar, _, _ = _xnys_calendar()
    if calendar is not None:
        direction = "next" if include_day else "none"
        try:
            label = calendar.date_to_session(day, direction=direction)
        except ValueError:
            label = calendar.date_to_session(day + timedelta(days=1), direction="next")
        if not include_day and label.date() == day:
            label = calendar.next_session(label)
        return calendar.session_open(label).to_pydatetime().astimezone(timezone.utc)

    start = day if include_day else day + timedelta(days=1)
    return _at_local(_next_fallback_session(start), time(9, 30))


def market_clock_status(asof_utc: datetime, *, replay: bool = False) -> MarketClockStatus:
    """Return auditable XNYS session state and the next operator transition."""
    now = utc_datetime(asof_utc)
    if replay:
        return MarketClockStatus(
            asof_utc=now,
            exchange=EXCHANGE,
            market_session=MarketSession.REPLAY,
            is_trading_day=False,
            is_early_close=False,
            regular_open_utc=None,
            regular_close_utc=None,
            next_regular_open_utc=None,
            next_transition_utc=None,
            next_transition=None,
            calendar_source="replay",
        )

    local = now.astimezone(NEW_YORK)
    day = local.date()
    is_session, opened, closed, early, source, warning = _calendar_day(day)
    premarket_open = _at_local(day, time(4, 0)) if is_session else None
    after_hours_close = _at_local(day, time(20, 0)) if is_session else None

    if not is_session:
        next_open = _next_session_open(day, include_day=True)
        next_transition = next_open.astimezone(NEW_YORK).replace(
            hour=4, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)
        session = MarketSession.CLOSED
        transition_name = "premarket_opens"
    elif premarket_open is not None and now < premarket_open:
        next_open = opened
        next_transition = premarket_open
        session = MarketSession.CLOSED
        transition_name = "premarket_opens"
    elif opened is not None and now < opened:
        next_open = opened
        next_transition = opened
        session = MarketSession.PREMARKET
        transition_name = "regular_opens"
    elif closed is not None and now < closed:
        next_open = _next_session_open(day, include_day=False)
        next_transition = closed
        session = MarketSession.REGULAR
        transition_name = "regular_closes"
    elif after_hours_close is not None and now < after_hours_close:
        next_open = _next_session_open(day, include_day=False)
        next_transition = after_hours_close
        session = MarketSession.AFTER_HOURS
        transition_name = "after_hours_closes"
    else:
        next_open = _next_session_open(day, include_day=False)
        next_transition = next_open.astimezone(NEW_YORK).replace(
            hour=4, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)
        session = MarketSession.CLOSED
        transition_name = "premarket_opens"

    return MarketClockStatus(
        asof_utc=now,
        exchange=EXCHANGE,
        market_session=session,
        is_trading_day=is_session,
        is_early_close=early,
        regular_open_utc=opened,
        regular_close_utc=closed,
        next_regular_open_utc=next_open,
        next_transition_utc=next_transition,
        next_transition=transition_name,
        calendar_source=source,
        warning=warning,
    )


def classify_session(asof_utc: datetime, *, replay: bool = False) -> MarketSession:
    return market_clock_status(asof_utc, replay=replay).market_session


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
