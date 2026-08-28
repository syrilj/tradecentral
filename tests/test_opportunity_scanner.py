from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edge.daily_plays.opportunity_scanner import (
    build_live_opportunities,
    build_suggestion,
    gex_relative_sell,
    qlib_rows_from_panel,
    setup_level_model,
)
from edge.daily_plays.options_intelligence import OptionsFilters


ASOF = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)


def _board_row(symbol, squeeze_score=1.0, spread_pct=0.05, open_interest=500, selected_dte=10, **overrides):
    row = {
        "symbol": symbol,
        "squeeze_score": squeeze_score,
        "spread_pct": spread_pct,
        "open_interest": open_interest,
        "selected_dte": selected_dte,
    }
    row.update(overrides)
    return row


def _flow_row(symbol, unusual_score=50.0, call_put_imbalance=0.2, ret_1d=0.01, **overrides):
    row = {
        "symbol": symbol,
        "unusual_score": unusual_score,
        "call_put_imbalance": call_put_imbalance,
        "ret_1d": ret_1d,
    }
    row.update(overrides)
    return row


def _by_symbol(result):
    return {row["symbol"]: row for row in result["rows"]}


class TestUnionJoin:
    def test_signal_basis_covers_all_three_combinations(self):
        board_rows = [_board_row("BOTH"), _board_row("STRUCT_ONLY")]
        flow_rows = [_flow_row("BOTH"), _flow_row("FLOW_ONLY")]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=flow_rows, filters=OptionsFilters())
        basis = {symbol: row["signal_basis"] for symbol, row in _by_symbol(result).items()}
        assert basis == {"BOTH": "both", "STRUCT_ONLY": "structure_only", "FLOW_ONLY": "flow_only"}

    def test_every_row_appears_exactly_once(self):
        board_rows = [_board_row("AAA"), _board_row("BBB")]
        flow_rows = [_flow_row("BBB"), _flow_row("CCC")]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=flow_rows, filters=OptionsFilters())
        symbols = [row["symbol"] for row in result["rows"]]
        assert sorted(symbols) == ["AAA", "BBB", "CCC"]
        assert len(symbols) == len(set(symbols))

    def test_symbols_are_cleaned_and_first_occurrence_wins_on_duplicates(self):
        board_rows = [
            _board_row(" aaa ", squeeze_score=1.0),
            _board_row("AAA", squeeze_score=999.0),
        ]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=OptionsFilters())
        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["symbol"] == "AAA"
        assert row["board_squeeze_score"] == 1.0

    def test_flow_only_row_carries_no_chain_fields(self):
        result = build_live_opportunities(
            board_rows=[], flow_rows=[_flow_row("ZZZ")], filters=OptionsFilters(),
        )
        row = result["rows"][0]
        assert row["signal_basis"] == "flow_only"
        assert row["spread_pct"] is None
        assert row["open_interest"] is None
        assert row["selected_dte"] is None
        assert row["board_squeeze_score"] is None


class TestCompositeScore:
    def test_averages_zscored_signals_when_both_present(self):
        board_rows = [_board_row("AAA", squeeze_score=10.0), _board_row("BBB", squeeze_score=20.0),
                      _board_row("CCC", squeeze_score=30.0)]
        flow_rows = [_flow_row("AAA", unusual_score=40.0), _flow_row("BBB", unusual_score=60.0),
                     _flow_row("CCC", unusual_score=80.0)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=flow_rows, filters=OptionsFilters())
        rows = _by_symbol(result)
        # Both signals rank the three symbols identically, so composite == the
        # shared per-symbol z-score exactly.
        assert rows["AAA"]["composite_score"] == pytest.approx(-1.2247, abs=1e-4)
        assert rows["BBB"]["composite_score"] == pytest.approx(0.0, abs=1e-4)
        assert rows["CCC"]["composite_score"] == pytest.approx(1.2247, abs=1e-4)

    def test_uses_only_the_signal_that_is_present_for_a_symbol(self):
        board_rows = [_board_row("AAA", squeeze_score=10.0), _board_row("BBB", squeeze_score=20.0),
                      _board_row("CCC", squeeze_score=30.0)]
        flow_rows = [_flow_row("DDD", unusual_score=5.0)]  # DDD has no board row at all
        result = build_live_opportunities(board_rows=board_rows, flow_rows=flow_rows, filters=OptionsFilters())
        rows = _by_symbol(result)
        assert rows["AAA"]["flow_unusual_score"] is None
        assert rows["AAA"]["composite_score"] == rows["AAA"]["board_squeeze_z"]
        assert rows["DDD"]["board_squeeze_score"] is None
        assert rows["DDD"]["composite_score"] == rows["DDD"]["flow_unusual_z"]

    def test_single_observation_zscore_is_neutral_not_fabricated(self):
        # Only one symbol carries a flow score in this pull -- spread is undefined,
        # so the z-score must be a defined neutral 0.0, not an inflated outlier.
        result = build_live_opportunities(
            board_rows=[_board_row("AAA")], flow_rows=[_flow_row("AAA", unusual_score=999.0)],
            filters=OptionsFilters(),
        )
        row = result["rows"][0]
        assert row["flow_unusual_z"] == 0.0


class TestTradabilityGate:
    def test_passes_when_all_thresholds_are_satisfied(self):
        filters = OptionsFilters(max_spread_pct=0.25, min_open_interest=100, min_dte=0, max_dte=60)
        board_rows = [_board_row("AAA", spread_pct=0.10, open_interest=500, selected_dte=20)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        row = result["rows"][0]
        assert row["gate_pass"] is True
        assert row["gate_reasons"] == []

    def test_fails_on_wide_spread_with_human_readable_reason(self):
        filters = OptionsFilters(max_spread_pct=0.12)
        board_rows = [_board_row("AAA", spread_pct=0.18, open_interest=500, selected_dte=10)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        row = result["rows"][0]
        assert row["gate_pass"] is False
        assert "spread 18% > max 12%" in row["gate_reasons"]

    def test_fails_on_low_open_interest_with_human_readable_reason(self):
        filters = OptionsFilters(min_open_interest=100)
        board_rows = [_board_row("AAA", spread_pct=0.05, open_interest=40, selected_dte=10)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        row = result["rows"][0]
        assert row["gate_pass"] is False
        assert "open interest 40 < min 100" in row["gate_reasons"]

    def test_fails_on_dte_outside_window_with_human_readable_reason(self):
        filters = OptionsFilters(min_dte=0, max_dte=60)
        board_rows = [_board_row("AAA", spread_pct=0.05, open_interest=500, selected_dte=75)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        row = result["rows"][0]
        assert row["gate_pass"] is False
        assert "dte 75 outside [0, 60]" in row["gate_reasons"]

    def test_boundary_thresholds_pass_inclusively(self):
        filters = OptionsFilters(max_spread_pct=0.12, min_open_interest=100, min_dte=0, max_dte=60)
        board_rows = [_board_row("AAA", spread_pct=0.12, open_interest=100, selected_dte=60)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        assert result["rows"][0]["gate_pass"] is True

    def test_missing_fields_fail_closed_and_are_never_assumed_tradable(self):
        board_rows = [{"symbol": "AAA", "squeeze_score": 1.0}]  # no spread/OI/dte at all
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=OptionsFilters())
        row = result["rows"][0]
        assert row["gate_pass"] is False
        assert len(row["gate_reasons"]) == 3
        assert all("unmeasured" in reason for reason in row["gate_reasons"])


class TestSort:
    def test_gate_passing_rows_all_sort_before_gate_failing_rows(self):
        filters = OptionsFilters(max_spread_pct=0.25, min_open_interest=100, min_dte=0, max_dte=60)
        board_rows = [
            _board_row("LOW_SCORE_PASS", squeeze_score=1.0, spread_pct=0.05, open_interest=500, selected_dte=10),
            _board_row("HIGH_SCORE_FAIL", squeeze_score=99.0, spread_pct=0.90, open_interest=500, selected_dte=10),
        ]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        symbols_in_order = [row["symbol"] for row in result["rows"]]
        assert symbols_in_order == ["LOW_SCORE_PASS", "HIGH_SCORE_FAIL"]

    def test_failed_rows_are_included_not_discarded(self):
        filters = OptionsFilters(max_spread_pct=0.12)
        board_rows = [_board_row("AAA", spread_pct=0.90)]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=filters)
        assert len(result["rows"]) == 1
        assert result["rows"][0]["gate_pass"] is False


class TestDegradedInput:
    def test_board_rows_empty_still_produces_flow_only_output(self):
        result = build_live_opportunities(
            board_rows=[], flow_rows=[_flow_row("AAA"), _flow_row("BBB")], filters=OptionsFilters(),
        )
        assert result["available"] is True
        assert len(result["rows"]) == 2
        assert all(row["signal_basis"] == "flow_only" for row in result["rows"])
        assert any("No board_rows supplied" in w for w in result["warnings"])

    def test_flow_rows_empty_still_produces_structure_only_output(self):
        result = build_live_opportunities(
            board_rows=[_board_row("AAA"), _board_row("BBB")], flow_rows=[], filters=OptionsFilters(),
        )
        assert result["available"] is True
        assert len(result["rows"]) == 2
        assert all(row["signal_basis"] == "structure_only" for row in result["rows"])
        assert any("No flow_rows supplied" in w for w in result["warnings"])

    def test_both_empty_returns_unavailable_with_reason(self):
        result = build_live_opportunities(board_rows=[], flow_rows=[], filters=OptionsFilters())
        assert result["available"] is False
        assert result["reason"] == "No board or unusual-flow rows were supplied."
        assert result["suggestion"]["right"] == "blocked"
        assert result["suggestion"]["sell"] is None

    def test_rows_missing_symbols_are_ignored_not_crashed_on(self):
        board_rows = [{"squeeze_score": 1.0}, "not-a-dict", _board_row("AAA")]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[], filters=OptionsFilters())
        assert [row["symbol"] for row in result["rows"]] == ["AAA"]


class TestPayloadShape:
    def test_top_level_fields_never_authorize_a_decision(self):
        result = build_live_opportunities(board_rows=[_board_row("AAA")], flow_rows=[], filters=OptionsFilters())
        assert result["decision_authorized"] is False
        assert result["score_kind"] == "ordinal_composite"
        assert result["available"] is True

    def test_coverage_reports_source_and_gate_counts(self):
        filters = OptionsFilters(max_spread_pct=0.12)
        board_rows = [
            _board_row("PASS", spread_pct=0.05),
            _board_row("FAIL", spread_pct=0.90),
        ]
        result = build_live_opportunities(board_rows=board_rows, flow_rows=[_flow_row("PASS")], filters=filters)
        cov = result["coverage"]
        assert cov["board_symbols"] == 2
        assert cov["flow_symbols"] == 1
        assert cov["union_symbols"] == 2
        assert cov["gate_pass"] == 1
        assert cov["gate_fail"] == 1


class TestConfidenceFreshnessAndPlaybook:
    def _live_board(self, symbol="AAA", **overrides):
        values = {
            "score_kind": "calibrated_probability",
            "selection_score": 0.71,
            "context_side": "long",
            "mode_resolved": "live",
            "chain_source": "lse_live",
            "observed_at": ASOF.isoformat(),
            "age_seconds": 5,
            "spot": 100,
            "expected_move": 4,
            "call_wall": 108,
            "put_wall": 96,
            "gamma_flip": 101,
            "pin_strike": 100,
            "selected_expiry": "2026-08-21",
        }
        values.update(overrides)
        return _board_row(symbol, **values)

    def _live_flow(self, symbol="AAA", **overrides):
        values = {
            "live": True,
            "live_asof": ASOF.isoformat(),
            "premium": 500_000,
            "context_side": "long",
        }
        values.update(overrides)
        return _flow_row(symbol, **values)

    def test_highlight_requires_calibrated_probability_and_fresh_live_inputs(self):
        result = build_live_opportunities(
            board_rows=[self._live_board()],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["confidence"]["band"] == "HIGH"
        assert row["freshness"]["pass"] is True
        assert row["highlighted"] is True
        assert row["playbook"]["status"] == "candidate"
        assert result["coverage"]["high_confidence"] == 1

    def test_large_ordinal_score_never_masquerades_as_confidence(self):
        board = self._live_board(score_kind="ordinal_score", selection_score=999.0)
        result = build_live_opportunities(
            board_rows=[board], flow_rows=[self._live_flow()], filters=OptionsFilters(), asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["confidence"]["band"] == "UNCALIBRATED"
        assert row["highlighted"] is False
        assert row["playbook"]["status"] == "research_only"

    def test_calibrated_overlay_survives_a_higher_priority_ordinal_board_route(self):
        board = self._live_board(score_kind="ordinal_activity", selection_score=99.0)
        calibrated = [{
            "symbol": "AAA",
            "side": "SHORT",
            "probability": 0.61,
            "confidence_kind": "calibrated_probability",
            "calibration_version": "v1",
            "model": "frozen_model",
            "setup_ok": True,
            "state": "WATCH",
        }]
        result = build_live_opportunities(
            board_rows=[board],
            flow_rows=[self._live_flow()],
            calibrated_rows=calibrated,
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["confidence"]["band"] == "MODERATE"
        assert row["confidence"]["calibration_version"] == "v1"
        assert row["playbook"]["direction"] == "short"
        assert row["playbook"]["direction_source"] == "calibrated_directional_model"

    def test_high_probability_watch_state_does_not_become_a_candidate(self):
        calibrated = [{
            "symbol": "AAA",
            "side": "LONG",
            "probability": 0.72,
            "confidence_kind": "calibrated_probability",
            "setup_ok": False,
            "state": "WATCH",
        }]
        result = build_live_opportunities(
            board_rows=[self._live_board(score_kind="ordinal_activity")],
            flow_rows=[self._live_flow()],
            calibrated_rows=calibrated,
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["confidence"]["band"] == "HIGH"
        assert row["highlighted"] is False
        assert row["playbook"]["status"] == "research_only"
        assert any("setup gate is not active" in blocker for blocker in row["playbook"]["blockers"])

    def test_stale_chain_blocks_an_otherwise_high_confidence_candidate(self):
        board = self._live_board(observed_at="2026-08-09T19:50:00+00:00", age_seconds=600)
        result = build_live_opportunities(
            board_rows=[board], flow_rows=[self._live_flow()], filters=OptionsFilters(), asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["freshness"]["pass"] is False
        assert row["highlighted"] is False
        assert row["playbook"]["status"] == "blocked"
        assert row["suggestion"]["status"] == "plan"
        assert row["suggestion"]["entry_eligible"] is False
        assert any("chain age" in reason for reason in row["freshness"]["reasons"])

    def test_defined_risk_playbook_uses_measured_barriers_and_size_formula(self):
        result = build_live_opportunities(
            board_rows=[self._live_board()],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        play = result["rows"][0]["playbook"]
        assert play["structure"] == "call_debit_spread"
        assert play["trigger"] == pytest.approx(101)
        assert play["target"] == pytest.approx(108)
        assert play["invalidation"] == pytest.approx(96)
        assert play["risk"]["max_account_risk_pct"] == pytest.approx(0.005)
        assert "net_debit" in play["risk"]["sizing_formula"]

    def test_quote_cost_estimate_is_explicitly_incomplete(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(spread_pct=0.10)],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        costs = result["rows"][0]["costs"]
        assert costs["one_way_half_spread_pct"] == pytest.approx(0.05)
        assert costs["one_way_half_spread_bps"] == pytest.approx(500)
        assert costs["complete"] is False
        assert costs["market_impact"] is None


class TestSuggestionAndRisk(TestConfidenceFreshnessAndPlaybook):
    def test_flow_only_long_suggests_call_with_unmeasured_sell(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row("AAA", context_side="long")],
            filters=OptionsFilters(),
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["sell"] is None
        assert sug["sell_source"] is None
        assert sug["spot"] is None
        assert sug["qlib"]["measured"] is False
        assert sug["qlib"]["score"] is None
        assert sug["qlib"]["alignment"] == "unmeasured"

    def test_flow_only_short_suggests_put(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row("AAA", context_side="short")],
            filters=OptionsFilters(),
        )
        assert result["rows"][0]["suggestion"]["right"] == "put"

    def test_call_wall_above_spot_is_the_long_sell(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(spot=100, call_wall=108, put_wall=96)],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["sell"] == pytest.approx(108)
        assert sug["sell_source"] == "call_wall"
        assert sug["sell_rel_pct"] == pytest.approx(0.08)
        assert sug["invalidation"] == pytest.approx(96)
        assert sug["invalidation_source"] == "put_wall"

    def test_put_wall_below_spot_is_the_short_sell(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(context_side="short", spot=100, call_wall=108, put_wall=94)],
            flow_rows=[self._live_flow(context_side="short")],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "put"
        assert sug["sell"] == pytest.approx(94)
        assert sug["sell_source"] == "put_wall"
        assert sug["sell_rel_pct"] == pytest.approx(-0.06)

    def test_wrong_side_walls_stay_unmeasured(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(spot=100, call_wall=95, put_wall=110)],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["sell"] is None
        assert sug["sell_source"] is None
        assert sug["sell_rel_pct"] is None
        assert sug["invalidation"] is None

    def test_missing_walls_do_not_invent_an_expected_move_sell(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(spot=100, call_wall=None, put_wall=None, expected_move=4)],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["sell"] is None
        assert sug["sell"] != pytest.approx(104)
        assert sug["plan_target"] is None
        assert sug["plan_invalidation"] is None
        assert sug["risk_levels_complete"] is False
        assert "GEX take-profit target" in sug["risk_missing_fields"]
        assert "GEX invalidation" in sug["risk_missing_fields"]
        assert all(zone.get("price") != pytest.approx(104) for zone in (sug.get("take_profit_zones") or []))
        assert result["rows"][0]["playbook"]["target"] is None
        assert result["rows"][0]["playbook"]["invalidation"] is None
        assert result["rows"][0]["playbook"]["status"] == "research_only"
        assert result["rows"][0]["highlighted"] is False
        assert any("call wall above spot" in item for item in sug["blockers"])
        assert any("put wall below spot" in item for item in sug["blockers"])

    def test_wrong_side_risk_levels_cannot_become_ready(self):
        result = build_live_opportunities(
            board_rows=[self._live_board(spot=100, call_wall=99, put_wall=101)],
            flow_rows=[self._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        assert row["confidence"]["band"] == "HIGH"
        assert row["gate_pass"] is True
        assert row["freshness"]["pass"] is True
        assert row["playbook"]["risk_levels_complete"] is False
        assert row["suggestion"]["entry_eligible"] is False
        assert row["suggestion"]["setup_tier"] == "paper"
        assert row["live_ready"] is False
        assert result["coverage"]["live_ready"] == 0

    def test_no_direction_is_watch_or_blocked_with_an_explicit_reason(self):
        result = build_live_opportunities(
            board_rows=[_board_row("AAA")],
            flow_rows=[_flow_row("AAA")],
            filters=OptionsFilters(),
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] in {"watch", "blocked"}
        assert sug["reason"]
        assert any("long/short" in item.lower() for item in sug["blockers"])

    def test_unsigned_activity_lean_becomes_unsized_paper_candidate(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row(
                "AAA",
                activity_lean="bullish",
                activity_lean_source="call_put_premium",
                spot=123.45,
                flow_focus={
                    "call": {
                        "right": "call", "strike": 125, "expiry": "2026-09-18",
                        "dte": 35, "price": 2.5, "premium": 250_000,
                        "contracts": 1000, "timestamp": "2026-08-13T20:00:00Z",
                    },
                },
            )],
            filters=OptionsFilters(),
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["status"] == "paper_candidate"
        assert sug["setup_tier"] == "paper"
        assert sug["evidence_kind"] == "activity_lean"
        assert sug["entry_eligible"] is False
        assert sug["bias_right"] == "call"
        assert sug["bias_confirmed"] is False
        assert sug["spot"] == pytest.approx(123.45)
        assert "paper call candidate" in sug["reason"].lower()
        assert sug["contract_plan"]["action"] == "REVIEW_FLOW_PRINT"
        assert sug["contract_plan"]["sizing_eligible"] is False
        assert sug["contract_plan"]["sizing_debit"] is None
        play = sug["contract_plan"]["play"]
        assert play["strategy"] == "long_call"
        assert play["breakeven"] == pytest.approx(127.5)
        assert play["max_loss"] == pytest.approx(250.0)
        assert play["decision_authorized"] is False
        assert play["vol_source"] == "unmeasured"

    def test_invalid_observed_flow_contract_is_not_forwarded_as_a_plan(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row(
                "AAA",
                activity_lean="bullish",
                activity_lean_source="call_put_premium",
                spot=100.0,
                flow_focus={
                    "call": {
                        "right": "call", "strike": 5, "expiry": "2026-12-18",
                        "dte": 126, "price": 95.0, "premium": 9_500_000,
                        "contracts": 1000, "timestamp": "2026-08-14T16:00:00Z",
                    },
                },
            )],
            filters=OptionsFilters(),
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["contract_plan"] is None
        assert any("rejected before planning" in item for item in sug["warnings"])

    def test_upstream_flow_contract_rejections_are_explicit(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row(
                "AAA",
                activity_lean="bullish",
                activity_lean_source="call_put_premium",
                spot=100.0,
                flow_focus={},
                flow_focus_rejections={
                    "call": ["contract is outside the 0–60 DTE review window"],
                },
            )],
            filters=OptionsFilters(),
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["contract_plan"] is None
        assert any("excluded from planning" in item for item in sug["warnings"])
        assert any("0–60 DTE" in item for item in sug["warnings"])

    def test_chain_contract_wins_and_returns_a_complete_specific_plan(self):
        board = _board_row(
            "AAA",
            spot=120,
            contract_focus={
                "call": {
                    "right": "call", "strike": 125, "expiry": "2026-09-18", "dte": 35,
                    "bid": 2.4, "ask": 2.6, "midpoint": 2.5, "spread_pct": 0.08,
                    "volume": 320, "open_interest": 1800, "implied_volatility": 0.34,
                    "delta": 0.46, "contract_multiplier": 100,
                    "observed_at": "2026-08-13T20:00:00Z", "quote_complete": True,
                    "liquidity_complete": True, "tenor_complete": True,
                    "contract_complete": True, "rejection_reasons": [],
                    "selection_method": "fixture selector",
                },
            },
        )
        result = build_live_opportunities(
            board_rows=[board],
            flow_rows=[_flow_row(
                "AAA", activity_lean="bullish", activity_lean_source="signed_flow",
            )],
            filters=OptionsFilters(),
        )
        plan = result["rows"][0]["suggestion"]["contract_plan"]
        assert plan["kind"] == "chain_selected_contract"
        assert plan["action"] == "REVIEW_ONLY"
        assert plan["strike"] == pytest.approx(125)
        assert plan["reference_debit"] == pytest.approx(2.5)
        assert plan["reference_max_loss"] == pytest.approx(250.0)
        assert plan["take_profit_debit"] is None
        assert plan["review_exit_debit"] is None
        assert plan["play"]["breakeven"] == pytest.approx(127.5)
        assert plan["play"]["vol_source"] == "contract_iv"
        assert plan["play"]["greeks"]["delta"] > 0
        assert plan["play"]["decision_authorized"] is False
        assert plan["open_interest"] == 1800
        assert plan["quote_status"] == "chain_two_sided"
        assert plan["sizing_eligible"] is False

    def test_delayed_exact_quote_is_visible_but_never_sizing_eligible(self):
        board = _board_row(
            "AAA",
            contract_focus={
                "call": {
                    "right": "call", "strike": 125, "expiry": "2026-09-18", "dte": 35,
                    "bid": 2.4, "ask": 2.6, "midpoint": 2.5, "spread_pct": 0.08,
                    "volume": 320, "open_interest": 1800, "implied_volatility": 0.34,
                    "delta": 0.46, "contract_multiplier": 100,
                    "observed_at": "2026-08-13T20:00:00Z", "quote_complete": False,
                    "quote_live": False, "quote_reference_only": True,
                    "quote_status": "delayed_reference",
                    "quote_source": "yfinance_delayed_exact_occ",
                    "liquidity_complete": True, "tenor_complete": True,
                    "contract_complete": False,
                    "rejection_reasons": [
                        "quote is delayed reference only; live two-sided quote required",
                    ],
                    "selection_method": "fixture delayed selector",
                },
            },
        )
        result = build_live_opportunities(
            board_rows=[board],
            flow_rows=[_flow_row(
                "AAA", activity_lean="bullish", activity_lean_source="signed_flow",
            )],
            filters=OptionsFilters(),
        )
        plan = result["rows"][0]["suggestion"]["contract_plan"]
        assert plan["action"] == "WAIT_FOR_LIVE_QUOTE"
        assert plan["quote_status"] == "delayed_reference"
        assert plan["bid"] == pytest.approx(2.4)
        assert plan["midpoint"] == pytest.approx(2.5)
        assert plan["ask"] == pytest.approx(2.6)
        assert plan["reference_debit"] == pytest.approx(2.5)
        assert plan["sizing_debit"] is None
        assert plan["sizing_eligible"] is False
        assert "live bid" in plan["missing_fields"]
        assert "live ask" in plan["missing_fields"]
        assert result["rows"][0]["live_ready"] is False
        assert result["coverage"]["live_ready"] == 0

    def test_neutral_activity_without_direction_remains_blocked(self):
        result = build_live_opportunities(
            board_rows=[],
            flow_rows=[_flow_row("AAA", activity_lean="neutral")],
            filters=OptionsFilters(),
        )
        assert result["rows"][0]["suggestion"]["right"] == "blocked"

    def test_qlib_rank_confirms_a_long_call_when_present(self):
        result = build_live_opportunities(
            board_rows=[self._live_board()],
            flow_rows=[self._live_flow()],
            qlib_rows=[{
                "symbol": "AAA",
                "qlib_score": 0.55,
                "qlib_rank": 2,
                "n_symbols": 12,
                "source": "qlib_scan_lgb_v2",
                "score_kind": "ordinal_qlib_xs",
            }],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["qlib"]["measured"] is True
        assert sug["qlib"]["score"] == pytest.approx(0.55)
        assert sug["qlib"]["rank"] == 2
        assert sug["qlib"]["alignment"] == "confirms"
        assert result["rows"][0]["qlib_score"] == pytest.approx(0.55)

    def test_qlib_conflict_is_reported_not_used_to_flip_the_right(self):
        result = build_live_opportunities(
            board_rows=[self._live_board()],
            flow_rows=[self._live_flow()],
            qlib_rows=[{
                "symbol": "AAA",
                "qlib_score": -0.4,
                "qlib_rank": 11,
                "n_symbols": 12,
                "source": "qlib_scan_lgb_v2",
            }],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        sug = result["rows"][0]["suggestion"]
        assert sug["right"] == "call"
        assert sug["qlib"]["alignment"] == "conflicts"
        assert any("qlib" in w.lower() for w in sug["warnings"])

    def test_missing_qlib_stays_unmeasured(self):
        result = build_live_opportunities(
            board_rows=[self._live_board()],
            flow_rows=[self._live_flow()],
            qlib_rows=[],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        qlib = result["rows"][0]["suggestion"]["qlib"]
        assert qlib["score"] is None
        assert qlib["rank"] is None
        assert qlib["alignment"] == "unmeasured"
        assert qlib["measured"] is False

    def test_empty_union_exposes_a_blocked_suggestion_not_a_silent_gap(self):
        result = build_live_opportunities(board_rows=[], flow_rows=[], filters=OptionsFilters())
        assert result["available"] is False
        assert result["suggestion"]["right"] == "blocked"
        assert result["suggestion"]["sell"] is None
        assert result["suggestion"]["reason"]

    def test_gex_relative_sell_is_the_shipped_risk_entry(self):
        measured = gex_relative_sell(direction="long", spot=50, call_wall=55, put_wall=46)
        assert measured["sell"] == pytest.approx(55)
        assert measured["sell_rel_pct"] == pytest.approx(0.10)
        absent = gex_relative_sell(direction="long", spot=50, call_wall=None, put_wall=46)
        assert absent["sell"] is None
        assert absent["measured"] is False

    def test_build_suggestion_is_the_shipped_right_entry(self):
        sug = build_suggestion(
            direction="short",
            playbook_status="research_only",
            blockers=["Calibrated probability is below 65%."],
            spot=200,
            call_wall=210,
            put_wall=188,
            qlib={"qlib_score": 0.1, "qlib_rank": 20, "n_symbols": 21, "source": "deep"},
        )
        assert sug["right"] == "put"
        assert sug["sell"] == pytest.approx(188)
        assert sug["qlib"]["alignment"] == "confirms"

    def test_qlib_rows_from_panel_do_not_invent_missing_symbols(self):
        rows = qlib_rows_from_panel({
            "quality": "ok",
            "source": "qlib_scan_lgb_v2",
            "coverage": {"scored": 2},
            "by_symbol": {
                "AAA": {"symbol": "AAA", "qlib_score": 0.2, "qlib_rank": 1},
            },
        })
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAA"
        assert rows[0]["n_symbols"] == 2
        assert qlib_rows_from_panel(None) == []
        assert qlib_rows_from_panel({"by_symbol": {}}) == []


ALLOWED_LEVEL_SOURCES = {
    "resistance/support",
    "options GEX",
    "positions",
    "technical analysis",
}


class TestSetupLevelModel:
    def test_complete_inputs_attribute_each_headline_to_a_measured_source(self):
        model = setup_level_model(
            direction="long",
            spot=100,
            support=97,
            resistance=110,
            call_wall=108,
            put_wall=96,
            gamma_flip=101,
            pin_strike=100,
            position_strike=102,
            ta_support=95.5,
            expected_move=4,
        )
        assert model["strike"] == pytest.approx(102)
        assert model["strike_source"] == "positions"
        support_sources = {item["source"] for item in model["supports"]}
        zone_sources = {item["source"] for item in model["take_profit_zones"]}
        assert {item["price"] for item in model["supports"]} >= {96, 97, 95.5}
        assert model["invalidation"] is not None
        assert model["invalidation"] < 100
        assert model["invalidation_source"] in ALLOWED_LEVEL_SOURCES
        assert {item["price"] for item in model["take_profit_zones"]} >= {108, 110, 101}
        assert support_sources <= ALLOWED_LEVEL_SOURCES
        assert zone_sources <= ALLOWED_LEVEL_SOURCES
        assert support_sources & {"resistance/support", "options GEX", "technical analysis"}
        assert zone_sources & {"resistance/support", "options GEX", "technical analysis"}
        assert all(item["price"] != pytest.approx(104) for item in model["take_profit_zones"])
        assert model["complete"] is True
        assert model["risk_levels_complete"] is True

    def test_expected_move_and_wrong_side_levels_stay_unmeasured(self):
        model = setup_level_model(
            direction="long",
            spot=100,
            support=110,
            resistance=90,
            call_wall=95,
            put_wall=112,
            gamma_flip=None,
            pin_strike=None,
            position_strike=None,
            expected_move=4,
        )
        assert model["strike"] is None
        assert model["supports"] == []
        assert model["invalidation"] is None
        assert model["take_profit_zones"] == []
        assert model["complete"] is False
        assert model["risk_levels_complete"] is False
        assert 104 not in [item.get("price") for item in model["take_profit_zones"]]
        assert "expected_move" not in str(model).lower() or all(
            item.get("source") != "expected_move" for item in model["take_profit_zones"]
        )

    def test_live_opportunities_complete_payload_keeps_source_tags(self):
        helper = TestConfidenceFreshnessAndPlaybook()
        result = build_live_opportunities(
            board_rows=[helper._live_board(
                support_price=97,
                resistance_price=110,
                pin_strike=100,
                ta_support=95.5,
                gex_by_strike=[
                    {"strike": 96, "put_gex_m": -2.4, "call_gex_m": 0.1, "put_oi": 4200, "call_oi": 200},
                    {"strike": 100, "put_gex_m": -0.4, "call_gex_m": 0.5, "call_oi": 9000, "put_oi": 8800},
                    {"strike": 108, "put_gex_m": 0.0, "call_gex_m": 3.1, "call_oi": 5100, "put_oi": 300},
                ],
                contract_focus={"call": {
                    "right": "call", "strike": 101, "expiry": "2026-08-21", "dte": 12,
                    "bid": 2.1, "ask": 2.3, "midpoint": 2.2, "spread_pct": 0.09,
                    "volume": 400, "open_interest": 2200, "implied_volatility": 0.28,
                    "delta": 0.51, "contract_multiplier": 100,
                    "observed_at": ASOF.isoformat(), "quote_complete": True,
                    "contract_complete": True, "rejection_reasons": [],
                    "selection_method": "complete fixture",
                }},
            )],
            flow_rows=[helper._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        sug = row["suggestion"]
        assert sug["strike"] == pytest.approx(101)
        assert sug["strike_source"] in ALLOWED_LEVEL_SOURCES
        assert sug["supports"]
        assert sug["invalidation"] is not None
        assert sug["take_profit_zones"]
        assert {item["source"] for item in sug["supports"]} <= ALLOWED_LEVEL_SOURCES
        assert {item["source"] for item in sug["take_profit_zones"]} <= ALLOWED_LEVEL_SOURCES
        assert sug["invalidation_source"] in ALLOWED_LEVEL_SOURCES or sug["plan_invalidation_source"] in {
            "put_wall", "call_wall", *ALLOWED_LEVEL_SOURCES,
        }
        assert sug["risk_levels_complete"] is True

    def test_incomplete_expected_move_cannot_become_ready(self):
        helper = TestConfidenceFreshnessAndPlaybook()
        result = build_live_opportunities(
            board_rows=[helper._live_board(
                spot=100, call_wall=None, put_wall=None, expected_move=4,
                gamma_flip=None, pin_strike=None, support_price=None, resistance_price=None,
            )],
            flow_rows=[helper._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        sug = row["suggestion"]
        assert sug["sell"] is None
        assert sug["plan_target"] is None
        assert sug["plan_invalidation"] is None
        assert sug["supports"] in (None, [])
        assert not sug.get("take_profit_zones")
        assert all(
            zone.get("price") != pytest.approx(104)
            for zone in (sug.get("take_profit_zones") or [])
        )
        assert sug["risk_levels_complete"] is False
        assert row["live_ready"] is False
        assert row["highlighted"] is False
        assert row["playbook"]["status"] != "candidate"
        assert row["confidence"]["band"] == "HIGH"
        assert result["coverage"]["live_ready"] == 0


class TestGammaFlipLevelSource:
    """Verify gamma_flip is strictly attributed to LEVEL_SOURCE_GEX ("options GEX")."""

    def test_gamma_flip_below_spot_is_tagged_as_options_gex_in_supports(self):
        """When gamma_flip < spot, it must be added to supports with source="options GEX"."""
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=98.0,
            support=None,
            resistance=None,
            call_wall=None,
            put_wall=None,
        )
        assert len(model["supports"]) == 1
        support_item = model["supports"][0]
        assert support_item["price"] == pytest.approx(98.0)
        assert support_item["source"] == "options GEX"
        assert support_item["source"] != "technical analysis"
        assert model["source_status"]["options GEX"] == "measured"
        assert model["source_status"]["technical analysis"] == "unmeasured"

    def test_gamma_flip_above_spot_is_tagged_as_options_gex_in_resistances(self):
        """When gamma_flip > spot, it must be added to take_profit_zones with source="options GEX"."""
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=105.0,
            support=None,
            resistance=None,
            call_wall=None,
            put_wall=None,
        )
        assert len(model["take_profit_zones"]) == 1
        zone_item = model["take_profit_zones"][0]
        assert zone_item["price"] == pytest.approx(105.0)
        assert zone_item["source"] == "options GEX"
        assert zone_item["source"] != "technical analysis"
        assert model["source_status"]["options GEX"] == "measured"
        assert model["source_status"]["technical analysis"] == "unmeasured"

    def test_gamma_flip_invalidation_source_is_options_gex(self):
        """When gamma_flip serves as the closest support for a long setup, invalidation_source is "options GEX"."""
        model = setup_level_model(
            direction="long",
            spot=100.0,
            gamma_flip=97.5,
            put_wall=95.0,  # further below spot than gamma_flip
        )
        assert model["invalidation"] == pytest.approx(97.5)
        assert model["invalidation_source"] == "options GEX"


class TestPlanTargetAndInvalidationSources:
    """Verify plan_target_source and plan_invalidation_source are preserved and never None when prices exist."""

    def test_plan_sources_populated_for_standard_gex_walls(self):
        """Standard GEX call/put walls retain 'options GEX' or specific wall source tags."""
        helper = TestConfidenceFreshnessAndPlaybook()
        result = build_live_opportunities(
            board_rows=[helper._live_board(
                spot=100.0,
                call_wall=110.0,
                put_wall=95.0,
                support_price=97.0,
                resistance_price=108.0,
            )],
            flow_rows=[helper._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        sug = row["suggestion"]

        # Target assertions
        assert sug["plan_target"] is not None
        assert sug["plan_target_source"] is not None
        assert sug["plan_target_source"] in {"call_wall", "options GEX", "resistance/support", "technical analysis"}

        # Invalidation assertions
        assert sug["plan_invalidation"] is not None
        assert sug["plan_invalidation_source"] is not None
        assert sug["plan_invalidation_source"] in {"put_wall", "options GEX", "resistance/support", "technical analysis"}

    def test_plan_sources_retained_when_flow_state_levels_attached(self):
        """Attached flow state resistance/support levels retain valid source tags in suggestion."""
        helper = TestConfidenceFreshnessAndPlaybook()
        # Board with flow state support/resistance but no raw GEX walls
        board = helper._live_board(
            spot=100.0,
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            support_price=96.5,
            resistance_price=107.5,
        )
        result = build_live_opportunities(
            board_rows=[board],
            flow_rows=[helper._live_flow()],
            filters=OptionsFilters(),
            asof_utc=ASOF,
        )
        row = result["rows"][0]
        sug = row["suggestion"]

        assert sug["invalidation"] == pytest.approx(96.5)
        assert sug["invalidation_source"] == "resistance/support"
        if sug.get("plan_invalidation") is not None:
            assert sug["plan_invalidation_source"] is not None
