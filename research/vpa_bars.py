"""Timeframe-aware bar loading for the VPA engine (contract §2, defect D1).

Before this module the VPA route ignored the timeframe control entirely: the
handler always received daily bars from `/api/trajectory` and the selector only
relabelled them, so `Daily`, `15m` and `Weekly` returned byte-identical
analyses. This module makes the control real, and -- just as important -- makes
it *honest* when it cannot be honoured.

Data reality on disk (verified, contract §2):

============  ================================================  ==============
Timeframe     Source                                            Status
============  ================================================  ==============
``1h``        ``data/1h/{SYM}.parquet`` native                   59 symbols
``2h``/``4h`` resampled from 1h                                  59 symbols
``1D``        ``data/1d/`` and ``data/1d_wide/``                 558 symbols
``1W``        resampled from daily                               558 symbols
``1m``..``30m``  no data exists                                  unavailable
============  ================================================  ==============

`data/1d` and `data/1d_wide` are **order + fallback, never one replacing the
other** (project convention, see `research/squeeze_validation._load_price`):
both are read when both hold the symbol and the fresher last bar wins, because
`1d_wide` carries 558 symbols while `1d` carries a different 217 and neither is
a superset of the other.

Sub-hourly requests are never silently served as daily. They are downgraded to
the finest real timeframe available for the symbol and the downgrade is
reported through `bars_meta.downgraded` / `downgrade_reason`, which the API
returns on every response as the user's proof the control did something.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research.vpa_thresholds import VPA_THRESHOLDS

EDGE_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = EDGE_ROOT / "data"
HOURLY_DIR = DATA_ROOT / "1h"
# Order matters only as a read order; the fresher file always wins (see
# `_load_daily_frame`). Never treat either directory as replacing the other.
DAILY_DIRS: Tuple[Path, ...] = (DATA_ROOT / "1d", DATA_ROOT / "1d_wide")

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")

#: Ordered timeframe support matrix. ``basis`` is the on-disk granularity a
#: timeframe is built from; ``None`` means no data exists at or below it.
TIMEFRAME_SPECS: List[Dict[str, Any]] = [
    {"value": "1m", "label": "1 Minute", "basis": None, "factor": None, "minutes": 1},
    {"value": "5m", "label": "5 Minutes", "basis": None, "factor": None, "minutes": 5},
    {"value": "15m", "label": "15 Minutes", "basis": None, "factor": None, "minutes": 15},
    {"value": "30m", "label": "30 Minutes", "basis": None, "factor": None, "minutes": 30},
    {"value": "1h", "label": "1 Hour", "basis": "1h", "factor": 1, "minutes": 60},
    {"value": "2h", "label": "2 Hours", "basis": "1h", "factor": 2, "minutes": 120},
    {"value": "4h", "label": "4 Hours", "basis": "1h", "factor": 4, "minutes": 240},
    {"value": "1D", "label": "Daily", "basis": "1d", "factor": 1, "minutes": 1440},
    {"value": "1W", "label": "Weekly", "basis": "1d", "factor": "W", "minutes": 10080},
]

_SPEC_BY_VALUE = {s["value"]: s for s in TIMEFRAME_SPECS}

#: Everything the UI, the old dropdown, or a hand-written curl might send.
_ALIASES: Dict[str, str] = {
    "1m": "1m", "1min": "1m", "1minute": "1m", "m1": "1m",
    "5m": "5m", "5min": "5m", "5minute": "5m", "5-minute": "5m", "m5": "5m",
    "15m": "15m", "15min": "15m", "15minute": "15m", "15-minute": "15m", "m15": "15m",
    "30m": "30m", "30min": "30m", "30minute": "30m", "30-minute": "30m", "m30": "30m",
    "1h": "1h", "60m": "1h", "60min": "1h", "hourly": "1h", "hour": "1h", "h1": "1h",
    "1hour": "1h", "1-hour": "1h",
    "2h": "2h", "120m": "2h", "2hour": "2h", "h2": "2h",
    "4h": "4h", "240m": "4h", "4hour": "4h", "h4": "4h",
    "1d": "1D", "d": "1D", "day": "1D", "daily": "1D", "1day": "1D", "eod": "1D",
    "1w": "1W", "w": "1W", "week": "1W", "weekly": "1W", "1week": "1W",
}

DEFAULT_TIMEFRAME = "1D"


def normalize_timeframe(timeframe: Optional[str]) -> str:
    """Map any label the UI might send onto a matrix entry."""
    if not timeframe:
        return DEFAULT_TIMEFRAME
    key = str(timeframe).strip().lower().replace(" ", "").replace("_", "")
    if key in _ALIASES:
        return _ALIASES[key]
    key2 = key.replace("-", "")
    if key2 in _ALIASES:
        return _ALIASES[key2]
    # Unknown label: do not guess a granularity, fall back to daily and say so
    # via the caller's downgrade_reason.
    return DEFAULT_TIMEFRAME


def sanitize_symbol(symbol: Optional[str]) -> Optional[str]:
    """Uppercase and validate; returns None for anything path-unsafe."""
    if not symbol:
        return None
    sym = str(symbol).strip().upper()
    if not _SYMBOL_RE.match(sym) or ".." in sym:
        return None
    return sym


# ---------------------------------------------------------------- loading --

def _read_parquet(path: Path):
    import pandas as pd  # local import: keeps module importable without pandas

    df = pd.read_parquet(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = ("open", "high", "low", "close", "volume")
    if not all(k in cols for k in need):
        return None
    df = df.rename(columns={cols[k]: k for k in need})[list(need)]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df if not df.empty else None


def _load_hourly_frame(symbol: str):
    path = HOURLY_DIR / f"{symbol}.parquet"
    if not path.is_file():
        return None, None
    try:
        df = _read_parquet(path)
    except Exception:
        return None, None
    if df is None:
        return None, None
    return df, str(path.relative_to(EDGE_ROOT))


def _load_daily_frame(symbol: str):
    """Read every daily directory holding the symbol; freshest last bar wins.

    Project convention: `data/1d` and `data/1d_wide` are order + fallback, not
    substitutes. Returning the first directory that merely *contains* the file
    silently pins the analysis to whichever snapshot is stale.
    """
    best = None
    best_src = None
    best_last = None
    for root in DAILY_DIRS:
        path = root / f"{symbol}.parquet"
        if not path.is_file():
            continue
        try:
            df = _read_parquet(path)
        except Exception:
            continue
        if df is None:
            continue
        last = df.index.max()
        if best is None or last > best_last:
            best, best_last, best_src = df, last, str(path.relative_to(EDGE_ROOT))
    return best, best_src


def _aggregate_intraday(df, factor: int):
    """Chunk consecutive hourly bars into groups of `factor`, within a session.

    Clock resampling (``df.resample("4h")``) straddles the overnight gap and
    invents empty buckets outside the 13:30-20:00 UTC session, which would put
    a bar's volume in the wrong bucket. Grouping consecutive bars per calendar
    day keeps each aggregate inside one session.
    """
    import pandas as pd

    if factor <= 1:
        return df
    out_index = []
    rows = []
    for day, chunk in df.groupby(df.index.normalize(), sort=True):
        for start in range(0, len(chunk), factor):
            piece = chunk.iloc[start : start + factor]
            if piece.empty:
                continue
            out_index.append(piece.index[0])
            rows.append(
                {
                    "open": float(piece["open"].iloc[0]),
                    "high": float(piece["high"].max()),
                    "low": float(piece["low"].min()),
                    "close": float(piece["close"].iloc[-1]),
                    "volume": float(piece["volume"].fillna(0.0).sum()),
                }
            )
    if not rows:
        return None
    return pd.DataFrame(rows, index=pd.DatetimeIndex(out_index)).sort_index()


def _aggregate_weekly(df):
    """Daily -> weekly bars anchored on Friday (the US cash-session week)."""
    agg = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    return agg if not agg.empty else None


def _frame_to_bars(df, limit: int) -> List[Dict[str, Any]]:
    if limit and limit > 0:
        df = df.tail(limit)
    bars: List[Dict[str, Any]] = []
    for ts, row in df.iterrows():
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        except (TypeError, ValueError):
            continue
        if not (h >= l and h > 0):
            continue
        try:
            vol = float(row["volume"])
        except (TypeError, ValueError):
            vol = 0.0
        if vol != vol or vol < 0:  # NaN or negative
            vol = 0.0
        bars.append(
            {
                "date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )
    return bars


def _empty_meta(requested: str, normalized: str, reason: str) -> Dict[str, Any]:
    return {
        "timeframe_requested": requested,
        "timeframe_normalized": normalized,
        "timeframe_served": None,
        "timeframe_label": _SPEC_BY_VALUE.get(normalized, {}).get("label"),
        "downgraded": False,
        "downgrade_reason": reason,
        "bar_count": 0,
        "first_bar": None,
        "last_bar": None,
        "source": None,
        "resampled_from": None,
        "available": False,
    }


def default_lookback(timeframe: str) -> int:
    cfg = VPA_THRESHOLDS["bars"]
    return int(cfg["default_lookback"].get(timeframe, cfg["fallback_lookback"]))


def load_bars(
    symbol: Optional[str],
    timeframe: Optional[str] = None,
    lookback: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load bars for `symbol` at `timeframe`, reporting exactly what was served.

    Returns ``(bars, bars_meta)``. `bars` is a list of
    ``{date, open, high, low, close, volume}`` dicts, oldest first. `bars_meta`
    is the contract §4 block and is returned even when nothing could be loaded,
    so the caller always has something honest to say.
    """
    requested = str(timeframe) if timeframe else DEFAULT_TIMEFRAME
    normalized = normalize_timeframe(timeframe)
    sym = sanitize_symbol(symbol)
    if not sym:
        return [], _empty_meta(requested, normalized, "no valid symbol supplied")

    spec = _SPEC_BY_VALUE[normalized]
    downgraded = False
    reason: Optional[str] = None
    target = normalized

    # Sub-hourly: there is no data below 1h anywhere in this repo (contract §2).
    if spec["basis"] is None:
        downgraded = True
        reason = f"no data below 1h for {sym}; {normalized} is not backed by any source"
        target = "1h"

    hourly, hourly_src = (None, None)
    if _SPEC_BY_VALUE[target]["basis"] == "1h" or target == "1h":
        hourly, hourly_src = _load_hourly_frame(sym)
        if hourly is None:
            # 59 symbols have hourly bars; everything else falls back to daily.
            prior = reason
            downgraded = True
            reason = f"no hourly bars on disk for {sym}; served daily instead"
            if prior:
                reason = f"{prior}; additionally {reason}"
            target = "1D"

    frame = None
    source = None
    resampled_from = None

    if _SPEC_BY_VALUE[target]["basis"] == "1h":
        factor = _SPEC_BY_VALUE[target]["factor"]
        frame = hourly if factor == 1 else _aggregate_intraday(hourly, int(factor))
        source = hourly_src
        resampled_from = None if factor == 1 else "1h"
    else:
        daily, daily_src = _load_daily_frame(sym)
        if daily is None:
            return [], _empty_meta(
                requested, normalized, f"no daily parquet found for {sym} in data/1d or data/1d_wide"
            )
        source = daily_src
        if target == "1W":
            frame = _aggregate_weekly(daily)
            resampled_from = "1d"
        else:
            frame = daily

    if frame is None or frame.empty:
        return [], _empty_meta(requested, normalized, f"no usable bars for {sym} at {target}")

    limit = int(lookback) if lookback else default_lookback(target)
    bars = _frame_to_bars(frame, limit)
    if not bars:
        return [], _empty_meta(requested, normalized, f"no usable bars for {sym} at {target}")

    meta = {
        "timeframe_requested": requested,
        "timeframe_normalized": normalized,
        "timeframe_served": target,
        "timeframe_label": _SPEC_BY_VALUE[target]["label"],
        "downgraded": bool(downgraded),
        "downgrade_reason": reason,
        "bar_count": len(bars),
        "first_bar": bars[0]["date"],
        "last_bar": bars[-1]["date"],
        "source": source,
        "resampled_from": resampled_from,
        "lookback_requested": limit,
        "available": True,
    }
    return bars, meta


def bars_meta_from_series(
    bars: List[Dict[str, Any]],
    timeframe: Optional[str],
    source: str = "client_supplied_series",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """`bars_meta` for bars the caller handed us instead of ones we loaded.

    The UI posts an `ohlcv_series` alongside the symbol; when we cannot back
    the requested timeframe from disk we may still analyse those bars, but the
    response has to say the timeframe is unverified rather than claim it.
    """
    requested = str(timeframe) if timeframe else DEFAULT_TIMEFRAME
    normalized = normalize_timeframe(timeframe)
    if not bars:
        return _empty_meta(requested, normalized, reason or "no bars supplied")
    return {
        "timeframe_requested": requested,
        "timeframe_normalized": normalized,
        "timeframe_served": normalized,
        "timeframe_label": _SPEC_BY_VALUE.get(normalized, {}).get("label"),
        "downgraded": bool(reason),
        "downgrade_reason": reason,
        "bar_count": len(bars),
        "first_bar": bars[0].get("date"),
        "last_bar": bars[-1].get("date"),
        "source": source,
        "resampled_from": None,
        "lookback_requested": len(bars),
        "available": True,
        "client_supplied": True,
    }


# ------------------------------------------------------------ availability --

_COUNT_CACHE: Dict[str, int] = {}


def _count_parquet(directory: Path) -> int:
    key = str(directory)
    if key not in _COUNT_CACHE:
        try:
            _COUNT_CACHE[key] = sum(1 for _ in directory.glob("*.parquet"))
        except OSError:
            _COUNT_CACHE[key] = 0
    return _COUNT_CACHE[key]


def data_source_counts() -> Dict[str, int]:
    """Symbol counts per on-disk source, for `/api/vpa/health`."""
    daily = set()
    for root in DAILY_DIRS:
        try:
            daily.update(p.stem for p in root.glob("*.parquet"))
        except OSError:
            continue
    return {
        "1h": _count_parquet(HOURLY_DIR),
        "1d": _count_parquet(DATA_ROOT / "1d"),
        "1d_wide": _count_parquet(DATA_ROOT / "1d_wide"),
        "daily_union": len(daily),
    }


def timeframe_availability() -> List[Dict[str, Any]]:
    """The per-timeframe matrix the frontend builds its dropdown from."""
    counts = data_source_counts()
    hourly_n = counts["1h"]
    daily_n = counts["daily_union"]
    out: List[Dict[str, Any]] = []
    for spec in TIMEFRAME_SPECS:
        entry: Dict[str, Any] = {
            "value": spec["value"],
            "label": spec["label"],
            "available": spec["basis"] is not None,
        }
        if spec["basis"] is None:
            entry["symbols"] = 0
            entry["reason"] = "no data below 1h"
            entry["fallback"] = "1h"
        elif spec["basis"] == "1h":
            entry["symbols"] = hourly_n
            entry["source"] = "data/1h" + ("" if spec["factor"] == 1 else " (resampled)")
            entry["native"] = spec["factor"] == 1
            entry["fallback"] = "1D"
            entry["reason"] = None
        else:
            entry["symbols"] = daily_n
            entry["source"] = "data/1d + data/1d_wide" + ("" if spec["factor"] == 1 else " (resampled)")
            entry["native"] = spec["factor"] == 1
            entry["reason"] = None
        out.append(entry)
    return out


def symbol_timeframes(symbol: Optional[str]) -> Dict[str, bool]:
    """Which timeframes this specific symbol can actually be served at."""
    sym = sanitize_symbol(symbol)
    if not sym:
        return {spec["value"]: False for spec in TIMEFRAME_SPECS}
    has_hourly = (HOURLY_DIR / f"{sym}.parquet").is_file()
    has_daily = any((root / f"{sym}.parquet").is_file() for root in DAILY_DIRS)
    out = {}
    for spec in TIMEFRAME_SPECS:
        if spec["basis"] is None:
            out[spec["value"]] = False
        elif spec["basis"] == "1h":
            out[spec["value"]] = has_hourly
        else:
            out[spec["value"]] = has_daily
    return out
