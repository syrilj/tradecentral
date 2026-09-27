from datetime import datetime, timezone

from edge.daily_plays.adapters.sector_flow import select_sector_targets
from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import load_config
from edge.daily_plays.pipeline import PipelineAdapters, run_pipeline


ASOF = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


def _report():
    return {
        "ok": True,
        "asof": "2026-07-30T18:00:00Z",
        "asof_bar": "2026-07-30",
        "source": "synthetic",
        "rotation": {"kind": "internal", "confidence": 0.68, "is_definitive": True},
        "money_in": [{
            "etf": "SOXX", "name": "Semis", "flow_direction": "in",
            "flow_score": 0.03, "rs_1d": 0.02, "rs_5d": 0.04,
            "definitive": True, "definitive_score": 0.8,
            "focus_names": ["NVDA", "MU", "AMD"],
        }],
        "money_out": [{
            "etf": "XLE", "name": "Energy", "flow_direction": "out",
            "flow_score": -0.02, "rs_1d": -0.01, "rs_5d": -0.03,
            "definitive": True, "definitive_score": 0.75,
            "focus_names": ["XOM", "CVX"],
        }],
        "sectors_ranked": [{"etf": "SOXX"}, {"etf": "XLE"}],
        "missing_themes": [],
    }


def test_sector_targets_put_promoted_symbols_first_and_balance_sleeves():
    result = select_sector_targets(
        _report(),
        universe_symbols=["SPY", "MU", "NVDA", "AMD", "XOM", "CVX"],
        promotion_symbols={"SPY", "MU"},
        limit=7,
    )
    assert result["target_symbols"][:2] == ["MU", "SPY"]
    assert result["model_covered_symbols"] == ["MU", "SPY"]
    assert {"NVDA", "AMD", "XOM", "CVX"}.issubset(result["target_symbols"])
    assert {"SOXX", "XLE"}.issubset(result["routed_but_unsupported_symbols"])
    assert result["symbol_context"]["MU"]["sector_etf"] == "SOXX"
    assert result["symbol_context"]["XOM"]["flow_direction"] == "out"
    assert result["market_map"]["rotation"]["kind"] == "internal"


def test_pipeline_passes_discovery_targets_to_model_scan_without_promoting_them():
    observed = {}

    def models(**kwargs):
        observed["symbols"] = kwargs["symbols"]
        observed["context"] = kwargs["symbol_context"]
        return []

    discovery = select_sector_targets(
        _report(),
        universe_symbols=["SPY", "MU", "NVDA", "XOM"],
        promotion_symbols={"SPY", "MU"},
        limit=6,
    )
    result = run_pipeline(
        context=RunContext.create(asof_utc=ASOF),
        account=1000,
        config=load_config(),
        adapters=PipelineAdapters(
            internal_models=models,
            discovery=lambda **_: discovery,
        ),
        persist=False,
    )
    assert observed["symbols"] == discovery["target_symbols"]
    assert observed["context"]["MU"]["sector_etf"] == "SOXX"
    assert result["market_map"]["rotation"]["kind"] == "internal"
    assert result["scan_scope"]["targeted_count"] == len(discovery["target_symbols"])
    assert result["scan_scope"]["model_covered_count"] == 2
    assert result["plays"] == []


def test_unsigned_live_activity_reorders_heatmap_targets_before_model_scan():
    observed = {}
    discovery = select_sector_targets(
        _report(),
        universe_symbols=["SPY", "MU", "NVDA", "XOM"],
        promotion_symbols={"SPY", "MU"},
        limit=6,
    )

    def models(**kwargs):
        observed["symbols"] = kwargs["symbols"]
        return []

    board = {
        "schema_version": "daily-plays-flow-activity-v1",
        "requested_symbols": discovery["target_symbols"],
        "rows": [{
            "symbol": "XOM", "direction": "neutral",
            "evidence": {"premium": 500_000, "alert_count": 2},
            "decision_authorized": False,
        }],
        "coverage": {
            "requested": len(discovery["target_symbols"]),
            "completed": len(discovery["target_symbols"]),
            "with_activity": 1,
            "direction_signed": 0,
        },
        "warnings": [],
        "routing_order": ["XOM", *[s for s in discovery["target_symbols"] if s != "XOM"]],
    }
    result = run_pipeline(
        context=RunContext.create(asof_utc=ASOF),
        account=1000,
        config=load_config(),
        adapters=PipelineAdapters(
            internal_models=models,
            discovery=lambda **_: discovery,
            flow_activity=lambda **_: board,
        ),
        persist=False,
    )
    assert observed["symbols"][0] == "XOM"
    assert result["flow_activity"]["rows"][0]["direction"] == "neutral"
    assert result["scan_scope"]["flow_activity_observed"] == 1
    assert result["plays"] == []
