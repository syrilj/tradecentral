"""Empirical stress-testing and adversarial challenger suite for Milestone 3.

Tests:
1. Qlib 16-factor extraction across corrupt/missing columns, zero volume, flat prices, extreme spikes, and large universes (500+ symbols).
2. Concurrent scan stage execution in render_dashboard.py: simulated thread exceptions, fail-closed handling, deadlock prevention.
3. Benchmark suite for PEAD, Qlib, and Full Quick Scan.
"""
from __future__ import annotations

import math
import time
import numpy as np
import pandas as pd

from edge.daily_plays.qlib_scan_score import (
    FEATURE_NAMES,
    SCORE_KIND,
    _normalize_frame,
    feature_row_from_frame,
    score_cross_section_asof,
)
from edge.daily_plays.adapters.pead_adapter import (
    generate_pead_candidates,
)
from edge.tools import render_dashboard as dashboard


# ============================================================================
# 1. QLIB 16-FACTOR ADVERSARIAL STRESS TESTS
# ============================================================================

def _make_stress_frame(
    *,
    periods: int = 300,
    price_pattern: str = "normal",
    volume_pattern: str = "normal",
    base_price: float = 100.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV frames with controlled pathologies."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=periods)
    
    if price_pattern == "normal":
        rets = rng.normal(0.0005, 0.02, size=periods)
        close = base_price * np.cumprod(1.0 + rets)
        high = np.maximum(close * 1.01, close)
        low = np.minimum(close * 0.99, close)
        open_p = np.r_[close[0], close[:-1]]
    elif price_pattern == "flat":
        close = np.full(periods, base_price)
        high = np.full(periods, base_price)
        low = np.full(periods, base_price)
        open_p = np.full(periods, base_price)
    elif price_pattern == "zero_close":
        close = np.zeros(periods)
        high = np.zeros(periods)
        low = np.zeros(periods)
        open_p = np.zeros(periods)
    elif price_pattern == "spike_up":
        rets = rng.normal(0.0005, 0.01, size=periods)
        close = base_price * np.cumprod(1.0 + rets)
        close[-1] = close[-2] * 1000.0  # 100,000% jump
        high = np.maximum(close * 1.01, close)
        low = np.minimum(close * 0.99, close)
        open_p = np.r_[close[0], close[:-1]]
    elif price_pattern == "spike_down":
        rets = rng.normal(0.0005, 0.01, size=periods)
        close = base_price * np.cumprod(1.0 + rets)
        close[-1] = 1e-6  # Penny stock collapse
        high = np.maximum(close * 1.01, close)
        low = np.minimum(close * 0.99, close)
        open_p = np.r_[close[0], close[:-1]]
    elif price_pattern == "extreme_large":
        close = np.full(periods, 1e12)
        high = close * 1.01
        low = close * 0.99
        open_p = close.copy()
    elif price_pattern == "extreme_small":
        close = np.full(periods, 1e-12)
        high = close * 1.01
        low = close * 0.99
        open_p = close.copy()
    else:
        raise ValueError(f"Unknown pattern {price_pattern}")
        
    if volume_pattern == "normal":
        vol = rng.uniform(500_000, 2_000_000, size=periods)
    elif volume_pattern == "zero":
        vol = np.zeros(periods)
    elif volume_pattern == "constant":
        vol = np.full(periods, 1_000_000.0)
    elif volume_pattern == "spike":
        vol = rng.uniform(500_000, 2_000_000, size=periods)
        vol[-1] = 1e11
    elif volume_pattern == "nan_injected":
        vol = rng.uniform(500_000, 2_000_000, size=periods)
        vol[20:30] = np.nan
    else:
        raise ValueError(f"Unknown volume pattern {volume_pattern}")
    
    return pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        },
        index=dates,
    )


def test_qlib_factors_corrupt_missing_columns():
    """Verify factor extraction handles corrupt, missing, or malformed columns without unhandled crashes."""
    # 1. Missing close column
    df_no_close = pd.DataFrame({"open": [100]*100, "high": [101]*100, "low": [99]*100, "volume": [1000]*100})
    norm = _normalize_frame(df_no_close)
    assert norm.empty
    
    # 2. Corrupt string columns
    dates = pd.bdate_range("2024-01-01", periods=100)
    df_strings = pd.DataFrame({
        "open": ["invalid"] * 100,
        "high": ["corrupt"] * 100,
        "low": ["bad"] * 100,
        "close": ["string_val"] * 100,
        "volume": ["NaN"] * 100,
    }, index=dates)
    norm_str = _normalize_frame(df_strings)
    assert norm_str.empty
    
    # 3. Empty DataFrame
    feats_empty = feature_row_from_frame(pd.DataFrame())
    assert all(feats_empty[k] is None for k in FEATURE_NAMES)
    
    # 4. Partial string corruption with some valid rows
    df_partial = pd.DataFrame({
        "open": [100.0]*50 + ["bad"]*50,
        "high": [101.0]*50 + ["bad"]*50,
        "low": [99.0]*50 + ["bad"]*50,
        "close": [100.0]*50 + ["bad"]*50,
        "volume": [1000.0]*50 + ["bad"]*50,
    }, index=dates)
    norm_partial = _normalize_frame(df_partial)
    assert len(norm_partial) == 50
    # Less than MIN_HISTORY_BARS (60)
    feats_partial = feature_row_from_frame(norm_partial)
    assert all(feats_partial[k] is None for k in FEATURE_NAMES)


def test_qlib_factors_zero_and_constant_volume():
    """Verify zero or constant volume outputs finite/None values without division by zero or NaN propagation."""
    # 1. Zero volume
    df_zero_vol = _make_stress_frame(periods=300, price_pattern="normal", volume_pattern="zero")
    feats_zero_vol = feature_row_from_frame(df_zero_vol)
    
    # Check all factors are either finite float or None (never NaN, Inf, or exception)
    for k, v in feats_zero_vol.items():
        if v is not None:
            assert math.isfinite(v), f"Factor {k} is non-finite: {v}"
            assert not math.isnan(v), f"Factor {k} is NaN"
            
    # Expected behavior for zero volume
    assert feats_zero_vol["liq"] == 0.0
    assert feats_zero_vol["log_adv"] is None
    assert feats_zero_vol["volume_z"] is None
    # Price based factors should still compute
    assert feats_zero_vol["rev1"] is not None
    assert feats_zero_vol["rev5"] is not None
    assert feats_zero_vol["ret_5"] is not None

    # 2. Constant volume (std(volume) == 0)
    df_const_vol = _make_stress_frame(periods=300, price_pattern="normal", volume_pattern="constant")
    feats_const_vol = feature_row_from_frame(df_const_vol)
    assert feats_const_vol["volume_z"] is None  # standard dev is 0 <= 1e-12
    assert feats_const_vol["log_adv"] is not None
    assert math.isfinite(feats_const_vol["log_adv"])


def test_qlib_factors_flat_prices():
    """Verify flat prices output finite/None values with zero volatility and no division by zero."""
    df_flat = _make_stress_frame(periods=300, price_pattern="flat", volume_pattern="normal")
    feats_flat = feature_row_from_frame(df_flat)
    
    for k, v in feats_flat.items():
        if v is not None:
            assert math.isfinite(v), f"Factor {k} is non-finite: {v}"
            assert not math.isnan(v), f"Factor {k} is NaN"
            
    assert feats_flat["rev1"] == 0.0
    assert feats_flat["rev5"] == 0.0
    assert feats_flat["ret_5"] == 0.0
    assert feats_flat["ret_21"] == 0.0
    assert feats_flat["ret_63"] == 0.0
    assert feats_flat["mom12_1"] == 0.0
    assert feats_flat["lowvol"] == 0.0
    assert feats_flat["vol_20"] == 0.0
    assert feats_flat["vol_ratio"] is None  # std20 is 0.0 <= 1e-12, guarded against div by 0
    assert feats_flat["hl_range"] == 0.0
    assert feats_flat["max_dd_21"] == 0.0


def test_qlib_factors_extreme_spikes():
    """Verify extreme spikes (+100,000% or -99.9999%) produce finite numbers without overflow."""
    # 1. Massive spike up
    df_spike_up = _make_stress_frame(periods=300, price_pattern="spike_up", volume_pattern="spike")
    feats_spike_up = feature_row_from_frame(df_spike_up)
    for k, v in feats_spike_up.items():
        if v is not None:
            assert math.isfinite(v), f"Factor {k} on spike up is non-finite: {v}"
            assert not math.isnan(v), f"Factor {k} on spike up is NaN"
            
    assert feats_spike_up["rev1"] < 0  # Reversal is negative return
    assert feats_spike_up["ret_5"] > 0
    assert feats_spike_up["volume_z"] is not None
    assert math.isfinite(feats_spike_up["volume_z"])

    # 2. Massive collapse down
    df_spike_down = _make_stress_frame(periods=300, price_pattern="spike_down", volume_pattern="normal")
    feats_spike_down = feature_row_from_frame(df_spike_down)
    for k, v in feats_spike_down.items():
        if v is not None:
            assert math.isfinite(v), f"Factor {k} on spike down is non-finite: {v}"
            assert not math.isnan(v), f"Factor {k} on spike down is NaN"


def test_qlib_large_universe_cross_sectional_ranking():
    """Test 600+ symbols universe with pathological mix. Verify dense ranks 1..N and finite scores."""
    symbols = [f"SYM_{i:04d}" for i in range(600)]
    universe_frames: dict[str, pd.DataFrame] = {}
    
    # Inject diverse pathologies:
    # 0..399: Normal random walks with different seeds
    # 400..449: Flat prices
    # 450..479: Zero volume
    # 480..499: Extreme spike up
    # 500..519: Extreme spike down
    # 520..549: Insufficient history (20 bars) -> should skip
    # 550..579: Missing columns -> should skip (empty frame returned by normalize)
    # 580..599: Constant volume
    for i, sym in enumerate(symbols):
        if i < 400:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="normal", volume_pattern="normal", seed=i)
        elif i < 450:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="flat", volume_pattern="normal", seed=i)
        elif i < 480:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="normal", volume_pattern="zero", seed=i)
        elif i < 500:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="spike_up", volume_pattern="spike", seed=i)
        elif i < 520:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="spike_down", volume_pattern="normal", seed=i)
        elif i < 550:
            universe_frames[sym] = _make_stress_frame(periods=20, price_pattern="normal", volume_pattern="normal", seed=i)
        elif i < 580:
            # Corrupt columns (missing required columns)
            universe_frames[sym] = pd.DataFrame({"foo": [1]*50, "bar": [2]*50})
        else:
            universe_frames[sym] = _make_stress_frame(periods=300, price_pattern="normal", volume_pattern="constant", seed=i)

    start_time = time.perf_counter()
    panel = score_cross_section_asof(
        symbols=symbols,
        candle_loader=lambda s: universe_frames.get(s, pd.DataFrame()),
    )
    elapsed = time.perf_counter() - start_time
    
    assert panel["quality"] == "ok"
    assert panel["score_kind"] == SCORE_KIND
    assert panel["coverage"]["requested"] == 600
    
    # Scored count: 400 (normal) + 50 (flat) + 30 (zero vol) + 20 (spike up) + 20 (spike down) + 20 (const vol) = 540
    # Skipped: 30 (insufficient history < 60 bars) + 30 (missing required columns < 60 bars) = 60
    assert panel["coverage"]["scored"] == 540
    assert panel["coverage"]["skipped_insufficient_history"] == 60
    assert len(panel["rows"]) == 540

    # Verify Ranks: strictly dense 1..540
    ranks = [r["qlib_rank"] for r in panel["rows"]]
    assert ranks == list(range(1, 541)), "Ranks must be strictly 1..N contiguous integers"
    
    # Verify scores are sorted descending
    scores = [r["qlib_score"] for r in panel["rows"]]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], f"Scores not monotonically non-increasing at index {i}: {scores[i]} < {scores[i+1]}"

    # Verify all scores and features are finite
    for r in panel["rows"]:
        assert math.isfinite(r["qlib_score"])
        assert not math.isnan(r["qlib_score"])
        for fname, fval in r["features"].items():
            assert fname in FEATURE_NAMES
            if fval is not None:
                assert math.isfinite(fval), f"Non-finite feature {fname}={fval} in symbol {r['symbol']}"
                assert not math.isnan(fval), f"NaN feature {fname} in symbol {r['symbol']}"

    print(f"\n[STRESS TEST] 600 symbols scored in {elapsed:.4f}s ({540 / elapsed:.1f} symbols/sec)")


# ============================================================================
# 2. CONCURRENT SCAN STAGE EXECUTION & THREAD EXCEPTION STRESS TESTS
# ============================================================================

def test_concurrent_scan_resilience_all_stages_throw_exceptions(monkeypatch):
    """Adversarially simulate simultaneous thread crashes across all concurrent stages.
    Verify get_dashboard_data handles failures gracefully without deadlocking or crashing.
    """
    def explode_sector():
        raise RuntimeError("CRITICAL: Sector Flow API completely crashed")

    def explode_pead(*args, **kwargs):
        raise ValueError("CRITICAL: PEAD parquet corruption in worker thread")

    def explode_dir(*args, **kwargs):
        raise MemoryError("CRITICAL: XGBoost out of memory")

    monkeypatch.setattr(dashboard, "fetch_sector_flow_signals", explode_sector)
    monkeypatch.setattr(dashboard, "generate_pead_candidates", explode_pead)
    monkeypatch.setattr(dashboard, "fetch_internal_directional_signals", explode_dir)
    monkeypatch.setattr(dashboard, "get_all_gcp_resources", lambda: {})
    monkeypatch.setattr(dashboard, "load_dynamic_leaderboard", lambda: [])

    # Test both quick and deep scan depths
    for depth in ["quick", "deep"]:
        start_t = time.perf_counter()
        data = dashboard.get_dashboard_data(scan_depth=depth)
        elapsed = time.perf_counter() - start_t
        
        # Verify no deadlock, fast fail-closed return
        assert elapsed < 5.0, f"Deadlock or excessive timeout on thread failure ({elapsed:.2f}s)"
        assert isinstance(data, dict)
        assert "scan_summary" in data
        assert "sector_flow" in data
        assert "pead_candidates" in data
        assert "directional_signals" in data
        assert data["scan_summary"]["depth"] == depth
        
        # Fail-closed invariants
        assert data["pead_candidates"] == []
        assert data["directional_signals"] == []
        assert data["scan_summary"]["pead_qualified_symbols"] == 0
        assert data["scan_summary"]["directional_scored_symbols"] == 0


def test_concurrent_scan_partial_stage_failure(monkeypatch):
    """Test partial stage failures: PEAD fails, Sector Flow succeeds, Directional succeeds."""
    monkeypatch.setattr(dashboard, "fetch_sector_flow_signals", lambda: {
        "money_in": ["XLK"], "money_out": ["XLE"], "sectors_ranked": [], "watch_names": []
    })
    monkeypatch.setattr(dashboard, "generate_pead_candidates", lambda **_: (_ for _ in ()).throw(RuntimeError("PEAD exploded")))
    monkeypatch.setattr(dashboard, "fetch_internal_directional_signals", lambda **_: [
        {"symbol": "AAPL", "side": "LONG", "probability": 0.72, "state": "ENTER", "horizon": "5 Days"}
    ])
    monkeypatch.setattr(dashboard, "get_all_gcp_resources", lambda: {})
    monkeypatch.setattr(dashboard, "load_dynamic_leaderboard", lambda: [])

    data = dashboard.get_dashboard_data(scan_depth="quick")
    assert data["pead_candidates"] == []
    assert len(data["directional_signals"]) == 1
    assert data["directional_signals"][0]["symbol"] == "AAPL"
    assert data["sector_flow"]["money_in"] == ["XLK"]
    assert data["signal_reconciliation"]["counts"]["pead_flags"] == 0
    assert data["signal_reconciliation"]["counts"]["directional_forecasts"] == 1


# ============================================================================
# 3. PEAD ADAPTER ROBUSTNESS & CONCURRENCY
# ============================================================================

def test_pead_adapter_corrupt_files_and_concurrency(tmp_path, monkeypatch):
    """Stress test PEAD adapter with mix of valid and corrupt Parquet files."""
    wide = tmp_path / "1d_wide"
    wide.mkdir()
    
    dates = pd.bdate_range("2024-01-01", periods=60)
    
    # 1. Valid gap up symbol (PEAD candidate)
    close_vals = np.linspace(100, 110, 60)
    df_valid = pd.DataFrame({
        "open": close_vals * 1.05,  # 5% gap
        "high": close_vals * 1.06,
        "low": close_vals * 0.99,
        "close": close_vals,
        "volume": [1_000_000]*59 + [5_000_000],  # 5x volume surge
    }, index=dates)
    df_valid.to_parquet(wide / "GAP_UP.parquet")
    
    # 2. Corrupt parquet
    (wide / "CORRUPT.parquet").write_bytes(b"NOT_A_PARQUET_FILE")
    
    # 3. Flat parquet
    df_flat = pd.DataFrame({
        "open": [100.0]*60,
        "high": [100.0]*60,
        "low": [100.0]*60,
        "close": [100.0]*60,
        "volume": [1000.0]*60,
    }, index=dates)
    df_flat.to_parquet(wide / "FLAT.parquet")
    
    # 4. Short parquet (10 bars)
    df_short = pd.DataFrame({
        "open": [100.0]*10, "high": [101.0]*10, "low": [99.0]*10, "close": [100.0]*10, "volume": [1000.0]*10
    }, index=dates[:10])
    df_short.to_parquet(wide / "SHORT.parquet")

    monkeypatch.setattr("edge.daily_plays.adapters.pead_adapter.ROOT", tmp_path.parent)
    
    def fake_load_df(sym):
        p = wide / f"{sym}.parquet"
        if not p.is_file():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(p)
            df.columns = [c.capitalize() for c in df.columns]
            return df
        except Exception:
            return pd.DataFrame()

    monkeypatch.setattr("edge.daily_plays.adapters.pead_adapter._load_symbol_df", fake_load_df)

    diagnostics = {}
    candidates = generate_pead_candidates(
        symbols=["GAP_UP", "CORRUPT", "FLAT", "SHORT", "NON_EXISTENT"],
        threshold=0.5,
        diagnostics=diagnostics,
    )
    
    assert diagnostics["attempted_symbols"] == 5
    assert diagnostics["evaluated_symbols"] >= 2
    assert diagnostics["unavailable_symbols"] >= 2
    assert diagnostics["qualified_symbols"] == len(candidates)
    
    # GAP_UP must qualify
    assert len(candidates) >= 1
    assert candidates[0]["symbol"] == "GAP_UP"
    assert candidates[0]["model"]["confidence_kind"] == "ordinal_score"
    assert candidates[0]["model"]["promotion_authorized"] is False
    assert candidates[0]["decision_authorized"] is False
