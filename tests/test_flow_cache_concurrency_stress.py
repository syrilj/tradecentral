from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import random
import threading
import time

import pytest

from edge.tools import api_server


def _make_sample_payload(symbol: str, right: str = "call", occ: str | None = None) -> dict:
    """Helper to generate mock opportunity payload."""
    occ_sym = occ or f"{symbol}260918C00150000"
    return {
        "available": True,
        "requested_symbol": symbol,
        "rows": [
            {
                "symbol": symbol,
                "composite_score": 10.0,
                "suggestion": {
                    "right": right,
                    "evidence_kind": "model_signal",
                    "setup_tier": "ready",
                    "warnings": [],
                    "contract_plan": {
                        "kind": "chain_selected_contract",
                        "right": right,
                        "occ_symbol": occ_sym,
                        "expiry": "2026-09-18",
                        "strike": 150.0,
                        "action": "BUY_TO_OPEN",
                        "contract_stage": "chain_quote_ready",
                        "sizing_eligible": True,
                        "stable": False,
                        "rejection_reasons": [],
                    },
                },
            }
        ],
        "filters": {"min_volume": 10, "min_open_interest": 100, "max_spread_pct": 0.25},
    }


@pytest.fixture(autouse=True)
def clean_stability_and_cache(monkeypatch, tmp_path):
    """Ensure clean isolated cache and stability state for each test."""
    with api_server._FLOW_SUGGESTION_LOCK:
        api_server._FLOW_SUGGESTION_CACHE.clear()
        api_server._FLOW_SUGGESTION_BUILD_LOCKS.clear()
    with api_server._UNUSUAL_FLOW_LOCK:
        api_server._UNUSUAL_FLOW_CACHE.clear()
        api_server._UNUSUAL_FLOW_BUILD_LOCKS.clear()
    with api_server._CONTRACT_STABILITY_LOCK:
        api_server._CONTRACT_STABILITY_STATE.clear()
        api_server._DIRECTION_STABILITY_STATE.clear()
        api_server._STABILITY_STATE_LOADED = True
    test_stability_path = tmp_path / "test_stability.json"
    monkeypatch.setattr(api_server, "_STABILITY_STATE_PATH", test_stability_path)
    yield
    with api_server._FLOW_SUGGESTION_LOCK:
        api_server._FLOW_SUGGESTION_CACHE.clear()
        api_server._FLOW_SUGGESTION_BUILD_LOCKS.clear()
    with api_server._CONTRACT_STABILITY_LOCK:
        api_server._CONTRACT_STABILITY_STATE.clear()
        api_server._DIRECTION_STABILITY_STATE.clear()


class TestFlowSuggestionCacheConcurrency:
    """Stress-test _FLOW_SUGGESTION_CACHE under concurrent requests with varying symbols and force flags."""

    def test_flow_suggestion_cache_extreme_concurrency_same_symbol(self, monkeypatch):
        """100 concurrent threads requesting the exact same symbol without force should coalesce into exactly 1 build."""
        build_counter = 0
        build_lock = threading.Lock()

        def slow_impl(symbol: str, force: bool = False) -> dict:
            nonlocal build_counter
            with build_lock:
                build_counter += 1
            time.sleep(0.05)  # Simulate expensive chain fetch and parsing
            return {"symbol": symbol, "build_id": build_counter, "ts": time.time()}

        monkeypatch.setattr(api_server, "_flow_suggestion_payload_impl", slow_impl)

        num_threads = 100
        results = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(api_server._flow_suggestion_payload, "AAPL", force=False)
                for _ in range(num_threads)
            ]
            for fut in as_completed(futures):
                results.append(fut.result())

        assert len(results) == num_threads
        # All 100 threads must receive the same build result
        assert all(res["symbol"] == "AAPL" for res in results)
        first_build_id = results[0]["build_id"]
        assert all(res["build_id"] == first_build_id for res in results)
        assert build_counter == 1, f"Expected 1 build under concurrency coalescing, got {build_counter}"

    def test_flow_suggestion_cache_concurrent_multi_symbol_contention(self, monkeypatch):
        """30 distinct symbols queried across 150 worker threads with mixed force flags and jitter."""
        symbols = [f"SYM_{i:02d}" for i in range(30)]
        build_counts = {sym: 0 for sym in symbols}
        counter_lock = threading.Lock()

        def mock_impl(symbol: str, force: bool = False) -> dict:
            with counter_lock:
                build_counts[symbol] += 1
            # Add random sleep jitter (1-10ms) to trigger interleaving
            time.sleep(random.uniform(0.001, 0.01))
            return {"symbol": symbol, "force": force, "time": time.time()}

        monkeypatch.setattr(api_server, "_flow_suggestion_payload_impl", mock_impl)

        num_tasks = 150
        results = []

        def worker_task(idx: int):
            sym = symbols[idx % len(symbols)]
            # 30% of requests are force=True, 70% force=False
            force = (idx % 3) == 0
            time.sleep(random.uniform(0.0, 0.005))
            return api_server._flow_suggestion_payload(sym, force=force)

        with ThreadPoolExecutor(max_workers=40) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_tasks)]
            for fut in as_completed(futures):
                results.append(fut.result())

        assert len(results) == num_tasks
        assert all("symbol" in res for res in results)
        with api_server._FLOW_SUGGESTION_LOCK:
            # Cache size must not exceed the 64 bound limit + 1
            assert len(api_server._FLOW_SUGGESTION_CACHE) <= 65

    def test_flow_suggestion_cache_force_coalescing_under_heavy_concurrency(self, monkeypatch):
        """50 concurrent threads simultaneously requesting force=True for the same symbol.
        They queue behind the symbol build lock and should share the newly built snapshot."""
        builds = 0
        lock = threading.Lock()

        def mock_impl(symbol: str, force: bool = False) -> dict:
            nonlocal builds
            with lock:
                builds += 1
                curr_build = builds
            time.sleep(0.04)
            return {"symbol": symbol, "build_seq": curr_build, "created_at": time.time()}

        monkeypatch.setattr(api_server, "_flow_suggestion_payload_impl", mock_impl)

        num_threads = 50
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(api_server._flow_suggestion_payload, "NVDA", force=True)
                for _ in range(num_threads)
            ]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == num_threads
        assert all(r["symbol"] == "NVDA" for r in results)
        # Because all requests started simultaneously, the subsequent threads acquiring
        # the build_lock will see cached[0] >= request_started and avoid rebuilding!
        assert builds <= 2, f"Expected <= 2 builds due to force coalescing, but got {builds}"

    def test_flow_suggestion_cache_capacity_bounding_under_concurrency_surge(self, monkeypatch):
        """Insert 120 unique symbols concurrently; verify the cache strictly maintains max capacity 64."""
        monkeypatch.setattr(
            api_server,
            "_flow_suggestion_payload_impl",
            lambda sym, force=False: {"symbol": sym, "ts": time.time()},
        )

        symbols = [f"SURGE_{i:03d}" for i in range(120)]
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [
                executor.submit(api_server._flow_suggestion_payload, sym, force=True)
                for sym in symbols
            ]
            for fut in as_completed(futures):
                fut.result()

        with api_server._FLOW_SUGGESTION_LOCK:
            cache_len = len(api_server._FLOW_SUGGESTION_CACHE)
            # The bounded while len > 64 loop guarantees <= 64 items
            assert cache_len == 64, f"Expected cache capacity strictly 64, got {cache_len}"

    def test_flow_suggestion_cache_ttl_expiration_behavior(self, monkeypatch):
        """Verify cache hits before TTL (15s) and cleanly re-builds after TTL expires."""
        calls = []
        simulated_time = 1000.0

        monkeypatch.setattr(time, "time", lambda: simulated_time)

        def mock_impl(symbol: str, force: bool = False):
            calls.append((symbol, force, simulated_time))
            return {"symbol": symbol, "fetch_time": simulated_time}

        monkeypatch.setattr(api_server, "_flow_suggestion_payload_impl", mock_impl)

        # 1. First fetch (cache miss)
        res1 = api_server._flow_suggestion_payload("META", force=False)
        assert res1["fetch_time"] == 1000.0
        assert len(calls) == 1

        # 2. Fetch at t = 1010.0 (10s elapsed < 15s TTL -> Cache HIT)
        simulated_time = 1010.0
        res2 = api_server._flow_suggestion_payload("META", force=False)
        assert res2["fetch_time"] == 1000.0
        assert len(calls) == 1

        # 3. Fetch at t = 1016.0 (16s elapsed > 15s TTL -> Cache EXPIRED, rebuild)
        simulated_time = 1016.0
        res3 = api_server._flow_suggestion_payload("META", force=False)
        assert res3["fetch_time"] == 1016.0
        assert len(calls) == 2


class TestFlowCacheInvalidationMechanics:
    """Verify cache invalidation when fresh flow prints arrive for a subset of symbols."""

    def test_flow_invalidation_exact_subset_pruning(self, monkeypatch):
        """When unusual flow returns prints for a subset of symbols, only those matching symbols are evicted."""
        # Populate 8 symbols in suggestion cache
        for sym in ["AAPL", "MSFT", "GOOG", "AMZN", "META", "TSLA", "NVDA", "AMD"]:
            api_server._FLOW_SUGGESTION_CACHE[sym] = (time.time(), {"symbol": sym, "stale": True})

        assert len(api_server._FLOW_SUGGESTION_CACHE) == 8

        # Unusual flow returns prints for TSLA and NVDA only
        monkeypatch.setattr(
            api_server,
            "build_unusual_options_flow",
            lambda **_: {
                "rows": [
                    {"symbol": "TSLA", "activity_lean": "bullish"},
                    {"symbol": "NVDA", "activity_lean": "bearish"},
                ],
                "coverage": {},
            },
        )

        api_server._unusual_flow_payload_impl(limit=40, min_premium=25_000.0, force=True)

        with api_server._FLOW_SUGGESTION_LOCK:
            # TSLA and NVDA must be purged
            assert "TSLA" not in api_server._FLOW_SUGGESTION_CACHE
            assert "NVDA" not in api_server._FLOW_SUGGESTION_CACHE
            # AAPL, MSFT, GOOG, AMZN, META, AMD must remain intact
            for sym in ["AAPL", "MSFT", "GOOG", "AMZN", "META", "AMD"]:
                assert sym in api_server._FLOW_SUGGESTION_CACHE

    def test_flow_invalidation_case_and_whitespace_normalization(self, monkeypatch):
        """Flow row symbols with mixed case and whitespace properly invalidate normalized uppercase entries."""
        api_server._FLOW_SUGGESTION_CACHE["AAPL"] = (time.time(), {"symbol": "AAPL"})
        api_server._FLOW_SUGGESTION_CACHE["NVDA"] = (time.time(), {"symbol": "NVDA"})
        api_server._FLOW_SUGGESTION_CACHE["SPY"] = (time.time(), {"symbol": "SPY"})

        monkeypatch.setattr(
            api_server,
            "build_unusual_options_flow",
            lambda **_: {
                "rows": [
                    {"symbol": "  aapl  "},
                    {"symbol": "NvDa"},
                ],
                "coverage": {},
            },
        )

        api_server._unusual_flow_payload_impl(limit=40, min_premium=25_000.0, force=True)

        with api_server._FLOW_SUGGESTION_LOCK:
            assert "AAPL" not in api_server._FLOW_SUGGESTION_CACHE
            assert "NVDA" not in api_server._FLOW_SUGGESTION_CACHE
            assert "SPY" in api_server._FLOW_SUGGESTION_CACHE

    def test_flow_invalidation_malformed_flow_rows_resilience(self, monkeypatch):
        """Unusual flow payload containing None, malformed rows, or invalid types does not crash invalidation."""
        api_server._FLOW_SUGGESTION_CACHE["VALID"] = (time.time(), {"symbol": "VALID"})
        api_server._FLOW_SUGGESTION_CACHE["STAY"] = (time.time(), {"symbol": "STAY"})

        monkeypatch.setattr(
            api_server,
            "build_unusual_options_flow",
            lambda **_: {
                "rows": [
                    None,
                    "not-a-dict",
                    {},
                    {"symbol": None},
                    {"symbol": ""},
                    {"symbol": 12345},
                    {"symbol": "VALID"},
                ],
                "coverage": {},
            },
        )

        # Must execute cleanly without exception
        api_server._unusual_flow_payload_impl(limit=40, min_premium=25_000.0, force=True)

        with api_server._FLOW_SUGGESTION_LOCK:
            assert "VALID" not in api_server._FLOW_SUGGESTION_CACHE
            assert "STAY" in api_server._FLOW_SUGGESTION_CACHE

    def test_flow_invalidation_forces_subsequent_rebuild(self, monkeypatch):
        """After invalidation, next passive flow suggestion query MUST invoke payload impl instead of cache."""
        calls = []

        def mock_impl(symbol: str, force: bool = False):
            calls.append(symbol)
            return {"symbol": symbol, "fetch_count": len(calls)}

        monkeypatch.setattr(api_server, "_flow_suggestion_payload_impl", mock_impl)

        # 1. Warm cache
        res1 = api_server._flow_suggestion_payload("QQQ", force=False)
        assert res1["fetch_count"] == 1
        assert len(calls) == 1

        # 2. Passive fetch hits cache
        res2 = api_server._flow_suggestion_payload("QQQ", force=False)
        assert res2["fetch_count"] == 1
        assert len(calls) == 1

        # 3. Invalidate via fresh unusual flow
        monkeypatch.setattr(
            api_server,
            "build_unusual_options_flow",
            lambda **_: {"rows": [{"symbol": "QQQ"}], "coverage": {}},
        )
        api_server._unusual_flow_payload_impl(limit=40, min_premium=25_000.0, force=True)

        # 4. Subsequent passive fetch MUST re-execute impl
        res3 = api_server._flow_suggestion_payload("QQQ", force=False)
        assert res3["fetch_count"] == 2
        assert len(calls) == 2

    def test_flow_invalidation_concurrent_with_active_readers(self, monkeypatch):
        """Concurrent reader threads and invalidation threads running concurrently do not deadlock or raise RuntimeError."""
        symbols = [f"CONC_{i}" for i in range(20)]
        for s in symbols:
            api_server._FLOW_SUGGESTION_CACHE[s] = (time.time(), {"symbol": s})

        stop_event = threading.Event()

        def reader_worker():
            while not stop_event.is_set():
                sym = random.choice(symbols)
                with api_server._FLOW_SUGGESTION_LOCK:
                    _ = api_server._FLOW_SUGGESTION_CACHE.get(sym)
                time.sleep(0.001)

        def invalidator_worker():
            for _ in range(25):
                subset = random.sample(symbols, k=5)
                monkeypatch.setattr(
                    api_server,
                    "build_unusual_options_flow",
                    lambda **_: {"rows": [{"symbol": s} for s in subset], "coverage": {}},
                )
                api_server._unusual_flow_payload_impl(limit=40, min_premium=25_000.0, force=True)
                time.sleep(0.002)

        with ThreadPoolExecutor(max_workers=8) as pool:
            readers = [pool.submit(reader_worker) for _ in range(6)]
            invalidator = pool.submit(invalidator_worker)
            invalidator.result()
            stop_event.set()
            for r in readers:
                r.result()


class TestDirectionalFlipStabilityPurgeAndObservationReset:
    """Verify directional flips immediately purge stability state and reset observation counter."""

    def test_directional_flip_call_to_put_purges_contract_stability_and_resets_count(self):
        """Observing CALL 3 times achieves stability. A subsequent PUT observation immediately
        resets direction count to 1, purges all contract stability, and demotes action to WAIT_FOR_STABILITY."""
        sym = "TEST_SYM"

        # Observation 1 (CALL)
        p1 = _make_sample_payload(sym, right="call", occ="TEST260918C00100000")
        res1 = api_server._stabilize_contract_plans(p1)
        sug1 = res1["rows"][0]["suggestion"]
        plan1 = sug1["contract_plan"]
        assert sug1["direction_observations"] == 1
        assert sug1["direction_stable"] is False
        assert sug1["direction_churned"] is False
        assert plan1["stability_observations"] == 1
        assert plan1["stable"] is False
        assert plan1["action"] == "WAIT_FOR_STABILITY"

        # Observation 2 (CALL)
        p2 = _make_sample_payload(sym, right="call", occ="TEST260918C00100000")
        res2 = api_server._stabilize_contract_plans(p2)
        sug2 = res2["rows"][0]["suggestion"]
        plan2 = sug2["contract_plan"]
        assert sug2["direction_observations"] == 2
        assert sug2["direction_stable"] is True
        assert plan2["stability_observations"] == 2
        assert plan2["stable"] is False

        # Observation 3 (CALL) -> Fully stabilized
        p3 = _make_sample_payload(sym, right="call", occ="TEST260918C00100000")
        res3 = api_server._stabilize_contract_plans(p3)
        sug3 = res3["rows"][0]["suggestion"]
        plan3 = sug3["contract_plan"]
        assert sug3["direction_observations"] == 2
        assert sug3["direction_stable"] is True
        assert plan3["stability_observations"] == 3
        assert plan3["stable"] is True
        assert plan3["action"] == "BUY_TO_OPEN"
        assert plan3["sizing_eligible"] is True

        # Observation 4: Directional Flip to PUT
        p4 = _make_sample_payload(sym, right="put", occ="TEST260918P00095000")
        res4 = api_server._stabilize_contract_plans(p4)
        sug4 = res4["rows"][0]["suggestion"]
        plan4 = sug4["contract_plan"]

        # 1. Direction churned is flagged
        assert sug4["direction_churned"] is True
        # 2. Direction count is reset to 1
        assert sug4["direction_observations"] == 1
        # 3. Direction is not stable
        assert sug4["direction_stable"] is False
        # 4. Warning is recorded
        assert any("Suggested right changed" in w for w in sug4.get("warnings", []))
        # 5. Contract stability for symbol is completely purged and reset to 1
        assert plan4["stability_observations"] == 1
        assert plan4["stable"] is False
        # 6. Action is gated back to WAIT_FOR_STABILITY and sizing is blocked
        assert plan4["action"] == "WAIT_FOR_STABILITY"
        assert plan4["contract_stage"] == "chain_quote_waiting_for_stability"
        assert plan4["sizing_eligible"] is False
        # 7. Internal contract state dictionary has zero entries for the old CALL contract
        with api_server._CONTRACT_STABILITY_LOCK:
            assert (sym, "call") not in api_server._CONTRACT_STABILITY_STATE
            assert (sym, "put") in api_server._CONTRACT_STABILITY_STATE
            assert api_server._CONTRACT_STABILITY_STATE[(sym, "put")][1] == 1

    def test_directional_flip_put_to_call_purges_and_resets(self):
        """Observing PUT to full stability, then flipping to CALL immediately resets state."""
        sym = "FLIP_PUT"

        # 3 observations of PUT
        for _ in range(3):
            p = _make_sample_payload(sym, right="put", occ="FLIP260918P00050000")
            res = api_server._stabilize_contract_plans(p)

        plan_put = res["rows"][0]["suggestion"]["contract_plan"]
        assert plan_put["stable"] is True
        assert plan_put["action"] == "BUY_TO_OPEN"

        # Flip to CALL
        p_call = _make_sample_payload(sym, right="call", occ="FLIP260918C00055000")
        res_call = api_server._stabilize_contract_plans(p_call)
        sug_call = res_call["rows"][0]["suggestion"]
        plan_call = sug_call["contract_plan"]

        assert sug_call["direction_churned"] is True
        assert sug_call["direction_observations"] == 1
        assert sug_call["direction_stable"] is False
        assert plan_call["stability_observations"] == 1
        assert plan_call["stable"] is False
        assert plan_call["action"] == "WAIT_FOR_STABILITY"

        with api_server._CONTRACT_STABILITY_LOCK:
            assert (sym, "put") not in api_server._CONTRACT_STABILITY_STATE
            assert (sym, "call") in api_server._CONTRACT_STABILITY_STATE
            assert api_server._CONTRACT_STABILITY_STATE[(sym, "call")][1] == 1

    def test_rapid_alternating_direction_churn_never_stabilizes(self):
        """Repeatedly flipping directions (CALL -> PUT -> CALL -> PUT) keeps count at 1 and prevents execution."""
        sym = "CHURN_SYM"
        directions = ["call", "put", "call", "put", "call", "put"]

        for i, right in enumerate(directions):
            occ = f"CHURN260918{right[0].upper()}00100000"
            p = _make_sample_payload(sym, right=right, occ=occ)
            res = api_server._stabilize_contract_plans(p)
            sug = res["rows"][0]["suggestion"]
            plan = sug["contract_plan"]

            if i > 0:
                assert sug["direction_churned"] is True
                assert sug["direction_observations"] == 1
                assert sug["direction_stable"] is False
                assert plan["stability_observations"] == 1
                assert plan["stable"] is False
                assert plan["action"] == "WAIT_FOR_STABILITY"

    def test_restabilization_after_directional_flip(self):
        """After a directional flip occurs, subsequent consistent observations in the new direction
        successfully re-accumulate stability (1 -> 2 -> 3)."""
        sym = "RE_STAB"

        # CALL 3 times
        for _ in range(3):
            p = _make_sample_payload(sym, right="call", occ="RESTAB260918C00100000")
            api_server._stabilize_contract_plans(p)

        # Flip to PUT (obs 1 of PUT)
        p_put1 = _make_sample_payload(sym, right="put", occ="RESTAB260918P00090000")
        res_put1 = api_server._stabilize_contract_plans(p_put1)
        assert res_put1["rows"][0]["suggestion"]["direction_observations"] == 1
        assert res_put1["rows"][0]["suggestion"]["contract_plan"]["stable"] is False

        # PUT obs 2
        p_put2 = _make_sample_payload(sym, right="put", occ="RESTAB260918P00090000")
        res_put2 = api_server._stabilize_contract_plans(p_put2)
        assert res_put2["rows"][0]["suggestion"]["direction_observations"] == 2
        assert res_put2["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 2
        assert res_put2["rows"][0]["suggestion"]["contract_plan"]["stable"] is False

        # PUT obs 3 -> Fully re-stabilized in PUT direction
        p_put3 = _make_sample_payload(sym, right="put", occ="RESTAB260918P00090000")
        res_put3 = api_server._stabilize_contract_plans(p_put3)
        assert res_put3["rows"][0]["suggestion"]["direction_observations"] == 2
        assert res_put3["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 3
        assert res_put3["rows"][0]["suggestion"]["contract_plan"]["stable"] is True
        assert res_put3["rows"][0]["suggestion"]["contract_plan"]["action"] == "BUY_TO_OPEN"

    def test_cross_symbol_isolation_during_directional_flip(self):
        """A directional flip on symbol AAPL does not affect or purge the stability of symbol MSFT."""
        # Stabilize MSFT
        for _ in range(3):
            p_msft = _make_sample_payload("MSFT", right="call", occ="MSFT260918C00400000")
            api_server._stabilize_contract_plans(p_msft)

        # Stabilize AAPL
        for _ in range(3):
            p_aapl = _make_sample_payload("AAPL", right="call", occ="AAPL260918C00200000")
            api_server._stabilize_contract_plans(p_aapl)

        with api_server._CONTRACT_STABILITY_LOCK:
            assert api_server._CONTRACT_STABILITY_STATE[("MSFT", "call")][1] == 3
            assert api_server._CONTRACT_STABILITY_STATE[("AAPL", "call")][1] == 3

        # Flip AAPL to PUT
        p_aapl_put = _make_sample_payload("AAPL", right="put", occ="AAPL260918P00190000")
        api_server._stabilize_contract_plans(p_aapl_put)

        with api_server._CONTRACT_STABILITY_LOCK:
            # AAPL CALL was purged, AAPL PUT is at 1
            assert ("AAPL", "call") not in api_server._CONTRACT_STABILITY_STATE
            assert api_server._CONTRACT_STABILITY_STATE[("AAPL", "put")][1] == 1
            # MSFT CALL MUST remain at count 3!
            assert api_server._CONTRACT_STABILITY_STATE[("MSFT", "call")][1] == 3

        # Confirm MSFT payload remains stable
        p_msft_check = _make_sample_payload("MSFT", right="call", occ="MSFT260918C00400000")
        res_msft = api_server._stabilize_contract_plans(p_msft_check)
        assert res_msft["rows"][0]["suggestion"]["contract_plan"]["stable"] is True
        assert res_msft["rows"][0]["suggestion"]["contract_plan"]["action"] == "BUY_TO_OPEN"

    def test_evidence_kind_activity_lean_requires_3_observations(self):
        """evidence_kind == 'activity_lean' requires 3 observations to become direction stable,
        whereas model_signal requires only 2."""
        sym = "ACT_LEAN"

        # Obs 1 (activity_lean)
        p1 = _make_sample_payload(sym, right="call")
        p1["rows"][0]["suggestion"]["evidence_kind"] = "activity_lean"
        res1 = api_server._stabilize_contract_plans(p1)
        sug1 = res1["rows"][0]["suggestion"]
        assert sug1["direction_required"] == 3
        assert sug1["direction_observations"] == 1
        assert sug1["direction_stable"] is False

        # Obs 2 (activity_lean)
        p2 = _make_sample_payload(sym, right="call")
        p2["rows"][0]["suggestion"]["evidence_kind"] = "activity_lean"
        res2 = api_server._stabilize_contract_plans(p2)
        sug2 = res2["rows"][0]["suggestion"]
        assert sug2["direction_observations"] == 2
        assert sug2["direction_stable"] is False  # 2 < 3, so not stable yet!

        # Obs 3 (activity_lean)
        p3 = _make_sample_payload(sym, right="call")
        p3["rows"][0]["suggestion"]["evidence_kind"] = "activity_lean"
        res3 = api_server._stabilize_contract_plans(p3)
        sug3 = res3["rows"][0]["suggestion"]
        assert sug3["direction_observations"] == 3
        assert sug3["direction_stable"] is True
