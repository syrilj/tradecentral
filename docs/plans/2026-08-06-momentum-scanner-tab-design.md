# Momentum scanner tab design

## Goal

Add a new dashboard tab that runs the "Five Pillars" pre-scan from Ross
Cameron's small-cap momentum strategy (RVOL, price, float, gap) as a nightly
EOD watchlist, against a broad small-cap universe this repo does not
currently fetch. This is the pre-market research step a trader would do
before the bell — a ranked candidate list, not a live scanner.

## Non-goals

This ships Phase 1 (the Pre-Scanner) only. Explicitly out of scope, and
called out in the tab's own UI copy so it is never mistaken for more:

- **Entry logic** (VWAP / 9-EMA trend, 50% retracement, first 1-min candle
  trigger, stop placement). Requires intraday 1-minute bars, which do not
  exist for this universe and are not part of this design.
- **Exit logic** (L2 order-book walls, hidden sellers, tape reading).
  Requires a live Level 2 feed. Nothing in this codebase provides one, and
  none of the earlier "L2" or "order book" search hits in this repo turned
  out to be real matches (L2 regularization, a comment noting Fintel is
  polled *not* streamed).
- **Time-of-day (7-10am) gating.** Meaningless for once-nightly EOD data.
  Replaced with an explicit "as of [date] close" label.
- **Backtesting the strategy historically.** The new universe data is a
  bounded rolling window (see below), not full history — it serves the live
  nightly scan only.

## Chosen approach

### Data pipeline

Two new fetch scripts, wired into `update_all_data.sh` as new steps 6-7
alongside the existing overnight batch:

- **`tools/fetch_smallcap_universe.py`** — downloads the NASDAQ Trader
  symbol directory (`nasdaqlisted.txt` + `otherlisted.txt`; public, no auth,
  ~8-11k NASDAQ/NYSE/AMEX tickers), bulk-fetches daily OHLCV via yfinance,
  writes `data/1d_smallcap/*.parquet` — schema matches `data/1d_wide`
  (`DatetimeIndex` + `open/high/low/close/volume`). Keeps a bounded
  **~70-trading-day rolling window** per symbol rather than full history:
  this is a scanner input (needs a 50-day volume average plus the last
  couple of sessions), not a backtest input, and bounding it keeps nightly
  runtime and storage flat regardless of universe size. Mirrors
  `fetch_universe_wide.py`'s conventions — `--force`, `--limit` for smoke
  tests, a manifest JSON that reports real per-symbol failures honestly,
  never silently drops them.
- **`tools/fetch_float_data.py`** — for symbols whose last close is at or
  under a cheap pre-filter ceiling (~$25), fetches float / shares-outstanding
  via yfinance's `.info`. Writes `data/float_data/float.csv`
  (`symbol, float_shares, shares_outstanding, as_of_date`). Runs daily, same
  cadence as the universe fetch (no separate weekly job — simplicity was
  chosen over the marginal cost savings of a longer cadence). A symbol with
  no resolvable float is stored with `float_shares = null` — never silently
  coerced to pass or fail the float pillar. This mirrors the rule already
  established in `tools/data_sources.py` for the FINRA short-vol loader:
  return real data, or flag it as missing; never let a lookup failure
  masquerade as a value.

Universe fetch failures follow the existing `update_all_data.sh` pattern
(`|| true` — a bad night here does not block the qlib/FINRA steps that
already run after it). A stale or partial universe is surfaced to the user
via pipeline metadata (see Backend, below), not hidden.

### Pillar computation (nightly, from the most recent close)

| Pillar | Formula | Qualifies |
|---|---|---|
| RVOL | `last_session_volume / mean(trailing 50 sessions, excluding last)` | > 5x |
| Price | last close | $2-$20 |
| Gap | `(last_open - prior_close) / prior_close` | ≥ 2% (10-30% flagged "sweet spot") |
| Float | from `float.csv` | < 20M shares (flagged "optimal" under 3M); unknown float shown as "n/a" |

Day-change % (`last_close` vs `prior_close`) is computed and shown alongside
gap % as informational context, since the source material uses "gap" and
"gain" somewhat interchangeably; gap (open-based) is the filtering
definition used for the pillar itself.

The default candidate list is gated on the three **always-computable**
pillars — price, gap, RVOL. Float renders as a badge (qualifies / doesn't /
unknown) next to each row rather than as a hard filter, because a meaningful
share of the universe will have unresolvable float via yfinance, and hiding
those rows would silently discard otherwise-valid candidates.

### Backend

`get_momentum_scan()` in `tools/api_server.py` — a TTL-cached wrapper
following the same pattern as the existing `get_dashboard_data()`. Reads
`data/1d_smallcap/` and `float.csv`, computes and ranks candidates by RVOL
descending. New route returns the ranked list plus pipeline metadata:
universe size (actual vs. expected, so a partial fetch is visible), last
refresh timestamp, and float coverage %.

### Frontend

- `MomentumCandidate` type + `api.momentumScan()` in `dashboard/src/api.ts`,
  following the existing typed-client pattern (`req<T>()`, thrown
  `ApiError`).
- `dashboard/src/views/MomentumView.vue` — `Panel.vue` framing,
  `useResource` polling at a long interval (5 min; the underlying data only
  changes once a night, so this exists to pick up a server restart, not to
  simulate a live feed). Ranked table: symbol, price, gap %, day chg %,
  RVOL, float badge, pillars-met count. A header banner states plainly: "As
  of [date] close · pre-market watchlist, not a live feed."
- New router entry (`/momentum`, index `14`) + nav item in `App.vue`,
  following the existing 13-tab pattern exactly (same nav array shape,
  same digit-shortcut exclusion rule already documented in `App.vue` for
  tabs past 9).

## Failure behavior and tests

- **Universe fetch fails or is partial** (NASDAQ Trader unreachable,
  yfinance rate-limited mid-run): pipeline continues (`|| true`), scan runs
  on whatever landed, and the UI shows the real universe size against the
  expected count from the manifest rather than pretending coverage was
  complete.
- **Float lookup fails for a symbol:** stored and rendered as unknown
  (`n/a`), never coerced to pass or fail.
- **Data stale** (pipeline didn't run, or failed entirely overnight): the
  tab reuses the existing footer stale-indicator convention already in
  `App.vue`/`api.ts` (`age()` + the `ok`/`stale` class pair) rather than
  inventing a new one.
- **Zero candidates on a given night** (plausible — this is a real filter,
  not a curated list): rendered as an honest empty state ("0 candidates met
  all criteria as of [date]"), not an error.
- **Tests** (`tests/test_momentum_scan.py`, following the existing flat
  `tests/test_*.py` convention): pillar math (RVOL, gap %, band checks)
  against synthetic OHLCV frames, no network; the float-null-never-silently-
  resolves-to-pass-or-fail rule; a manifest/partial-universe test asserting
  a failed symbol is reported, not dropped.

This feature adds a new read-only research surface. It does not change
signals, model gates, risk limits, promotion state, broker connectivity, or
any existing tab's data.
