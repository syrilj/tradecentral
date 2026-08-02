# xs_v3 live paper-trade signal scheduling

`edge/tools/xs_v3_live_signals.py` is the forward paper-trade signal logger
for the frozen xs_v3 configuration (see `edge/runs/xs_v3/DECISION_RECORD.md`,
priority #1: *"Forward paper-trade the frozen configuration. Costs time, not
compute. It is the only remaining source of untainted evidence."*). Until
this runs on a schedule, no forward evidence accumulates — it must be run
once per trading day, after `edge/data/1d_wide/` has that day's bar.

## What it does

- Reads `edge/data/1d_wide/*.parquet`, scores the FROZEN configuration (see
  the `CONFIG` dict in the script — do not edit it without a fresh,
  pre-registered holdout evaluation), and appends one day's rebalance to
  `edge/runs/xs_v3/live/signal_log.parquet` (plus a per-day
  `signals_<date>.csv` and the current `positions.json`).
- Writes ONLY inside `edge/runs/xs_v3/live/`. No network calls, no order
  placement — see the script's own module docstring for the exact safety
  contract.
- Idempotent per as-of date: a second run for a date already present in
  `signal_log.parquet` is a documented no-op (`already_processed()`).

## Running it once

```bash
python3 -m edge.tools.xs_v3_live_signals                    # today's signals (or --asof YYYY-MM-DD)
python3 -m edge.tools.xs_v3_live_signals --evaluate          # realized paper P&L to date
```

## Scheduling

This follows the exact same pattern as `edge/tools/daily_plays_schedule.py`
(`edge/daily_plays/schedule.py`'s `run_locked` — no new locking mechanism was
introduced): a lock-safe wrapper that the repository does not itself install
into cron or launchd.

```bash
python3 -m edge.tools.xs_v3_live_signals_schedule
python3 -m edge.tools.xs_v3_live_signals_schedule --evaluate
```

The wrapper takes an atomic lock scoped to `edge/runs/xs_v3/live/` for the
duration of one invocation (a concurrent invocation sees
`ScheduleAlreadyRunning` and exits 0, a no-op) and is additionally protected
by the underlying script's own idempotence guard, so a duplicate or
overlapping trigger cannot double-log a day or corrupt `positions.json`.

### cron (run after the trading day's bar lands, e.g. 21:00 local time)

```cron
0 21 * * 1-5 cd /path/to/alltrading && /usr/bin/python3 -m edge.tools.xs_v3_live_signals_schedule >> edge/runs/xs_v3/live/cron.log 2>&1
```

### launchd (macOS)

Create `~/Library/LaunchAgents/com.alltrading.xs_v3_live_signals.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alltrading.xs_v3_live_signals</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>edge.tools.xs_v3_live_signals_schedule</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/alltrading</string>
  <key>StandardOutPath</key><string>edge/runs/xs_v3/live/launchd.log</string>
  <key>StandardErrorPath</key><string>edge/runs/xs_v3/live/launchd.err</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>21</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
</dict>
</plist>
```

Then `launchctl load ~/Library/LaunchAgents/com.alltrading.xs_v3_live_signals.plist`.

Neither cron nor launchd is installed by this change — installing a schedule
is an operator action outside this repository, exactly as
`DAILY_PLAYS_RUNBOOK.md` documents for `daily_plays_schedule.py`. Replace
`/path/to/alltrading` with the real checkout path before use.

## Verifying the schedule works

```bash
python3 -m edge.tools.xs_v3_live_signals_schedule
ls edge/runs/xs_v3/live/                    # positions.json, signal_log.parquet, signals_<date>.csv
python3 -m edge.tools.xs_v3_live_signals_schedule --evaluate
cat edge/runs/xs_v3/live/evaluate_report.json
```
