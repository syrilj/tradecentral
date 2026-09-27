"""PEAD-style broad-universe gap/volume activity adapter.

Scans expanded multi-sector universe (60+ liquid US equities across 11 sectors) for post-earnings gap acceleration.

Computes:
  - gap_std: (Open - PrevClose) / ATR_20d
  - vol_surge: Volume / Volume_20d_SMA
  - pead_score: gap_std * np.log1p(vol_surge)
  - pead_score is kept as an ordinal strength score

The checked-in PEAD gate is NO-GO and there is no frozen calibration artifact.
Consequently this adapter flags setups for attention but never turns its
hand-written sigmoid into a probability or an ENTER recommendation.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Sequence
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]

DEFAULT_UNIVERSE_PATH = ROOT / "edge" / "config" / "universe_wide.json"

def _load_broad_universe() -> list[str]:
    if DEFAULT_UNIVERSE_PATH.exists():
        try:
            data = json.loads(DEFAULT_UNIVERSE_PATH.read_text(encoding="utf-8"))
            syms = data.get("symbols", [])
            if syms:
                return [str(s).upper() for s in syms]
        except Exception:
            pass
    return ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "AMD",
            "TSLA", "NFLX", "CRM", "ORCL", "NOW", "PLTR", "MU", "QCOM",
            "JPM", "GS", "V", "MA", "UNH", "LLY", "JNJ", "COST", "WMT"]

import concurrent.futures

def _load_symbol_df(sym: str) -> pd.DataFrame:
    cols = ["open", "high", "low", "close", "volume"]
    # Order matters: the first directory containing the symbol wins, so a stale
    # directory listed first silently shadows fresher data. `1d_wide` is the
    # maintained feed (558 symbols, current); `1d` lags it by ~13 sessions but
    # still holds 19 symbols -- mostly index ETFs -- that `1d_wide` lacks, so it
    # stays as the fallback rather than being dropped.
    for cache_dir in [ROOT / "edge" / "data" / "1d_wide", ROOT / "edge" / "data" / "1d"]:
        p = cache_dir / f"{sym}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p, columns=cols)
                df.columns = [c.capitalize() for c in df.columns]
                if len(df) >= 20:
                    return df.tail(60)
            except Exception:
                try:
                    df = pd.read_parquet(p)
                    df.columns = [c.capitalize() for c in df.columns]
                    if len(df) >= 20:
                        return df.tail(60)
                except Exception:
                    pass
    try:
        import yfinance as yf
        df = yf.download(sym, period="30d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(sym, level=1, axis=1) if sym in df.columns.levels[1] else df.droplevel(1, axis=1)
        return df
    except Exception:
        return pd.DataFrame()


def _eval_single_pead_symbol(sym: str, threshold: float) -> tuple[str, dict[str, Any] | None]:
    try:
        df = _load_symbol_df(sym)
        if df.empty or len(df) < 20:
            return "unavailable", None
            
        open_col = "Open" if "Open" in df else "open"
        high_col = "High" if "High" in df else "high"
        low_col = "Low" if "Low" in df else "low"
        close_col = "Close" if "Close" in df else "close"
        vol_col = "Volume" if "Volume" in df else "volume"

        open_p = df[open_col].dropna()
        close_p = df[close_col].dropna()
        prev_close = close_p.shift(1)
        high_p = df[high_col].dropna()
        low_p = df[low_col].dropna()
        vol = df[vol_col].dropna()
        
        if len(close_p) < 20:
            return "unavailable", None

        tr = np.maximum(high_p - low_p, np.maximum(abs(high_p - prev_close), abs(low_p - prev_close)))
        atr_20d = tr.rolling(20).mean()
        atr_pct = (atr_20d / prev_close).iloc[-1]
        
        gap_pct = (open_p.iloc[-1] - prev_close.iloc[-1]) / prev_close.iloc[-1]
        gap_std = float(gap_pct / (atr_pct if atr_pct > 0 else 0.02))
        
        vol_20d_sma = vol.rolling(20).mean().iloc[-1]
        vol_surge = float(vol.iloc[-1] / vol_20d_sma if vol_20d_sma > 0 else 1.0)
        
        pead_score = float(gap_std * np.log1p(max(0, vol_surge)))
        
        go_long = pead_score >= threshold
        go_short = pead_score <= -threshold
        
        if go_long or go_short:
            return "evaluated", {
                "symbol": sym,
                "pead_score": pead_score,
                "gap_std": gap_std,
                "vol_surge": vol_surge,
                "go_long": go_long,
                "go_short": go_short,
            }
        return "evaluated", None
    except Exception:
        return "failed", None


def generate_pead_candidates(
    symbols: Sequence[str] | None = None,
    asof_utc: datetime | None = None,
    threshold: float = 0.8, # Lower threshold to capture all notable gaps
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    target_symbols = list(symbols) if symbols else _load_broad_universe()
    raw_candidates = []
    evaluated_symbols = 0
    unavailable_symbols = 0
    failed_symbols = 0
    
    print(f"PEAD Engine scanning broad universe ({len(target_symbols)} symbols)...")
    
    workers = min(16, max(1, len(target_symbols)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_eval_single_pead_symbol, sym, threshold) for sym in target_symbols]
        for fut in futures:
            status, item = fut.result()
            if status == "evaluated":
                evaluated_symbols += 1
                if item is not None:
                    raw_candidates.append(item)
            elif status == "unavailable":
                unavailable_symbols += 1
            else:
                failed_symbols += 1
            
    # Sort candidates by absolute PEAD score
    raw_candidates.sort(key=lambda x: abs(x["pead_score"]), reverse=True)
    
    results = []
    for rank, item in enumerate(raw_candidates, start=1):
        results.append({
            "source": "local_daily_ohlcv",
            "symbol": item["symbol"],
            "rank": rank,
            "side": "long" if item["go_long"] else "short",
            "setup_ok": True,
            "live": {"go_long": item["go_long"], "go_short": item["go_short"]},
            "model": {
                "id": "pead_gap_volume_ordinal_v1",
                "probability": None,
                "raw_score": item["pead_score"],
                "confidence_kind": "ordinal_score",
                "calibration_version": None,
                "probability_target": None,
                "horizon_days": 5,
                "entry_threshold": None,
                "threshold_version": "pead-activity-threshold-v1",
                "artifact_sha256": None,
                "promotion_authorized": False,
                "state": "FLAG",
                "reasons": [
                    "pead_gate_no_go",
                    "calibrated_probability_unavailable",
                    "activity_flag_not_entry",
                ],
            },
            "evidence": {
                "pead_score": item["pead_score"],
                "gap_std": item["gap_std"],
                "vol_surge": item["vol_surge"],
            },
            "decision_authorized": False,
        })
        
    print(f"PEAD Engine identified {len(results)} active gap candidates across universe.")
    if diagnostics is not None:
        diagnostics.update({
            "attempted_symbols": len(target_symbols),
            "evaluated_symbols": evaluated_symbols,
            "unavailable_symbols": unavailable_symbols,
            "failed_symbols": failed_symbols,
            "qualified_symbols": len(results),
            "threshold": threshold,
        })
    return results
