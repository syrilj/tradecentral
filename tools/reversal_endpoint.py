"""I/O half of the Reversal tab: bar loading, caching, and the scan job.

``GET /api/reversal?symbol=NVDA&tf=1d`` -> ``reversal_payload``
``GET /api/reversal/scan?tf=1d``        -> ``reversal_scan_payload`` (background job)

Bars come from local parquet and are topped up from Yahoo when the local
file is behind. Whatever was actually used is named in ``source``, and a
failed top-up is reported, not hidden -- the read then runs on the stale
bars with their real ``asof``.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from edge.research import reversal_engine as engine
from edge.research import reversal_study as study

EDGE_DIR = Path(__file__).resolve().parents[1]
DATA_1H = EDGE_DIR / "data" / "1h"
DATA_WIDE = EDGE_DIR / "data" / "1d_wide"
DATA_CORE = EDGE_DIR / "data" / "1d"
EXCHANGE_TZ = "America/New_York"

_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_S = 120.0
_BARS_CACHE: dict[tuple[str, str, bool], tuple[float, pd.DataFrame, str]] = {}
_BARS_TTL_S = 300.0


def _read_local(symbol: str, tf: str) -> pd.DataFrame | None:
    bases = [DATA_1H] if tf == "1h" else [DATA_WIDE, DATA_CORE]
    best = None
    for base in bases:
        path = base / f"{symbol}.parquet"
        if not path.is_file():
            continue
        try:
            frame = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume"])
        except Exception:
            continue
        if frame.empty:
            continue
        if best is None or frame.index[-1] > best.index[-1]:
            best = frame
    return best


def _yahoo(symbol: str, tf: str, yf_mod) -> pd.DataFrame | None:
    if yf_mod is None:
        return None
    interval, period = ("60m", "60d") if tf == "1h" else ("1d", "6mo")
    frame = yf_mod.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if frame is None or frame.empty:
        return None
    idx = frame.index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(EXCHANGE_TZ).tz_localize(None)
    if tf == "1d":
        idx = idx.normalize()
    out = pd.DataFrame(
        {
            "open": frame["Open"].to_numpy(float),
            "high": frame["High"].to_numpy(float),
            "low": frame["Low"].to_numpy(float),
            "close": frame["Close"].to_numpy(float),
            "volume": frame["Volume"].to_numpy(float),
        },
        index=idx,
    )
    return out.dropna(subset=["close"])


def _session_is_open_now() -> bool:
    now = pd.Timestamp.now(tz=EXCHANGE_TZ)
    return now.dayofweek < 5 and (9 * 60 + 30) <= now.hour * 60 + now.minute < 16 * 60


def load_bars(symbol: str, tf: str, yf_mod, *, top_up: bool = True) -> tuple[pd.DataFrame | None, str]:
    """(bars, source description). Local parquet, then Yahoo for anything newer."""
    # the scan reads local-only bars; they must never satisfy a topped-up read
    key = (symbol, tf, top_up)
    now = time.time()
    hit = _BARS_CACHE.get(key)
    if hit and now - hit[0] < _BARS_TTL_S:
        return hit[1], hit[2]
    local = _read_local(symbol, tf)
    parts = []
    if local is not None:
        parts.append(f"local {tf} parquet through {local.index[-1].date()}")
    frame = local
    if top_up:
        try:
            fresh = _yahoo(symbol, tf, yf_mod)
        except Exception as exc:  # network / provider failure is reported, not swallowed
            fresh = None
            parts.append(f"yahoo top-up failed ({type(exc).__name__})")
        if fresh is not None and len(fresh):
            if frame is None:
                frame = fresh
            else:
                frame = pd.concat([frame[frame.index < fresh.index[0]], fresh])
            parts.append(f"yahoo {('60m' if tf == '1h' else '1d')} through {fresh.index[-1]}")
    if frame is None:
        return None, "no bars"
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if tf == "1d" and _session_is_open_now() and len(frame) and frame.index[-1].normalize() == pd.Timestamp.now(tz=EXCHANGE_TZ).normalize().tz_localize(None):
        # today's daily bar is still forming; the study only ever saw closed bars
        frame = frame.iloc[:-1]
        parts.append("forming daily bar dropped")
    source = "; ".join(parts)
    _BARS_CACHE[key] = (now, frame, source)
    return frame, source


def reversal_payload(symbol: str, query: dict, yf_mod, *, force: bool = False) -> tuple[dict, int]:
    tf = (query.get("tf", ["1d"])[0] or "1d").lower()
    if tf not in study.CONFIGS:
        return {"error": f"tf must be one of {sorted(study.CONFIGS)}"}, 400
    key = (symbol, tf)
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
            if hit and now - hit[0] < _CACHE_TTL_S:
                return {**hit[1], "cache": {"hit": True, "age_seconds": round(now - hit[0], 1)}}, 200
    try:
        bars, source = load_bars(symbol, tf, yf_mod)
        if bars is None:
            return {"symbol": symbol, "tf": tf, "measurable": False, "reason": f"no {tf} bars for {symbol}"}, 200
        market, _ = load_bars(study.MARKET_SYMBOL, tf, yf_mod)
        if market is None:
            return {"symbol": symbol, "tf": tf, "measurable": False, "reason": "SPY bars unavailable for market context"}, 200
        htf = None
        if tf == "1h":
            htf, htf_src = load_bars(symbol, "1d", yf_mod)
            source = f"{source} | HTF: {htf_src}"
            if htf is None:
                return {"symbol": symbol, "tf": tf, "measurable": False, "reason": "no daily bars for the higher timeframe"}, 200
        breadth = engine.universe_breadth(tf, None)
        payload = engine.read_symbol(symbol, bars, htf if htf is not None else bars, market, tf, source=source, breadth=breadth)
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        return {"error": f"reversal read failed: {type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=3)}, 500
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > 128:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
    return {**payload, "cache": {"hit": False, "age_seconds": 0.0}}, 200


# ---------------------------------------------------------------------------
# scan job

_SCAN_LOCK = threading.Lock()
_SCAN: dict[str, dict[str, Any]] = {}
_SCAN_TTL_S = 1800.0


def _scan_universe() -> list[str]:
    syms = sorted(p.stem for p in DATA_CORE.glob("*.parquet"))
    return syms or sorted(p.stem for p in DATA_WIDE.glob("*.parquet"))


def _run_scan(tf: str, yf_mod) -> None:
    state = _SCAN[tf]
    try:
        syms = _scan_universe()
        state.update(total=len(syms), done=0)
        market, market_src = load_bars(study.MARKET_SYMBOL, tf, yf_mod)
        breadth = engine.universe_breadth(tf, None)
        rows, errors = [], 0
        for sym in syms:
            try:
                # local bars only: one Yahoo call per symbol would take minutes
                bars, _ = load_bars(sym, tf, yf_mod, top_up=False)
                htf = None
                if tf == "1h":
                    htf, _ = load_bars(sym, "1d", yf_mod, top_up=False)
                if bars is not None and (tf == "1d" or htf is not None):
                    row = engine.scan_row(sym, bars, htf if htf is not None else bars, market, tf, breadth)
                    if row:
                        rows.append(row)
            except Exception:
                errors += 1
            state["done"] += 1
        # model rank first: it is the only read with a measured out-of-sample edge
        rows.sort(key=lambda r: (-(r["rank_score"] if r["rank_tier_edge"] == "helps" else -1.0), -(r["rank_score"] or 0)))
        state.update(
            status="ready", rows=rows, errors=errors, finished_at=time.time(),
            market_source=market_src, universe="data/1d core universe (local bars, no Yahoo top-up)",
        )
    except Exception as exc:
        state.update(status="error", error=f"{type(exc).__name__}: {exc}", finished_at=time.time())


def reversal_scan_payload(query: dict, yf_mod, *, force: bool = False) -> tuple[dict, int]:
    tf = (query.get("tf", ["1d"])[0] or "1d").lower()
    if tf not in study.CONFIGS:
        return {"error": f"tf must be one of {sorted(study.CONFIGS)}"}, 400
    now = time.time()
    with _SCAN_LOCK:
        state = _SCAN.get(tf)
        stale = state is None or (state.get("status") in ("ready", "error") and now - state.get("finished_at", 0) > _SCAN_TTL_S)
        if force and state and state.get("status") != "running":
            stale = True
        if stale:
            state = {"status": "running", "started_at": now, "done": 0, "total": None, "rows": []}
            _SCAN[tf] = state
            threading.Thread(target=_run_scan, args=(tf, yf_mod), daemon=True, name=f"reversal-scan-{tf}").start()
    summary, _ = engine.load_artifacts(tf)
    return {
        "tf": tf,
        "status": state["status"],
        "done": state.get("done"),
        "total": state.get("total"),
        "rows": state.get("rows", []),
        "errors": state.get("errors"),
        "error": state.get("error"),
        "universe": state.get("universe"),
        "market_source": state.get("market_source"),
        "age_seconds": round(now - state["finished_at"], 1) if state.get("finished_at") else None,
        "study": engine.study_meta(summary),
    }, 200
