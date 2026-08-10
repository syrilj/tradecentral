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

  GET|POST /api/trigger_scan?depth=<quick|deep>
      -> re-runs the 25-name quick scan or complete frozen-domain deep scan
         and returns {status, message, asof, data}.

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

  GET  /api/options?symbol=X&mode=<live|history>&range=<1d|5d|1m|3m>
      -> truth-preserving call/put activity, stock overlay, gamma-by-strike,
         risk-neutral range diagnostics, provenance, and filter accounting.

  GET|POST /api/options/backfill_oi?symbol=X[&max_dte=60]
      -> Live OI capture for one symbol (tools/backfill_option_oi.py, run
         in-process via yfinance). Writes
         data/option_chains/date=<today>/<SYMBOL>.parquet and evicts that
         symbol's /api/options cache entries so the next fetch reflects it
         immediately. {status:"ok", symbol, asof, contracts, with_oi} on
         success; 404 {status:"error", symbol, message} when the provider
         has no chain for the symbol at all.

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

  GET  /api/market-clock
      -> XNYS session state, authoritative regular open/close, early-close
         status, next transition, and the calendar source used.

  GET  /api/health
      -> {ok, ts, symbols_indexed, uptime_s}

  GET  /api/sentiment[?symbol=X]
      -> Accuracy-first desk sentiment: vol complex, CFTC COT, FINRA short
         volume, local options P/C, optional SEC filings for symbol.
         Every block carries asof/source/quality; never fabricates HF books.

  GET  /api/anomalies[?limit=40&symbol=X]
      -> Statistical outliers: price/volume z-scores, FINRA short extremes,
         options P/C extremes, SEC filing activity. Thresholded + source-tagged.

  GET  /api/unusual-flow[?limit=40&min_premium=25000]
      -> Market-wide unusual options-flow board (live LSE tape on hot names +
         liquid seeds). Ordinal attention rank — not a trade signal.

  GET  /api/ga[?run_id=X]
      -> Genetic evolution lab: list of runs under runs/ga/, optional detail
         for run_id (defaults to LATEST). Research-only; decision_authorized
         is always false.

  GET  /api/graph[?max_nodes=400]
      -> Repo knowledge graph built by tools/graphify_index.py, read from
         runs/graph/. Topology only (no coordinates) — the client owns layout,
         so the same graph draws identically every load. Capped by descending
         degree; `stats.truncated` says whether anything was dropped.
         Returns {available: false, reason} before the repo has been indexed.

  GET  /api/factors
      -> Latest factor tearsheet written by tools/factor_tearsheet.py
         (runs/factor_diagnostics/latest.json): IC decay by horizon, quantile
         returns, and turnover by quantile. DIAGNOSTIC ONLY — computed outside
         research/portfolio.py::simulate_long_short, so it is not gate
         evidence. Returns {available: false, reason} until the tool is run.

  GET  /api/changepoints[?symbol=X&window=<1m|3m|6m|1y|3y|5y|max, default 1y>]
      -> Bayesian Online Changepoint Detection (Adams & MacKay 2007,
         arXiv:0710.3742) on daily returns. Without `symbol`, the
         cross-section: the latest artifact written by
         tools/build_changepoints.py (runs/changepoints/latest.json) — the
         same "read an offline artifact, never compute on request" contract
         as /api/graph and /api/factors above. With `symbol`, the one live
         compute path this endpoint has: BOCPD run over that symbol's full
         daily history, windowed for display only (the model itself always
         sees the whole series, never just the window, so run lengths at the
         window's start are not falsely reset to zero). Returns
         {available: false, reason} for an unresolvable symbol or fewer than
         60 usable daily bars. Research/diagnostic only — never authorizes a
         trade.

  GET  /api/flow-state
      -> Latent flow-state cross-section (forced-flow shocks / cascades /
         absorption / fade) written by tools/build_flow_state.py
         (runs/flow_state/latest.json) — offline artifact only, same
         contract as /api/changepoints without ?symbol. Daily-bar proxies
         only (no order-book depth anywhere in this repo); tier 0/1 today
         (states + matched-control validation, if a study has been run);
         models stay null and decision_authorized stays false until a
         Phase-3 development gate exists and passes. Returns
         {available: false, reason} before the builder has been run.

  GET  /api/adaptive-signal[?symbol=X&limit=40]
      -> Regime-aware multi-stream live blend (technical, sector, sentiment,
         fundamental). Prefers 1h bars when present (else daily). Weights shift
         with vol×trend regime and rolling shadow stream hit-rates when enough
         realized outcomes exist. score_kind=ordinal_adaptive_blend; never
         authorizes trades or capital.

  GET  /api/fintel/status
      -> Whether FINTEL_API_KEY is configured (never returns the key).

  GET  /api/fintel/stream[?squeeze_limit=40]
      -> Polled Fintel market boards: short-squeeze / short-interest / gainers /
         losers / volume leaderboards + earnings/dividend calendars. Analysis-only.

  GET  /api/fintel/intel?symbol=X[&country=US]
      -> Per-symbol Fintel intel bundle: short interest, borrow, FTD, owners,
         insiders, price targets, unusual options flow, analysis notes.

  GET  /api/fintel/search?q=<str>[&limit=25&country=US]
      -> Fintel security master search.

  Neither /api/graph nor /api/factors computes anything on request. Both read
  artifacts produced offline, so a dashboard poll can never kick off a graph
  rebuild or a walk-forward. A missing artifact is reported missing, never
  manufactured.

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
import concurrent.futures
from dataclasses import asdict
import http.server
import json
import math
import mimetypes
import os
import re
import socketserver
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = ROOT / "edge"
DATA_WIDE_DIR = EDGE_DIR / "data" / "1d_wide"
DATA_CORE_DIR = EDGE_DIR / "data" / "1d"
DATA_SMALLCAP_DIR = EDGE_DIR / "data" / "1d_smallcap"
RUNS_DIR = EDGE_DIR / "runs"
DOCS_DIR = EDGE_DIR / "docs"
TOOLS_DIR = EDGE_DIR / "tools"
DIST_DIR = RUNS_DIR / "dashboard_dist"

PORT = 8787
LOOPBACK_HOST = "127.0.0.1"
SERVER_START_TS = time.time()

import types
if 'edge' not in sys.modules:
    _edge_mod = types.ModuleType('edge')
    _edge_mod.__path__ = [str(EDGE_DIR)]
    sys.modules['edge'] = _edge_mod

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))
sys.path.insert(0, str(TOOLS_DIR))
from render_dashboard import (  # noqa: E402
    get_dashboard_data as _get_dashboard_data_uncached,
    analyze_symbol_adhoc,
    load_dynamic_leaderboard,
)
from check_gcp_resources import get_all_gcp_resources  # noqa: E402
from sentiment_anomalies import (  # noqa: E402
    build_anomalies_payload,
    build_sentiment_payload,
)
from backfill_option_oi import capture as _capture_option_oi  # noqa: E402
from momentum_scan import build_momentum_scan  # noqa: E402
from fetch_float_data import load_float_data  # noqa: E402

sys.path.insert(0, str(ROOT))
from edge.daily_plays.config import load_project_environment  # noqa: E402
from edge.daily_plays.clock import market_clock_status  # noqa: E402
from edge.daily_plays.options_intelligence import (  # noqa: E402
    OptionsFilters,
    build_options_intelligence,
)
from edge.daily_plays.options_board import (  # noqa: E402
    board_payload as _options_board_wire,
    select_board_candidates,
    summarize_board_row,
)
from edge.daily_plays.adapters.options import LSEOptionsAdapter  # noqa: E402
from edge.daily_plays.live_activity import build_unusual_options_flow  # noqa: E402
from edge.daily_plays.opportunity_scanner import build_live_opportunities  # noqa: E402
from edge.daily_plays.qlib_scan_score import (  # noqa: E402
    SCORE_KIND as QLIB_SCORE_KIND,
    SOURCE_ID as QLIB_SOURCE_ID,
    lookup_symbol_on_shared_panel,
)
from edge.daily_plays.adaptive_signal import (  # noqa: E402
    AdaptiveSignalInputs,
    market_sentiment_from_dashboard_blocks,
    scan_adaptive_signals,
    score_symbol,
)
from edge.daily_plays.stream_hit_rates import (  # noqa: E402
    load_stream_performance_from_shadow,
)
from edge.research.ga.storage import run_payload as _ga_run_payload  # noqa: E402
from edge.research.bocpd import BocpdResult, changepoints_from_prices  # noqa: E402
from edge.daily_plays.adapters.fintel import (  # noqa: E402
    FintelAuthError,
    FintelClient,
    FintelQuotaError,
    fetch_market_stream,
    fetch_security_intel,
    search_securities as fintel_search_securities,
    status_payload as fintel_status_payload,
)

DATA_1H_DIR = EDGE_DIR / "data" / "1h"
_FINTEL_STREAM_CACHE: dict[str, Any] = {"ts": 0.0, "key": None, "payload": None}
# Long TTL — Fintel monthly weight is scarce; avoid re-hitting on every desk poll.
_FINTEL_STREAM_TTL_S = 600.0
_FINTEL_QUOTA_TTL_S = 3600.0
_FINTEL_INTEL_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_FINTEL_INTEL_TTL_S = 900.0
_FINTEL_INTEL_LOCK = threading.Lock()
_STREAM_HIT_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_STREAM_HIT_TTL_S = 120.0
# Conviction board: N live chain fetches per build, so cache harder than the
# single-symbol view and never rebuild it on an incidental desk poll.
_OPTIONS_BOARD_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_OPTIONS_BOARD_TTL_S = 300.0
_OPTIONS_BOARD_LOCK = threading.Lock()
_OPTIONS_BOARD_BUILD_LOCKS: dict[tuple[Any, ...], threading.Lock] = {}
_OPTIONS_BOARD_MAX_WORKERS = 6

load_project_environment(paths=(EDGE_DIR / ".env", ROOT / "TradingWork" / ".env"))


# ---------------------------------------------------------------------------
# Research artifacts: knowledge graph and factor tearsheet.
#
# Both are produced by offline tools and read from disk here. Neither is
# computed on request — a dashboard poll must never kick off a graph rebuild or
# a walk-forward, and a missing artifact is reported as missing rather than
# manufactured. `available: false` plus a `reason` is a normal, expected
# response before the corresponding tool has been run; the views render it as
# an empty state with the command needed to populate it.
# ---------------------------------------------------------------------------

GRAPH_DIR = RUNS_DIR / "graph"
FACTOR_DIR = RUNS_DIR / "factor_diagnostics"
CHANGEPOINT_DIR = RUNS_DIR / "changepoints"
FLOW_STATE_DIR = RUNS_DIR / "flow_state"


def _load_symbol_bars(symbol: str, *, prefer_intraday: bool = True) -> pd.DataFrame:
    """OHLCV for adaptive scoring: prefer 1h when present so the blend moves intraday."""
    bases: list[Path] = []
    if prefer_intraday:
        bases.append(DATA_1H_DIR)
    bases.extend([DATA_WIDE_DIR, DATA_CORE_DIR])
    for base in bases:
        path = base / f"{symbol}.parquet"
        if path.is_file():
            try:
                frame = pd.read_parquet(path)
            except Exception:
                continue
            if frame is not None and len(frame) > 0:
                return frame
    return pd.DataFrame()


def _stream_performance_payload() -> dict[str, Any]:
    """Rolling shadow hit-rates (cached) for soft weight adaptation."""
    now = time.time()
    cached = _STREAM_HIT_CACHE.get("payload")
    if cached is not None and now - float(_STREAM_HIT_CACHE.get("ts") or 0) < _STREAM_HIT_TTL_S:
        return cached

    def loader(symbol: str) -> pd.DataFrame:
        # Hit-rate reconstruction uses the same bar preference as live scoring.
        return _load_symbol_bars(symbol, prefer_intraday=True)

    try:
        payload = load_stream_performance_from_shadow(
            candle_loader=loader,
            lookback_events=60,
            # Soft floor: need a handful of directional stream calls before
            # tilting weights.  With sparse shadow journals this stays empty
            # and the blend uses regime weights only.
            min_events=5,
        )
    except Exception as exc:  # noqa: BLE001 - degrade to regime-only weights
        payload = {
            "schema_version": "stream-hit-rates-v1",
            "score_kind": "rolling_shadow_hit_rate",
            "decision_authorized": False,
            "stream_performance": {},
            "quality": "missing",
            "error": f"{type(exc).__name__}: {exc}",
            "caveat": "Shadow hit-rate computation failed; using regime weights only.",
        }
    _STREAM_HIT_CACHE["ts"] = now
    _STREAM_HIT_CACHE["payload"] = payload
    return payload


def _sector_context_map(status: Mapping | None) -> dict[str, dict]:
    """Map symbols → sector flow context from the latest dashboard status blob."""
    flow = (status or {}).get("sector_flow") if isinstance(status, dict) else None
    if not isinstance(flow, Mapping):
        return {}
    out: dict[str, dict] = {}

    def _put(symbol: str, row: Mapping) -> None:
        sym = str(symbol or "").strip().upper().removesuffix(".US")
        if not sym or sym in out:
            return
        out[sym] = {
            "sector_etf": row.get("etf") or row.get("sector_etf"),
            "sector_name": row.get("name") or row.get("sector") or row.get("sector_name"),
            "flow_direction": row.get("flow_direction") or row.get("day_direction") or row.get("direction"),
            "flow_score": row.get("flow_score") or row.get("definitive_score"),
            "rs_1d": row.get("rs_1d"),
            "rs_5d": row.get("rs_5d"),
        }

    for row in flow.get("sectors_ranked") or []:
        if not isinstance(row, Mapping):
            continue
        etf = row.get("etf")
        if etf:
            _put(str(etf), row)
        for name in row.get("focus_names") or row.get("names") or []:
            _put(str(name).split()[0], row)
    for row in flow.get("watch_names") or []:
        if isinstance(row, Mapping):
            _put(str(row.get("symbol") or ""), row)
    return out


def _fundamental_context_map(status: Mapping | None) -> dict[str, dict]:
    """Attach PEAD / short-context ordinals when the status scan already has them."""
    status = status if isinstance(status, Mapping) else {}
    out: dict[str, dict] = {}
    for row in status.get("pead_candidates") or []:
        if not isinstance(row, Mapping):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out[sym] = {
            "pead_score": row.get("score") or row.get("ordinal_score") or row.get("pead_score"),
            "catalyst_score": row.get("catalyst_score"),
        }
    return out


def _adaptive_board_symbols(status: Mapping | None, *, limit: int) -> list[str]:
    """Prefer liquid names already on the desk, then fill from local wide catalog."""
    status = status if isinstance(status, Mapping) else {}
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        sym = str(raw or "").strip().upper().removesuffix(".US")
        if not sym or sym in seen:
            return
        seen.add(sym)
        ordered.append(sym)

    for key in ("directional_signals", "pead_candidates", "activity_flags", "market_activity"):
        block = status.get(key)
        if isinstance(block, list):
            for row in block:
                if isinstance(row, Mapping):
                    _add(row.get("symbol"))
                else:
                    _add(row)
        elif isinstance(block, Mapping):
            for row in block.get("rows") or []:
                if isinstance(row, Mapping):
                    _add(row.get("symbol"))

    # Seed majors so the board is never empty when scans are cold.
    for sym in ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"):
        _add(sym)

    if DATA_WIDE_DIR.is_dir():
        for path in sorted(DATA_WIDE_DIR.glob("*.parquet")):
            if len(ordered) >= max(limit * 3, 80):
                break
            _add(path.stem)

    return ordered[: max(limit * 3, 40)]


def _adaptive_signal_payload(*, symbol: str | None = None, limit: int = 40) -> dict:
    """Build live adaptive blend for one symbol or a ranked board."""
    status = get_dashboard_data()
    sector_map = _sector_context_map(status)
    fund_map = _fundamental_context_map(status)
    vol = status.get("latest_vol") if isinstance(status, Mapping) else None
    try:
        sentiment_payload = build_sentiment_payload(symbol=symbol)
    except Exception:
        sentiment_payload = {}
    market_sentiment = market_sentiment_from_dashboard_blocks(
        vol=vol if isinstance(vol, Mapping) else None,
        sentiment_payload=sentiment_payload if isinstance(sentiment_payload, Mapping) else None,
    )
    hit_payload = _stream_performance_payload()
    stream_performance = (
        hit_payload.get("stream_performance")
        if isinstance(hit_payload.get("stream_performance"), Mapping)
        else {}
    )

    def loader(sym: str) -> pd.DataFrame:
        return _load_symbol_bars(sym, prefer_intraday=True)

    if symbol:
        row = score_symbol(
            AdaptiveSignalInputs(
                symbol=symbol,
                bars=loader(symbol),
                sector_context=sector_map.get(symbol),
                market_sentiment=market_sentiment,
                fundamental_context=fund_map.get(symbol),
                stream_performance=stream_performance or None,
            )
        )
        return {
            "mode": "symbol",
            "symbol": symbol,
            "asof": row.get("asof"),
            "board": None,
            "signal": row,
            "stream_hit_rates": hit_payload,
            "decision_authorized": False,
            "live_capital_authorized": False,
        }

    symbols = _adaptive_board_symbols(status, limit=limit)
    board = scan_adaptive_signals(
        symbols=symbols,
        candle_loader=loader,
        sector_by_symbol=sector_map,
        market_sentiment=market_sentiment,
        fundamental_by_symbol=fund_map,
        stream_performance=stream_performance or None,
        row_limit=limit,
    )
    return {
        "mode": "board",
        "symbol": None,
        "asof": board.get("asof"),
        "board": board,
        "signal": None,
        "stream_hit_rates": hit_payload,
        "decision_authorized": False,
        "live_capital_authorized": False,
    }


def _graph_payload(max_nodes: int) -> dict:
    """Repo knowledge graph, trimmed to what a browser can lay out.

    The import is deliberately deferred rather than hoisted to module scope:
    `graphify_payload` is an optional research tool, and the whole API server
    failing to start because a knowledge-graph helper is absent would be a
    poor trade. A missing helper degrades this one endpoint, nothing else.
    """
    try:
        from graphify_payload import build_graph_payload  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"graphify_payload unavailable: {type(e).__name__}: {e}",
            "generated_at": None,
            "stats": None,
            "communities": [],
            "nodes": [],
            "edges": [],
        }
    try:
        return build_graph_payload(GRAPH_DIR, max_nodes=max_nodes)
    except Exception as e:  # noqa: BLE001
        # build_graph_payload is contracted not to raise on absent/malformed
        # input, so reaching here means a genuine bug rather than "no graph
        # yet". Surface the exception type instead of flattening it into the
        # same empty state a never-indexed repo produces — those two cases
        # need different actions from whoever is reading the screen.
        return {
            "available": False,
            "reason": f"graph payload failed: {type(e).__name__}: {e}",
            "generated_at": None,
            "stats": None,
            "communities": [],
            "nodes": [],
            "edges": [],
        }


def _factor_tearsheet_payload() -> dict:
    """Latest factor tearsheet written by tools/factor_tearsheet.py."""
    empty = {
        "available": False,
        "reason": None,
        "generated_at": None,
        "source": None,
        "n_dates": 0,
        "n_symbols": 0,
        "execution_lag": 1,
        "monotonicity": None,
        "ic_decay": [],
        "quantiles": [],
        "quantile_turnover": [],
    }
    latest = FACTOR_DIR / "latest.json"
    if not latest.is_file():
        return {**empty, "reason": f"no tearsheet at {latest.relative_to(EDGE_DIR)}"}
    try:
        with latest.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return {**empty, "reason": f"unreadable tearsheet: {type(e).__name__}: {e}"}
    if not isinstance(payload, dict):
        return {**empty, "reason": "tearsheet is not a JSON object"}
    # Fill only absent keys. A tearsheet that genuinely computed `monotonicity`
    # as null must keep its null — overwriting a measured absence with a
    # default is how a broken run starts looking like a successful one.
    return {**empty, **payload, "available": bool(payload.get("available", True))}


# ---------------------------------------------------------------------------
# BOCPD changepoint surface (Adams & MacKay 2007, arXiv:0710.3742).
#
# Cross-section (`?symbol` absent) reads the offline artifact written by
# tools/build_changepoints.py, mirroring `_factor_tearsheet_payload`'s
# defensive read exactly. `?symbol=` is this endpoint's one on-request
# compute path -- a single symbol's daily-bar BOCPD run, never the whole
# universe.
#
# Model constants mirror BOCPD_CONTRACT.md's "Model defaults (single source
# of truth)" section and tools/build_changepoints.py's copy of the same
# numbers -- keep all three in sync if the contract ever changes.
# ---------------------------------------------------------------------------
_BOCPD_LAMBDA_GAP = 250.0
_BOCPD_PRIOR_A = 1.0
_BOCPD_PRIOR_B = 1e-4
_BOCPD_TRUNCATION_MASS = 1e-4
# AMENDMENT 1 (BOCPD_CONTRACT.md): P(r_t=0|x_1:t) is provably constant (= the
# hazard rate) under a constant hazard -- see research/bocpd.py's module
# docstring for the eq. 3-4 derivation -- so it carries zero detection
# information and cannot be a threshold target. `break_prob` = P(r_t<=5|x_1:t)
# replaces it; 0.50 is the contract's measured midpoint between a stable
# regime (~0.015) and an actual break (~1.0).
_BOCPD_BREAK_THRESHOLD = 0.50
_BOCPD_SETTLING_RUNS = 10
_BOCPD_MIN_BARS = 60
_BOCPD_REFERENCE = "Adams & MacKay 2007, arXiv:0710.3742"
_BOCPD_LOG_FLOOR = -6.0
_BOCPD_MAX_ROWS = 130
_BOCPD_MAX_COLS = 260

# Single-symbol BOCPD is the one live-compute path on this endpoint; cache it
# briefly so a dashboard poll re-hitting the same symbol/window does not
# re-run the recursion every request. Same shape/eviction as
# `_FINTEL_INTEL_CACHE` above.
_CHANGEPOINT_SYMBOL_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_CHANGEPOINT_SYMBOL_TTL_S = 120.0
_CHANGEPOINT_SYMBOL_LOCK = threading.Lock()


def _bocpd_model_meta() -> dict:
    return {
        "observation": "gaussian_variance",
        "hazard": "constant",
        "lambda_gap": _BOCPD_LAMBDA_GAP,
        "prior": {"a": _BOCPD_PRIOR_A, "b": _BOCPD_PRIOR_B},
        "truncation_mass": _BOCPD_TRUNCATION_MASS,
        "reference": _BOCPD_REFERENCE,
    }


def _bocpd_thresholds() -> dict:
    return {"break": _BOCPD_BREAK_THRESHOLD, "settling": _BOCPD_SETTLING_RUNS}


def _changepoints_payload() -> dict:
    """Latest cross-section written by tools/build_changepoints.py (payload A)."""
    empty = {
        "available": False,
        "reason": None,
        "generated_at": None,
        "source": None,
        "asof": None,
        "model": _bocpd_model_meta(),
        "thresholds": _bocpd_thresholds(),
        "n_symbols": 0,
        "lookback_days": None,
        "symbols": [],
    }
    latest = CHANGEPOINT_DIR / "latest.json"
    if not latest.is_file():
        return {**empty, "reason": f"no changepoint artifact at {latest.relative_to(EDGE_DIR)}"}
    try:
        with latest.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return {**empty, "reason": f"unreadable changepoint artifact: {type(e).__name__}: {e}"}
    if not isinstance(payload, dict):
        return {**empty, "reason": "changepoint artifact is not a JSON object"}
    # Same "fill only absent keys" discipline as _factor_tearsheet_payload:
    # a genuinely-computed null must survive, never get papered over by a
    # default that would make a broken run look like a clean empty state.
    return {**empty, **payload, "available": bool(payload.get("available", True))}


def _flow_state_payload() -> dict:
    """Latest cross-section written by tools/build_flow_state.py.

    Same "read an offline artifact, never compute on request" contract as
    _changepoints_payload above: a missing/malformed artifact degrades to
    `available: false` + `reason`, never raises, and never manufactures
    data. `models` stays `null` until Phase 3 (cascade/fade ML models)
    exists and a passing development-gate record raises `tier` to >= 2.
    """
    empty = {
        "available": False,
        "reason": None,
        "as_of": None,
        "tier": 0,
        "decision_authorized": False,
        "caveats": [],
        "states": [],
        "timelines": {},
        "events": [],
        "barrier_fields": {},
        "impact_curve": {"lags": [], "mean_cum_ret": [], "ci_lo": [], "ci_hi": []},
        "phenomenon": {
            "tested": False, "effect": None, "nw_t": None, "boot_ci": None,
            "perm_p": None, "n_events": 0, "n_controls": 0, "grid": [],
            "prereg_id": None, "passed": False,
        },
        "gate": {"evaluated": False, "passed": False, "checks": {}, "ledger_id": None},
        "models": None,
        "producing_script": "tools/build_flow_state.py",
    }
    latest = FLOW_STATE_DIR / "latest.json"
    if not latest.is_file():
        try:
            shown_path = latest.relative_to(EDGE_DIR)
        except ValueError:
            # FLOW_STATE_DIR is monkeypatched outside EDGE_DIR in tests;
            # fall back to the absolute path rather than raising here.
            shown_path = latest
        return {**empty, "reason": f"no flow-state artifact at {shown_path}"}
    try:
        with latest.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return {**empty, "reason": f"unreadable flow-state artifact: {type(e).__name__}: {e}"}
    if not isinstance(payload, dict):
        return {**empty, "reason": "flow-state artifact is not a JSON object"}
    return {**empty, **payload, "available": bool(payload.get("available", True))}


def _bocpd_align_dates(index: pd.DatetimeIndex, arr_len: int) -> pd.DatetimeIndex:
    """Map a BocpdResult array back onto dates.

    BOCPD_CONTRACT.md documents `BocpdResult`'s arrays as "per bar" without
    pinning whether that means aligned to `close` (length T) or to the
    derived return series R_t = p_t/p_{t-1} - 1 (length T-1, since the first
    bar has no prior close to form a return against). Accept either without
    guessing silently; any other length is a genuine mismatch with
    research/bocpd.py's contract and must raise, not misalign dates quietly.
    Kept in sync with tools/build_changepoints.py::_align_dates.
    """
    if arr_len == len(index):
        return index
    if arr_len == len(index) - 1:
        return index[1:]
    raise ValueError(
        f"BocpdResult array length {arr_len} does not align with close index "
        f"length {len(index)} (expected {len(index)} or {len(index) - 1})"
    )


def _changepoint_row_from_result(
    symbol: str, close: pd.Series, aligned_index: pd.DatetimeIndex, result: BocpdResult,
) -> dict | None:
    """The exact payload-A per-symbol row shape, built from an already-run result.

    Field-for-field the same construction as
    tools/build_changepoints.py::_process_symbol's row (kept in sync
    deliberately, not imported, since this one runs over whatever history
    `_changepoint_symbol_payload` fed the model rather than a lookback-capped
    batch run) -- this is what BOCPD_CONTRACT.md's payload B `stats` field
    means by "the exact per-symbol row object from A, for this symbol".
    """
    # `cp_prob_raw` is deliberately NOT read here (AMENDMENT 1): it is
    # constant by construction and never emitted in any payload. `break_prob`
    # / `break_prob_20` are the real, data-responsive detection statistics,
    # computed by research/bocpd.py itself -- never re-derived here.
    break_prob_arr = np.asarray(result.break_prob, dtype=float)
    break_prob_20_arr = np.asarray(result.break_prob_20, dtype=float)
    map_run_arr = np.asarray(result.map_run_length)
    exp_run_arr = np.asarray(result.expected_run_length, dtype=float)
    pred_std_arr = np.asarray(result.pred_std, dtype=float)
    defined_mass_arr = np.asarray(result.pred_var_defined_mass, dtype=float)
    if len(break_prob_arr) == 0:
        return None
    last_break_prob = float(break_prob_arr[-1])
    last_break_prob_20 = float(break_prob_20_arr[-1])
    last_map_run = map_run_arr[-1]
    last_exp_run = float(exp_run_arr[-1])
    # These four are sums/argmax over a normalized probability distribution
    # and should be finite by construction -- if one isn't, this is a broken
    # computation for this symbol, not a per-field null.
    if not all(math.isfinite(v) for v in (last_break_prob, last_break_prob_20, float(last_map_run), last_exp_run)):
        return None
    map_run_last = int(last_map_run)

    # `pred_std`/`pred_var_defined_mass`, unlike the four checked above, CAN
    # legitimately be undefined at a bar where every live hypothesis has
    # dof<=2 (see research/bocpd.py's pred_var docstring) -- real information
    # ("no defined-variance mass left"), not a broken run, so it becomes a
    # `null` field rather than dropping the whole symbol.
    last_pred_std = float(pred_std_arr[-1])
    predictive_vol = last_pred_std if math.isfinite(last_pred_std) else None
    last_defined_mass = float(defined_mass_arr[-1])
    predictive_vol_defined_mass = last_defined_mass if math.isfinite(last_defined_mass) else None

    rets = close.pct_change().dropna()
    last_return = float(rets.iloc[-1]) if len(rets) else None
    trailing_vol_20d = None
    if len(rets) >= 2:
        v = float(rets.tail(20).std(ddof=1))
        trailing_vol_20d = v if math.isfinite(v) else None
    vol_ratio = None
    if predictive_vol is not None and trailing_vol_20d not in (None, 0.0):
        vol_ratio = predictive_vol / trailing_vol_20d

    break_mask = break_prob_arr >= _BOCPD_BREAK_THRESHOLD
    if break_mask.any():
        break_idx = int(np.nonzero(break_mask)[0][-1])
        last_break_date = aligned_index[break_idx].strftime("%Y-%m-%d")
        days_since_break = int(len(aligned_index) - 1 - break_idx)
    else:
        last_break_date = None
        days_since_break = None

    if last_break_prob >= _BOCPD_BREAK_THRESHOLD:
        regime = "BREAK"
    elif map_run_last <= _BOCPD_SETTLING_RUNS:
        regime = "SETTLING"
    else:
        regime = "STABLE"

    return {
        "symbol": symbol,
        "n_bars": int(len(close)),
        "last_date": close.index[-1].strftime("%Y-%m-%d"),
        "break_prob": _safe_round(last_break_prob, 6),
        "break_prob_20": _safe_round(last_break_prob_20, 6),
        "map_run_length": map_run_last,
        "expected_run_length": _safe_round(last_exp_run, 6),
        "last_break_date": last_break_date,
        "days_since_break": days_since_break,
        "predictive_vol": _safe_round(predictive_vol, 6),
        "predictive_vol_defined_mass": _safe_round(predictive_vol_defined_mass, 6),
        "trailing_vol_20d": _safe_round(trailing_vol_20d, 6),
        "vol_ratio": _safe_round(vol_ratio, 6),
        "last_return": _safe_round(last_return, 6),
        "regime": regime,
    }


def _bocpd_runlength_heatmap(
    result: BocpdResult, pos_in_window: np.ndarray, aligned_index: pd.DatetimeIndex,
) -> dict:
    """The paper's Fig-3-bottom heatmap, trimmed to the window and downsampled.

    Per BOCPD_CONTRACT.md: row-major, rows = run length, values = log10
    P(r|x_1:t) clipped to [log_floor, 0], null where the run length exceeds
    elapsed time (structurally impossible) or the probability is below
    log_floor. Downsampling strides both axes; row-groups are MAX-pooled (in
    probability space, before the log — max(log10(p)) == log10(max(p)) since
    log10 is monotonic) so a sharp ridge across run lengths is never averaged
    away, while columns are picked by plain stride since adjacent bars are
    distinct time points that must not be blended.

    Safe to treat `full[row, col]` as literally "P(run_length=row | x_1:col)"
    ONLY because `BocpdResult.run_length_posterior()` scatters each
    hypothesis by its TRUE run-length label, not by its array position --
    research/bocpd.py's §2.4 truncation can (and in steady state does) drop
    hypotheses out of the middle of the array, so "position == run length"
    is false for the raw `run_length_posteriors` list and would silently
    mislabel this whole heatmap if assumed here. This function never touches
    that raw list directly, only the dense matrix `run_length_posterior()`
    already fixed up -- verified against research/bocpd.py's source, not
    assumed.
    """
    empty = {
        "dates": [], "run_values": [], "n_rows": 0, "n_cols": 0,
        "log_floor": _BOCPD_LOG_FLOOR, "matrix": [],
    }
    try:
        full = np.asarray(result.run_length_posterior(), dtype=float)
    except Exception:  # noqa: BLE001
        return empty
    if full.ndim != 2 or full.shape[0] == 0 or full.shape[1] == 0:
        return empty

    n_rows_full, n_cols_full = full.shape
    t_full = min(n_cols_full, len(aligned_index))
    cols = np.asarray(pos_in_window, dtype=int)
    cols = cols[cols < t_full]
    if len(cols) == 0:
        return empty

    win = full[:, cols]

    # Crop vertical extent to active run-length range (plus buffer) so heatmap
    # doesn't waste 80% height on empty space
    active_rows = np.nonzero(win >= 10**_BOCPD_LOG_FLOOR)[0]
    if len(active_rows) > 0:
        max_active_r = int(active_rows.max())
        r_limit = min(n_rows_full, max(60, max_active_r + 15))
    else:
        r_limit = min(n_rows_full, 120)
    win = win[:r_limit, :]
    n_rows_crop = r_limit

    row_step = max(1, math.ceil(n_rows_crop / _BOCPD_MAX_ROWS))
    row_starts = list(range(0, n_rows_crop, row_step))
    pooled = np.stack([win[r:r + row_step, :].max(axis=0) for r in row_starts], axis=0)
    run_values = row_starts

    col_step = max(1, math.ceil(len(cols) / _BOCPD_MAX_COLS))
    col_sel = list(range(0, len(cols), col_step))
    pooled = pooled[:, col_sel]
    sel_cols = cols[col_sel]
    dates = [aligned_index[c].strftime("%Y-%m-%d") for c in sel_cols]

    matrix: list[list[float | None]] = []
    for i, run_value in enumerate(run_values):
        row_out: list[float | None] = []
        for j, t_global in enumerate(sel_cols):
            if run_value > t_global:
                row_out.append(None)  # structurally impossible: r > t
                continue
            p = float(pooled[i, j])
            if not math.isfinite(p) or p <= 0.0:
                row_out.append(None)
                continue
            log_p = math.log10(p)
            if log_p < _BOCPD_LOG_FLOOR:
                row_out.append(None)
                continue
            row_out.append(round(min(log_p, 0.0), 3))
        matrix.append(row_out)

    return {
        "dates": dates,
        "run_values": run_values,
        "n_rows": len(run_values),
        "n_cols": len(dates),
        "log_floor": _BOCPD_LOG_FLOOR,
        "matrix": matrix,
    }


def _changepoint_symbol_cache_put(key: tuple[str, str], payload: dict) -> None:
    with _CHANGEPOINT_SYMBOL_LOCK:
        _CHANGEPOINT_SYMBOL_CACHE[key] = (time.time(), payload)
        if len(_CHANGEPOINT_SYMBOL_CACHE) > 64:
            oldest = min(_CHANGEPOINT_SYMBOL_CACHE, key=lambda k: _CHANGEPOINT_SYMBOL_CACHE[k][0])
            _CHANGEPOINT_SYMBOL_CACHE.pop(oldest, None)


def _changepoint_symbol_payload(symbol: str, window: str) -> dict:
    """Payload B: one symbol's BOCPD run, computed live and cached briefly.

    Uses `_load_symbol_bars(symbol, prefer_intraday=False)` -- always daily
    bars, never 1h, because this is a daily-returns model and intraday bars
    would silently change the meaning of every number (lambda_gap=250 is a
    ~1-year-of-trading-days hazard horizon, not a ~1-year-of-hours one).

    The model always runs over the symbol's full available history, never
    just the requested window: BOCPD_CONTRACT.md's boundary condition
    P(r_0=0)=1 applies once, at the true start of the series (Sec 2.2). Only
    the *display* -- `series`, `runlength`, `breaks` -- is trimmed to
    `window`, reusing `_slice_window`/`WINDOW_OFFSETS` exactly as
    `/api/trajectory` does, so a run length reported at the window's start
    can correctly show a long-lived regime rather than a falsely-reset one.
    """
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW

    cache_key = (symbol, window)
    now = time.time()
    with _CHANGEPOINT_SYMBOL_LOCK:
        hit = _CHANGEPOINT_SYMBOL_CACHE.get(cache_key)
    if hit is not None and now - hit[0] < _CHANGEPOINT_SYMBOL_TTL_S:
        return hit[1]

    empty = {
        "available": False,
        "reason": None,
        "symbol": symbol,
        "window": window,
        "n_bars": 0,
        "first_date": None,
        "last_date": None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": _bocpd_model_meta(),
        "thresholds": _bocpd_thresholds(),
        "series": [],
        "runlength": {
            "dates": [], "run_values": [], "n_rows": 0, "n_cols": 0,
            "log_floor": _BOCPD_LOG_FLOOR, "matrix": [],
        },
        "breaks": [],
        "stats": None,
    }

    raw = _load_symbol_bars(symbol, prefer_intraday=False)
    if raw is None or raw.empty or "close" not in raw.columns:
        payload = {**empty, "reason": f"no daily bars found for '{symbol}'"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    df_full = raw
    if not isinstance(df_full.index, pd.DatetimeIndex):
        payload = {**empty, "reason": f"'{symbol}' bars have no DatetimeIndex"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload
    df_full = df_full[~df_full.index.duplicated(keep="last")].sort_index()
    close_full = pd.to_numeric(df_full["close"], errors="coerce").dropna()
    if len(close_full) < _BOCPD_MIN_BARS:
        payload = {**empty, "reason": f"only {len(close_full)} usable bars (< {_BOCPD_MIN_BARS})"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    try:
        result = changepoints_from_prices(
            close_full,
            lambda_gap=_BOCPD_LAMBDA_GAP, a=_BOCPD_PRIOR_A, b=_BOCPD_PRIOR_B,
            truncation_mass=_BOCPD_TRUNCATION_MASS,
        )
        aligned_index = _bocpd_align_dates(close_full.index, len(np.asarray(result.break_prob)))
    except Exception as e:  # noqa: BLE001
        payload = {**empty, "reason": f"changepoints_from_prices failed: {type(e).__name__}: {e}"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    # `cp_prob_raw` is deliberately not read (AMENDMENT 1: constant by
    # construction, carries zero information, never emitted).
    break_prob_arr = np.asarray(result.break_prob, dtype=float)
    break_prob_20_arr = np.asarray(result.break_prob_20, dtype=float)
    map_run_arr = np.asarray(result.map_run_length)
    pred_mean_arr = np.asarray(result.pred_mean, dtype=float)
    pred_std_arr = np.asarray(result.pred_std, dtype=float)
    ret_by_date = close_full.pct_change()

    stats_row = _changepoint_row_from_result(symbol, close_full, aligned_index, result)

    # The model itself already ran over `close_full` above -- the ENTIRE
    # available history, never just this window. Only the *display* is
    # sliced here. Do not "optimize" this by slicing `close_full` to the
    # window before calling `changepoints_from_prices`: the run-length
    # posterior is a function of everything the series has seen since its
    # true start (BOCPD_CONTRACT.md §2.2, P(r_0=0)=1 applies once, at the
    # real start), so restarting the model at the window boundary would
    # fabricate a break at the left edge of every chart.
    win_df = _slice_window(df_full, window)
    if win_df.empty:
        payload = {**empty, "reason": f"no data in window for '{symbol}'", "stats": stats_row}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload
    win_start, win_end = win_df.index[0], win_df.index[-1]

    pos_in_window = np.nonzero((aligned_index >= win_start) & (aligned_index <= win_end))[0]
    if len(pos_in_window) == 0:
        payload = {**empty, "reason": f"no BOCPD output in window for '{symbol}'", "stats": stats_row}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    series: list[dict] = []
    for pos in pos_in_window:
        d = aligned_index[pos]
        pv = float(pred_std_arr[pos])
        series.append({
            "d": d.strftime("%Y-%m-%d"),
            "ret": _safe_round(ret_by_date.get(d), 6),
            "break_prob": _safe_round(float(break_prob_arr[pos]), 6),
            "break_prob_20": _safe_round(float(break_prob_20_arr[pos]), 6),
            "map_run": int(map_run_arr[pos]),
            "pred_vol": _safe_round(pv, 6) if math.isfinite(pv) else None,
            "pred_mean": _safe_round(float(pred_mean_arr[pos]), 6),
        })

    breaks: list[dict] = []
    for pos in pos_in_window:
        if float(break_prob_arr[pos]) < _BOCPD_BREAK_THRESHOLD:
            continue
        d = aligned_index[pos]
        pv_before = float(pred_std_arr[pos - 1]) if pos > 0 else None
        pv_after = float(pred_std_arr[pos])
        breaks.append({
            "date": d.strftime("%Y-%m-%d"),
            "break_prob": _safe_round(float(break_prob_arr[pos]), 6),
            "break_prob_20": _safe_round(float(break_prob_20_arr[pos]), 6),
            "ret": _safe_round(ret_by_date.get(d), 6),
            "pred_vol_before": _safe_round(pv_before, 6) if pv_before is not None and math.isfinite(pv_before) else None,
            "pred_vol_after": _safe_round(pv_after, 6) if math.isfinite(pv_after) else None,
        })

    runlength = _bocpd_runlength_heatmap(result, pos_in_window, aligned_index)

    payload = {
        "available": True,
        "reason": None,
        "symbol": symbol,
        "window": window,
        "n_bars": len(series),
        "first_date": series[0]["d"] if series else None,
        "last_date": series[-1]["d"] if series else None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": _bocpd_model_meta(),
        "thresholds": _bocpd_thresholds(),
        "series": series,
        "runlength": runlength,
        "breaks": breaks,
        "stats": stats_row,
    }
    _changepoint_symbol_cache_put(cache_key, payload)
    return payload


# Status aggregation (PEAD scan + directional + GCP) is expensive. Cache each
# scan depth independently so a deep result is not silently replaced by the
# 25-name quick snapshot. Trigger-scan always bypasses the cache.
_STATUS_CACHE: dict[str, dict] = {}
_STATUS_CACHE_TS: dict[str, float] = {}
_STATUS_CACHE_TTL_S: float = 45.0
_DEEP_STATUS_CACHE_TTL_S: float = 300.0
_STATUS_LOCK = threading.Lock()
_ACTIVE_SCAN_DEPTH = "quick"


def _scan_depth(value: str | None) -> str:
    return "deep" if str(value or "").strip().lower() == "deep" else "quick"


def get_dashboard_data(
    *, force: bool = False, scan_depth: str | None = None, activate: bool = False,
) -> dict:
    """Thread-safe, TTL-cached wrapper around render_dashboard.get_dashboard_data."""
    global _ACTIVE_SCAN_DEPTH
    depth = _scan_depth(scan_depth) if scan_depth is not None else _ACTIVE_SCAN_DEPTH
    now = time.time()
    cache_ttl = _DEEP_STATUS_CACHE_TTL_S if depth == "deep" else _STATUS_CACHE_TTL_S
    if (
        not force
        and depth in _STATUS_CACHE
        and (now - _STATUS_CACHE_TS.get(depth, 0.0)) < cache_ttl
    ):
        if activate:
            _ACTIVE_SCAN_DEPTH = depth
        return _STATUS_CACHE[depth]
    with _STATUS_LOCK:
        now = time.time()
        if (
            not force
            and depth in _STATUS_CACHE
            and (now - _STATUS_CACHE_TS.get(depth, 0.0)) < cache_ttl
        ):
            data = _STATUS_CACHE[depth]
        else:
            data = _get_dashboard_data_uncached(scan_depth=depth)
            data["searchable_symbol_count"] = len(SYMBOL_INDEX)
            _STATUS_CACHE[depth] = data
            _STATUS_CACHE_TS[depth] = time.time()
        if activate:
            _ACTIVE_SCAN_DEPTH = depth
        return data


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

# Options tape/chain calls are materially more expensive than daily price
# reads. Cache exact request payloads briefly; the response still carries its
# provider observation time so a cached read cannot masquerade as a new tick.
_OPTIONS_CACHE: dict[tuple, tuple[float, dict]] = {}
_OPTIONS_LOCK = threading.Lock()
_OPTIONS_CACHE_TTL_S = 20.0

# Market-wide unusual flow is multi-symbol live work — cache longer than a
# single-name options pull so the desk can re-open the board without re-taxing LSE.
_UNUSUAL_FLOW_CACHE: dict[tuple, tuple[float, dict]] = {}
_UNUSUAL_FLOW_LOCK = threading.Lock()
_UNUSUAL_FLOW_BUILD_LOCKS: dict[tuple, threading.Lock] = {}
_UNUSUAL_FLOW_TTL_S = 90.0


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


def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """Coerce parquet/yfinance frames into the trajectory OHLCV schema."""
    if df is None or df.empty:
        return None
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        for col in ("date", "Date", "datetime", "Datetime"):
            if col in out.columns:
                out[col] = pd.to_datetime(out[col], utc=False, errors="coerce")
                out = out.set_index(col)
                break
        else:
            try:
                out.index = pd.to_datetime(out.index, utc=False, errors="coerce")
            except (TypeError, ValueError):
                return None
    out = out[~out.index.isna()].sort_index()
    rename = {c: str(c).strip().lower() for c in out.columns}
    out = out.rename(columns=rename)
    # yfinance MultiIndex residual or Adj Close noise
    for needed in ("open", "high", "low", "close", "volume"):
        if needed not in out.columns:
            alt = needed.capitalize()
            if alt in df.columns:
                out[needed] = df[alt]
    if not all(c in out.columns for c in ("open", "high", "low", "close")):
        return None
    if "volume" not in out.columns:
        out["volume"] = 0.0
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["close"])
    if out.empty:
        return None
    return out[["open", "high", "low", "close", "volume"]]


def _fetch_yfinance_ohlcv(symbol: str) -> pd.DataFrame | None:
    """On-demand daily bars for names missing from the local parquet universe."""
    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        raw = yf.download(symbol, period="5y", progress=False, auto_adjust=True, threads=False)
    except Exception:
        return None
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        # yfinance often returns (Price, Ticker) even for a single name.
        try:
            levels = [str(x).upper() for x in raw.columns.get_level_values(-1)]
            if symbol.upper() in levels:
                raw = raw.xs(symbol, axis=1, level=-1, drop_level=True)
            else:
                raw.columns = raw.columns.get_level_values(0)
        except Exception:
            raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    return _normalize_ohlcv_df(raw)


def _load_symbol_df(symbol: str) -> tuple[pd.DataFrame | None, str | None]:
    """Load a symbol's full OHLCV parquet, cached by (symbol, tier, mtime).

    Falls back to a short-lived yfinance pull when the ticker is not in the
    local 1d/1d_wide catalog so ⌘K can open names like ASTS that users type.
    """
    target = symbol
    tier = SYMBOL_INDEX.get(target)
    if tier is None and target in TRACK_FALLBACK_MAP:
        target = TRACK_FALLBACK_MAP[target]
        tier = SYMBOL_INDEX.get(target)
    if tier is None:
        # Live/ad-hoc path for out-of-universe tickers.
        cache_key = (symbol, "live", 0.0)
        with _PARQUET_LOCK:
            cached = _PARQUET_CACHE.get(cache_key)
        if cached is not None:
            return cached, "live"
        live = _fetch_yfinance_ohlcv(symbol)
        if live is None or live.empty:
            return None, None
        with _PARQUET_LOCK:
            _PARQUET_CACHE[cache_key] = live
        return live, "live"
    path = _symbol_path(target, tier)
    if not path.exists():
        return None, None
    mtime = path.stat().st_mtime
    key = (symbol, tier, mtime)
    with _PARQUET_LOCK:
        df = _PARQUET_CACHE.get(key)
    if df is not None:
        return df, tier
    df = _normalize_ohlcv_df(pd.read_parquet(path))
    if df is None:
        return None, None
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

    if tier == "wide":
        source_label = "1d_wide"
    elif tier == "core":
        source_label = "1d"
    else:
        source_label = "live"

    # Reuse the published full-catalog panel (deep scan or prior Market build).
    # Do NOT pass this symbol's last bar as the cross-section asof — staggered
    # data ends would re-cut the panel and disagree with deep ranks.
    qlib_ctx = _trajectory_qlib_context(symbol)

    payload = {
        "symbol": symbol,
        "window": window,
        "n_bars": int(len(win)),
        "first_date": win.index[0].strftime("%Y-%m-%d"),
        "last_date": win.index[-1].strftime("%Y-%m-%d"),
        "source": source_label,
        "series": series,
        "stats": stats,
        "factors": _compute_factors(df_full),
        "qlib": qlib_ctx,
        "qlib_score": qlib_ctx.get("qlib_score"),
        "qlib_rank": qlib_ctx.get("qlib_rank"),
        "qlib_score_kind": qlib_ctx.get("score_kind") or QLIB_SCORE_KIND,
        "qlib_source": qlib_ctx.get("source") or QLIB_SOURCE_ID,
        "qlib_asof": qlib_ctx.get("asof"),
        "qlib_quality": qlib_ctx.get("quality"),
    }
    return payload, 200


def _trajectory_qlib_context(symbol: str, *, asof: str | None = None) -> dict:
    """Shared qlib context for Market trajectory — full catalog, same as deep scan.

    Uses the process-level panel cache published by deep scan when available;
    otherwise builds a full-catalog panel with asof=None (latest bars), matching
    deep scan. Per-symbol last-bar dates are NOT used to re-cut the cross-section
    (``match_asof=False``) so GIS/ZTS ranks stay identical to deep after AAPL.
    The optional ``asof`` argument is accepted for API compatibility but ignored
    for panel construction on the live Market path.
    """
    data_dirs = (DATA_WIDE_DIR, DATA_CORE_DIR)
    try:
        return lookup_symbol_on_shared_panel(
            symbol,
            data_dirs=data_dirs,
            asof=None,  # never re-cut XS on symbol-local last bar
            match_asof=False,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed for Market strip
        return {
            "symbol": str(symbol or "").strip().upper(),
            "qlib_score": None,
            "qlib_rank": None,
            "score_kind": QLIB_SCORE_KIND,
            "source": QLIB_SOURCE_ID,
            "asof": None,
            "quality": "missing",
            "decision_authorized": False,
            "features": None,
            "warnings": [f"qlib_trajectory_failed: {type(exc).__name__}: {exc}"],
        }


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


def _options_price_series(
    symbol: str, selected_range: str, *, date_from: str | None = None, date_to: str | None = None,
) -> tuple[list[dict], float | None]:
    price_window = {"1d": "1m", "5d": "1m", "1m": "3m", "3m": "6m"}.get(
        selected_range, "3m"
    )
    trajectory, status = _trajectory_payload(symbol, price_window)
    if status != 200:
        return [], None
    series = [
        {"t": f"{row['d']}T20:00:00+00:00", "close": row.get("c")}
        for row in trajectory.get("series", [])
        if row.get("d") and row.get("c") is not None
    ]
    if date_from or date_to:
        lower = date_from or "0000-01-01"
        upper = date_to or "9999-12-31"
        series = [row for row in series if lower <= row["t"][:10] <= upper]
    else:
        # Range labels refer to trading sessions for the stock trace. Keep an
        # extra anchor bar so a 1D selection still shows the day's move.
        keep = {"1d": 2, "5d": 6, "1m": 23, "3m": 66}.get(selected_range, 23)
        series = series[-keep:]
    return series, trajectory.get("stats", {}).get("last_price")


def _option_chain_dates(symbol: str, *, limit: int = 93) -> list[str]:
    """Return available dated chain folders for a symbol (oldest → newest)."""
    option_root = EDGE_DIR / "data" / "option_chains"
    dates: list[str] = []
    for path in sorted(option_root.glob(f"date=*/{symbol}.parquet"))[-limit:]:
        try:
            # Skip unreadable / empty files so "last good" is actually usable.
            frame = pd.read_parquet(path)
        except (OSError, ValueError):
            continue
        if frame.empty:
            continue
        dates.append(path.parent.name.removeprefix("date="))
    return dates


def _historical_option_rows(
    symbol: str, *, asof: str | None = None, all_days: bool = False,
) -> tuple[list[dict], str | None, list[str]]:
    """Load cached option-chain parquet rows.

    When ``all_days`` is False (default for history structural reads), only the
    selected as-of day is returned — defaulting to the last good dated snapshot.
    When ``all_days`` is True, the full lookback window is returned for GEX history.
    """
    available = _option_chain_dates(symbol)
    if not available:
        return [], None, []
    selected = asof if asof in available else available[-1]
    option_root = EDGE_DIR / "data" / "option_chains"
    rows: list[dict] = []
    days = available if all_days else [selected]
    for day in days:
        path = option_root / f"date={day}" / f"{symbol}.parquet"
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except (OSError, ValueError):
            continue
        if frame.empty:
            continue
        rows.extend(frame.to_dict("records"))
    return rows, selected, available


def _fetch_live_option_inputs(
    symbol: str, *, filters: OptionsFilters,
) -> tuple[list[dict], list[dict], float | None, str, list[str]]:
    warnings: list[str] = []
    snapshot = LSEOptionsAdapter(
        api_key=os.getenv("LSE_API_KEY"), min_dte=filters.min_dte, max_dte=filters.max_dte,
    ).snapshot(symbol, asof_utc=datetime.now(timezone.utc))
    chain_rows = list(snapshot.get("contracts") or [])
    underlying = snapshot.get("underlying", {})
    # A last-trade-derived spot without its own quote timestamp is not a live
    # underlying quote. Let the latest verified stock close supply the spot.
    spot = underlying.get("price") if underlying.get("quote_asof_utc") else None
    open_interest_source = "lse_live"

    if chain_rows and not any(int(row.get("open_interest") or 0) > 0 for row in chain_rows):
        cached_rows, latest_label, _ = _historical_option_rows(symbol, all_days=False)
        oi_by_occ: dict[str, int] = {}
        for row in cached_rows:
            occ = str(row.get("contractSymbol") or row.get("occ_symbol") or "").upper()
            try:
                oi = int(float(row.get("openInterest") or row.get("open_interest") or 0))
            except (TypeError, ValueError):
                oi = 0
            if occ and oi > 0:
                oi_by_occ[occ] = oi
        matched = 0
        for row in chain_rows:
            occ = str(row.get("occ_symbol") or "").upper()
            if occ in oi_by_occ:
                row["open_interest"] = oi_by_occ[occ]
                matched += 1
        if matched:
            open_interest_source = f"cached_chain_exact_occ:{latest_label or 'unknown'}"
            warnings.append(
                f"OI from dated chain snapshot ({matched} OCC matches) — LSE live quotes omit OI."
            )
        else:
            open_interest_source = "unavailable"

    flow_rows: list[dict] = []
    try:
        provider_src = ROOT / "TradingWork" / "src"
        if str(provider_src) not in sys.path:
            sys.path.insert(0, str(provider_src))
        from lse_provider import fetch_lse_options_flow  # type: ignore[import-not-found]

        # Fetch with a soft floor so strict UI filters can still be applied in
        # options_intelligence without the vendor pre-emptying the tape.
        fetch_floor = min(float(filters.min_premium), 10_000.0) if filters.min_premium > 0 else 0.0
        observed = fetch_lse_options_flow(
            symbol, min_premium=fetch_floor, limit=500, timeout=12,
        )
        flow_rows = list(observed or [])
        if not flow_rows:
            warnings.append(
                "No recent trade-tape prints from LSE — try RAW noise filter or a more liquid name."
            )
    except Exception as exc:  # noqa: BLE001 - live flow is optional evidence
        warnings.append(f"Live flow unavailable: {type(exc).__name__}")
    return chain_rows, flow_rows, spot, open_interest_source, warnings


def _backfill_oi_payload(symbol: str, *, max_dte: int) -> tuple[dict, int]:
    """Capture a live OI snapshot for one symbol and cache it to disk.

    Runs the same fetch as `tools/backfill_option_oi.py`, in-process, so the
    dashboard's "BACKFILL OI" button can drive it directly instead of the user
    running the CLI by hand. Provider gaps (delisted, no listed chain, a
    transient yfinance hiccup) are expected per-symbol outcomes, not server
    bugs -- they come back as a clean 404 with the reason, not a 500 trace.
    """
    asof = datetime.now(timezone.utc).date()
    try:
        frame = _capture_option_oi(symbol, asof=asof, max_dte=max_dte)
    except Exception as exc:  # noqa: BLE001 - provider gaps are per-symbol, not fatal
        return {
            "error": f"No options data from the provider for {symbol}: "
                     f"{type(exc).__name__}: {exc}",
            "endpoint": "/api/options/backfill_oi",
            "symbol": symbol,
        }, 404

    out_dir = EDGE_DIR / "data" / "option_chains" / f"date={asof.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_dir / f"{symbol}.parquet")

    # The next /api/options fetch must see this snapshot immediately, not
    # after the 20s options cache TTL expires.
    with _OPTIONS_LOCK:
        for key in [k for k in _OPTIONS_CACHE if k[0] == symbol]:
            _OPTIONS_CACHE.pop(key, None)

    return {
        "status": "ok",
        "symbol": symbol,
        "asof": asof.isoformat(),
        "contracts": int(len(frame)),
        "with_oi": int((frame["openInterest"] > 0).sum()),
    }, 200


def _options_payload(symbol: str, query: dict) -> tuple[dict, int]:
    mode = str(query.get("mode", ["live"])[0]).lower()
    mode = mode if mode in {"live", "history"} else "live"
    selected_range = str(query.get("range", ["5d"])[0]).lower()
    selected_range = selected_range if selected_range in {"1d", "5d", "1m", "3m"} else "5d"

    def q_float(name: str, default: float, lo: float, hi: float) -> float:
        try:
            value = float(query.get(name, [str(default)])[0])
        except (TypeError, ValueError):
            value = default
        return min(hi, max(lo, value))

    min_dte = _safe_int(query.get("min_dte", ["0"])[0], 0, 0, 730)
    max_dte = _safe_int(query.get("max_dte", ["60"])[0], 60, 0, 730)
    if max_dte < min_dte:
        return {"error": "max_dte must be greater than or equal to min_dte",
                "endpoint": "/api/options"}, 400
    selected_expiry = str(query.get("expiry", ["nearest"])[0] or "nearest").lower()
    if selected_expiry not in {"nearest", "all"}:
        try:
            datetime.fromisoformat(selected_expiry)
        except ValueError:
            return {"error": "expiry must be nearest, all, or YYYY-MM-DD",
                    "endpoint": "/api/options"}, 400
    filters = OptionsFilters(
        range=selected_range,
        min_premium=q_float("min_premium", 50_000.0, 0, 100_000_000),
        min_volume=_safe_int(query.get("min_volume", ["10"])[0], 10, 0, 1_000_000),
        min_open_interest=_safe_int(query.get("min_oi", ["100"])[0], 100, 0, 10_000_000),
        max_spread_pct=q_float("max_spread", 0.25, 0.001, 2.0),
        min_dte=min_dte,
        max_dte=max_dte,
        expiry=selected_expiry,
        tape_limit=_safe_int(query.get("tape_limit", ["100"])[0], 100, 1, 500),
        date_from=(query.get("from", [None])[0] or None),
        date_to=(query.get("to", [None])[0] or None),
        risk_free_rate=q_float("rate", 0.045, -0.05, 0.25),
    )
    cache_key = (symbol, mode, *asdict(filters).values())
    with _OPTIONS_LOCK:
        cached = _OPTIONS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _OPTIONS_CACHE_TTL_S:
        return cached[1], 200

    price_series, price_spot = _options_price_series(
        symbol, selected_range, date_from=filters.date_from, date_to=filters.date_to,
    )
    warnings: list[str] = []
    chain_rows: list[dict] = []
    flow_rows: list[dict] = []
    live_spot: float | None = None
    mode_resolved = mode
    chain_source = "lse_live"
    flow_source = "lse_live_trade_tape"
    open_interest_source = "lse_live"
    history_chain_rows: list[dict] = []

    history_meta: dict = {
        "available_dates": [],
        "selected_asof": None,
        "last_good_asof": None,
        "auto_selected": False,
    }

    if mode == "live":
        try:
            chain_rows, flow_rows, live_spot, open_interest_source, live_warnings = _fetch_live_option_inputs(
                symbol, filters=filters,
            )
            warnings.extend(live_warnings)
        except Exception as exc:  # noqa: BLE001 - fall back visibly, never silently
            warnings.append(f"Live chain unavailable: {type(exc).__name__}")

    if mode == "history" or not chain_rows:
        # Prefer an explicit `to` date when it matches a dated snapshot; otherwise
        # auto-load the last good chain day so History is never an empty shell.
        requested_asof = filters.date_to
        chain_rows, latest_label, available_dates = _historical_option_rows(
            symbol, asof=requested_asof, all_days=False,
        )
        history_chain_rows, _, _ = _historical_option_rows(symbol, all_days=True)
        history_meta = {
            "available_dates": available_dates,
            "selected_asof": latest_label,
            "last_good_asof": available_dates[-1] if available_dates else None,
            "auto_selected": bool(
                available_dates and (not requested_asof or requested_asof not in available_dates)
            ),
        }
        if not chain_rows:
            return {
                "error": f"No options chain is available for {symbol}.",
                "endpoint": "/api/options",
                "warnings": warnings,
                "history": history_meta,
            }, 404
        mode_resolved = "history" if mode == "history" else "history_fallback"
        chain_source = f"cached_chain:{latest_label or 'unknown'}"
        flow_source = "unavailable"
        open_interest_source = chain_source
        if mode == "live":
            warnings.append("Showing the latest dated chain because the live chain was unavailable.")
        elif history_meta["auto_selected"] and latest_label:
            warnings.append(
                f"History auto-loaded the last good chain day ({latest_label})."
            )
        elif latest_label and requested_asof and requested_asof != latest_label:
            warnings.append(
                f"Requested chain day {requested_asof} was unavailable; loaded {latest_label}."
            )

    if not history_chain_rows:
        history_chain_rows, hist_label, available_dates = _historical_option_rows(
            symbol, all_days=True,
        )
        if available_dates and not history_meta["available_dates"]:
            history_meta = {
                "available_dates": available_dates,
                "selected_asof": hist_label,
                "last_good_asof": available_dates[-1],
                "auto_selected": False,
            }

    payload = build_options_intelligence(
        symbol=symbol,
        chain_rows=chain_rows,
        flow_rows=flow_rows,
        price_series=price_series,
        # A dated chain must use the spot captured with that chain, not the
        # latest daily close. Mixing observation clocks distorts every Greek.
        spot=(live_spot or price_spot) if mode_resolved == "live" else None,
        filters=filters,
        mode_requested=mode,
        mode_resolved=mode_resolved,
        chain_source=chain_source,
        flow_source=flow_source,
        asof_utc=datetime.now(timezone.utc),
        warnings=warnings,
        open_interest_source=open_interest_source,
        history_chain_rows=history_chain_rows,
    )
    if isinstance(payload, dict):
        payload["history"] = history_meta
    with _OPTIONS_LOCK:
        _OPTIONS_CACHE[cache_key] = (time.time(), payload)
        if len(_OPTIONS_CACHE) > 128:
            oldest = min(_OPTIONS_CACHE, key=lambda key: _OPTIONS_CACHE[key][0])
            _OPTIONS_CACHE.pop(oldest, None)
    return payload, 200


# ---------------------------------------------------------------------------
# Conviction board: scan candidates -> live option chains.
#
# This is the missing link between the scan (which produced symbols and stopped)
# and the options engine (which only ever ran on a hand-typed ticker). It reuses
# the exact same build_options_intelligence call as /api/options so a board score
# equals the detail-view score for the same symbol and filters.
#
# The one deliberate difference: history_chain_rows is empty. The single-symbol
# view reads up to 93 dated parquet folders to draw the GEX history strip; doing
# that for 25 symbols would mean thousands of file reads per board build for a
# column the board does not render.
# ---------------------------------------------------------------------------

#: Board filters are looser than the single-symbol defaults on purpose. Strict
#: floors (50K premium / 100 OI) empty the chain on mid-caps, and a board that
#: silently blanks the names it was asked to inspect is worse than no board.
_BOARD_FILTER_DEFAULTS = {
    "min_premium": 0.0,
    "min_volume": 0,
    "min_open_interest": 0,
    "max_spread_pct": 0.75,
    "min_dte": 0,
    "max_dte": 60,
}


def _options_board_row(candidate) -> dict:
    """Fetch one candidate's live chain and compact it into a board row."""
    symbol = candidate.symbol
    filters = OptionsFilters(
        range="5d",
        expiry="nearest",
        tape_limit=50,
        risk_free_rate=0.045,
        **_BOARD_FILTER_DEFAULTS,
    )
    price_asof: str | None = None
    try:
        price_series, price_spot = _options_price_series(symbol, "5d")
        # Last local bar timestamp — compared against the chain clock so a live
        # chain scored on stale bars is flagged, not silently rendered.
        price_asof = str(price_series[-1].get("t")) if price_series else None
        chain_rows, flow_rows, live_spot, oi_source, warnings = _fetch_live_option_inputs(
            symbol, filters=filters,
        )
        chain_source = "lse_live"
        mode_resolved = "live"
        if not chain_rows:
            # Fall back visibly to the last good dated snapshot rather than
            # reporting the name as unavailable.
            chain_rows, label, _ = _historical_option_rows(symbol, all_days=False)
            if not chain_rows:
                return summarize_board_row(
                    candidate, None, price_asof=price_asof,
                    error=f"No options chain is available for {symbol}.",
                )
            chain_source = f"cached_chain:{label or 'unknown'}"
            oi_source = chain_source
            mode_resolved = "history_fallback"
            live_spot = None
            warnings.append("Live chain unavailable; showing the latest dated chain.")

        intel = build_options_intelligence(
            symbol=symbol,
            chain_rows=chain_rows,
            flow_rows=flow_rows,
            price_series=price_series,
            spot=(live_spot or price_spot) if mode_resolved == "live" else None,
            filters=filters,
            mode_requested="live",
            mode_resolved=mode_resolved,
            chain_source=chain_source,
            flow_source="lse_live_trade_tape" if flow_rows else "unavailable",
            asof_utc=datetime.now(timezone.utc),
            warnings=warnings,
            open_interest_source=oi_source,
            history_chain_rows=(),
        )
        return summarize_board_row(candidate, intel, price_asof=price_asof)
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not empty the board
        return summarize_board_row(
            candidate, None, price_asof=price_asof, error=f"{type(exc).__name__}: {exc}",
        )


def _options_board_payload_impl(
    *, limit: int, depth: str, require_live_flow: bool, force: bool,
) -> dict:
    cache_key = (limit, depth, require_live_flow)
    if not force:
        with _OPTIONS_BOARD_LOCK:
            hit = _OPTIONS_BOARD_CACHE.get(cache_key)
        if hit and time.time() - hit[0] < _OPTIONS_BOARD_TTL_S:
            payload = dict(hit[1])
            # Staleness is never implicit: say how old this copy is and that a
            # forced refetch is available, so the desk is not reading a cached
            # chain while believing it is live.
            payload["cache"] = {
                "hit": True,
                "age_seconds": round(time.time() - hit[0], 1),
                "ttl_seconds": _OPTIONS_BOARD_TTL_S,
                "refresh_hint": "GET /api/options/board?force=1 for a live refetch",
            }
            return payload

    # force refetches the chains; it does not force a full rescan. Rescanning is
    # the Desk's explicit action (/api/trigger_scan) and can take minutes.
    status = get_dashboard_data(scan_depth=depth)
    candidates, considered = select_board_candidates(
        status=status, limit=limit, require_live_flow=require_live_flow,
    )
    warnings: list[str] = []
    if not candidates:
        warnings.append(
            "No scan candidate met the selection tiers. Run a deep scan from the "
            "Desk, or clear the live-flow requirement."
        )

    rows: list[dict] = []
    if candidates:
        workers = min(_OPTIONS_BOARD_MAX_WORKERS, len(candidates))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_options_board_row, candidates))
    # Rank by structural conviction, but keep unavailable names on the board so
    # coverage is visible rather than quietly trimmed.
    # Measurable structure first, then conviction. A name whose GEX could not be
    # measured must never outrank one that was actually observed.
    rows.sort(key=lambda r: (
        not r.get("available"),
        not r.get("gex_measurable"),
        -abs(float(r.get("squeeze_score") or 0.0)),
        int(r.get("rank") or 10**6),
    ))

    scan = status.get("activity_scan") if isinstance(status.get("activity_scan"), dict) else {}
    payload = _options_board_wire(
        rows=rows,
        candidates_considered=considered,
        requested=len(candidates),
        depth=str((status.get("scan_summary") or {}).get("depth") or depth),
        scan_asof=scan.get("asof") or status.get("asof"),
        asof_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        limit=limit,
        require_live_flow=require_live_flow,
        warnings=warnings,
    )
    payload["calibrated_signals"] = [
        {
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "probability": row.get("probability"),
            "confidence_kind": row.get("confidence_kind"),
            "calibration_version": row.get("calibration_version"),
            "model": row.get("model"),
            "setup_ok": row.get("setup_ok"),
            "state": row.get("state"),
        }
        for row in (status.get("directional_signals") or [])
        if isinstance(row, dict)
        and row.get("symbol")
        and row.get("confidence_kind") == "calibrated_probability"
    ]
    payload["cache"] = {
        "hit": False,
        "age_seconds": 0.0,
        "ttl_seconds": _OPTIONS_BOARD_TTL_S,
        "refresh_hint": "GET /api/options/board?force=1 for a live refetch",
    }
    with _OPTIONS_BOARD_LOCK:
        _OPTIONS_BOARD_CACHE[cache_key] = (time.time(), payload)
        if len(_OPTIONS_BOARD_CACHE) > 8:
            oldest = min(_OPTIONS_BOARD_CACHE, key=lambda k: _OPTIONS_BOARD_CACHE[k][0])
            _OPTIONS_BOARD_CACHE.pop(oldest, None)
    return payload


def _options_board_payload(
    *, limit: int, depth: str, require_live_flow: bool, force: bool,
) -> dict:
    """Return one board build per cache key, even under concurrent requests.

    The threaded HTTP server can receive the Flow radar and the optional full
    structure board together. Without a keyed build lock, both cache misses
    launch the same 25 vendor chain reads. A concurrent forced request may use
    a result produced after it began; a later, deliberate force still rebuilds.
    """
    cache_key = (limit, depth, require_live_flow)
    request_started = time.time()
    with _OPTIONS_BOARD_LOCK:
        build_lock = _OPTIONS_BOARD_BUILD_LOCKS.setdefault(cache_key, threading.Lock())
    with build_lock:
        if force:
            with _OPTIONS_BOARD_LOCK:
                hit = _OPTIONS_BOARD_CACHE.get(cache_key)
            if hit and hit[0] >= request_started:
                return dict(hit[1])
        return _options_board_payload_impl(
            limit=limit,
            depth=depth,
            require_live_flow=require_live_flow,
            force=force,
        )


def _unusual_flow_payload_impl(*, limit: int, min_premium: float, force: bool = False) -> dict:
    cache_key = (limit, round(min_premium, 2))
    if not force:
        with _UNUSUAL_FLOW_LOCK:
            cached = _UNUSUAL_FLOW_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _UNUSUAL_FLOW_TTL_S:
            payload = dict(cached[1])
            payload["cache"] = {
                "hit": True,
                "age_seconds": round(time.time() - cached[0], 1),
                "ttl_seconds": _UNUSUAL_FLOW_TTL_S,
                "refresh_hint": "GET /api/unusual-flow?force=1 for a live refetch",
            }
            return payload
    data_dirs = [p for p in (DATA_WIDE_DIR, DATA_CORE_DIR) if p.is_dir()]
    payload = build_unusual_options_flow(
        data_dirs=data_dirs,
        live_target_limit=min(60, max(24, limit + 12)),
        row_limit=limit,
        min_premium=min_premium,
    )
    payload = dict(payload)
    payload["cache"] = {
        "hit": False,
        "age_seconds": 0.0,
        "ttl_seconds": _UNUSUAL_FLOW_TTL_S,
        "refresh_hint": "GET /api/unusual-flow?force=1 for a live refetch",
    }
    with _UNUSUAL_FLOW_LOCK:
        _UNUSUAL_FLOW_CACHE[cache_key] = (time.time(), payload)
        if len(_UNUSUAL_FLOW_CACHE) > 8:
            oldest = min(_UNUSUAL_FLOW_CACHE, key=lambda k: _UNUSUAL_FLOW_CACHE[k][0])
            _UNUSUAL_FLOW_CACHE.pop(oldest, None)
    return payload


def _unusual_flow_payload(*, limit: int, min_premium: float, force: bool = False) -> dict:
    """Coalesce identical concurrent market-wide tape scans.

    Threshold/limit variants remain independent cache keys, but two browser
    panes asking for the same variant now share one local parquet + LSE pass.
    """
    cache_key = (limit, round(min_premium, 2))
    request_started = time.time()
    with _UNUSUAL_FLOW_LOCK:
        build_lock = _UNUSUAL_FLOW_BUILD_LOCKS.setdefault(cache_key, threading.Lock())
    with build_lock:
        if force:
            with _UNUSUAL_FLOW_LOCK:
                hit = _UNUSUAL_FLOW_CACHE.get(cache_key)
            if hit and hit[0] >= request_started:
                return dict(hit[1])
        return _unusual_flow_payload_impl(
            limit=limit,
            min_premium=min_premium,
            force=force,
        )


# Passive reads recombine the board/unusual-flow caches above. A force request
# is an explicit operator action and refreshes both upstream sources once.
_LIVE_OPPORTUNITIES_CACHE: dict | None = None
_LIVE_OPPORTUNITIES_CACHE_TS: float = 0.0
_LIVE_OPPORTUNITIES_TTL_S = 90.0
_LIVE_OPPORTUNITIES_LOCK = threading.Lock()


def _live_opportunities_payload(*, force: bool = False) -> dict:
    global _LIVE_OPPORTUNITIES_CACHE, _LIVE_OPPORTUNITIES_CACHE_TS
    now = time.time()
    if (
        not force and _LIVE_OPPORTUNITIES_CACHE is not None
        and (now - _LIVE_OPPORTUNITIES_CACHE_TS) < _LIVE_OPPORTUNITIES_TTL_S
    ):
        return _LIVE_OPPORTUNITIES_CACHE
    with _LIVE_OPPORTUNITIES_LOCK:
        now = time.time()
        if (
            not force and _LIVE_OPPORTUNITIES_CACHE is not None
            and (now - _LIVE_OPPORTUNITIES_CACHE_TS) < _LIVE_OPPORTUNITIES_TTL_S
        ):
            return _LIVE_OPPORTUNITIES_CACHE
        # Passive polling stays cache-friendly. Only an explicit force request
        # cascades to vendors, matching the dashboard's "PULL LIVE DATA" action.
        board = _options_board_payload(
            limit=25, depth=_ACTIVE_SCAN_DEPTH, require_live_flow=False, force=force,
        )
        flow = _unusual_flow_payload(limit=40, min_premium=25_000.0, force=force)
        board_cache = board.get("cache") if isinstance(board.get("cache"), dict) else {}
        flow_cache = flow.get("cache") if isinstance(flow.get("cache"), dict) else {}
        payload = build_live_opportunities(
            board_rows=list(board.get("rows") or []),
            flow_rows=list(flow.get("rows") or []),
            calibrated_rows=list(board.get("calibrated_signals") or []),
            filters=OptionsFilters(),
            board_cache_age_seconds=float(board_cache.get("age_seconds") or 0.0),
            flow_cache_age_seconds=float(flow_cache.get("age_seconds") or 0.0),
        )
        if payload.get("available"):
            payload["sources"] = {
                "board": {
                    "cache": board_cache,
                    "asof_utc": board.get("asof_utc"),
                    "scan_asof": board.get("scan_asof"),
                },
                "flow": {
                    "cache": flow_cache,
                    "asof": flow.get("asof"),
                },
                "scan_depth": _ACTIVE_SCAN_DEPTH,
            }
        _LIVE_OPPORTUNITIES_CACHE = payload
        _LIVE_OPPORTUNITIES_CACHE_TS = time.time()
        return payload


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
    """Ticker search over the priced universe only.

    Factor "tracks" (PEAD, GEX, …) are research labels, not tradeable symbols.
    Mixing them into ⌘K sent users to trajectory 404s and looked like junk
    results, so they are no longer returned here.

    Exact typed tickers that are missing from the local parquet catalog are
    still returned as ``tier=live`` so names like ASTS can be opened via the
    yfinance trajectory fallback.
    """
    q_norm = (q or "").strip().upper()
    # Strip common non-ticker noise (spaces, punctuation) for prefix match.
    q_clean = "".join(ch for ch in q_norm if ch.isalnum() or ch in ".-")
    all_syms = sorted(SYMBOL_INDEX.keys())
    limit = max(1, min(int(limit or 25), 80))

    if not q_clean:
        # Empty query: liquid majors first, then alpha-sorted remainder.
        majors = [
            s for s in (
                "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN",
                "META", "GOOGL", "TSLA", "AMD", "XLF", "XLK", "XLE", "GLD",
            )
            if s in SYMBOL_INDEX
        ]
        rest = [s for s in all_syms if s not in set(majors)]
        chosen = (majors + rest)[:limit]
    else:
        exact = [s for s in all_syms if s == q_clean]
        exact_set = set(exact)
        prefix = [s for s in all_syms if s not in exact_set and s.startswith(q_clean)]
        seen = exact_set | set(prefix)
        # Substring only for queries ≥ 2 chars — single-letter substr matches
        # half the universe and feels broken.
        substr: list[str] = []
        if len(q_clean) >= 2:
            substr = [s for s in all_syms if s not in seen and q_clean in s]
        chosen = (exact + prefix + substr)[:limit]

    out: list[dict] = []
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

    # Promote exact typed ticker even when it is not in the local catalog.
    if q_clean and _SYMBOL_RE.match(q_clean) and not any(r["symbol"] == q_clean for r in out):
        out.insert(0, {
            "symbol": q_clean,
            "kind": "symbol",
            "tier": "live",
            "n_bars": 0,
            "first_date": "",
            "last_date": "",
        })
        out = out[:limit]
    return out


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


_MOMENTUM_SCAN_CACHE: dict | None = None
_MOMENTUM_SCAN_CACHE_TS: float = 0.0
_MOMENTUM_SCAN_CACHE_TTL_S = 300.0
_MOMENTUM_SCAN_LOCK = threading.Lock()


def _load_smallcap_price_data() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    search_dirs = [
        DATA_SMALLCAP_DIR,
        RUNS_DIR.parent / "data" / "1d",
        RUNS_DIR.parent / "data" / "1d_wide",
    ]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for path in d.glob("*.parquet"):
            sym = path.stem
            if sym in out or "MANIFEST" in sym:
                continue
            try:
                out[sym] = pd.read_parquet(path)
            except Exception:
                continue
    return out


def _momentum_scan_payload(*, force: bool = False) -> dict:
    global _MOMENTUM_SCAN_CACHE, _MOMENTUM_SCAN_CACHE_TS
    now = time.time()
    if not force and _MOMENTUM_SCAN_CACHE is not None and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S:
        return _MOMENTUM_SCAN_CACHE
    with _MOMENTUM_SCAN_LOCK:
        now = time.time()
        if not force and _MOMENTUM_SCAN_CACHE is not None and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S:
            return _MOMENTUM_SCAN_CACHE
        price_data = _load_smallcap_price_data()
        float_data = load_float_data()
        expected = len(price_data)
        manifest_path = DATA_SMALLCAP_DIR / "FETCH_MANIFEST_SMALLCAP.json"
        if manifest_path.exists():
            try:
                expected = json.loads(manifest_path.read_text()).get("expected_universe_size", expected)
            except Exception:
                pass
        payload = build_momentum_scan(price_data, float_data, expected_universe_size=expected)
        _MOMENTUM_SCAN_CACHE = payload
        _MOMENTUM_SCAN_CACHE_TS = time.time()
        return payload


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


def _market_clock_payload() -> dict:
    """Lightweight, uncached session clock for the operator strip."""
    return market_clock_status(datetime.now(timezone.utc)).to_dict()


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
        # index.html must not be sticky — it points at hashed asset names that
        # change every build. Hashed assets under /assets/ can be immutable.
        name = path.name.lower()
        if name == "index.html" or path.suffix.lower() in {".html", ".htm"}:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        elif "/assets/" in str(path).replace("\\", "/") or path.parent.name == "assets":
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
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
                requested_depth = query.get("depth", [None])[0]
                self._send_json(get_dashboard_data(scan_depth=requested_depth))

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
                depth = _scan_depth(query.get("depth", ["quick"])[0])
                data = get_dashboard_data(force=True, scan_depth=depth, activate=True)
                summary = data.get("scan_summary") or {}
                self._send_json({
                    "status": "ok",
                    "message": (
                        f"{depth.title()} scan complete: "
                        f"{summary.get('activity_local_scanned_symbols', 0)}/"
                        f"{summary.get('activity_market_universe_symbols', 0)} market names activity-ranked; "
                        f"{summary.get('activity_live_completed_symbols', 0)}/"
                        f"{summary.get('activity_live_requested_symbols', 0)} live flow checks completed; "
                        f"{summary.get('directional_scored_symbols', 0)}/"
                        f"{summary.get('directional_model_universe_symbols', 0)} directional symbols scored; "
                        f"{summary.get('pead_qualified_symbols', 0)}/"
                        f"{summary.get('pead_attempted_symbols', 0)} PEAD activity flags."
                    ),
                    "asof": data["asof"],
                    "data": data,
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

            elif path == "/api/options":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _options_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/options/board":
                limit = _safe_int(query.get("limit", ["25"])[0], default=25, lo=1, hi=60)
                depth = _scan_depth(query.get("depth", [None])[0] or _ACTIVE_SCAN_DEPTH)
                require_live_flow = str(
                    query.get("require_live_flow", ["0"])[0]
                ).lower() in {"1", "true", "yes"}
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(_options_board_payload(
                    limit=limit,
                    depth=depth,
                    require_live_flow=require_live_flow,
                    force=force,
                ))

            elif path == "/api/options/backfill_oi":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                max_dte = _safe_int(query.get("max_dte", ["60"])[0], 60, 1, 730)
                payload, status = _backfill_oi_payload(sym_or_err, max_dte=max_dte)
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

            elif path == "/api/momentum-scan":
                self._send_json(_momentum_scan_payload())

            elif path == "/api/readiness":
                self._send_json(_readiness_payload())

            elif path == "/api/market-clock":
                self._send_json(_market_clock_payload())

            elif path == "/api/health":
                self._send_json(_health_payload())

            elif path == "/api/sentiment":
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                sym: str | None = None
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    sym = sym_or_err
                self._send_json(build_sentiment_payload(symbol=sym))

            elif path == "/api/anomalies":
                limit = _safe_int(query.get("limit", ["40"])[0], default=40, lo=5, hi=200)
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                sym = None
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    sym = sym_or_err
                self._send_json(build_anomalies_payload(limit=limit, symbol=sym))

            elif path == "/api/unusual-flow":
                limit = _safe_int(query.get("limit", ["40"])[0], default=40, lo=1, hi=100)
                try:
                    min_premium = float(query.get("min_premium", ["25000"])[0])
                except (TypeError, ValueError):
                    min_premium = 25_000.0
                min_premium = max(0.0, min(min_premium, 5_000_000.0))
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(_unusual_flow_payload(limit=limit, min_premium=min_premium, force=force))

            elif path == "/api/options/opportunities":
                limit = _safe_int(query.get("limit", [None])[0], default=0, lo=1, hi=500)
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                payload = _live_opportunities_payload(force=force)
                if limit and isinstance(payload.get("rows"), list):
                    payload = {**payload, "rows": payload["rows"][:limit]}
                self._send_json(payload)

            elif path == "/api/ga":
                run_id = (query.get("run_id", [None])[0] or None)
                if run_id is not None:
                    run_id = str(run_id).strip() or None
                    if run_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", run_id):
                        self._send_json(
                            {"error": "invalid run_id", "endpoint": path},
                            status=400,
                        )
                        return
                self._send_json(_ga_run_payload(run_id))

            elif path == "/api/graph":
                max_nodes = _safe_int(
                    query.get("max_nodes", ["400"])[0], default=400, lo=10, hi=2000
                )
                self._send_json(_graph_payload(max_nodes))

            elif path == "/api/factors":
                self._send_json(_factor_tearsheet_payload())

            elif path == "/api/changepoints":
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    window = query.get("window", [DEFAULT_WINDOW])[0]
                    self._send_json(_changepoint_symbol_payload(sym_or_err, window))
                else:
                    self._send_json(_changepoints_payload())

            elif path == "/api/flow-state":
                self._send_json(_flow_state_payload())

            elif path == "/api/adaptive-signal":
                limit = _safe_int(query.get("limit", ["40"])[0], default=40, lo=5, hi=120)
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                sym: str | None = None
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    sym = sym_or_err
                self._send_json(_adaptive_signal_payload(symbol=sym, limit=limit))

            elif path == "/api/fintel/status":
                self._send_json(fintel_status_payload())

            elif path == "/api/fintel/stream":
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                squeeze_limit = _safe_int(
                    query.get("squeeze_limit", ["25"])[0], default=25, lo=5, hi=100
                )
                short_limit = _safe_int(
                    query.get("short_interest_limit", ["25"])[0], default=25, lo=5, hi=100
                )
                cache_key = (squeeze_limit, short_limit)
                cached = _FINTEL_STREAM_CACHE
                ttl = _FINTEL_STREAM_TTL_S
                if cached.get("payload") and cached["payload"].get("quota_exceeded"):
                    ttl = _FINTEL_QUOTA_TTL_S
                if (
                    not force
                    and cached.get("key") == cache_key
                    and cached.get("payload") is not None
                    and time.time() - float(cached.get("ts") or 0) < ttl
                ):
                    self._send_json(cached["payload"])
                    return
                try:
                    payload = fetch_market_stream(
                        squeeze_limit=squeeze_limit,
                        short_interest_limit=short_limit,
                    )
                except FintelAuthError as e:
                    self._send_json(
                        {
                            "available": False,
                            "configured": FintelClient().configured,
                            "error": str(e),
                            "error_kind": "auth",
                            "decision_authorized": False,
                            "live_capital_authorized": False,
                        },
                        status=401,
                    )
                    return
                except FintelQuotaError as e:
                    payload = {
                        "available": False,
                        "configured": FintelClient().configured,
                        "error": str(e),
                        "error_kind": "quota",
                        "quota_exceeded": True,
                        "decision_authorized": False,
                        "live_capital_authorized": False,
                    }
                    _FINTEL_STREAM_CACHE["ts"] = time.time()
                    _FINTEL_STREAM_CACHE["key"] = cache_key
                    _FINTEL_STREAM_CACHE["payload"] = payload
                    # 200 + structured body so the desk can render a quota banner
                    self._send_json(payload)
                    return
                _FINTEL_STREAM_CACHE["ts"] = time.time()
                _FINTEL_STREAM_CACHE["key"] = cache_key
                _FINTEL_STREAM_CACHE["payload"] = payload
                self._send_json(payload)

            elif path == "/api/fintel/intel":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                country = (query.get("country", ["US"])[0] or "US").strip().upper()[:2]
                if not re.fullmatch(r"[A-Z]{2}", country):
                    self._send_json({"error": "invalid country", "endpoint": path}, status=400)
                    return
                depth = (query.get("depth", ["core"])[0] or "core").strip().lower()
                if depth not in {"core", "full", "deep", "all"}:
                    depth = "core"
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                cache_key = (country, sym_or_err, depth)
                with _FINTEL_INTEL_LOCK:
                    hit = _FINTEL_INTEL_CACHE.get(cache_key)
                ttl = _FINTEL_INTEL_TTL_S
                if hit and hit[1].get("quota_exceeded"):
                    ttl = _FINTEL_QUOTA_TTL_S
                if hit and not force and time.time() - hit[0] < ttl:
                    self._send_json(hit[1])
                    return
                try:
                    payload = fetch_security_intel(
                        sym_or_err, country=country, depth=depth, include_options_flow=False
                    )
                except FintelAuthError as e:
                    self._send_json(
                        {
                            "available": False,
                            "configured": FintelClient().configured,
                            "error": str(e),
                            "error_kind": "auth",
                            "symbol": sym_or_err,
                            "country": country,
                            "decision_authorized": False,
                            "live_capital_authorized": False,
                        },
                        status=401,
                    )
                    return
                except FintelQuotaError as e:
                    payload = {
                        "available": False,
                        "configured": FintelClient().configured,
                        "error": str(e),
                        "error_kind": "quota",
                        "quota_exceeded": True,
                        "symbol": sym_or_err,
                        "country": country,
                        "depth": depth,
                        "decision_authorized": False,
                        "live_capital_authorized": False,
                    }
                    with _FINTEL_INTEL_LOCK:
                        _FINTEL_INTEL_CACHE[cache_key] = (time.time(), payload)
                    self._send_json(payload)
                    return
                with _FINTEL_INTEL_LOCK:
                    _FINTEL_INTEL_CACHE[cache_key] = (time.time(), payload)
                    if len(_FINTEL_INTEL_CACHE) > 64:
                        oldest = min(_FINTEL_INTEL_CACHE, key=lambda k: _FINTEL_INTEL_CACHE[k][0])
                        _FINTEL_INTEL_CACHE.pop(oldest, None)
                self._send_json(payload)

            elif path == "/api/fintel/search":
                q = (query.get("q", [""])[0] or "").strip()
                if not q:
                    self._send_json({"error": "q is required", "endpoint": path}, status=400)
                    return
                limit = _safe_int(query.get("limit", ["25"])[0], default=25, lo=1, hi=100)
                country = (query.get("country", ["US"])[0] or "US").strip().upper() or None
                try:
                    self._send_json(
                        fintel_search_securities(q, country=country, limit=limit)
                    )
                except FintelAuthError as e:
                    self._send_json(
                        {
                            "available": False,
                            "configured": FintelClient().configured,
                            "error": str(e),
                            "query": q,
                            "results": [],
                        },
                        status=401,
                    )

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
    # This dashboard exposes research artifacts and provider-derived trading
    # context without authentication. Keep it on loopback; publishing it to a
    # LAN requires a separate authenticated reverse proxy, not a wider bind.
    server = ThreadedHTTPServer((LOOPBACK_HOST, port), ApiRequestHandler)
    url = f"http://localhost:{port}"

    print(f"===========================================================")
    print(f"  QUANT DASHBOARD API SERVER")
    print(f"  Listening on: {url}")
    print(f"  Serving SPA from: {_static_root()}")
    print(f"  Symbols indexed: {len(SYMBOL_INDEX)}")
    print(f"===========================================================")

    def _warm_status_cache():
        try:
            t0 = time.time()
            data = get_dashboard_data(force=True)
            n_pead = len(data.get("pead_candidates") or [])
            n_dir = len(data.get("directional_signals") or [])
            print(
                f"[api_server] status cache warm in {time.time() - t0:.1f}s "
                f"(pead={n_pead}, directional={n_dir}, universe={data.get('broad_universe_count')})",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[api_server] status cache warm failed: {e}", file=sys.stderr, flush=True)

    threading.Thread(target=_warm_status_cache, daemon=True, name="status-warm").start()

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    main()
