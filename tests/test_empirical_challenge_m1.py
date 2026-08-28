"""Adversarial and empirical stress tests for Milestone 1:
1. Level source attribution under boundary, extreme, and negative gamma flip values.
2. Plan target and invalidation source under all level combinations.
3. Contract & direction stability counters across time deltas (0s, 60s, 300s, 2699s, 2700s, 2701s, 5401s).
"""
import copy
import json
import math
import os
import time
from datetime import datetime, timezone
import pytest

from daily_plays.opportunity_scanner import (
    LEVEL_SOURCE_GEX,
    LEVEL_SOURCE_POSITIONS,
    LEVEL_SOURCE_SUPPORT,
    LEVEL_SOURCE_TA,
    _level,
    _append_level,
    build_live_opportunities,
    setup_inputs_from_rows,
    setup_level_model,
)
from daily_plays.options_intelligence import OptionsFilters
from tools import api_server


# ============================================================================
# Helper fixtures / builders
# ============================================================================
ASOF_DT = datetime(2026, 8, 9, 20, 0, 0, tzinfo=timezone.utc)
ASOF_STR = "2026-08-09T20:00:00+00:00"


def make_board_row(
    symbol: str = "TEST",
    spot: float = 100.0,
    direction: str = "long",
    call_wall: float | None = 110.0,
    put_wall: float | None = 95.0,
    gamma_flip: float | None = 98.0,
    support_price: float | None = None,
    resistance_price: float | None = None,
    ta_support: float | None = None,
    ta_resistance: float | None = None,
    gex_by_strike: list[dict] | None = None,
    observed_at: str = ASOF_STR,
) -> dict:
    right = "call" if direction == "long" else "put"
    strike = 105.0 if direction == "long" else 95.0
    return {
        "symbol": symbol,
        "spot": spot,
        "score_kind": "ordinal_activity",
        "composite_score": 75.0,
        "observed_at": observed_at,
        "age_seconds": 30.0,
        "flow_direction": "bullish" if direction == "long" else "bearish",
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": gamma_flip,
        "support_price": support_price,
        "resistance_price": resistance_price,
        "ta_support": ta_support,
        "ta_resistance": ta_resistance,
        "gex_by_strike": gex_by_strike or [],
        "contract_focus": {
            right: {
                "occ_symbol": f"{symbol}260815{right[0].upper()}{int(strike):05d}000",
                "strike": strike,
                "expiry": "2026-08-15",
                "open_interest": 1500,
                "spread_pct": 0.05,
                "volume": 500,
                "bid": 2.90,
                "ask": 3.10,
                "mid": 3.00,
                "observed_at": observed_at,
            }
        },
    }


def make_flow_row(symbol: str = "TEST", context_side: str = "long") -> dict:
    return {
        "symbol": symbol,
        "net_signed_score": 8.5 if context_side == "long" else -8.5,
        "activity_lean": "bullish" if context_side == "long" else "bearish",
        "activity_lean_source": "flow_prints",
        "context_side": context_side,
        "total_premium": 2_500_000,
        "call_premium": 2_000_000 if context_side == "long" else 500_000,
        "put_premium": 500_000 if context_side == "long" else 2_000_000,
    }


# ============================================================================
# Challenge 1: Level source attribution & gamma_flip boundary / extreme values
# ============================================================================
class TestGammaFlipBoundaryAndAttribution:
    """Stress-test gamma_flip equal to spot, extreme positive, zero, negative, NaN/Inf."""

    def test_gamma_flip_exactly_equal_to_spot(self):
        """When gamma_flip == spot, it is on the boundary (neither below nor above spot).

        It must NOT be included in supports or resistances, but must trigger
        source_status['options GEX'] == 'wrong-side' if no other GEX levels exist.
        """
        spot = 100.0
        model_long = setup_level_model(
            direction="long",
            spot=spot,
            gamma_flip=100.0,
        )
        assert model_long["supports"] == []
        assert model_long["take_profit_zones"] == []
        assert model_long["invalidation"] is None
        assert model_long["invalidation_source"] is None
        assert model_long["source_status"][LEVEL_SOURCE_GEX] == "wrong-side"
        assert LEVEL_SOURCE_GEX in model_long["missing_sources"]

        model_short = setup_level_model(
            direction="short",
            spot=spot,
            gamma_flip=100.0,
        )
        assert model_short["supports"] == []
        assert model_short["take_profit_zones"] == []
        assert model_short["invalidation"] is None
        assert model_short["invalidation_source"] is None
        assert model_short["source_status"][LEVEL_SOURCE_GEX] == "wrong-side"

    def test_gamma_flip_negative_values(self):
        """Negative gamma_flip (e.g. -100.0, -0.01) is non-physical for equity spot levels.

        _level filters out <= 0, so negative values are treated as unmeasured, not wrong-side.
        """
        for neg_val in [-100.0, -1.0, -0.0001]:
            assert _level(neg_val) is None
            model = setup_level_model(
                direction="long",
                spot=100.0,
                gamma_flip=neg_val,
            )
            assert model["supports"] == []
            assert model["take_profit_zones"] == []
            assert model["source_status"][LEVEL_SOURCE_GEX] == "unmeasured"

    def test_gamma_flip_zero(self):
        """gamma_flip == 0.0 is non-positive, should be filtered by _level."""
        assert _level(0.0) is None
        assert _level(0) is None
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=0.0,
        )
        assert model["supports"] == []
        assert model["source_status"][LEVEL_SOURCE_GEX] == "unmeasured"

    def test_gamma_flip_extreme_positive_values(self):
        """gamma_flip == 1e9 (extreme high) should be placed in resistances for long and short,

        with source LEVEL_SOURCE_GEX ('options GEX').
        """
        extreme_high = 1_000_000_000.0
        model_long = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=extreme_high,
        )
        assert len(model_long["take_profit_zones"]) == 1
        assert model_long["take_profit_zones"][0]["price"] == extreme_high
        assert model_long["take_profit_zones"][0]["source"] == LEVEL_SOURCE_GEX
        assert model_long["source_status"][LEVEL_SOURCE_GEX] == "measured"

        model_short = setup_level_model(
            direction="short",
            spot=100.0,
            gamma_flip=extreme_high,
        )
        assert model_short["invalidation"] == extreme_high
        assert model_short["invalidation_source"] == LEVEL_SOURCE_GEX
        assert model_short["source_status"][LEVEL_SOURCE_GEX] == "measured"

    def test_gamma_flip_extreme_small_positive_value(self):
        """gamma_flip == 0.0001 (very small positive number > 0) should be placed in supports."""
        small_val = 0.0001
        assert _level(small_val) == 0.0001
        model_long = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=small_val,
        )
        assert len(model_long["supports"]) == 1
        assert model_long["supports"][0]["price"] == 0.0001
        assert model_long["supports"][0]["source"] == LEVEL_SOURCE_GEX
        assert model_long["invalidation"] == 0.0001
        assert model_long["invalidation_source"] == LEVEL_SOURCE_GEX

    def test_gamma_flip_nan_inf_none_strings(self):
        """Adversarial non-numeric inputs (NaN, Inf, strings, None) do not crash setup_level_model."""
        for bad_val in [float("nan"), float("inf"), float("-inf"), "invalid", None, [], {}]:
            model = setup_level_model(
                direction="long",
                spot=100.0,
                gamma_flip=bad_val,
            )
            assert model["supports"] == []
            assert model["source_status"][LEVEL_SOURCE_GEX] == "unmeasured"

    def test_gamma_flip_attribution_distinct_from_ta(self):
        """Verify gamma_flip is strictly tagged as LEVEL_SOURCE_GEX ('options GEX') and NEVER LEVEL_SOURCE_TA."""
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=98.0,
            ta_support=95.0,
        )
        assert len(model["supports"]) == 2
        # Highest support is gamma_flip at 98.0
        assert model["supports"][0]["price"] == 98.0
        assert model["supports"][0]["source"] == LEVEL_SOURCE_GEX
        assert model["supports"][0]["source"] != LEVEL_SOURCE_TA
        # Second support is TA at 95.0
        assert model["supports"][1]["price"] == 95.0
        assert model["supports"][1]["source"] == LEVEL_SOURCE_TA

        # Invalidation is closest support (98.0)
        assert model["invalidation"] == 98.0
        assert model["invalidation_source"] == LEVEL_SOURCE_GEX


# ============================================================================
# Challenge 2: Plan Target & Invalidation Sources Under Multiple Combinations
# ============================================================================
class TestPlanTargetAndInvalidationCombinations:
    """Verify plan_target_source and plan_invalidation_source under varied level combinations."""

    def test_combination_pure_gex_walls(self):
        """Setup with call_wall and put_wall only."""
        board = make_board_row(
            symbol="GEX_ONLY",
            spot=100.0,
            direction="long",
            call_wall=110.0,
            put_wall=95.0,
            gamma_flip=None,
            support_price=None,
            resistance_price=None,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("GEX_ONLY", "long")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["plan_target"] == 110.0
        assert sug["plan_target_source"] in {"call_wall", LEVEL_SOURCE_GEX}
        assert sug["plan_invalidation"] == 95.0
        assert sug["plan_invalidation_source"] in {"put_wall", LEVEL_SOURCE_GEX}

    def test_combination_flow_state_levels_only(self):
        """Setup with flow state support_price and resistance_price, no GEX walls."""
        board = make_board_row(
            symbol="FLOW_ONLY",
            spot=100.0,
            direction="long",
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            support_price=97.0,
            resistance_price=106.0,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("FLOW_ONLY", "long")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["invalidation"] == 97.0
        assert sug["invalidation_source"] == LEVEL_SOURCE_SUPPORT
        if sug.get("plan_invalidation") is not None:
            assert sug["plan_invalidation_source"] == LEVEL_SOURCE_SUPPORT

    def test_combination_ta_levels_only(self):
        """Setup with ta_support and ta_resistance only."""
        board = make_board_row(
            symbol="TA_ONLY",
            spot=100.0,
            direction="long",
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            support_price=None,
            resistance_price=None,
            ta_support=96.0,
            ta_resistance=108.0,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("TA_ONLY", "long")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["invalidation"] == 96.0
        assert sug["invalidation_source"] == LEVEL_SOURCE_TA
        if sug.get("plan_invalidation") is not None:
            assert sug["plan_invalidation_source"] == LEVEL_SOURCE_TA

    def test_combination_pure_gamma_flip_no_walls(self):
        """When gamma_flip is the only GEX level (no call_wall, no put_wall), invalidation adopts gamma_flip."""
        board = make_board_row(
            symbol="GF_PURE",
            spot=100.0,
            direction="long",
            call_wall=None,
            put_wall=None,
            gamma_flip=98.0,
            support_price=None,
            ta_support=None,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("GF_PURE", "long")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["invalidation"] == 98.0
        assert sug["invalidation_source"] == LEVEL_SOURCE_GEX
        if sug.get("plan_invalidation") is not None:
            assert sug["plan_invalidation_source"] == LEVEL_SOURCE_GEX

    def test_combination_level_model_multi_support_ordering(self):
        """In setup_level_model, supports are ordered descending by price, with correct source attribution."""
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=98.0,
            support=96.0,
            put_wall=94.0,
            ta_support=92.0,
        )
        assert len(model["supports"]) == 4
        # Descending order: 98.0 (GEX) -> 96.0 (support) -> 94.0 (GEX) -> 92.0 (TA)
        assert model["supports"][0] == {"price": 98.0, "source": LEVEL_SOURCE_GEX}
        assert model["supports"][1] == {"price": 96.0, "source": LEVEL_SOURCE_SUPPORT}
        assert model["supports"][2] == {"price": 94.0, "source": LEVEL_SOURCE_GEX}
        assert model["supports"][3] == {"price": 92.0, "source": LEVEL_SOURCE_TA}
        assert model["invalidation"] == 98.0
        assert model["invalidation_source"] == LEVEL_SOURCE_GEX

    def test_combination_short_direction_pure_gamma_flip(self):
        """For short setups with pure gamma_flip above spot and no call wall."""
        board = make_board_row(
            symbol="SHORT_GF",
            spot=100.0,
            direction="short",
            call_wall=None,
            put_wall=90.0,
            gamma_flip=104.0,  # resistance above spot
            resistance_price=None,
            support_price=None,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("SHORT_GF", "short")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["right"] == "put"
        assert sug["plan_target"] == 90.0
        assert sug["plan_target_source"] in {"put_wall", LEVEL_SOURCE_GEX}
        # Invalidation adopts gamma_flip 104.0 with options GEX source
        assert sug["invalidation"] == 104.0
        assert sug["invalidation_source"] == LEVEL_SOURCE_GEX

    def test_combination_all_levels_missing(self):
        """When all levels are missing, plan sources must safely be None without crashing or fabricating."""
        board = make_board_row(
            symbol="NO_LEVELS",
            spot=100.0,
            direction="long",
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            support_price=None,
            resistance_price=None,
            ta_support=None,
            ta_resistance=None,
        )
        res = build_live_opportunities(
            board_rows=[board],
            flow_rows=[make_flow_row("NO_LEVELS", "long")],
            filters=OptionsFilters(),
            asof_utc=ASOF_DT,
        )
        sug = res["rows"][0]["suggestion"]
        assert sug["plan_target"] is None
        assert sug["plan_target_source"] is None
        assert sug["plan_invalidation"] is None
        assert sug["plan_invalidation_source"] is None
        assert sug["invalidation"] is None
        assert sug["invalidation_source"] is None
        assert sug["risk_levels_complete"] is False

    def test_gex_strike_rows_attribution(self):
        """GEX strike rows generate strike supports/resistances attributed to options GEX or positions."""
        gex_rows = [
            {"strike": 94.0, "open_interest": 5000, "put_gex_m": -2.5, "call_gex_m": 0.1},
            {"strike": 106.0, "open_interest": 8000, "put_gex_m": -0.1, "call_gex_m": 4.2},
        ]
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gex_rows=gex_rows,
        )
        # 94.0 should be present in supports with options GEX and positions
        support_sources = {s["price"]: s["source"] for s in model["supports"]}
        assert 94.0 in support_sources
        # 106.0 should be present in take_profit_zones
        zone_sources = {z["price"]: z["source"] for z in model["take_profit_zones"]}
        assert 106.0 in zone_sources


# ============================================================================
# Challenge 3: Contract Stability Counters Across Varied Time Deltas
# ============================================================================
class TestContractStabilityTimeDeltas:
    """Stress-test contract stability counters across exact time deltas: 0s, 60s, 300s, 2699s, 2700s, 2701s, 5401s."""

    def _make_payload(self, symbol="AAPL", right="call", occ_symbol="AAPL260815C00150000"):
        return {
            "rows": [
                {
                    "symbol": symbol,
                    "composite_score": 80.0,
                    "freshness": {"pass": True},
                    "live_ready": True,
                    "suggestion": {
                        "right": right,
                        "setup_tier": "ready",
                        "entry_eligible": True,
                        "risk_levels_complete": True,
                        "contract_plan": {
                            "kind": "chain_selected_contract",
                            "action": "BUY_TO_OPEN",
                            "right": right,
                            "occ_symbol": occ_symbol,
                            "expiry": "2026-08-15",
                            "strike": 150.0,
                            "volume": 200,
                            "open_interest": 1000,
                            "spread_pct": 0.04,
                            "quote_complete": True,
                            "sizing_eligible": True,
                            "sizing_debit": 3.50,
                            "observed_at": "2026-08-09T19:00:00Z",
                        },
                    },
                }
            ],
            "filters": {"min_volume": 10, "min_open_interest": 100, "max_spread_pct": 0.25},
            "asof_utc": "2026-08-09T19:00:00Z",
        }

    def _setup_api_state(self, monkeypatch, tmp_path):
        state_path = tmp_path / "stability.json"
        monkeypatch.setattr(api_server, "_STABILITY_STATE_PATH", state_path)
        monkeypatch.setattr(api_server, "_STABILITY_STATE_LOADED", True)
        api_server._CONTRACT_STABILITY_STATE.clear()
        api_server._DIRECTION_STABILITY_STATE.clear()
        return state_path

    def test_delta_0s_immediate_succession(self, monkeypatch, tmp_path):
        """Successive calls at exact same timestamp (delta=0s) increment counter."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0
        monkeypatch.setattr(time, "time", lambda: base_t)

        # Call 1
        res1 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        assert res1["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 1
        assert res1["rows"][0]["suggestion"]["contract_plan"]["stable"] is False

        # Call 2 at delta = 0s
        res2 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        assert res2["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 2
        assert res2["rows"][0]["suggestion"]["contract_plan"]["stable"] is False

        # Call 3 at delta = 0s -> Reaches stability
        res3 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        assert res3["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 3
        assert res3["rows"][0]["suggestion"]["contract_plan"]["stable"] is True
        assert res3["rows"][0]["suggestion"]["contract_plan"]["action"] == "BUY_TO_OPEN"

    def test_delta_60s_one_minute_intervals(self, monkeypatch, tmp_path):
        """1-minute intervals (60s) cleanly progress 1 -> 2 -> 3."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        for i, step in enumerate([0.0, 60.0, 120.0], start=1):
            monkeypatch.setattr(time, "time", lambda t=base_t + step: t)
            res = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
            plan = res["rows"][0]["suggestion"]["contract_plan"]
            assert plan["stability_observations"] == i
            assert plan["stable"] is (i == 3)

    def test_delta_300s_five_minute_intervals(self, monkeypatch, tmp_path):
        """5-minute intervals (300s) cleanly progress 1 -> 2 -> 3."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        for i, step in enumerate([0.0, 300.0, 600.0], start=1):
            monkeypatch.setattr(time, "time", lambda t=base_t + step: t)
            res = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
            plan = res["rows"][0]["suggestion"]["contract_plan"]
            assert plan["stability_observations"] == i
            assert plan["stable"] is (i == 3)

    def test_delta_2699s_just_below_max_gap_boundary(self, monkeypatch, tmp_path):
        """At delta = 2699s (< 2700s threshold), gap is accepted and counter increments."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        # Obs 1 at T=0
        monkeypatch.setattr(time, "time", lambda: base_t)
        res1 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        assert res1["rows"][0]["suggestion"]["contract_plan"]["stability_observations"] == 1

        # Obs 2 at T=2699s
        monkeypatch.setattr(time, "time", lambda: base_t + 2699.0)
        res2 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        plan2 = res2["rows"][0]["suggestion"]["contract_plan"]
        assert plan2["stability_observations"] == 2  # Incremented!
        assert plan2["stable"] is False

        # Obs 3 at T=2699 + 2699s
        monkeypatch.setattr(time, "time", lambda: base_t + 2699.0 + 2699.0)
        res3 = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        plan3 = res3["rows"][0]["suggestion"]["contract_plan"]
        assert plan3["stability_observations"] == 3  # Stable!
        assert plan3["stable"] is True

    def test_delta_2700s_exact_boundary(self, monkeypatch, tmp_path):
        """At delta = 2700.0s (exact threshold _CONTRACT_STABILITY_MAX_GAP_S), condition <= holds and increments."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        monkeypatch.setattr(time, "time", lambda: base_t)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))

        monkeypatch.setattr(time, "time", lambda: base_t + 2700.0)
        res = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        plan = res["rows"][0]["suggestion"]["contract_plan"]
        assert plan["stability_observations"] == 2  # <= 2700.0 is True

    def test_delta_2701s_exceeds_max_gap_boundary(self, monkeypatch, tmp_path):
        """At delta = 2701s (> 2700s threshold), gap is too large and counter resets to 1."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        # Obs 1 at T=0
        monkeypatch.setattr(time, "time", lambda: base_t)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))

        # Obs 2 at T=2701s
        monkeypatch.setattr(time, "time", lambda: base_t + 2701.0)
        res = api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload()))
        plan = res["rows"][0]["suggestion"]["contract_plan"]
        assert plan["stability_observations"] == 1  # Reset to 1!
        assert plan["stable"] is False

    def test_direction_churn_purges_contract_state(self, monkeypatch, tmp_path):
        """When direction changes from CALL to PUT within stability window:

        1. Direction count becomes 1.
        2. direction_churned becomes True.
        3. Contract stability for symbol is wiped.
        """
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        # Step 1: Call setup reaches count 2
        monkeypatch.setattr(time, "time", lambda: base_t)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload(right="call")))
        monkeypatch.setattr(time, "time", lambda: base_t + 60.0)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload(right="call")))

        assert api_server._DIRECTION_STABILITY_STATE["AAPL"][1] == 2
        assert ("AAPL", "call") in api_server._CONTRACT_STABILITY_STATE

        # Step 2: Direction flips to PUT at t = 120s
        monkeypatch.setattr(time, "time", lambda: base_t + 120.0)
        put_payload = self._make_payload(right="put", occ_symbol="AAPL260815P00150000")
        res = api_server._stabilize_contract_plans(copy.deepcopy(put_payload))
        sug = res["rows"][0]["suggestion"]
        plan = sug["contract_plan"]

        assert sug["direction_churned"] is True
        assert sug["direction_observations"] == 1
        assert sug["direction_stable"] is False
        assert any("Suggested right changed" in w for w in sug["warnings"])
        # Previous contract key ("AAPL", "call") was purged
        assert ("AAPL", "call") not in api_server._CONTRACT_STABILITY_STATE
        # New contract plan is count 1 and not stable
        assert plan["stability_observations"] == 1
        assert plan["stable"] is False

    def test_contract_identity_change_resets_count(self, monkeypatch, tmp_path):
        """When strike or expiry changes on subsequent observation, contract count resets to 1."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        # Obs 1: 150 Call
        monkeypatch.setattr(time, "time", lambda: base_t)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload(occ_symbol="AAPL260815C00150000")))

        # Obs 2: 155 Call (different contract identity)
        monkeypatch.setattr(time, "time", lambda: base_t + 60.0)
        payload2 = self._make_payload(occ_symbol="AAPL260815C00155000")
        payload2["rows"][0]["suggestion"]["contract_plan"]["strike"] = 155.0
        res = api_server._stabilize_contract_plans(copy.deepcopy(payload2))
        plan = res["rows"][0]["suggestion"]["contract_plan"]

        assert plan["stability_observations"] == 1  # Reset because identity changed
        assert plan["stable"] is False

    def test_stale_key_purging_at_2x_max_gap(self, monkeypatch, tmp_path):
        """After 2 * max_gap (5400s), stale entries are purged from memory."""
        self._setup_api_state(monkeypatch, tmp_path)
        base_t = 1_700_000_000.0

        # Symbol A observed at T=0
        monkeypatch.setattr(time, "time", lambda: base_t)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload(symbol="AAPL")))

        assert ("AAPL", "call") in api_server._CONTRACT_STABILITY_STATE
        assert "AAPL" in api_server._DIRECTION_STABILITY_STATE

        # Symbol B observed at T=5401s (> 5400s)
        monkeypatch.setattr(time, "time", lambda: base_t + 5401.0)
        api_server._stabilize_contract_plans(copy.deepcopy(self._make_payload(symbol="MSFT", occ_symbol="MSFT260815C00400000")))

        # AAPL should be pruned due to age > 5400s
        assert ("AAPL", "call") not in api_server._CONTRACT_STABILITY_STATE
        assert "AAPL" not in api_server._DIRECTION_STABILITY_STATE
        # MSFT should be present
        assert ("MSFT", "call") in api_server._CONTRACT_STABILITY_STATE
        assert "MSFT" in api_server._DIRECTION_STABILITY_STATE
