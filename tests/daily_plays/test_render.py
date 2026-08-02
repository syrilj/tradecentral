from edge.daily_plays.render import render_report


def test_default_render_never_lists_abstain_rows_as_plays():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "degraded",
        "plays": [],
        "watchlist": [],
        "rejected_count": 10,
        "abstention_reasons": ["lse_credential_missing"],
    })
    assert "No live-validated actionable plays today." in output
    assert "Audit only: 10 rejected candidate(s)" in output
    assert "AAPL" not in output
    assert "ABSTAIN" not in output


def test_render_lists_only_enter_tickets():
    output = render_report({
        "status": "COMPLETE",
        "market_session": "regular",
        "mode": "live",
        "plays": [{
            "rank": 1,
            "symbol": "NVDA",
            "state": "ENTER",
            "strategy": "long_call",
            "confidence": {"calibrated_probability": 0.71},
            "risk": {"max_loss_dollars": 4.0},
            "legs": [{"side": "buy", "occ_symbol": "NVDA260918C00180000", "ask": 0.04}],
        }],
    })
    assert "Validated actionable plays" in output
    assert "NVDA260918C00180000" in output
    assert "limit ≤ $0.04" in output


def test_render_shows_compact_market_map_and_scan_funnel():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "live",
        "plays": [],
        "market_map": {
            "rotation": {"kind": "semis_to_tech"},
            "money_in": [{"etf": "IGV"}, {"etf": "XLK"}],
            "money_out": [{"etf": "SOXX"}],
        },
        "scan_scope": {
            "sector_books_scored": 13,
            "targeted_count": 25,
            "model_covered_count": 7,
        },
    })
    assert "Market map: SEMIS TO TECH | money in IGV, XLK | money out SOXX" in output
    assert "Scan funnel: 13 sector/theme books → 25 flow targets → 7 model-covered symbols" in output


def test_render_keeps_live_options_activity_separate_and_unsigned():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "live",
        "plays": [],
        "flow_activity": {
            "coverage": {"requested": 25, "with_activity": 2},
            "rows": [
                {"symbol": "QQQ", "evidence": {"premium": 724_572}},
                {"symbol": "NVDA", "evidence": {"premium": 1_250_000}},
            ],
        },
    })
    assert "Options activity route: 2/25 names with prints" in output
    assert "QQQ $725K" in output
    assert "NVDA $1.2M" in output
    assert "unsigned tape, routing only" in output


def test_render_prioritizes_model_reason_over_optional_research_warning():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "degraded",
        "plays": [],
        "rejected_count": 2,
        "abstention_reasons": [
            "no_directional_model_setup",
            "model_probability_not_calibrated",
            "kronos_symbol_not_in_same_session_artifact",
        ],
    })
    why = next(line for line in output.splitlines() if line.startswith("Why:"))
    assert why.startswith("Why: the promoted models produced no directional setup")
    assert "no entry-eligible fixed-horizon probability is available" in why


def test_render_uses_actual_funnel_and_excludes_advisory_warnings_from_why():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "live",
        "plays": [],
        "decision_blockers": ["no_directional_model_setup"],
        "advisory_evidence_warnings": ["kronos_same_session_artifact_missing"],
        "scan_scope": {
            "sector_books": 14,
            "routed_targets": 25,
            "model_domain_supported": 7,
            "successfully_scanned_candidates": 7,
            "directional_setups": 0,
            "chain_requests": 0,
            "chain_snapshots": 0,
        },
    })
    assert "Scan funnel: 14 sector books → 25 routed targets → 7 model-domain → 7 scanned → 0 directional → 0/0 chains" in output
    assert "Why: the promoted models produced no directional setup." in output
    assert "Kronos" not in output


def test_render_research_board_is_explicitly_sealed_and_never_a_play():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "live",
        "plays": [],
        "research_board": [
            {"symbol": "AAA", "side": "long", "horizon_days": 10, "directional_confidence": 0.71},
            {"symbol": "AAA", "side": "short", "horizon_days": 5, "directional_confidence": 0.82},
            {"symbol": "BBB", "side": "short", "horizon_days": 20, "directional_confidence": 0.63},
        ],
    })
    assert "Research board (sealed holdout — not plays):" in output
    assert "AAA long H10 dev-calibrated 71.0%" in output
    assert "BBB short H20 dev-calibrated 63.0%" in output
    assert output.count("AAA ") == 1
    assert "not live-validated and cannot be acted on until the terminal holdout clears" in output


def test_render_explains_failed_broad_market_challenger_as_advisory():
    output = render_report({
        "status": "NO_PLAY",
        "market_session": "regular",
        "mode": "live",
        "plays": [],
        "decision_blockers": ["no_directional_model_setup"],
        "advisory_evidence_warnings": [
            "directional_research_artifact_unavailable:"
            "ValueError:daily_directional_artifact_failed_development"
        ],
    })
    assert "Why: the promoted models produced no directional setup." in output
    assert "Broad-market research scan: latest challenger failed development validation." in output
