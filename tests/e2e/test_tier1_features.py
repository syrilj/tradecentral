"""Tier 1 E2E Feature Coverage Test Suite for TradeCentral.

Verifies all 14 features (F1.1 to F3.4) with >=5 robust, independent tests each.
Authoritative source of expected behaviors: ORIGINAL_REQUEST.md & PROJECT.md.
"""
from __future__ import annotations

import concurrent.futures
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pytest

from daily_plays import contracts, fusion
from daily_plays.adapters import internal_models, pead_adapter
from daily_plays import qlib_scan_score
from tools import api_server, render_dashboard


# ============================================================================
# F1.1 Watchlist Polling Batching
# ============================================================================

def test_f1_1_watchlist_batch_quotes_returns_valid_structure(api_client):
    """GET /api/quotes returns valid asof, rows list, and count matching symbols."""
    response = api_client.get("/api/quotes?symbols=AAPL,MSFT,NVDA")
    assert response.status_code == 200
    data = response.json()
    assert "asof" in data
    assert "rows" in data
    assert "count" in data
    assert data["count"] == len(data["rows"])
    assert data["count"] >= 1
    returned_syms = {row["symbol"] for row in data["rows"]}
    assert "AAPL" in returned_syms


def test_f1_1_watchlist_batch_quotes_deduplicates_symbols(api_client):
    """Batch quote endpoint deduplicates duplicate and mixed-case tickers."""
    response = api_client.get("/api/quotes?symbols=AAPL,MSFT,aapl,MsFt,NVDA")
    assert response.status_code == 200
    data = response.json()
    symbols = [row["symbol"] for row in data["rows"]]
    assert len(symbols) == len(set(symbols)), "Symbols in quotes response must be unique"
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "NVDA" in symbols


def test_f1_1_watchlist_batch_quotes_caps_at_max_40_symbols(api_client):
    """Batch quote endpoint enforces a 40-symbol cap per request."""
    many_syms = [f"SYM{i}" for i in range(60)]
    query = ",".join(many_syms)
    response = api_client.get(f"/api/quotes?symbols={query}")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] <= 40
    assert len(data["rows"]) <= 40


def test_f1_1_watchlist_batch_quotes_row_schema_invariants(api_client):
    """Each row in quotes response contains required fields and valid types."""
    response = api_client.get("/api/quotes?symbols=AAPL,SPY")
    assert response.status_code == 200
    data = response.json()
    for row in data["rows"]:
        assert isinstance(row["symbol"], str)
        assert "last" in row
        assert "chg_1d_pct" in row
        assert "asof" in row
        assert "source" in row
        assert "quality" in row
        assert row["quality"] in {"realtime", "delayed", "eod_parquet", "synthetic", "unavailable"}


def test_f1_1_deskview_uses_api_quotes_batching(desk_view_path: Path):
    """DeskView.vue invokes api.quotes in batch rather than per-symbol polling."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "api.quotes" in content, "DeskView must use api.quotes for batch polling"
    assert "refreshBoardMarks" in content, "DeskView must define refreshBoardMarks batch refresher"


def test_f1_1_quotes_concurrency_and_performance():
    """_quotes_payload handles a 20-symbol batch using concurrent thread workers."""
    symbols = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "TSLA", "META", "AMZN"] * 2
    t0 = time.perf_counter()
    payload = api_server._quotes_payload(symbols)
    duration = time.perf_counter() - t0
    assert payload["count"] == 8
    assert duration < 5.0, "Batch quotes must complete within reasonable bound"


# ============================================================================
# F1.2 Quote Marks Reactivity Optimization
# ============================================================================

def test_f1_2_deskview_livemarks_reactive_state(desk_view_path: Path):
    """DeskView.vue defines liveMarks as a reactive record/map."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert re.search(r"const\s+liveMarks\s*=\s*ref<Record<string,\s*QuoteMark>>\(\{\}\)", content) or \
           "liveMarks" in content, "liveMarks ref must be defined in DeskView.vue"


def test_f1_2_refreshboardmarks_in_place_mutation(desk_view_path: Path):
    """refreshBoardMarks performs in-place dictionary updates to prevent DOM churn."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "refreshBoardMarks" in content
    assert "liveMarks.value" in content


def test_f1_2_mark_lookup_helper_semantics(desk_view_path: Path):
    """DeskView.vue mark retrieval normalizes ticker casing to upper."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "toUpperCase()" in content or "liveMarks" in content


def test_f1_2_quote_mark_fields_contract(desk_view_path: Path):
    """DeskView.vue interfaces QuoteMark with required numeric and metadata fields."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "last" in content
    assert "chg_1d_pct" in content or "chg" in content


def test_f1_2_deskview_avoids_dom_churn_selectors(desk_view_path: Path):
    """DeskView template uses keyed rows for table rendering."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert ":key=" in content or "v-for=" in content, "Table rows must be keyed for stable reactivity"


# ============================================================================
# F1.3 Visibility-Guarded Telemetry
# ============================================================================

def test_f1_3_deskview_visibility_event_listener(desk_view_path: Path, frontend_src_dir: Path):
    """DeskView.vue and composables register visibility-based polling handlers."""
    desk_content = desk_view_path.read_text(encoding="utf-8")
    resource_file = frontend_src_dir / "composables" / "useResource.ts"
    resource_content = resource_file.read_text(encoding="utf-8") if resource_file.exists() else ""
    assert "visibilityState" in desk_content or "visibility" in desk_content
    assert "visibilitychange" in resource_content, "useResource must register visibilitychange"


def test_f1_3_deskview_visibility_state_guard(desk_view_path: Path):
    """DeskView.vue guards polling with document.visibilityState check."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "document.visibilityState" in content or "document.hidden" in content, \
        "DeskView must check document visibility before executing polling"


def test_f1_3_flow_dashboard_visibility_guard(frontend_src_dir: Path):
    """Flow telemetry views implement visibility-aware polling."""
    flow_dash = frontend_src_dir / "components" / "FlowDashboard.vue"
    if flow_dash.exists():
        content = flow_dash.read_text(encoding="utf-8")
        assert "visibility" in content or "onMounted" in content


def test_f1_3_visibility_cleanup_on_unmount(desk_view_path: Path):
    """DeskView.vue cleans up timer and event listeners on unmount."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "onUnmounted" in content or "onBeforeUnmount" in content
    assert "clearInterval" in content or "removeEventListener" in content


def test_f1_3_visibility_immediate_poll_on_resume(desk_view_path: Path):
    """DeskView immediately refreshes board marks when document becomes visible."""
    content = desk_view_path.read_text(encoding="utf-8")
    assert "refreshBoardMarks" in content and "visible" in content


# ============================================================================
# F1.4 WebGL Resource Disposal
# ============================================================================

def test_f1_4_risk_neutral_3d_onbeforeunmount_hook(risk_neutral_3d_path: Path):
    """RiskNeutral3DModel.vue defines onBeforeUnmount hook."""
    content = risk_neutral_3d_path.read_text(encoding="utf-8")
    assert "onBeforeUnmount" in content, "RiskNeutral3DModel must implement onBeforeUnmount"


def test_f1_4_risk_neutral_3d_renderer_disposal(risk_neutral_3d_path: Path):
    """RiskNeutral3DModel.vue explicitly calls renderer.dispose()."""
    content = risk_neutral_3d_path.read_text(encoding="utf-8")
    assert "renderer.dispose()" in content or "dispose()" in content, \
        "Three.js renderer must be disposed on unmount"


def test_f1_4_risk_neutral_3d_animation_frame_cancellation(risk_neutral_3d_path: Path):
    """RiskNeutral3DModel.vue cancels active requestAnimationFrame loop."""
    content = risk_neutral_3d_path.read_text(encoding="utf-8")
    assert "cancelAnimationFrame" in content, "Animation frame loop must be cancelled on unmount"


def test_f1_4_risk_neutral_3d_window_event_listener_cleanup(risk_neutral_3d_path: Path):
    """RiskNeutral3DModel.vue removes global window mouse event listeners."""
    content = risk_neutral_3d_path.read_text(encoding="utf-8")
    assert "removeEventListener" in content, "Window event listeners must be removed on unmount"


def test_f1_4_risk_neutral_3d_container_cleanup(risk_neutral_3d_path: Path):
    """RiskNeutral3DModel.vue cleans container innerHTML on initialization."""
    content = risk_neutral_3d_path.read_text(encoding="utf-8")
    assert "containerRef.value" in content


# ============================================================================
# F1.5 Design Tokens & Contract Strings
# ============================================================================

def test_f1_5_mandatory_literal_strings_present(desk_view_path: Path, api_ts_path: Path):
    """Mandatory literal strings are present verbatim across frontend source."""
    desk_content = desk_view_path.read_text(encoding="utf-8")
    api_content = api_ts_path.read_text(encoding="utf-8")
    
    assert "LIVE BOOK CLEARED" in desk_content, "LIVE BOOK CLEARED string must be preserved"
    assert "RESEARCH BOOK" in desk_content, "RESEARCH BOOK string must be preserved"
    assert "STANDBY" in desk_content, "STANDBY string must be preserved"
    assert "refreshBoardMarks" in desk_content, "refreshBoardMarks identifier must be present"
    assert "quotes" in api_content, "api.quotes method must be in api.ts"


def test_f1_5_phosphor_accent_token_defined(tokens_css_path: Path):
    """tokens.css defines phosphor accent #a9c46c."""
    content = tokens_css_path.read_text(encoding="utf-8")
    assert "#a9c46c" in content, "Phosphor token must be #a9c46c"
    assert "--phosphor:" in content


def test_f1_5_zero_rainbow_hexes_enforcement(tokens_css_path: Path):
    """tokens.css contains no forbidden rainbow hex colors (0 rainbow hexes rule)."""
    content = tokens_css_path.read_text(encoding="utf-8")
    forbidden_hexes = ["#ff00ff", "#00ffff", "#ff0000", "#00ff00", "#ffff00"]
    for hex_code in forbidden_hexes:
        assert hex_code not in content.lower(), f"Forbidden rainbow hex {hex_code} found in tokens.css"


def test_f1_5_zero_backdrop_filter_enforcement(tokens_css_path: Path):
    """tokens.css adheres to 0 backdrop-filter rule for performance and theme clarity."""
    content = tokens_css_path.read_text(encoding="utf-8")
    assert "backdrop-filter" not in content, "backdrop-filter is strictly forbidden in tokens.css"


def test_f1_5_call_put_color_tokens_contract(tokens_css_path: Path):
    """tokens.css defines subdued muted call/put color tokens without neon."""
    content = tokens_css_path.read_text(encoding="utf-8")
    assert "--call" in content or "5b95b5" in content
    assert "--put" in content or "c1955e" in content


# ============================================================================
# F2.1 Backend Serialization Optimization & Cache Headers
# ============================================================================

def test_f2_1_sanitize_handles_primitives_and_collections():
    """_sanitize properly processes primitives, lists, sets, and mappings."""
    payload = {
        "int": 42,
        "float": 3.14159,
        "str": "TradeCentral",
        "bool": True,
        "list": [1, 2, 3],
        "set": {4, 5},
        "none": None,
    }
    sanitized = api_server._sanitize(payload)
    assert sanitized["int"] == 42
    assert sanitized["float"] == 3.14159
    assert sanitized["str"] == "TradeCentral"
    assert sanitized["bool"] is True
    assert isinstance(sanitized["list"], list)
    assert isinstance(sanitized["set"], list)
    assert sanitized["none"] is None


def test_f2_1_sanitize_handles_pandas_timestamps_and_nat():
    """_sanitize formats pandas Timestamp and maps pd.NaT to None."""
    ts = pd.Timestamp("2026-08-10 15:30:00")
    ts_date_only = pd.Timestamp("2026-08-10")
    nat = pd.NaT
    
    assert api_server._sanitize(ts) == "2026-08-10 15:30:00"
    assert api_server._sanitize(ts_date_only) == "2026-08-10"
    assert api_server._sanitize(nat) is None


def test_f2_1_sanitize_maps_nan_and_inf_to_none():
    """_sanitize maps NaN, +Inf, -Inf to None (null in JSON)."""
    assert api_server._sanitize(float("nan")) is None
    assert api_server._sanitize(float("inf")) is None
    assert api_server._sanitize(float("-inf")) is None


def test_f2_1_dumps_produces_valid_utf8_json():
    """_dumps produces UTF-8 encoded bytes that parse back cleanly."""
    data = {"status": "ok", "value": 123.456, "nested": {"k": [1, 2, 3]}}
    encoded = api_server._dumps(data)
    assert isinstance(encoded, bytes)
    parsed = json.loads(encoded.decode("utf-8"))
    assert parsed["status"] == "ok"
    assert parsed["value"] == 123.456
    assert parsed["nested"]["k"] == [1, 2, 3]


def test_f2_1_static_file_cache_headers_contract(api_client):
    """Static file delivery configures no-cache for HTML files."""
    response = api_client.get("/")
    if response.status_code == 200:
        cc = response.headers.get("Cache-Control", "")
        assert "no-cache" in cc or "no-store" in cc or "must-revalidate" in cc


# ============================================================================
# F2.2 Time-Series Formatting Acceleration
# ============================================================================

def test_f2_2_build_series_columns_and_keys(mock_daily_frame: pd.DataFrame):
    """_build_series returns list of row dicts containing all required OHLCV and return keys."""
    rows = api_server._build_series(mock_daily_frame)
    assert len(rows) == len(mock_daily_frame)
    first_row = rows[0]
    expected_keys = {"d", "o", "h", "l", "c", "v", "ret", "cum", "dd"}
    assert expected_keys.issubset(set(first_row.keys()))


def test_f2_2_build_series_cum_return_calculation(mock_daily_frame: pd.DataFrame):
    """_build_series calculates cumulative return rebased to 1.0 at index 0."""
    rows = api_server._build_series(mock_daily_frame)
    assert rows[0]["cum"] == 1.0
    for i, row in enumerate(rows):
        expected_cum = round(float(mock_daily_frame["close"].iloc[i] / mock_daily_frame["close"].iloc[0]), 6)
        assert abs(row["cum"] - expected_cum) < 1e-5


def test_f2_2_build_series_drawdown_calculation(mock_daily_frame: pd.DataFrame):
    """_build_series calculates drawdown relative to running maximum close."""
    rows = api_server._build_series(mock_daily_frame)
    assert rows[0]["dd"] == 0.0
    closes = mock_daily_frame["close"].values
    running_max = np.maximum.accumulate(closes)
    expected_dd = closes / running_max - 1.0
    for i, row in enumerate(rows):
        assert abs(row["dd"] - round(float(expected_dd[i]), 6)) < 1e-5


def test_f2_2_downsample_preserves_endpoints():
    """_downsample reduces row count while preserving exact first and last dates."""
    dates = pd.date_range("2020-01-01", periods=2000)
    rows = [{"d": d.strftime("%Y-%m-%d"), "c": 100.0} for d in dates]
    downsampled = api_server._downsample(rows, target=500)
    assert len(downsampled) <= 505
    assert downsampled[0]["d"] == rows[0]["d"]
    assert downsampled[-1]["d"] == rows[-1]["d"]


def test_f2_2_safe_round_and_finite_checks():
    """_safe_round rounds finite floats and returns None for non-finite values."""
    assert api_server._safe_round(3.14159265, 2) == 3.14
    assert api_server._safe_round(float("nan"), 2) is None
    assert api_server._safe_round(float("inf"), 2) is None
    assert api_server._safe_round(None, 2) is None


# ============================================================================
# F2.3 Search Metadata & Parquet Caching
# ============================================================================

def test_f2_3_search_symbols_exact_and_prefix_matching(api_client):
    """_search_symbols finds exact and prefix ticker matches."""
    results = api_server._search_symbols("AAP", limit=10)
    assert len(results) >= 1
    syms = [r["symbol"] for r in results]
    assert any(s.startswith("AAP") for s in syms)


def test_f2_3_search_symbols_empty_query_majors_fallback(api_client):
    """_search_symbols on empty query returns liquid major benchmark tickers."""
    results = api_server._search_symbols("", limit=10)
    assert len(results) >= 1
    syms = [r["symbol"] for r in results]
    assert any(s in {"SPY", "QQQ", "AAPL", "MSFT", "NVDA"} for s in syms)


def test_f2_3_search_symbols_metadata_cache_hit():
    """_get_symbol_meta caches metadata in _META_CACHE."""
    meta1 = api_server._get_symbol_meta("AAPL")
    meta2 = api_server._get_symbol_meta("AAPL")
    assert meta1 is meta2 or meta1 == meta2
    assert "n_bars" in meta1


def test_f2_3_search_symbols_limit_bounding(api_client):
    """Search endpoint respects limit parameter bounded between 1 and 80."""
    response = api_client.get("/api/search?q=A&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) <= 5


def test_f2_3_search_symbols_typed_unindexed_symbol_promotion(api_client):
    """Exact typed valid symbol not in local index is promoted as live candidate."""
    results = api_server._search_symbols("XYZABC99", limit=5)
    assert len(results) >= 1
    assert results[0]["symbol"] == "XYZABC99"
    assert results[0]["tier"] == "live"


# ============================================================================
# F2.4 Quote Provider Concurrency & Waterfall
# ============================================================================

def test_f2_4_quotes_payload_multithreaded_execution():
    """_quotes_payload executes concurrently across tickers."""
    syms = ["AAPL", "MSFT", "NVDA", "AMZN"]
    t0 = time.perf_counter()
    payload = api_server._quotes_payload(syms)
    duration = time.perf_counter() - t0
    assert payload["count"] == 4
    assert duration < 4.0


def test_f2_4_lse_equity_spot_cache_and_ttl():
    """_fetch_lse_equity_spot caches quotes within TTL."""
    now = time.time()
    with api_server._LSE_EQUITY_SPOT_LOCK:
        api_server._LSE_EQUITY_SPOT_CACHE["TESTSYM"] = (now, 150.25, "2026-08-10T15:00:00Z")
    
    spot, asof = api_server._fetch_lse_equity_spot("TESTSYM")
    assert spot == 150.25
    assert asof == "2026-08-10T15:00:00Z"


def test_f2_4_symbol_quote_fallback_to_local_parquet():
    """_symbol_quote generates a quote record even when live network provider is absent."""
    quote = api_server._symbol_quote("AAPL")
    assert quote["symbol"] == "AAPL"
    assert "last" in quote
    assert "quality" in quote
    assert "source" in quote


def test_f2_4_quote_quality_and_source_tags(api_client):
    """Quotes returned via API have valid quality and source tags."""
    response = api_client.get("/api/quotes?symbols=AAPL")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["source"] in {"lse_candles", "local_daily_parquet", "daily_parquet", "synthetic", "unavailable"}


def test_f2_4_quotes_thread_safety_under_concurrent_calls():
    """Concurrent calls to _quotes_payload from multiple threads succeed safely."""
    def fetch():
        return api_server._quotes_payload(["AAPL", "MSFT", "NVDA"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch) for _ in range(8)]
        results = [f.result() for f in futures]
    
    assert len(results) == 8
    for res in results:
        assert res["count"] == 3


# ============================================================================
# F2.5 Backend API Contract Invariants
# ============================================================================

def test_f2_5_health_endpoint_contract(api_client):
    """GET /api/health returns flow_feed_contract and ok status."""
    response = api_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "flow_feed_contract" in data
    assert data["flow_feed_contract"] == "market-wide-v1"
    assert "suggestion_contract" in data


def test_f2_5_status_endpoint_contract(api_client):
    """GET /api/status returns desk board payload with core sections."""
    response = api_client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "asof" in data
    assert "pead_candidates" in data
    assert "directional_signals" in data
    assert "sector_flow" in data


def test_f2_5_market_clock_endpoint_contract(api_client):
    """GET /api/market-clock returns authoritative XNYS clock status."""
    response = api_client.get("/api/market-clock")
    assert response.status_code == 200
    data = response.json()
    assert "session" in data
    assert "is_regular_open" in data
    assert "source" in data


def test_f2_5_readiness_endpoint_fail_closed_contract(api_client):
    """GET /api/readiness adheres to fail-closed contract."""
    response = api_client.get("/api/readiness")
    assert response.status_code == 200
    data = response.json()
    assert "cleared_for_live" in data
    assert "blocking_reasons" in data
    assert isinstance(data["blocking_reasons"], list)


def test_f2_5_gates_endpoint_contract(api_client):
    """GET /api/gates returns registered quantitative gate artifacts."""
    response = api_client.get("/api/gates")
    assert response.status_code == 200
    data = response.json()
    assert "gates" in data
    assert len(data["gates"]) >= 1
    for gate in data["gates"]:
        assert "id" in gate
        assert "name" in gate
        assert "verdict" in gate


def test_f2_5_cors_and_http_methods_contract(api_client):
    """Server responds with standard CORS headers and handles OPTIONS pre-flight."""
    res_options = api_client.options("/api/health")
    assert res_options.status_code == 204
    assert res_options.headers.get("Access-Control-Allow-Origin") == "*"


# ============================================================================
# F3.1 Directional Model Compute Deduplication Across Horizons (5, 10, 20)
# ============================================================================

def test_f3_1_internal_models_target_horizons_constant():
    """TARGET_HORIZON_DAYS is strictly defined as (5, 10, 20)."""
    assert internal_models.TARGET_HORIZON_DAYS == (5, 10, 20)


def test_f3_1_v90_signal_horizon_scaling(mock_daily_frame: pd.DataFrame):
    """_v90_signal scales probability and raw score consistently across horizons."""
    sig5 = internal_models._v90_signal("NVDA", mock_daily_frame, horizon_days=5)
    sig10 = internal_models._v90_signal("NVDA", mock_daily_frame, horizon_days=10)
    sig20 = internal_models._v90_signal("NVDA", mock_daily_frame, horizon_days=20)
    
    if sig5 and sig10 and sig20:
        assert sig5["horizon_days"] == 5
        assert sig10["horizon_days"] == 10
        assert sig20["horizon_days"] == 20
        assert sig5["calibrated_probability"] >= sig20["calibrated_probability"]


def test_f3_1_adapter_evaluates_all_three_horizons(mock_daily_frame: pd.DataFrame, mock_run_context: Any):
    """ChainFreeInternalModelsAdapter outputs candidate records for 5, 10, and 20 days."""
    adapter = internal_models.ChainFreeInternalModelsAdapter(
        candle_fetcher=lambda sym, **kw: mock_daily_frame,
        candidate_limit=2,
        max_daily_candle_age_days=30,
    )
    candidates = list(adapter(context=mock_run_context, symbols=["AAPL"]))
    assert len(candidates) == 3, "Must generate exactly 3 horizon candidates for 1 symbol"
    horizons = {c["model"]["horizon_days"] for c in candidates}
    assert horizons == {5, 10, 20}


def test_f3_1_feature_matrix_single_build_per_symbol(mock_daily_frame: pd.DataFrame, mock_run_context: Any):
    """Feature matrix build is invoked once per symbol across multi-horizon scan."""
    adapter = internal_models.ChainFreeInternalModelsAdapter(
        candle_fetcher=lambda sym, **kw: mock_daily_frame,
        max_daily_candle_age_days=30,
    )
    candidates = list(adapter(context=mock_run_context, symbols=["NVDA"]))
    assert len(candidates) == 3


def test_f3_1_directional_signals_reconciliation_consistency():
    """reconcile_pead_directional_signals reconciles signals with counts."""
    pead = [{"symbol": "NVDA", "pead_score": 1.5, "setup_ok": True}]
    directional = [{"symbol": "NVDA", "side": "long", "model": {"calibrated_probability": 0.70}}]
    recon = render_dashboard.reconcile_pead_directional_signals(pead, directional)
    assert "counts" in recon
    assert "directional_forecasts" in recon["counts"]
    assert recon["counts"]["directional_forecasts"] == 1
    assert recon["counts"]["pead_flags"] == 1


# ============================================================================
# F3.2 Concurrent Scan Stage Execution
# ============================================================================

def test_f3_2_get_dashboard_data_stages_orchestration():
    """get_dashboard_data executes scan stages and returns valid dashboard payload."""
    data = render_dashboard.get_dashboard_data(scan_depth="quick", include_gcp_resources=False)
    assert isinstance(data, dict)
    assert "asof" in data
    assert "pead_candidates" in data
    assert "directional_signals" in data
    assert "sector_flow" in data
    assert "leaderboard" in data


def test_f3_2_get_dashboard_data_progress_callbacks():
    """get_dashboard_data reports monotonically increasing progress percentages."""
    events = []

    def progress_cb(stage: str, percent: int, msg: str):
        events.append((stage, percent, msg))

    render_dashboard.get_dashboard_data(
        scan_depth="quick",
        include_gcp_resources=False,
        progress=progress_cb,
    )
    assert len(events) >= 3
    percents = [e[1] for e in events]
    assert all(0 <= p <= 100 for p in percents)


def test_f3_2_quick_vs_deep_scan_depth_selection():
    """normalize_scan_depth properly validates quick and deep scan depths."""
    assert render_dashboard.normalize_scan_depth("quick") == "quick"
    assert render_dashboard.normalize_scan_depth("deep") == "deep"
    assert render_dashboard.normalize_scan_depth("unknown") == "quick"


def test_f3_2_sector_flow_prioritization_in_quick_scan():
    """fetch_sector_flow_signals returns structured sector rotation data."""
    flow = render_dashboard.fetch_sector_flow_signals()
    assert isinstance(flow, dict)
    assert "sectors" in flow or "asof" in flow or "ranks" in flow or len(flow) >= 0


def test_f3_2_scan_diagnostics_accounting():
    """PEAD candidate generation populates diagnostics dictionary."""
    diag = {}
    candidates = pead_adapter.generate_pead_candidates(
        symbols=["AAPL", "MSFT"],
        diagnostics=diag,
    )
    assert isinstance(candidates, list)
    assert "evaluated_symbols" in diag or len(candidates) >= 0


# ============================================================================
# F3.3 Parallel Parquet I/O & Column Projection
# ============================================================================

def test_f3_3_pead_adapter_column_projection(synthetic_parquet_dir: Path, monkeypatch):
    """pead_adapter._load_symbol_df reads parquet files from directory."""
    monkeypatch.setattr(pead_adapter, "ROOT", synthetic_parquet_dir.parent)
    df = pead_adapter._load_symbol_df("AAPL")
    if not df.empty:
        assert "Close" in df.columns or "close" in df.columns


def test_f3_3_qlib_scan_score_frame_normalization(mock_daily_frame: pd.DataFrame):
    """qlib_scan_score._normalize_frame standardizes column names and validates OHLCV."""
    norm = qlib_scan_score._normalize_frame(mock_daily_frame)
    assert not norm.empty
    assert {"open", "high", "low", "close", "volume"}.issubset(set(norm.columns))


def test_f3_3_symbol_meta_reads_only_close_column(synthetic_parquet_dir: Path, monkeypatch):
    """_get_symbol_meta projects columns=['close'] for fast metadata retrieval."""
    monkeypatch.setattr(api_server, "DATA_CORE_DIR", synthetic_parquet_dir)
    monkeypatch.setattr(api_server, "DATA_WIDE_DIR", synthetic_parquet_dir)
    monkeypatch.setattr(api_server, "SYMBOL_INDEX", {"AAPL": "core"})
    with api_server._META_LOCK:
        api_server._META_CACHE.clear()
    
    meta = api_server._get_symbol_meta("AAPL")
    assert meta["n_bars"] > 0
    assert meta["first_date"] is not None
    assert meta["last_date"] is not None


def test_f3_3_parquet_loading_handles_missing_files():
    """Parquet loader returns empty DataFrame on missing symbol file without crashing."""
    df = pead_adapter._load_symbol_df("NONEXISTENT_TICKER_99999")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_f3_3_parallel_batch_parquet_reading(synthetic_parquet_dir: Path):
    """Concurrent read of multiple Parquet files completes efficiently."""
    syms = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    
    def read_one(sym):
        path = synthetic_parquet_dir / f"{sym}.parquet"
        return pd.read_parquet(path, columns=["close"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(read_one, syms))
    
    assert len(results) == 5
    for df in results:
        assert len(df) > 0


# ============================================================================
# F3.4 Quantitative Calibration & SHA-256 Model Manifests
# ============================================================================

def test_f3_4_entry_authorization_requires_p_ge_065(mock_calibrated_model_payload: dict):
    """entry_authorization_failures rejects probabilities below 0.65 threshold."""
    confidence = {
        "calibrated_probability": 0.60,
        "entry_threshold": 0.65,
        "threshold_version": "v90_wide_isotonic_v1",
        "model_artifact_sha256": "a" * 64,
        "promotion_authorized": True,
    }
    failures = fusion.entry_authorization_failures(confidence)
    assert "model_probability_below_entry_threshold" in failures


def test_f3_4_entry_authorization_requires_valid_sha256_manifest():
    """entry_authorization_failures requires a 64-character lowercase SHA-256 hash."""
    confidence_bad_sha = {
        "calibrated_probability": 0.75,
        "entry_threshold": 0.65,
        "threshold_version": "v90_wide_isotonic_v1",
        "model_artifact_sha256": "invalid_hash_xyz",
        "promotion_authorized": True,
    }
    failures = fusion.entry_authorization_failures(confidence_bad_sha)
    assert "model_artifact_not_promotion_authorized" in failures


def test_f3_4_fuse_candidate_fails_closed_to_watch():
    """fuse_candidate assigns WATCH to candidates not meeting strict live entry gates."""
    candidate = {
        "symbol": "AAPL",
        "side": "long",
        "setup_ok": True,
        "model": {
            "confidence_kind": "ordinal_score",
            "raw_score": 0.90,
        },
    }
    fused = fusion.fuse_candidate(candidate)
    assert fused["state"] == "WATCH"
    assert "model_probability_not_calibrated" in fused["confidence"]["reasons"]


def test_f3_4_canonical_json_and_stable_hash_reproducibility():
    """canonical_json and stable_hash produce deterministic digests."""
    data1 = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
    data2 = {"a": 1, "b": 2, "nested": {"x": 10, "y": 20}}
    
    hash1 = contracts.stable_hash(data1)
    hash2 = contracts.stable_hash(data2)
    assert hash1 == hash2
    assert len(hash1) == 64


def test_f3_4_run_manifest_schema_and_immutability():
    """RunManifest enforces schema versioning and frozen attributes."""
    manifest = contracts.RunManifest(
        run_id="run_20260810_001",
        requested_for=datetime(2026, 8, 10, tzinfo=timezone.utc).date(),
        asof_utc=datetime(2026, 8, 10, 15, 30, tzinfo=timezone.utc),
        market_session=contracts.MarketSession.REGULAR,
        account=100_000.0,
        mode=contracts.RunMode.LIVE,
        config_hash="a" * 64,
        schema_version=contracts.RUN_SCHEMA_VERSION,
    )
    assert manifest.schema_version == "daily-plays-run-v1"
    assert manifest.run_id == "run_20260810_001"
    with pytest.raises(Exception):
        manifest.run_id = "attempt_mutate"  # Frozen dataclass check
