"""FOMC macro calendar phases for the vanna tab's event-context banner."""
from __future__ import annotations

from datetime import date

from edge.daily_plays.macro_calendar import FOMC_DATES, event_context


def test_pre_fomc_day_before_meeting():
    ctx = event_context(date(2026, 9, 14))
    assert ctx["phase"] == "pre_fomc"
    assert ctx["next_fomc"] == "2026-09-15"  # meeting START (day 1)
    assert ctx["days_to_fomc"] == 1
    assert ctx["is_fomc_day"] is False
    assert ctx["is_fomc_week"] is True  # Sep 15-16 sit in the same Mon-Sun week
    assert ctx["last_fomc"] == "2026-07-29"
    assert ctx["days_since_fomc"] == 47
    assert ctx["note"]


def test_fomc_day_flags_on_both_meeting_days():
    for day in (date(2026, 9, 15), date(2026, 9, 16)):
        ctx = event_context(day)
        assert ctx["is_fomc_day"] is True
        assert ctx["phase"] == "fomc_today"
        assert ctx["days_to_fomc"] == 0
        assert ctx["note"]
    assert date(2026, 9, 15) in FOMC_DATES
    assert date(2026, 9, 16) in FOMC_DATES


def test_post_fomc_day():
    ctx = event_context(date(2026, 9, 17))
    assert ctx["phase"] == "post_fomc"
    assert ctx["days_since_fomc"] == 1
    assert ctx["is_fomc_day"] is False
    assert ctx["is_fomc_week"] is True


def test_baseline_mid_cycle():
    ctx = event_context(date(2026, 8, 10))
    assert ctx["phase"] == "baseline"
    assert ctx["is_fomc_day"] is False
    assert ctx["is_fomc_week"] is False
    assert ctx["next_fomc"] == "2026-09-15"
    assert ctx["days_to_fomc"] == 36
    assert ctx["last_fomc"] == "2026-07-29"
    assert ctx["days_since_fomc"] == 12
    assert ctx["note"]


def test_calendar_shape_eight_two_day_meetings_per_year_2024_to_2027():
    assert len(FOMC_DATES) == 8 * 2 * 4
    assert min(FOMC_DATES) == date(2024, 1, 30)
    assert max(FOMC_DATES) == date(2027, 12, 8)


def test_outside_curated_window_returns_none_not_a_guess():
    ctx = event_context(date(2028, 6, 1))
    assert ctx["next_fomc"] is None
    assert ctx["days_to_fomc"] is None
    assert ctx["phase"] == "baseline"
    assert ctx["last_fomc"] == "2027-12-08"
