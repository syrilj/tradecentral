# Market session guard design

## Goal

Give every live decision-support surface one auditable XNYS session clock. The
clock must respect full holidays, DST, and scheduled early closes; expose its
calendar source; and never submit or authorize an order.

## Chosen approach

Use `exchange_calendars` for authoritative regular-session boundaries. Keep a
small conservative fallback for environments where the optional operational
dependency is absent, and label that fallback in the API. The existing
`daily_plays.clock` module remains the only session classifier so pipeline and
dashboard semantics cannot drift.

The backend exposes `/api/market-clock` with the current session, today's
regular open/close, early-close status, the next transition, and the next
regular open. The Vue shell polls this lightweight endpoint and derives a
second-by-second local countdown from the returned absolute UTC timestamp.
The backend remains the authority; the browser only formats elapsed time.

## Failure behavior and tests

If the library cannot import, the system uses explicit recurring US equity
holiday and early-close rules and returns a visible warning plus
`calendar_source=builtin_fallback`. Unknown data is never represented as an
open market. Tests cover a normal session, a full holiday, the 2026
post-Thanksgiving early close boundary, a weekend-to-Monday transition, UTC
serialization, and the pre-existing deterministic run ID contract.

This feature changes operational timing only. It does not change signals,
model gates, risk limits, promotion state, or broker connectivity.
