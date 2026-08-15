"""Adversarial stress-test and empirical validation suite for Milestone 3.

Validates:
1. Mathematical equivalence & zero numeric drift across horizons (5, 10, 20)
2. Fail-closed behavior on short history, NaNs, Infs, zeroes, stale/future timestamps
3. Compute and latency reduction benchmarks (single symbol and 100-symbol universe)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

import numpy as np
import pandas as pd
import pytest

try:
    from edge.daily_plays.adapters.internal_models import (
        BASELINE_MODEL_ID,
        DEFAULT_DAILY_DATA_PATH,
        DEFAULT_UNIVERSE_PATH,
        PROBABILITY_TARGET,
        TARGET_HORIZON_DAYS,
        ChainFreeInternalModelsAdapter,
        _baseline_signal,
        _daily_asof,
        _frame,
        _load_v90_engine,
        _local_daily_candles,
        _v90_base_predict,
        _v90_signal,
        _v90_signal_from_base,
        _weekday_session_age,
    )
    from edge.daily_plays.clock import RunContext
except ImportError:
    from daily_plays.adapters.internal_models import (
        BASELINE_MODEL_ID,
        DEFAULT_DAILY_DATA_PATH,
        DEFAULT_UNIVERSE_PATH,
        PROBABILITY_TARGET,
        TARGET_HORIZON_DAYS,
        ChainFreeInternalModelsAdapter,
        _baseline_signal,
        _daily_asof,
        _frame,
        _load_v90_engine,
        _local_daily_candles,
        _v90_base_predict,
        _v90_signal,
        _v90_signal_from_base,
        _weekday_session_age,
    )
    from daily_plays.clock import RunContext


ASOF = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)



def _reference_un_deduplicated_v90_signal(symbol: str, frame: pd.DataFrame, horizon_days: int) -> dict[str, Any] | None:
    """The un-deduplicated reference implementation that extracts features and runs

    XGBoost booster inference independently for each horizon call.
    """
    engine = _load_v90_engine()
    if engine is None:
        return None
    try:
        code = f"{symbol}.US" if not symbol.endswith(".US") else symbol
        feats = engine._feat.build_features(frame).dropna()
        if feats.empty:
            return None

        raw_long = engine._predict(engine._long_model, feats)
        raw_short = engine._predict(engine._short_model, feats)
        cal_long = engine._cal_long.apply(raw_long)
        cal_short = engine._cal_short.apply(raw_short)

        rl = float(raw_long[-1])
        rs = float(raw_short[-1])
        cl = float(cal_long[-1])
        cs = float(cal_short[-1])

        thr_hi = float(getattr(engine, "_enter_hi", 0.5833))
        thr_lo = float(getattr(engine, "_enter_lo", 0.5662))

        if rl >= rs and rl >= thr_lo:
            side = "long"
            raw_score = rl
            prob = cl
            setup_ok = True
        elif rs > rl and rs >= thr_lo:
            side = "short"
            raw_score = -rs
            prob = cs
            setup_ok = True
        else:
            side = "long" if rl >= rs else "short"
            raw_score = rl if side == "long" else -rs
            prob = cl if side == "long" else cs
            setup_ok = False

        raw_diff = (rl - thr_hi) if side == "long" else (rs - thr_hi)
        smooth_adj = 0.05 * float(np.tanh(raw_diff * 6.0))
        base_prob = prob if prob > 0 else 0.52

        horizon_mult = 1.0 if horizon_days == 5 else (0.96 if horizon_days == 10 else 0.92)
        calibrated_prob = float(np.clip((base_prob + smooth_adj) * horizon_mult, 0.35, 0.88))
        return {
            "side": side,
            "setup_ok": setup_ok,
            "raw_score": raw_score * horizon_mult,
            "calibrated_probability": calibrated_prob,
            "model_id": "v90_meta_confidence_wide",
            "horizon_days": horizon_days,
        }
    except Exception:
        return None


def generate_synthetic_ohlcv(
    n_bars: int = 100,
    start_price: float = 150.0,
    drift: float = 0.001,
    vol: float = 0.02,
    asof: datetime = ASOF,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV dataframe."""
    np.random.seed(seed)
    # Generate business days up to asof
    end_date = asof.date()
    dates = []
    curr = end_date
    while len(dates) < n_bars:
        if curr.weekday() < 5:
            dates.append(curr)
        curr -= timedelta(days=1)
    dates.reverse()

    idx = pd.DatetimeIndex([datetime(d.year, d.month, d.day, 20, 0, tzinfo=timezone.utc) for d in dates])
    
    returns = np.random.normal(drift, vol, n_bars)
    prices = start_price * np.exp(np.cumsum(returns))
    
    highs = prices * (1.0 + np.abs(np.random.normal(0, vol * 0.5, n_bars)))
    lows = prices * (1.0 - np.abs(np.random.normal(0, vol * 0.5, n_bars)))
    opens = prices * (1.0 + np.random.normal(0, vol * 0.2, n_bars))
    closes = prices
    volumes = np.random.randint(100_000, 5_000_000, n_bars)

    # ensure high >= max(open, close), low <= min(open, close)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=idx)


# =========================================================================
# 1. Mathematical Equivalence & Zero Drift Tests
# =========================================================================

def test_v90_signal_zero_numeric_drift_synthetic():
    """Verify zero numeric drift between deduplicated base prediction and un-deduplicated reference."""
    synthetic_configs = [
        {"drift": 0.005, "vol": 0.015, "seed": 101, "desc": "bullish_lowvol"},
        {"drift": -0.005, "vol": 0.025, "seed": 202, "desc": "bearish_highvol"},
        {"drift": 0.0, "vol": 0.01, "seed": 303, "desc": "flat_lowvol"},
        {"drift": 0.002, "vol": 0.04, "seed": 404, "desc": "volatile_uptrend"},
        {"drift": -0.003, "vol": 0.035, "seed": 505, "desc": "volatile_downtrend"},
    ]

    for cfg in synthetic_configs:
        df = generate_synthetic_ohlcv(n_bars=120, drift=cfg["drift"], vol=cfg["vol"], seed=cfg["seed"])
        base = _v90_base_predict("SYNTH", df)
        assert base is not None, f"Failed base predict for {cfg['desc']}"

        for h in TARGET_HORIZON_DAYS:
            ref = _reference_un_deduplicated_v90_signal("SYNTH", df, h)
            dedup = _v90_signal_from_base(base, h)
            direct = _v90_signal("SYNTH", df, h)

            assert ref is not None
            assert direct is not None
            assert dedup == direct, f"Dedup vs Direct mismatch for {cfg['desc']} horizon {h}"

            # Exact equality assertions (zero drift)
            assert ref["side"] == dedup["side"]
            assert ref["setup_ok"] == dedup["setup_ok"]
            assert ref["model_id"] == dedup["model_id"]
            assert ref["horizon_days"] == dedup["horizon_days"]
            assert math.isclose(ref["raw_score"], dedup["raw_score"], abs_tol=1e-12)
            assert math.isclose(ref["calibrated_probability"], dedup["calibrated_probability"], abs_tol=1e-12)
            assert 0.35 <= dedup["calibrated_probability"] <= 0.88


def test_v90_signal_zero_numeric_drift_real_parquets():
    """Verify zero numeric drift on 30 real market parquet files."""
    real_symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "COST",
                    "JPM", "BAC", "XOM", "CVX", "LLY", "UNH", "CAT", "GE", "NFLX", "QCOM",
                    "INTC", "TXN", "HON", "IBM", "AMAT", "MU", "PANW", "CRWD", "NOW", "PLTR"]
    data_path = Path("data/1d")
    available_symbols = [s for s in real_symbols if (data_path / f"{s}.parquet").exists()]
    assert len(available_symbols) >= 20, f"Expected at least 20 real parquets, found {len(available_symbols)}"

    for sym in available_symbols:
        raw_df = pd.read_parquet(data_path / f"{sym}.parquet")
        frame = _frame(raw_df)
        assert not frame.empty, f"Empty frame for {sym}"

        base = _v90_base_predict(sym, frame)
        assert base is not None, f"Failed base predict for real symbol {sym}"

        for h in TARGET_HORIZON_DAYS:
            ref = _reference_un_deduplicated_v90_signal(sym, frame, h)
            dedup = _v90_signal_from_base(base, h)
            direct = _v90_signal(sym, frame, h)

            assert ref is not None
            assert direct is not None
            assert dedup == direct

            assert ref["side"] == dedup["side"]
            assert ref["setup_ok"] == dedup["setup_ok"]
            assert math.isclose(ref["raw_score"], dedup["raw_score"], abs_tol=1e-12)
            assert math.isclose(ref["calibrated_probability"], dedup["calibrated_probability"], abs_tol=1e-12)


def test_chain_free_adapter_model_parity_and_contracts(tmp_path):
    """Verify that ChainFreeInternalModelsAdapter produces compliant, fully aligned contracts."""
    data_path = Path("data/1d")
    test_symbols = ["AAPL", "NVDA", "TSLA"]
    
    universe_file = tmp_path / "test_uni.json"
    universe_file.write_text(json.dumps({"symbols": test_symbols}))

    adapter = ChainFreeInternalModelsAdapter(
        universe_path=universe_file,
        data_path=data_path,
        candidate_limit=10,
    )

    ctx = RunContext.create(asof_utc=ASOF)
    results = list(adapter(context=ctx))

    assert len(results) == len(test_symbols) * 3, f"Expected {len(test_symbols) * 3} results, got {len(results)}"

    for row in results:
        sym = row["symbol"]
        model = row["model"]
        horizon = model["horizon_days"]

        # Check required contract invariants
        assert row["source"] == "local_daily_chain_free_baseline"
        assert row["freshness"]["source"] == "local_daily_parquet"
        assert model["id"] == "v90_meta_confidence_wide"
        assert model["confidence_kind"] == "calibrated_probability"
        assert model["probability_target"] == PROBABILITY_TARGET
        assert model["calibration_version"] == "v90_wide_isotonic_v1"
        assert model["probability"] is not None
        assert 0.35 <= model["probability"] <= 0.88
        assert model["state"] in ("ENTER", "WATCH")
        if model["probability"] >= 0.60:
            assert model["state"] == "ENTER"
        else:
            assert model["state"] == "WATCH"

        # Verify exact mathematical agreement with direct v90 signal
        raw_df = pd.read_parquet(data_path / f"{sym}.parquet")
        expected_signal = _v90_signal(sym, _frame(raw_df), horizon)
        assert expected_signal is not None
        assert math.isclose(model["probability"], expected_signal["calibrated_probability"], abs_tol=1e-12)
        assert math.isclose(model["raw_score"], expected_signal["raw_score"], abs_tol=1e-12)
        assert row["side"] == expected_signal["side"]
        assert row["setup_ok"] == expected_signal["setup_ok"]


# =========================================================================
# 2. Short History & Edge Case Fail-Closed Tests
# =========================================================================

@pytest.mark.parametrize("n_bars", [0, 1, 5, 10, 19])
def test_short_history_under_20_bars_fails_closed(n_bars):
    """Verify frames with < 20 bars fail closed gracefully (base returns None, baseline raises)."""
    if n_bars == 0:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    else:
        df = generate_synthetic_ohlcv(n_bars=n_bars)

    # v90 feature extractor requires at least rolling window lookback (~20-30 bars)
    base = _v90_base_predict("SHORT", df)
    # v90 features will dropna to empty or fail -> returns None
    assert base is None

    # Baseline signal must raise ValueError("insufficient_daily_candles")
    if n_bars > 0:
        for h in TARGET_HORIZON_DAYS:
            with pytest.raises(ValueError, match="insufficient_daily_candles"):
                _baseline_signal(df, horizon_days=h)


def test_history_boundary_at_20_and_21_bars():
    """Verify 20 and 21 bar boundaries for baseline and v90."""
    df20 = generate_synthetic_ohlcv(n_bars=20)
    # Baseline for horizon 5 with 20 bars: lookback=20, len=20 < 20+1 -> raises
    with pytest.raises(ValueError, match="insufficient_daily_candles"):
        _baseline_signal(df20, horizon_days=5)

    df21 = generate_synthetic_ohlcv(n_bars=21)
    # Baseline for horizon 5 with 21 bars: lookback=20, len=21 >= 21 -> succeeds!
    sig5 = _baseline_signal(df21, horizon_days=5)
    assert "raw_score" in sig5
    assert "volatility" in sig5

    # Horizon 20 with 21 bars: lookback=max(20, 20)=20, len=21 >= 21 -> succeeds!
    sig20 = _baseline_signal(df21, horizon_days=20)
    assert "raw_score" in sig20


def test_standard_60_bars_and_252_bars_succeed_across_all_horizons(tmp_path):
    """Verify 60-bar (short history fallback) and 252-bar (full history) frames evaluate across all horizons."""
    # 1. 60-bar frame:
    # Baseline signal evaluates directly on all horizons (5, 10, 20)
    df60 = generate_synthetic_ohlcv(n_bars=60)
    for h in TARGET_HORIZON_DAYS:
        sig = _baseline_signal(df60, horizon_days=h)
        assert sig["volatility"] > 0
        assert math.isfinite(sig["raw_score"])
        assert sig["side"] in ("long", "short", "neutral")

    # v90 feature engineering requires ~70 bars, so 60 bars gracefully returns None
    assert _v90_base_predict("SHORT_60", df60) is None

    # ChainFreeInternalModelsAdapter gracefully falls back to baseline for 60-bar symbols
    uni60 = tmp_path / "uni60.json"
    uni60.write_text(json.dumps({"symbols": ["SHORT_60"]}))
    adapter60 = ChainFreeInternalModelsAdapter(
        universe_path=uni60,
        candle_fetcher=lambda sym, **kw: df60,
        candidate_limit=5,
    )
    rows60 = list(adapter60(context=RunContext.create(asof_utc=ASOF)))
    assert len(rows60) == 3
    assert [r["model"]["horizon_days"] for r in rows60] == [5, 10, 20]
    assert all(r["model"]["confidence_kind"] == "ordinal_score" for r in rows60)
    assert all(r["model"]["probability"] is None for r in rows60)

    # 2. 252-bar frame (full year of daily history):
    # Evaluates both baseline and v90 wide model across all horizons
    df252 = generate_synthetic_ohlcv(n_bars=252)
    for h in TARGET_HORIZON_DAYS:
        sig = _baseline_signal(df252, horizon_days=h)
        assert sig["volatility"] > 0
        assert math.isfinite(sig["raw_score"])

    base252 = _v90_base_predict("FULL_252", df252)
    assert base252 is not None
    for h in TARGET_HORIZON_DAYS:
        v90_sig = _v90_signal_from_base(base252, h)
        assert v90_sig["calibrated_probability"] is not None
        assert 0.35 <= v90_sig["calibrated_probability"] <= 0.88



def test_nan_values_fail_closed_gracefully():
    """Verify frames with NaN values in various positions fail closed or handle cleanly."""
    base_df = generate_synthetic_ohlcv(n_bars=100)

    # 1. NaN at last bar (close) -> _frame cleans or drops, or v90 drops
    df_nan_end = base_df.copy()
    df_nan_end.iloc[-1, df_nan_end.columns.get_loc("close")] = np.nan
    cleaned = _frame(df_nan_end)
    assert len(cleaned) == 99

    # 2. NaN in middle of series
    df_nan_mid = base_df.copy()
    df_nan_mid.iloc[50, df_nan_mid.columns.get_loc("open")] = np.nan
    cleaned_mid = _frame(df_nan_mid)
    assert len(cleaned_mid) == 99

    # 3. Entirely NaN frame -> returns empty dataframe
    df_all_nan = pd.DataFrame(np.nan, index=base_df.index, columns=base_df.columns)
    cleaned_all_nan = _frame(df_all_nan)
    assert cleaned_all_nan.empty
    assert _v90_base_predict("ALLNAN", cleaned_all_nan) is None


def test_infinite_and_zero_volatility_fail_closed():
    """Verify infinite values and zero volatility fail closed safely."""
    # Constant price -> zero volatility
    dates = pd.date_range("2026-06-01", periods=50, freq="D", tz=timezone.utc)
    flat_df = pd.DataFrame({
        "open": [100.0] * 50,
        "high": [100.0] * 50,
        "low": [100.0] * 50,
        "close": [100.0] * 50,
        "volume": [1000] * 50,
    }, index=dates)

    with pytest.raises(ValueError, match="invalid_realized_volatility"):
        _baseline_signal(flat_df, horizon_days=5)

    # Inf in close
    inf_df = flat_df.copy()
    inf_df.iloc[-1, inf_df.columns.get_loc("close")] = np.inf
    # v90 feature builder / predict handles or returns None gracefully without crash
    res = _v90_base_predict("INF", inf_df)
    # Either None or handles smoothly
    if res is not None:
        assert math.isfinite(res["base_prob"])


def test_future_and_stale_candle_validation():
    """Verify future candle (> asof) and stale candle (> max_age_days) fail closed."""
    df = generate_synthetic_ohlcv(n_bars=60, asof=ASOF)
    ctx = RunContext.create(asof_utc=ASOF)

    # Valid candle asof
    last_dt = _daily_asof(df, context=ctx, max_age_days=3)
    assert last_dt <= ASOF

    # Future candle
    future_df = generate_synthetic_ohlcv(n_bars=60, asof=ASOF + timedelta(days=5))
    with pytest.raises(ValueError, match="future_candle"):
        _daily_asof(future_df, context=ctx, max_age_days=3)

    # Stale candle (7 business days old)
    stale_df = generate_synthetic_ohlcv(n_bars=60, asof=ASOF - timedelta(days=12))
    with pytest.raises(ValueError, match="stale_candle"):
        _daily_asof(stale_df, context=ctx, max_age_days=3)


def test_adapter_gracefully_records_missing_symbol_warnings(tmp_path):
    """Verify adapter records warning and does not crash when symbol parquet is missing."""
    uni = tmp_path / "uni.json"
    uni.write_text(json.dumps({"symbols": ["NONEXISTENT_XYZ"]}))

    adapter = ChainFreeInternalModelsAdapter(
        universe_path=uni,
        data_path=Path("data/1d"),
    )
    results = list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert len(results) == 0
    assert len(adapter.last_warnings) == 1
    assert "internal_model_unavailable:NONEXISTENT_XYZ" in adapter.last_warnings[0]


# =========================================================================
# 3. Latency & Compute Reduction Benchmark
# =========================================================================

def run_performance_benchmarks():
    """Empirically benchmark single symbol and 100-symbol universe latency."""
    data_path = Path("data/1d")
    real_files = sorted(data_path.glob("*.parquet"))
    symbols = [p.stem for p in real_files][:100]
    assert len(symbols) >= 50, f"Expected at least 50 symbols for benchmark, found {len(symbols)}"

    print("\n" + "="*70)
    print("EMPIRICAL BENCHMARK: Directional Momentum Model Horizon Deduplication")
    print("="*70)

    # Warm up engine cache
    first_frame = _frame(pd.read_parquet(real_files[0]))
    _v90_base_predict(symbols[0], first_frame)

    # 1. Single Symbol Benchmark (Repeated 50 times)
    n_runs_single = 50
    test_sym = symbols[0]
    test_frame = first_frame

    # Time un-deduplicated
    t0 = time.perf_counter()
    for _ in range(n_runs_single):
        for h in TARGET_HORIZON_DAYS:
            _reference_un_deduplicated_v90_signal(test_sym, test_frame, h)
    t_single_undedup = (time.perf_counter() - t0) / n_runs_single

    # Time deduplicated (base predict + 3 horizon scalings)
    t0 = time.perf_counter()
    for _ in range(n_runs_single):
        base = _v90_base_predict(test_sym, test_frame)
        for h in TARGET_HORIZON_DAYS:
            _v90_signal_from_base(base, h)
    t_single_dedup = (time.perf_counter() - t0) / n_runs_single

    single_speedup = t_single_undedup / t_single_dedup
    single_reduction = (1.0 - t_single_dedup / t_single_undedup) * 100

    print(f"\n[Single Symbol ({test_sym}) - 3 Horizons (5, 10, 20)]")
    print(f"  Un-deduplicated (3x full inference) : {t_single_undedup * 1000:.3f} ms / symbol")
    print(f"  Deduplicated (1 base + 3x scale)    : {t_single_dedup * 1000:.3f} ms / symbol")
    print(f"  Speedup Factor                      : {single_speedup:.2f}x")
    print(f"  Compute Time Reduction              : {single_reduction:.1f}%")

    # 2. Multi-Symbol Universe Benchmark (100 symbols or max available)
    n_universe = len(symbols)
    frames = [(_sym, _frame(pd.read_parquet(data_path / f"{_sym}.parquet"))) for _sym in symbols]

    # Time full un-deduplicated universe pass
    t0 = time.perf_counter()
    for sym, frm in frames:
        for h in TARGET_HORIZON_DAYS:
            _reference_un_deduplicated_v90_signal(sym, frm, h)
    t_universe_undedup = time.perf_counter() - t0

    # Time full deduplicated universe pass
    t0 = time.perf_counter()
    for sym, frm in frames:
        base = _v90_base_predict(sym, frm)
        for h in TARGET_HORIZON_DAYS:
            _v90_signal_from_base(base, h)
    t_universe_dedup = time.perf_counter() - t0

    univ_speedup = t_universe_undedup / t_universe_dedup
    univ_reduction = (1.0 - t_universe_dedup / t_universe_undedup) * 100

    print(f"\n[Universe ({n_universe} symbols) - 3 Horizons ({n_universe * 3} evaluations)]")
    print(f"  Un-deduplicated Total Time          : {t_universe_undedup:.4f} s ({t_universe_undedup / n_universe * 1000:.2f} ms/sym)")
    print(f"  Deduplicated Total Time             : {t_universe_dedup:.4f} s ({t_universe_dedup / n_universe * 1000:.2f} ms/sym)")
    print(f"  Speedup Factor                      : {univ_speedup:.2f}x")
    print(f"  Compute Time Reduction              : {univ_reduction:.1f}%")
    print("="*70 + "\n")

    return {
        "single_undedup_ms": t_single_undedup * 1000,
        "single_dedup_ms": t_single_dedup * 1000,
        "single_speedup": single_speedup,
        "single_reduction_pct": single_reduction,
        "n_universe": n_universe,
        "universe_undedup_s": t_universe_undedup,
        "universe_dedup_s": t_universe_dedup,
        "universe_speedup": univ_speedup,
        "universe_reduction_pct": univ_reduction,
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
    bench_results = run_performance_benchmarks()
