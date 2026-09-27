"""Scheduler-safe wrapper around ``daily_plays today``.  It installs no schedule."""
from __future__ import annotations

import argparse
from pathlib import Path

from edge.daily_plays.cli import main
from edge.daily_plays.schedule import ScheduleAlreadyRunning, run_locked


def main_wrapper(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run daily plays once under an atomic scheduler lock")
    parser.add_argument("--account", required=True, type=float)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    command = ["today", "--account", str(args.account), "--output-root", str(args.output_root)]
    if args.config: command += ["--config", str(args.config)]
    try:
        return run_locked(lambda: main(command), output_root=args.output_root)
    except ScheduleAlreadyRunning:
        return 0  # another invocation owns the same idempotent ledger window


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_wrapper())
