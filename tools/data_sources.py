#!/usr/bin/env python3
"""Shared data-source loaders for research tools.

Extracted per plan Issue 3A / P1-3. `build_pead_factor_hybrid.py` and
`build_pead_catalyst_model.py` each carried their own copy of
`load_finra_short_vol()`. The hybrid tool's copy pointed at
`edge/data/finra_short_vol.csv`, a path that has never existed — the fetcher
writes `edge/data/finra_shortvol/`. The miss was swallowed by
`except Exception: pass` and the function returned `None`, so the caller's
`short_pressure` feature silently collapsed to a constant multiplier (1.0)
while `GATE_PEAD_HYBRID_RESULT.md` went on being generated as if the feature
were included. Full incident write-up: `edge/docs/LOOKAHEAD_CORRECTION.md`.

The rule enforced here, for every loader in this module: return real data, or
raise. Never return `None` to mean "couldn't find it" — that is precisely the
value that let the bug above go undetected for as long as it did. A caller
that wants to run without a data source must catch the raise explicitly at
its own call site and say so out loud in whatever artifact or doc it
produces. See `main()` in both PEAD tools, which now record
`short_pressure_active` either way instead of only when things go well.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# Where the FINRA short-volume fetcher is expected to land a processed panel,
# plus the legacy single-file path kept only because an operator could have
# dropped a file there by hand. `_finra_csv_candidates` below is the
# deterministic precedence between them.
_FINRA_DIR = ROOT / "edge" / "data" / "finra_shortvol"
_FINRA_CANONICAL_CSV = _FINRA_DIR / "short_vol.csv"
_FINRA_LEGACY_CSV = ROOT / "edge" / "data" / "finra_short_vol.csv"

_FINRA_REQUIRED_COLUMNS = ("date", "symbol", "short_ratio")


def _finra_csv_candidates() -> list[Path]:
    """Deterministic search order for a processed FINRA short-ratio CSV.

    1. The canonical path the fetcher is meant to populate:
       ``edge/data/finra_shortvol/short_vol.csv``.
    2. Any other ``*.csv`` sitting directly in ``edge/data/finra_shortvol/``,
       sorted by name so the order never depends on directory-listing order.
    3. The legacy flat-file path ``edge/data/finra_short_vol.csv``, tried
       last: it is deprecated, and in this repo has never actually held data
       (see ``edge/docs/LOOKAHEAD_CORRECTION.md``).

    The canonical file wins if both it and the legacy file exist — that is
    the "deterministic precedence" the new directory takes over the legacy
    one. A path that would appear twice (the canonical file also matching
    its own glob) is only tried once.
    """
    ordered: list[Path] = [_FINRA_CANONICAL_CSV]
    if _FINRA_DIR.is_dir():
        ordered.extend(sorted(_FINRA_DIR.glob("*.csv")))
    ordered.append(_FINRA_LEGACY_CSV)

    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in ordered:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def load_finra_short_vol() -> pd.Series:
    """Load the FINRA daily short-ratio panel, indexed by ``(date, symbol)``.

    Raises ``FileNotFoundError`` — never returns ``None`` — when no candidate
    resolves to a usable CSV. See the module docstring for why a silent
    ``None`` return is exactly the bug this function exists to make
    impossible: `short_pressure` collapsing to a constant with no run-time
    signal that anything was wrong.

    A candidate whose file exists but is missing a required column is
    reported and skipped, not silently treated as a hit; a candidate that
    exists and reads cleanly is used immediately without inspecting later
    candidates.

    Returns
    -------
    pd.Series
        ``short_ratio`` values indexed by a ``(date, symbol)`` MultiIndex.
    """
    attempts: list[str] = []
    for finra_file in _finra_csv_candidates():
        if not finra_file.exists():
            attempts.append(f"  - {finra_file}: not found")
            continue
        df = pd.read_csv(finra_file)
        missing = [c for c in _FINRA_REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            attempts.append(f"  - {finra_file}: missing columns {missing}")
            continue
        df["date"] = pd.to_datetime(df["date"])
        print(f"  FINRA short ratio loaded from {finra_file} ({len(df):,} rows)")
        return df.set_index(["date", "symbol"])["short_ratio"]

    # Report the raw mirror separately from the CSV search above: it is real
    # data on disk, but it is a directory of daily gzip files (one FINRA
    # CNMSshvol dump per session), not a (date, symbol, short_ratio) panel.
    # This loader only reads the processed form; aggregating the raw mirror
    # is a separate, not-yet-built step, and pretending otherwise here would
    # recreate the same "quietly not what the docs think it is" failure mode.
    raw_dir = _FINRA_DIR / "raw"
    raw_note = ""
    if raw_dir.is_dir():
        n_raw = sum(1 for _ in raw_dir.glob("*.txt.gz"))
        if n_raw:
            raw_note = (
                f"\n  Note: {n_raw} raw daily FINRA mirror files exist at {raw_dir} "
                "but have not been aggregated into a (date, symbol, short_ratio) "
                "panel yet — short_pressure cannot be computed from raw files "
                "directly; this loader only reads a processed CSV."
            )

    raise FileNotFoundError(
        "FINRA short-volume data NOT FOUND — short_pressure cannot be computed. "
        "Tried, in order:\n" + "\n".join(attempts) +
        f"\n  Expected columns: {list(_FINRA_REQUIRED_COLUMNS)}."
        + raw_note
    )
