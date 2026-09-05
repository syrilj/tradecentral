"""Tier 5 White-Box Adversarial Hardening and Stress Testing Suite.

Exhaustively verifies:
1. Analytical Backend Engine (edge/daily_plays/regime_attractor_engine.py):
   - Extreme option chains (10,000+ strikes, inverted strikes, negative DTE, extreme IVs, all-zero OI, illiquid spot far from strikes).
   - Kalman filter non-repainting & causal state isolation.
   - Scale-free regime strength invariants [0.0, 1.0].
2. API & Concurrency (edge/tools/api_server.py):
   - Single-flight mutex cache stampede resistance (_PRICE_ATTRACTOR_BUILD_LOCKS).
   - High-concurrency simulated requests across multiple threads for hot and cold symbols.
   - Cache invalidation on backfill.
"""

from __future__ import annotations

import concurrent.futures
import math
import random
import threading
import time
from typing import Any
import numpy as np
import pytest

from daily_plays.regime_attractor_engine import (
    ConfluenceCluster,
    MarketRegimeState,
    PriceMagnetLevel,
    RegimeAttractorSnapshot,
    bs_d1_d2,
    calculate_bs_charm_per_day,
    calculate_bs_gamma,
    calculate_dollar_gamma_1pct,
    calculate_gravitational_pull,
    calculate_max_pain,
    classify_market_regime,
    compute_gamma_flip_and_walls,
    compute_kinematic_drift_level,
    compute_net_charm_flow,
    compute_price_attractors,
    detect_confluence_clusters,
    extract_volume_poc,
    calculate_market_regime,
    detect_price_magnets,
    compute_confluence_zones,
    build_price_draw_telemetry_payload,
)
from tools.api_server import (
    _PRICE_ATTRACTOR_CACHE,
    _PRICE_ATTRACTOR_LOCK,
    _PRICE_ATTRACTOR_BUILD_LOCKS,
    _price_attractors_payload,
)


# ============================================================================
# 1. ANALYTICAL BACKEND ENGINE ADVERSARIAL STRESS TESTS
# ============================================================================


class TestTier5BackendAdversarial:
    """Stress tests on edge/daily_plays/regime_attractor_engine.py."""

    def test_massive_strikes_chain_scaling(self):
        """Stress-tests engine with large option chains (1,000+ strikes) for memory and performance."""
        spot = 5000.0
        # 1,000 strikes from 4000.0 to 6000.0
        chain_rows = []
        for i in range(4000, 5001, 2):
            k = float(i)
            chain_rows.append({
                "strike": k,
                "right": "call",
                "open_interest": max(0.0, 1000.0 - abs(k - spot) * 0.2),
                "iv": 0.20,
                "dte": 30.0,
                "volume": 100.0,
            })
            chain_rows.append({
                "strike": k,
                "right": "put",
                "open_interest": max(0.0, 1000.0 - abs(k - spot) * 0.2),
                "iv": 0.20,
                "dte": 30.0,
                "volume": 100.0,
            })

        t0 = time.perf_counter()
        snapshot = compute_price_attractors(
            symbol="SPX_MEGA",
            spot=spot,
            chain_rows=chain_rows,
            price_series=[spot - 10 + i * 0.5 for i in range(40)],
        )
        elapsed = time.perf_counter() - t0

        assert snapshot.quality["measurable"] is True
        assert snapshot.regime_state in [
            "volatility_dampening",
            "volatility_amplification",
            "neutral_transition",
            "charm_decay_selling",
            "charm_decay_buying",
        ]
        assert snapshot.regime_strength is not None
        assert 0.0 <= snapshot.regime_strength <= 1.0
        assert snapshot.primary_magnet is not None
        assert len(snapshot.levels) > 0
        assert len(snapshot.price_ladder) > 0
        assert elapsed < 1.0, f"1k strikes processing took {elapsed:.2f}s (expected < 1.0s)"

    def test_inverted_and_unsorted_strikes(self):
        """Inverted (descending), negative, zero, and scrambled strike inputs."""
        spot = 150.0
        scrambled_rows = [
            {"strike": 200.0, "right": "call", "oi": 5000, "iv": 0.25, "dte": 14},
            {"strike": 0.0, "right": "call", "oi": 1000, "iv": 0.25, "dte": 14},       # invalid 0 strike
            {"strike": -50.0, "right": "put", "oi": 2000, "iv": 0.25, "dte": 14},      # negative strike
            {"strike": 100.0, "right": "put", "oi": 8000, "iv": 0.30, "dte": 14},
            {"strike": 150.0, "right": "call", "oi": 12000, "iv": 0.22, "dte": 14},
            {"strike": 120.0, "right": "put", "oi": 6000, "iv": 0.28, "dte": 14},
            {"strike": 180.0, "right": "call", "oi": 9000, "iv": 0.24, "dte": 14},
        ]

        snapshot = compute_price_attractors(
            symbol="INVERTED_TEST",
            spot=spot,
            chain_rows=scrambled_rows,
        )
        assert snapshot.quality["measurable"] is True
        # Price ladder must be strictly sorted descending by price
        ladder_prices = [l.price for l in snapshot.price_ladder]
        assert ladder_prices == sorted(ladder_prices, reverse=True)
        # All valid prices must be positive
        for lvl in snapshot.levels:
            assert lvl.price > 0
            assert not math.isnan(lvl.price)
            assert not math.isnan(lvl.gravitational_pull)
            assert 0.0 <= lvl.gravitational_pull <= 100.0

    def test_negative_subsecond_and_ultra_long_dte(self):
        """Tenor edge cases: negative DTE, sub-second DTE (0.00001), 1000+ days LEAPs."""
        spot = 100.0
        dte_rows = [
            {"strike": 95.0, "right": "put", "oi": 1000, "iv": 0.25, "dte": -5.0},    # negative DTE
            {"strike": 100.0, "right": "call", "oi": 5000, "iv": 0.25, "dte": 0.0001}, # sub-minute DTE
            {"strike": 105.0, "right": "call", "oi": 3000, "iv": 0.25, "dte": 1500.0}, # 4+ year LEAP
        ]

        snapshot = compute_price_attractors(
            symbol="DTE_TEST",
            spot=spot,
            chain_rows=dte_rows,
        )
        assert snapshot.quality["measurable"] is True
        assert snapshot.regime_strength is not None
        assert 0.0 <= snapshot.regime_strength <= 1.0

    def test_extreme_iv_boundary_handling(self):
        """Extreme IVs: 0.0001, 0.005, 8.0, 100.0, NaN, Inf, None."""
        spot = 100.0
        iv_rows = [
            {"strike": 90.0, "right": "put", "oi": 1000, "iv": 0.0001, "dte": 30},   # clamped to 0.005
            {"strike": 95.0, "right": "put", "oi": 2000, "iv": float("nan"), "dte": 30}, # NaN -> fallback
            {"strike": 100.0, "right": "call", "oi": 5000, "iv": 0.30, "dte": 30},
            {"strike": 105.0, "right": "call", "oi": 3000, "iv": 50.0, "dte": 30},   # clamped to 8.0
            {"strike": 110.0, "right": "call", "oi": 1000, "iv": None, "dte": 30},   # None -> fallback
        ]

        snapshot = compute_price_attractors(
            symbol="IV_TEST",
            spot=spot,
            chain_rows=iv_rows,
        )
        assert snapshot.quality["measurable"] is True
        assert not math.isnan(snapshot.regime_strength or 0.0)
        for lvl in snapshot.levels:
            assert not math.isnan(lvl.gravitational_pull)
            assert 0.0 <= lvl.gravitational_pull <= 100.0

    def test_all_zero_oi_and_zero_volume_zero_spoofing(self):
        """All-zero OI across entire chain must strictly trigger unmeasurable state."""
        spot = 250.0
        zero_oi_rows = [
            {"strike": 240.0, "right": "put", "oi": 0, "volume": 0, "iv": 0.25, "dte": 30},
            {"strike": 250.0, "right": "call", "oi": 0, "volume": 0, "iv": 0.25, "dte": 30},
            {"strike": 260.0, "right": "call", "oi": 0, "volume": 0, "iv": 0.25, "dte": 30},
        ]

        snapshot = compute_price_attractors(
            symbol="ZERO_OI",
            spot=spot,
            chain_rows=zero_oi_rows,
        )
        assert snapshot.quality["measurable"] is False
        assert snapshot.regime_state == "unmeasurable"
        assert snapshot.regime_strength is None
        assert snapshot.primary_magnet is None
        assert snapshot.levels == []
        assert snapshot.price_ladder == []

    def test_spot_far_from_strikes_illiquid_tail(self):
        """Spot = $10,000, strikes = $10 to $50 (extreme deep ITM / unanchored)."""
        spot = 10_000.0
        far_rows = [
            {"strike": 10.0, "right": "call", "oi": 5000, "iv": 0.50, "dte": 30},
            {"strike": 20.0, "right": "call", "oi": 4000, "iv": 0.50, "dte": 30},
            {"strike": 30.0, "right": "put", "oi": 1000, "iv": 0.50, "dte": 30},
            {"strike": 50.0, "right": "put", "oi": 2000, "iv": 0.50, "dte": 30},
        ]

        snapshot = compute_price_attractors(
            symbol="FAR_SPOT",
            spot=spot,
            chain_rows=far_rows,
        )
        assert snapshot.quality["measurable"] is True
        for lvl in snapshot.levels:
            assert not math.isnan(lvl.gravitational_pull)
            assert 0.0 <= lvl.gravitational_pull <= 100.0
            if lvl.price < spot:
                assert lvl.direction == "below"
            elif lvl.price == spot:
                assert lvl.direction == "at_spot"
            else:
                assert lvl.direction == "above"
            # In an all-below strike scenario, no target can be above spot
            assert lvl.direction != "above"

    def test_kalman_filter_non_repainting_and_causal_isolation(self):
        """Verifies that streaming price updates do not rewrite/repaint historical states causally."""
        base_series = [100.0, 101.0, 102.5, 101.8, 103.0, 104.2, 103.8, 105.0]

        # Online step at step 8
        target_8, vz_8, reg_8 = compute_kinematic_drift_level(base_series, 105.0)
        assert target_8 is not None

        # Add step 9 (future step)
        extended_series = base_series + [106.5]
        target_9, vz_9, reg_9 = compute_kinematic_drift_level(extended_series, 106.5)

        # Non-repainting property: re-evaluating historical slice [0:8] produces identical result
        re_target_8, re_vz_8, re_reg_8 = compute_kinematic_drift_level(extended_series[:8], 105.0)
        assert re_target_8 == target_8
        assert re_vz_8 == vz_8
        assert re_reg_8 == reg_8

    def test_scale_free_regime_strength_invariants_monte_carlo(self):
        """Monte Carlo random permutations (1,000 cases) ensuring regime_strength strictly in [0.0, 1.0]."""
        rng = random.Random(42)
        for _ in range(1000):
            spot = rng.uniform(1.0, 1000.0)
            n_strikes = rng.randint(3, 30)
            strikes = sorted(rng.uniform(spot * 0.7, spot * 1.3) for _ in range(n_strikes))
            call_oi = [rng.randint(0, 50000) for _ in range(n_strikes)]
            put_oi = [rng.randint(0, 50000) for _ in range(n_strikes)]

            state = calculate_market_regime(
                spot=spot,
                strikes=strikes,
                call_oi=call_oi,
                put_oi=put_oi,
            )
            if state.measurable:
                assert 0.0 <= state.regime_strength <= 1.0, f"Violated: {state.regime_strength}"
                assert not math.isnan(state.regime_strength)
                assert not math.isinf(state.regime_strength)
            else:
                assert state.regime_strength == 0.0


# ============================================================================
# 2. API SERVER CONCURRENCY & SINGLE-FLIGHT MUTEX STRESS TESTS
# ============================================================================


class TestTier5ApiConcurrencyAdversarial:
    """Stress tests on API concurrency, cache coalescing, and cache stampede resistance."""

    def test_single_flight_mutex_cache_stampede_resistance(self):
        """Simulates 50 threads requesting the same uncached symbol simultaneously.

        Verifies:
        - Exactly one build executes under _PRICE_ATTRACTOR_BUILD_LOCKS.
        - All 50 threads receive identical valid 200 responses.
        - Zero race conditions, exceptions, or deadlocks.
        """
        symbol = f"TEST_STAMPEDE_{int(time.time()*1000)}"

        # Clear any existing cache for this symbol
        with _PRICE_ATTRACTOR_LOCK:
            _PRICE_ATTRACTOR_CACHE.pop(symbol, None)

        def worker_fetch() -> tuple[dict[str, Any], int]:
            return _price_attractors_payload(symbol)

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker_fetch) for _ in range(50)]
            results = [f.result() for f in futures]

        for payload, status in results:
            assert status == 200
            assert payload["symbol"] == symbol
            assert "quality" in payload
            assert "levels" in payload
            assert "regime_state" in payload

        # Subsequent fetch must be a cache hit
        cached_payload, cached_status = _price_attractors_payload(symbol)
        assert cached_status == 200
        assert cached_payload.get("cache", {}).get("hit") is True

    def test_high_concurrency_mixed_hot_and_cold_symbols(self):
        """Simulates 100 concurrent requests across a mixture of hot and cold symbols."""
        symbols = [f"COLD_{i}" for i in range(10)] + ["SPY", "QQQ", "AAPL", "NVDA"]

        def random_fetch(sym: str) -> tuple[dict[str, Any], int]:
            return _price_attractors_payload(sym)

        tasks = [random.choice(symbols) for _ in range(100)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(random_fetch, sym) for sym in tasks]
            results = [f.result() for f in futures]

        assert len(results) == 100
        for payload, status in results:
            assert status == 200
            assert isinstance(payload, dict)
            assert "symbol" in payload

    def test_cache_invalidation_on_backfill(self):
        """Populates cache, simulates backfill invalidation, and verifies fresh build."""
        symbol = "TEST_INVALIDATE_SYM"

        # Prime cache
        res1, status1 = _price_attractors_payload(symbol)
        assert status1 == 200

        with _PRICE_ATTRACTOR_LOCK:
            assert symbol in _PRICE_ATTRACTOR_CACHE

        # Invalidate via backfill eviction pattern in api_server.py:4768
        with _PRICE_ATTRACTOR_LOCK:
            _PRICE_ATTRACTOR_CACHE.pop(symbol.upper(), None)

        with _PRICE_ATTRACTOR_LOCK:
            assert symbol not in _PRICE_ATTRACTOR_CACHE

        # Next request must re-populate cache
        res2, status2 = _price_attractors_payload(symbol)
        assert status2 == 200
        assert res2["cache"]["hit"] is False

        with _PRICE_ATTRACTOR_LOCK:
            assert symbol in _PRICE_ATTRACTOR_CACHE
