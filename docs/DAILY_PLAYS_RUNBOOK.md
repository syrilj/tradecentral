# Daily plays operator runbook

This is a decision-support and shadow-trading command. It never submits, routes, or places an order.

## Run

From the workspace root, use:

```bash
python3 -m edge.daily_plays today --account 1000
python3 -m edge.daily_plays today --account 1000 --json
```

The command securely discovers `LSE_API_KEY` from the existing `TradingAlgoWork/.env` or `TradingWork/.env` files when the key is not already exported; an explicit shell value always wins. It does not print the key or place it in command history. The module entry point automatically re-executes through `TradingAlgoWork/.venv`, which contains the supported LSE SDK. Set `DAILY_PLAYS_DISABLE_DOTENV=1` or `DAILY_PLAYS_DISABLE_PROJECT_RUNTIME=1` only for controlled tests.

With `LSE_API_KEY`, the default path first runs the existing sector-money-flow heatmap on fresh LSE daily bars. Sector ETFs absent from the LSE catalog are batch-filled with Yahoo solely for discovery and labeled `lse_live_daily+yfinance_missing`; that proxy data can route a scan but can never validate execution. The router balances leading and lagging sector/theme sleeves into a bounded flow target list, then batches current LSE option-print activity across those names. That tape is direction-neutral because LSE does not report aggressor side; it can prioritize model work but cannot turn a put print bearish or a call print bullish. The command then evaluates the promoted model domain with regular-session, 09:30-aligned hourly bars built from LSE 30-minute candles and scores routed names with the frozen broad-market directional challenger for a separately labeled research board. Live option chains are requested only after a promoted candidate has an entry-eligible, fixed-horizon underlying-direction probability, a frozen threshold, and a promotion-authorized artifact. Sector flow and option activity choose where to look; neither modifies confidence or promotion eligibility.

The flow router defaults to 25 targets across the wider configured universe; set `DAILY_PLAYS_DISCOVERY_LIMIT` to a value from 1–50 for a controlled operational test. The full options routing contract (UI routes, API handlers, unsigned-tape rules, unusual/sweep formulas) is `docs/OPTIONS_ROUTE_NOTE.md`. The executable adapter verifies and follows the active deployment manifest, currently `v72_dual_sleeve`, on its frozen seven-symbol winner bag. Its confidence remains ordinal diagnostic evidence: it is not mislabeled as a 5/10/20-day directional probability and cannot by itself authorize an option ticket. The separate daily directional challenger covers the configured broad universe and predicts fixed 5/10/20-session underlying direction. Its current authoritative artifact failed the development gate, its terminal holdout remains sealed, and it explicitly forbids broker use and option-shadow collection. Depending on adapter context, its rows are either omitted with a `FAIL_DEVELOPMENT` reason or confined to `Research board (sealed holdout — not plays)`. A live `ENTER` requires a promoted, independently validated fixed-horizon calibration; none is silently inferred from the heatmap, Kronos, flow, v72, or the sealed research board.

The present LSE options chain is reference/activity data, not an executable
quote source: live samples expose contract identity, last trade, volume, IV,
and Greeks, but not bid/ask NBBO or open interest. The adapter reports this
field coverage and keeps quote time, multiplier, adjustment status, and
underlying quote time missing unless explicitly supplied. A live `ENTER`
therefore also requires a connected provider that supplies exact current
NBBO/OI and contract metadata; LSE last-trade timestamps are never relabeled as
quote timestamps.

For a controlled test output location, add `--output-root /path/to/output`. Do not point it at a directory containing secrets.

## Replay and checks

The offline replay suite has no network dependency:

```bash
python3 -m pytest edge/tests/daily_plays -q
```

An `ENTER` is possible only when a calibrated internal fixture/model, fresh primary-LSE quotes, exact listed OCC identity, liquidity/spread/DTE gates, and the account risk budget all pass. Ordinal confidence, delayed/degraded feeds, stale data, missing legs, and provider failures cannot enter.

The normal terminal output lists only `ENTER` tickets. If nothing passes every gate, it prints `NO_PLAY`, the actual scan funnel, and a causal reason summary; `WATCH`, `ABSTAIN`, and research-only rows are never presented as plays. The funnel distinguishes sector books, routed targets, promoted-model domain, successful model scans, directional setups, and option-chain requests/snapshots. JSON callers receive actionable tickets in `plays`, with non-actionable decisions separated into `watchlist`, `rejections`, and `research_board`.

## Audit artifacts

Each invocation writes the following under `edge/runs/daily_plays/<run_id>/` (or the configured output root):

- `manifest.json`
- `discovery.json`
- `flow_activity.json`
- `candidates.json`
- `option_snapshots.json`
- `plays.json`
- `decisions.json`
- `research_board.json`

`discovery.json` contains the full sector report, target symbols, and compact market map. `flow_activity.json` contains the unsigned live-tape coverage and ranking used only for routing. `plays.json` contains actionable `ENTER` tickets only. `decisions.json` contains the complete decision audit. `research_board.json` contains sealed-holdout context only and is deliberately excluded from the decision ledger. `shadow_decisions.jsonl` is appended once per `run_id`; rerunning the same deterministic context is idempotent. Artifacts omit credentials and authorization headers.

## Shadow realization, monitoring, and scheduling

Realize outcomes only after their configured horizon. The realization command uses an explicit, local outcome mapping during controlled/offline operation; it never calls a broker or submits an order:

```bash
python3 -m edge.daily_plays realize --output-root edge/runs/daily_plays --outcomes-json outcomes.json --json
python3 -m edge.daily_plays report --output-root edge/runs/daily_plays --spread-bps 10 --slippage-bps 5
```

The report includes reliability buckets, Brier/ECE for calibrated probabilities, state and abstention rates, net realized expectancy after the stated cost inputs, provider/model failure rates, and a fail-closed readiness checklist. Readiness requires at least 120 distinct market sessions, 200 completed shadow option trades, at least two recorded volatility/trend regimes, zero timestamp violations, and zero unresolved outcomes. Missing or invalid decision timestamps/outcomes are recorded as failures and are never inferred.

Promotion is a separate, pre-registered gate and still does not enable trading. It additionally requires positive ask-to-enter/bid-to-exit net expectancy with a positive 95% date-block-bootstrap lower bound, positive search-adjusted Sharpe using the recorded trial count, no symbol or regime contributing more than 50% of positive profit, simulated drawdown no worse than 8%, acceptable calibration, and explicit stable drift records. Any failed or missing record reports `FAIL_SHADOW_ONLY`; even `PASS_SHADOW_ONLY` never authorizes broker connectivity or live capital. A passing underlying-model gate only authorizes continued shadow collection, not option profitability or a live pilot.

For cron or launchd, install a schedule outside this repository that invokes the lock-safe wrapper (the repository does **not** install a schedule):

```bash
python3 -m edge.tools.daily_plays_schedule --account 1000 --output-root /secure/audit/daily_plays
```

The wrapper uses an atomic per-output-root lock and the underlying idempotent run ledger. Keep the audit location private and do not pass credentials in command arguments or write them to logs.

## Operator response

1. If `NO_PLAY` or `DEGRADED` appears, there is no play. Review the reason summary and, if needed, the separated decision audit; do not convert a rejected candidate into an order manually.
2. For `ENTER`, independently verify the displayed OCC contract(s), quote timestamp, maximum loss, and invalidation before any separate human decision. The command produces tickets only.
3. Keep the artifacts for outcome realization and reliability reporting. Do not claim production readiness before the frozen 120-session/200-completed-trade shadow gate and separate promotion gate pass.
