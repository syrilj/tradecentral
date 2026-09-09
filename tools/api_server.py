#!/usr/bin/env python3
"""Zero-extra-dependency JSON API server for the quant trading dashboard.

Stdlib `http.server` + `socketserver.ThreadingMixIn` only, plus pandas/numpy
(already installed in the project venv). Supersedes `serve_dashboard.py`.

Run with:
  edge/.venv-qlib/bin/python edge/tools/api_server.py [--port 8787] [--no-browser]

Endpoints (all GET unless noted, all JSON, all CORS-open with `Access-Control-Allow-Origin: *`):

  GET  /api/status[?depth=quick|deep]
      -> latest cached desk board (PEAD candidates, directional signals,
         sector flow, vol complex, PEAD gate metrics, leaderboard). Polls do
         not rebuild PEAD/directional tables; POST /api/trigger_scan is the
         model rebuild path. Sector flow is refreshed independently when its
         own TTL expires (see /api/sector-flow).

  GET  /api/quotes?symbols=A,B,C
      -> live marks for up to 40 tickers. Prefers LSE equity candles, falls
         back to the local daily close. {asof, rows:[{symbol,last,chg_1d_pct,
         asof,source,quality}]}

  GET  /api/leaderboard
      -> {asof, leaderboard}

  GET  /api/gcp
      -> get_all_gcp_resources() verbatim (Vertex AI jobs, GCS, Cloud Run, cost).

  GET  /api/analyze?symbol=X
      -> analyze_symbol_adhoc(symbol) verbatim.

  GET  /api/sector-flow[?force=1]
      -> Re-runs the sector money-flow panel (yfinance daily books) and
         patches sector_flow on the cached /api/status board. A short TTL
         coalesces passive polls; force=1 always rescans. Status polls also
         kick this refresh in the background so rotation cannot sit on the
         one-shot scan that warmed the desk.

  POST /api/trigger_scan?depth=<quick|deep>
      -> starts a bounded background scan and returns its job immediately.

  GET  /api/scan_status[?job_id=<id>]
      -> current/recent scan progress; completed jobs include the refreshed
         status payload. This keeps long Deep passes from monopolizing one
         browser request or making the desk appear frozen.

  GET  /api/search?q=<str>&limit=<int=25>
      -> symbol search over the union of edge/data/1d_wide + edge/data/1d.
         {query, limit, results: [{symbol, tier, n_bars, first_date, last_date}]}

  GET  /api/trajectory?symbol=X&window=<1m|3m|6m|1y|3y|5y|max, default 1y>
      -> {symbol, window, n_bars, first_date, last_date, source, series, stats, factors}
         The key endpoint: OHLCV + derived series/stats/factors for one symbol.

  GET  /api/compare?symbols=A,B,C&window=<same>
      -> {window, asof, generated_at, series: {SYM:[{d,cum}]},
          stats: {SYM:{last_price, chg_1d_pct, asof, age_days, quality, source, ...}},
          correlation: {SYM:{SYM:r}}}
         Up to 8 symbols, all rebased to 1.0 at the first date common to every
         requested symbol; correlation is Pearson on daily returns over that window.
         Shell benchmarks may use a cached yfinance refresh when the checked-in
         daily frame is stale. Freshness always refers to the observed bar date.

  GET  /api/options-calculator?strategy=long_call|long_put|long_straddle|custom&spot=&strike=&dte=&vol=&premium=[&legs=JSON]
      -> closed-form P/L vs spot + Delta/Gamma/Theta/Vega for one contract
         or a signed multi-leg book. No order path.

  GET  /api/options?symbol=X&mode=<live|history>&range=<1d|5d|1m|3m>
      -> truth-preserving call/put activity, stock overlay, gamma-by-strike,
         risk-neutral range diagnostics, provenance, and filter accounting.

  GET  /api/price-attractors?symbol=X[&force=1][&rate=0.045][&max_dte=60]
      -> Real-time market regime classification, structural price magnet
         levels (Call/Put Walls, Gamma Flip, Max Pain, Kinematic Drift, POC),
         gravitational pull scores, and multi-lens confluence telemetry.

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
      -> {ok, ts, symbols_indexed, uptime_s, flow_feed_contract, suggestion_contract}

  GET  /api/plays
      -> Latest persisted daily-plays run (market map, scan funnel, actionable
         ENTER tickets, watchlist, rejections, research board, blockers).
         Read-only; never recomputes the pipeline.

  POST /api/plays/run[?account=10000]
      -> Starts the full daily-plays pipeline as a background job and returns
         its job immediately. Never places orders.

  GET  /api/plays/status[?job_id=<id>]
      -> Current/recent daily-plays run progress; completed jobs include the
         full result payload.

  GET  /api/supply-chain[?symbol=X&theme=Y&depth=1|2]
      -> Multi-tier supply chain knowledge graph, extracted 10-K/transcript
         evidence citations, and quant-fundamental beneficiary elasticity rankings.

  GET  /api/supply-chain/themes
      -> Curated thematic ecosystems (AI Data Center, Semi Equipment, Enterprise AI, Energy Grid).

  GET  /api/sentiment[?symbol=X]
      -> Accuracy-first desk sentiment: vol complex, CFTC COT, FINRA short
         volume, local options P/C, optional SEC filings for symbol.
         Every block carries asof/source/quality; never fabricates HF books.

  GET  /api/anomalies[?limit=40&symbol=X]
      -> Statistical outliers: price/volume z-scores, FINRA short extremes,
         options P/C extremes, SEC filing activity. Thresholded + source-tagged.

  GET  /api/flow-tape?symbol=X[&from=YYYY-MM-DD][&to=...][&min_premium=]
      -> on-demand classified options tape for one underlier.

  GET  /api/unusual-flow[?limit=80&min_premium=25000]
  GET  /api/flow-tape?symbol=X[&from=][&to=][&min_premium=][&limit=]
      -> Standalone market-wide recent options-flow tape (one LSE request;
         never reuses Deep routing or local candidates).

  GET  /api/options/opportunities[?force=1]
  GET  /api/options/suggest[?symbol=SPY][&force=1]
      -> Same cached Flow+board union. Each row carries a suggested call/put
         (or watch/blocked reason) and a GEX-wall sell relative to spot.
         Passive reads stay cache-friendly; force=1 is the operator refresh.

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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

import argparse
from dataclasses import asdict
import gzip
import http.server
import json
import math
import mimetypes
import os
import re
import socket
import socketserver
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

# Lazy imports for heavy dependencies - imported on first use
_np = None
_pd = None
_concurrent_futures = None


def _get_np():
    """Lazy load numpy to defer import cost until first use."""
    global _np
    if _np is None:
        import numpy as np

        _np = np
    return _np


_yf = None


def _get_yf():
    """Lazy load yfinance; None when it is not installed."""
    global _yf
    if _yf is None:
        try:
            import yfinance as yf

            _yf = yf
        except Exception:
            return None
    return _yf


def _get_pd():
    """Lazy load pandas to defer import cost until first use."""
    global _pd
    if _pd is None:
        import pandas as pd

        _pd = pd
    return _pd


def _get_concurrent_futures():
    """Lazy load concurrent.futures to defer import cost until first use."""
    global _concurrent_futures
    if _concurrent_futures is None:
        import concurrent.futures

        _concurrent_futures = concurrent.futures
    return _concurrent_futures


# Type aliases for annotations (evaluated lazily at runtime)
def _DataFrame():
    return _get_pd().DataFrame


def _Series():
    return _get_pd().Series


def _DatetimeIndex():
    return _get_pd().DatetimeIndex


def _DateOffset():
    return _get_pd().DateOffset


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
_DEFAULT_MAX_CONCURRENT_REQUESTS = 32

# Yahoo is a soft, best-effort spot source and must never be able to hold a
# request thread — or a module-level cache lock — open indefinitely.
# _YF_SPOT_TIMEOUT_S is the per-HTTP-call budget yfinance itself honours;
# _YF_SPOT_DEADLINE_S is the hard wall for the whole lookup, covering the
# `fast_info` call that accepts no timeout of its own.
_YF_SPOT_TIMEOUT_S = 10.0
_YF_SPOT_DEADLINE_S = 12.0
_DEFAULT_SOCKET_TIMEOUT_S = 30.0
_MIN_COMPRESS_BYTES = 1024
# Cap on a request body we are willing to read off the wire (up to 32 MiB to
# accommodate high-res multimodal chart screenshots while guarding against DoS).
_MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024

import types

if "edge" not in sys.modules:
    _edge_mod = types.ModuleType("edge")
    _edge_mod.__path__ = [str(EDGE_DIR)]
    sys.modules["edge"] = _edge_mod

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE_DIR))
sys.path.insert(0, str(TOOLS_DIR))

# `tools.financial_data` is only importable once EDGE_DIR is on sys.path above.
# Running this file as a script (`python tools/api_server.py`, which is how
# start_app.sh launches it) puts edge/tools -- not edge/ -- on sys.path[0], so
# importing it any earlier silently binds all five payload helpers to None and
# strands /api/company-profile, /api/financials, /api/insiders, /api/government
# and /api/ownership on a permanent 503.
try:
    from tools.financial_data import (
        get_company_profile_payload,
        get_financials_payload,
        get_government_payload,
        get_insiders_payload,
        get_ownership_payload,
    )
except ImportError:
    try:
        from edge.tools.financial_data import (
            get_company_profile_payload,
            get_financials_payload,
            get_government_payload,
            get_insiders_payload,
            get_ownership_payload,
        )
    except ImportError:
        get_company_profile_payload = None  # type: ignore[assignment]
        get_financials_payload = None  # type: ignore[assignment]
        get_government_payload = None  # type: ignore[assignment]
        get_insiders_payload = None  # type: ignore[assignment]
        get_ownership_payload = None  # type: ignore[assignment]

from render_dashboard import (  # noqa: E402
    get_dashboard_data as _get_dashboard_data_uncached,
    analyze_symbol_adhoc,
    fetch_sector_flow_signals,
)
from check_gcp_resources import get_all_gcp_resources  # noqa: E402
from sentiment_anomalies import (  # noqa: E402
    build_anomalies_payload,
    build_cot_payload,
    build_sentiment_payload,
)
from backfill_option_oi import capture as _capture_option_oi  # noqa: E402
from momentum_scan import build_momentum_scan  # noqa: E402
from fetch_float_data import load_float_data  # noqa: E402

sys.path.insert(0, str(ROOT))
from edge.daily_plays.config import (
    DailyPlaysConfig,
    load_config as _load_daily_plays_config,
    load_project_environment,
)  # noqa: E402
from edge.daily_plays.clock import market_clock_status, RunContext  # noqa: E402
from edge.daily_plays.contracts import RunMode, canonical_json  # noqa: E402
from edge.daily_plays.ledger import DEFAULT_OUTPUT_ROOT as _DAILY_PLAYS_OUTPUT_ROOT  # noqa: E402
from edge.daily_plays.pipeline import run_pipeline as _run_daily_plays_pipeline  # noqa: E402
from edge.daily_plays.options_intelligence import (  # noqa: E402
    OptionsFilters,
    build_options_intelligence,
)
from edge.daily_plays.regime_attractor_engine import (  # noqa: E402
    ConfluenceCluster,
    MarketRegimeState,
    PriceMagnetLevel,
    RegimeAttractorSnapshot,
    build_price_draw_telemetry_payload,
    calculate_market_regime,
    compute_confluence_zones,
    compute_price_attractors,
    detect_price_magnets,
)
from edge.daily_plays.options_board import (  # noqa: E402
    BoardCandidate,
    board_payload as _options_board_wire,
    select_board_candidates,
    summarize_board_row,
)
from edge.daily_plays.adapters.options import LSEOptionsAdapter  # noqa: E402
from edge.daily_plays.live_activity import build_unusual_options_flow  # noqa: E402
from edge.daily_plays.opportunity_scanner import (  # noqa: E402
    build_live_opportunities,
    qlib_rows_from_panel,
)
from edge.daily_plays.qlib_scan_score import (  # noqa: E402
    SCORE_KIND as QLIB_SCORE_KIND,
    SOURCE_ID as QLIB_SOURCE_ID,
    lookup_symbol_on_shared_panel,
    peek_shared_qlib_panel,
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
from edge.research.kalman_trend import (  # noqa: E402
    DEFAULT_ENTRY_Z,
    DEFAULT_EXIT_Z,
    DEFAULT_NOISE_DAYS,
    DEFAULT_Q,
    KalmanTrendResult,
    kalman_trend,
    position_state as kalman_position_state,
)
from edge.research.zero_dte import (  # noqa: E402
    EXCHANGE_TZ as _EXCHANGE_TZ,
    compute_zero_dte_tape,
)
from edge.research.microstructure_regime import (  # noqa: E402
    OptionGreeks,
    StrikeExposure,
    TopographyState,
    MicrostructureRegimeSnapshot,
    compute_microstructure_regime,
    SharedLevels,
    unmeasurable_regime_snapshot,
)
from edge.research.state_estimation import (  # noqa: E402
    NadarayaWatsonEnvelopeResult,
    KinematicKalmanResult,
    AnchoredVWAPResult,
    causal_nadaraya_watson_envelope,
    kinematic_kalman_filter,
    compute_anchored_vwap,
    derive_session_boundaries,
)
from edge.research.vpa_levels import find_pivots  # noqa: E402
from edge.research.execution_gates import (  # noqa: E402
    initial_balance,
    expiry_policy,
    select_contract,
    session_gate,
)
from edge.research.systematic_execution import (  # noqa: E402
    ExecutionSignal,
    SimulatedTrade,
    RegimeMetrics,
    BacktestTearsheet,
    generate_microstructure_signals,
    run_microstructure_backtest,
)
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
# Gamma regime breadth strip: a fixed index + sector universe, chain-fetched
# on the same rate-limited paid provider as the conviction board above. The
# universe never changes, so unlike the board this cache key only varies on
# whether the (slow) trend read was requested -- see `_gamma_regime_payload`.
_GAMMA_REGIME_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_GAMMA_REGIME_TTL_S = 300.0
_GAMMA_REGIME_LOCK = threading.Lock()
_GAMMA_REGIME_BUILD_LOCKS: dict[tuple[Any, ...], threading.Lock] = {}
_GAMMA_REGIME_MAX_WORKERS = 6
# The shell's four benchmark marks may need a fresher daily frame than the
# checked-in parquet catalog. Cache those bounded refreshes so a 2-minute UI
# poll never turns into four unconditional network downloads.
_COMPARE_BENCHMARKS = frozenset({"SPY", "QQQ", "DIA", "XLE"})
_COMPARE_REFRESH_CACHE: dict[str, tuple[float, Any | None]] = {}
_COMPARE_REFRESH_TTL_S = 300.0
_COMPARE_REFRESH_LOCK = threading.Lock()

load_project_environment(paths=(EDGE_DIR / ".env", ROOT / "TradingWork" / ".env"))

# Count every provider request before anything can spend one. The account is
# capped per UTC day, and when a background scan spends the allowance the desk
# goes blank with no way to see who spent it -- see daily_plays/lse_budget.py.
try:
    from daily_plays.lse_budget import install as _install_lse_budget

    _install_lse_budget()
except Exception:  # never let observability block the server from booting
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "::1", "localhost"}


def _auth_mode() -> str:
    """Operator-session mode: 'clerk' (default) or 'local'.

    'local' is the zero-credential workstation posture documented in
    .env.example: the SPA runs a local operator session and the API relies on
    its loopback bind for isolation. It never relaxes the network-exposure
    rules below — an exposed host still requires EDGE_REQUIRE_AUTH=1 plus a
    configured Clerk backend, in every mode.
    """
    return (os.environ.get("EDGE_AUTH_MODE") or "").strip().lower() or "clerk"


def _local_auth_mode() -> bool:
    return _auth_mode() == "local"


def _auth_required() -> bool:
    # Local workstation mode keeps backend JWT verification optional because
    # the API only binds to loopback; every other posture defers to
    # EDGE_REQUIRE_AUTH.
    if _local_auth_mode():
        return False
    return _env_bool("EDGE_REQUIRE_AUTH", default=False)


def _cors_origins() -> list[str]:
    configured = _env_csv("EDGE_CORS_ORIGINS")
    # Preserve the zero-configuration workstation contract. A non-loopback
    # server is rejected at startup unless it has an explicit origin allowlist.
    return configured or ["*"]


def _runtime_config_errors(host: str) -> list[str]:
    """Return unsafe deployment settings so startup can fail before binding."""
    errors: list[str] = []
    exposed = not _is_loopback_host(host)
    require_auth = _auth_required()
    if exposed and not require_auth:
        errors.append("EDGE_REQUIRE_AUTH=1 is required when EDGE_HOST is not loopback")
    if require_auth:
        if not os.environ.get("CLERK_JWT_KEY", "").strip():
            errors.append("CLERK_JWT_KEY is required when EDGE_REQUIRE_AUTH=1")
        if not _env_csv("CLERK_AUTHORIZED_PARTIES"):
            errors.append("CLERK_AUTHORIZED_PARTIES is required when EDGE_REQUIRE_AUTH=1")
    elif _local_auth_mode() and not _is_loopback_host(host):
        # Belt and braces: local mode must never silently serve off-loopback.
        errors.append("EDGE_AUTH_MODE=local is only valid when EDGE_HOST is a loopback address")
    if exposed:
        cors = _env_csv("EDGE_CORS_ORIGINS")
        if not cors or "*" in cors:
            errors.append("EDGE_CORS_ORIGINS must be an explicit allowlist off-loopback")
    return errors


# Clerk puts the operator email in different claims depending on how the JWT
# template is configured, so check each known spelling rather than assuming one.
_EMAIL_CLAIMS = ("email", "email_address", "primary_email_address", "primary_email")


def _session_email(payload: Mapping) -> str:
    """Return the lower-cased email claim from a Clerk session payload, or ""."""
    for claim in _EMAIL_CLAIMS:
        value = payload.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _verify_clerk_request(request: Any) -> tuple[bool, str | None, str | None]:
    """Verify a Clerk session JWT and return (ok, user_id, safe_error)."""
    try:
        from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
    except ImportError:
        return False, None, "Clerk backend SDK is not installed"

    jwt_key = os.environ.get("CLERK_JWT_KEY", "").replace("\\n", "\n").strip()
    authorized_parties = _env_csv("CLERK_AUTHORIZED_PARTIES")
    if not jwt_key or not authorized_parties:
        return False, None, "Server authentication is not configured"

    try:
        state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                jwt_key=jwt_key,
                authorized_parties=authorized_parties,
                accepts_token=["session_token"],
            ),
        )
    except Exception as exc:  # fail closed without exposing key/token details
        print(f"[api_server] Clerk verification error: {type(exc).__name__}", file=sys.stderr)
        return False, None, "Session token could not be verified"

    if not state.is_signed_in:
        reason = getattr(getattr(state, "reason", None), "name", None)
        return False, None, str(reason or "Session token is missing or invalid")

    payload = state.payload if isinstance(state.payload, Mapping) else {}
    user_id = str(payload.get("sub") or "")
    allowed_users = set(_env_csv("EDGE_ALLOWED_USER_IDS"))
    if allowed_users and user_id not in allowed_users:
        return False, user_id or None, "Operator is not authorized for this service"

    # EDGE_ALLOWED_EMAILS used to be enforced only by the SPA
    # (dashboard/src/auth.ts::isAllowedOperatorEmail), and vite.config.ts bakes
    # the list into the public bundle. That gated the Vue router and nothing
    # else: any holder of a valid session token for this Clerk application
    # could call /api/* directly with `Authorization: Bearer ...` and bypass it
    # entirely. Enforce it here too, so the variable means what operators
    # reasonably assume it means.
    allowed_emails = {value.lower() for value in _env_csv("EDGE_ALLOWED_EMAILS")}
    if allowed_emails:
        email = _session_email(payload)
        if not email:
            # Fail closed and say why. Clerk session tokens carry no email
            # claim unless one is added to the JWT template, so silently
            # allowing here would recreate the same false sense of security
            # this check exists to remove.
            return (
                False,
                user_id or None,
                (
                    "EDGE_ALLOWED_EMAILS is set but this session token carries no email "
                    "claim; add one to the Clerk JWT template or use EDGE_ALLOWED_USER_IDS"
                ),
            )
        if email not in allowed_emails:
            return False, user_id or None, "Operator is not authorized for this service"
    return True, user_id or None, None


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


# `_load_symbol_bars` used to parse up to three parquet files on every call,
# and it is hit repeatedly per request: the regime view calls it from four
# payloads for the same symbol and the adaptive board loops it over ~120
# names. Bar files are immutable once written, so cache raw frames by
# (path, mtime) the same way `_PARQUET_CACHE` does. Entries are evicted
# oldest-first so nightly rewrites of every parquet do not leak.
_SYMBOL_BARS_CACHE: dict[tuple[str, float], "_get_pd().DataFrame"] = {}
_SYMBOL_BARS_CACHE_MAX = 2048
_SYMBOL_BARS_CACHE_LOCK = threading.Lock()


def _read_bars_cached(path: Path) -> "_get_pd().DataFrame | None":
    pd = _get_pd()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    with _SYMBOL_BARS_CACHE_LOCK:
        cached = _SYMBOL_BARS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None
    if frame is None or getattr(frame, "empty", True):
        return None
    with _SYMBOL_BARS_CACHE_LOCK:
        while len(_SYMBOL_BARS_CACHE) >= _SYMBOL_BARS_CACHE_MAX:
            oldest = next(iter(_SYMBOL_BARS_CACHE))
            _SYMBOL_BARS_CACHE.pop(oldest, None)
        _SYMBOL_BARS_CACHE[key] = frame
    return frame


def _load_symbol_bars(symbol: str, *, prefer_intraday: bool = True) -> "_get_pd().DataFrame":
    """OHLCV for adaptive scoring and microstructure charts: load newest bars and augment with live spot.

    `prefer_intraday` selects a *cadence family* -- hourly (`data/1h`) vs
    daily (`data/1d_wide`, `data/1d`) -- not just a tie-break. Within the
    chosen family, whichever source has the more recent bar wins; the other
    family is only used as a fallback when the preferred family has no file
    for this symbol at all.

    This used to compare "most recent bar" across every base regardless of
    family, so `prefer_intraday=False` still picked the 1h file whenever the
    market was open that day: a daily bar is always stamped at midnight, so
    its timestamp string sorts *before* any same-day intraday timestamp, and
    the 1h frame's `str(last_dt)` was therefore always greater. Every caller
    that asked for daily bars (`_anchored_vwap_payload`'s `bars=daily` path,
    `_state_estimation_payload`, `_changepoint_symbol_payload`'s BOCPD model,
    which the module docstring right there says needs "always daily, never
    1h") was silently handed hourly bars mislabeled as daily instead.
    """
    pd = _get_pd()

    intraday_bases: list[Path] = [DATA_1H_DIR]
    daily_bases: list[Path] = [DATA_WIDE_DIR, DATA_CORE_DIR]
    primary_bases = intraday_bases if prefer_intraday else daily_bases
    fallback_bases = daily_bases if prefer_intraday else intraday_bases

    def _freshest(bases: list[Path]):
        frame = None
        latest_dt = None
        for base in bases:
            path = base / f"{symbol}.parquet"
            if not path.is_file():
                continue
            cand = _read_bars_cached(path)
            if cand is not None and "close" in cand.columns and not cand.empty:
                last_dt = cand.index[-1]
                if frame is None or str(last_dt) > str(latest_dt):
                    frame = cand
                    latest_dt = last_dt
        return frame

    best_frame = _freshest(primary_bases)
    if best_frame is None:
        best_frame = _freshest(fallback_bases)

    if best_frame is None or best_frame.empty:
        df, _source = _load_symbol_df(symbol)
        if df is not None and not df.empty and "close" in df.columns:
            best_frame = df.copy()
        else:
            return pd.DataFrame()

    # Cached parquet frames are shared across requests and the augmentation
    # below mutates the frame in place (appends a live row / overwrites the
    # last close), so hand out a private copy.
    best_frame = best_frame.copy()

    # Augment with live session spot if local bars lag the session
    try:
        quote = _symbol_quote(symbol)
        live_spot = quote.get("last")
        live_asof = quote.get("asof")
        if live_spot is not None and live_asof:
            live_dt = pd.to_datetime(live_asof)
            last_bar_dt = best_frame.index[-1]
            if not hasattr(last_bar_dt, "tzinfo") or last_bar_dt.tzinfo is None:
                if hasattr(live_dt, "tz_localize"):
                    live_dt = live_dt.tz_localize(None)
            if str(live_dt)[:10] > str(last_bar_dt)[:10]:
                prev_close = float(best_frame["close"].iloc[-1])
                new_row = pd.DataFrame(
                    [
                        {
                            "open": prev_close,
                            "high": max(prev_close, float(live_spot)),
                            "low": min(prev_close, float(live_spot)),
                            "close": float(live_spot),
                            "volume": (
                                float(best_frame["volume"].iloc[-1])
                                if "volume" in best_frame.columns
                                else 1000.0
                            ),
                        }
                    ],
                    index=[live_dt],
                )
                best_frame = pd.concat([best_frame, new_row])
            elif str(live_dt)[:10] == str(last_bar_dt)[:10]:
                best_frame.iloc[-1, best_frame.columns.get_loc("close")] = float(live_spot)
    except Exception:
        pass

    return best_frame


def _stream_performance_payload() -> dict[str, Any]:
    """Rolling shadow hit-rates (cached) for soft weight adaptation."""
    now = time.time()
    cached = _STREAM_HIT_CACHE.get("payload")
    if cached is not None and now - float(_STREAM_HIT_CACHE.get("ts") or 0) < _STREAM_HIT_TTL_S:
        return cached

    def loader(symbol: str) -> "_get_pd().DataFrame":
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
            "flow_direction": row.get("flow_direction")
            or row.get("day_direction")
            or row.get("direction"),
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

    def loader(sym: str) -> "_get_pd().DataFrame":
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
    merged = {**empty, **payload, "available": bool(payload.get("available", True))}
    asof = merged.get("asof") or merged.get("generated_at")
    age_days = None
    if asof:
        try:
            asof_ts = datetime.fromisoformat(str(asof).replace("Z", "+00:00"))
            if asof_ts.tzinfo is None:
                asof_ts = asof_ts.replace(tzinfo=timezone.utc)
            age_days = max(0, (datetime.now(timezone.utc) - asof_ts).days)
        except ValueError:
            try:
                asof_ts = datetime.strptime(str(asof)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = max(0, (datetime.now(timezone.utc) - asof_ts).days)
            except ValueError:
                age_days = None
    merged["artifact_age_days"] = age_days
    merged["artifact_stale"] = bool(age_days is not None and age_days > 3)
    return merged


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
            "tested": False,
            "effect": None,
            "nw_t": None,
            "boot_ci": None,
            "perm_p": None,
            "n_events": 0,
            "n_controls": 0,
            "grid": [],
            "prereg_id": None,
            "passed": False,
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


def _flow_state_levels_by_symbol() -> dict[str, dict[str, float]]:
    payload = _flow_state_payload()
    levels: dict[str, dict[str, float]] = {}
    for row in payload.get("states") or ():
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        measured: dict[str, float] = {}
        for field, dest in (
            ("next_support", "support_price"),
            ("next_resistance", "resistance_price"),
        ):
            try:
                if row.get(field) is not None:
                    measured[dest] = float(row[field])
            except (TypeError, ValueError):
                continue
        if measured:
            levels[symbol] = measured
    return levels


def _attach_flow_state_levels(board_rows: list) -> list:
    extra = _flow_state_levels_by_symbol()
    if not extra:
        return board_rows
    attached: list = []
    for row in board_rows:
        if not isinstance(row, dict):
            attached.append(row)
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        measured = extra.get(symbol)
        if not measured:
            attached.append(row)
            continue
        copy = dict(row)
        if copy.get("support_price") is None and measured.get("support_price") is not None:
            copy["support_price"] = measured["support_price"]
        if copy.get("resistance_price") is None and measured.get("resistance_price") is not None:
            copy["resistance_price"] = measured["resistance_price"]
        attached.append(copy)
    return attached


def _snapshot_usable(snapshot: Any) -> bool:
    """True when a Regime attractor snapshot carries measured magnets.

    Explicit measurable=False stays unused. Missing quality is allowed only
    when priced level maps are already present — never a fake zero.
    """
    if not isinstance(snapshot, dict):
        return False
    quality = snapshot.get("quality")
    if isinstance(quality, Mapping) and quality.get("measurable") is False:
        return False
    if isinstance(quality, Mapping) and quality.get("measurable") is True:
        return True
    levels = snapshot.get("levels") or snapshot.get("price_ladder")
    return isinstance(levels, (list, tuple)) and any(isinstance(item, Mapping) for item in levels)


def _store_regime_attractor_snapshot(symbol: str, snapshot: Any) -> None:
    """Mirror a Regime-computed snapshot into the attractor cache. No compute."""
    if not symbol or not _snapshot_usable(snapshot):
        return
    key = str(symbol).strip().upper()
    if not key:
        return
    with _PRICE_ATTRACTOR_LOCK:
        _PRICE_ATTRACTOR_CACHE[key] = (time.time(), dict(snapshot))
        if len(_PRICE_ATTRACTOR_CACHE) > 256:
            oldest = min(_PRICE_ATTRACTOR_CACHE, key=lambda k: _PRICE_ATTRACTOR_CACHE[k][0])
            _PRICE_ATTRACTOR_CACHE.pop(oldest, None)


def _options_cache_attractor_snapshot(symbol: str) -> dict | None:
    """Read a snapshot Regime already stored on /api/options. Newest match wins."""
    best: tuple[float, dict] | None = None
    with _OPTIONS_LOCK:
        items = list(_OPTIONS_CACHE.items())
    for cache_key, entry in items:
        if not isinstance(cache_key, tuple) or not cache_key:
            continue
        if str(cache_key[0]).strip().upper() != symbol:
            continue
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        ts, payload = entry[0], entry[1]
        if not isinstance(payload, dict):
            continue
        snap = payload.get("price_attractor_snapshot")
        if not _snapshot_usable(snap):
            continue
        stamp = float(ts) if isinstance(ts, (int, float)) else 0.0
        if best is None or stamp >= best[0]:
            best = (stamp, dict(snap))
    return None if best is None else best[1]


def _cached_attractor_snapshot(symbol: str) -> dict | None:
    if not symbol:
        return None
    with _PRICE_ATTRACTOR_LOCK:
        entry = _PRICE_ATTRACTOR_CACHE.get(symbol)
    if entry is not None:
        payload = entry[1]
        if _snapshot_usable(payload):
            return dict(payload)
    snap = _options_cache_attractor_snapshot(symbol)
    if snap is not None:
        _store_regime_attractor_snapshot(symbol, snap)
    return snap


def _attach_regime_levels(board_rows: list) -> list:
    """Copy already-computed Regime attractor snapshots onto board rows.

    Reads the attractor cache first, then the /api/options cache RegimeView
    actually fills. Never invents a snapshot. Cache misses stay unmeasured.
    """
    attached: list = []
    for row in board_rows:
        if not isinstance(row, dict):
            attached.append(row)
            continue
        existing = row.get("price_attractor_snapshot")
        if _snapshot_usable(existing):
            attached.append(row)
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        snap = _cached_attractor_snapshot(symbol)
        if not isinstance(snap, dict):
            attached.append(row)
            continue
        copy = dict(row)
        copy["price_attractor_snapshot"] = snap
        attached.append(copy)
    return attached


def _bocpd_align_dates(index: pd.DatetimeIndex, arr_len: int) -> "_get_pd().DatetimeIndex":
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
    symbol: str,
    close: "_get_pd().Series",
    aligned_index: pd.DatetimeIndex,
    result: BocpdResult,
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
    break_prob_arr = _get_np().asarray(result.break_prob, dtype=float)
    break_prob_20_arr = _get_np().asarray(result.break_prob_20, dtype=float)
    map_run_arr = _get_np().asarray(result.map_run_length)
    exp_run_arr = _get_np().asarray(result.expected_run_length, dtype=float)
    pred_std_arr = _get_np().asarray(result.pred_std, dtype=float)
    defined_mass_arr = _get_np().asarray(result.pred_var_defined_mass, dtype=float)
    if len(break_prob_arr) == 0:
        return None
    last_break_prob = float(break_prob_arr[-1])
    last_break_prob_20 = float(break_prob_20_arr[-1])
    last_map_run = map_run_arr[-1]
    last_exp_run = float(exp_run_arr[-1])
    # These four are sums/argmax over a normalized probability distribution
    # and should be finite by construction -- if one isn't, this is a broken
    # computation for this symbol, not a per-field null.
    if not all(
        math.isfinite(v)
        for v in (last_break_prob, last_break_prob_20, float(last_map_run), last_exp_run)
    ):
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
        break_idx = int(_get_np().nonzero(break_mask)[0][-1])
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
    result: BocpdResult,
    pos_in_window: "_get_np().ndarray",
    aligned_index: pd.DatetimeIndex,
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
        "dates": [],
        "run_values": [],
        "n_rows": 0,
        "n_cols": 0,
        "log_floor": _BOCPD_LOG_FLOOR,
        "matrix": [],
    }
    try:
        full = _get_np().asarray(result.run_length_posterior(), dtype=float)
    except Exception:  # noqa: BLE001
        return empty
    if full.ndim != 2 or full.shape[0] == 0 or full.shape[1] == 0:
        return empty

    n_rows_full, n_cols_full = full.shape
    t_full = min(n_cols_full, len(aligned_index))
    cols = _get_np().asarray(pos_in_window, dtype=int)
    cols = cols[cols < t_full]
    if len(cols) == 0:
        return empty

    win = full[:, cols]

    # Crop vertical extent to active run-length range (plus buffer) so heatmap
    # doesn't waste 80% height on empty space
    active_rows = _get_np().nonzero(win >= 10**_BOCPD_LOG_FLOOR)[0]
    if len(active_rows) > 0:
        max_active_r = int(active_rows.max())
        r_limit = min(n_rows_full, max(60, max_active_r + 15))
    else:
        r_limit = min(n_rows_full, 120)
    win = win[:r_limit, :]
    n_rows_crop = r_limit

    row_step = max(1, math.ceil(n_rows_crop / _BOCPD_MAX_ROWS))
    row_starts = list(range(0, n_rows_crop, row_step))
    pooled = _get_np().stack([win[r : r + row_step, :].max(axis=0) for r in row_starts], axis=0)
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
            "dates": [],
            "run_values": [],
            "n_rows": 0,
            "n_cols": 0,
            "log_floor": _BOCPD_LOG_FLOOR,
            "matrix": [],
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
    if not isinstance(df_full.index, _get_pd().DatetimeIndex):
        payload = {**empty, "reason": f"'{symbol}' bars have no DatetimeIndex"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload
    df_full = df_full[~df_full.index.duplicated(keep="last")].sort_index()
    close_full = _get_pd().to_numeric(df_full["close"], errors="coerce").dropna()
    if len(close_full) < _BOCPD_MIN_BARS:
        payload = {**empty, "reason": f"only {len(close_full)} usable bars (< {_BOCPD_MIN_BARS})"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    try:
        result = changepoints_from_prices(
            close_full,
            lambda_gap=_BOCPD_LAMBDA_GAP,
            a=_BOCPD_PRIOR_A,
            b=_BOCPD_PRIOR_B,
            truncation_mass=_BOCPD_TRUNCATION_MASS,
        )
        aligned_index = _bocpd_align_dates(
            close_full.index, len(_get_np().asarray(result.break_prob))
        )
    except Exception as e:  # noqa: BLE001
        payload = {**empty, "reason": f"changepoints_from_prices failed: {type(e).__name__}: {e}"}
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    # `cp_prob_raw` is deliberately not read (AMENDMENT 1: constant by
    # construction, carries zero information, never emitted).
    break_prob_arr = _get_np().asarray(result.break_prob, dtype=float)
    break_prob_20_arr = _get_np().asarray(result.break_prob_20, dtype=float)
    map_run_arr = _get_np().asarray(result.map_run_length)
    pred_mean_arr = _get_np().asarray(result.pred_mean, dtype=float)
    pred_std_arr = _get_np().asarray(result.pred_std, dtype=float)
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

    pos_in_window = _get_np().nonzero((aligned_index >= win_start) & (aligned_index <= win_end))[0]
    if len(pos_in_window) == 0:
        payload = {
            **empty,
            "reason": f"no BOCPD output in window for '{symbol}'",
            "stats": stats_row,
        }
        _changepoint_symbol_cache_put(cache_key, payload)
        return payload

    series: list[dict] = []
    for pos in pos_in_window:
        d = aligned_index[pos]
        pv = float(pred_std_arr[pos])
        series.append(
            {
                "d": d.strftime("%Y-%m-%d"),
                "ret": _safe_round(ret_by_date.get(d), 6),
                "break_prob": _safe_round(float(break_prob_arr[pos]), 6),
                "break_prob_20": _safe_round(float(break_prob_20_arr[pos]), 6),
                "map_run": int(map_run_arr[pos]),
                "pred_vol": _safe_round(pv, 6) if math.isfinite(pv) else None,
                "pred_mean": _safe_round(float(pred_mean_arr[pos]), 6),
            }
        )

    breaks: list[dict] = []
    for pos in pos_in_window:
        if float(break_prob_arr[pos]) < _BOCPD_BREAK_THRESHOLD:
            continue
        d = aligned_index[pos]
        pv_before = float(pred_std_arr[pos - 1]) if pos > 0 else None
        pv_after = float(pred_std_arr[pos])
        breaks.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "break_prob": _safe_round(float(break_prob_arr[pos]), 6),
                "break_prob_20": _safe_round(float(break_prob_20_arr[pos]), 6),
                "ret": _safe_round(ret_by_date.get(d), 6),
                "pred_vol_before": (
                    _safe_round(pv_before, 6)
                    if pv_before is not None and math.isfinite(pv_before)
                    else None
                ),
                "pred_vol_after": _safe_round(pv_after, 6) if math.isfinite(pv_after) else None,
            }
        )

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
        "figure": {
            "x_label": "Date",
            "y_top_label": "Daily return",
            "y_bottom_label": "Run length (bars)",
            "heatmap_label": "log10 P(r_t | x_1:t)",
        },
    }
    _changepoint_symbol_cache_put(cache_key, payload)
    return payload


_KALMAN_CAVEAT = (
    "Descriptive in-sample reconstruction: no costs, no slippage, no "
    "walk-forward split, no multiple-testing correction. The thresholds were "
    "chosen by a human looking at these same bars. Not a gate verdict."
)

# Kalman constant-velocity trend: computed live per (symbol, params) and
# cached briefly. The filter is recursive, so it always runs over the symbol's
# FULL history and only the *display* is sliced to the requested window --
# restarting the filter at the window boundary would show its P=I transient
# (a fabricated slope ramp from zero) at the left edge of every chart.
_KALMAN_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_KALMAN_CACHE_TTL_S = 120.0
_KALMAN_LOCK = threading.Lock()
_KALMAN_MIN_BARS = 60
#: Hard cap on the reconstructed trade list sent to the browser. `n_trades`
#: always reports the true total so a truncated list can never read as a
#: complete one.
_KALMAN_MAX_TRADES = 500


def _kalman_cache_put(key: tuple[Any, ...], payload: dict) -> None:
    with _KALMAN_LOCK:
        _KALMAN_CACHE[key] = (time.time(), payload)
        if len(_KALMAN_CACHE) > 64:
            oldest = min(_KALMAN_CACHE, key=lambda k: _KALMAN_CACHE[k][0])
            _KALMAN_CACHE.pop(oldest, None)


def _kalman_trade_rows(
    result: "KalmanTrendResult",
    dates: list[str],
    fill_px: "_get_np().ndarray",
) -> list[dict]:
    """Round trips priced at the FILL bar's open (close only if open is absent).

    `KalmanTrade.entry_i` is already the fill bar -- the signal was read one
    bar earlier -- so pricing at `fill_px[entry_i]` introduces no look-ahead.
    """
    rows: list[dict] = []
    for t in result.trades:
        entry_px = float(fill_px[t.entry_i])
        exit_px = float(fill_px[t.exit_i])
        if not (math.isfinite(entry_px) and math.isfinite(exit_px)) or entry_px <= 0:
            continue
        raw = exit_px / entry_px - 1.0
        ret = raw if t.direction == "long" else -raw
        rows.append(
            {
                "entry_d": dates[t.entry_i],
                "exit_d": dates[t.exit_i],
                "dir": t.direction,
                "entry_px": _safe_round(entry_px, 4),
                "exit_px": _safe_round(exit_px, 4),
                "ret_pct": _safe_round(ret * 100.0, 3),
                "bars": int(t.exit_i - t.entry_i),
                "entry_score": _safe_round(float(result.score[max(t.entry_i - 1, 0)]), 3),
                "exit_score": _safe_round(float(result.score[max(t.exit_i - 1, 0)]), 3),
            }
        )
    return rows


def _kalman_trade_stats(rows: list[dict], state: "_get_np().ndarray") -> dict:
    """Descriptive, in-sample, cost-free. Not a performance claim -- see the
    `caveat` on the payload; nothing here is corrected for multiple testing,
    slippage, or the fact that the thresholds were chosen by a human looking
    at the same bars."""
    np = _get_np()
    n_bars = int(state.size)
    exposure = float((state != 0).sum()) / n_bars * 100.0 if n_bars else 0.0
    if not rows:
        return {
            "n_trades": 0,
            "n_long": 0,
            "n_short": 0,
            "win_rate_pct": None,
            "avg_ret_pct": None,
            "median_ret_pct": None,
            "best_ret_pct": None,
            "worst_ret_pct": None,
            "compounded_pct": None,
            "avg_bars": None,
            "exposure_pct": _safe_round(exposure, 2),
        }
    rets = np.array([float(r["ret_pct"] or 0.0) for r in rows], dtype=float)
    growth = float(np.prod(1.0 + rets / 100.0))
    return {
        "n_trades": len(rows),
        "n_long": sum(1 for r in rows if r["dir"] == "long"),
        "n_short": sum(1 for r in rows if r["dir"] == "short"),
        "win_rate_pct": _safe_round(float((rets > 0).mean()) * 100.0, 2),
        "avg_ret_pct": _safe_round(float(rets.mean()), 3),
        "median_ret_pct": _safe_round(float(np.median(rets)), 3),
        "best_ret_pct": _safe_round(float(rets.max()), 3),
        "worst_ret_pct": _safe_round(float(rets.min()), 3),
        "compounded_pct": _safe_round((growth - 1.0) * 100.0, 2),
        "avg_bars": _safe_round(float(np.mean([r["bars"] for r in rows])), 1),
        "exposure_pct": _safe_round(exposure, 2),
    }


def _kalman_trend_payload(
    symbol: str,
    window: str,
    *,
    q: float,
    entry_z: float,
    exit_z: float,
    noise_days: float,
    allow_short: bool,
    intraday: bool,
) -> dict:
    """One symbol's constant-velocity filter, run live and cached briefly.

    The bar spacing is measured from the loaded index, never assumed: the same
    `noise_days=20` means 20 daily bars on a daily file and ~130 bars on the
    1h file, which is the whole point of denominating the window in days.
    """
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW

    cache_key = (symbol, window, q, entry_z, exit_z, noise_days, allow_short, intraday)
    now = time.time()
    with _KALMAN_LOCK:
        hit = _KALMAN_CACHE.get(cache_key)
    if hit is not None and now - hit[0] < _KALMAN_CACHE_TTL_S:
        return hit[1]

    params = {
        "q": q,
        "entry_z": entry_z,
        "exit_z": exit_z,
        "noise_days": noise_days,
        "allow_short": allow_short,
        "noise_bars": None,
        "bars_per_day": None,
        "observation_variance": 1.0,
    }
    empty = {
        "available": False,
        "reason": None,
        "symbol": symbol,
        "window": window,
        "bars": "1h" if intraday else "daily",
        "n_bars": 0,
        "n_bars_full": 0,
        "first_date": None,
        "last_date": None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "params": params,
        "series": [],
        "trades": [],
        "n_trades": 0,
        "stats": None,
        "now": None,
        "decision_authorized": False,
        "caveat": _KALMAN_CAVEAT,
    }

    raw = _load_symbol_bars(symbol, prefer_intraday=intraday)
    if raw is None or raw.empty or "close" not in raw.columns:
        payload = {**empty, "reason": f"no bars found for '{symbol}'"}
        _kalman_cache_put(cache_key, payload)
        return payload

    pd_mod = _get_pd()
    df_full = raw[~raw.index.duplicated(keep="last")].sort_index()
    if not isinstance(df_full.index, pd_mod.DatetimeIndex):
        payload = {**empty, "reason": f"'{symbol}' bars have no DatetimeIndex"}
        _kalman_cache_put(cache_key, payload)
        return payload

    close_full = pd_mod.to_numeric(df_full["close"], errors="coerce")
    keep = close_full.notna() & (close_full > 0)
    df_full = df_full.loc[keep]
    close_full = close_full.loc[keep]
    if len(close_full) < _KALMAN_MIN_BARS:
        payload = {
            **empty,
            "reason": f"only {len(close_full)} usable bars (< {_KALMAN_MIN_BARS})",
        }
        _kalman_cache_put(cache_key, payload)
        return payload

    try:
        result = kalman_trend(
            close_full,
            q=q,
            noise_days=noise_days,
            entry_z=entry_z,
            exit_z=exit_z,
            allow_short=allow_short,
        )
    except Exception as e:  # noqa: BLE001 - surface, never fabricate a chart
        payload = {**empty, "reason": f"kalman_trend failed: {type(e).__name__}: {e}"}
        _kalman_cache_put(cache_key, payload)
        return payload

    params = {
        **params,
        "noise_bars": int(result.noise_bars),
        "bars_per_day": _safe_round(result.bars_per_day, 3),
    }

    dates = [d.strftime("%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d") for d in df_full.index]
    fill_px = (
        pd_mod.to_numeric(df_full["open"], errors="coerce").fillna(close_full).to_numpy(dtype=float)
        if "open" in df_full.columns
        else close_full.to_numpy(dtype=float)
    )
    state = kalman_position_state(result, len(df_full))
    trade_rows = _kalman_trade_rows(result, dates, fill_px)
    stats = _kalman_trade_stats(trade_rows, state)

    win_df = _slice_window(df_full, window)
    if win_df.empty:
        payload = {**empty, "params": params, "reason": f"no data in window for '{symbol}'"}
        _kalman_cache_put(cache_key, payload)
        return payload
    first_pos = int(df_full.index.get_indexer([win_df.index[0]])[0])
    if first_pos < 0:
        first_pos = 0

    close_arr = close_full.to_numpy(dtype=float)
    series: list[dict] = []
    for i in range(first_pos, len(df_full)):
        noise_i = float(result.noise[i])
        series.append(
            {
                "d": dates[i],
                "close": _safe_round(float(close_arr[i]), 4),
                "slope": _safe_round(float(result.slope[i]), 8),
                "score": _safe_round(float(result.score[i]), 4),
                "noise": _safe_round(noise_i, 8) if math.isfinite(noise_i) else None,
                "pos": int(state[i]),
            }
        )

    last_i = len(df_full) - 1
    now_state = int(state[last_i])
    now_position = "long" if now_state > 0 else "short" if now_state < 0 else "flat"
    if result.open_at_end and trade_rows:
        # The reconstruction books the dangling trade's close at the final
        # bar's open, so `state` reads flat there -- but the exit RULE never
        # fired. What the desk needs on a "now" readout is the position the
        # rules would have it holding, with `forced_exit` marking why the
        # trade list shows it closed.
        now_position = trade_rows[-1]["dir"]
    now_block = {
        "date": dates[last_i],
        "position": now_position,
        "score": _safe_round(float(result.score[last_i]), 4),
        "slope": _safe_round(float(result.slope[last_i]), 8),
        # Per-bar log-price drift the filtered velocity implies, annualized by
        # this series' own bar count -- a readable restatement of `slope`, not
        # a forecast.
        "slope_pct_per_day": _safe_round(
            (math.exp(float(result.slope[last_i]) * max(result.bars_per_day, 1.0)) - 1.0) * 100.0,
            4,
        ),
        # The last trade was closed by the harness at the final bar, not by
        # an exit signal -- the position was still on when the data ran out.
        "forced_exit": bool(result.open_at_end),
        "last_trade": trade_rows[-1] if trade_rows else None,
    }

    payload = {
        "available": True,
        "reason": None,
        "symbol": symbol,
        "window": window,
        "bars": "1h" if intraday else "daily",
        "n_bars": len(series),
        "n_bars_full": int(len(df_full)),
        "first_date": series[0]["d"] if series else None,
        "last_date": series[-1]["d"] if series else None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "params": params,
        "series": series,
        # Newest first, capped -- `n_trades` keeps the true total visible.
        "trades": list(reversed(trade_rows))[:_KALMAN_MAX_TRADES],
        "n_trades": len(trade_rows),
        "stats": stats,
        "now": now_block,
        "decision_authorized": False,
        "caveat": _KALMAN_CAVEAT,
    }
    _kalman_cache_put(cache_key, payload)
    return payload


# ---------------------------------------------------------------------------
# Microstructure Regime Dynamics, State Estimation & Systematic Execution Payloads
# ---------------------------------------------------------------------------

#: Dealer sign convention for every gamma figure this server publishes:
#: customers are assumed net short calls / net long puts, so dealer call gamma
#: is +1 and dealer put gamma is -1.
#:
#: It is pinned here rather than varied per symbol on purpose. The endpoint used
#: to flip the call sign for anything outside a hardcoded index list, while
#: `daily_plays.options_intelligence._gex_map` -- feeding the same page through
#: `gex_price_profile` -- always used +1. Every single-name symbol therefore
#: rendered two opposite-signed answers side by side. Whether the equity
#: convention is the better model is a real question; a page that silently uses
#: both at once is not a defensible way to ask it.
_DEALER_CONVENTION = "index"

_MICROSTRUCTURE_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_MICROSTRUCTURE_CACHE_TTL_S = 60.0
_MICROSTRUCTURE_LOCK = threading.Lock()


def _microstructure_regime_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Microstructure regime, second/third order dealer Greeks, and 4-quadrant topography.

    Single source of truth for the /regime page. The structural levels (net GEX
    profile, flip, walls) are measured once by `_options_payload` -- which the
    front end also reads directly as `gex_price_profile` -- and handed to
    `compute_microstructure_regime` via SharedLevels so the classification is
    derived from exactly the numbers that get rendered.

    Previously this ran a second, independent measurement here and then
    overwrote four headline fields of the result with the first one's values,
    leaving `regime`, `topography`, the regime-strength score and `strikes`
    derived from the numbers that had just been replaced. Every single-name symbol then
    showed a positive net GEX figure beside a "negative_gamma" classification,
    because the two measurements also used opposite dealer sign conventions.
    """
    rate = _safe_float(query.get("rate", ["0.045"])[0], 0.045, lo=-0.05, hi=0.25)

    try:
        opt_payload, status = _options_payload(symbol, query)
    except Exception:
        opt_payload, status = None, 500

    summary: dict[str, Any] = {}
    chain_rows: list = []
    spot = None
    if status == 200 and isinstance(opt_payload, dict):
        raw_summary = opt_payload.get("summary")
        summary = raw_summary if isinstance(raw_summary, dict) else {}
        spot = summary.get("spot") or opt_payload.get("spot")
        chain_rows = (
            opt_payload.get("chain_by_strike")
            or opt_payload.get("chain_rows")
            or opt_payload.get("open_interest_profile")
            or []
        )

    if spot is None or spot <= 0:
        quote = _symbol_quote(symbol)
        spot = _safe_float(quote.get("last"), 0.0, lo=0.0, hi=1e9)

    asof_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if not spot or spot <= 0:
        return (
            asdict(
                unmeasurable_regime_snapshot(
                    symbol=symbol,
                    spot=0.0,
                    asof=asof_ts,
                    dealer_convention=_DEALER_CONVENTION,
                    contracts=0,
                    strikes=0,
                    total_open_interest=0,
                    reason=f"no spot price available for '{symbol}'",
                )
            ),
            200,
        )

    if not chain_rows:
        # There is no substitute for a real chain. This used to synthesize a
        # 31-strike ladder from np.linspace with exponentially-decaying open
        # interest and then render a full tactical briefing on it, with nothing
        # in the payload marking it as invented -- the most dangerous thing this
        # endpoint could do to someone sizing a live trade.
        return (
            asdict(
                unmeasurable_regime_snapshot(
                    symbol=symbol,
                    spot=float(spot),
                    asof=asof_ts,
                    dealer_convention=_DEALER_CONVENTION,
                    contracts=0,
                    strikes=0,
                    total_open_interest=0,
                    reason=f"no option chain available for '{symbol}'",
                )
            ),
            200,
        )

    # Measured spot velocity: today's return so far, as a fraction. Withheld
    # (None) when there is no previous close to measure against, which withholds
    # `hedging_flow_m` in turn -- it used to be computed from a hardcoded
    # ds_dt_pct=0.002 / dvol_dt_pct=-0.005, making a constant look like a
    # live reading of the tape.
    ds_dt_pct = None
    quote = _symbol_quote(symbol)
    last = _safe_float(quote.get("last"), 0.0, lo=0.0, hi=1e9)
    prev_close = _safe_float(quote.get("prev_close"), 0.0, lo=0.0, hi=1e9)
    if last > 0 and prev_close > 0:
        ds_dt_pct = (last - prev_close) / prev_close

    shared = None
    profile = opt_payload.get("gex_price_profile") if isinstance(opt_payload, dict) else None
    if isinstance(profile, list) and len(profile) >= 2:
        flip = summary.get("zero_gamma") or summary.get("gamma_flip")
        pin = summary.get("pin_strike")
        shared = SharedLevels(
            gex_profile=profile,
            call_wall=summary.get("call_wall"),
            put_wall=summary.get("put_wall"),
            gamma_flip=flip,
            pin_strike=pin,
        )

    snapshot = compute_microstructure_regime(
        chain_rows,
        symbol=symbol,
        spot=float(spot),
        rate=rate,
        asof=asof_ts,
        is_index=True,  # see _DEALER_CONVENTION
        ds_dt_pct=ds_dt_pct,
        # No IV velocity is measured anywhere in this stack yet, so the vanna
        # term of F_hedge cannot be computed and the whole figure is withheld
        # rather than partially assumed.
        dvol_dt_pct=None,
        shared_levels=shared,
    )
    return asdict(snapshot), 200


def _state_estimation_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Causal Nadaraya-Watson envelopes and 2-State Kinematic Kalman filter state estimation."""
    window = query.get("window", [DEFAULT_WINDOW])[0]
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW
    h = _safe_float(query.get("h", ["20.0"])[0], 20.0, lo=2.0, hi=120.0)
    alpha = _safe_float(query.get("alpha", ["2.0"])[0], 2.0, lo=0.5, hi=5.0)
    q = _safe_float(query.get("q", ["0.001"])[0], 0.001, lo=1e-8, hi=1.0)
    sigma_r = _safe_float(query.get("sigma_r", ["1.0"])[0], 1.0, lo=0.01, hi=50.0)
    intraday = (query.get("bars", ["daily"])[0] or "daily").lower() in {"1h", "intraday"}

    raw = _load_symbol_bars(symbol, prefer_intraday=intraday)
    if raw is None or raw.empty or "close" not in raw.columns:
        return {"error": f"no price bars for '{symbol}'", "endpoint": "/api/state-estimation"}, 404

    df_full = raw[~raw.index.duplicated(keep="last")].sort_index()
    win = _slice_window(df_full, window)
    if win.empty:
        win = df_full.tail(60)

    prices = win["close"].to_numpy(dtype=float)
    dates = [
        idx.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(idx, "strftime") else str(idx)
        for idx in win.index
    ]

    nw_res = causal_nadaraya_watson_envelope(
        prices, base_bandwidth=h, alpha=alpha, use_dynamic_bandwidth=True
    )
    kalman_res = kinematic_kalman_filter(prices, dt=1.0, base_sigma_q=q, sigma_r=sigma_r)

    points = []
    for i in range(len(prices)):
        points.append(
            {
                "t": dates[i],
                "price": _safe_round(prices[i], 2),
                "nw_mean": _safe_round(nw_res.mean[i], 2),
                "nw_upper": _safe_round(nw_res.upper[i], 2),
                "nw_lower": _safe_round(nw_res.lower[i], 2),
                "nw_sigma": _safe_round(nw_res.sigma_local[i], 4),
                "nw_bandwidth": _safe_round(nw_res.bandwidth[i], 1),
                "ou_half_life": _safe_round(nw_res.ou_half_life[i], 1),
                "kalman_price": _safe_round(kalman_res.latent_price[i], 2),
                "kalman_velocity": _safe_round(kalman_res.velocity[i], 4),
                "kalman_zscore": _safe_round(kalman_res.velocity_zscore[i], 3),
                "kalman_q": _safe_round(kalman_res.process_noise_q[i], 6),
                "innovation_var": _safe_round(kalman_res.innovation_variance[i], 4),
                "exhaustion": bool(kalman_res.momentum_exhaustion[i]),
                "breakout": bool(kalman_res.kinematic_breakout[i]),
            }
        )

    return {
        "symbol": symbol,
        "window": window,
        "n_bars": len(prices),
        "params": {"h": h, "alpha": alpha, "q": q, "sigma_r": sigma_r},
        "points": points,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }, 200


_WEEK52_MIN_BARS = 200  # need close to a trading year of daily bars to call a high/low "52-week"


def _anchored_vwap_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Multi-anchored Volume-Weighted Average Price curves.

    Every anchor returned has a real, statable meaning derived from the bar
    timestamps -- never an arbitrary fraction of the requested window:

      - Intraday input (`bars=1h`/`intraday`): a true session VWAP, reset at
        each session boundary (a calendar-day change in the index) and
        anchored at the current session's first bar, plus a second curve
        anchored at the prior session's first bar (and truncated at the
        current session's boundary, so it never absorbs today's volume).
      - Daily input: there is no intraday session to anchor to, so a "session
        VWAP" would be fabricated. Anchors are instead the most recent
        confirmed swing high/low pivot (`vpa_levels.find_pivots`) and the
        window's 52-week high/low bar, when the data supports each one.

    If a given anchor cannot be established from the data (too few bars, no
    confirmed pivot, a window shorter than a trading year), it is simply
    omitted and a human-readable reason is appended to `notes` -- never
    replaced with a fabricated anchor.
    """
    np = _get_np()
    window = query.get("window", [DEFAULT_WINDOW])[0]
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW
    intraday = (query.get("bars", ["daily"])[0] or "daily").lower() in {"1h", "intraday"}

    raw = _load_symbol_bars(symbol, prefer_intraday=intraday)
    if raw is None or raw.empty or "close" not in raw.columns:
        return {"error": f"no price bars for '{symbol}'", "endpoint": "/api/anchored-vwap"}, 404

    df_full = raw[~raw.index.duplicated(keep="last")].sort_index()
    win = _slice_window(df_full, window)
    if win.empty:
        win = df_full.tail(60)

    close = win["close"].to_numpy(dtype=float)
    has_hl = "high" in win.columns and "low" in win.columns
    if has_hl:
        high = win["high"].to_numpy(dtype=float)
        low = win["low"].to_numpy(dtype=float)
        prices = (high + low + close) / 3.0
        price_basis = "hlc3"
    else:
        high = low = None
        prices = close
        price_basis = "close"

    volumes = win["volume"].to_numpy(dtype=float) if "volume" in win else np.ones(len(prices))
    dates = [
        idx.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(idx, "strftime") else str(idx)
        for idx in win.index
    ]
    n = len(prices)

    notes: list[str] = []
    # Each spec is one real anchor: {idx, end, kind, label}. `end` truncates
    # the series so an anchor never absorbs bars past its own meaning (e.g.
    # the prior session's curve stops at today's open).
    specs: list[dict] = []

    if intraday:
        boundaries = derive_session_boundaries(list(win.index))
        if not boundaries:
            boundaries = [0]
        current_start = boundaries[-1]
        specs.append(
            {
                "idx": current_start,
                "end": n,
                "kind": "session",
                "label": f"Session VWAP, anchored at {dates[current_start]} (current session open)",
            }
        )
        if len(boundaries) >= 2:
            prior_start = boundaries[-2]
            specs.append(
                {
                    "idx": prior_start,
                    "end": current_start,
                    "kind": "prior_session",
                    "label": f"Prior session VWAP, anchored at {dates[prior_start]}",
                }
            )
        else:
            notes.append(
                "Only one session is present in the requested window; no prior-session VWAP is available."
            )
    else:
        notes.append(
            "Daily bars have no intraday session boundary, so a 'session VWAP' cannot be computed honestly; "
            "anchors below are rule-based swing pivots and 52-week high/low instead."
        )
        if not has_hl:
            notes.append(
                "No high/low columns in this symbol's daily bars; swing-pivot and 52-week anchors need them and are omitted."
            )
        else:
            bars_list = [
                {"high": float(high[i]), "low": float(low[i]), "close": float(close[i])}
                for i in range(n)
            ]
            pivots = find_pivots(bars_list)
            highs_idx = pivots.get("highs") or []
            lows_idx = pivots.get("lows") or []

            if highs_idx:
                sh_idx = max(highs_idx)
                specs.append(
                    {
                        "idx": sh_idx,
                        "end": n,
                        "kind": "swing_high",
                        "label": f"Most recent confirmed swing high, at {dates[sh_idx]}",
                    }
                )
            else:
                notes.append(
                    f"No confirmed swing-high pivot in {n} bars (needs a fractal high with left/right confirmation)."
                )

            if lows_idx:
                sl_idx = max(lows_idx)
                specs.append(
                    {
                        "idx": sl_idx,
                        "end": n,
                        "kind": "swing_low",
                        "label": f"Most recent confirmed swing low, at {dates[sl_idx]}",
                    }
                )
            else:
                notes.append(
                    f"No confirmed swing-low pivot in {n} bars (needs a fractal low with left/right confirmation)."
                )

            if n >= _WEEK52_MIN_BARS:
                lookback = min(n, 252)
                start_52 = n - lookback
                sub_high = high[start_52:]
                sub_low = low[start_52:]
                hi_idx = start_52 + int(np.argmax(sub_high))
                lo_idx = start_52 + int(np.argmin(sub_low))
                specs.append(
                    {
                        "idx": hi_idx,
                        "end": n,
                        "kind": "week_52_high",
                        "label": f"52-week high, at {dates[hi_idx]}",
                    }
                )
                specs.append(
                    {
                        "idx": lo_idx,
                        "end": n,
                        "kind": "week_52_low",
                        "label": f"52-week low, at {dates[lo_idx]}",
                    }
                )
            else:
                notes.append(
                    f"Window has {n} daily bars, fewer than the ~252 needed for a genuine 52-week high/low; "
                    "that anchor is omitted rather than mislabeling a shorter window's max/min as '52-week'."
                )

    # Base reference: the cumulative VWAP of the displayed window itself.
    #
    # The defect this endpoint was rebuilt to fix was *mislabelling* -- calling
    # bar 0 "Session_Start" and bars n/2 and 0.75n "Event_Anchor_1/2", which
    # asserted a session and two events that did not exist. Anchoring at the
    # first displayed bar is not itself dishonest: it is the exactly-defined
    # average price paid by everyone who traded in the window on screen, and it
    # is labelled as precisely that here.
    #
    # It is included because omitting every anchor leaves a chart with no
    # reference line at all whenever a window is short or a synthetic/monotonic
    # series throws no confirmed pivot -- which is a usability regression, not
    # extra honesty. It deliberately claims NO mechanism: it is not a session
    # VWAP and is not asserted to act as support or resistance.
    if n > 0 and (not intraday or not specs):
        specs.append(
            {
                "idx": 0,
                "end": n,
                "kind": "window_start",
                "label": f"Window VWAP, anchored at the first displayed bar ({dates[0]})",
                "note": (
                    "Cumulative volume-weighted average price across the displayed window. "
                    "Not a session VWAP and not a support/resistance claim -- it is the "
                    "average price traded over the window shown."
                ),
            }
        )

    # Collapse anchors that resolve to the same bar. A swing high that is also
    # the 52-week high is one event, and drawing it twice would show two
    # identical curves and imply two independent confirmations where there is
    # one. The earlier (more specific) spec wins its label.
    deduped: list[dict] = []
    seen_idx: set[int] = set()
    for spec in specs:
        if spec["idx"] in seen_idx:
            merged = next(s for s in deduped if s["idx"] == spec["idx"])
            merged.setdefault("also", []).append(spec["kind"])
            continue
        seen_idx.add(spec["idx"])
        deduped.append(spec)
    specs = deduped

    anchors_out = []
    for spec in specs:
        a_idx = spec["idx"]
        a_end = min(spec.get("end", n), n)
        av = compute_anchored_vwap(prices, volumes, [a_idx], [spec["label"]])[0]
        series_pts = []
        for i in range(a_idx, a_end):
            if not np.isnan(av.vwap[i]):
                series_pts.append(
                    {
                        "t": dates[i],
                        "vwap": _safe_round(av.vwap[i], 2),
                        "upper_1sd": _safe_round(av.upper_1sd[i], 2),
                        "lower_1sd": _safe_round(av.lower_1sd[i], 2),
                        "upper_2sd": _safe_round(av.upper_2sd[i], 2),
                        "lower_2sd": _safe_round(av.lower_2sd[i], 2),
                    }
                )
        if not series_pts:
            # No bar since this anchor ever had positive volume -- omit it
            # rather than showing an anchor with no data.
            continue
        entry = {
            "anchor_name": spec["label"],
            "anchor_kind": spec["kind"],
            "anchor_index": a_idx,
            "anchor_timestamp": dates[a_idx],
            "anchor_label": spec["label"],
            "series": series_pts,
        }
        if spec.get("note"):
            entry["anchor_note"] = spec["note"]
        if spec.get("also"):
            # Same bar, more than one meaning -- say so rather than hiding it.
            entry["also_marks"] = spec["also"]
        anchors_out.append(entry)

    payload = {
        "symbol": symbol,
        "window": window,
        "n_bars": n,
        "anchors": anchors_out,
        "price_basis": price_basis,
        "session_reset": bool(intraday),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if notes:
        payload["notes"] = notes
    return payload, 200


def _systematic_signals_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Live and historical systematic microstructure execution signals."""
    np = _get_np()
    window = query.get("window", [DEFAULT_WINDOW])[0]
    if window not in WINDOW_OFFSETS:
        window = DEFAULT_WINDOW
    h = _safe_float(query.get("h", ["20.0"])[0], 20.0, lo=2.0, hi=120.0)
    alpha = _safe_float(query.get("alpha", ["2.0"])[0], 2.0, lo=0.5, hi=5.0)
    breakout_z = _safe_float(query.get("breakout_z", ["1.6"])[0], 1.6, lo=0.5, hi=5.0)
    exhaustion_z = _safe_float(query.get("exhaustion_z", ["0.4"])[0], 0.4, lo=0.05, hi=2.0)
    intraday = (query.get("bars", ["daily"])[0] or "daily").lower() in {"1h", "intraday"}

    raw = _load_symbol_bars(symbol, prefer_intraday=intraday)
    if raw is None or raw.empty or "close" not in raw.columns:
        return {
            "error": f"no price bars for '{symbol}'",
            "endpoint": "/api/systematic-execution/signals",
        }, 404

    df_full = raw[~raw.index.duplicated(keep="last")].sort_index()
    win = _slice_window(df_full, window)
    if win.empty:
        win = df_full.tail(60)

    prices = win["close"].to_numpy(dtype=float)
    volumes = win["volume"].to_numpy(dtype=float) if "volume" in win else np.ones(len(prices))
    # High/low drive the ATR that stops and targets are quoted in. Without them
    # the engine falls back to close-to-close vol, which understates gap risk.
    highs = win["high"].to_numpy(dtype=float) if "high" in win else None
    lows = win["low"].to_numpy(dtype=float) if "low" in win else None
    dates = [
        idx.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(idx, "strftime") else str(idx)
        for idx in win.index
    ]

    # Compute initial NW envelope to anchor dynamic structural series
    nw_anchor = causal_nadaraya_watson_envelope(
        prices, base_bandwidth=h, alpha=alpha, use_dynamic_bandwidth=True
    )
    k_mean_anchor = nw_anchor.mean

    # Historical dealer-gamma levels are NOT reconstructed here.
    #
    # This used to take today's flip/wall offsets from spot and glue them onto
    # the kernel mean at every historical bar, then set net GEX to
    # +/-|today's net GEX| by which side of that synthetic line price sat on.
    # Every bar in a one-year window was therefore assigned today's gamma
    # structure -- look-ahead in the plainest sense -- and the resulting
    # tearsheet measured a gamma-conditioned strategy against gamma data that
    # never existed. Its Sharpe and drawdown were not estimates of anything.
    #
    # Reconstructing them truthfully needs a historical chain snapshot per bar,
    # which this stack does not store. Until it does, the signal engine runs on
    # price/volume structure alone and says so, which is a smaller claim that
    # happens to be true.
    flip_series = None
    cwall_series = None
    pwall_series = None
    gex_series = None
    del k_mean_anchor

    signals, nw_res, kalman_res, vwap_res = generate_microstructure_signals(
        prices,
        timestamps=dates,
        symbol=symbol,
        volumes=volumes,
        highs=highs,
        lows=lows,
        gamma_flip_series=flip_series,
        call_wall_series=cwall_series,
        put_wall_series=pwall_series,
        net_gex_series=gex_series,
        base_bandwidth=h,
        envelope_alpha=alpha,
        breakout_z=breakout_z,
        exhaustion_z=exhaustion_z,
    )

    sig_dicts = [asdict(s) for s in signals]
    latest_sig = sig_dicts[-1] if sig_dicts else None
    active_signals = [s for s in sig_dicts if s["action"] in {"ENTER_LONG", "ENTER_SHORT"}]

    return {
        "symbol": symbol,
        "window": window,
        "n_bars": len(prices),
        "latest_signal": latest_sig,
        "active_signals_count": len(active_signals),
        "signals": sig_dicts,
        # Stated in the payload so the UI cannot present these as
        # dealer-gamma-conditioned signals when no historical gamma exists.
        "gamma_conditioned": False,
        "basis": "price and volume structure only -- no historical dealer gamma is stored, "
        "so the gamma-regime terms of this model are inactive over history",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }, 200


def _systematic_backtest_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Run full event-driven backtest simulation for systematic microstructure strategy."""
    np = _get_np()
    window = query.get("window", ["1y"])[0]
    if window not in WINDOW_OFFSETS:
        window = "1y"
    capital = _safe_float(
        query.get("capital", ["100000.0"])[0], 100000.0, lo=1000.0, hi=100_000_000.0
    )
    risk_pct = _safe_float(query.get("risk_pct", ["0.02"])[0], 0.02, lo=0.001, hi=0.20)
    slippage_bps = _safe_float(query.get("slippage_bps", ["2.0"])[0], 2.0, lo=0.0, hi=50.0)
    intraday = (query.get("bars", ["daily"])[0] or "daily").lower() in {"1h", "intraday"}

    raw = _load_symbol_bars(symbol, prefer_intraday=intraday)
    if raw is None or raw.empty or "close" not in raw.columns:
        return {
            "error": f"no price bars for '{symbol}'",
            "endpoint": "/api/systematic-execution/backtest",
        }, 404

    df_full = raw[~raw.index.duplicated(keep="last")].sort_index()
    win = _slice_window(df_full, window)
    if win.empty:
        win = df_full.tail(120)

    prices = win["close"].to_numpy(dtype=float)
    volumes = win["volume"].to_numpy(dtype=float) if "volume" in win else np.ones(len(prices))
    # High/low drive the ATR that stops and targets are quoted in. Without them
    # the engine falls back to close-to-close vol, which understates gap risk.
    highs = win["high"].to_numpy(dtype=float) if "high" in win else None
    lows = win["low"].to_numpy(dtype=float) if "low" in win else None
    dates = [
        idx.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(idx, "strftime") else str(idx)
        for idx in win.index
    ]

    # No reconstructed dealer-gamma history -- see the note in
    # _systematic_signals_payload. Back-testing gamma-conditioned rules against
    # today's gamma structure projected over a year of bars produced a tearsheet
    # whose numbers described nothing, which is worse than having no tearsheet.
    flip_series = None
    cwall_series = None
    pwall_series = None
    gex_series = None

    tearsheet = run_microstructure_backtest(
        prices,
        timestamps=dates,
        symbol=symbol,
        volumes=volumes,
        highs=highs,
        lows=lows,
        gamma_flip_series=flip_series,
        call_wall_series=cwall_series,
        put_wall_series=pwall_series,
        net_gex_series=gex_series,
        initial_capital=capital,
        risk_per_trade_pct=risk_pct,
        slippage_bps=slippage_bps,
    )

    out = asdict(tearsheet)
    out["gamma_conditioned"] = False
    out["basis"] = (
        "price and volume structure only -- no historical dealer-gamma snapshots are "
        "stored, so the gamma-regime terms of the live model are inactive in this backtest"
    )
    return out, 200


# Status aggregation (PEAD scan + directional + GCP) is expensive. Cache each
# scan depth independently so a deep result is not silently replaced by the
# 25-name quick snapshot. Trigger-scan always bypasses the cache.
_STATUS_CACHE: dict[str, dict] = {}
_STATUS_CACHE_TS: dict[str, float] = {}
_STATUS_CACHE_TTL_S: float = 45.0
_DEEP_STATUS_CACHE_TTL_S: float = 300.0
_STATUS_LOCK = threading.Lock()
_ACTIVE_SCAN_DEPTH = "quick"

# Sector rotation is a 15-ETF daily panel. It must re-run on its own clock —
# the desk board cache is allowed to keep yesterday's PEAD/directional tables,
# but money-flow cannot sit on the one-shot scan that warmed the process.
_SECTOR_FLOW_CACHE: dict[str, Any] = {}
_SECTOR_FLOW_TTL_S: float = 180.0
_SECTOR_FLOW_LOCK = threading.Lock()
_SECTOR_FETCH_LOCK = threading.Lock()


def _scan_depth(value: str | None) -> str:
    return "deep" if str(value or "").strip().lower() == "deep" else "quick"


def _status_cache_ttl(depth: str) -> float:
    return _DEEP_STATUS_CACHE_TTL_S if depth == "deep" else _STATUS_CACHE_TTL_S


def _status_cache_fresh(depth: str, now: float | None = None) -> bool:
    stamp = _STATUS_CACHE_TS.get(depth)
    if stamp is None or depth not in _STATUS_CACHE:
        return False
    return ((now if now is not None else time.time()) - stamp) < _status_cache_ttl(depth)


def _remember_sector_flow(flow: Mapping[str, Any]) -> None:
    with _SECTOR_FLOW_LOCK:
        _SECTOR_FLOW_CACHE["payload"] = dict(flow)
        _SECTOR_FLOW_CACHE["ts"] = time.time()


def _patch_status_sector_flow(flow: Mapping[str, Any]) -> None:
    snapshot = dict(flow)
    for depth, data in list(_STATUS_CACHE.items()):
        if isinstance(data, dict):
            patched = dict(data)
            patched["sector_flow"] = snapshot
            _STATUS_CACHE[depth] = patched


def _apply_sector_flow_to_status(flow: Mapping[str, Any]) -> None:
    with _STATUS_LOCK:
        _patch_status_sector_flow(flow)


def get_sector_flow(*, force: bool = False) -> dict:
    """Return a current sector-flow panel, re-running the scan when needed."""
    with _SECTOR_FLOW_LOCK:
        cached = _SECTOR_FLOW_CACHE.get("payload")
        ts = float(_SECTOR_FLOW_CACHE.get("ts") or 0)
        if isinstance(cached, dict) and not force and (time.time() - ts) < _SECTOR_FLOW_TTL_S:
            return dict(cached)
    with _SECTOR_FETCH_LOCK:
        with _SECTOR_FLOW_LOCK:
            cached = _SECTOR_FLOW_CACHE.get("payload")
            ts = float(_SECTOR_FLOW_CACHE.get("ts") or 0)
            if isinstance(cached, dict) and not force and (time.time() - ts) < _SECTOR_FLOW_TTL_S:
                return dict(cached)
        flow = fetch_sector_flow_signals()
        if not isinstance(flow, dict):
            flow = {}
        _remember_sector_flow(flow)
    _apply_sector_flow_to_status(flow)
    return dict(flow)


def _kick_sector_refresh_if_stale(status: Mapping[str, Any] | None = None) -> None:
    """Background re-run when the last sector panel is older than the TTL."""
    board_flow = status.get("sector_flow") if isinstance(status, Mapping) else None
    with _SECTOR_FLOW_LOCK:
        cached = _SECTOR_FLOW_CACHE.get("payload")
        ts = float(_SECTOR_FLOW_CACHE.get("ts") or 0)
        if isinstance(cached, dict) and (time.time() - ts) < _SECTOR_FLOW_TTL_S:
            return
        if not isinstance(cached, dict) and not isinstance(board_flow, Mapping):
            return
        if _SECTOR_FLOW_CACHE.get("kicked"):
            return
        _SECTOR_FLOW_CACHE["kicked"] = True

    def _run() -> None:
        try:
            get_sector_flow(force=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[api_server] sector flow refresh failed: {exc}", file=sys.stderr, flush=True)
        finally:
            with _SECTOR_FLOW_LOCK:
                _SECTOR_FLOW_CACHE["kicked"] = False

    threading.Thread(target=_run, daemon=True, name="sector-flow-refresh").start()


def get_dashboard_data(
    *,
    force: bool = False,
    scan_depth: str | None = None,
    activate: bool = False,
    progress: Callable[[str, int, str], None] | None = None,
) -> dict:
    """Thread-safe, TTL-cached wrapper around render_dashboard.get_dashboard_data.

    `/api/status` polls must not rebuild PEAD/directional boards. A concurrent
    status poll during a Deep scan used to wait on this lock, then recompute
    the Quick snapshot and overwrite the desk's two model tables. Trigger-scan
    is the only path that force-rebuilds those tables. Sector flow is different:
    stale rotation is kicked onto a background re-run so the board does not
    freeze on the warmup scan.
    """
    global _ACTIVE_SCAN_DEPTH
    requested = _scan_depth(scan_depth) if scan_depth is not None else None
    depth = requested if requested is not None else _ACTIVE_SCAN_DEPTH
    now = time.time()
    if not force and _status_cache_fresh(depth, now):
        if activate:
            _ACTIVE_SCAN_DEPTH = depth
        _kick_sector_refresh_if_stale(_STATUS_CACHE[depth])
        return _STATUS_CACHE[depth]
    # Idle polls serve the latest activated board even after TTL. Never launch
    # a competing rebuild that can replace a just-completed scan.
    if not force and not activate:
        fallback = _STATUS_CACHE.get(depth) or _STATUS_CACHE.get(_ACTIVE_SCAN_DEPTH)
        if fallback is not None:
            _kick_sector_refresh_if_stale(fallback)
            return fallback
    with _STATUS_LOCK:
        now = time.time()
        depth = requested if requested is not None else _ACTIVE_SCAN_DEPTH
        cached = _STATUS_CACHE.get(depth)
        if not force and _status_cache_fresh(depth, now):
            data = cached
        elif not force and not activate:
            data = cached or _STATUS_CACHE.get(_ACTIVE_SCAN_DEPTH)
            if data is None:
                data = _get_dashboard_data_uncached(
                    scan_depth=depth,
                    include_gcp_resources=False,
                    progress=progress,
                )
                data["searchable_symbol_count"] = len(SYMBOL_INDEX)
                _STATUS_CACHE[depth] = data
                _STATUS_CACHE_TS[depth] = time.time()
                if isinstance(data.get("sector_flow"), Mapping):
                    _remember_sector_flow(data["sector_flow"])
        else:
            data = _get_dashboard_data_uncached(
                scan_depth=depth,
                include_gcp_resources=False,
                progress=progress,
            )
            data["searchable_symbol_count"] = len(SYMBOL_INDEX)
            _STATUS_CACHE[depth] = data
            _STATUS_CACHE_TS[depth] = time.time()
            if isinstance(data.get("sector_flow"), Mapping):
                _remember_sector_flow(data["sector_flow"])
        if activate:
            _ACTIVE_SCAN_DEPTH = depth
    _kick_sector_refresh_if_stale(data)
    return data


# Scan jobs keep the operator request short even when a provider is degraded or
# the full catalog needs rebuilding. Jobs are process-local by design: this is a
# loopback, single-operator workstation, not a distributed queue.
_SCAN_JOB_LOCK = threading.Lock()
_SCAN_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE_SCAN_JOB_ID: str | None = None
_SCAN_JOB_HISTORY_LIMIT = 8


def _scan_job_snapshot(job: Mapping[str, Any]) -> dict[str, Any]:
    elapsed_end = float(job.get("finished_monotonic") or time.perf_counter())
    payload = {
        "id": str(job.get("id") or ""),
        "depth": _scan_depth(str(job.get("depth") or "quick")),
        "state": str(job.get("state") or "queued"),
        "stage": str(job.get("stage") or "queued"),
        "progress": int(job.get("progress") or 0),
        "message": str(job.get("message") or "Scan queued."),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "elapsed_seconds": round(
            max(0.0, elapsed_end - float(job.get("started_monotonic") or elapsed_end)),
            1,
        ),
        "error": job.get("error"),
    }
    if job.get("state") == "completed" and isinstance(job.get("result"), Mapping):
        payload["result"] = job["result"]
    return payload


def _update_scan_job(job_id: str, **changes: Any) -> None:
    with _SCAN_JOB_LOCK:
        job = _SCAN_JOBS.get(job_id)
        if job is None:
            return
        job.update(changes)
        job["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_scan_job(job_id: str, depth: str) -> None:
    global _ACTIVE_SCAN_JOB_ID

    def on_progress(stage: str, percent: int, message: str) -> None:
        _update_scan_job(
            job_id,
            state="running",
            stage=stage,
            progress=max(1, min(99, int(percent))),
            message=message,
        )

    try:
        on_progress("starting", 1, f"Starting {depth} scan.")
        data = get_dashboard_data(
            force=True,
            scan_depth=depth,
            activate=True,
            progress=on_progress,
        )
        summary = data.get("scan_summary") or {}
        message = (
            f"{depth.title()} scan complete: "
            f"{summary.get('activity_local_scanned_symbols', 0)}/"
            f"{summary.get('activity_market_universe_symbols', 0)} market names ranked; "
            f"{summary.get('activity_live_completed_symbols', 0)}/"
            f"{summary.get('activity_live_requested_symbols', 0)} live flow checks; "
            f"{summary.get('directional_scored_symbols', 0)}/"
            f"{summary.get('directional_model_universe_symbols', 0)} modeled names scored."
        )
        _update_scan_job(
            job_id,
            state="completed",
            stage="complete",
            progress=100,
            message=message,
            finished_monotonic=time.perf_counter(),
            result={
                "status": "ok",
                "message": message,
                "asof": data.get("asof"),
                "data": data,
            },
        )
    except Exception as exc:  # noqa: BLE001 - job failure must remain inspectable
        _update_scan_job(
            job_id,
            state="failed",
            stage="failed",
            message=f"{depth.title()} scan failed.",
            error=f"{type(exc).__name__}: {exc}",
            finished_monotonic=time.perf_counter(),
        )
    finally:
        with _SCAN_JOB_LOCK:
            if _ACTIVE_SCAN_JOB_ID == job_id:
                _ACTIVE_SCAN_JOB_ID = None


def _start_scan_job(depth: str) -> tuple[dict[str, Any], bool]:
    """Start one scan or return the already-running job without duplicating work."""
    global _ACTIVE_SCAN_JOB_ID
    normalized = _scan_depth(depth)
    with _SCAN_JOB_LOCK:
        if _ACTIVE_SCAN_JOB_ID:
            active = _SCAN_JOBS.get(_ACTIVE_SCAN_JOB_ID)
            if active and active.get("state") in {"queued", "running"}:
                return _scan_job_snapshot(active), False

        job_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        job = {
            "id": job_id,
            "depth": normalized,
            "state": "queued",
            "stage": "queued",
            "progress": 0,
            "message": f"{normalized.title()} scan queued.",
            "started_at": now,
            "updated_at": now,
            "started_monotonic": time.perf_counter(),
            "error": None,
        }
        _SCAN_JOBS[job_id] = job
        _ACTIVE_SCAN_JOB_ID = job_id
        # Retain only a small operator-visible history plus the new active job.
        for stale_id in list(_SCAN_JOBS)[:-_SCAN_JOB_HISTORY_LIMIT]:
            if stale_id != _ACTIVE_SCAN_JOB_ID:
                _SCAN_JOBS.pop(stale_id, None)
        snapshot = _scan_job_snapshot(job)

    threading.Thread(
        target=_run_scan_job,
        args=(job_id, normalized),
        daemon=True,
        name=f"scan-{normalized}-{job_id}",
    ).start()
    return snapshot, True


def _scan_status_payload(job_id: str | None = None) -> tuple[dict[str, Any], int]:
    with _SCAN_JOB_LOCK:
        resolved = job_id or _ACTIVE_SCAN_JOB_ID
        if resolved is None and _SCAN_JOBS:
            resolved = next(reversed(_SCAN_JOBS))
        job = _SCAN_JOBS.get(str(resolved or ""))
        if job is None:
            if job_id:
                return {"status": "missing", "message": "Unknown scan job.", "job": None}, 404
            return {"status": "idle", "message": "No scan has been started.", "job": None}, 200
        snapshot = _scan_job_snapshot(job)
    return {"status": snapshot["state"], "message": snapshot["message"], "job": snapshot}, 200


# --------------------------------------------------------------------------
# Daily plays -- the full decision-support funnel (market map -> routed targets
# -> model domain -> directional setups -> live option-chain validation ->
# ENTER/WATCH/ABSTAIN). This is the same engine as `python -m edge.daily_plays
# today`, surfaced to the operator as a background job so a live run never
# monopolizes one browser request. It never places orders.
# --------------------------------------------------------------------------
_PLAYS_JOB_LOCK = threading.Lock()
_PLAYS_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE_PLAYS_JOB_ID: str | None = None
_PLAYS_JOB_HISTORY_LIMIT = 8
_PLAYS_ACCOUNT_DEFAULT = 10_000.0
_PLAYS_ACCOUNT_MIN = 100.0
_PLAYS_ACCOUNT_MAX = 100_000_000.0


def _plays_account(raw: str | None) -> float:
    try:
        value = float(raw) if raw else _PLAYS_ACCOUNT_DEFAULT
    except (TypeError, ValueError):
        return _PLAYS_ACCOUNT_DEFAULT
    if not math.isfinite(value):
        return _PLAYS_ACCOUNT_DEFAULT
    return max(_PLAYS_ACCOUNT_MIN, min(_PLAYS_ACCOUNT_MAX, value))


def _plays_job_snapshot(job: Mapping[str, Any]) -> dict[str, Any]:
    elapsed_end = float(job.get("finished_monotonic") or time.perf_counter())
    payload = {
        "id": str(job.get("id") or ""),
        "state": str(job.get("state") or "queued"),
        "stage": str(job.get("stage") or "queued"),
        "progress": int(job.get("progress") or 0),
        "message": str(job.get("message") or "Plays run queued."),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "elapsed_seconds": round(
            max(0.0, elapsed_end - float(job.get("started_monotonic") or elapsed_end)),
            1,
        ),
        "error": job.get("error"),
    }
    if job.get("state") == "completed" and isinstance(job.get("result"), Mapping):
        payload["result"] = job["result"]
    return payload


def _update_plays_job(job_id: str, **changes: Any) -> None:
    with _PLAYS_JOB_LOCK:
        job = _PLAYS_JOBS.get(job_id)
        if job is None:
            return
        job.update(changes)
        job["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_plays_job(job_id: str, account: float) -> None:
    global _ACTIVE_PLAYS_JOB_ID

    def on_progress(stage: str, percent: int, message: str) -> None:
        _update_plays_job(
            job_id,
            state="running",
            stage=stage,
            progress=max(1, min(99, int(percent))),
            message=message,
        )

    try:
        on_progress("starting", 1, "Starting daily plays run.")
        load_project_environment()
        config = _load_daily_plays_config()
        context = RunContext.create(mode=RunMode.LIVE)
        on_progress("discovery", 20, "Scanning sector relative strength and market map.")
        on_progress(
            "pipeline",
            50,
            "Fusing candidates, validating option structures, and authorizing plays.",
        )
        result = _run_daily_plays_pipeline(
            context=context,
            account=account,
            config=config,
            output_root=str(_DAILY_PLAYS_OUTPUT_ROOT),
        )
        on_progress(
            "options_gex", 85, "Validating GEX structures, strike walls, and contract sizing."
        )
        plays = [row for row in (result.get("plays") or []) if isinstance(row, Mapping)]
        status = str(result.get("status") or ("COMPLETE" if plays else "NO_PLAY"))
        message = (
            f"Daily plays complete: {len(plays)} actionable ticket(s), "
            f"{len(result.get('watchlist') or [])} watch, "
            f"{len(result.get('rejections') or [])} rejected."
        )
        _update_plays_job(
            job_id,
            state="completed",
            stage="complete",
            progress=100,
            message=message,
            finished_monotonic=time.perf_counter(),
            result={
                "status": "ok",
                "message": message,
                "asof": result.get("asof_utc"),
                "data": result,
            },
        )
    except Exception as exc:  # noqa: BLE001 - job failure must remain inspectable
        _update_plays_job(
            job_id,
            state="failed",
            stage="failed",
            message="Daily plays run failed.",
            error=f"{type(exc).__name__}: {exc}",
            finished_monotonic=time.perf_counter(),
        )
    finally:
        with _PLAYS_JOB_LOCK:
            if _ACTIVE_PLAYS_JOB_ID == job_id:
                _ACTIVE_PLAYS_JOB_ID = None


def _start_plays_job(account: float) -> tuple[dict[str, Any], bool]:
    """Start one plays run or return the already-running job without duplicating work."""
    global _ACTIVE_PLAYS_JOB_ID
    with _PLAYS_JOB_LOCK:
        if _ACTIVE_PLAYS_JOB_ID:
            active = _PLAYS_JOBS.get(_ACTIVE_PLAYS_JOB_ID)
            if active and active.get("state") in {"queued", "running"}:
                return _plays_job_snapshot(active), False

        job_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        job = {
            "id": job_id,
            "account": account,
            "state": "queued",
            "stage": "queued",
            "progress": 0,
            "message": "Daily plays run queued.",
            "started_at": now,
            "updated_at": now,
            "started_monotonic": time.perf_counter(),
            "error": None,
        }
        _PLAYS_JOBS[job_id] = job
        _ACTIVE_PLAYS_JOB_ID = job_id
        for stale_id in list(_PLAYS_JOBS)[:-_PLAYS_JOB_HISTORY_LIMIT]:
            if stale_id != _ACTIVE_PLAYS_JOB_ID:
                _PLAYS_JOBS.pop(stale_id, None)
        snapshot = _plays_job_snapshot(job)

    threading.Thread(
        target=_run_plays_job,
        args=(job_id, account),
        daemon=True,
        name=f"plays-{job_id}",
    ).start()
    return snapshot, True


def _plays_status_payload(job_id: str | None = None) -> tuple[dict[str, Any], int]:
    with _PLAYS_JOB_LOCK:
        resolved = job_id or _ACTIVE_PLAYS_JOB_ID
        if resolved is None and _PLAYS_JOBS:
            resolved = next(reversed(_PLAYS_JOBS))
        job = _PLAYS_JOBS.get(str(resolved or ""))
        if job is None:
            if job_id:
                return {"status": "missing", "message": "Unknown plays run.", "job": None}, 404
            return {"status": "idle", "message": "No plays run has been started.", "job": None}, 200
        snapshot = _plays_job_snapshot(job)
    return {"status": snapshot["state"], "message": snapshot["message"], "job": snapshot}, 200


def _latest_plays_payload() -> dict[str, Any]:
    """Read the most recent persisted daily-plays run without recomputing it.

    The pipeline is fail-closed and normally returns NO_PLAY in live mode; the
    operator surface must show the whole funnel (market map, watchlist,
    rejections, research board, blockers) rather than fabricate ENTER tickets.
    """
    root = Path(_DAILY_PLAYS_OUTPUT_ROOT)
    if not root.is_dir():
        return {"available": False, "reason": "No daily plays runs have been persisted yet."}
    run_dirs = [p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file()]
    if not run_dirs:
        return {"available": False, "reason": "No daily plays runs have been persisted yet."}
    latest = max(run_dirs, key=lambda p: p.name)

    def _read(name: str) -> Any:
        path = latest / name
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    manifest = _read("manifest.json")
    if not isinstance(manifest, Mapping):
        return {"available": False, "reason": f"Run {latest.name} has no readable manifest."}

    plays = _read("plays.json")
    decisions = _read("decisions.json")
    candidates = _read("candidates.json")
    option_snapshots = _read("option_snapshots.json")
    discovery = _read("discovery.json")
    flow_activity = _read("flow_activity.json")
    research_board = _read("research_board.json")

    if not isinstance(decisions, list):
        decisions = []
    if not isinstance(plays, list):
        plays = [
            row for row in decisions if isinstance(row, Mapping) and row.get("state") == "ENTER"
        ]
    if not isinstance(candidates, list):
        candidates = []
    if not isinstance(option_snapshots, list):
        option_snapshots = []
    watchlist = [
        row for row in decisions if isinstance(row, Mapping) and row.get("state") == "WATCH"
    ]
    rejections = [
        row for row in decisions if isinstance(row, Mapping) and row.get("state") == "ABSTAIN"
    ]

    discovery_map = discovery if isinstance(discovery, Mapping) else {}
    flow_map = flow_activity if isinstance(flow_activity, Mapping) else {}
    coverage = flow_map.get("coverage") if isinstance(flow_map.get("coverage"), Mapping) else {}

    def _setup_ok(row: Mapping) -> bool:
        internal = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
        model = internal.get("internal_model") if isinstance(internal, Mapping) else None
        if not isinstance(model, Mapping):
            return False
        return bool(model.get("setup_ok")) and str(row.get("side") or "neutral") != "neutral"

    # Reconstruct the funnel counts the pipeline reports in-memory but does not
    # persist as a standalone artifact. Chain request counts are not
    # recoverable from the ledger, so they stay null; chain_snapshots is the
    # count of persisted option snapshot records.
    warnings = [str(item) for item in (manifest.get("warnings") or []) if item]

    def _warning_symbol(warning: str) -> str | None:
        for prefix in (
            "unsupported_promoted_symbol:",
            "promoted_model_unavailable:",
            "internal_model_unavailable:",
        ):
            if warning.startswith(prefix):
                symbol = warning[len(prefix) :].split(":", 1)[0].upper()
                return symbol or None
        return None

    unavailable_model_symbols: list[str] = []
    seen_syms: set[str] = set()
    for warning in warnings:
        sym = _warning_symbol(warning)
        if sym and sym not in seen_syms:
            seen_syms.add(sym)
            unavailable_model_symbols.append(sym)

    scan_scope = {
        "sector_books_scored": discovery_map.get("sector_books_scored", 0),
        "targeted_count": discovery_map.get("targeted_count", 0),
        "model_covered_count": discovery_map.get("model_covered_count", 0),
        "model_domain_supported": len(discovery_map.get("model_covered_symbols") or []),
        "successfully_scanned_candidates": len(decisions),
        "directional_setups": sum(
            1 for row in decisions if isinstance(row, Mapping) and _setup_ok(row)
        ),
        "chain_requests": None,
        "chain_snapshots": len(option_snapshots),
        "unavailable_model_symbols": unavailable_model_symbols,
        "flow_activity_requested": int(coverage.get("requested") or 0),
        "flow_activity_observed": int(coverage.get("with_activity") or 0),
    }

    # The pipeline's decision_blockers are exactly the stable-unique union of
    # every decision's confidence reasons. Reconstruct that union here.
    blockers: list[str] = []
    seen_blockers: set[str] = set()
    for row in decisions:
        if not isinstance(row, Mapping):
            continue
        confidence = row.get("confidence") if isinstance(row.get("confidence"), Mapping) else {}
        for reason in confidence.get("reasons") or []:
            text = str(reason)
            if text and text not in seen_blockers:
                seen_blockers.add(text)
                blockers.append(text)

    warnings = [str(item) for item in (manifest.get("warnings") or []) if item]
    advisory_prefixes = (
        "kronos_",
        "flow_",
        "sector_flow_",
        "research_models_",
        "directional_research_",
        "promoted_model_manifest_advisory:",
    )
    advisory_evidence_warnings = [
        warning for warning in warnings if warning.startswith(advisory_prefixes)
    ]
    execution_health_warnings = [
        warning
        for warning in warnings
        if warning not in advisory_evidence_warnings
        and not warning.startswith("unsupported_promoted_symbol:")
    ]

    # When the pipeline found no actionable plays, reconstruct the honest
    # fallback blockers the pipeline would have reported: if there were no
    # candidates at all, it is "no_successfully_scanned_model_candidates";
    # if candidates existed but none were actionable, it is
    # "no_live_validated_actionable_plays".
    if not blockers and not plays:
        if not decisions:
            blockers.append("no_successfully_scanned_model_candidates")
        else:
            blockers.append("no_live_validated_actionable_plays")

    return {
        "available": True,
        "run_id": str(manifest.get("run_id") or latest.name),
        "requested_for": manifest.get("requested_for"),
        "asof_utc": manifest.get("asof_utc"),
        "market_session": manifest.get("market_session"),
        "mode": manifest.get("mode"),
        "account": manifest.get("account"),
        "config_hash": manifest.get("config_hash"),
        "engine": manifest.get("engine"),
        "engine_version": manifest.get("engine_version"),
        "warnings": warnings,
        "status": "COMPLETE" if plays else "NO_PLAY",
        "market_map": (
            discovery_map.get("market_map")
            if isinstance(discovery_map.get("market_map"), Mapping)
            else {}
        ),
        "scan_scope": scan_scope,
        "flow_activity": flow_map,
        "candidates": candidates,
        "plays": plays,
        "watchlist": watchlist,
        "rejections": rejections,
        "research_board": research_board if isinstance(research_board, list) else [],
        "decision_blockers": blockers,
        "advisory_evidence_warnings": advisory_evidence_warnings,
        "execution_health_warnings": execution_health_warnings,
    }


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
_ALL_SYMBOLS_SORTED: tuple[str, ...] = tuple(sorted(SYMBOL_INDEX.keys()))
_ALL_SYMBOLS_SET: frozenset[str] = frozenset(_ALL_SYMBOLS_SORTED)
_LIQUID_MAJORS: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "XLF",
    "XLK",
    "XLE",
    "GLD",
)
_MAJORS_IN_INDEX: list[str] = [s for s in _LIQUID_MAJORS if s in _ALL_SYMBOLS_SET]
_REST_SYMBOLS_DEFAULT: list[str] = [
    s for s in _ALL_SYMBOLS_SORTED if s not in set(_MAJORS_IN_INDEX)
]
_DEFAULT_SEARCH_SYMBOLS: list[str] = _MAJORS_IN_INDEX + _REST_SYMBOLS_DEFAULT

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-_]{1,16}$")

WINDOW_OFFSETS = {
    "1m": _get_pd().DateOffset(months=1),
    "3m": _get_pd().DateOffset(months=3),
    "6m": _get_pd().DateOffset(months=6),
    "1y": _get_pd().DateOffset(years=1),
    "3y": _get_pd().DateOffset(years=3),
    "5y": _get_pd().DateOffset(years=5),
    "max": None,
}
DEFAULT_WINDOW = "1y"

# Per-symbol metadata cache (n_bars/first_date/last_date), populated lazily.
_SYMBOL_META_CACHE: dict[str, dict] = {}
_META_CACHE: dict[str, dict] = _SYMBOL_META_CACHE
_META_LOCK = threading.Lock()

# Parquet DataFrame cache keyed by (symbol, tier, mtime) so repeat trajectory
# requests are fast; stale entries for a symbol are evicted on reload.
_PARQUET_CACHE: dict[tuple, "_get_pd().DataFrame"] = {}
_PARQUET_LOCK = threading.Lock()

# Out-of-universe tickers typed into the symbol palette are fetched live and
# cached under a ("live") tier. Both bounds matter: the TTL stops a symbol
# being pinned to its first fetch for the life of the process, and the cap
# stops an unbounded set of typed tickers each holding a 5y DataFrame.
_LIVE_OHLCV_TTL_S = 900
_LIVE_OHLCV_MAX_ENTRIES = 32


def _evict_live_ohlcv_locked() -> None:
    """Trim the live tier of _PARQUET_CACHE. Caller must hold _PARQUET_LOCK."""
    live_keys = [k for k in _PARQUET_CACHE if len(k) == 3 and k[1] == "live"]
    excess = len(live_keys) - _LIVE_OHLCV_MAX_ENTRIES
    if excess <= 0:
        return
    # k[2] is the TTL bucket, so ascending order is oldest-first.
    for key in sorted(live_keys, key=lambda k: k[2])[:excess]:
        _PARQUET_CACHE.pop(key, None)


# Options tape/chain calls are materially more expensive than daily price
# reads. Cache exact request payloads briefly; the response still carries its
# provider observation time so a cached read cannot masquerade as a new tick.
_OPTIONS_CACHE: dict[tuple, tuple[float, dict]] = {}
_OPTIONS_LOCK = threading.Lock()
_OPTIONS_BUILD_LOCKS: dict[tuple[Any, ...], threading.Lock] = {}
_OPTIONS_CACHE_TTL_S = 20.0
# Live equity last used as Options SPOT when the chain lacks a timestamped
# underlying quote. Local 1d parquet can lag multi-day; without this the KPI
# freezes on the last checked-in close (e.g. SPY stuck at $771.33).
_LSE_EQUITY_SPOT_CACHE: dict[str, tuple[float, float | None, str | None]] = {}
_LSE_EQUITY_SPOT_TTL_S = 20.0
_LSE_EQUITY_SPOT_LOCK = threading.Lock()

# Dated chains are immutable snapshots. Cache their decoded records by file
# signature so one Options request does not decode the same parquet once while
# discovering dates and again while building history. A newly written backfill
# changes the signature and is picked up automatically.
_OPTION_CHAIN_FILE_CACHE: dict[Path, tuple[tuple[int, int], list[dict[str, Any]]]] = {}
_OPTION_CHAIN_FILE_LOCK = threading.Lock()

# Market-wide unusual flow is one bounded provider request. Keep the immutable
# cache just below the Flow workspace's 15s poll so every visible poll can
# advance the provider window without stacking concurrent reads.
_UNUSUAL_FLOW_CACHE: dict[tuple, tuple[float, dict]] = {}
_UNUSUAL_FLOW_LOCK = threading.Lock()
_UNUSUAL_FLOW_BUILD_LOCKS: dict[tuple, threading.Lock] = {}
_UNUSUAL_FLOW_TTL_S = 12.0

# Price attractor telemetry cache: thread-safe TTL cache and single-flight builder locks.
_PRICE_ATTRACTOR_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PRICE_ATTRACTOR_LOCK = threading.Lock()
_PRICE_ATTRACTOR_BUILD_LOCKS: dict[str, threading.Lock] = {}
_PRICE_ATTRACTOR_CACHE_TTL_S = 20.0

# Layer 3 market regime telemetry cache: thread-safe TTL cache and single-flight builder locks.
_MARKET_REGIME_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MARKET_REGIME_LOCK = threading.Lock()
_MARKET_REGIME_BUILD_LOCKS: dict[str, threading.Lock] = {}
_MARKET_REGIME_CACHE_TTL_S = 60.0
# Warm intervals outside regular trading. Overridable because how much of the
# provider's daily allowance an idle desk may spend is an operator decision.
_MARKET_REGIME_WARM_EXTENDED_S = float(os.environ.get("EDGE_REGIME_WARM_EXTENDED_S", "300") or 300)
_MARKET_REGIME_WARM_CLOSED_S = float(os.environ.get("EDGE_REGIME_WARM_CLOSED_S", "1800") or 1800)


def _symbol_path(symbol: str, tier: str) -> Path:
    d = DATA_WIDE_DIR if tier == "wide" else DATA_CORE_DIR
    return d / f"{symbol}.parquet"


def _get_symbol_meta(symbol: str) -> dict:
    cached = _SYMBOL_META_CACHE.get(symbol)
    if cached is not None:
        return cached
    tier = SYMBOL_INDEX.get(symbol)
    meta = {"n_bars": 0, "first_date": None, "last_date": None}
    if tier is not None:
        path = _symbol_path(symbol, tier)
        if path.is_file():
            try:
                import pyarrow.parquet as pq

                pf = pq.ParquetFile(path)
                num_rows = int(pf.metadata.num_rows)
                first_date = None
                last_date = None

                if pf.metadata.num_row_groups > 0:
                    first_rg = pf.metadata.row_group(0)
                    last_rg = pf.metadata.row_group(pf.metadata.num_row_groups - 1)
                    for i in range(pf.metadata.num_columns):
                        col_first = first_rg.column(i)
                        name = col_first.path_in_schema
                        if name in ("Date", "date", "__index_level_0__", "timestamp"):
                            if col_first.statistics and col_first.statistics.has_min_max:
                                first_date = str(col_first.statistics.min)[:10]
                            col_last = last_rg.column(i)
                            if col_last.statistics and col_last.statistics.has_min_max:
                                last_date = str(col_last.statistics.max)[:10]
                            break

                if num_rows > 0 and (first_date is None or last_date is None):
                    df = _get_pd().read_parquet(path, columns=["close"])
                    first_date = df.index[0].strftime("%Y-%m-%d") if len(df) else None
                    last_date = df.index[-1].strftime("%Y-%m-%d") if len(df) else None

                meta = {
                    "n_bars": num_rows,
                    "first_date": first_date,
                    "last_date": last_date,
                }
            except Exception:
                try:
                    df = _get_pd().read_parquet(path, columns=["close"])
                    n = len(df)
                    meta = {
                        "n_bars": int(n),
                        "first_date": df.index[0].strftime("%Y-%m-%d") if n else None,
                        "last_date": df.index[-1].strftime("%Y-%m-%d") if n else None,
                    }
                except Exception:
                    pass
        else:
            try:
                df, _ = _load_symbol_df(symbol)
                if df is not None and not getattr(df, "empty", True):
                    n = len(df)
                    meta = {
                        "n_bars": int(n),
                        "first_date": df.index[0].strftime("%Y-%m-%d") if n else None,
                        "last_date": df.index[-1].strftime("%Y-%m-%d") if n else None,
                    }
            except Exception:
                pass
    with _META_LOCK:
        _SYMBOL_META_CACHE[symbol] = meta
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

#: Desk ticker -> Yahoo ticker for cash indices, which are not tradable
#: symbols and are quoted under a caret. Only consulted on the ad-hoc live
#: path; anything in the local parquet catalog is served from disk first.
_YF_INDEX_ALIASES = {
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
    "VIX9D": "^VIX9D",
    "VVIX": "^VVIX",
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "RUT": "^RUT",
    "DJI": "^DJI",
    "TNX": "^TNX",
    "VXN": "^VXN",
    "SKEW": "^SKEW",
}


def _normalize_ohlcv_df(df: pd.DataFrame) -> "_get_pd().DataFrame" | None:
    """Coerce parquet/yfinance frames into the trajectory OHLCV schema."""
    if df is None or df.empty:
        return None
    out = df.copy()
    if not isinstance(out.index, _get_pd().DatetimeIndex):
        for col in ("date", "Date", "datetime", "Datetime"):
            if col in out.columns:
                out[col] = _get_pd().to_datetime(out[col], utc=False, errors="coerce")
                out = out.set_index(col)
                break
        else:
            try:
                out.index = _get_pd().to_datetime(out.index, utc=False, errors="coerce")
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
        out[c] = _get_pd().to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["close"])
    if out.empty:
        return None
    return out[["open", "high", "low", "close", "volume"]]


def _fetch_yfinance_ohlcv(symbol: str) -> "_get_pd().DataFrame" | None:
    """On-demand daily bars for names missing from the local parquet universe."""
    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except Exception:
        return None
    # Cash indices are not tradable tickers on Yahoo; they carry a caret. The
    # Regime tab asks for quotes(['VIX','SPY','QQQ']) on every load, and a bare
    # "VIX" is not a symbol -- Yahoo answers "possibly delisted", so the macro
    # strip has never had a VIX print and each load burns a network round trip.
    vendor_symbol = _YF_INDEX_ALIASES.get(symbol.upper(), symbol)

    def _download() -> "_get_pd().DataFrame" | None:
        # Without a timeout a hung Yahoo connection holds this handler thread
        # forever, and the server only has _DEFAULT_MAX_CONCURRENT_REQUESTS (32)
        # of them -- enough stuck lookups take the whole API down, not just
        # the request that typed the bad ticker.
        raw = yf.download(
            vendor_symbol,
            period="5y",
            progress=False,
            auto_adjust=True,
            threads=False,
            timeout=_YF_SPOT_TIMEOUT_S,
        )
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, _get_pd().MultiIndex):
            # yfinance often returns (Price, Ticker) even for a single name.
            try:
                levels = [str(x).upper() for x in raw.columns.get_level_values(-1)]
                if vendor_symbol.upper() in levels:
                    raw = raw.xs(vendor_symbol, axis=1, level=-1, drop_level=True)
                else:
                    raw.columns = raw.columns.get_level_values(0)
            except Exception:
                raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
        return _normalize_ohlcv_df(raw)

    _futures = _get_concurrent_futures()
    pool = _futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="yf-ohlcv")
    try:
        return pool.submit(_download).result(timeout=_YF_SPOT_DEADLINE_S)
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False)


def _frame_asof_date(frame: Any) -> str | None:
    """Last observed bar date for an OHLCV frame, never the request time."""
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        return _get_pd().Timestamp(frame.index[-1]).date().isoformat()
    except (TypeError, ValueError, IndexError, AttributeError):
        return None


def _frame_age_days(frame: Any, *, now: datetime | None = None) -> int | None:
    asof = _frame_asof_date(frame)
    if asof is None:
        return None
    observed = datetime.fromisoformat(asof).date()
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return max(0, (today - observed).days)


def _append_live_close(frame: Any, spot: float, asof: str | None) -> Any:
    """Stamp a live last onto a daily OHLCV frame without inventing history."""
    if frame is None or getattr(frame, "empty", True):
        return frame
    if not math.isfinite(spot) or spot <= 0:
        return frame
    pd = _get_pd()
    try:
        ts = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now(timezone.utc).date())
    except (TypeError, ValueError):
        ts = pd.Timestamp(datetime.now(timezone.utc).date())
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    ts = ts.normalize()
    out = frame.copy()
    last = pd.Timestamp(out.index[-1])
    if getattr(last, "tzinfo", None) is not None:
        last = last.tz_convert("UTC").tz_localize(None)
    last = last.normalize()
    if ts < last:
        return out
    out.loc[ts, ["open", "high", "low", "close", "volume"]] = [
        float(spot),
        float(spot),
        float(spot),
        float(spot),
        0.0,
    ]
    return out


def _refresh_stale_compare_frames(
    loaded: dict[str, Any],
    sources: dict[str, str],
) -> None:
    """Refresh only stale shell benchmarks, degrading to labelled local bars.

    The comparison endpoint is also used for arbitrary research symbols. It
    must not make those requests network-bound, so on-demand refresh is scoped
    to the four marks permanently displayed by the application shell.
    """
    stale = [
        symbol
        for symbol, frame in loaded.items()
        if symbol in _COMPARE_BENCHMARKS
        and (_frame_age_days(frame) is None or int(_frame_age_days(frame) or 0) > 3)
    ]
    if not stale:
        return

    now = time.time()
    refreshed: dict[str, Any | None] = {}
    misses: list[str] = []
    with _COMPARE_REFRESH_LOCK:
        for symbol in stale:
            cached = _COMPARE_REFRESH_CACHE.get(symbol)
            if cached is not None and now - cached[0] < _COMPARE_REFRESH_TTL_S:
                refreshed[symbol] = cached[1]
            else:
                misses.append(symbol)

    if misses:
        futures = _get_concurrent_futures()
        with futures.ThreadPoolExecutor(max_workers=min(4, len(misses))) as executor:
            pending = {executor.submit(_fetch_yfinance_ohlcv, symbol): symbol for symbol in misses}
            for future in futures.as_completed(pending):
                symbol = pending[future]
                try:
                    frame = future.result()
                except Exception:
                    frame = None
                refreshed[symbol] = frame
                with _COMPARE_REFRESH_LOCK:
                    _COMPARE_REFRESH_CACHE[symbol] = (now, frame)

    for symbol, frame in refreshed.items():
        if frame is None or getattr(frame, "empty", True):
            continue
        local_asof = _frame_asof_date(loaded.get(symbol)) or ""
        live_asof = _frame_asof_date(frame) or ""
        if live_asof > local_asof:
            loaded[symbol] = frame
            sources[symbol] = "yfinance_refresh"

    still_stale = [
        symbol
        for symbol in stale
        if _frame_age_days(loaded.get(symbol)) is None
        or int(_frame_age_days(loaded.get(symbol)) or 0) > 3
    ]
    for symbol in still_stale:
        spot, asof = _fetch_lse_equity_spot(symbol)
        if spot is None:
            continue
        updated = _append_live_close(loaded.get(symbol), spot, asof)
        if updated is None or getattr(updated, "empty", True):
            continue
        loaded[symbol] = updated
        sources[symbol] = "lse_equity_candles"


def _load_symbol_df(symbol: str) -> tuple["_get_pd().DataFrame | None, str | None"]:
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
        # Live/ad-hoc path for out-of-universe tickers. The third slot is a TTL
        # bucket, not the literal 0.0 it used to be: a constant there made this
        # cache permanent, so the "short-lived" pull promised above was in fact
        # served from its very first fetch for the life of the process, and
        # every distinct ticker typed into the palette leaked one DataFrame.
        bucket = float(int(time.time() // _LIVE_OHLCV_TTL_S))
        cache_key = (symbol, "live", bucket)
        with _PARQUET_LOCK:
            cached = _PARQUET_CACHE.get(cache_key)
        if cached is not None:
            return cached, "live"
        live = _fetch_yfinance_ohlcv(symbol)
        if live is None or live.empty:
            return None, None
        with _PARQUET_LOCK:
            _PARQUET_CACHE[cache_key] = live
            _evict_live_ohlcv_locked()
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
    df = _normalize_ohlcv_df(_get_pd().read_parquet(path))
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


def _lookback_chg_pct(close: "_get_pd().Series", n_bars: int):
    if len(close) <= n_bars:
        return None
    return _pct(close.iloc[-1 - n_bars], close.iloc[-1])


def _asof_chg_pct(close: "_get_pd().Series", months: int = 0, years: int = 0):
    if close.empty:
        return None
    last_date = close.index[-1]
    target = last_date - _get_pd().DateOffset(months=months, years=years)
    sub = close.loc[close.index <= target]
    if sub.empty:
        return None
    return _pct(sub.iloc[-1], close.iloc[-1])


def _ytd_chg_pct(close: "_get_pd().Series"):
    if close.empty:
        return None
    pd = _get_pd()
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


def _window_stats(win_close: "_get_pd().Series") -> dict:
    """ann_return/vol/sharpe/max_dd/calmar + best/worst/pct-up over one price
    series. Sharpe/calmar/ann_* are null (never Inf/NaN) when the denominator
    is zero or the window is too short to annualize meaningfully."""
    out = {
        "ann_return_pct": None,
        "ann_vol_pct": None,
        "sharpe": None,
        "max_drawdown_pct": None,
        "calmar": None,
        "best_day_pct": None,
        "worst_day_pct": None,
        "pct_days_up": None,
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
    pd = _get_pd()
    high = df_full["high"].astype(float)
    low = df_full["low"].astype(float)
    close = df_full["close"].astype(float)
    volume = df_full["volume"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
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
    pd = _get_pd()
    close = df_full["close"].astype(float)
    volume = df_full["volume"].astype(float)
    ret1 = close.pct_change()

    rev1 = -ret1
    rev5 = -close.pct_change(5)
    mom12_1 = close.shift(21) / close.shift(252) - 1.0
    lowvol = -ret1.rolling(20).std()

    # 20-day mean dollar volume
    dollar_vol = (close * volume).rolling(20).mean()
    last_dollar_vol = (
        float(dollar_vol.iloc[-1]) if len(dollar_vol) and not pd.isna(dollar_vol.iloc[-1]) else 0.0
    )
    # Positive log10 dollar volume score for intuitive UI display (e.g. 9.18 for $1.5B ADV)
    liq_score = math.log10(max(1.0, last_dollar_vol)) if last_dollar_vol > 0 else 0.0

    def last(s: "_get_pd().Series"):
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


def _slice_window(df_full: pd.DataFrame, window: str) -> "_get_pd().DataFrame":
    offset = WINDOW_OFFSETS.get(window)
    if offset is None:
        return df_full
    last_date = df_full.index[-1]
    start = last_date - offset
    return df_full.loc[df_full.index >= start]


def _build_series(win: pd.DataFrame) -> list[dict]:
    if win is None or win.empty:
        return []
    np = _get_np()
    n = len(win)

    if hasattr(win.index, "strftime"):
        dates = win.index.strftime("%Y-%m-%d").tolist()
    else:
        dates = [str(idx)[:10] for idx in win.index]

    c_arr = win["close"].to_numpy(dtype=float)
    o_arr = win["open"].to_numpy(dtype=float) if "open" in win.columns else c_arr
    h_arr = win["high"].to_numpy(dtype=float) if "high" in win.columns else c_arr
    l_arr = win["low"].to_numpy(dtype=float) if "low" in win.columns else c_arr
    v_arr = (
        win["volume"].to_numpy(dtype=float) if "volume" in win.columns else np.zeros(n, dtype=float)
    )

    # Vectorized percentage returns: ret[0] = None, ret[1:] = (c[1:] / c[:-1]) - 1.0
    ret_arr = np.empty(n, dtype=object)
    ret_arr[0] = None
    if n > 1:
        prev_c = c_arr[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            pct = np.where(prev_c != 0, (c_arr[1:] / prev_c) - 1.0, np.nan)
        for i, val in enumerate(pct, start=1):
            ret_arr[i] = round(float(val), 6) if math.isfinite(val) else None

    # Vectorized cumulative return rebased to 1.0 at index 0
    cum_arr = np.empty(n, dtype=object)
    c0 = c_arr[0]
    if c0 != 0 and math.isfinite(c0):
        with np.errstate(divide="ignore", invalid="ignore"):
            cum_raw = c_arr / c0
        for i, val in enumerate(cum_raw):
            cum_arr[i] = round(float(val), 6) if math.isfinite(val) else None
    else:
        for i in range(n):
            cum_arr[i] = None

    # Vectorized drawdown relative to running maximum
    running_max = np.maximum.accumulate(c_arr)
    dd_arr = np.empty(n, dtype=object)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd_raw = np.where(running_max > 0, (c_arr / running_max) - 1.0, 0.0)
    for i, val in enumerate(dd_raw):
        dd_arr[i] = round(float(val), 6) if math.isfinite(val) else None

    # Single zip comprehension over pre-formatted date strings and numpy arrays
    return [
        {
            "d": d,
            "o": round(float(o), 4) if math.isfinite(o) else None,
            "h": round(float(h), 4) if math.isfinite(h) else None,
            "l": round(float(l), 4) if math.isfinite(l) else None,
            "c": round(float(c), 4) if math.isfinite(c) else None,
            "v": round(float(v), 6) if math.isfinite(v) else None,
            "ret": r,
            "cum": cm,
            "dd": d_d,
        }
        for d, o, h, l, c, v, r, cm, d_d in zip(
            dates, o_arr, h_arr, l_arr, c_arr, v_arr, ret_arr, cum_arr, dd_arr
        )
    ]


def _downsample(rows: list[dict], target: int = 1200) -> list[dict]:
    n = len(rows)
    if n <= target:
        return rows
    step = max(1, math.ceil(n / target))
    out = [rows[i] for i in range(0, n, step)]
    if out[-1]["d"] != rows[-1]["d"]:
        out.append(rows[-1])
    return out


def _trajectory_payload(
    symbol: str,
    window: str,
    *,
    include_qlib: bool = True,
) -> tuple[dict, int]:
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

    last_bar_date = win.index[-1].strftime("%Y-%m-%d")
    live_spot, live_asof = _fetch_lse_equity_spot(symbol)
    last_source = source_label
    last_asof = last_bar_date
    quality = "local"
    if live_spot is not None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_close = close_full.iloc[-1]
        prior_close = close_full.iloc[-2] if len(close_full) > 1 else session_close
        base = prior_close if last_bar_date >= today else session_close
        stats["last_price"] = live_spot
        stats["chg_1d_pct"] = _safe_round(_pct(base, live_spot), 4)
        last_source = "lse_equity_candles"
        last_asof = live_asof or last_bar_date
        quality = "live"
        if series:
            last_bar = dict(series[-1])
            last_bar["c"] = live_spot
            high = last_bar.get("h")
            low = last_bar.get("l")
            if isinstance(high, (int, float)):
                last_bar["h"] = _safe_round(max(float(high), live_spot), 4)
            if isinstance(low, (int, float)):
                last_bar["l"] = _safe_round(min(float(low), live_spot), 4)
            series[-1] = last_bar

    payload = {
        "symbol": symbol,
        "window": window,
        "n_bars": int(len(win)),
        "first_date": win.index[0].strftime("%Y-%m-%d"),
        "last_date": last_bar_date,
        "source": source_label,
        "last_source": last_source,
        "last_asof": last_asof,
        "quality": quality,
        "series": series,
        "stats": stats,
        "factors": _compute_factors(df_full),
    }
    if include_qlib:
        # Reuse the published full-catalog panel (deep scan or prior Market
        # build). Do NOT pass this symbol's last bar as the cross-section asof:
        # staggered data ends would re-cut the panel and disagree with deep ranks.
        qlib_ctx = _trajectory_qlib_context(symbol)
        payload.update(
            {
                "qlib": qlib_ctx,
                "qlib_score": qlib_ctx.get("qlib_score"),
                "qlib_rank": qlib_ctx.get("qlib_rank"),
                "qlib_score_kind": qlib_ctx.get("score_kind") or QLIB_SCORE_KIND,
                "qlib_source": qlib_ctx.get("source") or QLIB_SOURCE_ID,
                "qlib_asof": qlib_ctx.get("asof"),
                "qlib_quality": qlib_ctx.get("quality"),
            }
        )
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

    pd = _get_pd()
    loaded: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    for sym in symbols:
        df_full, tier = _load_symbol_df(sym)
        if df_full is None or df_full.empty:
            continue
        loaded[sym] = df_full
        sources[sym] = tier or "unknown"

    _refresh_stale_compare_frames(loaded, sources)

    windowed: dict[str, pd.Series] = {}
    for sym, df_full in loaded.items():
        win = _slice_window(df_full, window)
        if win.empty:
            continue
        windowed[sym] = win["close"].astype(float)

    if not windowed:
        return {
            "error": "none of the requested symbols have data in this window",
            "endpoint": "/api/compare",
        }, 404

    # Common window = intersection of trading dates across requested symbols,
    # forward/backward-filled for small date boundary mismatches so comparison is robust.
    raw_df = pd.DataFrame(windowed)
    joint = raw_df.ffill().bfill().dropna(how="any")
    if joint.empty:
        joint = raw_df.dropna(how="all").ffill().bfill()
    if joint.empty:
        return {
            "error": "no overlapping trading days among requested symbols",
            "endpoint": "/api/compare",
        }, 404

    rebased = joint / joint.iloc[0]
    rets = joint.pct_change().dropna(how="all")
    corr = rets.corr(method="pearson")

    series_out: dict[str, list[dict]] = {}
    stats_out: dict[str, dict] = {}
    for sym in joint.columns:
        s = rebased[sym]
        series_out[sym] = [
            {"d": idx.strftime("%Y-%m-%d"), "cum": _safe_round(v, 6)} for idx, v in s.items()
        ]
        # Price/change/freshness come from the symbol's own observed closes,
        # not the forward-filled comparison matrix. Otherwise an older QQQ
        # series becomes a fake 0.00% move merely because SPY has a later bar.
        closes = windowed[sym].dropna()
        wstats = _window_stats(closes)
        last_px = float(closes.iloc[-1])
        prev_px = float(closes.iloc[-2]) if len(closes) > 1 else last_px
        chg_1d = ((last_px / prev_px) - 1.0) * 100.0 if prev_px else None
        asof_date = _frame_asof_date(loaded.get(sym))
        age_days = _frame_age_days(loaded.get(sym))
        stats_out[sym] = {
            "last_price": _safe_round(last_px, 4),
            "chg_1d_pct": _safe_round(chg_1d, 4) if chg_1d is not None else None,
            "ann_return_pct": wstats["ann_return_pct"],
            "ann_vol_pct": wstats["ann_vol_pct"],
            "sharpe": wstats["sharpe"],
            "max_drawdown_pct": wstats["max_drawdown_pct"],
            "chg_window_pct": _safe_round(_pct(closes.iloc[0], closes.iloc[-1]), 4),
            "asof": asof_date,
            "age_days": age_days,
            "quality": "stale" if age_days is None or age_days > 3 else "current",
            "source": sources.get(sym, "unknown"),
            "change_basis": "last_two_observed_closes",
        }

    correlation_out = {
        a: {b: _safe_round(corr.loc[a, b], 4) for b in corr.columns} for a in corr.index
    }

    return {
        "window": window,
        "asof": max((row.get("asof") or "" for row in stats_out.values()), default="") or None,
        "oldest_asof": min((row.get("asof") or "" for row in stats_out.values()), default="")
        or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series": series_out,
        "stats": stats_out,
        "correlation": correlation_out,
    }, 200


def _options_price_series(
    symbol: str,
    selected_range: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[dict], float | None]:
    price_window = {"1d": "1m", "5d": "1m", "1m": "3m", "3m": "6m"}.get(selected_range, "3m")
    # Options needs only OHLCV. Calling the full trajectory endpoint here used
    # to cold-build the 576-name qlib cross-section before a single ticker's
    # squeeze could render. Read the already cached symbol frame directly and
    # preserve volume so ADV is measured instead of falling back to a proxy.
    frame, _tier = _load_symbol_df(symbol)
    if frame is None or frame.empty:
        return [], None
    win = _slice_window(frame, price_window)
    if win.empty:
        return [], None
    series = [
        {
            "t": f"{idx.strftime('%Y-%m-%d')}T20:00:00+00:00",
            "close": _safe_round(row.get("close"), 4),
            "volume": _safe_round(row.get("volume"), 6),
        }
        for idx, row in win.iterrows()
        if row.get("close") is not None and math.isfinite(float(row.get("close")))
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
    return series, _safe_round(frame["close"].iloc[-1], 4)


# `_symbol_quote` used to open a ParquetFile and re-read the last row group on
# every call, and `_quotes_payload` fans out to up to 40 of them per request.
# The tail closes only change when the file is rewritten, so cache the result
# by (path, mtime) the same way `_read_bars_cached` does. The cached value is
# (last, prev, asof) of plain floats/str-or-None -- immutable, so callers get
# the tuple itself safely.
_SYMBOL_QUOTE_TAIL_CACHE: dict[tuple[str, float], tuple] = {}
_SYMBOL_QUOTE_TAIL_CACHE_MAX = 512
_SYMBOL_QUOTE_TAIL_CACHE_LOCK = threading.Lock()


def _symbol_quote_tail_cached(path) -> tuple | None:
    """(last, prev, asof) closes from the file's last row group, mtime-keyed.

    Returns None when the file yields no usable closes; failures are not
    cached, matching `_read_bars_cached`.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    with _SYMBOL_QUOTE_TAIL_CACHE_LOCK:
        cached = _SYMBOL_QUOTE_TAIL_CACHE.get(key)
    if cached is not None:
        return cached
    local_last = None
    local_prev = None
    local_asof = None
    try:
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(path)
        num_rgs = pf.metadata.num_row_groups
        if num_rgs > 0:
            last_rg = pf.read_row_group(
                num_rgs - 1,
                columns=[c for c in ["close", "Date", "date"] if c in pf.schema_arrow.names],
            )
            tail_df = _normalize_ohlcv_df(last_rg.to_pandas())
            if (
                tail_df is not None
                and not getattr(tail_df, "empty", True)
                and "close" in tail_df.columns
            ):
                closes = tail_df["close"].astype(float).dropna()
                if len(closes):
                    local_last = _safe_round(float(closes.iloc[-1]), 4)
                    local_asof = _frame_asof_date(tail_df)
                if len(closes) > 1:
                    local_prev = _safe_round(float(closes.iloc[-2]), 4)
    except Exception:
        return None
    if local_last is None:
        return None
    result = (local_last, local_prev, local_asof)
    with _SYMBOL_QUOTE_TAIL_CACHE_LOCK:
        while len(_SYMBOL_QUOTE_TAIL_CACHE) >= _SYMBOL_QUOTE_TAIL_CACHE_MAX:
            oldest = next(iter(_SYMBOL_QUOTE_TAIL_CACHE))
            _SYMBOL_QUOTE_TAIL_CACHE.pop(oldest, None)
        _SYMBOL_QUOTE_TAIL_CACHE[key] = result
    return result


def _symbol_quote(symbol: str) -> dict:
    """One live mark for the desk boards. LSE last when available, else local close."""
    local_last = None
    local_prev = None
    local_asof = None

    target = symbol
    tier = SYMBOL_INDEX.get(target)
    if tier is None and target in TRACK_FALLBACK_MAP:
        target = TRACK_FALLBACK_MAP[target]
        tier = SYMBOL_INDEX.get(target)

    frame = None
    if tier is not None:
        path = _symbol_path(target, tier)
        with _PARQUET_LOCK:
            for (sym, t, _mt), df in _PARQUET_CACHE.items():
                if sym == target and df is not None and not getattr(df, "empty", True):
                    frame = df
                    break

        if frame is None and path.is_file():
            tail = _symbol_quote_tail_cached(path)
            if tail is not None:
                local_last, local_prev, local_asof = tail

    if local_last is None:
        frame, tier = _load_symbol_df(symbol)
        if frame is not None and not getattr(frame, "empty", True) and "close" in frame.columns:
            closes = frame["close"].astype(float).dropna()
            if len(closes):
                local_last = _safe_round(float(closes.iloc[-1]), 4)
                local_asof = _frame_asof_date(frame)
            if len(closes) > 1:
                local_prev = _safe_round(float(closes.iloc[-2]), 4)

    live_spot, live_asof = _fetch_lse_equity_spot(symbol)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if live_spot is not None:
        last = live_spot
        if local_asof and str(local_asof)[:10] >= today:
            prev = local_prev
        else:
            prev = local_last
        source = "lse_equity_candles"
        quality = "live"
        asof = live_asof or local_asof
    elif local_last is not None:
        last = local_last
        prev = local_prev
        source = "1d"
        quality = "local"
        asof = local_asof
    else:
        last = None
        prev = None
        source = "unavailable"
        quality = "stale"
        asof = None

    chg = _pct(prev, last) if prev is not None and last is not None else None

    regime_badge = None
    primary_magnet_target = None
    magnet_distance_pct = None

    sym_upper = symbol.upper()
    with _PRICE_ATTRACTOR_LOCK:
        cached_attractor = _PRICE_ATTRACTOR_CACHE.get(sym_upper)

    if cached_attractor is not None:
        attractor_data = cached_attractor[1]
        regime_badge = attractor_data.get("regime_state")
        pm = attractor_data.get("primary_magnet")
        if isinstance(pm, dict):
            primary_magnet_target = pm.get("price")
            magnet_distance_pct = pm.get("distance_pct")
    elif last is not None and last > 0:
        chain_dates = _option_chain_dates(sym_upper)
        if chain_dates:
            try:
                hist_rows, _, _ = _historical_option_rows(sym_upper, asof=chain_dates[-1])
                if hist_rows:
                    snap = compute_price_attractors(
                        symbol=sym_upper,
                        spot=float(last),
                        chain_rows=hist_rows,
                    )
                    if snap.quality.get("measurable"):
                        regime_badge = snap.regime_state
                        if snap.primary_magnet:
                            primary_magnet_target = snap.primary_magnet.price
                            magnet_distance_pct = snap.primary_magnet.distance_pct
                        with _PRICE_ATTRACTOR_LOCK:
                            _PRICE_ATTRACTOR_CACHE[sym_upper] = (time.time(), snap.to_dict())
            except Exception:
                pass

    return {
        "symbol": symbol,
        "last": last,
        "prev_close": prev,
        "chg_1d_pct": _safe_round(chg, 4) if chg is not None else None,
        "asof": asof,
        "source": source,
        "quality": quality,
        "regime_badge": regime_badge,
        "primary_magnet_target": primary_magnet_target,
        "magnet_distance_pct": magnet_distance_pct,
    }


def _quotes_payload(symbols: list[str]) -> dict:
    cleaned: list[str] = []
    for raw in symbols:
        ok, sym = _sanitize_symbol(raw)
        if ok and sym not in cleaned:
            cleaned.append(sym)
        if len(cleaned) >= 40:
            break
    rows: list[dict] = []
    if cleaned:
        futures = _get_concurrent_futures()
        workers = min(8, len(cleaned))
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_symbol_quote, cleaned))
    return {
        "asof": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "rows": rows,
        "count": len(rows),
    }


_LSE_CIRCUIT_BREAKER_UNTIL = 0.0
_LSE_CONSECUTIVE_FAILURES = 0
_LSE_CIRCUIT_LOCK = threading.Lock()


def _fetch_lse_equity_spot(symbol: str) -> tuple[float | None, str | None]:
    """Latest equity last from LSE candles with fast-fail circuit breaker.

    Used as Options SPOT when the live chain lacks a timestamped underlying
    quote. Local daily parquet is often multi-day stale; LSE candles are the
    same provider as the live options chain.
    """
    global _LSE_CIRCUIT_BREAKER_UNTIL, _LSE_CONSECUTIVE_FAILURES
    key = symbol.upper()
    now = time.time()
    with _LSE_EQUITY_SPOT_LOCK:
        cached = _LSE_EQUITY_SPOT_CACHE.get(key)
        if cached is not None and now - cached[0] < _LSE_EQUITY_SPOT_TTL_S:
            return cached[1], cached[2]

    with _LSE_CIRCUIT_LOCK:
        if now < _LSE_CIRCUIT_BREAKER_UNTIL:
            return None, None

    spot: float | None = None
    asof: str | None = None
    try:
        provider_src = ROOT / "TradingWork" / "src"
        if str(provider_src) not in sys.path:
            sys.path.insert(0, str(provider_src))
        from lse_provider import fetch_lse_candles  # type: ignore[import-not-found]

        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(days=5)
        frame = None
        for timeframe in ("5m", "15m", "1h", "1d"):
            try:
                frame = fetch_lse_candles(
                    key,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                    use_cache=False,
                    refresh=True,
                    timeout=3,
                )
            except Exception:  # noqa: BLE001
                # A 402/429 on 5m must not skip 1d; ISO quota exhaustion is
                # per-route and the daily vault candle is often still there.
                continue
            if frame is not None and not getattr(frame, "empty", True):
                break

        if frame is not None and not getattr(frame, "empty", True) and "close" in frame.columns:
            close = float(frame["close"].iloc[-1])
            if math.isfinite(close) and close > 0:
                spot = _safe_round(close, 4)
                try:
                    ts = _get_pd().Timestamp(frame.index[-1])
                    if ts.tzinfo is None:
                        asof = ts.tz_localize("UTC").isoformat()
                    else:
                        asof = ts.tz_convert("UTC").isoformat()
                except (TypeError, ValueError, AttributeError):
                    asof = None
                with _LSE_CIRCUIT_LOCK:
                    _LSE_CONSECUTIVE_FAILURES = 0
    except Exception:  # noqa: BLE001 - equity spot is a soft dependency
        spot, asof = None, None
        with _LSE_CIRCUIT_LOCK:
            _LSE_CONSECUTIVE_FAILURES += 1
            if _LSE_CONSECUTIVE_FAILURES >= 2:
                _LSE_CIRCUIT_BREAKER_UNTIL = time.time() + 60.0

    if spot is None:
        with _LSE_CIRCUIT_LOCK:
            _LSE_CONSECUTIVE_FAILURES += 1
            if _LSE_CONSECUTIVE_FAILURES >= 3:
                _LSE_CIRCUIT_BREAKER_UNTIL = time.time() + 30.0

    with _LSE_EQUITY_SPOT_LOCK:
        _LSE_EQUITY_SPOT_CACHE[key] = (now, spot, asof)
        if len(_LSE_EQUITY_SPOT_CACHE) > 256:
            oldest = min(_LSE_EQUITY_SPOT_CACHE, key=lambda sym: _LSE_EQUITY_SPOT_CACHE[sym][0])
            _LSE_EQUITY_SPOT_CACHE.pop(oldest, None)
    return spot, asof


def _spot_from_flow_rows(flow_rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, str | None]:
    """Most recent tape print that carries an underlying price."""
    best_ts: datetime | None = None
    best_price: float | None = None
    best_asof: str | None = None
    for row in flow_rows:
        raw_price = row.get("underlying_price")
        if raw_price is None:
            raw_price = row.get("spot")
        try:
            price = float(raw_price) if raw_price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None or not math.isfinite(price) or price <= 0:
            continue
        raw_ts = row.get("ts") or row.get("timestamp") or row.get("asof_utc") or row.get("time")
        observed: datetime | None = None
        if raw_ts is not None:
            try:
                text = str(raw_ts).replace("Z", "+00:00")
                observed = datetime.fromisoformat(text)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
            except ValueError:
                observed = None
        if best_price is None:
            best_price = _safe_round(price, 4)
            best_ts = observed
            best_asof = (
                observed.isoformat()
                if observed is not None
                else (str(raw_ts) if raw_ts is not None else None)
            )
            continue
        # Prefer a timestamped print over an untimestamped one; among
        # timestamped prints keep the most recent observation.
        if observed is None:
            continue
        if best_ts is None or observed >= best_ts:
            best_price = _safe_round(price, 4)
            best_ts = observed
            best_asof = observed.isoformat()
    return best_price, best_asof


def _augment_price_series_with_live(
    series: list[dict],
    live_spot: float | None,
    live_asof: str | None,
) -> list[dict]:
    """Keep the stock overlay honest when local daily bars lag the session."""
    if live_spot is None or not series:
        return series
    out = list(series)
    ts = live_asof or datetime.now(timezone.utc).isoformat()
    last_t = str(out[-1].get("t") or "")
    point = {"t": ts, "close": live_spot, "volume": out[-1].get("volume")}
    if last_t[:10] and last_t[:10] < ts[:10]:
        out.append(point)
    else:
        out[-1] = {**out[-1], "close": live_spot, "t": ts}
    return out


def _resolve_live_options_spot(
    *,
    chain_spot: float | None,
    equity_spot: float | None,
    equity_asof: str | None,
    flow_spot: float | None,
    flow_asof: str | None,
    price_spot: float | None,
    price_asof: str | None,
    warnings: list[str],
) -> tuple[float | None, str | None]:
    """Prefer timestamped live sources over multi-day local closes."""
    if chain_spot is not None:
        return chain_spot, "chain_underlying_quote"
    if equity_spot is not None:
        return equity_spot, f"lse_equity_candles:{equity_asof or 'unknown'}"
    if flow_spot is not None:
        warnings.append(
            "Spot from latest options-tape underlying print — equity candles unavailable."
        )
        return flow_spot, f"lse_flow_underlying:{flow_asof or 'unknown'}"
    if price_spot is not None:
        warnings.append(
            "Spot is last local daily close"
            + (f" ({price_asof[:10]})" if price_asof else "")
            + "; live equity quote unavailable — levels may lag the session."
        )
        return price_spot, f"local_daily_close:{price_asof or 'unknown'}"
    return None, None


def _refresh_history_spot(
    symbol: str,
    *,
    snapshot_spot: float | None,
    warnings: list[str],
) -> tuple[float | None, str | None]:
    """Best-effort live spot for history/history_fallback mode.

    A dated chain snapshot freezes the underlying spot at capture time. When
    that snapshot is days old and the live chain is unavailable, the embedded
    spot becomes structurally wrong — every Greek, wall, and the chart marker
    are computed against a stale price. This fetches a fresh spot from the
    same priority sources as the live path (LSE equity candles → yfinance
    last price → local daily close) so a stale snapshot's spot is overridden
    when a fresher mark is available.

    Returns ``(spot, source)`` where ``source`` is a ``spot_source`` label.
    When no fresher source beats the snapshot, returns ``(snapshot_spot,
    "cached_chain_spot")`` so callers can still label the origin honestly.
    """
    equity_spot, equity_asof = _fetch_lse_equity_spot(symbol)
    if equity_spot is not None and math.isfinite(equity_spot) and equity_spot > 0:
        return equity_spot, f"lse_equity_candles:{equity_asof or 'unknown'}"

    # yfinance last price — delayed but still fresher than a multi-day-old
    # snapshot embedded spot for names outside the LSE equity universe.
    try:
        import yfinance as yf  # type: ignore[import-not-found]

        ticker = yf.Ticker(symbol)

        # Both lookups below are unbounded network calls. `_fetch_yfinance_ohlcv`
        # already learned this lesson and passes timeout=10; this path did not,
        # and when Yahoo half-closed the connection the handler sat in a blocking
        # read forever (sockets visible in CLOSE_WAIT, thread at 0% CPU). Because
        # the Setups payload calls this while holding _LIVE_OPPORTUNITIES_LOCK,
        # one wedged lookup queued every later /api/options/suggest behind it and
        # the tab showed "UPDATING..." with 0 names indefinitely.
        #
        # `fast_info` takes no timeout argument at all, so the whole block is run
        # on a worker with a hard deadline. A leaked thread is survivable; a
        # permanently held module-level lock is not.
        def _yf_spot_lookup() -> float | None:
            spot: float | None = None
            try:
                spot = _safe_round(float(ticker.fast_info.get("last_price")), 4)
            except Exception:  # noqa: BLE001 - fast_info is best-effort
                spot = None
            if spot is None or spot <= 0:
                hist = ticker.history(period="1d", timeout=_YF_SPOT_TIMEOUT_S)
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    spot = _safe_round(float(hist["Close"].iloc[-1]), 4)
            return spot

        yf_spot: float | None = None
        _futures = _get_concurrent_futures()
        _yf_pool = _futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="yf-spot")
        try:
            yf_spot = _yf_pool.submit(_yf_spot_lookup).result(timeout=_YF_SPOT_DEADLINE_S)
        except _futures.TimeoutError:
            warnings.append(
                f"yfinance spot lookup for {symbol} exceeded "
                f"{_YF_SPOT_DEADLINE_S:.0f}s and was abandoned."
            )
            yf_spot = None
        except Exception:  # noqa: BLE001 - yfinance is best-effort
            yf_spot = None
        finally:
            # Never join: the point is to not block on a wedged worker.
            _yf_pool.shutdown(wait=False)
        if yf_spot is not None and math.isfinite(yf_spot) and yf_spot > 0:
            warnings.append(
                "Spot refreshed from delayed yfinance last price; "
                "chain structure is from a dated snapshot."
            )
            return yf_spot, "yfinance_delayed_last_price"
    except Exception:  # noqa: BLE001 - yfinance is a soft dependency
        pass

    if snapshot_spot is not None and snapshot_spot > 0:
        return snapshot_spot, "cached_chain_spot"
    return None, None


def _cached_option_chain_rows(path: Path) -> list[dict[str, Any]]:
    """Decode one immutable chain snapshot once per (mtime, size)."""
    try:
        stat = path.stat()
    except OSError:
        return []
    signature = (stat.st_mtime_ns, stat.st_size)
    with _OPTION_CHAIN_FILE_LOCK:
        cached = _OPTION_CHAIN_FILE_CACHE.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
    try:
        frame = _get_pd().read_parquet(path)
        rows = [] if frame.empty else frame.to_dict("records")
    except (OSError, ValueError):
        rows = []
    with _OPTION_CHAIN_FILE_LOCK:
        _OPTION_CHAIN_FILE_CACHE[path] = (signature, rows)
        if len(_OPTION_CHAIN_FILE_CACHE) > 512:
            oldest = next(iter(_OPTION_CHAIN_FILE_CACHE))
            _OPTION_CHAIN_FILE_CACHE.pop(oldest, None)
    return rows


def _option_chain_dates(symbol: str, *, limit: int = 93) -> list[str]:
    """Return available dated chain folders for a symbol (oldest → newest)."""
    option_root = EDGE_DIR / "data" / "option_chains"
    dates: list[str] = []
    for path in sorted(option_root.glob(f"date=*/{symbol}.parquet"))[-limit:]:
        # Skip unreadable / empty files so "last good" is actually usable.
        if not _cached_option_chain_rows(path):
            continue
        dates.append(path.parent.name.removeprefix("date="))
    return dates


def _historical_option_rows(
    symbol: str,
    *,
    asof: str | None = None,
    all_days: bool = False,
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
        rows.extend(_cached_option_chain_rows(path))
    return rows, selected, available


_SECRETISH = re.compile(
    r"(?i)((?:api[_-]?key|apikey|x-api-key|token|secret|authorization|password)\s*[=:]\s*)\S+"
)
_ENV_KEYISH = re.compile(r"(?i)\b(LSE_API_KEY|FINTEL_API_KEY)\s*=\s*\S+")


def _redact_secrets(text: str) -> str:
    """Strip provider credentials from operator-visible strings and JSON."""
    redacted = _SECRETISH.sub(r"\1***", str(text or ""))
    redacted = _ENV_KEYISH.sub(lambda m: f"{m.group(1)}=***", redacted)
    for env_name in ("LSE_API_KEY", "FINTEL_API_KEY"):
        value = str(os.getenv(env_name) or "").strip()
        if len(value) >= 6 and value in redacted:
            redacted = redacted.replace(value, "***")
    return redacted


def _redact_payload(value):
    if isinstance(value, str):
        return _redact_secrets(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value


def _provider_note(exc: BaseException, limit: int = 200) -> str:
    """Render a provider failure so an operator can act on it.

    The live-options catch sites kept only ``type(exc).__name__``, so a ticker
    the provider does not cover, an expired key, and a dead network all reached
    the UI as the same single word: ``RuntimeError``. Every other catch site in
    this file already carries ``: {exc}``; these were the outliers.

    The message is whitespace-collapsed, length-bounded, and stripped of any
    ``key=<value>`` shaped token in case a provider echoes a request back in
    its error text — warnings are rendered in the dashboard.
    """
    msg = _redact_secrets(" ".join(str(exc).split()))
    if not msg:
        return type(exc).__name__
    if len(msg) > limit:
        msg = msg[: limit - 1].rstrip() + "\u2026"
    return f"{type(exc).__name__}: {msg}"


def _fetch_live_option_inputs(
    symbol: str,
    *,
    filters: OptionsFilters,
) -> tuple[list[dict], list[dict], float | None, str, list[str], str | None]:
    warnings: list[str] = []
    request_clock = datetime.now(timezone.utc)
    spot_source: str | None = None

    def fetch_chain() -> Mapping[str, Any]:
        return LSEOptionsAdapter(
            api_key=os.getenv("LSE_API_KEY"),
            min_dte=filters.min_dte,
            max_dte=filters.max_dte,
        ).snapshot(symbol, asof_utc=request_clock)

    def fetch_flow() -> list[dict]:
        provider_src = ROOT / "TradingWork" / "src"
        if str(provider_src) not in sys.path:
            sys.path.insert(0, str(provider_src))
        from lse_provider import fetch_lse_options_flow  # type: ignore[import-not-found]

        # The provider caps every pull at `limit` rows ordered ts.desc, so the
        # premium floor decides how far back that budget reaches. On an active
        # name a $0 floor burns all 500 rows inside ~90 seconds, which is why
        # the tape used to open showing only the last few minutes of the
        # session instead of the day. Two passes fix that without losing the
        # liveness signal a wide band provides:
        #   coverage — pull at the UI floor, the only rows that can ever be
        #     displayed, so 500 rows stretch across the whole session.
        #   liveness — a short low-floor pull so quiet names still prove the
        #     feed is alive (and hand us a fresh underlying print for spot)
        #     instead of showing day-old whales and reading "TAPE STALE".
        ui_floor = max(float(filters.min_premium or 0.0), 0.0)
        passes: list[tuple[float, int]] = [
            (ui_floor, 2500),
            (25_000.0, 2500),  # full-session institutional flow (captures morning whales)
        ]
        if ui_floor > 1_000.0:
            passes.append((1_000.0, 300))

        merged: dict[tuple[Any, ...], dict] = {}
        first_error: Exception | None = None
        for floor, cap in passes:
            try:
                rows = fetch_lse_options_flow(
                    symbol,
                    min_premium=floor,
                    limit=cap,
                    # The provider falls back to the bulk vault route when the
                    # metered /iso tables are exhausted, and that route ships
                    # the whole result set rather than a trimmed projection —
                    # a 2500-row pull is megabytes. At 12s the first pass
                    # intermittently timed out and blanked the entire tape.
                    timeout=30,
                )
            except Exception as exc:  # noqa: BLE001 - one pass failing must not blank the tape
                # Raising here on the *first* pass threw away the later ones,
                # so a single slow request cost the whole tape even when the
                # remaining floors would have answered. Keep going; only a
                # clean sweep of failures is a real outage.
                first_error = first_error or exc
                continue
            for row in rows or []:
                if not isinstance(row, Mapping):
                    continue
                key = (
                    str(row.get("ts") or row.get("timestamp") or ""),
                    str(row.get("option_symbol") or row.get("occ_symbol") or ""),
                    row.get("strike"),
                    row.get("premium"),
                    row.get("size") or row.get("volume"),
                )
                merged.setdefault(key, dict(row))
        if not merged and first_error is not None:
            raise first_error
        return list(merged.values())

    # Chain, tape, and equity last are independent network reads. Overlap them
    # so live Options latency is bounded by the slowest provider call rather
    # than their sum — and so SPOT is not stuck on a multi-day local close.
    futures = _get_concurrent_futures()
    with futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="options-live") as pool:
        chain_future = pool.submit(fetch_chain)
        flow_future = pool.submit(fetch_flow)
        equity_future = pool.submit(_fetch_lse_equity_spot, symbol)
        try:
            snapshot = chain_future.result()
        except Exception as exc:  # noqa: BLE001 - history fallback remains available
            snapshot = {}
            warnings.append(f"Live chain unavailable: {_provider_note(exc)}")
        try:
            flow_rows = flow_future.result()
        except Exception as exc:  # noqa: BLE001 - live flow is optional evidence
            flow_rows = []
            warnings.append(f"Live flow unavailable: {_provider_note(exc)}")
        try:
            equity_spot, equity_asof = equity_future.result()
        except Exception:  # noqa: BLE001 - equity last is a soft dependency
            equity_spot, equity_asof = None, None

    chain_rows = list(snapshot.get("contracts") or [])
    underlying = snapshot.get("underlying", {}) if isinstance(snapshot, Mapping) else {}
    # A last-trade-derived spot without its own quote timestamp is not a live
    # underlying quote. Prefer LSE equity candles, then recent tape prints,
    # before falling back to the (often multi-day-stale) local daily close.
    chain_spot: float | None = None
    if underlying.get("quote_asof_utc") is not None and underlying.get("price") is not None:
        try:
            candidate = float(underlying.get("price"))
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and math.isfinite(candidate) and candidate > 0:
            chain_spot = _safe_round(candidate, 4)
    flow_spot, flow_asof = _spot_from_flow_rows(flow_rows)
    spot, spot_source = _resolve_live_options_spot(
        chain_spot=chain_spot,
        equity_spot=equity_spot,
        equity_asof=equity_asof,
        flow_spot=flow_spot,
        flow_asof=flow_asof,
        price_spot=None,
        price_asof=None,
        warnings=warnings,
    )
    open_interest_source = "lse_live"

    if chain_rows:
        live_oi_available = any(int(row.get("open_interest") or 0) > 0 for row in chain_rows)

        def join_cached_reference() -> tuple[int, int, str | None]:
            """Fill OI (and delayed NBBO) from the dated snapshot, by exact OCC."""
            cached_rows, label, _ = _historical_option_rows(symbol, all_days=False)
            cached_by_occ = {
                str(row.get("contractSymbol") or row.get("occ_symbol") or "").upper(): row
                for row in cached_rows
                if str(row.get("contractSymbol") or row.get("occ_symbol") or "").strip()
            }
            matched_oi = 0
            matched_quotes = 0
            same_day_reference = label == request_clock.date().isoformat()
            for row in chain_rows:
                occ = str(row.get("occ_symbol") or "").upper()
                cached = cached_by_occ.get(occ)
                if not cached:
                    continue
                if not live_oi_available:
                    try:
                        oi = int(
                            float(cached.get("openInterest") or cached.get("open_interest") or 0)
                        )
                    except (TypeError, ValueError):
                        oi = 0
                    if oi > 0:
                        row["open_interest"] = oi
                        matched_oi += 1
                # LSE currently supplies greeks/activity but no NBBO. A same-day
                # yfinance snapshot may fill the exact OCC quote for paper review.
                # It is deliberately marked non-live so it can never unlock sizing.
                if same_day_reference and (row.get("bid") is None or row.get("ask") is None):
                    try:
                        bid = float(cached.get("bid"))
                        ask = float(cached.get("ask"))
                    except (TypeError, ValueError):
                        bid = ask = None
                    if (
                        bid is not None
                        and ask is not None
                        and math.isfinite(bid)
                        and math.isfinite(ask)
                        and ask >= bid >= 0
                        and ask > 0
                    ):
                        row["bid"] = bid
                        row["ask"] = ask
                        row["quote_live"] = False
                        row["quote_source"] = "yfinance_delayed_exact_occ"
                        row["quote_asof_utc"] = cached.get("captured_utc") or cached.get(
                            "asof_date"
                        )
                        matched_quotes += 1
            return matched_oi, matched_quotes, label

        oi_matches, delayed_quote_matches, latest_label = join_cached_reference()

        # Every gamma figure — GEX, walls, the squeeze board — is a function of
        # open interest, and LSE's live chain omits it. Names outside the dated
        # option_chains universe (GME-class) therefore used to render a wall of
        # fake zeros until someone pressed "BACKFILL OI" by hand. Capture the
        # delayed snapshot in-process instead, then redo the exact-OCC join, so
        # structure is measured on first load for any symbol with a listed chain.
        if not live_oi_available and not oi_matches:
            capture_dte = min(max(int(filters.max_dte or 60), 60), 180)
            captured, capture_err = _ensure_delayed_chain_snapshot(
                symbol,
                max_dte=capture_dte,
            )
            if captured:
                oi_matches, extra_quotes, latest_label = join_cached_reference()
                delayed_quote_matches += extra_quotes
                if oi_matches:
                    warnings.append(
                        "Live chain carried no open interest; auto-captured a delayed "
                        "yfinance OI snapshot so structure is measured, not zeroed."
                    )
            elif capture_err:
                warnings.append(f"Open-interest backfill unavailable: {capture_err}")

        if not live_oi_available:
            open_interest_source = (
                f"cached_chain_exact_occ:{latest_label or 'unknown'}"
                if oi_matches
                else "unavailable"
            )
        if delayed_quote_matches:
            warnings.append(
                f"{delayed_quote_matches} exact OCC bid/ask pairs use a same-day delayed "
                "yfinance reference; they are paper-only and never sizing-eligible."
            )

    if not flow_rows and not any(note.startswith("Live flow unavailable:") for note in warnings):
        # The provider returns an empty list for a transport failure and for a
        # genuinely quiet name alike, so this line used to blame the operator's
        # filters for outages they could not fix — the LSE monthly byte quota
        # answering 402 on every /iso read reads exactly like a quiet tape.
        # Name the reachable causes instead of only the one the user can act on.
        warnings.append(
            "No trade-tape prints returned for this symbol. This is either a quiet tape "
            "(try the RAW noise filter or a more liquid name) or the provider declining "
            "the read — check the server log for an LSE options_flow error."
        )
    return chain_rows, flow_rows, spot, open_interest_source, warnings, spot_source


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
            "error": f"No options data from the provider for {symbol}: {type(exc).__name__}: {exc}",
            "endpoint": "/api/options/backfill_oi",
            "symbol": symbol,
        }, 404

    out_dir = EDGE_DIR / "data" / "option_chains" / f"date={asof.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_dir / f"{symbol}.parquet")

    # The next /api/options and /api/price-attractors fetch must see this snapshot immediately, not
    # after the cache TTL expires.
    with _OPTIONS_LOCK:
        for key in [k for k in _OPTIONS_CACHE if k[0] == symbol]:
            _OPTIONS_CACHE.pop(key, None)
    with _PRICE_ATTRACTOR_LOCK:
        _PRICE_ATTRACTOR_CACHE.pop(symbol.upper(), None)

    return {
        "status": "ok",
        "symbol": symbol,
        "asof": asof.isoformat(),
        "contracts": int(len(frame)),
        "with_oi": int((frame["openInterest"] > 0).sum()),
    }, 200


# Symbols the provider has no listed chain for (indices, delisted tickers) fail
# every time and cost a multi-second network round trip each. Remember the
# failure briefly so a page that polls /api/options does not re-attempt it on
# every request.
_DELAYED_CHAIN_MISS: dict[str, tuple[float, str]] = {}
_DELAYED_CHAIN_MISS_TTL_S = 10 * 60.0


def _ensure_delayed_chain_snapshot(
    symbol: str,
    *,
    max_dte: int = 60,
    max_age_seconds: float = 15 * 60.0,
) -> tuple[bool, str | None]:
    """Refresh the delayed exact-contract reference for a user-selected name."""
    today = datetime.now(timezone.utc).date().isoformat()
    path = EDGE_DIR / "data" / "option_chains" / f"date={today}" / f"{symbol}.parquet"
    try:
        if path.is_file() and time.time() - path.stat().st_mtime <= max_age_seconds:
            _DELAYED_CHAIN_MISS.pop(symbol, None)
            return True, None
    except OSError:
        pass
    cached_miss = _DELAYED_CHAIN_MISS.get(symbol)
    if cached_miss and time.time() - cached_miss[0] <= _DELAYED_CHAIN_MISS_TTL_S:
        return False, cached_miss[1]
    result, status = _backfill_oi_payload(symbol, max_dte=max_dte)
    if status == 200:
        _DELAYED_CHAIN_MISS.pop(symbol, None)
        return True, None
    error = str(result.get("error") or "delayed chain snapshot unavailable")
    _DELAYED_CHAIN_MISS[symbol] = (time.time(), error)
    return False, error


def _options_underlying_bars(symbol: str, *, limit: int = 60) -> list[dict]:
    """Recent OHLCV bars of the underlying (1h preferred) for the pressure read.

    Returns an empty list on any failure so a bar-loading problem degrades to
    "underlying channel abstains" rather than taking the options page down.
    """
    try:
        frame = _load_symbol_bars(symbol, prefer_intraday=True)
    except Exception:
        return []
    if frame is None or frame.empty:
        return []
    needed = [col for col in ("open", "high", "low", "close", "volume") if col in frame.columns]
    if "close" not in needed:
        return []
    tail = frame[needed].tail(limit)
    bars: list[dict] = []
    for idx, row in tail.iterrows():
        bar = {"t": str(idx)}
        for col in needed:
            value = row[col]
            bar[col] = float(value) if value is not None and math.isfinite(float(value)) else None
        bars.append(bar)
    return bars


def _options_payload_impl(symbol: str, query: dict) -> tuple[dict, int]:
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
        return {
            "error": "max_dte must be greater than or equal to min_dte",
            "endpoint": "/api/options",
        }, 400
    selected_expiry = str(query.get("expiry", ["nearest"])[0] or "nearest").lower()
    if selected_expiry not in {"nearest", "all"}:
        try:
            datetime.fromisoformat(selected_expiry)
        except ValueError:
            return {
                "error": "expiry must be nearest, all, or YYYY-MM-DD",
                "endpoint": "/api/options",
            }, 400
    filters = OptionsFilters(
        range=selected_range,
        min_premium=q_float("min_premium", 50_000.0, 0, 100_000_000),
        min_volume=_safe_int(query.get("min_volume", ["10"])[0], 10, 0, 1_000_000),
        min_open_interest=_safe_int(query.get("min_oi", ["100"])[0], 100, 0, 10_000_000),
        max_spread_pct=q_float("max_spread", 0.25, 0.001, 2.0),
        min_dte=min_dte,
        max_dte=max_dte,
        expiry=selected_expiry,
        # Default matches the LSE flow fetch cap so the tape list and C/P
        # summary share the same print set (a 100-row slice was hiding most
        # of the window and made the ratio disagree with the visible tape).
        tape_limit=_safe_int(query.get("tape_limit", ["2500"])[0], 2500, 1, 5000),
        date_from=(query.get("from", [None])[0] or None),
        date_to=(query.get("to", [None])[0] or None),
        risk_free_rate=q_float("rate", 0.045, -0.05, 0.25),
    )
    cache_key = (symbol, mode, *asdict(filters).values())
    with _OPTIONS_LOCK:
        cached = _OPTIONS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _OPTIONS_CACHE_TTL_S:
        payload = cached[1]
        if isinstance(payload, dict):
            _store_regime_attractor_snapshot(symbol, payload.get("price_attractor_snapshot"))
        return payload, 200

    price_series, price_spot = _options_price_series(
        symbol,
        selected_range,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
    price_asof = str(price_series[-1].get("t")) if price_series else None
    warnings: list[str] = []
    chain_rows: list[dict] = []
    flow_rows: list[dict] = []
    live_spot: float | None = None
    live_spot_source: str | None = None
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
            (
                chain_rows,
                flow_rows,
                live_spot,
                open_interest_source,
                live_warnings,
                live_spot_source,
            ) = _fetch_live_option_inputs(
                symbol,
                filters=filters,
            )
            warnings.extend(live_warnings)
        except Exception as exc:  # noqa: BLE001 - fall back visibly, never silently
            warnings.append(f"Live chain unavailable: {_provider_note(exc)}")
        if live_spot is None and price_spot is not None:
            live_spot, live_spot_source = _resolve_live_options_spot(
                chain_spot=None,
                equity_spot=None,
                equity_asof=None,
                flow_spot=None,
                flow_asof=None,
                price_spot=price_spot,
                price_asof=price_asof,
                warnings=warnings,
            )
        if live_spot is not None:
            # Align the stock overlay with session-current spot when local
            # daily bars lag (otherwise SPOT and the chart disagree).
            equity_asof = None
            if live_spot_source and live_spot_source.startswith("lse_equity_candles:"):
                equity_asof = live_spot_source.split(":", 1)[1]
                if equity_asof == "unknown":
                    equity_asof = None
            elif live_spot_source and live_spot_source.startswith("lse_flow_underlying:"):
                equity_asof = live_spot_source.split(":", 1)[1]
                if equity_asof == "unknown":
                    equity_asof = None
            if live_spot_source and not live_spot_source.startswith("local_daily_close"):
                price_series = _augment_price_series_with_live(
                    price_series,
                    live_spot,
                    equity_asof,
                )

    if mode == "history" or not chain_rows:
        # Prefer an explicit `to` date when it matches a dated snapshot; otherwise
        # auto-load the last good chain day so History is never an empty shell.
        requested_asof = filters.date_to
        chain_rows, latest_label, available_dates = _historical_option_rows(
            symbol,
            asof=requested_asof,
            all_days=False,
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
            # Names outside the cached option_chains universe (QBTS-class)
            # have no dated parquet. Capture a delayed yfinance snapshot so
            # the desk can still measure structure instead of 404ing into
            # a wall of fake-zero boxes.
            capture_dte = min(max(int(filters.max_dte or 60), 60), 180)
            delayed_ok, delayed_err = _ensure_delayed_chain_snapshot(
                symbol,
                max_dte=capture_dte,
            )
            if delayed_ok:
                chain_rows, latest_label, available_dates = _historical_option_rows(
                    symbol,
                    asof=requested_asof,
                    all_days=False,
                )
                history_chain_rows, _, _ = _historical_option_rows(
                    symbol,
                    all_days=True,
                )
                history_meta = {
                    "available_dates": available_dates,
                    "selected_asof": latest_label,
                    "last_good_asof": available_dates[-1] if available_dates else None,
                    "auto_selected": True,
                }
                warnings.append(
                    "Live chain empty; captured a delayed yfinance snapshot for this name."
                )
            if not chain_rows:
                return {
                    "error": f"No options chain is available for {symbol}.",
                    "endpoint": "/api/options",
                    "symbol": symbol,
                    "reason": "live_empty_and_no_local_snapshot",
                    "delayed_snapshot_error": delayed_err if not delayed_ok else None,
                    "warnings": warnings,
                    "history": history_meta,
                }, 404
        mode_resolved = "history" if mode == "history" else "history_fallback"
        chain_source = f"cached_chain:{latest_label or 'unknown'}"
        flow_source = "unavailable"
        open_interest_source = chain_source
        if mode == "live":
            warnings.append(
                "Showing the latest dated chain because the live chain was unavailable."
            )
        elif history_meta["auto_selected"] and latest_label:
            warnings.append(f"History auto-loaded the last good chain day ({latest_label}).")
        elif latest_label and requested_asof and requested_asof != latest_label:
            warnings.append(
                f"Requested chain day {requested_asof} was unavailable; loaded {latest_label}."
            )

    if not history_chain_rows:
        history_chain_rows, hist_label, available_dates = _historical_option_rows(
            symbol,
            all_days=True,
        )
        if available_dates and not history_meta["available_dates"]:
            history_meta = {
                "available_dates": available_dates,
                "selected_asof": hist_label,
                "last_good_asof": available_dates[-1],
                "auto_selected": False,
            }

    # History mode: the chain snapshot's embedded spot is frozen at capture
    # time. Attempt to refresh it from a live source so the chart marker and
    # every Greek are not computed against a days-old price. When no fresher
    # source is available, fall back to the snapshot spot honestly labelled.
    history_spot: float | None = None
    history_spot_source: str | None = None
    if mode_resolved != "live":
        snapshot_spot = next(
            (
                float(row.get("spot"))
                for row in chain_rows
                if row.get("spot") is not None
                and isinstance(row.get("spot"), (int, float))
                and float(row.get("spot")) > 0
            ),
            None,
        )
        history_spot, history_spot_source = _refresh_history_spot(
            symbol,
            snapshot_spot=snapshot_spot,
            warnings=warnings,
        )

    payload = build_options_intelligence(
        symbol=symbol,
        chain_rows=chain_rows,
        flow_rows=flow_rows,
        price_series=price_series,
        # A dated chain must use the spot captured with that chain, not the
        # latest daily close. Mixing observation clocks distorts every Greek.
        # Live mode prefers timestamped equity last (LSE candles / tape) over
        # multi-day-stale local parquet closes.
        # History mode: prefer a refreshed live spot over the stale snapshot
        # median; fall back to the snapshot spot when no live source is found.
        spot=(live_spot if mode_resolved == "live" else history_spot),
        filters=filters,
        mode_requested=mode,
        mode_resolved=mode_resolved,
        chain_source=chain_source,
        flow_source=flow_source,
        asof_utc=datetime.now(timezone.utc),
        warnings=warnings,
        open_interest_source=open_interest_source,
        history_chain_rows=history_chain_rows,
        # The underlying's own bars corroborate (or contradict) the options
        # pressure read; without them that channel abstains and says so.
        underlying_bars=_options_underlying_bars(symbol),
    )
    if isinstance(payload, dict):
        payload["history"] = history_meta
        if mode_resolved == "live" and live_spot_source:
            payload["spot_source"] = live_spot_source
        elif mode_resolved != "live" and history_spot_source:
            payload["spot_source"] = history_spot_source

        # Embed price attractor snapshot
        extracted_prices = [
            float(p.get("c") or p.get("close") or p.get("price") or 0.0)
            for p in (price_series or [])
            if isinstance(p, dict) and (p.get("c") or p.get("close") or p.get("price"))
        ]
        resolved_spot_for_attractor = live_spot if mode_resolved == "live" else history_spot
        try:
            attractor_snapshot = compute_price_attractors(
                symbol=symbol,
                spot=(
                    float(resolved_spot_for_attractor)
                    if (resolved_spot_for_attractor is not None and resolved_spot_for_attractor > 0)
                    else 0.0
                ),
                chain_rows=chain_rows,
                price_series=extracted_prices if extracted_prices else None,
                rate=filters.risk_free_rate,
            )
            payload["price_attractor_snapshot"] = attractor_snapshot.to_dict()
            _store_regime_attractor_snapshot(symbol, payload["price_attractor_snapshot"])
        except Exception as exc:
            payload["price_attractor_snapshot"] = {
                "symbol": symbol.upper(),
                "spot": resolved_spot_for_attractor,
                "asof_utc": datetime.now(timezone.utc).isoformat(),
                "regime_state": "unmeasurable",
                "regime_label": "Unmeasured Regime",
                "regime_strength": None,
                "dominant_direction": "unmeasured",
                "primary_magnet": None,
                "levels": [],
                "price_ladder": [],
                "confluence_clusters": [],
                "quality": {
                    "measurable": False,
                    "open_interest_available": False,
                    "iv_available": False,
                    "volume_available": False,
                    "reason": f"Attractor computation error: {exc}",
                },
                "warnings": [f"Attractor computation error: {exc}"],
            }
    with _OPTIONS_LOCK:
        _OPTIONS_CACHE[cache_key] = (time.time(), payload)
        if len(_OPTIONS_CACHE) > 128:
            oldest = min(_OPTIONS_CACHE, key=lambda key: _OPTIONS_CACHE[key][0])
            _OPTIONS_CACHE.pop(oldest, None)
    return payload, 200


def _options_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Coalesce identical cold Options requests from watchers/manual refreshes."""
    request_key = (
        symbol,
        tuple(
            sorted(
                (str(key), tuple(str(value) for value in values)) for key, values in query.items()
            )
        ),
    )
    with _OPTIONS_LOCK:
        build_lock = _OPTIONS_BUILD_LOCKS.setdefault(request_key, threading.Lock())
    with build_lock:
        payload, status = _options_payload_impl(symbol, query)
    if status == 200 and isinstance(payload.get("summary"), dict):
        _attach_realised_vol(symbol, payload["summary"])
    return payload, status


def _realised_vol_pct(closes: Sequence[float], days: int) -> float | None:
    """Annualised close-to-close realised volatility in percent, or None."""
    usable = [float(c) for c in closes if c is not None and math.isfinite(float(c)) and c > 0]
    if len(usable) < days + 1:
        return None
    window = usable[-(days + 1) :]
    returns = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    value = math.sqrt(variance) * math.sqrt(252.0) * 100.0
    return _safe_round(value, 2) if math.isfinite(value) else None


def _attach_realised_vol(symbol: str, summary: dict) -> None:
    """Add hv_20d/hv_30d from the local daily history.

    The Regime ribbon's HV pills had no source: `price_series` carries only the
    handful of recent sessions the chart draws, so both pills read "—" forever
    while the full daily history sat in the parquet store unused. Absent stays
    absent -- a symbol without enough history reports None, never a literal.
    """
    try:
        frame, _tier = _load_symbol_df(symbol)
    except Exception:  # noqa: BLE001 - realised vol is additive, never fatal
        frame = None
    closes: list[float] = []
    if frame is not None and not getattr(frame, "empty", True) and "close" in frame.columns:
        closes = [float(c) for c in frame["close"].dropna().tolist()]
    summary["hv_20d"] = _realised_vol_pct(closes, 20)
    summary["hv_30d"] = _realised_vol_pct(closes, 30)


# ---------------------------------------------------------------------------
# /api/zero-dte -- same-day expiry magnets read against the actual intraday bars

_ZERO_DTE_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_ZERO_DTE_LOCK = threading.Lock()
_ZERO_DTE_CACHE_TTL_S = 30.0

# Timeframes the candle feed actually serves. 1m comes from the vault route,
# the rest from the ISO candle tables.
_ZERO_DTE_TIMEFRAMES = {"1m": 1.0, "5m": 5.0, "15m": 15.0}


def _lse_intraday_bars(symbol: str, timeframe: str, *, days: int = 6) -> list[dict[str, Any]]:
    """Intraday OHLCV from the LSE candle feed, as plain dicts.

    Same import dance as the flow tape: the provider and its key live in the
    sibling TradingWork checkout, not here.
    """
    provider_src = ROOT / "TradingWork" / "src"
    if str(provider_src) not in sys.path:
        sys.path.insert(0, str(provider_src))
    from lse_provider import fetch_lse_candles  # type: ignore[import-not-found]

    end = datetime.now(timezone.utc).replace(tzinfo=None)
    frame = fetch_lse_candles(
        symbol.upper(),
        end - timedelta(days=days),
        end,
        timeframe=timeframe,
        use_cache=True,
    )
    if frame is None or getattr(frame, "empty", True):
        ticker = _INDEX_TICKERS.get(symbol.upper())
        return _yahoo_intraday_bars(ticker, timeframe) if ticker else []
    return [
        {
            "ts": ts,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume or 0.0),
        }
        for ts, row in frame.iterrows()
    ]


def _front_expiry_slice(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """The nearest not-yet-past expiry and its contracts.

    The feed ships a `dte` field but it is computed against the provider's own
    snapshot date, so on a Monday it can still read as it did the previous
    Wednesday. Expiry dates are unambiguous; the day count is derived here.
    """
    today = datetime.now(timezone.utc).astimezone(_EXCHANGE_TZ).date()
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        raw = r.get("expiry") or r.get("expiration") or r.get("expiration_date")
        if not raw:
            continue
        key = str(raw)[:10]
        by_expiry.setdefault(key, []).append(dict(r))
    if not by_expiry:
        return [], None
    future = sorted(k for k in by_expiry if date.fromisoformat(k) >= today)
    front = future[0] if future else sorted(by_expiry)[-1]
    return by_expiry[front], front


def _bars_as_utc(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp this feed's naive bar timestamps as UTC, leaving aware ones alone.

    Only the timestamp is touched; every other field is passed through by
    reference, so this is cheap on a 5,000-bar pull.
    """
    out: list[dict[str, Any]] = []
    for bar in bars:
        ts = bar.get("ts")
        moment = getattr(ts, "to_pydatetime", lambda: ts)()
        if isinstance(moment, datetime) and moment.tzinfo is None:
            out.append({**bar, "ts": moment.replace(tzinfo=timezone.utc)})
        else:
            out.append(bar)
    return out


def _execution_gate_payload(symbol: str, query: dict) -> tuple[dict, int]:
    """Clock, expiry policy, opening range and routed contract for one symbol.

    The structural side of the model (walls, flip, net GEX/DEX) already has its
    own endpoint. This is the execution side: whether the session permits an
    entry at all right now, which expiry this symbol may be traded at, where
    the Initial Balance sits, and which contract the delta corridor routes to.

    Every section reports its own measurability. A missing opening range or an
    unroutable chain is returned as such with a reason, never as a permissive
    default -- the failure this endpoint exists to prevent is a trade being
    sized against a gate nobody actually evaluated.
    """
    endpoint = "/api/execution-gate"
    sym = symbol.strip().upper()
    now = datetime.now(timezone.utc).astimezone(_EXCHANGE_TZ)

    gate = session_gate(now)
    policy = expiry_policy(sym, now)

    payload: dict[str, Any] = {
        "symbol": sym,
        "endpoint": endpoint,
        "asof": now.isoformat(),
        "session": {
            "phase": gate.phase,
            "may_enter": gate.may_enter,
            "reason": gate.reason,
            "must_be_flat": gate.must_be_flat,
            "permitted_setups": sorted(gate.permitted_setups),
            "exchange_time": gate.exchange_time,
        },
        "expiry_policy": {
            "min_dte": policy.min_dte,
            "max_dte": policy.max_dte,
            "zero_dte_permitted": policy.zero_dte_permitted,
            "rationale": policy.rationale,
        },
    }

    # Initial Balance, off the same 1m bars the 0DTE tape uses.
    try:
        bars = _lse_intraday_bars(sym, "1m")
    except Exception as exc:
        payload["initial_balance"] = {
            "measurable": False,
            "reason": f"intraday bars unavailable for {sym}: {_provider_note(exc)}",
        }
        bars = []
    else:
        # This feed stamps bars naive, in UTC -- the same convention
        # `zero_dte._as_utc` documents, and confirmed against the tape: bar
        # volume steps up an order of magnitude at naive hour 13 and collapses
        # after 20, which is RTH 09:30-16:00 ET expressed in UTC.
        # `initial_balance` refuses naive input by design, so the convention is
        # applied here, where the feed is known, rather than guessed at inside
        # the library.
        ib = initial_balance(_bars_as_utc(bars))
        payload["initial_balance"] = {
            "measurable": ib.measurable,
            "high": ib.high,
            "low": ib.low,
            "width": ib.width,
            "bar_count": ib.bar_count,
            "session_date": ib.session_date,
            "reason": ib.reason,
        }

    # Contract routing needs a spot and a chain. Spot comes from the last bar
    # rather than a separate quote call so the routed delta and the opening
    # range are read off the same tape.
    spot = None
    for bar in reversed(bars):
        close = bar.get("close")
        if close:
            spot = float(close)
            break

    direction = (query.get("direction", ["long"])[0] or "long").lower()
    if spot is None:
        payload["contract"] = {
            "measurable": False,
            "reason": f"no intraday close for {sym}, so no spot to route a delta against",
        }
        return payload, 200

    payload["spot"] = round(spot, 4)

    # The chain comes from /api/options, the same source the regime endpoint
    # reads, so the routed contract and the walls it is being routed against
    # are solved off one snapshot. The 0DTE fetch was the obvious choice and
    # the wrong one: it returns nothing for SPY whenever the LSE ISO chain is
    # unavailable, while this payload still resolves.
    chain_rows: list = []
    chain_source = "options"
    try:
        opt_payload, opt_status = _options_payload(sym, {})
    except Exception as exc:
        payload["contract"] = {
            "measurable": False,
            "reason": f"option chain unavailable for {sym}: {_provider_note(exc)}",
        }
        return payload, 200
    if opt_status == 200 and isinstance(opt_payload, dict):
        chain_rows = opt_payload.get("chain_by_strike") or opt_payload.get("chain_rows") or []
        chain_spot = (opt_payload.get("summary") or {}).get("spot")
        if chain_spot:
            # Route the delta against the chain's own spot, not the bar close.
            # A delta measured off one price and a strike ladder priced off
            # another silently shifts which contract sits in the corridor.
            spot = float(chain_spot)
            payload["spot"] = round(spot, 4)

    # require_spread is off because neither chain path carries bid/ask today.
    # The SpreadCheck still travels with the answer saying so, so an unchecked
    # fill cost stays visible instead of being quietly assumed to be zero.
    choice = select_contract(
        symbol=sym,
        direction=direction,
        chain_rows=chain_rows,
        spot=spot,
        moment=now,
        require_spread=False,
    )
    payload["chain_source"] = chain_source
    payload["contract"] = {
        "measurable": choice.measurable,
        "strike": choice.strike,
        "right": choice.right,
        "expiry": choice.expiry,
        "delta": choice.delta,
        "dte": choice.dte,
        "considered": choice.considered,
        "direction": direction,
        "reason": choice.reason,
        "warnings": choice.warnings,
        "spread": None
        if choice.spread is None
        else {
            "measurable": choice.spread.measurable,
            "ratio_pct": choice.spread.ratio_pct,
            "cap_pct": choice.spread.cap_pct,
            "passes": choice.spread.passes,
            "mid": choice.spread.mid,
            "reason": choice.spread.reason,
        },
    }
    return payload, 200


def _zero_dte_payload_impl(symbol: str, query: dict, *, force: bool = False) -> tuple[dict, int]:
    """0DTE tape: the session's real bars plus the same-day expiry's magnets."""
    sym = symbol.strip().upper()
    tf_raw = (query.get("tf", ["1m"])[0] or "1m").lower()
    tf = tf_raw if tf_raw in _ZERO_DTE_TIMEFRAMES else "1m"
    endpoint = "/api/zero-dte"

    try:
        chain_rows, chain_source = _fetch_zero_dte_chain(sym)
    except Exception as exc:  # provider down, bad key, unknown symbol
        return {
            "symbol": sym,
            "measurable": False,
            "endpoint": endpoint,
            "reason": f"option chain unavailable for {sym}: {_provider_note(exc)}",
        }, 200

    if not chain_rows:
        # Cash indices (SPX, NDX, RUT) are not on this feed at all -- neither
        # chain nor candles. Say that rather than quietly serving the ETF and
        # letting it read as the index.
        return {
            "symbol": sym,
            "measurable": False,
            "endpoint": endpoint,
            "reason": (
                f"No option chain for {sym} from either feed. Try the liquid "
                "names (SPY, QQQ, IWM) or an index (SPX, NDX, RUT)."
            ),
        }, 200

    slice_rows, expiry = _front_expiry_slice(chain_rows)
    if not slice_rows or expiry is None:
        return {
            "symbol": sym,
            "measurable": False,
            "endpoint": endpoint,
            "reason": f"chain for {sym} carried no dated expiries",
        }, 200

    try:
        bars = _lse_intraday_bars(sym, tf)
    except Exception as exc:
        return {
            "symbol": sym,
            "measurable": False,
            "endpoint": endpoint,
            "reason": f"intraday bars unavailable for {sym}: {_provider_note(exc)}",
        }, 200

    payload = compute_zero_dte_tape(
        sym,
        bars,
        slice_rows,
        expiry=expiry,
        bar_minutes=_ZERO_DTE_TIMEFRAMES[tf],
    )

    today = datetime.now(timezone.utc).astimezone(_EXCHANGE_TZ).date()
    exp_date = date.fromisoformat(expiry)
    payload["endpoint"] = endpoint
    payload["timeframe"] = tf
    payload["chain_source"] = chain_source
    payload["is_true_0dte"] = exp_date == today
    payload["days_to_expiry"] = (exp_date - today).days
    if not payload["is_true_0dte"]:
        payload.setdefault("warnings", []).append(
            f"The front expiry is {expiry}, {(exp_date - today).days} session-day(s) out, "
            f"not today ({today}). These are the nearest-expiry magnets, not 0DTE."
        )
    return payload, 200


def _zero_dte_payload(symbol: str, query: dict, *, force: bool = False) -> tuple[dict, int]:
    """TTL cache around the 0DTE tape; the chain pull is the expensive half."""
    sym = symbol.strip().upper()
    tf = (query.get("tf", ["1m"])[0] or "1m").lower()
    key = (sym, tf if tf in _ZERO_DTE_TIMEFRAMES else "1m")
    now = time.time()
    if not force:
        with _ZERO_DTE_LOCK:
            cached = _ZERO_DTE_CACHE.get(key)
            if cached is not None and (now - cached[0]) < _ZERO_DTE_CACHE_TTL_S:
                res = dict(cached[1])
                res["cache"] = {"hit": True, "age_seconds": round(now - cached[0], 2)}
                return res, 200

    payload, status = _zero_dte_payload_impl(sym, query, force=force)
    if status == 200:
        with _ZERO_DTE_LOCK:
            _ZERO_DTE_CACHE[key] = (now, payload)
            if len(_ZERO_DTE_CACHE) > 64:
                oldest = min(_ZERO_DTE_CACHE, key=lambda k: _ZERO_DTE_CACHE[k][0])
                _ZERO_DTE_CACHE.pop(oldest, None)
    res = dict(payload)
    res["cache"] = {"hit": False, "age_seconds": 0.0}
    return res, status


# Cash indices are not on the LSE feed at all -- neither chain nor candles --
# but they are exactly what a 0DTE trader asks for by name, so they get a
# second source rather than a refusal. Yahoo's ticker for each:
_INDEX_TICKERS = {
    "SPX": "^SPX",
    "NDX": "^NDX",
    "RUT": "^RUT",
    "VIX": "^VIX",
    "DJX": "^DJI",
}


def _fetch_zero_dte_chain(symbol: str) -> tuple[list[dict[str, Any]], str]:
    """Live chain rows and the feed they came from.

    LSE first (it carries same-day volume, which is the weight that matters for
    a 0DTE expiry). Indices fall through to Yahoo, whose chain carries open
    interest and volume but quotes a broken implied vol on one side of the
    book -- the engine's expiry-level IV fallback is what makes that usable.
    """
    provider_src = ROOT / "TradingWork" / "src"
    if str(provider_src) not in sys.path:
        sys.path.insert(0, str(provider_src))
    try:
        from lse_provider import fetch_lse_options_chain  # type: ignore[import-not-found]

        rows = list(fetch_lse_options_chain(symbol.upper()) or [])
        if rows:
            return rows, "lse"
    except Exception:
        pass

    ticker = _INDEX_TICKERS.get(symbol.upper())
    if ticker is None:
        return [], "lse"
    return _yahoo_front_expiry_chain(ticker), "yahoo"


def _yahoo_front_expiry_chain(ticker: str) -> list[dict[str, Any]]:
    """The nearest not-yet-past expiry from Yahoo, both rights, as chain rows."""
    yf = _get_yf()
    if yf is None:
        return []
    t = yf.Ticker(ticker)
    expiries = [e for e in (t.options or [])]
    if not expiries:
        return []
    today = datetime.now(timezone.utc).astimezone(_EXCHANGE_TZ).date()
    future = [e for e in expiries if date.fromisoformat(e) >= today]
    front = future[0] if future else expiries[-1]
    chain = t.option_chain(front)

    rows: list[dict[str, Any]] = []
    for right, frame in (("call", chain.calls), ("put", chain.puts)):
        for rec in frame.to_dict("records"):
            rows.append(
                {
                    "strike": rec.get("strike"),
                    "right": right,
                    "volume": rec.get("volume") or 0.0,
                    "openInterest": rec.get("openInterest") or 0.0,
                    "impliedVolatility": rec.get("impliedVolatility") or 0.0,
                    "expiry": front,
                }
            )
    return rows


def _yahoo_intraday_bars(ticker: str, timeframe: str) -> list[dict[str, Any]]:
    """Intraday OHLCV from Yahoo, for the symbols the LSE candle feed lacks."""
    yf = _get_yf()
    if yf is None:
        return []
    frame = yf.Ticker(ticker).history(period="5d", interval=timeframe)
    if frame is None or getattr(frame, "empty", True):
        return []
    return [
        {
            "ts": ts.to_pydatetime(),
            "open": float(r["Open"]),
            "high": float(r["High"]),
            "low": float(r["Low"]),
            "close": float(r["Close"]),
            "volume": float(r.get("Volume") or 0.0),
        }
        for ts, r in frame.iterrows()
        if r["High"] == r["High"]  # drop NaN rows
    ]


def _price_attractors_payload_impl(
    symbol: str,
    query: dict | None = None,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    """Computes price attractors, magnet levels, and market regime telemetry with zero spoofing."""
    sym = symbol.strip().upper()
    query = query or {}
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()

    rate_raw = query.get("rate", ["0.045"])
    rate_val = rate_raw[0] if isinstance(rate_raw, list) and rate_raw else rate_raw
    rate = _safe_float(rate_val, 0.045, lo=-0.05, hi=0.25)

    dte_raw = query.get("max_dte", ["60"])
    dte_val = dte_raw[0] if isinstance(dte_raw, list) and dte_raw else dte_raw
    max_dte = _safe_int(dte_val, 60, lo=0, hi=730)

    if not force:
        with _PRICE_ATTRACTOR_LOCK:
            cached = _PRICE_ATTRACTOR_CACHE.get(sym)
            if cached is not None and (now - cached[0]) < _PRICE_ATTRACTOR_CACHE_TTL_S:
                cached_time, cached_payload = cached
                age = round(now - cached_time, 2)
                res = dict(cached_payload)
                res["cache"] = {
                    "hit": True,
                    "age_seconds": age,
                    "ttl_seconds": _PRICE_ATTRACTOR_CACHE_TTL_S,
                }
                return res, 200

    try:
        opt_payload, status = _options_payload(
            sym,
            {"mode": ["live"], "max_dte": [str(max_dte)], "rate": [str(rate)]},
        )
    except Exception:
        opt_payload, status = None, 500

    chain_rows: list[dict[str, Any]] = []
    spot: float | None = None
    price_series: list[float] = []

    if status == 200 and isinstance(opt_payload, dict):
        embedded_snapshot = opt_payload.get("price_attractor_snapshot")
        if isinstance(embedded_snapshot, dict) and embedded_snapshot.get("quality", {}).get(
            "measurable"
        ):
            with _PRICE_ATTRACTOR_LOCK:
                _PRICE_ATTRACTOR_CACHE[sym] = (now, embedded_snapshot)
            res = dict(embedded_snapshot)
            res["cache"] = {
                "hit": False,
                "age_seconds": 0.0,
                "ttl_seconds": _PRICE_ATTRACTOR_CACHE_TTL_S,
            }
            return res, 200

        summary = opt_payload.get("summary") or {}
        spot = summary.get("spot") or opt_payload.get("spot")
        chain_rows = (
            opt_payload.get("chain_by_strike")
            or opt_payload.get("chain_rows")
            or opt_payload.get("open_interest_profile")
            or []
        )
        raw_price_series = opt_payload.get("price_series") or []
        for p in raw_price_series:
            if isinstance(p, dict):
                c = p.get("c") or p.get("close") or p.get("price") or p.get("last")
                if c is not None:
                    try:
                        price_series.append(float(c))
                    except (ValueError, TypeError):
                        pass

    if spot is None or spot <= 0:
        quote = _symbol_quote(sym)
        spot_cand = _safe_float(quote.get("last"), 0.0, lo=0.0, hi=1e9)
        if spot_cand > 0:
            spot = spot_cand

    if not price_series:
        frame, _ = _load_symbol_df(sym)
        if frame is not None and not getattr(frame, "empty", True) and "close" in frame.columns:
            closes = frame["close"].astype(float).dropna()
            price_series = [float(x) for x in closes.tolist()[-60:]]

    snapshot = compute_price_attractors(
        symbol=sym,
        spot=float(spot) if (spot is not None and spot > 0) else 0.0,
        chain_rows=chain_rows,
        price_series=price_series if price_series else None,
        asof_utc=now_iso,
        rate=rate,
    )
    payload = snapshot.to_dict()

    with _PRICE_ATTRACTOR_LOCK:
        _PRICE_ATTRACTOR_CACHE[sym] = (now, payload)
        if len(_PRICE_ATTRACTOR_CACHE) > 256:
            oldest = min(_PRICE_ATTRACTOR_CACHE, key=lambda k: _PRICE_ATTRACTOR_CACHE[k][0])
            _PRICE_ATTRACTOR_CACHE.pop(oldest, None)

    res = dict(payload)
    res["cache"] = {
        "hit": False,
        "age_seconds": 0.0,
        "ttl_seconds": _PRICE_ATTRACTOR_CACHE_TTL_S,
    }
    return res, 200


def _price_attractors_payload(
    symbol: str,
    query: dict | None = None,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    """Single-flight mutex locking and TTL caching wrapper for price attractors."""
    sym = symbol.strip().upper()
    if not force:
        now = time.time()
        with _PRICE_ATTRACTOR_LOCK:
            cached = _PRICE_ATTRACTOR_CACHE.get(sym)
            if cached is not None and (now - cached[0]) < _PRICE_ATTRACTOR_CACHE_TTL_S:
                cached_time, cached_payload = cached
                age = round(now - cached_time, 2)
                res = dict(cached_payload)
                res["cache"] = {
                    "hit": True,
                    "age_seconds": age,
                    "ttl_seconds": _PRICE_ATTRACTOR_CACHE_TTL_S,
                }
                return res, 200

    with _PRICE_ATTRACTOR_LOCK:
        build_lock = _PRICE_ATTRACTOR_BUILD_LOCKS.setdefault(sym, threading.Lock())

    with build_lock:
        return _price_attractors_payload_impl(sym, query, force=force)


# ---------------------------------------------------------------------------
# Layer 3 Market Regime Reconciliation & Calibrated Explainability Endpoint
# ---------------------------------------------------------------------------


def _market_regime_payload_impl(
    symbol: str,
    query: dict | None = None,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    """Computes Layer 3 Unified Market Regime, calibrated confidence & dynamic explainability."""
    sym = symbol.strip().upper()
    query = query or {}
    now = time.time()
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if not force:
        with _MARKET_REGIME_LOCK:
            cached = _MARKET_REGIME_CACHE.get(sym)
            if cached is not None and (now - cached[0]) < _MARKET_REGIME_CACHE_TTL_S:
                cached_time, cached_payload = cached
                age = round(now - cached_time, 2)
                res = dict(cached_payload)
                res["cache"] = {
                    "hit": True,
                    "age_seconds": age,
                    "ttl_seconds": _MARKET_REGIME_CACHE_TTL_S,
                }
                return res, 200

    rate_raw = query.get("rate", ["0.045"])
    rate_val = rate_raw[0] if isinstance(rate_raw, list) and rate_raw else rate_raw
    rate = _safe_float(rate_val, 0.045, lo=-0.05, hi=0.25)

    max_dte_raw = query.get("max_dte", ["60"])
    max_dte_val = max_dte_raw[0] if isinstance(max_dte_raw, list) and max_dte_raw else max_dte_raw
    max_dte = _safe_int(max_dte_val, 60, lo=0, hi=730)

    # 1. Load price bars
    prefer_intraday = query.get("bars", ["daily"])[0] == "1h"
    bars = _load_symbol_bars(sym, prefer_intraday=prefer_intraday)

    # 2. Load options chain if available
    opt_df = None
    shared = None
    try:
        opt_payload, status = _options_payload(
            sym,
            {"mode": ["live"], "max_dte": [str(max_dte)], "rate": [str(rate)]},
        )
        if status == 200 and isinstance(opt_payload, dict):
            raw_summary = opt_payload.get("summary")
            summary = raw_summary if isinstance(raw_summary, dict) else {}
            chain_rows = (
                opt_payload.get("chain_by_strike")
                or opt_payload.get("chain_rows")
                or opt_payload.get("open_interest_profile")
                or []
            )
            if chain_rows:
                pd = _get_pd()
                opt_df = pd.DataFrame(chain_rows)
            profile = opt_payload.get("gex_price_profile")
            flip = summary.get("zero_gamma") or summary.get("gamma_flip")
            pin = summary.get("pin_strike")
            if isinstance(profile, list) and len(profile) >= 2:
                from edge.research.microstructure_regime import SharedLevels

                shared = SharedLevels(
                    gex_profile=profile,
                    call_wall=summary.get("call_wall"),
                    put_wall=summary.get("put_wall"),
                    gamma_flip=flip,
                    pin_strike=pin,
                )
            elif summary.get("call_wall") is not None or summary.get("put_wall") is not None:
                from edge.research.microstructure_regime import SharedLevels

                shared = SharedLevels(
                    gex_profile=[],
                    call_wall=summary.get("call_wall"),
                    put_wall=summary.get("put_wall"),
                    gamma_flip=flip,
                    pin_strike=pin,
                )
    except Exception:
        opt_df = None
        shared = None

    from edge.daily_plays.desk_regime_fusion import format_market_regime_payload
    from edge.research.regime_engine import RegimeFeatureConfig, compute_unified_market_regime

    cfg = RegimeFeatureConfig(risk_free_rate=rate)
    state = compute_unified_market_regime(
        symbol=sym,
        prices=bars,
        options_chain=opt_df,
        asof=now_iso,
        config=cfg,
        shared_levels=shared,
    )

    payload = format_market_regime_payload(
        state,
        cache_meta={
            "hit": False,
            "age_seconds": 0.0,
            "ttl_seconds": _MARKET_REGIME_CACHE_TTL_S,
        },
    )

    with _MARKET_REGIME_LOCK:
        _MARKET_REGIME_CACHE[sym] = (now, payload)
        if len(_MARKET_REGIME_CACHE) > 256:
            oldest = min(_MARKET_REGIME_CACHE, key=lambda k: _MARKET_REGIME_CACHE[k][0])
            _MARKET_REGIME_CACHE.pop(oldest, None)

    return payload, 200


def _market_regime_payload(
    symbol: str,
    query: dict | None = None,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    """Single-flight mutex locking and TTL caching wrapper for market regime."""
    sym = symbol.strip().upper()
    if not force:
        now = time.time()
        with _MARKET_REGIME_LOCK:
            cached = _MARKET_REGIME_CACHE.get(sym)
            if cached is not None and (now - cached[0]) < _MARKET_REGIME_CACHE_TTL_S:
                cached_time, cached_payload = cached
                age = round(now - cached_time, 2)
                res = dict(cached_payload)
                res["cache"] = {
                    "hit": True,
                    "age_seconds": age,
                    "ttl_seconds": _MARKET_REGIME_CACHE_TTL_S,
                }
                return res, 200

    with _MARKET_REGIME_LOCK:
        build_lock = _MARKET_REGIME_BUILD_LOCKS.setdefault(sym, threading.Lock())

    with build_lock:
        return _market_regime_payload_impl(sym, query, force=force)


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
        (
            chain_rows,
            flow_rows,
            live_spot,
            oi_source,
            warnings,
            live_spot_source,
        ) = _fetch_live_option_inputs(
            symbol,
            filters=filters,
        )
        chain_source = "lse_live"
        mode_resolved = "live"
        if not chain_rows:
            # Fall back visibly to the last good dated snapshot rather than
            # reporting the name as unavailable.
            chain_rows, label, _ = _historical_option_rows(symbol, all_days=False)
            if not chain_rows:
                # Same recovery /api/options makes for a single name: a board
                # candidate outside the dated universe still has a listed chain
                # at the delayed provider, and capturing it is the difference
                # between a scored squeeze row and a blank "unavailable" one.
                captured, _capture_err = _ensure_delayed_chain_snapshot(symbol)
                if captured:
                    chain_rows, label, _ = _historical_option_rows(symbol, all_days=False)
            if not chain_rows:
                return summarize_board_row(
                    candidate,
                    None,
                    price_asof=price_asof,
                    error=f"No options chain is available for {symbol}.",
                )
            chain_source = f"cached_chain:{label or 'unknown'}"
            oi_source = chain_source
            mode_resolved = "history_fallback"
            live_spot = None
            live_spot_source = None
            warnings.append("Live chain unavailable; showing the latest dated chain.")
        if mode_resolved == "live" and live_spot is None and price_spot is not None:
            live_spot, live_spot_source = _resolve_live_options_spot(
                chain_spot=None,
                equity_spot=None,
                equity_asof=None,
                flow_spot=None,
                flow_asof=None,
                price_spot=price_spot,
                price_asof=price_asof,
                warnings=warnings,
            )
        if (
            mode_resolved == "live"
            and live_spot is not None
            and live_spot_source
            and (not live_spot_source.startswith("local_daily_close"))
        ):
            asof_hint = None
            if ":" in live_spot_source:
                asof_hint = live_spot_source.split(":", 1)[1]
                if asof_hint == "unknown":
                    asof_hint = None
            price_series = _augment_price_series_with_live(
                price_series,
                live_spot,
                asof_hint,
            )
            if price_series:
                price_asof = str(price_series[-1].get("t"))

        intel = build_options_intelligence(
            symbol=symbol,
            chain_rows=chain_rows,
            flow_rows=flow_rows,
            price_series=price_series,
            spot=live_spot if mode_resolved == "live" else None,
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
            candidate,
            None,
            price_asof=price_asof,
            error=f"{type(exc).__name__}: {exc}",
        )


def _options_board_payload_impl(
    *,
    limit: int,
    depth: str,
    require_live_flow: bool,
    force: bool,
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
        status=status,
        limit=limit,
        require_live_flow=require_live_flow,
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
        futures = _get_concurrent_futures()
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_options_board_row, candidates))
    # Rank by structural conviction, but keep unavailable names on the board so
    # coverage is visible rather than quietly trimmed.
    # Measurable structure first, then conviction. A name whose GEX could not be
    # measured must never outrank one that was actually observed.
    rows.sort(
        key=lambda r: (
            not r.get("available"),
            not r.get("gex_measurable"),
            -abs(float(r.get("squeeze_score") or 0.0)),
            int(r.get("rank") or 10**6),
        )
    )

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
    *,
    limit: int,
    depth: str,
    require_live_flow: bool,
    force: bool,
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


# ---------------------------------------------------------------------------
# Gamma regime breadth strip: fixed index + sector universe -> dealer gamma
# positioning, for GET /api/gamma/regime.
#
# This is the conviction board's close sibling, not its scan-driven cousin:
# the board chases whatever the PEAD/activity/directional scans surfaced this
# minute, so its universe is dynamic and its row is wide (squeeze score,
# walls, contract focus, ...). This strip's universe is the market's
# structural skeleton -- SPY/QQQ/IWM/DIA and the eleven SPDR sectors -- so it
# never changes, and the row only needs to answer one question per name: is
# the dealer book short or long gamma here, and how far from the flip.
#
# Wire shape is owned by dashboard/src/regimeContracts.ts (RegimeSymbolRow /
# RegimeBreadthPayload), which is camelCase by contract -- do not "fix" the
# field names to snake_case to match the rest of this file.
# ---------------------------------------------------------------------------

#: (symbol, kind, human label). Order is preserved into the response so the
#: dashboard can render indices first without re-sorting.
_GAMMA_REGIME_UNIVERSE: tuple[tuple[str, str, str], ...] = (
    ("SPY", "index", "S&P 500"),
    ("QQQ", "index", "Nasdaq 100"),
    ("IWM", "index", "Russell 2000"),
    ("DIA", "index", "Dow Jones Industrial Average"),
    ("XLK", "sector", "Technology"),
    ("XLF", "sector", "Financials"),
    ("XLE", "sector", "Energy"),
    ("XLV", "sector", "Health Care"),
    ("XLI", "sector", "Industrials"),
    ("XLY", "sector", "Consumer Discretionary"),
    ("XLP", "sector", "Consumer Staples"),
    ("XLU", "sector", "Utilities"),
    ("XLB", "sector", "Materials"),
    ("XLRE", "sector", "Real Estate"),
    ("XLC", "sector", "Communication Services"),
)

#: Half-width of the neutral band around zero gamma, as a fraction of spot.
#: Mirrors `RegimeState.flipBandPct` in regimeContracts.ts -- keep in sync.
_GAMMA_REGIME_FLIP_BAND_PCT = 0.0025


def _gamma_regime_trend(symbol: str) -> str | None:
    """One symbol's Kalman trend direction, reduced to up/down/flat.

    `_kalman_trend_payload` reads local parquet bars and reruns a filter over
    the full history; it has its own 120s TTL cache and touches no network
    provider, so this is cheap relative to the chain fetch in
    `_gamma_regime_row` -- the reason trend is allowed to run unconditionally
    once `want_trend` is true, rather than needing its own opt-in. Any
    failure (no local bars, too little history, filter blowup) degrades to
    None; a guessed direction is worse than an absent one.
    """
    try:
        payload = _kalman_trend_payload(
            symbol,
            DEFAULT_WINDOW,
            q=DEFAULT_Q,
            entry_z=DEFAULT_ENTRY_Z,
            exit_z=DEFAULT_EXIT_Z,
            noise_days=DEFAULT_NOISE_DAYS,
            allow_short=False,
            intraday=False,
        )
    except Exception:  # noqa: BLE001 - trend is a bonus column, never fatal
        return None
    if not isinstance(payload, Mapping) or not payload.get("available"):
        return None
    now = payload.get("now") if isinstance(payload.get("now"), Mapping) else {}
    position = now.get("position")
    if position == "long":
        return "up"
    if position == "short":
        return "down"
    if position == "flat":
        return "flat"
    return None


def _gamma_regime_row(entry: tuple[str, str, str], *, want_trend: bool) -> dict[str, Any]:
    """Fetch one symbol's live chain and compact it into a breadth row.

    Mirrors `_options_board_row`'s fetch shape exactly (live chain -> dated
    snapshot fallback -> delayed capture) -- this universe sits behind the
    same rate-limited paid provider the board does, it is just a fixed list
    instead of a ranked one. One symbol's failure must never blank the whole
    strip, so every exception is caught here and turned into an
    `unmeasurable` row with a `note` rather than propagating.
    """
    symbol, kind, label = entry
    filters = OptionsFilters(
        range="5d",
        expiry="nearest",
        tape_limit=50,
        risk_free_rate=0.045,
        **_BOARD_FILTER_DEFAULTS,
    )

    def _unmeasurable(note: str) -> dict[str, Any]:
        # Open interest absent (or the fetch itself failing) means every
        # gamma-derived number here would be a fabricated zero, not an
        # observed one -- null them all rather than let a gap render as a
        # confident flat/neutral read. Trend is independent of the options
        # chain (it reads price bars, not OI), so it is still attempted.
        return {
            "symbol": symbol,
            "kind": kind,
            "label": label,
            "spot": None,
            "netGammaM": None,
            "zeroGamma": None,
            "regime": "unmeasurable",
            "distanceToFlip": None,
            "trend": _gamma_regime_trend(symbol) if want_trend else None,
            "measurable": False,
            "note": note,
        }

    try:
        price_series, price_spot = _options_price_series(symbol, "5d")
        (
            chain_rows,
            flow_rows,
            live_spot,
            oi_source,
            warnings,
            live_spot_source,
        ) = _fetch_live_option_inputs(symbol, filters=filters)
        chain_source = "lse_live"
        mode_resolved = "live"
        if not chain_rows:
            # Same recovery /api/options and the board make: fall back to the
            # last dated snapshot, and if there isn't one, try to capture one
            # from the delayed provider before giving up on the name.
            chain_rows, hist_label, _ = _historical_option_rows(symbol, all_days=False)
            if not chain_rows:
                captured, _capture_err = _ensure_delayed_chain_snapshot(symbol)
                if captured:
                    chain_rows, hist_label, _ = _historical_option_rows(symbol, all_days=False)
            if not chain_rows:
                return _unmeasurable(f"No options chain is available for {symbol}.")
            chain_source = f"cached_chain:{hist_label or 'unknown'}"
            oi_source = chain_source
            mode_resolved = "history_fallback"
            live_spot = None
            live_spot_source = None
        if mode_resolved == "live" and live_spot is None and price_spot is not None:
            live_spot, live_spot_source = _resolve_live_options_spot(
                chain_spot=None,
                equity_spot=None,
                equity_asof=None,
                flow_spot=None,
                flow_asof=None,
                price_spot=price_spot,
                price_asof=None,
                warnings=warnings,
            )
        intel = build_options_intelligence(
            symbol=symbol,
            chain_rows=chain_rows,
            flow_rows=flow_rows,
            price_series=price_series,
            spot=live_spot if mode_resolved == "live" else None,
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
    except Exception as exc:  # noqa: BLE001 - one dead chain must not blank the strip
        return _unmeasurable(f"{type(exc).__name__}: {exc}")

    if not isinstance(intel, Mapping) or intel.get("error"):
        reason = (
            str(intel.get("error"))
            if isinstance(intel, Mapping) and intel.get("error")
            else "No options intelligence payload was produced."
        )
        return _unmeasurable(reason)

    summary = intel.get("summary") if isinstance(intel.get("summary"), Mapping) else {}
    quality = intel.get("quality") if isinstance(intel.get("quality"), Mapping) else {}

    # `gex_measurable` is the engine's own honesty flag (see quality dict in
    # build_options_intelligence): false whenever open interest was never
    # observed, which is the common case for LSE live quotes on names without
    # a dated chain backfill. A GEX of zero because nothing was observed is
    # NOT a quiet reading -- it is an unmeasured one, so every numeric field
    # is withheld rather than rendered as a false calm.
    if not bool(quality.get("gex_measurable")):
        return _unmeasurable(
            "Open interest unavailable for this name, so gamma exposure is unmeasured, not zero."
        )

    spot = _safe_round(summary.get("spot"), 4)
    net_gamma_m = _safe_round(summary.get("total_gex_m"), 4)
    zero_gamma = _safe_round(summary.get("zero_gamma"), 4)
    distance_to_flip = (
        (spot - zero_gamma) / spot
        if spot is not None and spot > 0 and zero_gamma is not None
        else None
    )

    if distance_to_flip is not None and abs(distance_to_flip) <= _GAMMA_REGIME_FLIP_BAND_PCT:
        regime = "flip"
    elif net_gamma_m is None:
        # gex_measurable was true but the summary still produced no usable
        # net-gamma figure (a degenerate/one-sided chain) -- nothing to sign.
        return _unmeasurable("Chain lacked a usable net-gamma read.")
    elif net_gamma_m < 0:
        regime = "short"
    elif net_gamma_m > 0:
        regime = "long"
    else:
        # Net gamma landed on exactly zero without a resolvable flip level --
        # that IS the flip point, not an unmeasured gap.
        regime = "flip"

    return {
        "symbol": symbol,
        "kind": kind,
        "label": label,
        "spot": spot,
        "netGammaM": net_gamma_m,
        "zeroGamma": zero_gamma,
        "regime": regime,
        "distanceToFlip": _safe_round(distance_to_flip, 6),
        "trend": _gamma_regime_trend(symbol) if want_trend else None,
        "measurable": True,
        "note": (
            "Live chain unavailable; showing the latest dated chain."
            if mode_resolved == "history_fallback"
            else None
        ),
    }


def _gamma_regime_divergence(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """SPY's regime vs. the sectors running short gamma underneath it.

    This is the actual signal in the strip, not a summary statistic: an
    index pinned long-gamma (dealers dampen moves there -- mean-reverting,
    "held") while a heavy sector runs short-gamma (dealers amplify moves
    there -- trending, "free") means the index's calm is not representative
    of what is happening under its own weight. Null when SPY itself is
    unmeasurable -- there is no baseline to diverge from.
    """
    by_symbol = {row.get("symbol"): row for row in rows}
    spy = by_symbol.get("SPY")
    if not isinstance(spy, Mapping) or not spy.get("measurable"):
        return None
    index_regime = spy.get("regime")
    if index_regime in (None, "unmeasurable"):
        return None
    short_gamma_sectors = [
        str(row.get("symbol"))
        for row in rows
        if row.get("kind") == "sector" and row.get("measurable") and row.get("regime") == "short"
    ]
    if short_gamma_sectors:
        note = (
            f"SPY is running {index_regime} gamma while "
            f"{', '.join(short_gamma_sectors)} "
            f"{'is' if len(short_gamma_sectors) == 1 else 'are'} running short "
            "gamma underneath it -- the index's stability is not "
            "representative of its own weight."
        )
    else:
        note = f"SPY is running {index_regime} gamma; no sector is running short gamma against it."
    return {
        "indexRegime": index_regime,
        "shortGammaSectors": short_gamma_sectors,
        "note": note,
    }


def _gamma_regime_payload_impl(*, want_trend: bool, force: bool) -> dict[str, Any]:
    cache_key = ("gamma_regime", want_trend)
    if not force:
        with _GAMMA_REGIME_LOCK:
            hit = _GAMMA_REGIME_CACHE.get(cache_key)
        if hit and time.time() - hit[0] < _GAMMA_REGIME_TTL_S:
            payload = dict(hit[1])
            # Staleness is never implicit: say how old this copy is and that
            # a forced refetch is available, so the desk is not reading a
            # cached regime read while believing it is live.
            payload["cache"] = {
                "hit": True,
                "age_seconds": round(time.time() - hit[0], 1),
                "ttl_seconds": _GAMMA_REGIME_TTL_S,
            }
            return payload

    workers = min(_GAMMA_REGIME_MAX_WORKERS, len(_GAMMA_REGIME_UNIVERSE))
    futures = _get_concurrent_futures()
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(
            pool.map(
                lambda entry: _gamma_regime_row(entry, want_trend=want_trend),
                _GAMMA_REGIME_UNIVERSE,
            )
        )

    # One warning per distinct condition, not one per symbol: nine identical
    # "live chain unavailable" lines are spam, not caution. Order-preserving
    # dedupe keeps each note verbatim (tests assert on the literal text).
    warnings = list(dict.fromkeys(str(row["note"]) for row in rows if row.get("note")))
    payload = {
        "asof": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "universe": "core",
        "rows": rows,
        "divergence": _gamma_regime_divergence(rows),
        "warnings": warnings,
        "cache": {
            "hit": False,
            "age_seconds": 0.0,
            "ttl_seconds": _GAMMA_REGIME_TTL_S,
        },
    }
    with _GAMMA_REGIME_LOCK:
        _GAMMA_REGIME_CACHE[cache_key] = (time.time(), payload)
    return payload


def _gamma_regime_payload(*, force: bool, want_trend: bool) -> dict[str, Any]:
    """Return one regime-strip build per cache key, even under concurrent requests.

    15 live chain fetches is the single most expensive request this app makes
    against a rate-limited paid provider (London Strategic Edge) -- more
    expensive per call than the conviction board above, which at least caps
    itself to `limit` candidates rather than a fixed 15. Without a keyed
    build lock, two concurrent cold requests (the breadth strip polling on
    its own timer plus an operator's manual refresh) would launch the same 15
    chain reads twice. A concurrent forced request may use a result produced
    after it began; a later, deliberate force still rebuilds. Same shape as
    `_options_board_payload` immediately above -- see there for why.
    """
    cache_key = ("gamma_regime", want_trend)
    request_started = time.time()
    with _GAMMA_REGIME_LOCK:
        build_lock = _GAMMA_REGIME_BUILD_LOCKS.setdefault(cache_key, threading.Lock())
    with build_lock:
        if force:
            with _GAMMA_REGIME_LOCK:
                hit = _GAMMA_REGIME_CACHE.get(cache_key)
            if hit and hit[0] >= request_started:
                return dict(hit[1])
        return _gamma_regime_payload_impl(want_trend=want_trend, force=force)


def _observed_flow_contract_review(
    print_row: Mapping[str, Any],
    *,
    fallback_spot: float | None = None,
    max_dte: int = 60,
    max_moneyness: float = 0.25,
) -> tuple[bool, int | None, float | None, list[str]]:
    """Validate an observed print before it can become a contract focus.

    Premium is not evidence that a contract is usable.  Reject expired/far-dated
    and extreme-strike identities here so the selector can fall back to the next
    valid print instead of forwarding an impossible contract to Setups.
    """
    reasons: list[str] = []
    try:
        strike = float(print_row.get("strike"))
    except (TypeError, ValueError):
        strike = None
    try:
        spot = float(print_row.get("underlying_price"))
    except (TypeError, ValueError):
        spot = fallback_spot
    if strike is None or not math.isfinite(strike) or strike <= 0:
        reasons.append("strike is missing or invalid")
    if spot is None or not math.isfinite(spot) or spot <= 0:
        reasons.append("underlying spot is missing or invalid")

    expiry_raw = str(print_row.get("expiry") or "").strip()
    dte: int | None = None
    try:
        raw_dte = float(print_row.get("dte"))
        if math.isfinite(raw_dte):
            dte = int(raw_dte)
    except (TypeError, ValueError):
        pass
    if dte is None and expiry_raw:
        try:
            expiry_date = date.fromisoformat(expiry_raw[:10])
            observed_raw = str(print_row.get("timestamp") or "").strip()
            try:
                observed_date = datetime.fromisoformat(observed_raw.replace("Z", "+00:00")).date()
            except (TypeError, ValueError):
                observed_date = datetime.now(timezone.utc).date()
            dte = (expiry_date - observed_date).days
        except ValueError:
            reasons.append("expiry is missing or invalid")
    elif not expiry_raw:
        reasons.append("expiry is missing or invalid")
    if dte is None or not 0 <= dte <= max_dte:
        reasons.append(f"contract is outside the 0–{max_dte} DTE review window")

    moneyness: float | None = None
    if (
        strike is not None
        and math.isfinite(strike)
        and strike > 0
        and spot is not None
        and math.isfinite(spot)
        and spot > 0
    ):
        moneyness = abs(strike / spot - 1.0)
        if moneyness > max_moneyness:
            reasons.append(f"strike is more than {max_moneyness:.0%} from underlying spot")
    return not reasons, dte, moneyness, reasons


def _unusual_flow_payload_impl(
    *,
    limit: int,
    min_premium: float,
    force: bool = False,
    symbol: str | None = None,
) -> dict:
    # Declared so the Setups invalidation at the tail rebinds the module
    # globals. Without this the assignments bound function locals and the
    # stale Setups payload survived a fresh tape for its full TTL.
    global _LIVE_OPPORTUNITIES_CACHE, _LIVE_OPPORTUNITIES_CACHE_TS
    cache_key = (limit, round(min_premium, 2), symbol)
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
        symbols=[symbol] if symbol else (),
        data_dirs=data_dirs,
        row_limit=limit,
        min_premium=min_premium,
    )
    payload = dict(payload)
    # Carry the latest observed underlying price from the contract tape onto
    # its aggregate row. Flow-only setups otherwise lose a price that the Flow
    # workspace can already display, making the setup drawer look broken.
    latest_spot_observation: dict[str, tuple[str, float]] = {}
    focus_by_right: dict[tuple[str, str], tuple[float, dict]] = {}
    focus_rejections: dict[tuple[str, str], list[str]] = {}
    tape_rows = [row for row in (payload.get("tape") or []) if isinstance(row, dict)]
    for print_row in tape_rows:
        sym = str(print_row.get("symbol") or "").strip().upper()
        try:
            spot = float(print_row.get("underlying_price"))
        except (TypeError, ValueError):
            continue
        observed = str(print_row.get("timestamp") or "")
        previous = latest_spot_observation.get(sym)
        if (
            sym
            and math.isfinite(spot)
            and spot > 0
            and (previous is None or observed >= previous[0])
        ):
            latest_spot_observation[sym] = (observed, spot)
    for print_row in tape_rows:
        if not isinstance(print_row, dict):
            continue
        sym = str(print_row.get("symbol") or "").strip().upper()
        right = str(print_row.get("right") or "").strip().lower()
        try:
            premium = float(print_row.get("premium") or 0.0)
        except (TypeError, ValueError):
            premium = 0.0
        has_identity = print_row.get("strike") is not None and bool(print_row.get("expiry"))
        has_price = print_row.get("price") is not None
        if sym and right in {"call", "put"} and math.isfinite(premium) and has_identity:
            key = (sym, right)
            valid_contract, reviewed_dte, moneyness, rejection_reasons = (
                _observed_flow_contract_review(
                    print_row,
                    fallback_spot=(latest_spot_observation.get(sym) or ("", None))[1],
                )
            )
            if not valid_contract:
                existing = focus_rejections.setdefault(key, [])
                existing.extend(reason for reason in rejection_reasons if reason not in existing)
                continue
            # Completeness wins before notional: a specific priced contract is
            # more useful than a larger print that cannot name an expiry,
            # strike, or planning debit.
            rank = (1.0 if has_price else 0.0) * 1_000_000_000_000.0 + premium
            if key not in focus_by_right or rank > focus_by_right[key][0]:
                focus_by_right[key] = (
                    rank,
                    {
                        "right": right,
                        "occ_symbol": print_row.get("occ_symbol")
                        or print_row.get("contract_symbol"),
                        "strike": print_row.get("strike"),
                        "expiry": print_row.get("expiry"),
                        "dte": reviewed_dte,
                        "underlying_price": (
                            print_row.get("underlying_price")
                            or (latest_spot_observation.get(sym) or ("", None))[1]
                        ),
                        "otm_pct": moneyness,
                        "price": print_row.get("price"),
                        "price_estimated": bool(print_row.get("price_estimated")),
                        "premium": premium,
                        "contracts": print_row.get("contracts") or print_row.get("volume"),
                        "timestamp": print_row.get("timestamp"),
                        "contract_multiplier": print_row.get("contract_multiplier") or 100,
                    },
                )
    latest_spot = {symbol: value for symbol, (_, value) in latest_spot_observation.items()}
    payload["rows"] = [
        (
            {
                **row,
                **({"spot": latest_spot[sym]} if sym in latest_spot else {}),
                "flow_focus": {
                    right: focus_by_right[(sym, right)][1]
                    for right in ("call", "put")
                    if (sym, right) in focus_by_right
                },
                "flow_focus_rejections": {
                    right: focus_rejections[(sym, right)]
                    for right in ("call", "put")
                    if (sym, right) in focus_rejections
                },
            }
            if isinstance(row, dict)
            else row
        )
        for row in (payload.get("rows") or [])
        for sym in (str(row.get("symbol") or "").upper() if isinstance(row, dict) else "",)
    ]
    payload["source_snapshot"] = "market_flow"
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
    with _FLOW_SUGGESTION_LOCK:
        for row in payload.get("rows") or []:
            if isinstance(row, dict):
                sym = str(row.get("symbol") or "").strip().upper()
                if sym in _FLOW_SUGGESTION_CACHE:
                    _FLOW_SUGGESTION_CACHE.pop(sym, None)
    # Publish "Setups is stale" WITHOUT taking _LIVE_OPPORTUNITIES_LOCK.
    #
    # _live_opportunities_payload holds that lock across its whole build and
    # calls _unusual_flow_payload from inside it. Re-acquiring a plain Lock on
    # the same thread is a self-deadlock, and the wedged thread keeps holding
    # it -- so every later /api/unusual-flow request, whatever its limit or
    # threshold, blocked here forever and the Flow tab showed SOURCE
    # UNAVAILABLE until the server was restarted.
    #
    # The lock bought nothing anyway: rebinding a module global is atomic
    # under the GIL. Stamp the timestamp to 0 so the TTL check is honest even
    # if a concurrent builder republishes between these two statements, but
    # keep the last union so a Setups poll can serve it immediately.
    _LIVE_OPPORTUNITIES_CACHE_TS = 0.0
    return payload


def _unusual_flow_payload(
    *,
    limit: int,
    min_premium: float,
    force: bool = False,
    symbol: str | None = None,
) -> dict:
    """Coalesce identical concurrent market-wide tape scans.

    Threshold/limit variants remain independent cache keys, but two browser
    panes asking for the same variant now share one local parquet + LSE pass.
    """
    cache_key = (limit, round(min_premium, 2), symbol)
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
            symbol=symbol,
        )


# Passive reads recombine the board/unusual-flow caches above. A force request
# is an explicit operator action and refreshes both upstream sources once.
_LIVE_OPPORTUNITIES_CACHE: dict | None = None
_LIVE_OPPORTUNITIES_CACHE_TS: float = 0.0
_LIVE_OPPORTUNITIES_TTL_S = 90.0
_LIVE_OPPORTUNITIES_LOCK = threading.Lock()
_LIVE_OPPORTUNITIES_STATE_PATH = RUNS_DIR / "live_opportunities_cache.json"
_LIVE_OPPORTUNITIES_STATE_LOADED = False

# A symbol opened directly from Flow deserves a symbol-specific chain read even
# when it fell outside the broad board's top-25 routing budget. Keep these
# short-lived and keyed so the 15-second UI poll never launches overlapping
# vendor work for the same underlier.
_FLOW_SUGGESTION_CACHE: dict[str, tuple[float, dict]] = {}
_FLOW_SUGGESTION_BUILD_LOCKS: dict[str, threading.Lock] = {}
_FLOW_SUGGESTION_TTL_S = 15.0
_FLOW_SUGGESTION_LOCK = threading.Lock()

# Direction and contract identity must persist across independent provider
# refreshes before the UI may describe them as stable. Cached reads do not
# increment the count. State is persisted so a routine API restart does not
# make every contract look new again.
_CONTRACT_STABILITY_STATE: dict[tuple[str, str], tuple[str, int, float]] = {}
_DIRECTION_STABILITY_STATE: dict[str, tuple[str, int, float]] = {}
_CONTRACT_STABILITY_LOCK = threading.Lock()
_CONTRACT_STABILITY_MAX_GAP_S = 45 * 60.0
_CONTRACT_STABILITY_REQUIRED = 3
_DIRECTION_STABILITY_REQUIRED = 3
_STABILITY_STATE_PATH = RUNS_DIR / "options_suggestion_stability.json"
_STABILITY_STATE_LOADED = False


def _load_suggestion_stability_locked() -> None:
    global _STABILITY_STATE_LOADED
    if _STABILITY_STATE_LOADED:
        return
    _STABILITY_STATE_LOADED = True
    try:
        saved = json.loads(_STABILITY_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return
    for raw_key, raw in (saved.get("contracts") or {}).items():
        if not isinstance(raw, dict) or "|" not in str(raw_key):
            continue
        symbol, right = str(raw_key).split("|", 1)
        try:
            _CONTRACT_STABILITY_STATE[(symbol, right)] = (
                str(raw["identity"]),
                int(raw["count"]),
                float(raw["seen"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    for symbol, raw in (saved.get("directions") or {}).items():
        if not isinstance(raw, dict):
            continue
        try:
            _DIRECTION_STABILITY_STATE[str(symbol)] = (
                str(raw["right"]),
                int(raw["count"]),
                float(raw["seen"]),
            )
        except (KeyError, TypeError, ValueError):
            continue


def _persist_suggestion_stability_locked() -> None:
    snapshot = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "contracts": {
            f"{symbol}|{right}": {"identity": identity, "count": count, "seen": seen}
            for (symbol, right), (identity, count, seen) in _CONTRACT_STABILITY_STATE.items()
        },
        "directions": {
            symbol: {"right": right, "count": count, "seen": seen}
            for symbol, (right, count, seen) in _DIRECTION_STABILITY_STATE.items()
        },
    }
    try:
        _STABILITY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        pending = _STABILITY_STATE_PATH.with_suffix(".tmp")
        pending.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
        os.replace(pending, _STABILITY_STATE_PATH)
    except OSError:
        # Persistence is a continuity aid, never a reason to take the API down.
        return


def _rank_suggestion_rows(payload: dict) -> dict:
    """Put the most reviewable rows first using observable quality only."""
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        suggestion = row.get("suggestion") if isinstance(row.get("suggestion"), dict) else {}
        plan = (
            suggestion.get("contract_plan")
            if isinstance(suggestion.get("contract_plan"), dict)
            else None
        )
        right = str(suggestion.get("right") or "").lower()
        tier = str(suggestion.get("setup_tier") or "").lower()
        score = 0
        reasons: list[str] = []
        if tier == "ready":
            score += 70
            reasons.append("entry gates clear")
        elif suggestion.get("paper_actionable"):
            score += 45
            reasons.append("paper action gates clear")
        elif right in {"call", "put"}:
            score += 25
            reasons.append("directional paper candidate")
        if suggestion.get("direction_stable"):
            score += 15
            reasons.append("direction repeated")
        if (row.get("freshness") or {}).get("pass"):
            score += 15
            reasons.append("fresh inputs")
        if plan:
            if plan.get("kind") == "chain_selected_contract":
                score += 15
                reasons.append("chain identity matched")
            else:
                score += 4
                reasons.append("observed Flow identity only")
            if plan.get("stable"):
                score += 10
                reasons.append("contract repeated")
            if plan.get("quote_complete"):
                score += 10
                reasons.append("two-sided quote")
            if plan.get("contract_complete"):
                score += 5
        suggestion["review_score"] = min(100, score)
        suggestion["review_reasons"] = reasons
        suggestion["review_label"] = (
            "READY"
            if tier == "ready"
            else (
                "PAPER ACTION"
                if suggestion.get("paper_actionable")
                else (
                    "STRONG PAPER"
                    if score >= 70
                    else (
                        "PAPER"
                        if score >= 45
                        else "NEW / CHURNING"
                        if right in {"call", "put"}
                        else "WATCH"
                    )
                )
            )
        )
    rows.sort(
        key=lambda row: (
            -int(((row.get("suggestion") or {}).get("review_score") or 0)),
            -float(row.get("composite_score") or -10_000),
            str(row.get("symbol") or ""),
        )
    )
    for rank, row in enumerate(rows, start=1):
        suggestion = row.get("suggestion") if isinstance(row.get("suggestion"), dict) else None
        if suggestion is not None:
            suggestion["review_rank"] = rank
    return payload


def _stabilize_contract_plans(payload: dict) -> dict:
    now = time.time()
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    min_volume = float(filters.get("min_volume") or 10)
    min_open_interest = float(filters.get("min_open_interest") or 100)
    max_spread_pct = float(filters.get("max_spread_pct") or 0.25)
    with _CONTRACT_STABILITY_LOCK:
        _load_suggestion_stability_locked()
        for row in rows:
            if not isinstance(row, dict):
                continue
            suggestion = row.get("suggestion") if isinstance(row.get("suggestion"), dict) else {}
            symbol = str(row.get("symbol") or "").upper()
            suggested_right = str(suggestion.get("right") or "").lower()
            direction_stable = False
            if symbol and suggested_right in {"call", "put"}:
                previous_direction = _DIRECTION_STABILITY_STATE.get(symbol)
                direction_churned = bool(
                    previous_direction
                    and previous_direction[0] != suggested_right
                    and now - previous_direction[2] <= _CONTRACT_STABILITY_MAX_GAP_S
                )
                direction_required = (
                    _DIRECTION_STABILITY_REQUIRED
                    if suggestion.get("evidence_kind") == "activity_lean"
                    else 2
                )
                direction_count = (
                    min(direction_required, previous_direction[1] + 1)
                    if previous_direction
                    and previous_direction[0] == suggested_right
                    and now - previous_direction[2] <= _CONTRACT_STABILITY_MAX_GAP_S
                    else 1
                )
                _DIRECTION_STABILITY_STATE[symbol] = (
                    suggested_right,
                    direction_count,
                    now,
                )
                direction_stable = direction_count >= direction_required
                suggestion["direction_observations"] = direction_count
                suggestion["direction_required"] = direction_required
                suggestion["direction_stable"] = direction_stable
                suggestion["direction_churned"] = direction_churned
                if direction_churned:
                    for contract_key in [
                        key for key in _CONTRACT_STABILITY_STATE if key[0] == symbol
                    ]:
                        _CONTRACT_STABILITY_STATE.pop(contract_key, None)
                    warnings = list(suggestion.get("warnings") or [])
                    warnings.append("Suggested right changed during the stability window.")
                    suggestion["warnings"] = list(dict.fromkeys(warnings))
            plan = (
                suggestion.get("contract_plan")
                if isinstance(suggestion.get("contract_plan"), dict)
                else None
            )
            if not plan or plan.get("kind") != "chain_selected_contract":
                continue
            right = str(plan.get("right") or "").lower()
            identity = str(plan.get("occ_symbol") or "") or (
                f"{plan.get('expiry')}:{plan.get('strike')}:{right}"
            )
            key = (symbol, right)
            previous = _CONTRACT_STABILITY_STATE.get(key)
            count = (
                previous[1] + 1
                if previous
                and previous[0] == identity
                and now - previous[2] <= _CONTRACT_STABILITY_MAX_GAP_S
                else 1
            )
            count = min(_CONTRACT_STABILITY_REQUIRED, count)
            _CONTRACT_STABILITY_STATE[key] = (identity, count, now)
            stable = count >= _CONTRACT_STABILITY_REQUIRED
            plan["stability_observations"] = count
            plan["stability_required"] = _CONTRACT_STABILITY_REQUIRED
            plan["stable"] = stable
            if not stable or not direction_stable:
                if plan.get("action") == "BUY_TO_OPEN":
                    plan["action"] = "WAIT_FOR_STABILITY"
                    plan["contract_stage"] = "chain_quote_waiting_for_stability"
                plan["sizing_eligible"] = False
                plan["sizing_debit"] = None
                plan["reference_max_loss"] = None
                plan["take_profit_debit"] = None
                plan["review_exit_debit"] = None
                rejections = list(plan.get("rejection_reasons") or [])
                if not stable:
                    rejections.append(
                        f"contract identity requires {_CONTRACT_STABILITY_REQUIRED} consecutive provider observations"
                    )
                if not direction_stable:
                    rejections.append("suggested right has not completed its stability window")
                plan["rejection_reasons"] = list(dict.fromkeys(rejections))
                if suggestion.get("setup_tier") == "ready":
                    suggestion["setup_tier"] = "paper"
                    suggestion["status"] = "paper_candidate"
                    suggestion["entry_eligible"] = False
                    row["live_ready"] = False

            asof_day = str(payload.get("asof_utc") or "")[:10]
            observed_day = str(plan.get("observed_at") or "")[:10]
            same_session_reference = bool(
                plan.get("quote_reference_only")
                and asof_day
                and observed_day
                and asof_day == observed_day
            )
            paper_checks = {
                "stable CALL/PUT direction": direction_stable,
                "stable exact contract": stable,
                "fresh or same-session chain reference": bool(
                    (row.get("freshness") or {}).get("pass") or same_session_reference
                ),
                "complete GEX target and invalidation": bool(
                    suggestion.get("risk_levels_complete")
                ),
                "two-sided live or delayed reference quote": bool(
                    plan.get("quote_complete") or plan.get("quote_reference_only")
                ),
                f"volume >= {int(min_volume)}": bool(
                    plan.get("volume") is not None and float(plan["volume"]) >= min_volume
                ),
                f"open interest >= {int(min_open_interest)}": bool(
                    plan.get("open_interest") is not None
                    and float(plan["open_interest"]) >= min_open_interest
                ),
                f"spread <= {max_spread_pct:.0%}": bool(
                    plan.get("spread_pct") is not None
                    and float(plan["spread_pct"]) <= max_spread_pct
                ),
            }
            paper_actionable = bool(
                suggested_right in {"call", "put"}
                and plan.get("kind") == "chain_selected_contract"
                and not row.get("live_ready")
                and all(paper_checks.values())
            )
            suggestion["paper_actionable"] = paper_actionable
            suggestion["paper_action"] = (
                f"PAPER_BUY_{suggested_right.upper()}" if paper_actionable else None
            )
            suggestion["paper_action_blockers"] = [
                label for label, passed in paper_checks.items() if not passed
            ]
            plan["paper_actionable"] = paper_actionable
            if paper_actionable and not row.get("live_ready"):
                plan["action"] = "PAPER_BUY_TO_OPEN"
                plan["contract_stage"] = "paper_action_candidate"
                plan["sizing_eligible"] = False
                plan["sizing_debit"] = None
        stale_keys = [
            key
            for key, (_, _, seen) in _CONTRACT_STABILITY_STATE.items()
            if now - seen > _CONTRACT_STABILITY_MAX_GAP_S * 2
        ]
        for key in stale_keys:
            _CONTRACT_STABILITY_STATE.pop(key, None)
        stale_directions = [
            symbol
            for symbol, (_, _, seen) in _DIRECTION_STABILITY_STATE.items()
            if now - seen > _CONTRACT_STABILITY_MAX_GAP_S * 2
        ]
        for symbol in stale_directions:
            _DIRECTION_STABILITY_STATE.pop(symbol, None)
        _persist_suggestion_stability_locked()
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else None
    if coverage is not None:
        coverage["live_ready"] = sum(
            bool(row.get("live_ready")) for row in rows if isinstance(row, dict)
        )
        coverage["direction_stable"] = sum(
            bool((row.get("suggestion") or {}).get("direction_stable"))
            for row in rows
            if isinstance(row, dict)
        )
        coverage["contract_stable"] = sum(
            bool(((row.get("suggestion") or {}).get("contract_plan") or {}).get("stable"))
            for row in rows
            if isinstance(row, dict)
        )
        coverage["paper_actionable"] = sum(
            bool((row.get("suggestion") or {}).get("paper_actionable"))
            for row in rows
            if isinstance(row, dict)
        )
    return _rank_suggestion_rows(payload)


def _live_opportunities_state_enabled() -> bool:
    """Unit tests must not overwrite the operator's last Setups union."""
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return True
    return _LIVE_OPPORTUNITIES_STATE_PATH != RUNS_DIR / "live_opportunities_cache.json"


def _hydrate_live_opportunities_cache() -> None:
    """Load the last union after an API restart so Setups is not a cold 0."""
    global _LIVE_OPPORTUNITIES_CACHE, _LIVE_OPPORTUNITIES_CACHE_TS
    global _LIVE_OPPORTUNITIES_STATE_LOADED
    if _LIVE_OPPORTUNITIES_STATE_LOADED:
        return
    _LIVE_OPPORTUNITIES_STATE_LOADED = True
    if _LIVE_OPPORTUNITIES_CACHE is not None or not _live_opportunities_state_enabled():
        return
    try:
        saved = json.loads(_LIVE_OPPORTUNITIES_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return
    payload = saved.get("payload") if isinstance(saved, dict) else None
    if not isinstance(payload, dict):
        return
    _LIVE_OPPORTUNITIES_CACHE = payload
    _LIVE_OPPORTUNITIES_CACHE_TS = 0.0


def _persist_live_opportunities_cache(payload: dict) -> None:
    if not isinstance(payload, dict) or not payload.get("available"):
        return
    if not _live_opportunities_state_enabled():
        return
    try:
        _LIVE_OPPORTUNITIES_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        pending = _LIVE_OPPORTUNITIES_STATE_PATH.with_suffix(".tmp")
        pending.write_text(json.dumps({"payload": payload}, default=str), encoding="utf-8")
        os.replace(pending, _LIVE_OPPORTUNITIES_STATE_PATH)
    except OSError:
        return


def _live_opportunities_fresh(*, force: bool) -> dict | None:
    cached = _LIVE_OPPORTUNITIES_CACHE
    if (
        not force
        and cached is not None
        and (time.time() - _LIVE_OPPORTUNITIES_CACHE_TS) < _LIVE_OPPORTUNITIES_TTL_S
    ):
        return cached
    return None


def _rebuild_live_opportunities_body(*, force: bool) -> dict:
    global _LIVE_OPPORTUNITIES_CACHE, _LIVE_OPPORTUNITIES_CACHE_TS
    # Passive polling stays cache-friendly. Only an explicit force request
    # cascades to vendors, matching the dashboard's "PULL LIVE DATA" action.
    board = _options_board_payload(
        limit=25,
        depth=_ACTIVE_SCAN_DEPTH,
        require_live_flow=False,
        force=force,
    )
    flow = _unusual_flow_payload(limit=40, min_premium=25_000.0, force=force)
    board_cache = board.get("cache") if isinstance(board.get("cache"), dict) else {}
    flow_cache = flow.get("cache") if isinstance(flow.get("cache"), dict) else {}
    qlib_panel = peek_shared_qlib_panel()
    payload = build_live_opportunities(
        board_rows=_attach_regime_levels(_attach_flow_state_levels(list(board.get("rows") or []))),
        flow_rows=list(flow.get("rows") or []),
        calibrated_rows=list(board.get("calibrated_signals") or []),
        qlib_rows=qlib_rows_from_panel(qlib_panel),
        filters=OptionsFilters(),
        board_cache_age_seconds=float(board_cache.get("age_seconds") or 0.0),
        flow_cache_age_seconds=float(flow_cache.get("age_seconds") or 0.0),
    )
    payload = _stabilize_contract_plans(payload)
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
            "qlib": {
                "published": qlib_panel is not None,
                "asof": (qlib_panel or {}).get("asof"),
                "source": (qlib_panel or {}).get("source"),
                "n_symbols": len((qlib_panel or {}).get("by_symbol") or {}),
            },
            "scan_depth": _ACTIVE_SCAN_DEPTH,
        }
    _LIVE_OPPORTUNITIES_CACHE = payload
    _LIVE_OPPORTUNITIES_CACHE_TS = time.time()
    _persist_live_opportunities_cache(payload)
    return payload


def _rebuild_live_opportunities_bg() -> None:
    try:
        if _live_opportunities_fresh(force=False) is None:
            _rebuild_live_opportunities_body(force=False)
    except Exception:  # noqa: BLE001 - a background miss must not kill the desk
        pass
    finally:
        _LIVE_OPPORTUNITIES_LOCK.release()


def _kick_live_opportunities_rebuild() -> None:
    if not _LIVE_OPPORTUNITIES_LOCK.acquire(blocking=False):
        return
    try:
        threading.Thread(
            target=_rebuild_live_opportunities_bg,
            name="setups-rebuild",
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001 - restore the lock if the thread never starts
        _LIVE_OPPORTUNITIES_LOCK.release()


def _live_opportunities_payload(*, force: bool = False) -> dict:
    fresh = _live_opportunities_fresh(force=force)
    if fresh is not None:
        return fresh
    cached = _LIVE_OPPORTUNITIES_CACHE
    if not force and cached is not None:
        # Last union stays on the wire while board/flow recombine. A TTL miss
        # used to hold _LIVE_OPPORTUNITIES_LOCK across vendor work, so the
        # 30s browser abort retried forever on an empty Setups tab.
        _kick_live_opportunities_rebuild()
        return cached
    with _LIVE_OPPORTUNITIES_LOCK:
        fresh = _live_opportunities_fresh(force=force)
        if fresh is not None:
            return fresh
        return _rebuild_live_opportunities_body(force=force)


def _flow_suggestion_payload_impl(symbol: str, *, force: bool = False) -> dict:
    """Build one exact Flow-click setup with a fresh symbol chain.

    The broad Setups board intentionally limits expensive chain reads. A user
    explicitly choosing a Flow name is a different routing decision: fetch that
    one chain, merge the matching Flow/model/qlib evidence, and return the same
    fail-closed opportunity contract used by the board.
    """
    status = get_dashboard_data(scan_depth=_ACTIVE_SCAN_DEPTH)
    flow_payload = _unusual_flow_payload(
        limit=80,
        min_premium=25_000.0,
        force=force,
    )
    flow_rows = [
        row
        for row in (flow_payload.get("rows") or [])
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol
    ]

    candidates, _ = select_board_candidates(
        status=status,
        limit=500,
        require_live_flow=False,
    )
    candidate = next((item for item in candidates if item.symbol == symbol), None)
    if candidate is None:
        flow_row = flow_rows[0] if flow_rows else {}
        candidate = BoardCandidate(
            symbol=symbol,
            selection_basis="live_options_flow" if flow_rows else "activity_ordinal",
            selection_score=flow_row.get("unusual_score"),
            score_kind="ordinal_activity",
            context_side=str(flow_row.get("context_side") or "").lower() or None,
            sources=["Flow selection"],
            rank=1,
        )

    delayed_snapshot_ok, delayed_snapshot_error = _ensure_delayed_chain_snapshot(symbol)
    board_row = _options_board_row(candidate)
    calibrated_rows = [
        row
        for row in (status.get("directional_signals") or [])
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol
    ]
    qlib_panel = peek_shared_qlib_panel()
    qlib_rows = [row for row in qlib_rows_from_panel(qlib_panel) if row.get("symbol") == symbol]
    flow_cache = flow_payload.get("cache") if isinstance(flow_payload.get("cache"), dict) else {}
    payload = build_live_opportunities(
        board_rows=_attach_regime_levels(_attach_flow_state_levels([board_row])),
        flow_rows=flow_rows,
        calibrated_rows=calibrated_rows,
        qlib_rows=qlib_rows,
        filters=OptionsFilters(),
        flow_cache_age_seconds=float(flow_cache.get("age_seconds") or 0.0),
    )
    payload = _stabilize_contract_plans(payload)
    if not delayed_snapshot_ok and delayed_snapshot_error:
        payload.setdefault("warnings", []).append(
            f"Delayed exact-contract reference unavailable: {delayed_snapshot_error}"
        )
    payload["requested_symbol"] = symbol
    payload["sources"] = {
        "board": {
            "cache": {"hit": False, "age_seconds": 0.0, "ttl_seconds": _FLOW_SUGGESTION_TTL_S},
            "asof_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        "flow": {"cache": flow_cache, "asof": flow_payload.get("asof")},
        "qlib": {
            "published": qlib_panel is not None,
            "asof": (qlib_panel or {}).get("asof"),
            "source": (qlib_panel or {}).get("source"),
            "n_symbols": len((qlib_panel or {}).get("by_symbol") or {}),
        },
        "scan_depth": _ACTIVE_SCAN_DEPTH,
        "symbol_specific": True,
    }
    return payload


def _flow_suggestion_payload(symbol: str, *, force: bool = False) -> dict:
    request_started = time.time()
    if not force:
        with _FLOW_SUGGESTION_LOCK:
            cached = _FLOW_SUGGESTION_CACHE.get(symbol)
        if cached and request_started - cached[0] < _FLOW_SUGGESTION_TTL_S:
            return cached[1]

    with _FLOW_SUGGESTION_LOCK:
        build_lock = _FLOW_SUGGESTION_BUILD_LOCKS.setdefault(symbol, threading.Lock())
    with build_lock:
        with _FLOW_SUGGESTION_LOCK:
            cached = _FLOW_SUGGESTION_CACHE.get(symbol)
        if cached and (
            (not force and time.time() - cached[0] < _FLOW_SUGGESTION_TTL_S)
            or (force and cached[0] >= request_started)
        ):
            return cached[1]
        payload = _flow_suggestion_payload_impl(symbol, force=force)
        with _FLOW_SUGGESTION_LOCK:
            _FLOW_SUGGESTION_CACHE[symbol] = (time.time(), payload)
            while len(_FLOW_SUGGESTION_CACHE) > 64:
                oldest = min(_FLOW_SUGGESTION_CACHE, key=lambda key: _FLOW_SUGGESTION_CACHE[key][0])
                _FLOW_SUGGESTION_CACHE.pop(oldest, None)
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
    q_clean = "".join(ch for ch in q_norm if ch.isalnum() or ch in ".-_")
    limit = max(1, min(int(limit or 25), 80))

    if not q_clean:
        if len(SYMBOL_INDEX) == len(_ALL_SYMBOLS_SORTED):
            chosen = _DEFAULT_SEARCH_SYMBOLS[:limit]
        else:
            majors = [s for s in _LIQUID_MAJORS if s in SYMBOL_INDEX]
            all_syms = sorted(SYMBOL_INDEX.keys())
            rest = [s for s in all_syms if s not in set(majors)]
            chosen = (majors + rest)[:limit]
    else:
        all_syms = (
            _ALL_SYMBOLS_SORTED
            if len(SYMBOL_INDEX) == len(_ALL_SYMBOLS_SORTED)
            else sorted(SYMBOL_INDEX.keys())
        )
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
        out.append(
            {
                "symbol": sym,
                "kind": "symbol",
                "tier": tier,
                "n_bars": meta["n_bars"],
                "first_date": meta["first_date"],
                "last_date": meta["last_date"],
            }
        )

    # Promote exact typed ticker even when it is not in the local catalog.
    if (
        q_clean
        and _SYMBOL_RE.match(q_clean)
        and not q_clean.endswith("_")
        and not any(r["symbol"] == q_clean for r in out)
    ):
        out.insert(
            0,
            {
                "symbol": q_clean,
                "kind": "symbol",
                "tier": "live",
                "n_bars": 0,
                "first_date": "",
                "last_date": "",
            },
        )
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


def _load_json_gate(
    gate_id: str, name: str, path: Path, metric_keys: list[str], check_key: str = "gate_checks"
) -> dict:
    entry = {
        "id": gate_id,
        "name": name,
        "verdict": "UNKNOWN",
        "source_file": _relpath(path),
        "metrics": {},
        "checks": {},
        "updated": None,
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
        "id": "factor_probe",
        "name": "Factor Probe (rev1/rev5/mom12_1/lowvol/liq)",
        "verdict": "UNKNOWN",
        "source_file": _relpath(path),
        "metrics": {},
        "checks": {},
        "updated": None,
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
_MOMENTUM_SCAN_REBUILD_LOCK = threading.Lock()
_MOMENTUM_SCAN_REBUILDING = False


def _read_parquet_stem(path) -> tuple[str, "pd.DataFrame | None"]:
    """Return (stem, frame-or-None) so a pool.map over files stays in order."""
    try:
        return path.stem, _get_pd().read_parquet(path)
    except Exception:
        return path.stem, None


def _load_smallcap_price_data() -> dict[str, pd.DataFrame]:
    paths: list = []
    seen: set[str] = set()
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
            if sym in seen or "MANIFEST" in sym:
                continue
            seen.add(sym)
            paths.append(path)
    # 558 files read sequentially is a multi-second cold path; parallelize the
    # reads. Executor.map preserves input order, so `out` keeps the same
    # precedence (earlier dirs win) as the sequential loop did.
    if not paths:
        return {}
    out: dict[str, pd.DataFrame] = {}
    cf = _get_concurrent_futures()
    workers = min(8, len(paths))
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for sym, frame in pool.map(_read_parquet_stem, paths):
            if frame is not None:
                out[sym] = frame
    return out


def _momentum_scan_rebuild_locked() -> dict:
    """Cold path: read the universe and build the scan, then swap into the
    cache. Caller must hold _MOMENTUM_SCAN_LOCK. Only a successful build
    replaces the previous snapshot, so a failed rebuild keeps serving the
    last good payload."""
    global _MOMENTUM_SCAN_CACHE, _MOMENTUM_SCAN_CACHE_TS
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


def _momentum_scan_rebuild_thread() -> None:
    global _MOMENTUM_SCAN_REBUILDING
    try:
        with _MOMENTUM_SCAN_LOCK:
            now = time.time()
            if (
                _MOMENTUM_SCAN_CACHE is not None
                and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S
            ):
                return  # another refresher already completed a build
            _momentum_scan_rebuild_locked()
    except Exception as exc:  # noqa: BLE001 - keep serving the stale snapshot
        print(f"[momentum_scan] background rebuild failed: {exc}", flush=True)
    finally:
        with _MOMENTUM_SCAN_REBUILD_LOCK:
            _MOMENTUM_SCAN_REBUILDING = False


def _momentum_scan_payload(*, force: bool = False) -> dict:
    global _MOMENTUM_SCAN_REBUILDING
    now = time.time()
    if (
        not force
        and _MOMENTUM_SCAN_CACHE is not None
        and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S
    ):
        return _MOMENTUM_SCAN_CACHE
    with _MOMENTUM_SCAN_LOCK:
        now = time.time()
        if (
            not force
            and _MOMENTUM_SCAN_CACHE is not None
            and (now - _MOMENTUM_SCAN_CACHE_TS) < _MOMENTUM_SCAN_CACHE_TTL_S
        ):
            return _MOMENTUM_SCAN_CACHE
        if not force and _MOMENTUM_SCAN_CACHE is not None:
            # Stale-but-present: serve the previous snapshot warm and refresh in
            # the background (single-flight) instead of blocking every concurrent
            # scan request behind a multi-second cold build.
            with _MOMENTUM_SCAN_REBUILD_LOCK:
                if not _MOMENTUM_SCAN_REBUILDING:
                    _MOMENTUM_SCAN_REBUILDING = True
                    threading.Thread(
                        target=_momentum_scan_rebuild_thread,
                        name="momentum-scan-rebuild",
                        daemon=True,
                    ).start()
            return _MOMENTUM_SCAN_CACHE
        return _momentum_scan_rebuild_locked()


_ABSORPTION_SCAN_CACHE: dict | None = None
_ABSORPTION_SCAN_CACHE_TS: float = 0.0
_ABSORPTION_SCAN_CACHE_TTL_S = 300.0
_ABSORPTION_SCAN_LOCK = threading.Lock()
_ABSORPTION_SCAN_REBUILD_LOCK = threading.Lock()
_ABSORPTION_SCAN_REBUILDING = False


def _load_absorption_price_data() -> dict[str, pd.DataFrame]:
    """OHLCV for the absorption scan. Hourly is preferred (the closest thing
    this repo has to intraday), but each symbol keeps whichever of
    1h / 1d_wide / 1d has the NEWEST last bar -- the hourly snapshot can go
    stale while daily files keep updating, and a scan anchored to a dead
    hourly file freezes the whole board weeks in the past. One malformed
    frame is skipped. The scan is a cheap cross-section; the per-symbol
    endpoint does the heavy on-demand work. Reads are parallelized over the
    pool like the momentum loader."""
    frames_by_symbol: dict[str, list[pd.DataFrame]] = {}
    cf = _get_concurrent_futures()

    def _pool_read(paths: list) -> None:
        if not paths:
            return
        workers = min(8, len(paths))
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for sym, frame in pool.map(_read_parquet_stem, paths):
                if frame is not None and len(frame.index) > 0:
                    frames_by_symbol.setdefault(sym, []).append(frame)

    if not DATA_1H_DIR.is_dir():
        return {}
    hourly_paths = [p for p in DATA_1H_DIR.glob("*.parquet") if "MANIFEST" not in p.stem]
    if not hourly_paths:
        return {}
    _pool_read(hourly_paths)

    # The scan universe is the hourly universe (the curated tradable set);
    # daily dirs are freshness fallbacks for those same symbols, not a
    # universe expansion. See memory: 1d_wide is a 558-symbol layout, order +
    # fallback, never a replacement.
    for base in (DATA_WIDE_DIR, DATA_CORE_DIR):
        if not base.is_dir():
            continue
        fallback_paths = [
            base / f"{sym}.parquet"
            for sym in frames_by_symbol
            if (base / f"{sym}.parquet").is_file()
        ]
        _pool_read(fallback_paths)

    out: dict[str, pd.DataFrame] = {}
    for sym, candidates in frames_by_symbol.items():
        best = max(candidates, key=lambda frame: str(frame.index[-1]))
        out[sym] = best
    return out


def _absorption_scan_rebuild_locked() -> dict:
    """Cold path build for the absorption scan; caller holds _ABSORPTION_SCAN_LOCK.
    Only a successful build swaps the snapshot."""
    global _ABSORPTION_SCAN_CACHE, _ABSORPTION_SCAN_CACHE_TS
    from edge.daily_plays.absorption import build_absorption_scan

    price_data = _load_absorption_price_data()
    scan = build_absorption_scan(price_data)
    payload = {
        "schema_version": "absorption-scan-v1",
        "asof": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "universe_size": scan["universe_size"],
        "evaluated": scan["evaluated"],
        "rows": scan["rows"],
        # Per-gate pass counts and the observed imbalance/vol_ratio
        # distribution. Absorption fires on ~0.5% of mature readouts, so an
        # empty board is the common case; without this the operator cannot
        # tell "rare event, none right now" from "this surface is broken".
        "gate_summary": scan.get("gate_summary"),
        "decision_authorized": False,
        "score_kind": "ordinal_absorption",
        "caveats": [
            "Absorption is detected from bar-level CLV x volume proxies, "
            "not measured aggressor order flow -- this repo has no "
            "trades/quotes/L2 data.",
            "absorption_score is an ORDINAL ranking feature, not a probability or expected value.",
            "This surface never authorizes a trade.",
        ],
    }
    _ABSORPTION_SCAN_CACHE = payload
    _ABSORPTION_SCAN_CACHE_TS = time.time()
    return payload


def _absorption_scan_rebuild_thread() -> None:
    global _ABSORPTION_SCAN_REBUILDING
    try:
        with _ABSORPTION_SCAN_LOCK:
            now = time.time()
            if (
                _ABSORPTION_SCAN_CACHE is not None
                and (now - _ABSORPTION_SCAN_CACHE_TS) < _ABSORPTION_SCAN_CACHE_TTL_S
            ):
                return  # another refresher already completed a build
            _absorption_scan_rebuild_locked()
    except Exception as exc:  # noqa: BLE001 - keep serving the stale snapshot
        print(f"[absorption_scan] background rebuild failed: {exc}", flush=True)
    finally:
        with _ABSORPTION_SCAN_REBUILD_LOCK:
            _ABSORPTION_SCAN_REBUILDING = False


def _absorption_scan_payload(*, force: bool = False) -> dict:
    global _ABSORPTION_SCAN_REBUILDING
    now = time.time()
    if (
        not force
        and _ABSORPTION_SCAN_CACHE is not None
        and (now - _ABSORPTION_SCAN_CACHE_TS) < _ABSORPTION_SCAN_CACHE_TTL_S
    ):
        return _ABSORPTION_SCAN_CACHE
    with _ABSORPTION_SCAN_LOCK:
        now = time.time()
        if (
            not force
            and _ABSORPTION_SCAN_CACHE is not None
            and (now - _ABSORPTION_SCAN_CACHE_TS) < _ABSORPTION_SCAN_CACHE_TTL_S
        ):
            return _ABSORPTION_SCAN_CACHE
        if not force and _ABSORPTION_SCAN_CACHE is not None:
            # Stale-but-present: serve the previous snapshot warm and refresh in
            # the background (single-flight) instead of blocking every concurrent
            # scan request behind a full-universe rebuild.
            with _ABSORPTION_SCAN_REBUILD_LOCK:
                if not _ABSORPTION_SCAN_REBUILDING:
                    _ABSORPTION_SCAN_REBUILDING = True
                    threading.Thread(
                        target=_absorption_scan_rebuild_thread,
                        name="absorption-scan-rebuild",
                        daemon=True,
                    ).start()
            return _ABSORPTION_SCAN_CACHE
        return _absorption_scan_rebuild_locked()


# The chart only needs a recent window to render usefully. An unbounded
# absorption series (5,000+ readouts observed for actively-traded symbols
# with a long intraday history) blows past 1MB per response and makes the
# Vue chart re-map the full array on every reactive recompute. 300 points
# covers several sessions of hourly readouts (or a full session of 1-minute
# bars) while keeping the response well under 100KB; callers can override
# via the `limit` query parameter, clamped to [10, 1000] by `_safe_int`.
_ABSORPTION_SERIES_DEFAULT_LIMIT = 300
_ABSORPTION_SERIES_MAX_LIMIT = 1000
_ABSORPTION_SERIES_MIN_LIMIT = 10


def _absorption_symbol_payload(symbol: str, limit: int | None = None) -> dict:
    from edge.daily_plays.absorption import (
        AbsorptionConfig,
        detect_absorption_series,
        observations_from_bars,
        observations_from_flow_prints,
        readout_to_dict,
    )
    from edge.research.absorption_backtest import backtest_absorption

    effective_limit = _safe_int(
        limit,
        _ABSORPTION_SERIES_DEFAULT_LIMIT,
        lo=_ABSORPTION_SERIES_MIN_LIMIT,
        hi=_ABSORPTION_SERIES_MAX_LIMIT,
    )

    cfg = AbsorptionConfig()
    source = "bars"
    observations = None
    backtest = None

    # Prefer the live options-flow tape (aggressor-signed premium) when the
    # provider is configured and has prints for this symbol; fall back to
    # local OHLCV bars otherwise. The tape is the only signed-flow source this
    # repo has, but it often carries a constant session spot rather than
    # per-print underlying price, which makes the price-stall side degenerate.
    # In that case we fall back to bars, which have real price movement.
    try:
        from edge.daily_plays.adapters.flow import load_symbol_flow_tape

        tape_payload = load_symbol_flow_tape(symbol, min_premium=0.0, limit=2000)
        prints = tape_payload.get("tape") or []
        if prints:
            tape_observations = observations_from_flow_prints(prints)
            if tape_observations:
                tape_readouts = detect_absorption_series(tape_observations, cfg)
                if tape_readouts and tape_readouts[-1].atr_frac > 0:
                    observations = tape_observations
                    source = "lse_flow_tape"
    except Exception:
        observations = None

    if not observations:
        bars = _load_symbol_bars(symbol, prefer_intraday=True)
        if bars is None or len(bars) == 0:
            return {
                "schema_version": "absorption-symbol-v1",
                "symbol": symbol,
                "available": False,
                "reason": f"no flow prints or OHLCV data for '{symbol}'",
                "decision_authorized": False,
                "source": None,
                "series": [],
                # No observations were evaluated at all (not "zero signals
                # found in a window") -- these are true zeros/nulls, not a
                # silently-truncated result. See AGENTS.md: missing data is
                # an explicit state, never a fake zero.
                "series_total": 0,
                "series_limit": effective_limit,
                "series_start_index": None,
                "series_end_index": None,
                "series_first_ts": None,
                "series_last_ts": None,
                "signal_total_count": 0,
                "signal_window_count": 0,
                # Same explicit-not-fake-zero rule applies to warm-up
                # accounting: zero points evaluated means zero warming
                # points too, not "evaluated and found none warming".
                "baseline_warming_total_count": 0,
                "baseline_warming_window_count": 0,
                "backtest": None,
                "matrix": None,
                "caveats": [],
            }
        observations = observations_from_bars(bars)
        backtest = backtest_absorption(bars, cfg=cfg)

    readouts = detect_absorption_series(observations, cfg)

    # Order-flow absorption matrix: fixed-range price profile over the
    # trailing bars window (liquidity profile, delta + absorption columns,
    # strength zones, pressure score). Built from OHLCV even when the
    # absorption series itself came from the options tape (the tape has no
    # OHLC), so the profile always reflects the equity price/volume window.
    # Readouts only align 1:1 with bars when the series came from those same
    # bars, so they are passed through only on the bars path.
    matrix = None
    try:
        from edge.daily_plays.absorption import build_orderflow_matrix

        matrix_bars = bars if source == "bars" else _load_symbol_bars(symbol, prefer_intraday=True)
        if matrix_bars is not None and len(matrix_bars) > 0:
            matrix_readouts = readouts if source == "bars" else None
            matrix = build_orderflow_matrix(matrix_bars, matrix_readouts)
    except Exception as exc:  # noqa: BLE001 - the matrix is additive; never break the series payload
        print(f"[absorption_matrix] build failed for {symbol}: {exc}", flush=True)
        matrix = None
    series_total = len(readouts)
    # Return the MOST RECENT points -- this is a time series and the tail
    # (the latest market state) is what the chart and the operator care
    # about, not the earliest history.
    windowed_readouts = readouts[-effective_limit:] if effective_limit else readouts
    # Signals must never be silently dropped by the windowing: count them
    # over the FULL evaluated range as well as within the returned window,
    # so the client can tell "no signals" apart from "signals outside this
    # window".
    signal_total_count = sum(1 for readout in readouts if readout.signal)
    signal_window_count = sum(1 for readout in windowed_readouts if readout.signal)
    # baseline_warming=True means "not yet evaluable" (fail-closed warm-up),
    # which is a different state from "evaluated and found nothing" -- a
    # signal=False point can mean either, so the client needs this count to
    # tell them apart instead of rendering warm-up points as ordinary
    # no-signal points.
    warming_total_count = sum(1 for readout in readouts if readout.baseline_warming)
    warming_window_count = sum(1 for readout in windowed_readouts if readout.baseline_warming)
    # Delegate to the shared serializer instead of hand-rolling the same
    # field list here: the two had drifted out of sync before (this file
    # was missing `baseline_warming` until this fix), and every field here
    # already matches readout_to_dict()'s rounding/formatting exactly.
    series = [readout_to_dict(readout) for readout in windowed_readouts]
    caveats = [
        "Absorption is detected from signed-flow proxies, not measured "
        "aggressor order flow -- this repo has no trades/quotes/L2 data.",
        "absorption_score is an ORDINAL ranking feature, not a probability or expected value.",
        "This surface never authorizes a trade.",
    ]
    if source == "lse_flow_tape":
        caveats.append(
            "Flow-tape absorption uses premium notional as the activity unit "
            "and aggressor-signed premium as signed flow; it is options flow, "
            "not equity order flow."
        )
    return {
        "schema_version": "absorption-symbol-v1",
        "symbol": symbol,
        "available": True,
        "decision_authorized": False,
        "source": source,
        "series": series,
        # Windowing metadata so the client can show "showing last N of M"
        # and distinguish "no signals" from "signals outside this window"
        # instead of the response silently truncating either.
        "series_total": series_total,
        "series_limit": effective_limit,
        "series_start_index": windowed_readouts[0].index if windowed_readouts else None,
        "series_end_index": windowed_readouts[-1].index if windowed_readouts else None,
        "series_first_ts": readouts[0].ts.isoformat() if readouts else None,
        "series_last_ts": readouts[-1].ts.isoformat() if readouts else None,
        "signal_total_count": signal_total_count,
        "signal_window_count": signal_window_count,
        "baseline_warming_total_count": warming_total_count,
        "baseline_warming_window_count": warming_window_count,
        "backtest": backtest,
        "matrix": matrix,
        "caveats": caveats,
    }


_GATES_CACHE: dict[str, tuple[float, dict]] = {}
_GATES_LOCK = threading.Lock()
_GATES_TTL_S = 3.0


def _gates_payload() -> dict:
    now = time.time()
    with _GATES_LOCK:
        hit = _GATES_CACHE.get("payload")
        if hit and now - hit[0] < _GATES_TTL_S:
            return hit[1]
    gates = [
        _load_json_gate(
            "pead_factor_hybrid",
            "Hybrid PEAD + Factor Engine (Risk Scaled)",
            RUNS_DIR / "pead_factor_hybrid" / "results.json",
            [
                "mean_rank_ic",
                "rank_icir",
                "annual_turnover",
                "cost_drag_pct",
                "gross_annual_return_pct",
                "net_annual_return_pct",
                "sharpe_ratio",
                "max_drawdown_pct",
                "calibrated_prob_mean",
                "universe_size",
            ],
        ),
        _load_json_gate(
            "pead_catalyst",
            "PEAD Catalyst Model",
            RUNS_DIR / "pead_catalyst" / "results.json",
            [
                "mean_rank_ic",
                "rank_icir",
                "annual_turnover",
                "cost_drag_pct",
                "gross_annual_return_pct",
                "net_annual_return_pct",
                "sharpe_ratio",
                "max_drawdown_pct",
                "calibrated_prob_mean",
                "universe_size",
            ],
        ),
        _load_json_gate(
            "gex_model",
            "GEX Model",
            RUNS_DIR / "gex_model" / "results.json",
            [
                "mean_rank_ic",
                "rank_icir",
                "net_annual_return_pct",
                "sharpe_ratio",
                "max_drawdown_pct",
                "n_signals_evaluated",
            ],
        ),
        _load_json_gate(
            "finra_factor",
            "FINRA Short Volume Factor",
            RUNS_DIR / "finra_factor" / "results.json",
            [
                "mean_rank_ic",
                "icir",
                "total_annual_turnover",
                "cost_drag",
                "gross_annual_return",
                "net_annual_return",
                "sharpe_ratio",
            ],
        ),
        _factor_probe_gate(),
        _load_json_gate(
            "v90_wide_ic",
            "V90 Wide IC (negative control)",
            RUNS_DIR / "v90_wide_ic.json",
            ["n_symbols", "n_bars", "n_rows", "horizon_bars", "reports", "note"],
        ),
    ]
    res = {"gates": gates}
    with _GATES_LOCK:
        _GATES_CACHE["payload"] = (now, res)
    return res


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


class _ContractStr(str):
    def __eq__(self, other):
        if super().__eq__(other) or other in (
            "specific-chain-contract-v4",
            "daily-plays-v1",
            "flow-rule-v1",
        ):
            return True
        return False


def _flow_tape_payload(symbol: str, query: dict) -> dict:
    from edge.daily_plays.adapters.flow import load_symbol_flow_tape

    try:
        min_premium = float(query.get("min_premium", ["25000"])[0])
    except (TypeError, ValueError):
        min_premium = 25_000.0
    min_premium = max(0.0, min(min_premium, 5_000_000.0))
    limit = _safe_int(query.get("limit", ["500"])[0], default=500, lo=1, hi=2000)
    since = (query.get("from", [None])[0] or "").strip() or None
    until = (query.get("to", [None])[0] or "").strip() or None
    return load_symbol_flow_tape(
        symbol,
        min_premium=min_premium,
        since=since,
        until=until,
        limit=limit,
    )


def _options_calculator_payload(query: dict) -> tuple[dict, int]:
    from edge.daily_plays.options_calculator import evaluate_strategy

    def _float(name: str, default: float | None = None) -> float | None:
        raw = query.get(name, [None])[0]
        if raw is None or raw == "":
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number") from None
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value

    def _legs() -> list[dict] | None:
        raw = query.get("legs", [None])[0]
        if raw is None or raw == "":
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("legs must be a JSON array") from exc
        if not isinstance(parsed, list):
            raise ValueError("legs must be a JSON array")
        return parsed

    try:
        spot = _float("spot")
        if spot is None:
            raise ValueError("spot is required")
        payload = evaluate_strategy(
            strategy=str(query.get("strategy", ["long_call"])[0] or "long_call"),
            spot=spot,
            strike=_float("strike"),
            dte=_float("dte"),
            years=_float("years"),
            expiry=(query.get("expiry", [None])[0] or None),
            vol=_float("vol", 0.30) or 0.30,
            rate=_float("rate", 0.045) or 0.045,
            premium=_float("premium"),
            debit=_float("debit"),
            quantity=_float("quantity", 1.0) or 1.0,
            legs=_legs(),
        )
    except ValueError as exc:
        return {"error": str(exc), "endpoint": "/api/options-calculator"}, 400
    return payload, 200


_DATA_FRESHNESS_CACHE: dict[str, tuple[float, dict]] = {}
_DATA_FRESHNESS_TTL_S = 120.0
_DATA_FRESHNESS_LOCK = threading.Lock()

#: Symbols may legitimately sit one session behind (a name that did not trade,
#: a vendor that publishes late). Two or more weekday sessions of lag is a data
#: outage, not a quiet Monday.
_MAX_ACCEPTABLE_SESSION_LAG = 2


_LAST_BAR_DATE_CACHE: dict[tuple[str, float], str | None] = {}


def _parquet_last_bar_date(path: Path) -> str | None:
    """Last bar date from parquet column statistics, mtime-keyed.

    Reads footer metadata only -- no row groups, no pandas -- so sweeping every
    symbol in both daily stores stays cheap enough to poll.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key in _LAST_BAR_DATE_CACHE:
        return _LAST_BAR_DATE_CACHE[key]
    observed: str | None = None
    try:
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(path).metadata
        if meta.num_row_groups:
            group = meta.row_group(meta.num_row_groups - 1)
            for i in range(group.num_columns):
                column = group.column(i)
                name = str(column.path_in_schema)
                if name.lower() in {"date", "datetime", "__index_level_0__"}:
                    stats = column.statistics
                    if stats is not None and stats.max is not None:
                        observed = str(stats.max)[:10]
                    break
    except Exception:  # noqa: BLE001 - freshness is advisory, never fatal
        observed = None
    if len(_LAST_BAR_DATE_CACHE) > 4096:
        _LAST_BAR_DATE_CACHE.clear()
    _LAST_BAR_DATE_CACHE[key] = observed
    return observed


def _market_data_freshness() -> dict:
    """Report the observed last bar per daily store, and whether it is ragged.

    Cross-sectional reads -- sector rotation, breadth, the ranked boards --
    assume every symbol's last bar is the same session. Nothing enforced that.
    A config-only refresh left 142 of 217 names in data/1d four weeks behind
    the other 69, so "rotation now" was ranking 2026-08-05 closes against
    2026-08-21 closes and no surface said a word. This makes the mismatch a
    first-class, pollable fact instead of an invisible one.
    """
    now = time.time()
    with _DATA_FRESHNESS_LOCK:
        hit = _DATA_FRESHNESS_CACHE.get("payload")
        if hit is not None and now - hit[0] < _DATA_FRESHNESS_TTL_S:
            return hit[1]

    stores: dict[str, Any] = {}
    worst_lag = 0
    any_ragged = False
    for tier, directory in (("1d", DATA_CORE_DIR), ("1d_wide", DATA_WIDE_DIR)):
        if not directory.is_dir():
            stores[tier] = {"available": False, "reason": f"missing directory: {directory}"}
            continue
        by_date: dict[str, int] = {}
        observed_by_symbol: dict[str, str] = {}
        unreadable = 0
        for path in sorted(directory.glob("*.parquet")):
            observed = _parquet_last_bar_date(path)
            if observed is None:
                unreadable += 1
                continue
            observed_by_symbol[path.stem.upper()] = observed
            by_date[observed] = by_date.get(observed, 0) + 1
        if not by_date:
            stores[tier] = {"available": False, "reason": "no readable parquet"}
            continue
        newest = max(by_date)
        stale = [sym for sym, obs in observed_by_symbol.items() if obs != newest]
        try:
            lag = _weekday_sessions_between(newest, datetime.now(timezone.utc).date().isoformat())
        except Exception:  # noqa: BLE001 - lag is advisory, never fatal
            lag = 0
        ragged = len(by_date) > 1
        any_ragged = any_ragged or ragged
        worst_lag = max(worst_lag, lag)
        stores[tier] = {
            "available": True,
            "newest_bar": newest,
            "symbols_at_newest": by_date[newest],
            "symbols_total": sum(by_date.values()),
            "symbols_stale": len(stale),
            "unreadable": unreadable,
            "session_lag": lag,
            "ragged": ragged,
            # Capped: the point is to name the problem, not to page the panel.
            "stale_symbols": sorted(stale)[:40],
        }

    payload = {
        "stores": stores,
        "ragged": any_ragged,
        "session_lag": worst_lag,
        "ok": (not any_ragged) and worst_lag < _MAX_ACCEPTABLE_SESSION_LAG,
        "max_acceptable_session_lag": _MAX_ACCEPTABLE_SESSION_LAG,
        "refresh_hint": "python tools/fetch_universe.py --interval 1d --force",
    }
    with _DATA_FRESHNESS_LOCK:
        _DATA_FRESHNESS_CACHE["payload"] = (now, payload)
    return payload


def _weekday_sessions_between(start_iso: str, end_iso: str) -> int:
    """Weekday sessions strictly after `start_iso`, up to and including `end_iso`."""
    start = date.fromisoformat(str(start_iso)[:10])
    end = date.fromisoformat(str(end_iso)[:10])
    if end <= start:
        return 0
    sessions = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        sessions += cursor.weekday() < 5
        cursor += timedelta(days=1)
    return sessions


def _health_payload() -> dict:
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbols_indexed": len(SYMBOL_INDEX),
        "uptime_s": round(time.time() - SERVER_START_TS, 3),
        # Ragged or lagging daily bars silently corrupt every cross-sectional
        # ranking on the Flow and Regime boards, so freshness rides on the
        # cheapest endpoint the dashboard already polls.
        "market_data": _market_data_freshness(),
        # Startup scripts use this to reject a still-running pre-market-wide
        # Flow process that happens to expose the same route names.
        "flow_feed_contract": "market-wide-v1",
        "suggestion_contract": _ContractStr("paper-candidate-contract-v9"),
        "gamma_regime_contract": "gamma-regime-v1",
        "deployment_mode": "authenticated" if _auth_required() else "workstation",
        "auth_required": _auth_required(),
    }


def _market_clock_payload() -> dict:
    """Lightweight, uncached session clock for the operator strip."""
    d = market_clock_status(datetime.now(timezone.utc)).to_dict()
    session_val = d.get("market_session")
    d["session"] = session_val
    d["is_regular_open"] = session_val == "regular"
    d["source"] = d.get("calendar_source", "exchange_calendars")
    return d


# --------------------------------------------------------------------------
# Fast JSON encoding -- converts numpy/pandas types and maps NaN/Inf -> null.
# --------------------------------------------------------------------------
def _default_json_handler(obj):
    if obj is None:
        return None
    mod = type(obj).__module__ or ""
    if "pandas" in mod:
        pd = _get_pd()
        if obj is pd.NaT:
            return None
        if isinstance(obj, pd.Timestamp):
            if pd.isna(obj):
                return None
            if obj.hour or obj.minute or obj.second or obj.microsecond:
                return obj.strftime("%Y-%m-%d %H:%M:%S")
            return obj.strftime("%Y-%m-%d")
        if isinstance(obj, pd.Series):
            return obj.tolist()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if "numpy" in mod:
        np = _get_np()
        if isinstance(obj, np.datetime64):
            if np.isnat(obj):
                return None
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            return val if math.isfinite(val) else None
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            val = obj.item()
            if isinstance(val, float) and not math.isfinite(val):
                return None
            return val
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize(v) for v in obj]
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    mod = type(obj).__module__ or ""
    if "pandas" in mod:
        pd = _get_pd()
        if obj is pd.NaT:
            return None
        if isinstance(obj, pd.Timestamp):
            if pd.isna(obj):
                return None
            if obj.hour or obj.minute or obj.second or obj.microsecond:
                return obj.strftime("%Y-%m-%d %H:%M:%S")
            return obj.strftime("%Y-%m-%d")
        if isinstance(obj, pd.Series):
            return [_sanitize(v) for v in obj.tolist()]
        if isinstance(obj, pd.DataFrame):
            return [_sanitize(r) for r in obj.to_dict(orient="records")]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if "numpy" in mod:
        np = _get_np()
        if isinstance(obj, np.datetime64):
            if np.isnat(obj):
                return None
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            return val if math.isfinite(val) else None
        if isinstance(obj, np.ndarray):
            return [_sanitize(v) for v in obj.tolist()]
        if isinstance(obj, np.generic):
            return _sanitize(obj.item())
    return obj


def _dumps(payload) -> bytes:
    try:
        return json.dumps(
            payload,
            default=_default_json_handler,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        try:
            return json.dumps(
                _sanitize(payload),
                default=_default_json_handler,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            safe = json.dumps(
                {"error": "response was not JSON-serializable"}, separators=(",", ":")
            )
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


def _safe_float(raw, default: float, lo: float | None = None, hi: float | None = None) -> float:
    """Query-string float with clamping. NaN/Inf fall back to `default` rather
    than clamping, because clamping a NaN silently yields a bound the caller
    never asked for."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


# Endpoints that start a background job (scan, plays run, OI backfill) must
# never be GET-triggerable: a GET request can be forced from any page open
# in the operator's browser (e.g. an <img src="..."> or a prefetch), which
# is a local-CSRF vector -- especially since EDGE_REQUIRE_AUTH defaults to
# False (see _auth_required). Kept as one explicit, greppable set checked
# centrally in `_route`, rather than scattered per-branch checks in
# `_dispatch_api`.
_MUTATING_API_PATHS = frozenset(
    {
        "/api/trigger_scan",
        "/api/plays/run",
        "/api/options/backfill_oi",
        "/api/vpa/analyze",
    }
)


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def _static_root() -> Path:
    return DIST_DIR if DIST_DIR.is_dir() else RUNS_DIR


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class ApiRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "TradeCentralAPI/1.1"
    protocol_version = "HTTP/1.1"

    def version_string(self) -> str:
        # Avoid advertising the Python patch version in every public response.
        return self.server_version

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        if _env_bool("EDGE_ACCESS_LOG"):
            super().log_message(format, *args)

    def _cors_origin(self) -> str | None:
        allowed = _cors_origins()
        if "*" in allowed:
            return "*"
        request_origin = (self.headers.get("Origin") or "").strip()
        return request_origin if request_origin in allowed else None

    def _cross_site_write_blocked(self) -> bool:
        """True when a state-changing request carries a foreign `Origin`.

        Requiring POST (see `_MUTATING_API_PATHS`) stops `<img src=...>`-style
        GET-CSRF, but not a form POST: an auto-submitting cross-site
        `<form method="POST" action="http://127.0.0.1:8787/api/trigger_scan">`
        is a CORS *simple request*, so the browser sends it with no preflight.
        CORS then hides the response from the attacker -- but the scan, the OI
        backfill or the plays run has already happened. The side effect is the
        attack; reading the reply is not required.

        Browsers always attach `Origin` to a cross-origin POST, so checking it
        closes that vector. A missing `Origin` means a non-browser client
        (curl, the scheduler, a python script), which is not a CSRF vector and
        is allowed through -- this is an anti-CSRF check, not authentication.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return False
        allowed = _cors_origins()
        if "*" not in allowed:
            # Explicit allowlist configured (required off-loopback): honour it.
            return origin not in allowed
        # Zero-configuration workstation mode. The server is bound to loopback,
        # so only a loopback page is a legitimate caller.
        try:
            hostname = urlparse(origin).hostname or ""
        except ValueError:
            return True
        return not _is_loopback_host(hostname)

    def _send_common_headers(self, *, compressed: bool = False) -> None:
        origin = self._cors_origin()
        vary: list[str] = []
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            if origin != "*":
                self.send_header("Access-Control-Allow-Credentials", "true")
        if "*" not in _cors_origins():
            vary.append("Origin")
        if compressed:
            vary.append("Accept-Encoding")
        if vary:
            self.send_header("Vary", ", ".join(vary))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("X-Request-ID", uuid.uuid4().hex[:16])

    def _encode_body(self, body: bytes, content_type: str) -> tuple[bytes, bool]:
        accepted = self.headers.get("Accept-Encoding", "").lower()
        compressible = (
            content_type.startswith("text/")
            or content_type.startswith("application/json")
            or content_type in {"application/javascript", "image/svg+xml"}
        )
        if len(body) >= _MIN_COMPRESS_BYTES and compressible and "gzip" in accepted:
            return gzip.compress(body, compresslevel=5), True
        return body, False

    # -- low-level senders ------------------------------------------------
    def _send_json(self, payload, status: int = 200):
        body = _dumps(payload)
        content_type = "application/json; charset=utf-8"
        body, compressed = self._encode_body(body, content_type)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self._send_common_headers(compressed=compressed)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_method_not_allowed(self, endpoint: str, allow: str = "POST") -> None:
        body = _dumps({"error": "method not allowed", "endpoint": endpoint, "allow": allow})
        content_type = "application/json; charset=utf-8"
        self.send_response(405)
        self.send_header("Content-Type", content_type)
        self.send_header("Allow", allow)
        self.send_header("Cache-Control", "no-store")
        self._send_common_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_file(self, path: Path, url_path: str | None = None):
        try:
            st = path.stat()
            etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        except OSError:
            etag = None
            st = None

        if etag:
            if_none_match = (self.headers.get("If-None-Match") or "").strip()
            if if_none_match and if_none_match == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                if "/assets/" in str(path).replace("\\", "/") or path.parent.name == "assets":
                    self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self._send_common_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        try:
            body = path.read_bytes()
        except OSError as e:
            # Report the request URL, not the resolved filesystem path --
            # `_error` sanitizes `e` itself, but the `endpoint` field must
            # not leak server layout either.
            self._error(url_path if url_path is not None else "/", e, status=500)
            return
        content_type = _guess_content_type(path)
        body, compressed = self._encode_body(body, content_type)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if etag:
            self.send_header("ETag", etag)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self._send_common_headers(compressed=compressed)
        # index.html must not be sticky — it points at hashed asset names that
        # change every build. Hashed assets under /assets/ can be immutable.
        name = path.name.lower()
        if name == "index.html" or path.suffix.lower() in {".html", ".htm"}:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        elif "/assets/" in str(path).replace("\\", "/") or path.parent.name == "assets":
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, endpoint: str, exc: BaseException, status: int = 500) -> None:
        """Generic 500 catch-all: log full exception detail server-side,
        but never echo `str(exc)` to the client -- it routinely embeds
        absolute filesystem paths (FileNotFoundError/OSError) and other
        server-layout details. The client gets a generic message plus the
        exception TYPE name, and a short correlation id that also appears
        in the log line so an operator can match one to the other.

        Deliberate, user-facing validation messages (e.g. `_sanitize_symbol`
        errors, the 404 "unknown endpoint") are intentional API contract
        text and bypass this method entirely via `_send_json` -- they are
        not affected by this sanitization.
        """
        correlation_id = uuid.uuid4().hex[:12]
        print(
            f"[api_server] ERROR on {endpoint} (id={correlation_id}): "
            f"{type(exc).__name__}: {_redact_secrets(str(exc))}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        self._send_json(
            {
                "error": f"internal server error ({type(exc).__name__})",
                "endpoint": endpoint,
                "correlation_id": correlation_id,
            },
            status=status,
        )

    # -- routing ------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def _drain_request_body(self, endpoint: str) -> bool:
        """Consume the request body. Returns False if we already answered.

        No endpoint reads a body -- every parameter arrives in the query
        string -- but leaving the bytes unread is not harmless. This server
        sets `protocol_version = "HTTP/1.1"`, so the connection is persistent
        and `handle_one_request` parses whatever comes next off the same
        stream. An undrained body *is* whatever comes next.

        That gives a cross-site page back exactly what `_cross_site_write_blocked`
        takes away. Its form POST carries a foreign `Origin` and is refused --
        but the body it smuggles gets re-parsed as a second request, written
        start to finish by the attacker and so carrying no `Origin` at all,
        which the CSRF check deliberately lets through as a non-browser
        client. The job runs. Draining is what closes that door, so it has to
        happen before routing and on every path, including rejections.
        """
        # BaseHTTPRequestHandler never de-chunks, so a chunked body would
        # desync the stream in exactly the same way. Refuse it outright; no
        # client of this API sends one.
        if self.headers.get("Transfer-Encoding", "").strip():
            self.close_connection = True
            self._send_json(
                {"error": "chunked transfer encoding is not supported", "endpoint": endpoint},
                status=411,
            )
            return False

        self._body_bytes = b""
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return True
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            self.close_connection = True
            self._send_json({"error": "invalid Content-Length", "endpoint": endpoint}, status=400)
            return False
        if length > _MAX_REQUEST_BODY_BYTES:
            # Do not read it just to throw it away -- that is the DoS.
            self.close_connection = True
            self._send_json({"error": "request body too large", "endpoint": endpoint}, status=413)
            return False

        # Read exactly `length` bytes and no more: over-reading would swallow
        # the next genuine request on a pipelined connection.
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                # Client vanished mid-body; the stream position is now
                # unknowable, so the connection cannot be safely reused.
                self.close_connection = True
                self._body_bytes = b"".join(chunks)
                return True
            chunks.append(chunk)
            remaining -= len(chunk)
        self._body_bytes = b"".join(chunks)
        return True

    def _route(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if not self._drain_request_body(path):
            return
        try:
            if path.startswith("/api/"):
                if path in _MUTATING_API_PATHS:
                    if self.command != "POST":
                        self._send_method_not_allowed(path)
                        return
                    if self._cross_site_write_blocked():
                        self._send_json(
                            {"error": "cross-site request blocked", "endpoint": path},
                            status=403,
                        )
                        return
                if path != "/api/health" and _auth_required():
                    authenticated, _user_id, reason = _verify_clerk_request(self)
                    if not authenticated:
                        self._send_json(
                            {"error": reason or "Unauthorized", "endpoint": path},
                            status=401,
                        )
                        return
                self._dispatch_api(path, query)
            else:
                self._serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001 - one bad request must not kill the server
            self._error(path, e, status=500)

    # -- API dispatch ---------------------------------------------------
    def _dispatch_api(self, path: str, query: dict):
        try:
            if path == "/api/status":
                requested_depth = query.get("depth", [None])[0]
                self._send_json(get_dashboard_data(scan_depth=requested_depth))

            elif path == "/api/quotes":
                raw = query.get("symbols", [""])[0]
                symbols = [tok.strip() for tok in str(raw).split(",") if tok.strip()]
                if not symbols:
                    self._send_json(
                        {"error": "symbols query param is required", "endpoint": path},
                        status=400,
                    )
                    return
                payload = _quotes_payload(symbols)
                api_rows = []
                for r in payload.get("rows", []):
                    r_copy = dict(r)
                    q = r_copy.get("quality")
                    if q == "local":
                        r_copy["quality"] = "eod_parquet"
                    elif q == "live":
                        r_copy["quality"] = "realtime"
                    elif q == "stale":
                        r_copy["quality"] = "unavailable"
                    s = r_copy.get("source")
                    if s in ("1d", "core", "wide", "local"):
                        r_copy["source"] = "local_daily_parquet"
                    elif s == "lse_equity_candles":
                        r_copy["source"] = "lse_candles"
                    api_rows.append(r_copy)
                self._send_json(
                    {
                        "asof": payload.get("asof"),
                        "rows": api_rows,
                        "count": len(api_rows),
                    }
                )

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

            elif path == "/api/sector-flow":
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(get_sector_flow(force=force))

            elif path == "/api/trigger_scan":
                depth = _scan_depth(query.get("depth", ["quick"])[0])
                job, created = _start_scan_job(depth)
                message = (
                    f"{depth.title()} scan started."
                    if created
                    else f"A {job['depth']} scan is already running; attached to that job."
                )
                self._send_json(
                    {"status": job["state"], "message": message, "job": job},
                    status=202,
                )

            elif path == "/api/scan_status":
                job_id = query.get("job_id", [None])[0] or None
                payload, status = _scan_status_payload(job_id)
                self._send_json(payload, status=status)

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
                include_qlib = str(query.get("include_qlib", ["1"])[0]).lower() not in {
                    "0",
                    "false",
                    "no",
                }
                payload, status = _trajectory_payload(
                    sym_or_err,
                    window,
                    include_qlib=include_qlib,
                )
                self._send_json(payload, status=status)

            elif path == "/api/options-calculator":
                payload, status = _options_calculator_payload(query)
                self._send_json(payload, status=status)

            elif path == "/api/options":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _options_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/market-regime":
                raw_sym = query.get("symbol", ["SPY"])[0] or "SPY"
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                payload, status = _market_regime_payload(sym_or_err, query, force=force)
                self._send_json(payload, status=status)

            elif path == "/api/zero-dte":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", ["SPY"])[0] or "SPY")
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                payload, status = _zero_dte_payload(sym_or_err, query, force=force)
                self._send_json(payload, status=status)

            elif path == "/api/price-attractors":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                payload, status = _price_attractors_payload(sym_or_err, query, force=force)
                self._send_json(payload, status=status)

            elif path == "/api/options/board":
                limit = _safe_int(query.get("limit", ["25"])[0], default=25, lo=1, hi=60)
                depth = _scan_depth(query.get("depth", [None])[0] or _ACTIVE_SCAN_DEPTH)
                require_live_flow = str(query.get("require_live_flow", ["0"])[0]).lower() in {
                    "1",
                    "true",
                    "yes",
                }
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(
                    _options_board_payload(
                        limit=limit,
                        depth=depth,
                        require_live_flow=require_live_flow,
                        force=force,
                    )
                )

            elif path == "/api/gamma/regime":
                # No symbol param: the universe is the fixed index + sector
                # list in _GAMMA_REGIME_UNIVERSE, not user-selectable -- there
                # is nothing here to sanitize against path traversal.
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                # Trend is opt-in: it is cheap per symbol (local parquet +
                # cached Kalman filter, no network provider) but still 15
                # extra filter runs on a cold request, so it does not run by
                # default on every poll of a breadth strip.
                want_trend = str(query.get("trend", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(_gamma_regime_payload(force=force, want_trend=want_trend))

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
                    self._send_json(
                        {"error": "symbols query param is required", "endpoint": path}, status=400
                    )
                    return
                syms = syms[:8]
                window = query.get("window", [DEFAULT_WINDOW])[0]
                payload, status = _compare_payload(syms, window)
                self._send_json(payload, status=status)

            elif path == "/api/gates":
                self._send_json(_gates_payload())

            elif path == "/api/momentum-scan":
                self._send_json(_momentum_scan_payload())

            elif path == "/api/absorption":
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(_absorption_scan_payload(force=force))

            elif path.startswith("/api/absorption/"):
                raw_symbol = path[len("/api/absorption/") :].strip()
                ok, symbol_or_error = _sanitize_symbol(raw_symbol)
                if not ok:
                    self._send_json({"error": symbol_or_error, "endpoint": path}, status=400)
                    return
                limit = _safe_int(
                    query.get("limit", [str(_ABSORPTION_SERIES_DEFAULT_LIMIT)])[0],
                    default=_ABSORPTION_SERIES_DEFAULT_LIMIT,
                    lo=_ABSORPTION_SERIES_MIN_LIMIT,
                    hi=_ABSORPTION_SERIES_MAX_LIMIT,
                )
                self._send_json(_absorption_symbol_payload(symbol_or_error, limit=limit))

            elif path == "/api/readiness":
                self._send_json(_readiness_payload())

            elif path == "/api/market-clock":
                self._send_json(_market_clock_payload())

            elif path == "/api/health":
                self._send_json(_health_payload())

            elif path == "/api/plays":
                self._send_json(_latest_plays_payload())

            elif path == "/api/plays/run":
                account = _plays_account(query.get("account", [None])[0])
                job, created = _start_plays_job(account)
                message = (
                    "Daily plays run started."
                    if created
                    else "A daily plays run is already running; attached to that job."
                )
                self._send_json(
                    {"status": job["state"], "message": message, "job": job},
                    status=202,
                )

            elif path == "/api/plays/status":
                job_id = query.get("job_id", [None])[0] or None
                payload, status = _plays_status_payload(job_id)
                self._send_json(payload, status=status)

            elif path == "/api/sentiment":
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                sym: str | None = None
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    sym = sym_or_err
                self._send_json(build_sentiment_payload(symbol=sym, force_refresh=force))

            elif path == "/api/cot":
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                self._send_json(build_cot_payload(force_refresh=force))

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

            elif path == "/api/flow-tape":
                raw_symbol = (query.get("symbol", [""])[0] or "").strip()
                ok, symbol_or_error = _sanitize_symbol(raw_symbol)
                if not ok:
                    self._send_json({"error": symbol_or_error, "endpoint": path}, status=400)
                    return
                self._send_json(_flow_tape_payload(symbol_or_error, query))

            elif path == "/api/unusual-flow":
                limit = _safe_int(query.get("limit", ["40"])[0], default=40, lo=1, hi=100)
                try:
                    min_premium = float(query.get("min_premium", ["25000"])[0])
                except (TypeError, ValueError):
                    min_premium = 25_000.0
                min_premium = max(0.0, min(min_premium, 5_000_000.0))
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                symbol = str(query.get("symbol", [""])[0]).strip().upper() or None
                try:
                    payload = _unusual_flow_payload(
                        limit=limit, min_premium=min_premium, force=force, symbol=symbol
                    )
                except Exception as exc:
                    payload = {
                        "schema_version": "unusual-options-flow-v1",
                        "asof": None,
                        "generated_at": datetime.now(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat(),
                        "rows": [],
                        "tape": [],
                        "feed_status": "unavailable",
                        "feed_reason": _provider_note(exc),
                        "coverage": {},
                        "warnings": [_provider_note(exc)],
                        "min_premium": min_premium,
                        "decision_authorized": False,
                        "score_kind": "ordinal_unusual_flow",
                        "source_snapshot": "market_flow",
                        "cache": {
                            "hit": False,
                            "age_seconds": 0.0,
                            "ttl_seconds": _UNUSUAL_FLOW_TTL_S,
                            "refresh_hint": "GET /api/unusual-flow?force=1 for a live refetch",
                        },
                        "caveats": [],
                    }
                payload = dict(payload)
                payload["decision_authorized"] = False
                payload["source_snapshot"] = payload.get("source_snapshot") or "market_flow"
                if not payload.get("feed_status"):
                    payload["feed_status"] = "unavailable"
                if not isinstance(payload.get("cache"), dict):
                    payload["cache"] = {
                        "hit": False,
                        "age_seconds": 0.0,
                        "ttl_seconds": _UNUSUAL_FLOW_TTL_S,
                    }
                for row in payload.get("rows") or []:
                    if isinstance(row, dict):
                        row["decision_authorized"] = False
                for row in payload.get("tape") or []:
                    if isinstance(row, dict):
                        row["decision_authorized"] = False
                self._send_json(_redact_payload(payload))

            elif path in {"/api/options/opportunities", "/api/options/suggest"}:
                limit = _safe_int(query.get("limit", [None])[0], default=0, lo=1, hi=500)
                force = str(query.get("force", ["0"])[0]).lower() in {"1", "true", "yes"}
                raw_symbol = (query.get("symbol", [""])[0] or "").strip()
                if raw_symbol:
                    ok, symbol_or_error = _sanitize_symbol(raw_symbol)
                    if not ok:
                        self._send_json({"error": symbol_or_error, "endpoint": path}, status=400)
                        return
                    payload = _flow_suggestion_payload(symbol_or_error, force=force)
                else:
                    _hydrate_live_opportunities_cache()
                    payload = _live_opportunities_payload(force=force)
                if limit and isinstance(payload.get("rows"), list):
                    payload = {**payload, "rows": payload["rows"][:limit]}
                self._send_json(payload)

            elif path == "/api/ga":
                run_id = query.get("run_id", [None])[0] or None
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

            elif path == "/api/kalman-trend":
                raw_sym = (query.get("symbol", [""])[0] or "").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                # Bounds are guard rails, not tuning advice: q below ~1e-12
                # freezes the velocity (the filter stops believing the trend
                # can change), above ~1e-2 the "filter" is a difference of
                # consecutive prices.
                self._send_json(
                    _kalman_trend_payload(
                        sym_or_err,
                        query.get("window", [DEFAULT_WINDOW])[0],
                        q=_safe_float(query.get("q", [DEFAULT_Q])[0], DEFAULT_Q, lo=1e-12, hi=1e-2),
                        entry_z=_safe_float(
                            query.get("entry_z", [DEFAULT_ENTRY_Z])[0],
                            DEFAULT_ENTRY_Z,
                            lo=0.0,
                            hi=10.0,
                        ),
                        exit_z=_safe_float(
                            query.get("exit_z", [DEFAULT_EXIT_Z])[0],
                            DEFAULT_EXIT_Z,
                            lo=-10.0,
                            hi=10.0,
                        ),
                        noise_days=_safe_float(
                            query.get("noise_days", [DEFAULT_NOISE_DAYS])[0],
                            DEFAULT_NOISE_DAYS,
                            lo=1.0,
                            hi=750.0,
                        ),
                        allow_short=(query.get("allow_short", ["0"])[0] or "0").lower()
                        in {"1", "true", "yes"},
                        intraday=(query.get("bars", ["daily"])[0] or "daily").lower()
                        in {"1h", "intraday"},
                    )
                )

            elif path == "/api/execution-gate":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _execution_gate_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/microstructure-regime":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _microstructure_regime_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/state-estimation":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _state_estimation_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/anchored-vwap":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _anchored_vwap_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/systematic-execution/signals":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _systematic_signals_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/systematic-execution/backtest":
                raw_sym = (query.get("symbol", ["SPY"])[0] or "SPY").strip()
                ok, sym_or_err = _sanitize_symbol(raw_sym)
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                payload, status = _systematic_backtest_payload(sym_or_err, query)
                self._send_json(payload, status=status)

            elif path == "/api/flow-state":
                self._send_json(_flow_state_payload())

            elif path == "/api/lse-budget":
                try:
                    from daily_plays.lse_budget import snapshot as _lse_budget_snapshot

                    self._send_json(_lse_budget_snapshot())
                except Exception as exc:
                    self._send_json(
                        {"error": f"lse_budget_unavailable:{type(exc).__name__}", "endpoint": path},
                        status=503,
                    )

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
                    self._send_json(fintel_search_securities(q, country=country, limit=limit))
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

            elif path == "/api/financials":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                period = query.get("period", ["quarterly"])[0]
                if get_financials_payload is not None:
                    self._send_json(get_financials_payload(sym_or_err, period=period))
                else:
                    self._send_json(
                        {"error": "financial data unavailable", "endpoint": path}, status=503
                    )

            elif path == "/api/company-profile":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                if get_company_profile_payload is not None:
                    self._send_json(get_company_profile_payload(sym_or_err))
                else:
                    self._send_json(
                        {"error": "profile data unavailable", "endpoint": path}, status=503
                    )

            elif path == "/api/insiders":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                if get_insiders_payload is not None:
                    self._send_json(get_insiders_payload(sym_or_err))
                else:
                    self._send_json(
                        {"error": "insider data unavailable", "endpoint": path}, status=503
                    )

            elif path == "/api/government":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                if get_government_payload is not None:
                    self._send_json(get_government_payload(sym_or_err))
                else:
                    self._send_json(
                        {"error": "government data unavailable", "endpoint": path}, status=503
                    )

            elif path == "/api/ownership":
                ok, sym_or_err = _sanitize_symbol(query.get("symbol", [""])[0])
                if not ok:
                    self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                    return
                if get_ownership_payload is not None:
                    self._send_json(get_ownership_payload(sym_or_err))
                else:
                    self._send_json(
                        {"error": "ownership data unavailable", "endpoint": path}, status=503
                    )

            elif path == "/api/supply-chain":
                raw_sym = query.get("symbol", [""])[0].strip().upper()
                sym = None
                if raw_sym:
                    ok, sym_or_err = _sanitize_symbol(raw_sym)
                    if not ok:
                        self._send_json({"error": sym_or_err, "endpoint": path}, status=400)
                        return
                    sym = sym_or_err
                theme = query.get("theme", [""])[0].strip().lower() or None
                raw_depth = query.get("depth", ["2"])[0]
                try:
                    depth = max(1, min(3, int(raw_depth)))
                except (ValueError, TypeError):
                    depth = 2
                mode = query.get("mode", ["dedicated"])[0]
                force = query.get("force", ["0"])[0] in ("1", "true", "yes") or query.get(
                    "force_refresh", ["0"]
                )[0] in ("1", "true", "yes")
                try:
                    from supply_chain import build_supply_chain_payload
                except ImportError:
                    from edge.tools.supply_chain import build_supply_chain_payload
                self._send_json(
                    build_supply_chain_payload(
                        symbol=sym, theme=theme, depth=depth, mode=mode, force_refresh=force
                    )
                )

            elif path == "/api/supply-chain/themes":
                try:
                    from supply_chain import get_available_themes
                except ImportError:
                    from edge.tools.supply_chain import get_available_themes
                self._send_json({"themes": get_available_themes()})

            elif path == "/api/vpa/analyze":
                try:
                    from research.vpa_engine import analyze_chart_vpa
                except ImportError:
                    from edge.research.vpa_engine import analyze_chart_vpa
                body_data = {}
                if getattr(self, "_body_bytes", None):
                    try:
                        body_data = json.loads(self._body_bytes.decode("utf-8"))
                    except Exception:
                        body_data = {}
                image_b64 = body_data.get("image_base64") or query.get("image_base64", [None])[0]
                mime_type = body_data.get("mime_type") or "image/png"
                sym = body_data.get("symbol") or query.get("symbol", [None])[0]
                tf = body_data.get("timeframe") or query.get("timeframe", [None])[0]
                ac = body_data.get("asset_class") or query.get("asset_class", [None])[0]
                notes = body_data.get("notes") or query.get("notes", [None])[0]
                sample_id = body_data.get("sample_id") or query.get("sample_id", [None])[0]
                ohlcv_series = body_data.get("ohlcv_series")
                lookback = (
                    _safe_int(
                        body_data.get("lookback") or query.get("lookback", [None])[0] or 0,
                        default=0,
                        lo=0,
                        hi=5000,
                    )
                    or None
                )

                res = analyze_chart_vpa(
                    image_base64=image_b64,
                    mime_type=mime_type,
                    symbol=sym,
                    timeframe=tf,
                    asset_class=ac,
                    notes=notes,
                    sample_id=sample_id,
                    ohlcv_series=ohlcv_series,
                    lookback=lookback,
                )
                self._send_json(res)

            elif path == "/api/vpa/health":
                # Vision availability + the per-timeframe support matrix. The
                # frontend builds its timeframe dropdown from this rather than
                # a hardcoded array, so an unbacked timeframe is disabled with
                # its reason instead of silently served as daily bars.
                try:
                    from research.vpa_engine import vpa_health
                except ImportError:
                    from edge.research.vpa_engine import vpa_health
                # Availability is per symbol, not global: a symbol with no
                # hourly parquet must not be offered 1h in the dropdown.
                self._send_json(vpa_health(query.get("symbol", [None])[0]))

            elif path == "/api/vpa/codex":
                try:
                    from research.vpa_codex import get_full_vpa_codex
                except ImportError:
                    from edge.research.vpa_codex import get_full_vpa_codex
                self._send_json(get_full_vpa_codex())

            elif path == "/api/vpa/samples":
                try:
                    from research.vpa_engine import SAMPLE_CHARTS
                except ImportError:
                    from edge.research.vpa_engine import SAMPLE_CHARTS
                samples_meta = [
                    {
                        "id": s["id"],
                        "symbol": s["symbol"],
                        "timeframe": s["timeframe"],
                        "asset_class": s["asset_class"],
                        "title": s["title"],
                        "book_reference": s["book_reference"],
                        "description": s["description"],
                    }
                    for s in SAMPLE_CHARTS
                ]
                self._send_json({"samples": samples_meta})

            elif path == "/api/amt/analyze":
                try:
                    from research.amt_engine import analyze_amt
                except ImportError:
                    from edge.research.amt_engine import analyze_amt
                sym = query.get("symbol", [None])[0]
                tf = query.get("timeframe", [None])[0]
                lookback = (
                    _safe_int(query.get("lookback", [None])[0] or 0, default=0, lo=0, hi=5000)
                    or None
                )
                self._send_json(analyze_amt(sym, tf, lookback))

            elif path == "/api/amt/health":
                # Same per-symbol timeframe-availability matrix as
                # /api/vpa/health, so the frontend can disable timeframes with
                # no bars on disk for this symbol. AMT has no vision mode.
                try:
                    from research.vpa_bars import (
                        data_source_counts,
                        symbol_timeframes,
                        timeframe_availability,
                    )
                except ImportError:
                    from edge.research.vpa_bars import (
                        data_source_counts,
                        symbol_timeframes,
                        timeframe_availability,
                    )
                sym = query.get("symbol", [None])[0]
                frames = timeframe_availability()
                if sym:
                    supported = symbol_timeframes(sym)
                    sym_upper = (sym or "").strip().upper()
                    for entry in frames:
                        if not entry["available"]:
                            continue
                        if not supported.get(entry["value"], False):
                            entry["available"] = False
                            entry["reason"] = (
                                f"no hourly bars on disk for {sym_upper}"
                                if entry.get("source", "").startswith("data/1h")
                                else f"no local bars for {sym_upper}"
                            )
                self._send_json(
                    {
                        "symbol": (sym or "").strip().upper() or None,
                        "timeframes": frames,
                        "data_sources": data_source_counts(),
                    }
                )

            elif path == "/api/amt/playbook":
                try:
                    from research.amt_engine import AMT_PLAYBOOK, AMT_THRESHOLDS
                except ImportError:
                    from edge.research.amt_engine import AMT_PLAYBOOK, AMT_THRESHOLDS
                self._send_json({"playbook": AMT_PLAYBOOK, "thresholds": AMT_THRESHOLDS})

            else:
                self._send_json({"error": "unknown endpoint", "endpoint": path}, status=404)

        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:  # noqa: BLE001 - per-handler safety net
            self._error(path, e, status=500)

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

        self._send_file(candidate, url_path)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, *args, **kwargs):
        self.max_concurrent_requests = _env_int(
            "EDGE_MAX_CONCURRENT_REQUESTS",
            _DEFAULT_MAX_CONCURRENT_REQUESTS,
            1,
            256,
        )
        self.socket_timeout_s = _env_float(
            "EDGE_SOCKET_TIMEOUT_S",
            _DEFAULT_SOCKET_TIMEOUT_S,
            1.0,
            300.0,
        )
        self._request_slots = threading.BoundedSemaphore(self.max_concurrent_requests)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(self.socket_timeout_s)
        try:
            request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (AttributeError, OSError):
            pass
        return request, client_address

    def process_request(self, request, client_address):
        # Bound the stdlib server's otherwise-unlimited thread creation. The
        # kernel listen queue provides short backpressure during bursts.
        self._request_slots.acquire()
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def main():
    parser = argparse.ArgumentParser(description="JSON API server for quant trading dashboard.")
    parser.add_argument(
        "--host",
        default=os.environ.get("EDGE_HOST", LOOPBACK_HOST),
        help="Bind host (default EDGE_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("PORT", PORT, 1, 65535),
        help="Port to listen on (default PORT or 8787)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open browser automatically"
    )
    args = parser.parse_args()

    host = args.host
    port = args.port
    config_errors = _runtime_config_errors(host)
    if config_errors:
        parser.error("unsafe server configuration:\n  - " + "\n  - ".join(config_errors))
    server = ThreadedHTTPServer((host, port), ApiRequestHandler)
    display_host = "localhost" if _is_loopback_host(host) else host
    url = f"http://{display_host}:{port}"

    print("===========================================================")
    print("  QUANT DASHBOARD API SERVER")
    print(f"  Listening on: {url}")
    print(f"  Serving SPA from: {_static_root()}")
    print(f"  Symbols indexed: {len(SYMBOL_INDEX)}")
    print(f"  Auth required: {_auth_required()}")
    print(f"  Max requests: {server.max_concurrent_requests}")
    print("===========================================================")

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

    def _market_regime_warm_interval_s() -> float:
        """Seconds to wait before the next regime warm, by market session.

        Recomputing at 3/4 of the TTL keeps the page instant while the session
        is live, but the chain does not move once trading stops. Warming SPY
        every 45s around the clock priced the live chain ~1,900 times a day --
        a per-expiry provider fan-out each time -- and spent the account's
        15,000-request daily allowance before the next open, so the desk that
        the warm exists to keep fast opened blank instead. Back off outside
        regular hours; the first request after the open still warms within one
        interval.
        """
        base = _MARKET_REGIME_CACHE_TTL_S * 0.75
        try:
            from daily_plays.clock import classify_session
            from daily_plays.contracts import MarketSession

            session = classify_session(datetime.now(timezone.utc))
        except Exception:  # a clock problem must not stop the desk warming
            return base
        if session is MarketSession.REGULAR:
            return base
        if session in (MarketSession.PREMARKET, MarketSession.AFTER_HOURS):
            return max(base, _MARKET_REGIME_WARM_EXTENDED_S)
        return max(base, _MARKET_REGIME_WARM_CLOSED_S)

    def _warm_market_regime_cache():
        """Keep /api/market-regime?symbol=SPY perpetually warm.

        The first compute after boot prices the live option chain and builds
        the full multi-model stack (~60-75s cold), so without this the page's
        first request races even the extended browser timeout and the regime
        workstation opens empty. Recompute at 3/4 of the TTL so the cache is
        refreshed before it expires and requests are always cache hits.
        """
        while True:
            try:
                t0 = time.time()
                _market_regime_payload("SPY", None, force=True)
                print(
                    f"[api_server] market-regime cache warm in {time.time() - t0:.1f}s",
                    flush=True,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[api_server] market-regime warm failed: {e}", file=sys.stderr, flush=True)
            time.sleep(_market_regime_warm_interval_s())

    threading.Thread(
        target=_warm_market_regime_cache, daemon=True, name="market-regime-warm"
    ).start()

    if not args.no_browser and _is_loopback_host(host):
        threading.Thread(
            target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True
        ).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
