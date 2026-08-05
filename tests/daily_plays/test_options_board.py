"""Selection and summarisation for the options conviction board."""

from __future__ import annotations

import pytest

from edge.daily_plays.options_board import (
    CLOCK_SKEW_WARN_DAYS,
    board_payload,
    clock_skew_days,
    select_board_candidates,
    summarize_board_row,
)


def _status(**overrides):
    base = {
        "asof": "2026-08-04 14:00:00 UTC",
        "pead_candidates": [
            {"symbol": "AAA", "side": "long", "evidence": {"pead_score": 1.2}},
            {"symbol": "BBB", "side": "short", "evidence": {"pead_score": -3.4}},
        ],
        "directional_signals": [
            {"symbol": "DDD", "side": "long", "probability": 0.61},
        ],
        "activity_scan": {
            "asof": "2026-08-04T14:00:00+00:00",
            "rows": [
                {
                    "symbol": "CCC", "activity_score": 80.0, "live": True,
                    "print_count": 12, "flags": ["LIVE OPTIONS FLOW"],
                    "context_side": "long", "sources": ["LSE live flow"],
                },
                {
                    "symbol": "EEE", "activity_score": 55.0, "live": False,
                    "print_count": 0, "flags": ["VOLUME SPIKE"], "context_side": "neutral",
                },
                {
                    # Filler-only flag: not evidence, must not be selected.
                    "symbol": "FFF", "activity_score": 50.0, "live": False,
                    "print_count": 0, "flags": ["ACTIVITY RANK"], "context_side": "neutral",
                },
            ],
        },
    }
    base.update(overrides)
    return base


class TestSelection:
    def test_pead_outranks_live_flow_and_sorts_by_absolute_score(self):
        selected, considered = select_board_candidates(status=_status(), limit=10)
        assert [c.symbol for c in selected] == ["BBB", "AAA", "CCC", "EEE", "DDD"]
        assert selected[0].selection_basis == "pead_ordinal"
        assert selected[0].selection_score == pytest.approx(3.4)
        assert considered == 5

    def test_filler_flag_row_is_never_selected(self):
        selected, _ = select_board_candidates(status=_status(), limit=10)
        assert "FFF" not in [c.symbol for c in selected]

    def test_score_kinds_are_never_conflated(self):
        selected, _ = select_board_candidates(status=_status(), limit=10)
        kinds = {c.symbol: c.score_kind for c in selected}
        assert kinds["BBB"] == "ordinal_score"
        assert kinds["CCC"] == "ordinal_activity"
        # The frozen-domain model is the only calibrated input on the board.
        assert kinds["DDD"] == "calibrated_probability"

    def test_duplicate_symbol_keeps_first_tier_and_merges_sources(self):
        status = _status()
        status["activity_scan"]["rows"].append({
            "symbol": "BBB", "activity_score": 90.0, "live": True, "print_count": 4,
            "flags": ["LIVE OPTIONS FLOW"], "context_side": "short",
            "sources": ["LSE live flow"],
        })
        selected, considered = select_board_candidates(status=status, limit=10)
        bbb = next(c for c in selected if c.symbol == "BBB")
        assert bbb.selection_basis == "pead_ordinal"
        assert "LSE live flow" in bbb.sources
        assert "PEAD ordinal flag" in bbb.sources
        assert considered == 5, "a duplicate must not inflate the search width"

    def test_require_live_flow_drops_lower_tiers(self):
        selected, _ = select_board_candidates(
            status=_status(), limit=10, require_live_flow=True,
        )
        assert [c.symbol for c in selected] == ["BBB", "AAA", "CCC"]

    def test_limit_truncates_but_considered_reports_full_width(self):
        selected, considered = select_board_candidates(status=_status(), limit=2)
        assert len(selected) == 2
        assert considered == 5, "search width must survive the top-N slice"

    def test_ranks_are_assigned_in_selection_order(self):
        selected, _ = select_board_candidates(status=_status(), limit=10)
        assert [c.rank for c in selected] == [1, 2, 3, 4, 5]

    def test_empty_status_is_not_an_error(self):
        selected, considered = select_board_candidates(status={}, limit=10)
        assert selected == []
        assert considered == 0


def _intel(**overrides):
    base = {
        "observed_at": "2026-08-04T18:00:00+00:00",
        "mode_resolved": "live",
        "summary": {
            "spot": 100.0, "total_gex_m": -12.5, "regime": "negative",
            "call_oi": 4000, "put_oi": 3500,
            "call_premium": 1000.0, "put_premium": 500.0, "activity_imbalance": 0.33,
            "call_wall_pct": 0.05, "put_wall_pct": -0.04,
            "squeeze": {
                "score": 0.62, "label": "elevated", "primary": "bullish",
                "structure_score": 41.0, "long_gamma_dampened": False,
                "key_levels": {"call_wall": 105.0, "put_wall": 96.0,
                               "gamma_flip": 101.0, "pin_strike": 100.0},
            },
        },
        "probability": {"expected_move": 4.2, "atm_iv": 0.38},
        "quality": {"chain_contracts_included": 88},
        "provider": {
            "chain": "lse_live", "activity_basis": "trade_tape",
            "open_interest": "lse_live",
        },
        "freshness": {"age_seconds": 12.0},
        "chain_context": {"selected_expiry": "2026-08-21", "selected_dte": 17},
        "warnings": ["w1", "w2", "w3", "w4"],
    }
    base.update(overrides)
    return base


class TestSummarize:
    def _candidate(self):
        selected, _ = select_board_candidates(status=_status(), limit=1)
        return selected[0]

    def test_extracts_structure_without_authorizing_a_decision(self):
        row = summarize_board_row(
            self._candidate(), _intel(), price_asof="2026-08-04T20:00:00+00:00",
        )
        assert row["available"] is True
        assert row["squeeze_score"] == pytest.approx(0.62)
        assert row["net_gex_m"] == pytest.approx(-12.5)
        assert row["call_wall"] == pytest.approx(105.0)
        assert row["decision_authorized"] is False

    def test_warning_list_is_capped(self):
        row = summarize_board_row(self._candidate(), _intel())
        assert len(row["warnings"]) == 3

    def test_failed_fetch_stays_on_the_board(self):
        row = summarize_board_row(self._candidate(), None, error="boom")
        assert row["available"] is False
        assert row["error"] == "boom"
        assert row["symbol"] == "BBB", "a failure must not lose the candidate"

    def test_engine_error_payload_is_reported_not_swallowed(self):
        row = summarize_board_row(self._candidate(), {"error": "no spot"})
        assert row["available"] is False
        assert row["error"] == "no spot"


class TestUnmeasuredGex:
    """A zero from an absent observation is not a reading of zero."""

    def _row(self, **intel_overrides):
        candidate = select_board_candidates(status=_status(), limit=1)[0][0]
        return summarize_board_row(candidate, _intel(**intel_overrides))

    def test_observed_open_interest_is_measurable(self):
        assert self._row()["gex_measurable"] is True

    def test_zero_open_interest_nulls_structure_instead_of_reporting_quiet(self):
        summary = dict(_intel()["summary"])
        summary.update({"call_oi": 0, "put_oi": 0, "total_gex_m": 0.0, "regime": "neutral"})
        summary["squeeze"] = {**summary["squeeze"], "score": 0.0, "label": "quiet"}
        row = self._row(summary=summary)
        assert row["gex_measurable"] is False
        assert row["net_gex_m"] is None
        assert row["squeeze_score"] is None, "0.0 would read as a measured quiet market"
        assert row["squeeze_label"] is None
        assert row["call_wall"] is None
        assert "unmeasured" in row["warnings"][0]

    def test_unavailable_oi_source_is_unmeasurable_even_with_nonzero_oi(self):
        row = self._row(provider={
            "chain": "lse_live", "activity_basis": "trade_tape",
            "open_interest": "unavailable",
        })
        assert row["gex_measurable"] is False
        assert row["squeeze_score"] is None

    def test_non_structural_fields_survive_an_unmeasurable_row(self):
        summary = dict(_intel()["summary"])
        summary.update({"call_oi": 0, "put_oi": 0})
        row = self._row(summary=summary)
        assert row["available"] is True
        assert row["spot"] == pytest.approx(100.0)
        assert row["call_premium"] == pytest.approx(1000.0)
        assert row["atm_iv"] == pytest.approx(0.38)

    def test_payload_separates_unmeasured_from_scored(self):
        summary = dict(_intel()["summary"])
        summary.update({"call_oi": 0, "put_oi": 0})
        rows = [self._row(), self._row(summary=summary)]
        payload = board_payload(
            rows=rows, candidates_considered=59, requested=2, depth="quick",
            scan_asof=None, asof_utc="2026-08-04T18:00:00+00:00",
            limit=25, require_live_flow=False,
        )
        assert payload["coverage"]["gex_unmeasured"] == 1
        assert payload["coverage"]["squeeze_scored"] == 1
        assert payload["coverage"]["tests_run"] == 2
        assert any("unmeasured rather than quiet" in w for w in payload["warnings"])


class TestClockSkew:
    def test_same_session_is_not_a_mismatch(self):
        row = summarize_board_row(
            select_board_candidates(status=_status(), limit=1)[0][0],
            _intel(), price_asof="2026-08-04T20:00:00+00:00",
        )
        assert row["clock_skew_days"] == 0
        assert row["clock_mismatch"] is False

    def test_stale_price_bars_against_a_live_chain_are_flagged(self):
        row = summarize_board_row(
            select_board_candidates(status=_status(), limit=1)[0][0],
            _intel(), price_asof="2026-07-29T20:00:00+00:00",
        )
        assert row["clock_skew_days"] == 6
        assert row["clock_mismatch"] is True
        assert "stale" in row["warnings"][0].lower()

    def test_boundary_is_inclusive_of_the_warn_threshold(self):
        assert clock_skew_days("2026-08-04", "2026-08-02") == CLOCK_SKEW_WARN_DAYS
        row = summarize_board_row(
            select_board_candidates(status=_status(), limit=1)[0][0],
            _intel(), price_asof="2026-08-02T20:00:00+00:00",
        )
        assert row["clock_mismatch"] is False

    def test_missing_timestamps_produce_no_false_alarm(self):
        assert clock_skew_days(None, "2026-08-04") is None
        assert clock_skew_days("2026-08-04", None) is None
        assert clock_skew_days("not-a-date", "2026-08-04") is None


class TestPayload:
    def _rows(self):
        candidate = select_board_candidates(status=_status(), limit=1)[0][0]
        return [
            summarize_board_row(candidate, _intel(), price_asof="2026-07-29T20:00:00+00:00"),
            summarize_board_row(candidate, None, error="fetch failed"),
        ]

    def test_coverage_reports_search_width_and_test_count(self):
        payload = board_payload(
            rows=self._rows(), candidates_considered=500, requested=25,
            depth="deep", scan_asof="2026-08-04T14:00:00+00:00",
            asof_utc="2026-08-04T18:00:00+00:00", limit=25, require_live_flow=False,
        )
        cov = payload["coverage"]
        assert cov["candidates_considered"] == 500
        assert cov["chain_fetched"] == 1
        assert cov["chain_failed"] == 1
        assert cov["tests_run"] == 2, "one scored name on two sides is two tests"

    def test_clock_mismatch_is_escalated_to_a_payload_warning(self):
        payload = board_payload(
            rows=self._rows(), candidates_considered=500, requested=25,
            depth="deep", scan_asof=None, asof_utc="2026-08-04T18:00:00+00:00",
            limit=25, require_live_flow=False,
        )
        assert payload["coverage"]["clock_mismatched"] == 1
        assert any("ingestion gap" in w for w in payload["warnings"])

    def test_payload_never_authorizes_a_decision(self):
        payload = board_payload(
            rows=[], candidates_considered=0, requested=0, depth="quick",
            scan_asof=None, asof_utc="2026-08-04T18:00:00+00:00",
            limit=25, require_live_flow=False,
        )
        assert payload["decision_authorized"] is False
        assert payload["score_kind"] == "ordinal_structure"
        assert any("not an edge" in c for c in payload["caveats"])
