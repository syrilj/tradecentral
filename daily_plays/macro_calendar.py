"""Curated FOMC calendar + event-phase context for the vanna surface.

The vanna tab annotates dealer vanna exposure with where the current session
sits in the FOMC cycle, because event premium is the dominant mechanical
driver of short-dated implied vol — and the post-event IV crush is exactly
the delta migration vanna measures.

STATIC DATA WARNING: ``FOMC_MEETINGS`` below is hand-curated from the Fed's
published schedule and MUST be re-checked whenever the Federal Reserve
revises its calendar (https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).
Both days of each two-day meeting are included.
"""
from __future__ import annotations

from datetime import date, timedelta

# -- STATIC list: update when the Fed revises its meeting calendar ---------
# (year, month, day) for BOTH days of every scheduled two-day FOMC meeting.
FOMC_MEETINGS: tuple[tuple[int, int, int], ...] = (
    # 2024
    (2024, 1, 30), (2024, 1, 31),
    (2024, 3, 19), (2024, 3, 20),
    (2024, 4, 30), (2024, 5, 1),
    (2024, 6, 11), (2024, 6, 12),
    (2024, 7, 30), (2024, 7, 31),
    (2024, 9, 17), (2024, 9, 18),
    (2024, 11, 6), (2024, 11, 7),
    (2024, 12, 17), (2024, 12, 18),
    # 2025
    (2025, 1, 28), (2025, 1, 29),
    (2025, 3, 18), (2025, 3, 19),
    (2025, 5, 6), (2025, 5, 7),
    (2025, 6, 17), (2025, 6, 18),
    (2025, 7, 29), (2025, 7, 30),
    (2025, 9, 16), (2025, 9, 17),
    (2025, 10, 28), (2025, 10, 29),
    (2025, 12, 9), (2025, 12, 10),
    # 2026
    (2026, 1, 27), (2026, 1, 28),
    (2026, 3, 17), (2026, 3, 18),
    (2026, 4, 28), (2026, 4, 29),
    (2026, 6, 16), (2026, 6, 17),
    (2026, 7, 28), (2026, 7, 29),
    (2026, 9, 15), (2026, 9, 16),
    (2026, 10, 27), (2026, 10, 28),
    (2026, 12, 8), (2026, 12, 9),
    # 2027
    (2027, 1, 26), (2027, 1, 27),
    (2027, 3, 16), (2027, 3, 17),
    (2027, 4, 27), (2027, 4, 28),
    (2027, 6, 15), (2027, 6, 16),
    (2027, 7, 27), (2027, 7, 28),
    (2027, 9, 14), (2027, 9, 15),
    (2027, 10, 26), (2027, 10, 27),
    (2027, 12, 7), (2027, 12, 8),
)

FOMC_DATES: frozenset[date] = frozenset(
    date(year, month, day) for year, month, day in FOMC_MEETINGS
)

_PHASE_NOTES = {
    "fomc_today": (
        "FOMC today: hedging pins price toward high-|vanna| strikes into the "
        "2pm ET statement, then the event-premium collapse releases the move."
    ),
    "pre_fomc": (
        "Pre-FOMC: event premium inflates IV; when the crush unwinds, OTM call "
        "deltas lift — with net vanna > 0 dealers sell into the strength."
    ),
    "post_fomc": (
        "Post-FOMC: the IV crush has realized and vanna-driven delta migration "
        "is completing as event hedges unwind."
    ),
    "baseline": (
        "No FOMC within ±3 sessions: vanna flow is driven by ordinary vol "
        "drift, not event-premium build/unwind."
    ),
}


def event_context(asof: date) -> dict:
    """Where ``asof`` sits in the FOMC cycle, for vanna interpretation.

    Phase ladder: ``fomc_today`` (meeting day) > ``pre_fomc`` (1-3 days
    before) > ``post_fomc`` (0-3 days after) > ``baseline``. Dates outside the
    curated window yield ``None`` for the missing side rather than a guess.
    """
    next_fomc = min((d for d in FOMC_DATES if d >= asof), default=None)
    last_fomc = max((d for d in FOMC_DATES if d <= asof), default=None)
    days_to_fomc = (next_fomc - asof).days if next_fomc is not None else None
    days_since_fomc = (asof - last_fomc).days if last_fomc is not None else None
    is_fomc_day = asof in FOMC_DATES
    week_start = asof - timedelta(days=asof.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday
    is_fomc_week = any(week_start <= d <= week_end for d in FOMC_DATES)

    if is_fomc_day:
        phase = "fomc_today"
    elif days_to_fomc is not None and 0 < days_to_fomc <= 3:
        phase = "pre_fomc"
    elif days_since_fomc is not None and days_since_fomc <= 3:
        phase = "post_fomc"
    else:
        phase = "baseline"

    return {
        "next_fomc": next_fomc.isoformat() if next_fomc is not None else None,
        "days_to_fomc": days_to_fomc,
        "is_fomc_day": is_fomc_day,
        "is_fomc_week": is_fomc_week,
        "last_fomc": last_fomc.isoformat() if last_fomc is not None else None,
        "days_since_fomc": days_since_fomc,
        "phase": phase,
        "note": _PHASE_NOTES[phase],
    }
