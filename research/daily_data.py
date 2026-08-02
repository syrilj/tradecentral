"""Point-in-time loading for the local daily OHLCV research universe."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DATA_DIR = EDGE_ROOT / "data" / "1d"
_OHLCV = ("open", "high", "low", "close", "volume")


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


def load_daily_universe(symbols: Iterable[str], *, asof: date | datetime | pd.Timestamp,
                        data_dir: str | Path = DEFAULT_DAILY_DATA_DIR) -> pd.DataFrame:
    """Load a deterministic timestamp/symbol panel from local daily parquet files."""
    normalized = sorted({str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()})
    if not normalized:
        raise ValueError("at least one symbol is required")
    frames = [load_daily_symbol(symbol, asof=asof, data_dir=data_dir) for symbol in normalized]
    panel = pd.concat(frames).reset_index().set_index(["timestamp", "symbol"]).sort_index()
    return panel.loc[:, _OHLCV].copy()
