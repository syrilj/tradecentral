from datetime import datetime, timezone

import edge.daily_plays.clock as clock
from edge.daily_plays.clock import RunContext, classify_session, market_clock_status
from edge.daily_plays.contracts import MarketSession


def test_new_york_regular_session_and_holiday_boundary():
    assert classify_session(datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)) is MarketSession.REGULAR
    # Independence Day is observed Friday July 3 in 2026.
    assert classify_session(datetime(2026, 7, 3, 14, 0, tzinfo=timezone.utc)) is MarketSession.CLOSED


def test_run_id_is_deterministic_for_frozen_inputs():
    context = RunContext.create(asof_utc=datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc))
    assert context.run_id(account=1000, config_hash="abc") == context.run_id(account=1000, config_hash="abc")


def test_early_close_switches_to_after_hours_at_exchange_close():
    before = market_clock_status(datetime(2026, 11, 27, 17, 59, tzinfo=timezone.utc))
    after = market_clock_status(datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc))

    assert before.is_early_close is True
    assert before.market_session is MarketSession.REGULAR
    assert before.regular_close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
    assert before.next_transition == "regular_closes"
    assert after.market_session is MarketSession.AFTER_HOURS
    assert after.next_transition == "after_hours_closes"


def test_closed_day_points_to_next_premarket_and_regular_open():
    status = market_clock_status(datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc))

    assert status.market_session is MarketSession.CLOSED
    assert status.next_transition == "premarket_opens"
    assert status.next_transition_utc == datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
    assert status.next_regular_open_utc == datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)


def test_clock_payload_names_calendar_source_and_uses_utc_strings():
    payload = market_clock_status(
        datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
    ).to_dict()

    assert payload["exchange"] == "XNYS"
    assert payload["market_session"] == "regular"
    assert payload["calendar_source"].startswith(("exchange_calendars:", "builtin_fallback"))
    assert payload["regular_close_utc"].endswith("Z")


def test_dependency_free_fallback_is_conservative_on_early_close(monkeypatch):
    monkeypatch.setattr(
        clock,
        "_xnys_calendar",
        lambda: (None, "builtin_fallback", "calendar dependency unavailable"),
    )

    status = clock.market_clock_status(
        datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)
    )

    assert status.calendar_source == "builtin_fallback"
    assert status.warning == "calendar dependency unavailable"
    assert status.is_early_close is True
    assert status.market_session is MarketSession.AFTER_HOURS


def test_fallback_observes_next_year_new_year_on_prior_december(monkeypatch):
    monkeypatch.setattr(
        clock,
        "_xnys_calendar",
        lambda: (None, "builtin_fallback", "calendar dependency unavailable"),
    )

    assert clock.classify_session(
        datetime(2021, 12, 31, 16, 0, tzinfo=timezone.utc)
    ) is MarketSession.CLOSED
