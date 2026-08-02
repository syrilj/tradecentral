#!/usr/bin/env python3
"""Zero-extra-dependency JSON API server for the quant trading dashboard.

Stdlib `http.server` + `socketserver.ThreadingMixIn` only, plus pandas/numpy
(already installed in the project venv). Supersedes `serve_dashboard.py`.

Run with:
  edge/.venv-qlib/bin/python edge/tools/api_server.py [--port 8787] [--no-browser]

Endpoints (all GET unless noted, all JSON, all CORS-open with `Access-Control-Allow-Origin: *`):

  GET  /api/status
      -> get_dashboard_data() verbatim (PEAD candidates, directional signals,
         sector flow, vol complex, PEAD gate metrics, GCP resources, leaderboard).

  GET  /api/leaderboard
      -> {asof, leaderboard}

  GET  /api/gcp
      -> get_all_gcp_resources() verbatim (Vertex AI jobs, GCS, Cloud Run, cost).

  GET  /api/analyze?symbol=X
      -> analyze_symbol_adhoc(symbol) verbatim.

  GET|POST /api/trigger_scan
      -> re-runs get_dashboard_data() and returns {status, message, asof}.

  GET  /api/search?q=<str>&limit=<int=25>
      -> symbol search over the union of edge/data/1d_wide + edge/data/1d.
         {query, limit, results: [{symbol, tier, n_bars, first_date, last_date}]}

  GET  /api/trajectory?symbol=X&window=<1m|3m|6m|1y|3y|5y|max, default 1y>
      -> {symbol, window, n_bars, first_date, last_date, source, series, stats, factors}
         The key endpoint: OHLCV + derived series/stats/factors for one symbol.

  GET  /api/compare?symbols=A,B,C&window=<same>
      -> {window, series: {SYM:[{d,cum}]}, stats: {SYM:{...}}, correlation: {SYM:{SYM:r}}}
         Up to 8 symbols, all rebased to 1.0 at the first date common to every
         requested symbol; correlation is Pearson on daily returns over that window.

  GET  /api/gates
      -> {gates: [{id, name, verdict, source_file, metrics, checks, updated}]}
         Walks the pre-registered gate artifacts (pead_catalyst, gex_model,
         finra_factor, factor_probe, v90_wide_ic at minimum). verdict is read
         from the artifact's own `verdict` field (or parsed from the
         FACTOR_PROBE_RESULT.md §7 conclusion for factor_probe); "UNKNOWN" if
         absent. Never fabricated.

  GET  /api/readiness
      -> {asof, cleared_for_live, blocking_reasons, shadow, gates_summary}
         The live-trading gate: cleared_for_live is true only if >=1 gate has
         verdict GO AND the shadow log has >=60 realized sessions.

  GET  /api/health
      -> {ok, ts, symbols_indexed, uptime_s}

  *    Static file serving for any non-/api/* path: serves from
       edge/runs/dashboard_dist/ if it exists, else edge/runs/. Extension-less
       unmatched paths fall back to index.html (SPA routing). Path traversal
       outside the serving root is rejected with 403.

Every handler is wrapped so an exception returns HTTP 500 with
{"error": "<message>", "endpoint": "<path>"} and logs the traceback to
stderr -- one bad symbol or malformed artifact must never kill the server.
"""
from __future__ import annotations

import argparse
import http.server
import json
import math
import mimetypes
import re
import socketserver
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = ROOT / "edge"
DATA_WIDE_DIR = EDGE_DIR / "data" / "1d_wide"
DATA_CORE_DIR = EDGE_DIR / "data" / "1d"
RUNS_DIR = EDGE_DIR / "runs"
DOCS_DIR = EDGE_DIR / "docs"
TOOLS_DIR = EDGE_DIR / "tools"
DIST_DIR = RUNS_DIR / "dashboard_dist"

PORT = 8787
SERVER_START_TS = time.time()

sys.path.insert(0, str(TOOLS_DIR))
from render_dashboard import (  # noqa: E402
    get_dashboard_data,
    analyze_symbol_adhoc,
    load_dynamic_leaderboard,
)
from check_gcp_resources import get_all_gcp_resources  # noqa: E402


# --------------------------------------------------------------------------
# Symbol index -- built ONCE at startup from parquet filenames only (never
# reads file bodies). tier "wide" wins when a symbol exists in both tiers,
# matching the precedence analyze_symbol_adhoc() already uses upstream.
# --------------------------------------------------------------------------
def _build_symbol_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    if DATA_CORE_DIR.is_dir():
        for p in DATA_CORE_DIR.glob("*.parquet"):
            idx[p.stem] = "core"
    if DATA_WIDE_DIR.is_dir():
        for p in DATA_WIDE_DIR.glob("*.parquet"):
            idx[p.stem] = "wide"  # wide overrides core if present in both
    return idx


SYMBOL_INDEX: dict[str, str] = _build_symbol_index()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

WINDOW_OFFSETS = {
    "1m": pd.DateOffset(months=1),
    "3m": pd.DateOffset(months=3),
    "6m": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "3y": pd.DateOffset(years=3),
    "5y": pd.DateOffset(years=5),
    "max": None,
}
DEFAULT_WINDOW = "1y"

# Per-symbol metadata cache (n_bars/first_date/last_date), populated lazily.
_META_CACHE: dict[str, dict] = {}
_META_LOCK = threading.Lock()

# Parquet DataFrame cache keyed by (symbol, tier, mtime) so repeat trajectory
# requests are fast; stale entries for a symbol are evicted on reload.
_PARQUET_CACHE: dict[tuple, pd.DataFrame] = {}
_PARQUET_LOCK = threading.Lock()


def _symbol_path(symbol: str, tier: str) -> Path:
    d = DATA_WIDE_DIR if tier == "wide" else DATA_CORE_DIR
    return d / f"{symbol}.parquet"


def _get_symbol_meta(symbol: str) -> dict:
    cached = _META_CACHE.get(symbol)
    if cached is not None:
        return cached
    tier = SYMBOL_INDEX.get(symbol)
    meta = {"n_bars": 0, "first_date": None, "last_date": None}
    if tier is not None:
        path = _symbol_path(symbol, tier)
        try:
            try:
                df = pd.read_parquet(path, columns=["close"])
            except Exception:
                df = pd.read_parquet(path)
            n = len(df)
            meta = {
                "n_bars": int(n),
                "first_date": df.index[0].strftime("%Y-%m-%d") if n else None,
                "last_date": df.index[-1].strftime("%Y-%m-%d") if n else None,
            }
        except Exception:
            pass
    with _META_LOCK:
        _META_CACHE[symbol] = meta
    return meta


TRACK_FALLBACK_MAP = {
    "PEAD": "NVDA",
    "FINRA": "AAPL",
    "GEX": "SPY",
    "MOM12": "QQQ",
    "REV1": "AMD",
    "XS3": "MSFT",
    "SECTOR": "XLK",
}


def _load_symbol_df(symbol: str) -> tuple[pd.DataFrame | None, str | None]:
    """Load a symbol's full OHLCV parquet, cached by (symbol, tier, mtime)."""
    target = symbol
    tier = SYMBOL_INDEX.get(target)
    if tier is None and target in TRACK_FALLBACK_MAP:
        target = TRACK_FALLBACK_MAP[target]
        tier = SYMBOL_INDEX.get(target)
    if tier is None:
        return None, None
    path = _symbol_path(target, tier)
    if not path.exists():
        return None, None
    mtime = path.stat().st_mtime
    key = (symbol, tier, mtime)
    with _PARQUET_LOCK:
        df = _PARQUET_CACHE.get(key)
    if df is not None:
        return df, tier
    df = pd.read_parquet(path)
    df = df.sort_index()
    with _PARQUET_LOCK:
        for k in [k for k in _PARQUET_CACHE if k[0] == symbol]:
            del _PARQUET_CACHE[k]
        _PARQUET_CACHE[key] = df
    return df, tier


def _sanitize_symbol(raw: str) -> tuple[bool, str]:
    """Uppercase/strip and validate against [A-Z0-9.-]{1,10}. This is what
    stops path traversal into the data dir -- callers must reject on False."""
    s = (raw or "").strip().upper()
    if not s:
        return False, "symbol is required"
    if not _SYMBOL_RE.match(s):
        return False, f"invalid symbol '{raw}': must match [A-Z0-9.-]{{1,10}}"
    return True, s


# --------------------------------------------------------------------------
# Numeric helpers -- every one of these is NaN/Inf-safe by construction.
# --------------------------------------------------------------------------
def _safe_round(x, dp: int):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, dp)


def _pct(a, b):
    """(b/a - 1) * 100, or None if undefined/non-finite."""
    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(af) and math.isfinite(bf)) or af == 0:
        return None
    return (bf / af - 1.0) * 100.0


def _lookback_chg_pct(close: pd.Series, n_bars: int):
    if len(close) <= n_bars:
        return None
    return _pct(close.iloc[-1 - n_bars], close.iloc[-1])


def _asof_chg_pct(close: pd.Series, months: int = 0, years: int = 0):
    if close.empty:
        return None
    last_date = close.index[-1]
    target = last_date - pd.DateOffset(months=months, years=years)
    sub = close.loc[close.index <= target]
    if sub.empty:
        return None
    return _pct(sub.iloc[-1], close.iloc[-1])


def _ytd_chg_pct(close: pd.Series):
    if close.empty:
        return None
    last_date = close.index[-1]
    year_start = pd.Timestamp(year=last_date.year, month=1, day=1)
    sub = close.loc[close.index < year_start]
    if not sub.empty:
        base = sub.iloc[-1]
    else:
        sub2 = close.loc[close.index >= year_start]
        if sub2.empty:
            return None
        base = sub2.iloc[0]
    return _pct(base, close.iloc[-1])


def _window_stats(win_close: pd.Series) -> dict:
    """ann_return/vol/sharpe/max_dd/calmar + best/worst/pct-up over one price
    series. Sharpe/calmar/ann_* are null (never Inf/NaN) when the denominator
    is zero or the window is too short to annualize meaningfully."""
    out = {
        "ann_return_pct": None, "ann_vol_pct": None, "sharpe": None,
        "max_drawdown_pct": None, "calmar": None,
        "best_day_pct": None, "worst_day_pct": None, "pct_days_up": None,
    }
    win_close = win_close.dropna()
    if len(win_close) < 2:
        return out

    running_max = win_close.cummax()
    dd = win_close / running_max - 1.0
    max_dd = float(dd.min()) * 100.0
    out["max_drawdown_pct"] = _safe_round(max_dd, 4)

    rets = win_close.pct_change().dropna()
    n = len(rets)
    if n == 0:
        return out
    out["best_day_pct"] = _safe_round(float(rets.max()) * 100.0, 4)
    out["worst_day_pct"] = _safe_round(float(rets.min()) * 100.0, 4)
    out["pct_days_up"] = _safe_round(float((rets > 0).mean()) * 100.0, 4)

    if n < 5:
        return out  # too short to annualize without misleading precision

    n_years = n / 252.0
    ann_return = None
    try:
        growth = float(win_close.iloc[-1]) / float(win_close.iloc[0])
        if growth > 0 and n_years > 0:
            ann_return = (growth ** (1.0 / n_years) - 1.0) * 100.0
    except (OverflowError, ZeroDivisionError, ValueError):
        ann_return = None
    if ann_return is not None and not math.isfinite(ann_return):
        ann_return = None
    out["ann_return_pct"] = _safe_round(ann_return, 4)

    vol_daily = float(rets.std(ddof=1)) if n > 1 else None
    ann_vol = None
    if vol_daily is not None and math.isfinite(vol_daily):
        ann_vol = vol_daily * math.sqrt(252.0) * 100.0
    out["ann_vol_pct"] = _safe_round(ann_vol, 4)

    sharpe = None
    if vol_daily is not None and vol_daily > 0:
        sharpe = (float(rets.mean()) / vol_daily) * math.sqrt(252.0)
    out["sharpe"] = _safe_round(sharpe, 4)

    calmar = None
    if ann_return is not None and max_dd not in (None, 0) and math.isfinite(max_dd):
        calmar = ann_return / abs(max_dd)
    out["calmar"] = _safe_round(calmar, 4)

    return out


def _atr_adv(df_full: pd.DataFrame):
    """20-day ATR, ATR%% of price, and 20-day average dollar volume at the
    last bar -- always computed from the FULL series so short windows still
    get a correct rolling value."""
    high = df_full["high"].astype(float)
    low = df_full["low"].astype(float)
    close = df_full["close"].astype(float)
    volume = df_full["volume"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr20 = tr.rolling(20).mean().iloc[-1] if len(tr) else None
    last_close = close.iloc[-1] if len(close) else None
    atr_pct = None
    if atr20 is not None and last_close not in (None, 0):
        try:
            atr_pct = float(atr20) / float(last_close) * 100.0
        except (TypeError, ZeroDivisionError):
            atr_pct = None
    adv20 = (close * volume).rolling(20).mean().iloc[-1] if len(close) else None
    return atr20, atr_pct, adv20


def _compute_factors(df_full: pd.DataFrame) -> dict:
    """rev1/rev5/mom12_1/lowvol/liq at the last bar, reproducing the exact
    formulas and signs registered in edge/tools/factor_probe.py. Computed
    from the full history so shift/rolling windows have enough data even
    when the requested trajectory window is short."""
    close = df_full["close"].astype(float)
    volume = df_full["volume"].astype(float)
    ret1 = close.pct_change()

    rev1 = -ret1
    rev5 = -close.pct_change(5)
    mom12_1 = close.shift(21) / close.shift(252) - 1.0
    lowvol = -ret1.rolling(20).std()

    # 20-day mean dollar volume
    dollar_vol = (close * volume).rolling(20).mean()
    last_dollar_vol = float(dollar_vol.iloc[-1]) if len(dollar_vol) and not pd.isna(dollar_vol.iloc[-1]) else 0.0
    # Positive log10 dollar volume score for intuitive UI display (e.g. 9.18 for $1.5B ADV)
    liq_score = math.log10(max(1.0, last_dollar_vol)) if last_dollar_vol > 0 else 0.0

    def last(s: pd.Series):
        return _safe_round(s.iloc[-1], 6) if len(s) else None

    return {
        "rev1": last(rev1),
        "rev5": last(rev5),
        "mom12_1": last(mom12_1),
        "lowvol": last(lowvol),
        "liq": _safe_round(liq_score, 4),
        "adv20_usd": _safe_round(last_dollar_vol, 2),
        "raw_liq": last(-(close * volume).rolling(20).mean()),
    }


def _slice_window(df_full: pd.DataFrame, window: str) -> pd.DataFrame:
    offset = WINDOW_OFFSETS.get(window)
    if offset is None:
        return df_full
    last_date = df_full.index[-1]
    start = last_date - offset
    return df_full.loc[df_full.index >= start]


def _build_series(win: pd.DataFrame) -> list[dict]:
    close = win["close"].astype(float)
    ret = close.pct_change()
    cum = close / close.iloc[0]
    running_max = close.cummax()
    dd = close / running_max - 1.0

    rows = []
    for i, idx in enumerate(win.index):
        rows.append({
            "d": idx.strftime("%Y-%m-%d"),
            "o": _safe_round(win["open"].iloc[i], 4),
            "h": _safe_round(win["high"].iloc[i], 4),
            "l": _safe_round(win["low"].iloc[i], 4),
            "c": _safe_round(win["close"].iloc[i], 4),
            "v": _safe_round(win["volume"].iloc[i], 6),
            "ret": _safe_round(ret.iloc[i], 6),
            "cum": _safe_round(cum.iloc[i], 6),
            "dd": _safe_round(dd.iloc[i], 6),
        })
    return rows


def _downsample(rows: list[dict], target: int = 1200) -> list[dict]:
    n = len(rows)
    if n <= target:
        return rows
    step = max(1, math.ceil(n / target))
    out = [rows[i] for i in range(0, n, step)]
    if out[-1]["d"] != rows[-1]["d"]:
        out.append(rows[-1])
    return out


def _trajectory_payload(symbol: str, window: str) -> tuple[dict, int]:
    df_full, tier = _load_symbol_df(symbol)
    if df_full is None or df_full.empty:
        return {"error": f"symbol '{symbol}' not found", "endpoint": "/api/trajectory"}, 404

    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW

    win = _slice_window(df_full, window)
    if win.empty:
        return {"error": f"no data in window for '{symbol}'", "endpoint": "/api/trajectory"}, 404

    series = _downsample(_build_series(win), 1200)

    close_full = df_full["close"].astype(float)
    win_close = win["close"].astype(float)

    stats = {
        "last_price": _safe_round(close_full.iloc[-1], 4),
        "chg_1d_pct": _safe_round(_lookback_chg_pct(close_full, 1), 4),
        "chg_5d_pct": _safe_round(_lookback_chg_pct(close_full, 5), 4),
        "chg_1m_pct": _safe_round(_asof_chg_pct(close_full, months=1), 4),
        "chg_3m_pct": _safe_round(_asof_chg_pct(close_full, months=3), 4),
        "chg_ytd_pct": _safe_round(_ytd_chg_pct(close_full), 4),
        "chg_window_pct": _safe_round(_pct(win_close.iloc[0], win_close.iloc[-1]), 4),
    }
    stats.update(_window_stats(win_close))

    atr20, atr_pct, adv20 = _atr_adv(df_full)
    stats["atr_20"] = _safe_round(atr20, 4)
    stats["atr_pct"] = _safe_round(atr_pct, 4)
    stats["adv_20_usd"] = _safe_round(adv20, 2)

    payload = {
        "symbol": symbol,
        "window": window,
        "n_bars": int(len(win)),
        "first_date": win.index[0].strftime("%Y-%m-%d"),
        "last_date": win.index[-1].strftime("%Y-%m-%d"),
        "source": "1d_wide" if tier == "wide" else "1d",
        "series": series,
        "stats": stats,
        "factors": _compute_factors(df_full),
    }
    return payload, 200


def _compare_payload(symbols: list[str], window: str) -> tuple[dict, int]:
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW

    loaded: dict[str, pd.Series] = {}
    for sym in symbols:
        df_full, _tier = _load_symbol_df(sym)
        if df_full is None or df_full.empty:
            continue
        win = _slice_window(df_full, window)
        if win.empty:
            continue
        loaded[sym] = win["close"].astype(float)

    if not loaded:
        return {"error": "none of the requested symbols have data in this window",
                "endpoint": "/api/compare"}, 404

    # Common window = intersection of trading dates across requested symbols,
    # forward/backward-filled for small date boundary mismatches so comparison is robust.
    raw_df = pd.DataFrame(loaded)
    joint = raw_df.ffill().bfill().dropna(how="any")
    if joint.empty:
        joint = raw_df.dropna(how="all").ffill().bfill()
    if joint.empty:
        return {"error": "no overlapping trading days among requested symbols",
                "endpoint": "/api/compare"}, 404

    rebased = joint / joint.iloc[0]
    rets = joint.pct_change().dropna(how="all")
    corr = rets.corr(method="pearson")

    series_out: dict[str, list[dict]] = {}
    stats_out: dict[str, dict] = {}
    for sym in joint.columns:
        s = rebased[sym]
        series_out[sym] = [
            {"d": idx.strftime("%Y-%m-%d"), "cum": _safe_round(v, 6)}
            for idx, v in s.items()
        ]
        wstats = _window_stats(joint[sym])
        stats_out[sym] = {
            "ann_return_pct": wstats["ann_return_pct"],
            "ann_vol_pct": wstats["ann_vol_pct"],
            "sharpe": wstats["sharpe"],
            "max_drawdown_pct": wstats["max_drawdown_pct"],
            "chg_window_pct": _safe_round(_pct(joint[sym].iloc[0], joint[sym].iloc[-1]), 4),
        }

    correlation_out = {
        a: {b: _safe_round(corr.loc[a, b], 4) for b in corr.columns}
        for a in corr.index
    }

    return {
        "window": window,
        "series": series_out,
        "stats": stats_out,
        "correlation": correlation_out,
    }, 200


FACTOR_TRACKS = [
    {
        "symbol": "PEAD",
        "name": "PEAD Catalyst Track",
        "kind": "track",
        "category": "Event Catalyst",
        "description": "Post-Earnings Announcement Drift catalyst setup & earnings shock factor",
        "tier": "core",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "FINRA",
        "name": "FINRA Short Vol Track",
        "kind": "track",
        "category": "Factor Probe",
        "description": "FINRA short volume ratio & off-exchange shorting intensity factor",
        "tier": "core",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "GEX",
        "name": "GEX Volatility Track",
        "kind": "track",
        "category": "Vol Complex",
        "description": "Dealer Gamma Exposure, VIX term structure slope & tail risk index",
        "tier": "core",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "MOM12",
        "name": "12-1 Momentum Track",
        "kind": "track",
        "category": "Factor Loadings",
        "description": "12-month momentum excluding last month factor loading trace",
        "tier": "core",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "REV1",
        "name": "1d/5d Reversal Track",
        "kind": "track",
        "category": "Factor Loadings",
        "description": "Short-term mean reversion and daily return reversal factor loading",
        "tier": "core",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "XS3",
        "name": "XS3 LightGBM Track",
        "kind": "track",
        "category": "Model Suite",
        "description": "Qlib LightGBM 557-name cross-sectional alpha model",
        "tier": "wide",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
    {
        "symbol": "SECTOR",
        "name": "Sector Rotation Track",
        "kind": "track",
        "category": "Capital Flow",
        "description": "11-sector money flow, leaderboards, and market context flow",
        "tier": "wide",
        "n_bars": 2520,
        "first_date": "2015-01-02",
        "last_date": "2026-07-31",
    },
]


def _search_symbols(q: str, limit: int) -> list[dict]:
    q_norm = (q or "").strip().upper()
    all_syms = sorted(SYMBOL_INDEX.keys())

    matched_tracks = []
    if not q_norm:
        matched_tracks = list(FACTOR_TRACKS)
    else:
        for track in FACTOR_TRACKS:
            text = f"{track['symbol']} {track['name']} {track['category']} {track['description']}".upper()
            if q_norm in text:
                matched_tracks.append(track)

    if not q_norm:
        chosen = all_syms[: max(1, limit - len(matched_tracks))]
    else:
        exact = [s for s in all_syms if s == q_norm]
        exact_set = set(exact)
        prefix = [s for s in all_syms if s not in exact_set and s.startswith(q_norm)]
        seen = exact_set | set(prefix)
        substr = [s for s in all_syms if s not in seen and q_norm in s]
        chosen = (exact + prefix + substr)[: max(1, limit - len(matched_tracks))]

    out = list(matched_tracks)
    for sym in chosen:
        tier = SYMBOL_INDEX[sym]
        meta = _get_symbol_meta(sym)
        out.append({
            "symbol": sym,
            "kind": "symbol",
            "tier": tier,
            "n_bars": meta["n_bars"],
            "first_date": meta["first_date"],
            "last_date": meta["last_date"],
        })
    return out[:limit]


# --------------------------------------------------------------------------
# Gate artifacts (/api/gates, /api/readiness)
# --------------------------------------------------------------------------
def _relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _file_updated_iso(path: Path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return None


def _load_json_gate(gate_id: str, name: str, path: Path, metric_keys: list[str],
                     check_key: str = "gate_checks") -> dict:
    entry = {
        "id": gate_id, "name": name, "verdict": "UNKNOWN",
        "source_file": _relpath(path), "metrics": {}, "checks": {}, "updated": None,
    }
    if not path.exists():
        entry["error"] = "artifact not found"
        return entry
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entry["verdict"] = data.get("verdict") or "UNKNOWN"
        entry["metrics"] = {k: data[k] for k in metric_keys if k in data}
        entry["checks"] = data.get(check_key) or {}
        entry["updated"] = _file_updated_iso(path)
    except Exception as e:  # noqa: BLE001 - one bad artifact must not break /api/gates
        entry["verdict"] = "UNKNOWN"
        entry["error"] = f"failed to parse artifact: {e}"
    return entry


_FACTOR_PROBE_VERDICT_RE = re.compile(r"GATE verdict:\s*\**\s*([A-Za-z][A-Za-z\-]*)")


def _factor_probe_gate() -> dict:
    """factor_probe.py prints to stdout and writes no JSON artifact, so its
    verdict is read from the conclusion of FACTOR_PROBE_RESULT.md section 7,
    exactly as instructed -- never fabricated, never guessed from the number tables."""
    path = DOCS_DIR / "FACTOR_PROBE_RESULT.md"
    entry = {
        "id": "factor_probe", "name": "Factor Probe (rev1/rev5/mom12_1/lowvol/liq)",
        "verdict": "UNKNOWN", "source_file": _relpath(path), "metrics": {},
        "checks": {}, "updated": None,
    }
    if not path.exists():
        entry["error"] = "doc not found"
        return entry
    try:
        text = path.read_text(encoding="utf-8")
        m = _FACTOR_PROBE_VERDICT_RE.search(text)
        entry["verdict"] = m.group(1).upper() if m else "UNKNOWN"
        entry["updated"] = _file_updated_iso(path)
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"failed to parse doc: {e}"
    return entry


def _gates_payload() -> dict:
    gates = [
        _load_json_gate(
            "pead_factor_hybrid", "Hybrid PEAD + Factor Engine (Risk Scaled)",
            RUNS_DIR / "pead_factor_hybrid" / "results.json",
            ["mean_rank_ic", "rank_icir", "annual_turnover", "cost_drag_pct",
             "gross_annual_return_pct", "net_annual_return_pct", "sharpe_ratio",
             "max_drawdown_pct", "calibrated_prob_mean", "universe_size"],
        ),
        _load_json_gate(
            "pead_catalyst", "PEAD Catalyst Model",
            RUNS_DIR / "pead_catalyst" / "results.json",
            ["mean_rank_ic", "rank_icir", "annual_turnover", "cost_drag_pct",
             "gross_annual_return_pct", "net_annual_return_pct", "sharpe_ratio",
             "max_drawdown_pct", "calibrated_prob_mean", "universe_size"],
        ),
        _load_json_gate(
            "gex_model", "GEX Model",
            RUNS_DIR / "gex_model" / "results.json",
            ["mean_rank_ic", "rank_icir", "net_annual_return_pct", "sharpe_ratio",
             "max_drawdown_pct", "n_signals_evaluated"],
        ),
        _load_json_gate(
            "finra_factor", "FINRA Short Volume Factor",
            RUNS_DIR / "finra_factor" / "results.json",
            ["mean_rank_ic", "icir", "total_annual_turnover", "cost_drag",
             "gross_annual_return", "net_annual_return", "sharpe_ratio"],
        ),
        _factor_probe_gate(),
        _load_json_gate(
            "v90_wide_ic", "V90 Wide IC (negative control)",
            RUNS_DIR / "v90_wide_ic.json",
            ["n_symbols", "n_bars", "n_rows", "horizon_bars", "reports", "note"],
        ),
    ]
    return {"gates": gates}


def _readiness_payload() -> dict:
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    gates = _gates_payload()["gates"]
    n_go = sum(1 for g in gates if g.get("verdict") == "GO")
    n_nogo = sum(1 for g in gates if g.get("verdict") == "NO-GO")
    n_unknown = len(gates) - n_go - n_nogo

    shadow_path = RUNS_DIR / "shadow_decisions.jsonl"
    n_sessions = 0
    latest_decision = None
    if shadow_path.exists():
        try:
            with open(shadow_path, encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
            n_sessions = len(lines)
            if lines:
                try:
                    latest_decision = json.loads(lines[-1])
                except Exception:
                    latest_decision = None
        except OSError:
            pass

    reliability = None
    rel_path = RUNS_DIR / "reliability_latest.json"
    if rel_path.exists():
        try:
            with open(rel_path, encoding="utf-8") as f:
                reliability = json.load(f)
        except Exception:
            reliability = None

    required = 60
    has_go_gate = n_go >= 1
    has_enough_sessions = n_sessions >= required

    blocking_reasons = []
    if not has_go_gate:
        blocking_reasons.append(
            f"No gate currently has a GO verdict ({n_go} GO / {n_nogo} NO-GO / "
            f"{n_unknown} UNKNOWN)."
        )
    if not has_enough_sessions:
        blocking_reasons.append(
            f"Shadow log has {n_sessions} realized session(s) recorded; "
            f"{required} are required before any live-capital decision."
        )

    return {
        "asof": asof,
        "cleared_for_live": bool(has_go_gate and has_enough_sessions),
        "blocking_reasons": blocking_reasons,
        "shadow": {
            "n_sessions": n_sessions,
            "required": required,
            "latest_decision": latest_decision,
            "reliability": reliability,
        },
        "gates_summary": {"go": n_go, "no_go": n_nogo, "unknown": n_unknown},
    }


def _health_payload() -> dict:
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbols_indexed": len(SYMBOL_INDEX),
        "uptime_s": round(time.time() - SERVER_START_TS, 3),
    }


# --------------------------------------------------------------------------
# JSON encoding -- converts numpy/pandas types and maps NaN/Inf -> null.
# --------------------------------------------------------------------------
def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize(v) for v in obj]
    if obj is pd.NaT:
        return None
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, pd.Timestamp):
        if obj.hour or obj.minute or obj.second or obj.microsecond:
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return _sanitize(obj.tolist())
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _dumps(payload) -> bytes:
    try:
        return json.dumps(_sanitize(payload), allow_nan=False, default=str).encode("utf-8")
    except (TypeError, ValueError):
        # Last-resort guard so a single unexpected type can never crash a response.
        safe = json.dumps({"error": "response was not JSON-serializable"})
        return safe.encode("utf-8")


def _safe_int(raw, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def _static_root() -> Path:
    return DIST_DIR if DIST_DIR.is_dir() else RUNS_DIR


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class ApiRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "TradingDashboardAPI/1.0"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # suppress noisy default access log

    # -- low-level senders ------------------------------------------------
    def _send_json(self, payload, status: int = 200):
        body = _dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_file(self, path: Path):
        try:
            body = path.read_bytes()
        except OSError as e:
            self._error(str(path), f"failed to read file: {e}", status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", _guess_content_type(path))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, endpoint: str, message: str, status: int = 500):
        print(f"[api_server] ERROR on {endpoint}: {message}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        self._send_json({"error": str(message), "endpoint": endpoint}, status=status)

    # -- routing ------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def _route(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self._dispatch_api(path, query)
            else:
                self._serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001 - one bad request must not kill the server
            self._error(path, f"{type(e).__name__}: {e}", status=500)

    # -- API dispatch ---------------------------------------------------
    def _dispatch_api(self, path: str, query: dict):
        try:
            if path == "/api/status":
                self._send_json(get_dashboard_data())

            elif path == "/api/leaderboard":
                data = get_dashboard_data()
                self._send_json({"asof": data["asof"], "leaderboard": data["leaderboard"]})

            elif path == "/api/gcp":
                self._send_json(get_all_gcp_resources())

            elif path == "/api/analyze":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                self._send_json(analyze_symbol_adhoc(sym_or_err))

            elif path == "/api/trigger_scan":
                data = get_dashboard_data()
                self._send_json({
                    "status": "ok",
                    "message": "Pre-market scan re-run successfully.",
                    "asof": data["asof"],
                })

            elif path == "/api/search":
                q = query.get("q", [""])[0]
                limit = _safe_int(query.get("limit", ["25"])[0], default=25, lo=1, hi=1000)
                self._send_json({"query": q, "limit": limit, "results": _search_symbols(q, limit)})

            elif path == "/api/trajectory":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                window = query.get("window", [DEFAULT_WINDOW])[0]
                payload, status = _trajectory_payload(sym_or_err, window)
                self._send_json(payload, status=status)

            elif path == "/api/compare":
                raw = query.get("symbols", [""])[0]
                syms: list[str] = []
                for tok in raw.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    ok, sym_or_err = _sanitize_symbol(tok)
                    if not ok:
                        self._send_json(
                            {"error": f"invalid symbol '{tok}': {sym_or_err}", "endpoint": path},
                            status=400,
                        )
                        return
                    if sym_or_err not in syms:
                        syms.append(sym_or_err)
                if not syms:
                    self._send_json({"error": "symbols query param is required", "endpoint": path},
                                     status=400)
                    return
                syms = syms[:8]
                window = query.get("window", [DEFAULT_WINDOW])[0]
                payload, status = _compare_payload(syms, window)
                self._send_json(payload, status=status)

            elif path == "/api/gates":
                self._send_json(_gates_payload())

            elif path == "/api/readiness":
                self._send_json(_readiness_payload())

            elif path == "/api/health":
                self._send_json(_health_payload())

            else:
                self._send_json({"error": "unknown endpoint", "endpoint": path}, status=404)

        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:  # noqa: BLE001 - per-handler safety net
            self._error(path, f"{type(e).__name__}: {e}", status=500)

    # -- static file serving ---------------------------------------------
    def _serve_static(self, url_path: str):
        root = _static_root().resolve()
        rel = url_path.lstrip("/")
        if rel == "":
            rel = "index.html"

        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send_json({"error": "forbidden path", "endpoint": url_path}, status=403)
            return

        if not candidate.exists() or candidate.is_dir():
            # SPA fallback: an unmatched path with no file extension serves index.html.
            if "." not in Path(rel).name:
                spa = root / "index.html"
                if spa.exists():
                    candidate = spa
                else:
                    legacy = root / "dashboard.html"
                    candidate = legacy if legacy.exists() else candidate
            if not candidate.exists() or candidate.is_dir():
                self._send_json({"error": "not found", "endpoint": url_path}, status=404)
                return

        self._send_file(candidate)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="JSON API server for quant trading dashboard.")
    parser.add_argument("--port", type=int, default=PORT, help="Port to listen on (default 8787)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    port = args.port
    server = ThreadedHTTPServer(("0.0.0.0", port), ApiRequestHandler)
    url = f"http://localhost:{port}"

    print(f"===========================================================")
    print(f"  QUANT DASHBOARD API SERVER")
    print(f"  Listening on: {url}")
    print(f"  Serving SPA from: {_static_root()}")
    print(f"===========================================================")

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    main()
