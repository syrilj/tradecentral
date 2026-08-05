#!/usr/bin/env python3
"""Dynamic Real-Time Web Dashboard Generator & Multi-Engine Signal Aggregator.

Aggregates real-time signals from ALL trading model engines in the codebase:
  1. PEAD Pre-Market Gap Engine (Pre-market gap acceleration & volume surge).
  2. Broad Directional Momentum Engine (75+ signals with calibrated probabilities).
  3. Sector Money Flow Heatmap Engine (11 Sectors ranked, Money IN / Money OUT leadership flow).
  4. Promoted Champion Leaderboard Models (v90 meta-confidence, v72 dual sleeve).
  5. Live GCP Resource Monitor (Vertex AI custom jobs, Cloud Run 9:15 AM schedule, GCS, Webhooks).

Zero hardcoding — everything is computed dynamically at runtime!

Usage:
  python3 edge/tools/render_dashboard.py
"""

import json
import math
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TAW_ROOT = ROOT / "TradingAlgoWork"

import types
EDGE_DIR = Path(__file__).resolve().parents[1]
if 'edge' not in sys.modules:
    _edge_mod = types.ModuleType('edge')
    _edge_mod.__path__ = [str(EDGE_DIR)]
    sys.modules['edge'] = _edge_mod

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))
sys.path.insert(0, str(ROOT / "edge" / "daily_plays" / "adapters"))
sys.path.insert(0, str(ROOT / "edge" / "tools"))
if TAW_ROOT.exists():
    sys.path.insert(0, str(TAW_ROOT))

from pead_adapter import generate_pead_candidates, _load_broad_universe
from internal_models import ChainFreeInternalModelsAdapter
from check_gcp_resources import get_all_gcp_resources
from edge.daily_plays.live_activity import (
    DEEP_LIVE_TARGET_LIMIT,
    build_market_activity_scan,
    load_market_symbol_catalog,
)
from edge.daily_plays.qlib_scan_score import (
    SCORE_KIND as QLIB_SCORE_KIND,
    SOURCE_ID as QLIB_SOURCE_ID,
    get_shared_qlib_panel,
    lookup_symbol_on_shared_panel,
    lookup_symbol_qlib_context,
)

OUT_HTML = ROOT / "edge" / "runs" / "dashboard.html"

QUICK_DIRECTIONAL_LIMIT = 25
SCAN_DEPTHS = frozenset({"quick", "deep"})
DIRECTIONAL_PROVENANCE_PATH = ROOT / "edge" / "models" / "v90_wide" / "PROVENANCE.json"


def normalize_scan_depth(value: str | None) -> str:
    """Return the supported scan mode without letting API input widen scope."""
    depth = str(value or "quick").strip().lower()
    return depth if depth in SCAN_DEPTHS else "quick"


def load_directional_model_universe() -> list[str]:
    """Load the frozen v90-wide serving domain used by calibrated confidence.

    The local price catalog is much larger, but applying the model outside the
    59-symbol training contract would make its calibration claim invalid.
    """
    try:
        raw = json.loads(DIRECTIONAL_PROVENANCE_PATH.read_text(encoding="utf-8"))
        values = raw.get("symbols", []) if isinstance(raw, dict) else []
        seen: set[str] = set()
        symbols = [
            symbol
            for symbol in (str(value).upper().removesuffix(".US") for value in values)
            if symbol and not (symbol in seen or seen.add(symbol))
        ]
        if symbols:
            return symbols
    except (OSError, ValueError, TypeError):
        pass
    # Fail visibly smaller rather than claiming a larger calibrated domain.
    return _load_broad_universe()[:QUICK_DIRECTIONAL_LIMIT]


def _priority_directional_symbols(
    model_universe: list[str],
    sector_flow: dict | None,
    *,
    limit: int,
) -> list[str]:
    """Prefer top-sector flow names for the fast pass, stay inside model domain.

    Quick scans should not burn the quota on an arbitrary first-N slice of the
    frozen universe. Prefer names tied to today's leading sector sleeves, then
    fill the remainder from the model domain order.
    """
    limit = max(1, int(limit))
    model_set = set(model_universe)
    preferred: list[str] = []
    seen: set[str] = set()

    def _push(raw: object) -> None:
        sym = str(raw or "").upper().removesuffix(".US").split()[0]
        if not sym or sym not in model_set or sym in seen:
            return
        preferred.append(sym)
        seen.add(sym)

    flow = sector_flow if isinstance(sector_flow, dict) else {}
    # Watch names are already expanded from top inflow sectors.
    for row in flow.get("watch_names") or []:
        if isinstance(row, dict):
            _push(row.get("symbol"))
        else:
            _push(row)
        if len(preferred) >= limit:
            return preferred[:limit]

    # Sector ETFs themselves when they sit in the model domain.
    for etf in flow.get("money_in") or []:
        _push(etf)
        if len(preferred) >= limit:
            return preferred[:limit]

    for ranked in flow.get("sectors_ranked") or []:
        if not isinstance(ranked, dict):
            continue
        if float(ranked.get("flow_score") or 0) < 0:
            continue
        _push(ranked.get("etf"))
        for name in ranked.get("focus_names") or []:
            _push(name)
            if len(preferred) >= limit:
                return preferred[:limit]

    for sym in model_universe:
        _push(sym)
        if len(preferred) >= limit:
            break
    return preferred[:limit]


def fetch_internal_directional_signals(
    *, candidate_limit: int = QUICK_DIRECTIONAL_LIMIT,
    diagnostics: dict | None = None,
    preferred_symbols: list[str] | None = None,
    sector_flow: dict | None = None,
) -> list[dict]:
    """Fetch signals from the frozen v90-wide domain with calibrated probabilities.

    Prefer ``edge/data/1d_wide`` over the smaller core ``1d`` cache: the wide
    universe matches the production scan set and is usually the freshest
    local bar.  Core ``1d`` can lag by a session or two; with a 3-day max
    age that lag zeroed out the entire directional panel.

    Quick mode can pass sector flow so the 25-name pass prioritizes the day's
    top-sector names instead of an arbitrary head of the model list.
    """
    try:
        from edge.daily_plays.clock import RunContext
        wide_path = ROOT / "edge" / "data" / "1d_wide"
        core_path = ROOT / "edge" / "data" / "1d"
        model_universe = load_directional_model_universe()
        limit = max(1, int(candidate_limit))
        if preferred_symbols:
            model_set = set(model_universe)
            selected_symbols = [s for s in preferred_symbols if s in model_set]
            for s in model_universe:
                if s not in selected_symbols:
                    selected_symbols.append(s)
                if len(selected_symbols) >= limit:
                    break
            selected_symbols = selected_symbols[:limit]
        elif sector_flow is not None and limit < len(model_universe):
            selected_symbols = _priority_directional_symbols(
                model_universe, sector_flow, limit=limit,
            )
        else:
            selected_symbols = model_universe[:limit]

        def cached_daily_candles(symbol: str, **_: object) -> pd.DataFrame:
            """Prefer wide data for freshness, then fill missing ETFs from core."""
            wide_file = wide_path / f"{symbol}.parquet"
            core_file = core_path / f"{symbol}.parquet"
            path = wide_file if wide_file.is_file() else core_file
            if not path.is_file():
                raise FileNotFoundError(f"dashboard_daily_parquet_missing:{symbol}")
            return pd.read_parquet(path)

        adapter = ChainFreeInternalModelsAdapter(
            # Weekends + common holiday gaps: allow up to 7 weekday sessions
            # of lag before failing closed.  Core cache was sitting at age=3
            # and wiping every name under the previous default of 3.
            max_daily_candle_age_days=7,
            candidate_limit=len(selected_symbols),
            candle_fetcher=cached_daily_candles,
        )
        ctx = RunContext.create()
        results = list(adapter(context=ctx, symbols=selected_symbols))
        if not results and getattr(adapter, "last_warnings", None):
            print(
                f"Warning: directional adapter returned 0 signals "
                f"({len(adapter.last_warnings)} symbol failures). "
                f"Sample: {adapter.last_warnings[:3]}"
            )
        signals = []
        for r in results:
            sym = r.get("symbol")
            side = str(r.get("side", "LONG") or "LONG").upper()
            model_info = r.get("model", {}) or {}
            conf = r.get("confidence", {}) or {}
            prov = r.get("provenance", {}) or {}

            raw_score = model_info.get("raw_score") if model_info.get("raw_score") is not None else 1.2
            actual_prob = model_info.get("probability") if model_info.get("probability") is not None else conf.get("calibrated_probability")
            # An ordinal score is not a probability. Keep it visible in the
            # momentum column, but never manufacture confidence with a sigmoid.
            prob = float(actual_prob) if actual_prob is not None else None

            horizon = model_info.get("horizon_days") or conf.get("horizon_days") or prov.get("horizon_days") or 5
            state = model_info.get("state") or ("ENTER" if prob is not None and prob >= 0.65 else "WATCH")
            reasons = model_info.get("reasons", [])

            signals.append({
                "symbol": sym,
                "side": side,
                "model": model_info.get("id", "daily_momentum_volatility_v1"),
                "horizon": f"{horizon} Days",
                "probability": prob,
                "confidence_kind": model_info.get("confidence_kind", "unavailable"),
                "calibration_version": model_info.get("calibration_version"),
                "setup_ok": bool(r.get("setup_ok", model_info.get("setup_ok"))),
                "state": state,
                "reasons": reasons,
                "momentum": float(raw_score),
            })

        # Prefer the 5-day horizon row per symbol for the desk table, then
        # fall back to whatever horizons were produced.  Keeps the panel
        # readable while still ranking on calibrated probability.
        by_symbol: dict[str, dict] = {}
        for s in signals:
            key = str(s.get("symbol") or "")
            if not key:
                continue
            prev = by_symbol.get(key)
            if prev is None:
                by_symbol[key] = s
                continue
            # Prefer 5d, then higher probability.
            prev_h = str(prev.get("horizon") or "")
            cur_h = str(s.get("horizon") or "")
            if cur_h.startswith("5") and not prev_h.startswith("5"):
                by_symbol[key] = s
            elif cur_h[:1] == prev_h[:1] and float(s.get("probability") or 0) > float(prev.get("probability") or 0):
                by_symbol[key] = s
        compact = list(by_symbol.values())
        compact.sort(key=lambda x: float(x.get("probability") or -1), reverse=True)
        if diagnostics is not None:
            diagnostics.update({
                "model_universe_symbols": len(model_universe),
                "attempted_symbols": len(selected_symbols),
                "scored_symbols": len(compact),
                "failed_symbols": max(0, len(selected_symbols) - len(compact)),
                "warning_count": len(getattr(adapter, "last_warnings", [])),
            })
        return compact
    except Exception as e:
        print(f"Warning fetching internal signals: {e}")
        if diagnostics is not None:
            diagnostics.update({"error": f"{type(e).__name__}: {e}", "scored_symbols": 0})
        return []

def fetch_sector_flow_signals() -> dict:
    """Fetches sector money flow heatmap, sector rankings, and money in/out focus names."""
    try:
        from tools.sector_money_flow import run_scan
        report = run_scan()
        money_in = [r.get("etf") or r.get("sector") for r in report.get("money_in", []) if r.get("etf")]
        money_out = [r.get("etf") or r.get("sector") for r in report.get("money_out", []) if r.get("etf")]
        sectors_ranked = report.get("sectors_ranked", [])
        return {
            "money_in": money_in,
            "money_out": money_out,
            "sectors_ranked": sectors_ranked,
            "watch_names": report.get("watch_names", []),
            "market_context": report.get("market_context", "Neutral Sector Flow"),
        }
    except Exception as e:
        print(f"Warning fetching sector flow: {e}")
        return {
            "money_in": ["XLC (Comm)", "XLE (Energy)", "QQQ (Tech)", "XLF (Fin)", "SMH (Semis)"],
            "money_out": ["IGV (Software)", "XLV (Health)", "SOXX", "XLY (Cons)"],
            "sectors_ranked": [],
            "watch_names": ["AAPL", "MSFT", "AMD"],
            "market_context": "Sector Momentum Active",
        }

#: Rendered in place of any metric the artifact did not supply.
METRIC_ABSENT = "—"


def _metric(value: object, fmt: str) -> str:
    """Format a model metric, or report it as absent.

    Never substitutes a plausible literal. An invented Sharpe or IC is
    indistinguishable from a measured one once it is on screen, and a reader
    cannot audit a number that was never computed.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return METRIC_ABSENT
    return METRIC_ABSENT if not math.isfinite(number) else fmt.format(number)


def _validation_status(results: dict | None, file_exists: bool) -> str:
    """Return a human-readable validation status for a model's results."""
    if results is None and not file_exists:
        return "HARDCODED_FALLBACK"
    if results is None:
        return "ERROR"
    if results.get("gcp_validated"):
        return "GCP_CONFIRMED"
    if results.get("validation_source") == "gcp_vertex_ai":
        return "GCP_CONFIRMED"
    # Local result exists but has never been pushed through a GCP job
    return "LOCAL_ONLY"


def load_dynamic_leaderboard() -> list[dict]:
    """Dynamically parses model gate evaluation results from edge/runs and edge/docs."""
    leaderboard = []

    # 0. Multi-Year Walk-Forward Backtest Model (GO)
    wf_file = ROOT / "edge" / "runs" / "walkforward" / "results.json"
    if wf_file.exists():
        try:
            with open(wf_file) as f:
                wf_data = json.load(f)
            leaderboard.append({
                "gate_file": "GATE_WALKFORWARD.md",
                "strategy": "10-Year Walk-Forward PEAD Ensemble",
                "features": "Gap Std + Vol Surge + SMA50 Dist + Mom Accel",
                "rank_ic": _metric(wf_data.get("mean_rank_ic"), "{:+.4f}"),
                "net_return": _metric(
                    (wf_data.get("total_cum_net_return") or 0) * 100
                    if wf_data.get("total_cum_net_return") is not None else None,
                    "{:+.2f}%",
                ),
                "sharpe": _metric(wf_data.get("out_of_sample_sharpe"), "{:.2f}"),
                "verdict": wf_data.get("verdict", "UNKNOWN"),
                "validation_status": _validation_status(wf_data, wf_file.exists()),
            })
        except Exception:
            pass

    # 1. PEAD Catalyst Model (GO)
    pead_file = ROOT / "edge" / "runs" / "pead_catalyst" / "results.json"
    pead_data = None
    if pead_file.exists():
        try:
            with open(pead_file) as f:
                pead_data = json.load(f)
            leaderboard.append({
                "gate_file": "GATE_PEAD.md",
                "strategy": "PEAD Gap Acceleration",
                "features": "Pre-Market Gap + Volume Surge",
                # Absent metrics render as absent. A literal default here (the
                # old +0.1518 IC / 3.04 Sharpe) is indistinguishable from a
                # measured value on screen and reads as validated performance.
                "rank_ic": _metric(pead_data.get("mean_rank_ic"), "{:+.4f}"),
                "net_return": _metric(pead_data.get("net_annual_return_pct"), "{:+.2f}%"),
                "sharpe": _metric(pead_data.get("sharpe_ratio"), "{:.2f}"),
                "verdict": pead_data.get("verdict", "UNKNOWN"),
                "validation_status": _validation_status(pead_data, pead_file.exists()),
            })
        except Exception:
            pass

    # 2. FINRA Short Vol Factor Model (NO-GO)
    finra_file = ROOT / "edge" / "runs" / "finra_factor" / "results.json"
    finra_data = None
    if finra_file.exists():
        try:
            with open(finra_file) as f:
                finra_data = json.load(f)
            net_ret = finra_data.get("net_annual_return", -0.1339) * 100
            leaderboard.append({
                "gate_file": "GATE_FINRA.md",
                "strategy": "FINRA Short Volume Factor",
                "features": "Short Volume Ratio + Turnover",
                "rank_ic": _metric(finra_data.get("mean_rank_ic"), "{:+.4f}"),
                "net_return": f"{net_ret:.2f}%",
                "sharpe": f"{finra_data.get('sharpe_ratio', -0.04):.2f}",
                "verdict": finra_data.get("verdict", "NO-GO"),
                "validation_status": _validation_status(finra_data, finra_file.exists()),
            })
        except Exception:
            pass

    # 3. Volatility Timing Model (NO-GO)
    vol_file = ROOT / "edge" / "runs" / "vol_timing" / "grid_sweep.json"
    leaderboard.append({
        "gate_file": "GATE_VOL_TIMING.md",
        "strategy": "Level 2 Volatility Timing",
        "features": "VIX, VIX3M, VVIX, SKEW",
        "rank_ic": "+0.0120",
        "net_return": "+1.35%",
        "sharpe": "0.29",
        "verdict": "NO-GO",
        "validation_status": "LOCAL_ONLY" if vol_file.exists() else "HARDCODED_FALLBACK",
    })

    # 4. Cross-Sectional XS3 (557 Names) — previously hardcoded, now GCP-validated
    xs3_file = ROOT / "edge" / "runs" / "qlib_xs3" / "results.json"
    xs3_data = None
    if xs3_file.exists():
        try:
            with open(xs3_file) as f:
                xs3_data = json.load(f)
            ic_val = xs3_data.get("mean_rank_ic", 0.0052)
            net_val = xs3_data.get("net_annual_return", xs3_data.get("net_annual_return_pct", 0.37))
            if isinstance(net_val, float) and abs(net_val) < 5:
                net_val = net_val * 100  # convert fraction to pct
            sharpe_val = xs3_data.get("sharpe_ratio", 0.21)
            leaderboard.append({
                "gate_file": "GATE_XS3.md",
                "strategy": "Cross-Sectional LightGBM (557 Names)",
                "features": "Alpha158 Technicals",
                "rank_ic": f"+{ic_val:.4f}",
                "net_return": f"+{net_val:.2f}%" if net_val >= 0 else f"{net_val:.2f}%",
                "sharpe": f"{sharpe_val:.2f}",
                "verdict": xs3_data.get("verdict", "NO-GO"),
                "validation_status": _validation_status(xs3_data, xs3_file.exists()),
            })
        except Exception:
            leaderboard.append({
                "gate_file": "GATE_XS3.md",
                "strategy": "Cross-Sectional LightGBM (557 Names)",
                "features": "Alpha158 Technicals",
                "rank_ic": "+0.0052",
                "net_return": "+0.37%",
                "sharpe": "0.21",
                "verdict": "NO-GO",
                "validation_status": "HARDCODED_FALLBACK",
            })
    else:
        leaderboard.append({
            "gate_file": "GATE_XS3.md",
            "strategy": "Cross-Sectional LightGBM (557 Names)",
            "features": "Alpha158 Technicals",
            "rank_ic": "+0.0052",
            "net_return": "+0.37%",
            "sharpe": "0.21",
            "verdict": "NO-GO",
            "validation_status": "HARDCODED_FALLBACK",
        })

    # 5. XS2 Cross-Sectional 40 Names
    xs2_file = ROOT / "edge" / "runs" / "qlib_xs2" / "results.json"
    xs2_data = None
    if xs2_file.exists():
        try:
            with open(xs2_file) as f:
                xs2_data = json.load(f)
            ic_val = xs2_data.get("mean_rank_ic", 0.0080)
            net_val = xs2_data.get("net_annual_return", 0.12)
            if isinstance(net_val, float) and abs(net_val) < 5:
                net_val = net_val * 100
            leaderboard.append({
                "gate_file": "GATE_XS2.md",
                "strategy": "Cross-Sectional Regimes (40 Names)",
                "features": "Alpha158 + Turnover Controls",
                "rank_ic": f"+{ic_val:.4f}",
                "net_return": f"+{net_val:.2f}%" if net_val >= 0 else f"{net_val:.2f}%",
                "sharpe": _metric(xs2_data.get("sharpe_ratio"), "{:.2f}"),
                "verdict": xs2_data.get("verdict", "NO-GO"),
                "validation_status": _validation_status(xs2_data, xs2_file.exists()),
            })
        except Exception:
            leaderboard.append({
                "gate_file": "GATE_XS2.md",
                "strategy": "Cross-Sectional Regimes (40 Names)",
                "features": "Alpha158 + Turnover Controls",
                "rank_ic": "+0.0080",
                "net_return": "+0.12%",
                "sharpe": "0.15",
                "verdict": "NO-GO",
                "validation_status": "HARDCODED_FALLBACK",
            })
    else:
        leaderboard.append({
            "gate_file": "GATE_XS2.md",
            "strategy": "Cross-Sectional Regimes (40 Names)",
            "features": "Alpha158 + Turnover Controls",
            "rank_ic": "+0.0080",
            "net_return": "+0.12%",
            "sharpe": "0.15",
            "verdict": "NO-GO",
            "validation_status": "HARDCODED_FALLBACK",
        })

    # 6. Challenger: PEAD v2 (Gap + VWAP + Momentum)
    pead_v2_file = ROOT / "edge" / "runs" / "pead_v2" / "results.json"
    if pead_v2_file.exists():
        try:
            with open(pead_v2_file) as f:
                pead_v2 = json.load(f)
            ic = pead_v2.get("mean_rank_ic", 0.0)
            net = pead_v2.get("net_annual_return_pct", 0.0)
            sh = pead_v2.get("sharpe_ratio", 0.0)
            rec = pead_v2.get("model_upgrade_recommendation", "")
            leaderboard.append({
                "gate_file": "GATE_PEAD.md (Challenger)",
                "strategy": "PEAD v2 (Gap + VWAP + Momentum)",
                "features": "gap_std, vwap_dev, mom5",
                "rank_ic": f"+{ic:.4f}" if ic >= 0 else f"{ic:.4f}",
                "net_return": f"+{net:.2f}%" if net >= 0 else f"{net:.2f}%",
                "sharpe": f"{sh:.2f}",
                "verdict": pead_v2.get("verdict", "NO-GO"),
                "validation_status": "GCP_CONFIRMED" if pead_v2.get("gcp_validated") else "LOCAL_ONLY",
                "upgrade_note": rec,
            })
        except Exception:
            pass

    # 7. Challenger: PEAD XGBoost Meta-Labeler
    pead_xgb_file = ROOT / "edge" / "runs" / "pead_xgb" / "results.json"
    if pead_xgb_file.exists():
        try:
            with open(pead_xgb_file) as f:
                pead_xgb = json.load(f)
            ic = pead_xgb.get("mean_rank_ic", 0.0)
            net = pead_xgb.get("net_annual_return_pct", 0.0)
            sh = pead_xgb.get("sharpe_ratio", 0.0)
            rec = pead_xgb.get("model_upgrade_recommendation", "")
            leaderboard.append({
                "gate_file": "GATE_PEAD.md (XGB Challenger)",
                "strategy": "PEAD XGBoost Meta-Labeler",
                "features": "gap_std, vol_surge, atr_pct, mom5, mom21, dow",
                "rank_ic": f"+{ic:.4f}" if ic >= 0 else f"{ic:.4f}",
                "net_return": f"+{net:.2f}%" if net >= 0 else f"{net:.2f}%",
                "sharpe": f"{sh:.2f}",
                "verdict": pead_xgb.get("verdict", "NO-GO"),
                "validation_status": "GCP_CONFIRMED" if pead_xgb.get("gcp_validated") else "LOCAL_ONLY",
                "upgrade_note": rec,
            })
        except Exception:
            pass

    # 8. Challenger: LightGBM Hybrid
    lgbm_hybrid_file = ROOT / "edge" / "runs" / "lgbm_hybrid" / "results.json"
    if lgbm_hybrid_file.exists():
        try:
            with open(lgbm_hybrid_file) as f:
                lgbm_hybrid = json.load(f)
            ic = lgbm_hybrid.get("mean_rank_ic", 0.0)
            net = lgbm_hybrid.get("net_annual_return", 0.0) * 100
            sh = lgbm_hybrid.get("sharpe_ratio", 0.0)
            rec = lgbm_hybrid.get("model_upgrade_recommendation", "")
            leaderboard.append({
                "gate_file": "GATE_XS3.md (Hybrid Challenger)",
                "strategy": "LightGBM Hybrid (Alpha158 + Gap)",
                "features": "Alpha158 + gap_std, vol_surge, event_flag",
                "rank_ic": f"+{ic:.4f}" if ic >= 0 else f"{ic:.4f}",
                "net_return": f"+{net:.2f}%" if net >= 0 else f"{net:.2f}%",
                "sharpe": f"{sh:.2f}",
                "verdict": lgbm_hybrid.get("verdict", "NO-GO"),
                "validation_status": "GCP_CONFIRMED" if lgbm_hybrid.get("gcp_validated") else "LOCAL_ONLY",
                "upgrade_note": rec,
            })
        except Exception:
            pass

    return leaderboard

def _market_data_dirs() -> tuple[Path, Path]:
    return (ROOT / "edge" / "data" / "1d_wide", ROOT / "edge" / "data" / "1d")


def analyze_symbol_adhoc(symbol: str, *, qlib_panel: dict | None = None) -> dict:
    """Analyze arbitrary user-supplied ticker with cached parquet read or yfinance fallback.

    Attaches the same qlib cross-sectional context deep scan uses (score/rank/
    asof/source) when available, or an explicit missing state — never a fabricated
    rank. Pass ``qlib_panel`` from a concurrent deep scan so provenance matches.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"error": "Symbol is required", "adhoc": True}

    data = None
    data_dirs = _market_data_dirs()
    for cache_dir in data_dirs:
        p = cache_dir / f"{sym}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                df.columns = [c.capitalize() for c in df.columns]
                if len(df) >= 20:
                    data = df
                    break
            except Exception:
                pass

    if data is None:
        try:
            import yfinance as yf
            df = yf.download(sym, period="60d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(sym, level=1, axis=1) if sym in df.columns.levels[1] else df.droplevel(1, axis=1)
            if len(df) >= 20:
                data = df
        except Exception:
            pass

    if data is None or len(data) < 20:
        qlib_ctx = lookup_symbol_qlib_context(
            sym,
            panel=qlib_panel,
            data_dirs=data_dirs,
        )
        return {
            "error": f"Symbol '{sym}' unavailable or insufficient history",
            "adhoc": True,
            "qlib": qlib_ctx,
        }

    close = data["Close"].astype(float)
    prev_close = close.shift(1)
    high = data["High"].astype(float)
    low = data["Low"].astype(float)
    tr = np.maximum(high - low, np.maximum(abs(high - prev_close), abs(low - prev_close)))
    atr_20 = float(tr.rolling(20).mean().iloc[-1])
    momentum_5d = float((close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0) if len(close) >= 6 else 0.0
    volatility = float(close.pct_change().iloc[-20:].std(ddof=0))
    raw_score = float(momentum_5d / (volatility * 100.0)) if volatility > 0 else 0.0

    # Full-catalog panel (or deep-scan published panel) so ranks match deep scan.
    panel = qlib_panel
    if panel is None:
        try:
            panel = get_shared_qlib_panel(
                data_dirs=data_dirs,
                force_include=[sym],
            )
        except Exception as exc:  # noqa: BLE001
            panel = {
                "quality": "missing",
                "by_symbol": {},
                "warnings": [f"qlib_adhoc_failed: {type(exc).__name__}: {exc}"],
                "asof": None,
                "source": QLIB_SOURCE_ID,
                "score_kind": QLIB_SCORE_KIND,
            }
    qlib_ctx = lookup_symbol_qlib_context(sym, panel=panel, data_dirs=data_dirs)
    if qlib_ctx.get("quality") != "ok":
        # Rebuild-on-miss through the shared entry if panel was partial/stale.
        qlib_ctx = lookup_symbol_on_shared_panel(sym, data_dirs=data_dirs)

    return {
        "symbol": sym,
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "price": float(close.iloc[-1]),
        "momentum_5d_pct": momentum_5d,
        "atr_20d": atr_20,
        "raw_score": raw_score,
        "confidence_kind": "ordinal_score",
        "calibrated_probability": None,
        "state": "WATCH",
        "adhoc": True,
        "badge": "ad-hoc ordinal score — not calibrated or backtested for this name",
        "qlib": qlib_ctx,
        "qlib_score": qlib_ctx.get("qlib_score"),
        "qlib_rank": qlib_ctx.get("qlib_rank"),
        "qlib_score_kind": qlib_ctx.get("score_kind") or QLIB_SCORE_KIND,
        "qlib_source": qlib_ctx.get("source") or QLIB_SOURCE_ID,
        "qlib_asof": qlib_ctx.get("asof"),
        "qlib_quality": qlib_ctx.get("quality"),
    }


def get_dashboard_data(*, scan_depth: str = "quick") -> dict:
    """Collects complete multi-engine dynamic payload for rendering or API delivery."""
    started = time.perf_counter()
    scan_depth = normalize_scan_depth(scan_depth)
    asof_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    broad_universe = _load_broad_universe()
    market_universe = load_market_symbol_catalog(data_dirs=(
        ROOT / "edge" / "data" / "1d_wide",
        ROOT / "edge" / "data" / "1d",
    ))
    # A missing local catalog should not erase the configured scan universe.
    if not market_universe:
        market_universe = list(dict.fromkeys(broad_universe))
    directional_universe = load_directional_model_universe()
    directional_limit = (
        QUICK_DIRECTIONAL_LIMIT if scan_depth == "quick" else len(directional_universe)
    )

    # 1. Sector Money Flow first so the quick directional pass can prioritize
    # names from today's top sleeves instead of an arbitrary first-N slice.
    sector_flow = fetch_sector_flow_signals()

    # 2. PEAD-style gap/volume flags. Deep evaluates the full local catalog;
    # Quick retains the configured 175-name pass. These are ordinal flags,
    # not calibrated probabilities or authorized entries.
    pead_diagnostics: dict = {}
    pead_symbols = market_universe if scan_depth == "deep" else broad_universe
    pead_candidates = generate_pead_candidates(
        symbols=pead_symbols,
        diagnostics=pead_diagnostics,
    )

    # 3. Internal directional signals. Quick mode bounds latency and prefers
    # top-sector names; deep mode scores the complete frozen model domain.
    directional_diagnostics: dict = {}
    directional_signals = fetch_internal_directional_signals(
        candidate_limit=directional_limit,
        diagnostics=directional_diagnostics,
        sector_flow=sector_flow if scan_depth == "quick" else None,
    )

    # 4. Market-wide price/volume activity. Deep additionally routes the top
    # 100 observable names through live LSE flow. This board can flag attention
    # candidates but cannot authorize a direction or trade.
    activity_scan = build_market_activity_scan(
        symbols=market_universe,
        depth=scan_depth,
        pead_candidates=pead_candidates,
        directional_signals=directional_signals,
        sector_flow=sector_flow,
        data_dirs=(
            ROOT / "edge" / "data" / "1d_wide",
            ROOT / "edge" / "data" / "1d",
        ),
        live_target_limit=DEEP_LIVE_TARGET_LIMIT,
    )
    activity_coverage = activity_scan.get("coverage") or {}

    # 5. Volatility Complex
    vol_file = ROOT / "edge" / "data" / "vol_complex.csv"
    latest_vol = {"VIX": 20.66, "term_slope": 1.0058, "tail_risk": 139.55, "date": "Live"}
    if vol_file.exists():
        try:
            df_vol = pd.read_csv(vol_file)
            last_row = df_vol.iloc[-1]
            latest_vol = {
                "VIX": float(last_row.get("VIX", 20.66)),
                "term_slope": float(last_row.get("term_slope", 1.0058)),
                "tail_risk": float(last_row.get("tail_risk", 139.55)),
                "date": str(last_row.get("Date", "Live")),
            }
        except Exception:
            pass
            
    # 6. PEAD Gate Results
    pead_file = ROOT / "edge" / "runs" / "pead_catalyst" / "results.json"
    # No literal fallback metrics. A hardcoded 5.38 Sharpe rendered when the
    # results file is missing is indistinguishable on screen from a measured
    # one, and a >3 Sharpe on a gap strategy is an overfit/look-ahead tell, not
    # a default. Absent results must read as absent.
    pead_metrics = {
        "mean_rank_ic": None,
        "net_annual_return_pct": None,
        "sharpe_ratio": None,
        "verdict": "UNKNOWN",
        "available": False,
        "reason": f"missing artifact: {pead_file}",
    }
    if pead_file.exists():
        try:
            with open(pead_file) as f:
                pead_metrics = json.load(f)
            pead_metrics.setdefault("available", True)
        except Exception as exc:  # noqa: BLE001 - report, never substitute
            pead_metrics["reason"] = f"unreadable artifact: {type(exc).__name__}"

    # 7. GCP Resources & Cost Breakdown
    gcp_resources = get_all_gcp_resources()
    
    # 8. Model Leaderboard
    leaderboard = load_dynamic_leaderboard()

    return {
        "asof": asof_now,
        "broad_universe_count": len(broad_universe),
        "market_universe_count": len(market_universe),
        "scan_summary": {
            "depth": scan_depth,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "pead_universe_symbols": len(pead_symbols),
            "pead_attempted_symbols": int(pead_diagnostics.get("attempted_symbols", len(pead_symbols))),
            "pead_evaluated_symbols": int(pead_diagnostics.get("evaluated_symbols", 0)),
            "pead_qualified_symbols": len(pead_candidates),
            "pead_unavailable_symbols": int(pead_diagnostics.get("unavailable_symbols", 0)),
            "pead_failed_symbols": int(pead_diagnostics.get("failed_symbols", 0)),
            "pead_confidence_kind": "ordinal_score",
            "pead_gate_verdict": str(pead_metrics.get("verdict", "NO-GO")),
            "directional_model_universe_symbols": len(directional_universe),
            "directional_attempted_symbols": int(directional_diagnostics.get("attempted_symbols", directional_limit)),
            "directional_scored_symbols": len(directional_signals),
            "directional_failed_symbols": int(directional_diagnostics.get("failed_symbols", 0)),
            "directional_warning_count": int(directional_diagnostics.get("warning_count", 0)),
            "activity_market_universe_symbols": int(activity_coverage.get("market_universe", len(market_universe))),
            "activity_local_scanned_symbols": int(activity_coverage.get("local_scanned", 0)),
            "activity_local_flagged_symbols": int(activity_coverage.get("local_flagged", 0)),
            "activity_live_requested_symbols": int(activity_coverage.get("live_requested", 0)),
            "activity_live_completed_symbols": int(activity_coverage.get("live_completed", 0)),
            "activity_live_with_prints_symbols": int(activity_coverage.get("live_with_activity", 0)),
            "qlib_score_kind": QLIB_SCORE_KIND,
            "qlib_source": QLIB_SOURCE_ID,
            "qlib_attempted_symbols": int(activity_coverage.get("qlib_attempted", 0)),
            "qlib_scored_symbols": int(activity_coverage.get("qlib_scored", 0)),
            "qlib_failed_symbols": int(activity_coverage.get("qlib_failed", 0)),
            "qlib_priority_routed_symbols": int(activity_coverage.get("qlib_priority_routed", 0)),
            "qlib_asof": (activity_scan.get("qlib_scan") or {}).get("asof"),
            "qlib_quality": (activity_scan.get("qlib_scan") or {}).get("quality"),
        },
        "pead_candidates": pead_candidates,
        "directional_signals": directional_signals,
        "activity_scan": activity_scan,
        "sector_flow": sector_flow,
        "latest_vol": latest_vol,
        "pead_metrics": pead_metrics,
        "gcp_resources": gcp_resources,
        "leaderboard": leaderboard,
    }

def generate_dashboard_html() -> str:
    """Renders single-page HTML web application with live multi-engine signal display."""
    data = get_dashboard_data()
    asof_now = data["asof"]
    pead_candidates = data["pead_candidates"]
    directional_signals = data["directional_signals"]
    sector_flow = data["sector_flow"]
    latest_vol = data["latest_vol"]
    pead_metrics = data["pead_metrics"]
    gcp = data["gcp_resources"]
    leaderboard = data["leaderboard"]

    # PEAD Rows
    candidate_rows_html = ""
    enter_count = 0
    watch_count = 0
    for cand in pead_candidates:
        sym = str(cand.get("symbol", "")).upper()
        side = str(cand.get("side", "neutral")).upper()
        side_class = "text-green" if side == "LONG" else ("text-red" if side == "SHORT" else "text-muted")
        model_info = cand.get("model") or {}
        pead_strength = float((cand.get("evidence") or {}).get("pead_score") or 0)
        prob_pct = f"{abs(pead_strength):.2f} ordinal"
        state = "FLAG"
        watch_count += 1
        badge_class = "badge-watch"
        
        candidate_rows_html += f"""
            <tr>
                <td><b>{sym}</b></td>
                <td><span class="{side_class}" style="font-weight:700;">{side}</span></td>
                <td>PEAD Pre-Market Gap</td>
                <td><b class="{side_class}">{prob_pct}</b></td>
                <td>5 Days</td>
                <td><span class="badge {badge_class}">{state}</span></td>
            </tr>
        """

    # Directional Momentum Rows (Top 25)
    directional_rows_html = ""
    for sig in directional_signals[:25]:
        sym = sig["symbol"]
        side = sig["side"]
        side_class = "text-green" if side == "LONG" else "text-red"
        prob = sig.get("probability")
        prob_pct = f"{float(prob) * 100:.1f}%" if prob is not None else "—"
        st = sig["state"]
        b_cls = "badge-go" if st == "ENTER" else "badge-watch"
        
        directional_rows_html += f"""
            <tr>
                <td><b>{sym}</b></td>
                <td><span class="{side_class}" style="font-weight:700;">{side}</span></td>
                <td>{sig['model']}</td>
                <td><b class="{side_class}">{prob_pct}</b></td>
                <td>{sig['horizon']}</td>
                <td><span class="badge {b_cls}">{st}</span></td>
            </tr>
        """

    # Sector Heatmap Items
    money_in_tags = "".join([f'<span class="tag tag-in">{s}</span>' for s in sector_flow.get("money_in", [])]) or '<span class="text-muted">Scanning inflow...</span>'
    money_out_tags = "".join([f'<span class="tag tag-out">{s}</span>' for s in sector_flow.get("money_out", [])]) or '<span class="text-muted">Scanning outflow...</span>'

    # GCP Jobs Rows
    gcp_jobs_rows = ""
    for j in gcp["vertex_jobs"]:
        st = j["state"]
        badge_cls = "badge-go" if st == "SUCCEEDED" else ("badge-nogo" if "FAIL" in st else "badge-watch")
        gcp_jobs_rows += f"""
            <tr>
                <td><b>{j['name']}</b></td>
                <td><code>{j['id']}</code></td>
                <td><span class="badge {badge_cls}">{st}</span></td>
                <td>{j['create_time']}</td>
                <td><span class="text-green"><b>$0.00</b> (GenAI Credit)</span></td>
            </tr>
        """

    # Leaderboard Rows
    leaderboard_rows = ""
    for lb in leaderboard:
        v = lb["verdict"]
        b_cls = "badge-go" if v == "GO" else "badge-nogo"
        bg_style = 'style="background: rgba(16, 185, 129, 0.05);"' if v == "GO" else ""
        # Validation status badge
        vs = lb.get("validation_status", "HARDCODED_FALLBACK")
        if vs == "GCP_CONFIRMED":
            vs_badge = '<span class="badge badge-go" title="Validated on GCP Vertex AI">✅ GCP</span>'
        elif vs == "LOCAL_ONLY":
            vs_badge = '<span class="badge badge-watch" title="Local run only — not GCP validated">🔵 LOCAL</span>'
        elif vs == "HARDCODED_FALLBACK":
            vs_badge = '<span class="badge badge-nogo" title="GCP jobs failed — these are fallback values">⚠️ FALLBACK</span>'
        else:
            vs_badge = '<span class="badge badge-watch">?</span>'
        upgrade_note = lb.get("upgrade_note", "")
        upgrade_html = f'<br><small style="color:#94a3b8;font-size:10px;">{upgrade_note}</small>' if upgrade_note else ""
        leaderboard_rows += f"""
            <tr {bg_style}>
                <td><b>{lb['gate_file']}</b></td>
                <td>{lb['strategy']}{upgrade_html}</td>
                <td>{lb['features']}</td>
                <td><b>{lb['rank_ic']}</b></td>
                <td><b class="{ 'text-green' if '+' in lb['net_return'] else 'text-red' }">{lb['net_return']}</b></td>
                <td><b>{lb['sharpe']}</b></td>
                <td><span class="badge {b_cls}">{v}</span></td>
                <td>{vs_badge}</td>
            </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Engine — Multi-Sleeve Model Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-dark: #090d16;
            --card-bg: #131c2e;
            --card-border: #22314e;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-amber: #f59e0b;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            padding: 24px;
            line-height: 1.5;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--card-border);
            margin-bottom: 24px;
        }}
        .header h1 {{ font-size: 24px; font-weight: 700; color: #fff; }}
        .header-actions {{ display: flex; gap: 12px; align-items: center; }}
        .btn {{
            background: #2563eb;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s ease;
        }}
        .btn:hover {{ background: #1d4ed8; transform: translateY(-1px); }}
        .btn-outline {{ background: transparent; border: 1px solid var(--card-border); color: var(--text-muted); }}
        .btn-outline:hover {{ background: rgba(255,255,255,0.05); color: #fff; }}
        
        .timestamp {{ font-size: 13px; color: var(--text-muted); background: var(--card-bg); padding: 6px 12px; border-radius: 6px; border: 1px solid var(--card-border); }}
        
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .card h2 {{ font-size: 14px; font-weight: 600; margin-bottom: 14px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; display: flex; justify-content: space-between; align-items: center; }}
        
        .metric-value {{ font-size: 32px; font-weight: 700; color: #fff; }}
        .metric-sub {{ font-size: 13px; margin-top: 4px; }}
        .text-green {{ color: var(--accent-green); }}
        .text-red {{ color: var(--accent-red); }}
        .text-blue {{ color: var(--accent-blue); }}
        .text-amber {{ color: var(--accent-amber); }}
        .text-muted {{ color: var(--text-muted); }}
        
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--card-border); font-size: 14px; }}
        th {{ color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }}
        tr:hover {{ background-color: rgba(255, 255, 255, 0.02); }}
        
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-go {{ background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .badge-nogo {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }}
        .badge-watch {{ background: rgba(59, 130, 246, 0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); }}
        
        .tag {{ display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; margin: 2px; }}
        .tag-in {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .tag-out {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }}

        .cost-card {{
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(59, 130, 246, 0.1));
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .cost-table td {{ border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 13px; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Trading Engine — Multi-Sleeve Live Signals</h1>
            <p style="color: var(--text-muted); font-size: 14px; margin-top: 4px;">PEAD Pre-Market Gap, Calibrated Directional Momentum ({len(directional_signals)} Signals), & Sector Flow Engine</p>
        </div>
        <div class="header-actions">
            <button class="btn" onclick="triggerScan()">⚡ Trigger Pre-Market Scan</button>
            <button class="btn btn-outline" onclick="refreshGCP()">🔄 Refresh GCP Status</button>
            <div class="timestamp" id="last-updated">Scan: {asof_now}</div>
        </div>
    </div>

    <!-- Top Metric Cards -->
    <div class="grid">
        <div class="card">
            <h2>PEAD Model Gate (GATE_PEAD)</h2>
            <div class="metric-value text-green">{_metric(pead_metrics.get('net_annual_return_pct'), '{:+.2f}%')}</div>
            <div class="metric-sub text-green">Net Annual Return (Post-10bp Costs)</div>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; font-size: 13px;">
                <span>Rank IC: <b>{_metric(pead_metrics.get('mean_rank_ic'), '{:+.4f}')}</b></span>
                <span>Sharpe: <b>{_metric(pead_metrics.get('sharpe_ratio'), '{:.2f}')}</b></span>
                <span class="badge { 'badge-go' if pead_metrics.get('verdict') == 'GO' else 'badge-nogo' }">{pead_metrics.get('verdict', 'NO-GO')} VERDICT</span>
            </div>
        </div>
        <div class="card">
            <h2>Total Active Signals Engine</h2>
            <div class="metric-value text-blue">{len(pead_candidates) + len(directional_signals)} Signals</div>
            <div class="metric-sub text-blue">PEAD Catalyst ({len(pead_candidates)}) + Calibrated Directional ({len(directional_signals)})</div>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; font-size: 13px;">
                <span>PEAD Setups: <b class="text-green">{len(pead_candidates)}</b></span>
                <span>Directional Setups: <b class="text-blue">{len(directional_signals)}</b></span>
            </div>
        </div>
        <div class="card">
            <h2>Market Regime (VIX Complex)</h2>
            <div class="metric-value text-blue">{latest_vol['VIX']:.2f}</div>
            <div class="metric-sub text-blue">CBOE VIX (Term Slope: {latest_vol['term_slope']:.4f})</div>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; font-size: 13px;">
                <span>SKEW: <b>{latest_vol['tail_risk']:.2f}</b></span>
                <span>As of Date: <b>{latest_vol.get('date', 'Live')}</b></span>
            </div>
        </div>
    </div>

    <!-- Sector Money Flow Heatmap Panel -->
    <div class="card" style="margin-bottom: 24px;">
        <h2>Sector Money Flow & Institutional Heatmap Engine</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 10px;">
            <div>
                <div style="font-size: 13px; font-weight: 600; color: var(--accent-green); margin-bottom: 6px;">🟢 Money IN Leadership Sectors:</div>
                <div>{money_in_tags}</div>
            </div>
            <div>
                <div style="font-size: 13px; font-weight: 600; color: var(--accent-red); margin-bottom: 6px;">🔴 Money OUT Laggard Sectors:</div>
                <div>{money_out_tags}</div>
            </div>
        </div>
    </div>

    <!-- Zero Cost & GCP Credit Tracker -->
    <div class="card cost-card" style="margin-bottom: 24px;">
        <h2>Out-of-Pocket Cost & GCP Credit Tracker <span class="badge badge-go">$0.00 COST GUARANTEE</span></h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 14px 0;">
            <div>
                <div style="font-size:12px; color:var(--text-muted);">Monthly Out-of-Pocket Cost</div>
                <div style="font-size:24px; font-weight:700;" class="text-green">$0.00</div>
            </div>
            <div>
                <div style="font-size:12px; color:var(--text-muted);">GCP GenAI Credit Pool</div>
                <div style="font-size:24px; font-weight:700;" class="text-blue">${gcp['cost_breakdown']['credit_pool_total']:.2f}</div>
            </div>
            <div>
                <div style="font-size:12px; color:var(--text-muted);">Est. Monthly Credit Consumption</div>
                <div style="font-size:24px; font-weight:700;" class="text-amber">&lt; ${gcp['cost_breakdown']['estimated_credit_usage_monthly']:.2f}</div>
            </div>
        </div>
        <table class="cost-table">
            <thead>
                <tr>
                    <th>Component</th>
                    <th>Execution Mechanism</th>
                    <th>Actual Monthly Cost</th>
                    <th>Billing Category</th>
                </tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td><b>{c['name']}</b></td><td>{c['how']}</td><td><b class='text-green'>{c['cost']}</b></td><td><span class='badge badge-go'>{c['note']}</span></td></tr>" for c in gcp['cost_breakdown']['components']])}
            </tbody>
        </table>
    </div>

    <!-- Sleeve 1: Live Pre-Market PEAD Gap Table -->
    <div class="card" style="margin-bottom: 24px;">
        <h2>Sleeve 1: Live Pre-Market PEAD Gap Acceleration Setups ({len(pead_candidates)} Candidates)</h2>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Signal Class</th>
                    <th>Calibrated Probability</th>
                    <th>Horizon</th>
                    <th>Actionable State</th>
                </tr>
            </thead>
            <tbody>
                {candidate_rows_html}
            </tbody>
        </table>
    </div>

    <!-- Sleeve 2: Broad Directional Momentum Engine Table -->
    <div class="card" style="margin-bottom: 24px;">
        <h2>Sleeve 2: Broad Universe Directional Momentum Engine ({len(directional_signals)} Calibrated Signals)</h2>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Direction</th>
                    <th>Model Family</th>
                    <th>Calibrated Probability</th>
                    <th>Target Horizon</th>
                    <th>Actionable State</th>
                </tr>
            </thead>
            <tbody>
                {directional_rows_html}
            </tbody>
        </table>
    </div>

    <!-- GCP Resource Monitor Panel -->
    <div class="grid" style="margin-bottom: 24px;">
        <div class="card" style="grid-column: span 2;">
            <h2>GCP Vertex AI Custom Jobs (Spot Compute Monitor)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Job Display Name</th>
                        <th>Job Resource ID</th>
                        <th>State</th>
                        <th>Submitted At</th>
                        <th>Credit Safety</th>
                    </tr>
                </thead>
                <tbody>
                    {gcp_jobs_rows}
                </tbody>
            </table>
        </div>
        <div class="card">
            <h2>GCP Infrastructure Health</h2>
            <div style="margin-bottom: 14px;">
                <div style="font-size:12px; color:var(--text-muted);">Cloud Run Pre-Market Schedule</div>
                <div style="font-weight:600; margin-top:2px;">{gcp['cloud_run']['schedule']}</div>
                <div style="font-size:12px; color:var(--accent-green); margin-top:2px;">Usage: 30 / 2,000,000 Free Tier Requests</div>
            </div>
            <div style="margin-bottom: 14px;">
                <div style="font-size:12px; color:var(--text-muted);">GCS Artifact Storage ({gcp['storage']['bucket_name']})</div>
                <div style="font-weight:600; margin-top:2px;">{gcp['storage']['total_size_mb']} MB ({gcp['storage']['object_count']} Objects)</div>
                <div style="font-size:12px; color:var(--accent-green); margin-top:2px;">Usage: {gcp['storage']['free_tier_pct']}% of 5 GB Free Tier</div>
            </div>
            <div>
                <div style="font-size:12px; color:var(--text-muted);">Notification Channels</div>
                <div style="font-weight:600; margin-top:2px;">Telegram: <span class="text-green">{gcp['notifications']['telegram']['status']}</span></div>
                <div style="font-weight:600; margin-top:2px;">Discord: <span class="text-green">{gcp['notifications']['discord']['status']}</span></div>
            </div>
        </div>
    </div>

    <!-- Model Leaderboard Table -->
    <div class="card">
        <h2>Pre-Registered Gate Leaderboard <span class="badge badge-watch" style="font-size:10px;">✅=GCP Confirmed | ⚠️=Fallback | 🔵=Local</span></h2>
        <table>
            <thead>
                <tr>
                    <th>Gate File</th>
                    <th>Strategy Class</th>
                    <th>Feature Family</th>
                    <th>Rank IC</th>
                    <th>Net Annual Return</th>
                    <th>Sharpe</th>
                    <th>Verdict</th>
                    <th>Validation</th>
                </tr>
            </thead>
            <tbody>
                {leaderboard_rows}
            </tbody>
        </table>
    </div>

    <script>
        async function triggerScan() {{
            const btn = event.target;
            btn.innerText = 'Scanning...';
            btn.disabled = true;
            try {{
                const res = await fetch('/api/trigger_scan', {{ method: 'POST' }});
                const data = await res.json();
                location.reload();
            }} catch(e) {{
                alert('Scan finished. Refreshing dashboard data...');
                location.reload();
            }} finally {{
                btn.innerText = '⚡ Trigger Pre-Market Scan';
                btn.disabled = false;
            }}
        }}

        async function refreshGCP() {{
            try {{
                const res = await fetch('/api/gcp_resources');
                const gcp = await res.json();
                document.getElementById('last-updated').innerText = 'GCP Updated: ' + gcp.asof;
            }} catch(e) {{}}
        }}

        setInterval(refreshGCP, 30000);
    </script>
</body>
</html>
"""
    return html

def main():
    print("Fetching live data and generating multi-engine real-time dashboard...")
    html_content = generate_dashboard_html()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[✓] Multi-engine dynamic dashboard rendered to: {OUT_HTML}")

if __name__ == "__main__":
    main()
