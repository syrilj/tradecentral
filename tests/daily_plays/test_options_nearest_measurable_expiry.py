"""`expiry=nearest` must land on an expiry that can actually be measured.

GEX, the gamma walls, and the squeeze board are all open-interest weighted. LSE's
live chain carries no OI, so it is joined against a delayed yfinance snapshot by
exact OCC symbol -- and the two feeds do not always list the same expiries. When
LSE quotes a nearer weekly the snapshot never carried, the nearest slice has zero
OI across every contract, and scoring it renders a fake-flat "quiet" structure
instead of the real one an expiry out.

Observed on 2026-08-22: LSE listed XLE/AVGO 2026-08-24 while the snapshot started
at 2026-08-28, and the board reported those names unmeasured.
"""
from __future__ import annotations

from datetime import datetime, timezone

from edge.daily_plays.options_intelligence import OptionsFilters, _filter_chain


ASOF = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)


def _contract(expiry: str, right: str, strike: float, oi: int) -> dict:
    return {
        "expiry": expiry,
        "right": right,
        "strike": strike,
        "open_interest": oi,
        "volume": 25,
        "bid": 1.00,
        "ask": 1.05,
        "impliedVolatility": 0.30,
        "occ_symbol": f"XLE{expiry.replace('-', '')[2:]}{right}{int(strike * 1000):08d}",
    }


def _permissive(expiry: str = "nearest") -> OptionsFilters:
    """The board's filter set: nothing is dropped for thin OI."""
    return OptionsFilters(
        expiry=expiry,
        min_premium=0.0,
        min_volume=0,
        min_open_interest=0,
        max_spread_pct=0.75,
        min_dte=0,
        max_dte=60,
    )


def test_nearest_skips_an_expiry_the_oi_reference_never_covered():
    rows = [
        _contract("2026-08-24", "C", 63.0, 0),
        _contract("2026-08-24", "P", 63.0, 0),
        _contract("2026-08-28", "C", 63.0, 4100),
        _contract("2026-08-28", "P", 63.0, 3800),
    ]

    included, _rejected, context = _filter_chain(
        rows, asof=ASOF, spot=63.5, filters=_permissive()
    )

    assert context["selected_expiry"] == "2026-08-28"
    assert context["skipped_unmeasurable_expiries"] == ["2026-08-24"]
    assert {row["expiry"].isoformat() for row in included} == {"2026-08-28"}
    assert sum(row["open_interest"] for row in included) == 7900


def test_nearest_is_untouched_when_the_front_expiry_carries_oi():
    rows = [
        _contract("2026-08-24", "C", 63.0, 900),
        _contract("2026-08-28", "C", 63.0, 4100),
    ]

    _included, _rejected, context = _filter_chain(
        rows, asof=ASOF, spot=63.5, filters=_permissive()
    )

    assert context["selected_expiry"] == "2026-08-24"
    assert context["skipped_unmeasurable_expiries"] == []


def test_no_expiry_has_oi_still_selects_the_front_and_stays_unmeasured():
    """Skipping must never empty the chain -- unmeasured is the honest readout."""
    rows = [
        _contract("2026-08-24", "C", 63.0, 0),
        _contract("2026-08-28", "C", 63.0, 0),
    ]

    included, _rejected, context = _filter_chain(
        rows, asof=ASOF, spot=63.5, filters=_permissive()
    )

    assert context["selected_expiry"] == "2026-08-24"
    assert context["skipped_unmeasurable_expiries"] == []
    assert included, "the front expiry must still be scored, not dropped"
    assert sum(row["open_interest"] for row in included) == 0


def test_available_expiries_report_open_interest_per_expiry():
    rows = [
        _contract("2026-08-24", "C", 63.0, 0),
        _contract("2026-08-28", "C", 63.0, 4100),
        _contract("2026-09-04", "C", 63.0, 250),
    ]

    _included, _rejected, context = _filter_chain(
        rows, asof=ASOF, spot=63.5, filters=_permissive()
    )

    by_expiry = {row["expiry"]: row["open_interest"] for row in context["available_expiries"]}
    assert by_expiry == {"2026-08-24": 0, "2026-08-28": 4100, "2026-09-04": 250}


def test_an_explicit_expiry_is_honoured_even_when_it_has_no_oi():
    """Only `nearest` auto-advances; a hand-picked expiry is the operator's call."""
    rows = [
        _contract("2026-08-24", "C", 63.0, 0),
        _contract("2026-08-28", "C", 63.0, 4100),
    ]
    included, _rejected, context = _filter_chain(
        rows, asof=ASOF, spot=63.5, filters=_permissive("2026-08-24")
    )

    assert context["selected_expiry"] == "2026-08-24"
    assert {row["expiry"].isoformat() for row in included} == {"2026-08-24"}
