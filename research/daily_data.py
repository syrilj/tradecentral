"""Point-in-time loading for the local daily OHLCV research universe."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DATA_DIR = EDGE_ROOT / "data" / "1d"
DEFAULT_PIT_INSTRUMENTS = EDGE_ROOT / "data" / "qlib_us_1d" / "instruments" / "pit30.txt"
_OHLCV = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class PitMembership:
    """Point-in-time membership spans for one symbol, from a dated-interval
    instruments file (the format `edge/tools/build_pit_universe.py` writes).

    ``spans`` is a tuple of ``(start, end)`` pairs, both inclusive, sorted
    ascending.  A symbol is a member on date ``d`` iff some span contains it.
    """

    symbol: str
    spans: tuple[tuple[pd.Timestamp, pd.Timestamp], ...]

    def contains(self, value: pd.Timestamp) -> bool:
        for start, end in self.spans:
            if start <= value <= end:
                return True
            if value < start:
                return False
        return False


def load_pit_membership(
    path: str | Path = DEFAULT_PIT_INSTRUMENTS,
) -> dict[str, PitMembership]:
    """Parse a qlib-style dated-interval instruments file into membership spans.

    Expected line format: ``SYMBOL<TAB>YYYY-MM-DD<TAB>YYYY-MM-DD``.  Blank
    lines and lines without exactly three fields are skipped; a malformed date
    raises rather than silently dropping the span.
    """
    memberships: dict[str, PitMembership] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        symbol, start_raw, end_raw = fields
        start = pd.Timestamp(start_raw)
        end = pd.Timestamp(end_raw)
        if start > end:
            raise ValueError(f"PIT instruments file has an inverted span: {line!r}")
        entry = memberships.setdefault(symbol, PitMembership(symbol, ()))
        memberships[symbol] = PitMembership(symbol, entry.spans + ((start, end),))
    return {
        symbol: PitMembership(symbol, tuple(sorted(membership.spans)))
        for symbol, membership in memberships.items()
    }


def _asof_timestamp(asof: date | datetime | pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(asof)
    if value.tzinfo is not None:
        value = value.tz_convert(timezone.utc).tz_localize(None)
    # A date represents a completed daily session, so retain its whole day.
    if isinstance(asof, date) and not isinstance(asof, datetime):
        value = value.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return value


def load_daily_symbol(symbol: str, *, asof: date | datetime | pd.Timestamp,
                      data_dir: str | Path = DEFAULT_DAILY_DATA_DIR) -> pd.DataFrame:
    """Load one local parquet and remove every row later than ``asof``.

    This function has no provider fallback.  It therefore has a simple
    point-in-time contract: changing rows strictly after ``asof`` cannot alter
    the returned frame.
    """
    normalized_symbol = str(symbol).upper().strip()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    path = Path(data_dir) / f"{normalized_symbol}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"daily parquet missing for {normalized_symbol}: {path}")
    frame = pd.read_parquet(path).copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        timestamp = next((column for column in ("timestamp", "date", "Date") if column in frame), None)
        if timestamp is None:
            raise ValueError(f"daily parquet has no datetime index: {normalized_symbol}")
        frame.index = pd.to_datetime(frame.pop(timestamp), errors="coerce")
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()].copy()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert(timezone.utc).tz_localize(None)
    frame = frame.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    missing = [column for column in _OHLCV if column not in frame]
    if missing:
        raise ValueError(f"daily parquet missing columns for {normalized_symbol}: {', '.join(missing)}")
    frame = frame.loc[:, _OHLCV].apply(pd.to_numeric, errors="coerce").dropna().sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f"daily parquet has duplicate sessions: {normalized_symbol}")
    frame = frame.loc[frame.index <= _asof_timestamp(asof)].copy()
    frame.index.name = "timestamp"
    frame["symbol"] = normalized_symbol
    return frame


def _pit_membership_mask(
    frame: pd.DataFrame,
    membership: PitMembership,
) -> pd.Series:
    """Boolean mask of rows whose session date falls inside a membership span.

    Membership is decided per session date, not per row, so every row of a
    symbol on a given date is kept or dropped together.
    """
    dates = pd.DatetimeIndex(frame.index).normalize()
    return pd.Series(
        [membership.contains(pd.Timestamp(value)) for value in dates],
        index=frame.index,
    )


def load_daily_universe(symbols: Iterable[str], *, asof: date | datetime | pd.Timestamp,
                        data_dir: str | Path = DEFAULT_DAILY_DATA_DIR,
                        pit_instruments: str | Path | None = None,
                        pit_required: bool = False) -> pd.DataFrame:
    """Load a deterministic timestamp/symbol panel from local daily parquet files.

    When ``pit_instruments`` names a dated-interval instruments file (the
    format `edge/tools/build_pit_universe.py` writes), that file is
    authoritative: rows whose session date falls outside a symbol's
    point-in-time membership spans are dropped, and a symbol absent from the
    file is treated as never a member and dropped entirely.  This removes the
    hindsight/survivorship bias of testing on a fixed list of names that are
    alive today: a name contributes only on the dates it was actually a member
    of the screened universe.

    The default is ``pit_instruments=None`` (no filtering) so existing
    preregistered callers keep their frozen universes unchanged; opting a
    research runner into PIT filtering changes the universe under test and is
    a protocol change that belongs in a new preregistration, not a silent
    edit.  When the file is missing and ``pit_required`` is True the call
    raises; when it is missing and ``pit_required`` is False the call proceeds
    unfiltered, so callers keep working on checkouts without the PIT artifact.
    """
    normalized = sorted({str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()})
    if not normalized:
        raise ValueError("at least one symbol is required")
    memberships: Mapping[str, PitMembership] = {}
    if pit_instruments is not None:
        pit_path = Path(pit_instruments)
        if pit_path.is_file():
            memberships = load_pit_membership(pit_path)
        elif pit_required:
            raise FileNotFoundError(
                f"PIT instruments file required but missing: {pit_path}"
            )
    frames: list[pd.DataFrame] = []
    for symbol in normalized:
        frame = load_daily_symbol(symbol, asof=asof, data_dir=data_dir)
        if memberships:
            membership = memberships.get(symbol)
            if membership is None:
                # The PIT file is authoritative: a symbol it never admits is
                # not part of the screened universe on any date.
                continue
            frame = frame.loc[_pit_membership_mask(frame, membership)].copy()
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise ValueError(
            "no daily bars remain after point-in-time universe filtering; "
            "check the PIT instruments file and the requested symbols"
        )
    panel = pd.concat(frames).reset_index().set_index(["timestamp", "symbol"]).sort_index()
    return panel.loc[:, _OHLCV].copy()
