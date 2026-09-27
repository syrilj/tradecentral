"""Module entry point for ``python -m edge.daily_plays``."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _reexec_project_runtime() -> None:
    """Use the repository runtime that contains the configured LSE SDK."""
    if os.environ.get("DAILY_PLAYS_DISABLE_PROJECT_RUNTIME", "").strip().lower() in {"1", "true", "yes"}:
        return
    workspace = Path(__file__).resolve().parents[2]
    target = workspace / "TradingAlgoWork" / ".venv" / "bin" / "python"
    if not target.is_file():
        return
    try:
        if Path(sys.executable).resolve() == target.resolve():
            return
    except OSError:
        return
    os.execv(str(target), [str(target), "-m", "edge.daily_plays", *sys.argv[1:]])


_reexec_project_runtime()

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
