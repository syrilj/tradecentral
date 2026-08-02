"""Scheduler-safe wrapper around ``xs_v3_live_signals``.  It installs no schedule.

``xs_v3_live_signals.py`` generates one trading day's forward paper-trade
signal for the frozen xs_v3 configuration (see
``edge/runs/xs_v3/DECISION_RECORD.md``, priority #1: "the only remaining
source of untainted evidence") and appends it under ``edge/runs/xs_v3/live/``.
Every day this does not run is a day of forward evidence that cannot be
bought back later.

This wrapper follows the exact same pattern as
``edge/tools/daily_plays_schedule.py``: it reuses
``edge.daily_plays.schedule.run_locked`` (an atomic, per-output-root lock
built for an external cron/launchd scheduler) so a slow or hung invocation
cannot overlap with the next scheduled one and corrupt
``signal_log.parquet``/``positions.json``. No new locking mechanism is
introduced. ``xs_v3_live_signals.generate_signals`` is independently
idempotent per as-of date (see ``already_processed`` there), so a missed
lock -- or a manual re-run on the same day -- is also safe on its own.

See ``edge/docs/XS_V3_LIVE_SCHEDULING.md`` for cron/launchd setup. This
repository does not install a schedule itself.

Usage:
    python3 -m edge.tools.xs_v3_live_signals_schedule
    python3 -m edge.tools.xs_v3_live_signals_schedule --asof 2026-07-15
    python3 -m edge.tools.xs_v3_live_signals_schedule --evaluate
"""
from __future__ import annotations

import argparse

from edge.daily_plays.schedule import ScheduleAlreadyRunning, run_locked
from edge.tools.xs_v3_live_signals import LIVE_DIR, main


def main_wrapper(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run xs_v3 live paper-trade signals once under an atomic scheduler lock",
    )
    parser.add_argument("--asof", type=str, default=None, help="YYYY-MM-DD; default = latest date in data")
    parser.add_argument("--retrain", action="store_true", help="Force retrain even if a fresh cache exists")
    parser.add_argument("--evaluate", action="store_true", help="Report realized paper P&L from signal_log.parquet")
    args = parser.parse_args(argv)

    command: list[str] = []
    if args.asof:
        command += ["--asof", args.asof]
    if args.retrain:
        command += ["--retrain"]
    if args.evaluate:
        command += ["--evaluate"]

    try:
        return run_locked(lambda: main(command), output_root=LIVE_DIR)
    except ScheduleAlreadyRunning:
        return 0  # another invocation owns the same idempotent as-of window


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_wrapper())
