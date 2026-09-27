"""Empirical Latency Benchmark Suite for Milestone 3 optimizations.

Measures wall-clock time across multiple warm iterations for:
- Directional Model Inference (25 symbols, 59 symbols)
- PEAD Scan (175 symbols)
- Qlib 16-Factor Alpha Scoring (576 symbols)
- Full Dashboard Quick Scan
- Full Dashboard Deep Scan
"""
from __future__ import annotations

import statistics
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if 'edge' not in sys.modules:
    _edge_mod = types.ModuleType('edge')
    _edge_mod.__path__ = [str(ROOT)]
    sys.modules['edge'] = _edge_mod

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daily_plays"))
sys.path.insert(0, str(ROOT / "daily_plays" / "adapters"))
sys.path.insert(0, str(ROOT / "tools"))

from edge.tools.render_dashboard import (
    get_dashboard_data,
    fetch_internal_directional_signals,
    load_directional_model_universe,
)
from edge.daily_plays.adapters.pead_adapter import generate_pead_candidates, _load_broad_universe
from edge.daily_plays.qlib_scan_score import score_cross_section_asof
from edge.daily_plays.live_activity import load_market_symbol_catalog


def measure_latencies(fn, *args, iterations: int = 5, warmup: int = 1, **kwargs) -> list[float]:
    # Warmup
    for _ in range(warmup):
        fn(*args, **kwargs)
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def run_benchmarks():
    print("=" * 70)
    print("MILESTONE 3 LATENCY BENCHMARK HARNESS")
    print("=" * 70)

    # 1. Directional model inference
    dir_universe = load_directional_model_universe()
    print("\n[1/5] Benchmarking Directional Models (59 names)...")
    dir_times_59 = measure_latencies(fetch_internal_directional_signals, candidate_limit=len(dir_universe), iterations=5)
    mean_dir_59 = statistics.mean(dir_times_59)
    std_dir_59 = statistics.stdev(dir_times_59)
    print(f"  Directional (59 names): mean={mean_dir_59:.4f}s, std={std_dir_59:.4f}s, runs={[round(x, 4) for x in dir_times_59]}")

    print("\n[2/5] Benchmarking Directional Models (25 names, Quick limit)...")
    dir_times_25 = measure_latencies(fetch_internal_directional_signals, candidate_limit=25, iterations=5)
    mean_dir_25 = statistics.mean(dir_times_25)
    std_dir_25 = statistics.stdev(dir_times_25)
    print(f"  Directional (25 names): mean={mean_dir_25:.4f}s, std={std_dir_25:.4f}s, runs={[round(x, 4) for x in dir_times_25]}")

    # 2. PEAD Scan
    broad = _load_broad_universe()
    print(f"\n[3/5] Benchmarking PEAD Scan ({len(broad)} broad universe names)...")
    pead_times = measure_latencies(generate_pead_candidates, symbols=broad, iterations=5)
    mean_pead = statistics.mean(pead_times)
    std_pead = statistics.stdev(pead_times)
    print(f"  PEAD ({len(broad)} names): mean={mean_pead:.4f}s, std={std_pead:.4f}s, runs={[round(x, 4) for x in pead_times]}")

    # 3. Qlib Cross-Sectional Scoring
    catalog = load_market_symbol_catalog(data_dirs=(ROOT / "data" / "1d_wide", ROOT / "data" / "1d"))
    print(f"\n[4/5] Benchmarking Qlib 16-Factor Alpha Scoring ({len(catalog)} catalog names)...")
    qlib_times = measure_latencies(
        score_cross_section_asof,
        symbols=catalog,
        data_dirs=(ROOT / "data" / "1d_wide", ROOT / "data" / "1d"),
        iterations=5,
    )
    mean_qlib = statistics.mean(qlib_times)
    std_qlib = statistics.stdev(qlib_times)
    print(f"  Qlib ({len(catalog)} names): mean={mean_qlib:.4f}s, std={std_qlib:.4f}s, runs={[round(x, 4) for x in qlib_times]}")

    # 4. Full Dashboard Quick Scan
    print("\n[5/5] Benchmarking Full Dashboard Quick Scan...")
    dash_quick_times = measure_latencies(
        get_dashboard_data,
        scan_depth="quick",
        include_gcp_resources=False,
        iterations=5,
    )
    mean_dash_quick = statistics.mean(dash_quick_times)
    std_dash_quick = statistics.stdev(dash_quick_times)
    print(f"  Dashboard Quick: mean={mean_dash_quick:.4f}s, std={std_dash_quick:.4f}s, runs={[round(x, 4) for x in dash_quick_times]}")

    # Baseline comparison
    baselines = {
        "Directional (59 symbols)": {"baseline": 0.3583, "optimized": mean_dir_59},
        "PEAD (175 symbols)": {"baseline": 0.7492, "optimized": mean_pead},
        "Qlib Scoring (576 symbols)": {"baseline": 6.0473, "optimized": mean_qlib},
        "Full Dashboard Quick Scan": {"baseline": 1.5297, "optimized": mean_dash_quick},
    }

    print("\n" + "=" * 70)
    print("FINAL BENCHMARK COMPARISON TABLE")
    print("=" * 70)
    print(f"{'Component':<32} | {'Baseline':<10} | {'Optimized':<10} | {'Speedup':<10} | {'Latency Reduction':<18}")
    print("-" * 90)
    for name, data in baselines.items():
        base = data["baseline"]
        opt = data["optimized"]
        speedup = base / opt if opt > 0 else float("inf")
        reduction = (base - opt) / base * 100 if base > 0 else 0.0
        print(f"{name:<32} | {base:.4f}s    | {opt:.4f}s    | {speedup:.2f}x      | {reduction:+.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmarks()
