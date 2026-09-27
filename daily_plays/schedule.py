"""Locking primitives for an external cron/launchd scheduler; installs nothing."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Callable

from .ledger import DEFAULT_OUTPUT_ROOT


class ScheduleAlreadyRunning(RuntimeError): pass


def run_locked(action: Callable[[], Any], *, output_root: str | Path | None = None) -> Any:
    """Run one invocation under an atomic lock, removing it even on failure."""
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".daily_plays_scheduler.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ScheduleAlreadyRunning("daily plays scheduled invocation already running") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        return action()
    finally:
        os.close(fd)
        try: lock.unlink()
        except FileNotFoundError: pass
