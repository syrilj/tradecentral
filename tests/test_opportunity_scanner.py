from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edge.daily_plays.opportunity_scanner import build_live_opportunities
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
        assert result == {"available": False, "reason": "No board or unusual-flow rows were supplied."}

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
