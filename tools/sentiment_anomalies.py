#!/usr/bin/env python3
"""Accuracy-first sentiment and anomaly feeds for the desk dashboard.

Design rules (non-negotiable):
  * Never invent a number. Missing inputs → quality "missing" and empty rows.
  * Every block carries asof, source, lag_note, and quality.
  * Scores are descriptive composites of *observed* structure (vol, short vol,
    COT, options, filings activity). They are NOT claimed alpha and must not be
    framed as trade signals without a pre-registered gate.
  * Network sources (CFTC COT, SEC EDGAR) cache to disk and degrade cleanly
    when offline or SSL-broken. Local sources always take precedence for
    price/volume/short-volume work.

Endpoints built here are pure functions returning JSON-serialisable dicts.
"""
from __future__ import annotations

import gzip
import json
import math
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths — match api_server / data_sources layout (repo root = parent of edge/)
# ---------------------------------------------------------------------------
_TOOLS = Path(__file__).resolve().parent
EDGE_DIR = _TOOLS.parent
ROOT = EDGE_DIR.parent
DATA_DIR = EDGE_DIR / "data"
RUNS_DIR = EDGE_DIR / "runs"
CACHE_DIR = DATA_DIR / "alt_data_cache"
COT_CACHE = CACHE_DIR / "cot_latest.json"
SEC_CACHE_DIR = CACHE_DIR / "sec_submissions"
FINRA_RAW = DATA_DIR / "finra_shortvol" / "raw"
VOL_COMPLEX = DATA_DIR / "vol_complex.csv"
DATA_CORE = DATA_DIR / "1d"
DATA_WIDE = DATA_DIR / "1d_wide"
OPTION_CHAINS = DATA_DIR / "option_chains"

# CFTC legacy futures-only COT (Socrata). Public, free, weekly (Tue as-of, Fri pub).
_CFTC_DATASET = "6dca-aqww"
_CFTC_BASE = f"https://publicreporting.cftc.gov/resource/{_CFTC_DATASET}.json"

# Markets we care about for equity-desk context. Exact CFTC names preferred;
# fallbacks use LIKE + highest open interest on the freshest report date.
_COT_MARKETS: list[dict[str, str]] = [
    {
        "id": "ES",
        "label": "E-mini S&P 500",
        "exact": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "like": "E-MINI S&P 500%",
        "proxy": "SPY/ES futures positioning",
    },
    {
        "id": "NQ",
        "label": "Nasdaq-100",
        "exact": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
        "like": "NASDAQ-100 CONSOLIDATED%",
        "proxy": "QQQ/NQ futures positioning",
    },
    {
        "id": "RTY",
        "label": "Russell 2000",
        "exact": "E-MINI RUSSELL 2000 INDEX - CHICAGO MERCANTILE EXCHANGE",
        "like": "%RUSSELL 2000%INDEX%",
        "proxy": "IWM/RTY futures positioning",
    },
    {
        "id": "VX",
        "label": "VIX futures",
        "exact": "VIX FUTURES - CBOE FUTURES EXCHANGE",
        "like": "VIX FUTURES%",
        "proxy": "Vol complex / hedge demand",
    },
    {
        "id": "ZN",
        "label": "UST 10Y note",
        "exact": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
        "like": "UST 10Y NOTE%",
        "proxy": "Rates / duration risk appetite",
    },
    {
        "id": "GC",
        "label": "Gold",
        "exact": "GOLD - COMMODITY EXCHANGE INC.",
        "like": "GOLD - COMMODITY EXCHANGE%",
        "proxy": "Safe-haven / risk-off proxy",
    },
    {
        "id": "BTC",
        "label": "Bitcoin",
        "exact": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
        "like": "BITCOIN - CHICAGO MERCANTILE%",
        "proxy": "Speculative risk appetite",
    },
]

# SEC fair-access policy requires a descriptive UA with contact. Bare bot strings get 403.
_SEC_UA = "Mozilla/5.0 (compatible; EdgeDesk/1.0; +https://localhost; contact: research@example.com)"
_HTTP_TIMEOUT_S = 25.0
_SEC_TICKER_CACHE = CACHE_DIR / "sec_company_tickers.json"

_CACHE_LOCK = threading.Lock()
_MEM: dict[str, tuple[float, Any]] = {}
_MEM_TTL_S = 300.0  # 5 min in-process cache for expensive scans


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _today_utc_naive() -> pd.Timestamp:
    """UTC calendar day as tz-naive Timestamp (for lag vs asof strings)."""
    return pd.Timestamp(datetime.now(timezone.utc).date())


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _round(x: Any, dp: int = 4) -> float | None:
    v = _finite(x)
    return None if v is None else round(v, dp)


def _zscore(series: pd.Series, value: float | None = None) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 8:
        return None
    mu = float(s.mean())
    sd = float(s.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    target = float(s.iloc[-1]) if value is None else float(value)
    return (target - mu) / sd


def _percentile_rank(series: pd.Series, value: float | None = None) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 8:
        return None
    target = float(s.iloc[-1]) if value is None else float(value)
    return float((s <= target).mean())


def _quality(ok: bool, *, stale: bool = False, degraded: bool = False, missing: bool = False) -> str:
    if missing:
        return "missing"
    if degraded:
        return "degraded"
    if stale:
        return "stale"
    if ok:
        return "ok"
    return "missing"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    hdrs = {"Accept": "application/json", "User-Agent": _SEC_UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mem_get(key: str) -> Any | None:
    with _CACHE_LOCK:
        hit = _MEM.get(key)
        if not hit:
            return None
        ts, payload = hit
        if time.time() - ts > _MEM_TTL_S:
            return None
        return payload


def _mem_set(key: str, payload: Any) -> Any:
    with _CACHE_LOCK:
        _MEM[key] = (time.time(), payload)
    return payload


# ---------------------------------------------------------------------------
# Vol complex → market risk sentiment
# ---------------------------------------------------------------------------
def _load_vol_complex() -> pd.DataFrame:
    if not VOL_COMPLEX.exists():
        raise FileNotFoundError(f"vol_complex missing: {VOL_COMPLEX}")
    df = pd.read_csv(VOL_COMPLEX)
    if "Date" not in df.columns:
        raise ValueError("vol_complex.csv missing Date column")
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


def _vol_sentiment_block() -> dict[str, Any]:
    """Map published vol complex into a descriptive risk-sentiment readout."""
    try:
        df = _load_vol_complex()
    except Exception as e:
        return {
            "quality": "missing",
            "asof": None,
            "source": str(VOL_COMPLEX.relative_to(EDGE_DIR)) if VOL_COMPLEX.exists() else "edge/data/vol_complex.csv",
            "lag_note": "Local vol complex unavailable.",
            "error": f"{type(e).__name__}: {e}",
            "readouts": [],
            "composite": None,
        }

    last = df.iloc[-1]
    asof = pd.Timestamp(last["Date"]).strftime("%Y-%m-%d")
    hist = df.tail(252)  # ~1y for ranks

    def rank(col: str) -> float | None:
        if col not in hist.columns:
            return None
        return _percentile_rank(hist[col])

    def z(col: str) -> float | None:
        if col not in hist.columns:
            return None
        return _zscore(hist[col])

    vix = _finite(last.get("VIX"))
    term = _finite(last.get("term_slope"))  # VIX/VIX3M style ratio in this file
    skew = _finite(last.get("SKEW") if "SKEW" in last.index else last.get("tail_risk"))
    vrp = _finite(last.get("vix_vrp"))
    short_stress = _finite(last.get("short_stress"))

    # Composite: higher = more risk-off / fear. Transparent linear mix of ranks.
    # term_slope > 1 means near-term stress > mid-term (inversion → stress).
    components: list[tuple[str, float | None, float]] = []
    r_vix = rank("VIX")
    r_term = rank("term_slope")
    r_skew = rank("SKEW") if "SKEW" in hist.columns else rank("tail_risk")
    r_vvix = rank("VVIX") if "VVIX" in hist.columns else None

    for name, r, w in (
        ("VIX level (1y pctile)", r_vix, 0.35),
        ("term structure stress", r_term, 0.30),
        ("tail / SKEW", r_skew, 0.20),
        ("VVIX", r_vvix, 0.15),
    ):
        components.append((name, r, w))

    w_sum = 0.0
    score = 0.0
    for _, r, w in components:
        if r is None:
            continue
        score += r * w
        w_sum += w
    composite = score / w_sum if w_sum > 0 else None

    # Map composite pctile → label. Descriptive only.
    if composite is None:
        label = "UNKNOWN"
    elif composite >= 0.80:
        label = "RISK_OFF"
    elif composite >= 0.60:
        label = "CAUTIOUS"
    elif composite <= 0.25:
        label = "RISK_ON"
    else:
        label = "NEUTRAL"

    # Staleness: vol file more than 5 calendar days behind "today" is stale.
    lag_days = (_today_utc_naive() - pd.Timestamp(asof)).days
    stale = lag_days > 5

    readouts = [
        {"key": "VIX", "value": _round(vix, 2), "z_1y": _round(z("VIX"), 2), "pctile_1y": _round(r_vix, 3)},
        {
            "key": "term_slope",
            "value": _round(term, 4),
            "z_1y": _round(z("term_slope"), 2),
            "pctile_1y": _round(r_term, 3),
            "note": "VIX/VIX3M-style ratio in vol_complex; >1 near-term stress",
        },
        {
            "key": "SKEW_or_tail",
            "value": _round(skew, 2),
            "z_1y": _round(z("SKEW") if "SKEW" in hist.columns else z("tail_risk"), 2),
            "pctile_1y": _round(r_skew, 3),
        },
        {"key": "vix_vrp", "value": _round(vrp, 3), "z_1y": _round(z("vix_vrp"), 2), "pctile_1y": _round(rank("vix_vrp"), 3)},
        {
            "key": "short_stress",
            "value": _round(short_stress, 4),
            "z_1y": _round(z("short_stress"), 2),
            "pctile_1y": _round(rank("short_stress"), 3),
        },
        {
            "key": "SPY_ret_5d",
            "value": _round(last.get("spy_ret_5d"), 4),
            "unit": "fraction",
        },
        {
            "key": "QQQ_ret_5d",
            "value": _round(last.get("qqq_ret_5d"), 4),
            "unit": "fraction",
        },
    ]

    return {
        "quality": _quality(True, stale=stale),
        "asof": asof,
        "source": "edge/data/vol_complex.csv",
        "lag_note": (
            f"Local close as-of {asof} ({lag_days}d lag vs UTC today). "
            "Composite is a descriptive mix of 1y percentile ranks — not a trade signal."
        ),
        "composite_risk_pctile": _round(composite, 3),
        "composite_label": label,
        "readouts": readouts,
        "components": [
            {"name": n, "pctile": _round(r, 3), "weight": w} for n, r, w in components if r is not None
        ],
    }


# ---------------------------------------------------------------------------
# COT (CFTC)
# ---------------------------------------------------------------------------
def _cot_history(market_exact: str, *, weeks: int = 52) -> list[dict[str, Any]]:
    where = urllib.parse.quote(f"market_and_exchange_names='{market_exact}'")
    url = (
        f"{_CFTC_BASE}?$limit={weeks}&$order=report_date_as_yyyy_mm_dd%20DESC"
        f"&$where={where}"
    )
    rows = _http_json(url)
    return rows if isinstance(rows, list) else []


def _cot_resolve_market(spec: dict[str, str]) -> tuple[str | None, list[dict[str, Any]], str | None]:
    """Return (resolved_name, history_rows, error)."""
    try:
        hist = _cot_history(spec["exact"])
        if hist:
            # Reject stale series that stopped updating years ago.
            latest = str(hist[0].get("report_date_as_yyyy_mm_dd") or "")[:10]
            if latest and latest >= "2025-01-01":
                return spec["exact"], hist, None
        # Fallback LIKE search on recent rows, pick highest OI freshest name.
        like = spec["like"].replace("'", "''")
        where = urllib.parse.quote(
            f"upper(market_and_exchange_names) like '{like.upper()}' "
            f"AND report_date_as_yyyy_mm_dd > '2025-01-01T00:00:00.000'"
        )
        url = (
            f"{_CFTC_BASE}?$limit=40&$order=report_date_as_yyyy_mm_dd%20DESC"
            f"&$where={where}"
        )
        rows = _http_json(url)
        if not rows:
            return None, [], "no matching COT market rows"
        # Group by market name → freshest date, then pick max OI among freshest.
        by_name: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row.get("market_and_exchange_names") or "")
            d = str(row.get("report_date_as_yyyy_mm_dd") or "")[:10]
            oi = float(row.get("open_interest_all") or 0)
            prev = by_name.get(name)
            if prev is None or d > prev["_d"] or (d == prev["_d"] and oi > prev["_oi"]):
                by_name[name] = {**row, "_d": d, "_oi": oi}
        if not by_name:
            return None, [], "no usable COT market after filter"
        best_name = max(by_name.values(), key=lambda r: (r["_d"], r["_oi"]))["market_and_exchange_names"]
        hist = _cot_history(best_name)
        return best_name, hist, None
    except Exception as e:
        return None, [], f"{type(e).__name__}: {e}"


def _cot_row_metrics(row: dict[str, Any]) -> dict[str, float | None]:
    nc_long = _finite(row.get("noncomm_positions_long_all"))
    nc_short = _finite(row.get("noncomm_positions_short_all"))
    c_long = _finite(row.get("comm_positions_long_all"))
    c_short = _finite(row.get("comm_positions_short_all"))
    oi = _finite(row.get("open_interest_all"))
    nc_net = None if nc_long is None or nc_short is None else nc_long - nc_short
    c_net = None if c_long is None or c_short is None else c_long - c_short
    nc_pct_oi = None
    if nc_net is not None and oi and oi > 0:
        nc_pct_oi = 100.0 * nc_net / oi
    return {
        "noncomm_long": nc_long,
        "noncomm_short": nc_short,
        "noncomm_net": nc_net,
        "comm_long": c_long,
        "comm_short": c_short,
        "comm_net": c_net,
        "open_interest": oi,
        "noncomm_net_pct_oi": nc_pct_oi,
    }


def _build_cot_block(*, force_refresh: bool = False) -> dict[str, Any]:
    cached = None if force_refresh else _mem_get("cot_block")
    if cached is not None:
        return cached

    # Disk cache fallback when network fails.
    disk: dict[str, Any] | None = None
    if COT_CACHE.exists():
        try:
            disk = json.loads(COT_CACHE.read_text())
        except Exception:
            disk = None

    markets_out: list[dict[str, Any]] = []
    errors: list[str] = []
    freshest: str | None = None
    any_live = False

    for spec in _COT_MARKETS:
        name, hist, err = _cot_resolve_market(spec)
        if err or not hist:
            errors.append(f"{spec['id']}: {err or 'empty'}")
            # Try disk cache per-market.
            if disk:
                for m in disk.get("markets") or []:
                    if m.get("id") == spec["id"]:
                        m = dict(m)
                        m["quality"] = "stale"
                        m["lag_note"] = (
                            "Served from disk cache — live CFTC fetch failed for this market."
                        )
                        markets_out.append(m)
                        break
            continue

        any_live = True
        # Chronological for z-score.
        hist_sorted = sorted(hist, key=lambda r: str(r.get("report_date_as_yyyy_mm_dd") or ""))
        nets = []
        for r in hist_sorted:
            m = _cot_row_metrics(r)
            if m["noncomm_net"] is not None:
                nets.append(m["noncomm_net"])
        latest = hist_sorted[-1]
        metrics = _cot_row_metrics(latest)
        asof = str(latest.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if asof and (freshest is None or asof > freshest):
            freshest = asof
        net_series = pd.Series(nets, dtype=float)
        z = _zscore(net_series) if len(net_series) else None
        pctile = _percentile_rank(net_series) if len(net_series) else None

        # Positioning bias label from non-commercial net z-score.
        if z is None:
            bias = "UNKNOWN"
        elif z >= 1.25:
            bias = "SPEC_LONG_EXTREME"
        elif z >= 0.5:
            bias = "SPEC_LONG"
        elif z <= -1.25:
            bias = "SPEC_SHORT_EXTREME"
        elif z <= -0.5:
            bias = "SPEC_SHORT"
        else:
            bias = "BALANCED"

        markets_out.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "cftc_market": name,
                "proxy": spec["proxy"],
                "asof": asof,
                "quality": "ok",
                "noncomm_net": _round(metrics["noncomm_net"], 0),
                "comm_net": _round(metrics["comm_net"], 0),
                "open_interest": _round(metrics["open_interest"], 0),
                "noncomm_net_pct_oi": _round(metrics["noncomm_net_pct_oi"], 2),
                "noncomm_net_z_1y": _round(z, 2),
                "noncomm_net_pctile_1y": _round(pctile, 3),
                "bias": bias,
                "history_weeks": len(nets),
                "source": f"CFTC {_CFTC_DATASET} (legacy futures COT)",
                "lag_note": (
                    "CFTC COT is weekly; typically published Friday for Tuesday "
                    "positions. Spec (non-commercial) net is the common risk-appetite "
                    "read — not a timing signal by itself."
                ),
            }
        )

    if any_live and markets_out:
        payload = {
            "quality": "ok",
            "asof": freshest,
            "source": f"CFTC publicreporting {_CFTC_DATASET}",
            "lag_note": (
                "Weekly Commitment of Traders. Futures positioning, not single-stock "
                "hedge-fund books. Extreme non-commercial z-scores mark crowded "
                "positioning — useful context, not entries."
            ),
            "markets": markets_out,
            "errors": errors,
            "fetched_at": _utc_now_iso(),
        }
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            COT_CACHE.write_text(json.dumps(payload, indent=2))
        except Exception:
            pass
        return _mem_set("cot_block", payload)

    if disk and disk.get("markets"):
        disk = dict(disk)
        disk["quality"] = "stale"
        disk["errors"] = errors + list(disk.get("errors") or [])
        disk["lag_note"] = (
            "Live CFTC fetch failed; serving last good disk cache. "
            + str(disk.get("lag_note") or "")
        )
        return _mem_set("cot_block", disk)

    return _mem_set(
        "cot_block",
        {
            "quality": "missing",
            "asof": None,
            "source": f"CFTC publicreporting {_CFTC_DATASET}",
            "lag_note": "Could not fetch COT and no disk cache available.",
            "markets": [],
            "errors": errors,
            "fetched_at": _utc_now_iso(),
        },
    )


# ---------------------------------------------------------------------------
# FINRA short volume (local raw mirror)
# ---------------------------------------------------------------------------
def _finra_files() -> list[Path]:
    if not FINRA_RAW.is_dir():
        return []
    return sorted(FINRA_RAW.glob("CNMSshvol*.txt.gz"))


def _read_finra_day(path: Path, symbols: set[str] | None = None) -> pd.DataFrame:
    with gzip.open(path, "rt") as f:
        df = pd.read_csv(f, sep="|")
    # Normalise columns.
    cols = {c.lower(): c for c in df.columns}
    # Expected: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
    rename = {}
    for want in ("date", "symbol", "shortvolume", "totalvolume"):
        for c in df.columns:
            if c.lower().replace("_", "") == want:
                rename[c] = want
                break
    df = df.rename(columns=rename)
    need = {"date", "symbol", "shortvolume", "totalvolume"}
    if not need.issubset(set(df.columns)):
        raise ValueError(f"unexpected FINRA schema in {path.name}: {list(df.columns)}")
    df["symbol"] = df["symbol"].astype(str).str.upper()
    if symbols is not None:
        df = df[df["symbol"].isin(symbols)]
    df["shortvolume"] = pd.to_numeric(df["shortvolume"], errors="coerce")
    df["totalvolume"] = pd.to_numeric(df["totalvolume"], errors="coerce")
    df = df.dropna(subset=["shortvolume", "totalvolume"])
    df = df[df["totalvolume"] > 0]
    df["short_ratio"] = df["shortvolume"] / df["totalvolume"]
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    # Aggregate multi-market rows if present.
    g = (
        df.groupby(["date", "symbol"], as_index=False)[["shortvolume", "totalvolume"]]
        .sum()
    )
    g["short_ratio"] = g["shortvolume"] / g["totalvolume"]
    return g


def _finra_short_pressure_block(universe: list[str], *, lookback_days: int = 40) -> dict[str, Any]:
    cached = _mem_get(f"finra_short:{lookback_days}:{len(universe)}")
    if cached is not None:
        return cached

    files = _finra_files()
    if not files:
        return {
            "quality": "missing",
            "asof": None,
            "source": "edge/data/finra_shortvol/raw",
            "lag_note": "No FINRA CNMS short-volume mirror files on disk.",
            "rows": [],
            "market_median_short_ratio": None,
        }

    use = files[-lookback_days:]
    sym_set = set(universe)
    frames: list[pd.DataFrame] = []
    for path in use:
        try:
            frames.append(_read_finra_day(path, sym_set))
        except Exception:
            continue
    if not frames:
        return {
            "quality": "missing",
            "asof": None,
            "source": "edge/data/finra_shortvol/raw",
            "lag_note": "FINRA files present but unreadable/empty for universe.",
            "rows": [],
            "market_median_short_ratio": None,
        }

    panel = pd.concat(frames, ignore_index=True)
    asof = panel["date"].max()
    asof_s = pd.Timestamp(asof).strftime("%Y-%m-%d") if pd.notna(asof) else None
    latest = panel[panel["date"] == asof].copy()
    if latest.empty:
        return {
            "quality": "missing",
            "asof": asof_s,
            "source": "edge/data/finra_shortvol/raw (CNMSshvol)",
            "lag_note": "Panel loaded but latest day empty.",
            "rows": [],
            "market_median_short_ratio": None,
        }

    # History stats per symbol for z-score.
    hist_stats = (
        panel.groupby("symbol")["short_ratio"]
        .agg(["mean", "std", "count"])
        .rename(columns={"mean": "mu", "std": "sd", "count": "n"})
    )
    latest = latest.merge(hist_stats, left_on="symbol", right_index=True, how="left")
    latest["z"] = np.where(
        (latest["sd"].fillna(0) > 1e-9) & (latest["n"] >= 8),
        (latest["short_ratio"] - latest["mu"]) / latest["sd"],
        np.nan,
    )
    market_med = float(latest["short_ratio"].median())
    rows = []
    for _, r in latest.sort_values("z", ascending=False, na_position="last").iterrows():
        rows.append(
            {
                "symbol": str(r["symbol"]),
                "short_ratio": _round(r["short_ratio"], 4),
                "short_volume": _round(r["shortvolume"], 0),
                "total_volume": _round(r["totalvolume"], 0),
                "z_vs_own_hist": _round(r["z"], 2),
                "hist_days": int(r["n"]) if pd.notna(r["n"]) else 0,
            }
        )

    lag_days = (_today_utc_naive() - pd.Timestamp(asof_s)).days if asof_s else None
    stale = bool(lag_days is not None and lag_days > 5)
    payload = {
        "quality": _quality(True, stale=stale),
        "asof": asof_s,
        "source": "edge/data/finra_shortvol/raw (FINRA CNMS short volume)",
        "lag_note": (
            f"FINRA short *volume* (not short interest). T+0/T+1 exchange reporting. "
            f"asof={asof_s}"
            + (f", lag={lag_days}d" if lag_days is not None else "")
            + ". High short ratio is bearish *flow* that day — not locate borrow SI."
        ),
        "market_median_short_ratio": _round(market_med, 4),
        "n_symbols": len(rows),
        "lookback_days_used": len(use),
        "rows": rows,
    }
    return _mem_set(f"finra_short:{lookback_days}:{len(universe)}", payload)


# ---------------------------------------------------------------------------
# Options put/call sentiment from local chains
# ---------------------------------------------------------------------------
def _latest_option_chain_dir() -> Path | None:
    if not OPTION_CHAINS.is_dir():
        return None
    dirs = sorted(
        [p for p in OPTION_CHAINS.iterdir() if p.is_dir() and p.name.startswith("date=")]
    )
    return dirs[-1] if dirs else None


def _options_sentiment_block(limit: int = 40) -> dict[str, Any]:
    d = _latest_option_chain_dir()
    if d is None:
        return {
            "quality": "missing",
            "asof": None,
            "source": "edge/data/option_chains",
            "lag_note": "No local option chain snapshots.",
            "rows": [],
            "market_pc_oi": None,
        }
    asof = d.name.replace("date=", "")
    rows_out: list[dict[str, Any]] = []
    pc_vals: list[float] = []
    for path in sorted(d.glob("*.parquet")):
        try:
            df = pd.read_parquet(path, columns=["right", "openInterest", "volume", "strike", "spot", "dte"])
        except Exception:
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
        if df.empty or "right" not in df.columns:
            continue
        right = df["right"].astype(str).str.upper().str[0]
        oi = pd.to_numeric(df.get("openInterest"), errors="coerce").fillna(0.0)
        vol = pd.to_numeric(df.get("volume"), errors="coerce").fillna(0.0)
        call_oi = float(oi[right == "C"].sum())
        put_oi = float(oi[right == "P"].sum())
        call_vol = float(vol[right == "C"].sum())
        put_vol = float(vol[right == "P"].sum())
        if call_oi <= 0 and put_oi <= 0:
            continue
        pc_oi = put_oi / call_oi if call_oi > 0 else None
        pc_vol = put_vol / call_vol if call_vol > 0 else None
        if pc_oi is not None:
            pc_vals.append(pc_oi)
        spot = _finite(df["spot"].iloc[0]) if "spot" in df.columns else None
        rows_out.append(
            {
                "symbol": path.stem.upper(),
                "put_oi": _round(put_oi, 0),
                "call_oi": _round(call_oi, 0),
                "pc_oi": _round(pc_oi, 3),
                "pc_volume": _round(pc_vol, 3),
                "spot": _round(spot, 2),
            }
        )

    rows_out.sort(key=lambda r: (r.get("pc_oi") is None, -(r.get("pc_oi") or 0)))
    lag_days = (_today_utc_naive() - pd.Timestamp(asof)).days
    stale = lag_days > 5
    return {
        "quality": _quality(bool(rows_out), stale=stale, missing=not rows_out),
        "asof": asof,
        "source": f"edge/data/option_chains/{d.name}",
        "lag_note": (
            f"Local chain snapshot {asof}. Put/call OI is a *positioning* proxy; "
            "elevated PC can mean hedge demand or outright bearish bets — ambiguous alone."
        ),
        "market_pc_oi": _round(float(np.median(pc_vals)), 3) if pc_vals else None,
        "rows": rows_out[:limit],
        "n_underlyings": len(rows_out),
    }


# ---------------------------------------------------------------------------
# SEC EDGAR — filings activity (Form 4 / 8-K / 10-Q), not live HF books
# ---------------------------------------------------------------------------
def _sec_ticker_map() -> dict[str, dict[str, Any]]:
    cached = _mem_get("sec_ticker_map")
    if cached is not None:
        return cached

    def _parse(data: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if isinstance(data, dict):
            for row in data.values():
                if not isinstance(row, dict):
                    continue
                t = str(row.get("ticker") or "").upper()
                if not t:
                    continue
                out[t] = {
                    "cik": int(row["cik_str"]),
                    "cik10": str(row["cik_str"]).zfill(10),
                    "title": row.get("title"),
                }
        return out

    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        data = _http_json(url, headers={"User-Agent": _SEC_UA})
        out = _parse(data)
        if out:
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                _SEC_TICKER_CACHE.write_text(json.dumps(data))
            except Exception:
                pass
            return _mem_set("sec_ticker_map", out)
    except Exception:
        pass

    # Disk fallback so a temporary SEC 403 does not blank the panel.
    if _SEC_TICKER_CACHE.exists():
        try:
            data = json.loads(_SEC_TICKER_CACHE.read_text())
            out = _parse(data)
            if out:
                return _mem_set("sec_ticker_map", out)
        except Exception:
            pass
    raise RuntimeError("SEC company_tickers.json unavailable (network + no disk cache)")


def _sec_submissions(cik10: str) -> dict[str, Any]:
    SEC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = SEC_CACHE_DIR / f"CIK{cik10}.json"
    # Prefer fresh network, fall back to cache ≤7d.
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
        data = _http_json(url, headers={"User-Agent": _SEC_UA})
        cache_path.write_text(json.dumps(data))
        return data
    except Exception:
        if cache_path.exists():
            age_h = (time.time() - cache_path.stat().st_mtime) / 3600.0
            data = json.loads(cache_path.read_text())
            data["_cache_age_h"] = age_h
            return data
        raise


def sec_filings_for_symbol(symbol: str) -> dict[str, Any]:
    """Recent SEC filing activity for one issuer.

    Important accuracy notes returned in payload:
      * Form 4 = *insider* transactions (officers/directors), not hedge funds.
      * 13F-HR is filed by *managers* (funds), not by the portfolio company —
        so a stock ticker's submissions almost never contain 13F holdings of
        itself. True HF ownership is reconstructed from all managers' 13Fs
        with ~45 day lag after quarter-end. We do not fabricate that book.
    """
    sym = symbol.strip().upper()
    try:
        tmap = _sec_ticker_map()
    except Exception as e:
        return {
            "symbol": sym,
            "quality": "missing",
            "asof": None,
            "source": "SEC EDGAR data.sec.gov",
            "lag_note": "SEC ticker map unavailable.",
            "error": f"{type(e).__name__}: {e}",
            "filings": [],
            "counts_90d": {},
        }

    meta = tmap.get(sym)
    if not meta:
        return {
            "symbol": sym,
            "quality": "missing",
            "asof": None,
            "source": "SEC EDGAR data.sec.gov",
            "lag_note": "Ticker not found in SEC company_tickers.json (may be ETF/ADR).",
            "filings": [],
            "counts_90d": {},
            "cik": None,
        }

    try:
        sub = _sec_submissions(meta["cik10"])
    except Exception as e:
        return {
            "symbol": sym,
            "quality": "missing",
            "asof": None,
            "source": "SEC EDGAR data.sec.gov/submissions",
            "lag_note": "Submissions fetch failed.",
            "error": f"{type(e).__name__}: {e}",
            "filings": [],
            "counts_90d": {},
            "cik": meta["cik"],
            "name": meta.get("title"),
        }

    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primaries = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []

    cutoff = (_today_utc_naive() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    watch = {"4", "4/A", "8-K", "8-K/A", "10-Q", "10-K", "10-Q/A", "10-K/A", "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A", "144"}
    filings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for i, form in enumerate(forms):
        if i >= len(dates):
            break
        d = dates[i]
        f = str(form)
        if d >= cutoff:
            counts[f] = counts.get(f, 0) + 1
        if f not in watch:
            continue
        if d < cutoff and len(filings) >= 25:
            continue
        acc = accessions[i] if i < len(accessions) else ""
        acc_nodash = acc.replace("-", "")
        primary = primaries[i] if i < len(primaries) else ""
        desc = descriptions[i] if i < len(descriptions) else ""
        url = None
        if acc_nodash and primary:
            url = f"https://www.sec.gov/Archives/edgar/data/{meta['cik']}/{acc_nodash}/{primary}"
        filings.append(
            {
                "form": f,
                "filed": d,
                "description": desc,
                "accession": acc,
                "url": url,
            }
        )
        if len(filings) >= 40:
            break

    # Keep newest first (SEC already is, but be safe).
    filings.sort(key=lambda x: x.get("filed") or "", reverse=True)
    cache_age = sub.get("_cache_age_h")
    quality = "stale" if cache_age and cache_age > 24 else "ok"

    return {
        "symbol": sym,
        "name": meta.get("title") or sub.get("name"),
        "cik": meta["cik"],
        "quality": quality,
        "asof": filings[0]["filed"] if filings else None,
        "source": f"SEC EDGAR submissions CIK{meta['cik10']}",
        "lag_note": (
            "Form 4 = company insiders (not hedge funds). "
            "13F institutional ownership is reconstructed from *manager* filings "
            "with ~45 calendar days lag after quarter-end and is not fabricated here. "
            "SC 13D/G = large beneficial ownership disclosures when available."
        ),
        "counts_90d": counts,
        "filings": filings[:30],
        "edgar_company_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={meta['cik10']}&owner=include&count=40",
        "from_cache_hours": _round(cache_age, 1) if cache_age else None,
    }


def _sec_activity_scan(symbols: list[str], *, max_symbols: int = 24) -> dict[str, Any]:
    """Scan a small universe for elevated Form 4 / 8-K activity (rate-limit safe)."""
    cached = _mem_get(f"sec_scan:{max_symbols}")
    if cached is not None:
        return cached

    out_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for sym in symbols[:max_symbols]:
        try:
            # Light path: use cache-friendly submissions.
            payload = sec_filings_for_symbol(sym)
            if payload.get("quality") == "missing":
                continue
            c = payload.get("counts_90d") or {}
            form4 = int(c.get("4", 0) + c.get("4/A", 0))
            eightk = int(c.get("8-K", 0) + c.get("8-K/A", 0))
            sc13 = sum(int(c.get(k, 0)) for k in c if str(k).startswith("SC 13"))
            if form4 + eightk + sc13 == 0:
                continue
            out_rows.append(
                {
                    "symbol": sym,
                    "name": payload.get("name"),
                    "form4_90d": form4,
                    "eightk_90d": eightk,
                    "sc13_90d": sc13,
                    "latest_filing": (payload.get("filings") or [{}])[0].get("filed"),
                    "latest_form": (payload.get("filings") or [{}])[0].get("form"),
                    "quality": payload.get("quality"),
                }
            )
            # Be polite to SEC.
            time.sleep(0.12)
        except Exception as e:
            errors.append(f"{sym}: {type(e).__name__}")
            continue

    out_rows.sort(key=lambda r: (r.get("form4_90d", 0) + r.get("eightk_90d", 0)), reverse=True)
    payload = {
        "quality": _quality(bool(out_rows), degraded=bool(errors), missing=not out_rows),
        "asof": _utc_now_iso()[:10],
        "source": "SEC EDGAR data.sec.gov/submissions",
        "lag_note": (
            "Filing *counts* only (activity intensity). Not position sizes. "
            "Hedge-fund 13F holdings are intentionally omitted rather than guessed."
        ),
        "rows": out_rows,
        "errors": errors[:12],
        "n_scanned": min(len(symbols), max_symbols),
    }
    return _mem_set(f"sec_scan:{max_symbols}", payload)


# ---------------------------------------------------------------------------
# Price/volume anomalies (local bars)
# ---------------------------------------------------------------------------
def _load_ohlcv(symbol: str) -> pd.DataFrame | None:
    for base in (DATA_CORE, DATA_WIDE):
        path = base / f"{symbol}.parquet"
        if path.exists():
            try:
                df = pd.read_parquet(path)
                df = df.sort_index()
                return df
            except Exception:
                return None
    return None


def _core_universe() -> list[str]:
    if DATA_CORE.is_dir():
        return sorted(p.stem.upper() for p in DATA_CORE.glob("*.parquet"))
    if DATA_WIDE.is_dir():
        return sorted(p.stem.upper() for p in DATA_WIDE.glob("*.parquet"))[:80]
    return []


def _price_anomalies(universe: list[str], *, limit: int = 40) -> dict[str, Any]:
    cached = _mem_get(f"px_anom:{len(universe)}")
    if cached is not None:
        return cached

    rows: list[dict[str, Any]] = []
    asof_dates: list[str] = []
    for sym in universe:
        df = _load_ohlcv(sym)
        if df is None or len(df) < 30:
            continue
        close = pd.to_numeric(df["close"], errors="coerce")
        vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else None
        ret = close.pct_change()
        last_date = df.index[-1]
        asof_dates.append(pd.Timestamp(last_date).strftime("%Y-%m-%d"))
        r1 = _finite(ret.iloc[-1])
        r5 = _finite(close.iloc[-1] / close.iloc[-6] - 1.0) if len(close) >= 6 else None
        # 60d return z of 1d returns
        z1 = _zscore(ret.tail(61).dropna())
        # Volume spike vs 20d median
        vol_z = None
        vol_ratio = None
        if vol is not None and len(vol.dropna()) >= 25:
            v20 = float(vol.tail(21).iloc[:-1].median())
            v_last = _finite(vol.iloc[-1])
            if v_last is not None and v20 > 0:
                vol_ratio = v_last / v20
                vol_z = _zscore(vol.tail(60).dropna())
        # Gap proxy: open vs prior close if available
        gap = None
        if "open" in df.columns and len(df) >= 2:
            o = _finite(df["open"].iloc[-1])
            pc = _finite(close.iloc[-2])
            if o is not None and pc and pc > 0:
                gap = o / pc - 1.0

        severity = 0.0
        n_comp = 0
        for v in (z1, vol_z):
            if v is not None:
                severity += abs(v)
                n_comp += 1
        if r5 is not None:
            severity += min(abs(r5) / 0.05, 3.0)  # 5% move ~ 1 unit
            n_comp += 1
        score = severity / max(n_comp, 1)

        flags: list[str] = []
        if z1 is not None and abs(z1) >= 2.5:
            flags.append("RET_1D_EXTREME")
        if r5 is not None and abs(r5) >= 0.08:
            flags.append("RET_5D_LARGE")
        if vol_ratio is not None and vol_ratio >= 2.5:
            flags.append("VOLUME_SPIKE")
        if gap is not None and abs(gap) >= 0.03:
            flags.append("GAP")

        if not flags and (z1 is None or abs(z1) < 1.8):
            continue

        rows.append(
            {
                "symbol": sym,
                "asof": pd.Timestamp(last_date).strftime("%Y-%m-%d"),
                "last": _round(close.iloc[-1], 2),
                "ret_1d": _round(r1, 4),
                "ret_5d": _round(r5, 4),
                "ret_1d_z_60d": _round(z1, 2),
                "volume_vs_20d_med": _round(vol_ratio, 2),
                "volume_z_60d": _round(vol_z, 2),
                "gap_open": _round(gap, 4),
                "flags": flags,
                "severity": _round(score, 2),
                "source": "local OHLCV parquet",
            }
        )

    rows.sort(key=lambda r: r.get("severity") or 0, reverse=True)
    asof = max(asof_dates) if asof_dates else None
    lag_days = (_today_utc_naive() - pd.Timestamp(asof)).days if asof else None
    payload = {
        "quality": _quality(bool(rows), stale=bool(lag_days and lag_days > 5), missing=not rows),
        "asof": asof,
        "source": "edge/data/1d (+1d_wide fallback) OHLCV",
        "lag_note": (
            "Statistical outliers vs each name's own recent history. "
            "Cross-sectional extremes, not a forecast. Flags only fire on measured thresholds."
        ),
        "rows": rows[:limit],
        "n_scanned": len(universe),
        "n_flagged": len(rows),
    }
    return _mem_set(f"px_anom:{len(universe)}", payload)


# ---------------------------------------------------------------------------
# Public aggregates
# ---------------------------------------------------------------------------
def build_sentiment_payload(*, symbol: str | None = None) -> dict[str, Any]:
    """Desk-level sentiment page payload (+ optional symbol SEC deep-dive)."""
    universe = _core_universe()
    vol = _vol_sentiment_block()
    cot = _build_cot_block()
    finra = _finra_short_pressure_block(universe)
    opt = _options_sentiment_block()
    sector_note = {
        "quality": "ok",
        "source": "/api/status → sector_flow (daily plays adapter)",
        "lag_note": (
            "Sector flow lives on the Sectors tab / status feed. Sentiment tab "
            "does not recompute it — avoid double-counting the same residual."
        ),
    }

    # Honest composite: average available standardized pieces.
    pieces: list[tuple[str, float]] = []
    if vol.get("composite_risk_pctile") is not None:
        pieces.append(("vol_risk_pctile", float(vol["composite_risk_pctile"])))
    # COT: average absolute extreme-ness of ES/NQ if present.
    cot_zs = [
        abs(m["noncomm_net_z_1y"])
        for m in (cot.get("markets") or [])
        if m.get("id") in {"ES", "NQ", "VX"} and m.get("noncomm_net_z_1y") is not None
    ]
    if cot_zs:
        # Map mean |z| into 0-1-ish stress proxy via 1-exp.
        stress = 1.0 - math.exp(-float(np.mean(cot_zs)) / 1.5)
        pieces.append(("cot_crowding", stress))
    if finra.get("market_median_short_ratio") is not None:
        # Typical short ratio ~0.4-0.5; map 0.35→low, 0.6→high roughly.
        sr = float(finra["market_median_short_ratio"])
        pieces.append(("finra_short_ratio", min(max((sr - 0.30) / 0.40, 0.0), 1.0)))
    if opt.get("market_pc_oi") is not None:
        pc = float(opt["market_pc_oi"])
        pieces.append(("options_pc_oi", min(max((pc - 0.6) / 1.0, 0.0), 1.0)))

    if pieces:
        composite = float(np.mean([v for _, v in pieces]))
        if composite >= 0.70:
            label = "DEFENSIVE"
        elif composite >= 0.55:
            label = "CAUTIOUS"
        elif composite <= 0.35:
            label = "RISK_SEEKING"
        else:
            label = "MIXED"
    else:
        composite = None
        label = "UNKNOWN"

    sources_ok = sum(
        1
        for b in (vol, cot, finra, opt)
        if b.get("quality") in {"ok", "stale", "degraded"}
    )

    payload: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "disclaimer": (
            "Descriptive market-structure sentiment only. Not a GO-gated alpha model. "
            "Hedge-fund line-item positions are not available in real time; 13F is "
            "quarterly with ~45-day lag and is not reverse-engineered here."
        ),
        "composite": {
            "score": _round(composite, 3),
            "label": label,
            "inputs": [{"name": n, "value": _round(v, 3)} for n, v in pieces],
            "quality": _quality(sources_ok >= 2, degraded=sources_ok == 1, missing=sources_ok == 0),
        },
        "vol": vol,
        "cot": cot,
        "finra_short": {
            **{k: v for k, v in finra.items() if k != "rows"},
            "top_short_pressure": sorted(
                [r for r in (finra.get("rows") or []) if r.get("z_vs_own_hist") is not None],
                key=lambda r: r.get("z_vs_own_hist") or -999,
                reverse=True,
            )[:15],
            "low_short_pressure": sorted(
                [r for r in (finra.get("rows") or []) if r.get("z_vs_own_hist") is not None],
                key=lambda r: r.get("z_vs_own_hist") or 999,
            )[:10],
        },
        "options": opt,
        "sector_flow_pointer": sector_note,
        "accuracy": {
            "rule": "missing > fabricated",
            "sources_live": sources_ok,
            "notes": [
                "COT = futures specs/commercials (weekly).",
                "FINRA = short volume ratio, not short interest.",
                "Options PC from last local chain snapshot only.",
                "SEC Form 4 = insiders; not HF 13F books.",
            ],
        },
    }

    if symbol:
        payload["symbol_filings"] = sec_filings_for_symbol(symbol)

    return payload


def build_anomalies_payload(*, limit: int = 40, symbol: str | None = None) -> dict[str, Any]:
    universe = _core_universe()
    px = _price_anomalies(universe, limit=limit)
    finra = _finra_short_pressure_block(universe)
    opt = _options_sentiment_block(limit=limit)
    # SEC activity on a short liquid subset (rate limits).
    seed = [s for s in ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ"] if s in set(universe)]
    seed += [s for s in universe if s not in set(seed)][:14]
    sec = _sec_activity_scan(seed, max_symbols=20)

    short_ext = []
    for r in finra.get("rows") or []:
        z = r.get("z_vs_own_hist")
        if z is None or abs(z) < 2.0:
            continue
        short_ext.append(
            {
                "symbol": r["symbol"],
                "kind": "FINRA_SHORT_RATIO_Z",
                "value": r.get("short_ratio"),
                "z": z,
                "asof": finra.get("asof"),
                "source": finra.get("source"),
                "note": (
                    "Short volume / total volume elevated vs own history"
                    if z > 0
                    else "Short volume / total volume suppressed vs own history"
                ),
            }
        )
        if len(short_ext) >= limit:
            break

    opt_ext = [
        {
            "symbol": r["symbol"],
            "kind": "OPTIONS_PC_OI",
            "value": r.get("pc_oi"),
            "asof": opt.get("asof"),
            "source": opt.get("source"),
            "note": "Elevated put/call open-interest ratio in local snapshot",
        }
        for r in (opt.get("rows") or [])
        if r.get("pc_oi") is not None and r["pc_oi"] >= 1.3
    ][:limit]

    # Unified feed sorted by rough severity.
    unified: list[dict[str, Any]] = []
    for r in px.get("rows") or []:
        unified.append(
            {
                "symbol": r["symbol"],
                "kind": "PRICE_VOLUME",
                "severity": r.get("severity"),
                "asof": r.get("asof"),
                "flags": r.get("flags"),
                "ret_1d": r.get("ret_1d"),
                "ret_5d": r.get("ret_5d"),
                "volume_vs_20d_med": r.get("volume_vs_20d_med"),
                "source": r.get("source"),
            }
        )
    for r in short_ext:
        unified.append(
            {
                "symbol": r["symbol"],
                "kind": r["kind"],
                "severity": abs(r.get("z") or 0),
                "asof": r.get("asof"),
                "z": r.get("z"),
                "value": r.get("value"),
                "note": r.get("note"),
                "source": r.get("source"),
            }
        )
    for r in opt_ext:
        unified.append(
            {
                "symbol": r["symbol"],
                "kind": r["kind"],
                "severity": float(r.get("value") or 0),
                "asof": r.get("asof"),
                "value": r.get("value"),
                "note": r.get("note"),
                "source": r.get("source"),
            }
        )
    for r in sec.get("rows") or []:
        sev = 0.4 * r.get("form4_90d", 0) + 0.3 * r.get("eightk_90d", 0) + 1.0 * r.get("sc13_90d", 0)
        if sev < 2:
            continue
        unified.append(
            {
                "symbol": r["symbol"],
                "kind": "SEC_FILING_ACTIVITY",
                "severity": sev,
                "asof": r.get("latest_filing"),
                "form4_90d": r.get("form4_90d"),
                "eightk_90d": r.get("eightk_90d"),
                "sc13_90d": r.get("sc13_90d"),
                "latest_form": r.get("latest_form"),
                "source": "SEC EDGAR",
                "note": "Elevated filing count — inspect filings, do not trade the count",
            }
        )

    unified.sort(key=lambda r: r.get("severity") or 0, reverse=True)

    payload: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "disclaimer": (
            "Anomalies are statistical outliers in measured data. "
            "They are research breadcrumbs, not entries. Accuracy over coverage: "
            "empty panels mean the source failed, not that the market is quiet."
        ),
        "price_volume": px,
        "finra_short_extremes": {
            "quality": finra.get("quality"),
            "asof": finra.get("asof"),
            "source": finra.get("source"),
            "lag_note": finra.get("lag_note"),
            "rows": short_ext,
        },
        "options_extremes": {
            "quality": opt.get("quality"),
            "asof": opt.get("asof"),
            "source": opt.get("source"),
            "lag_note": opt.get("lag_note"),
            "rows": opt_ext,
        },
        "sec_activity": sec,
        "unified": unified[: limit * 2],
        "accuracy": {
            "rule": "thresholded, source-tagged, no fabricated HF positions",
            "thresholds": {
                "ret_1d_z": 2.5,
                "ret_5d_abs": 0.08,
                "volume_vs_20d_med": 2.5,
                "finra_short_z": 2.0,
                "options_pc_oi": 1.3,
            },
        },
    }
    if symbol:
        sym = symbol.strip().upper()
        payload["symbol_focus"] = {
            "symbol": sym,
            "price_volume": next((r for r in (px.get("rows") or []) if r["symbol"] == sym), None),
            "finra": next((r for r in (finra.get("rows") or []) if r["symbol"] == sym), None),
            "options": next((r for r in (opt.get("rows") or []) if r["symbol"] == sym), None),
            "filings": sec_filings_for_symbol(sym),
        }
    return payload


if __name__ == "__main__":
    # Smoke test without starting the HTTP server.
    import pprint

    s = build_sentiment_payload(symbol="AAPL")
    print("SENTIMENT composite:", s["composite"])
    print("vol quality", s["vol"]["quality"], "cot", s["cot"]["quality"], "finra", s["finra_short"]["quality"])
    print("COT markets", [(m["id"], m.get("bias"), m.get("noncomm_net_z_1y")) for m in s["cot"].get("markets") or []])
    a = build_anomalies_payload(limit=10)
    print("ANOMALIES unified", len(a["unified"]), "px", a["price_volume"]["n_flagged"])
    pprint.pp(a["unified"][:5])
