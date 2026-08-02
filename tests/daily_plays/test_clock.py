from datetime import datetime, timezone

from edge.daily_plays.clock import RunContext, classify_session
from edge.daily_plays.contracts import MarketSession


def test_new_york_regular_session_and_holiday_boundary():
    assert classify_session(datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)) is MarketSession.REGULAR
    # Independence Day is observed Friday July 3 in 2026.
    assert classify_session(datetime(2026, 7, 3, 14, 0, tzinfo=timezone.utc)) is MarketSession.CLOSED


def test_run_id_is_deterministic_for_frozen_inputs():
    context = RunContext.create(asof_utc=datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc))
    assert context.run_id(account=1000, config_hash="abc") == context.run_id(account=1000, config_hash="abc")
