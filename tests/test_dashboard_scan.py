from __future__ import annotations

import sys
import types

from edge.tools import render_dashboard as dashboard


def test_sector_flow_prefers_current_provider_and_preserves_freshness(monkeypatch):
    calls: list[str] = []
    module = types.ModuleType("tools.sector_money_flow")

    def fake_run_scan(*, source: str):
        calls.append(source)
        return {
            "ok": True,
            "asof": "2026-08-11T14:32:00Z",
            "asof_bar": "2026-08-11",
            "source": "yfinance",
            "money_in": [{"etf": "XLE"}],
            "money_out": [{"etf": "XLP"}],
            "sectors_ranked": [{"etf": "XLE", "flow_score": 0.024}],
            "watch_names": [{"symbol": "XOM", "etf": "XLE"}],
            "market_context": "Energy leadership",
        }

    module.run_scan = fake_run_scan  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools.sector_money_flow", module)

    payload = dashboard.fetch_sector_flow_signals()

    assert calls == ["yfinance"]
    assert payload["asof_bar"] == "2026-08-11"
    assert payload["source"] == "yfinance"
    assert payload["money_in"] == ["XLE"]
    assert payload["money_out"] == ["XLP"]


def test_scan_depth_is_bounded_and_deep_uses_complete_model_domain(monkeypatch):
    broad = [f"P{i:03d}" for i in range(175)]
    market = [f"X{i:03d}" for i in range(576)]
    modeled = [f"M{i:02d}" for i in range(59)]
    seen_limits: list[int] = []
    seen_sector_flow: list[object] = []

    monkeypatch.setattr(dashboard, "_load_broad_universe", lambda: broad)
    monkeypatch.setattr(dashboard, "load_market_symbol_catalog", lambda **_: market)
    monkeypatch.setattr(dashboard, "load_directional_model_universe", lambda: modeled)

    def fake_pead(*, symbols, diagnostics, **_):
        diagnostics.update({"attempted_symbols": len(symbols), "evaluated_symbols": len(symbols)})
        return [{"symbol": symbol} for symbol in symbols[:8]]

    def fake_directional(*, candidate_limit, diagnostics, sector_flow=None, **_):
        seen_limits.append(candidate_limit)
        seen_sector_flow.append(sector_flow)
        diagnostics.update({
            "attempted_symbols": candidate_limit,
            "failed_symbols": 0,
            "warning_count": 0,
        })
        return [{"symbol": symbol} for symbol in modeled[:candidate_limit]]

    monkeypatch.setattr(dashboard, "generate_pead_candidates", fake_pead)
    monkeypatch.setattr(dashboard, "fetch_internal_directional_signals", fake_directional)
    monkeypatch.setattr(
        dashboard,
        "fetch_sector_flow_signals",
        lambda: {"watch_names": [{"symbol": "M10", "etf": "XLK"}], "money_in": ["XLK"]},
    )
    monkeypatch.setattr(dashboard, "get_all_gcp_resources", lambda: {})
    monkeypatch.setattr(dashboard, "load_dynamic_leaderboard", lambda: [])
    monkeypatch.setattr(
        dashboard,
        "build_market_activity_scan",
        lambda **kwargs: {
            "rows": [],
            "qlib_scan": {
                "quality": "ok" if kwargs["depth"] == "deep" else "skipped",
                "score_kind": "ordinal_qlib_xs",
                "source": "qlib_alpha_factor_probe_v1",
                "asof": "2026-07-31" if kwargs["depth"] == "deep" else None,
                "coverage": {
                    "attempted": len(kwargs["symbols"]) if kwargs["depth"] == "deep" else 0,
                    "scored": 400 if kwargs["depth"] == "deep" else 0,
                    "failed": 0,
                },
                "warnings": [],
                "decision_authorized": False,
                "top_rows": [],
            },
            "coverage": {
                "market_universe": len(kwargs["symbols"]),
                "local_scanned": len(kwargs["symbols"]) if kwargs["depth"] == "deep" else 175,
                "local_flagged": 12,
                "live_requested": 100 if kwargs["depth"] == "deep" else 0,
                "live_completed": 96 if kwargs["depth"] == "deep" else 0,
                "live_with_activity": 7 if kwargs["depth"] == "deep" else 0,
                "qlib_attempted": len(kwargs["symbols"]) if kwargs["depth"] == "deep" else 0,
                "qlib_scored": 400 if kwargs["depth"] == "deep" else 0,
                "qlib_failed": 0,
                "qlib_priority_routed": 40 if kwargs["depth"] == "deep" else 0,
            },
        },
    )

    quick = dashboard.get_dashboard_data(scan_depth="unexpected")
    deep = dashboard.get_dashboard_data(scan_depth="deep")

    assert seen_limits == [25, 59]
    # Fast pass receives sector flow so it can prioritize top-sector names.
    assert seen_sector_flow[0] is not None
    assert seen_sector_flow[1] is None
    assert quick["scan_summary"]["depth"] == "quick"
    assert quick["scan_summary"]["pead_qualified_symbols"] == 8
    assert quick["scan_summary"]["pead_attempted_symbols"] == 175
    assert quick["scan_summary"]["directional_scored_symbols"] == 25
    assert deep["scan_summary"]["depth"] == "deep"
    assert deep["scan_summary"]["pead_attempted_symbols"] == 576
    assert deep["scan_summary"]["directional_scored_symbols"] == 59
    assert deep["scan_summary"]["directional_model_universe_symbols"] == 59
    assert deep["scan_summary"]["activity_local_scanned_symbols"] == 576
    assert deep["scan_summary"]["activity_live_requested_symbols"] == 100
    assert deep["scan_summary"]["activity_live_completed_symbols"] == 96
    assert deep["scan_summary"]["qlib_score_kind"] == "ordinal_qlib_xs"
    assert deep["scan_summary"]["qlib_scored_symbols"] == 400
    assert deep["scan_summary"]["qlib_priority_routed_symbols"] == 40
    assert deep["scan_summary"]["qlib_quality"] == "ok"
    assert deep["scan_summary"]["directional_scored_symbols"] <= deep["scan_summary"]["directional_model_universe_symbols"]
    assert quick["scan_summary"]["qlib_scored_symbols"] == 0


def test_priority_directional_symbols_prefers_top_sector_watch_names():
    modeled = [f"M{i:02d}" for i in range(10)]
    flow = {
        "watch_names": [
            {"symbol": "M07", "etf": "XLK"},
            {"symbol": "M03", "etf": "XLK"},
            {"symbol": "OUTSIDE", "etf": "XLK"},
        ],
        "money_in": ["M01"],
        "sectors_ranked": [
            {"etf": "M05", "flow_score": 0.04, "focus_names": ["M09"]},
            {"etf": "M02", "flow_score": -0.03, "focus_names": ["M00"]},
        ],
    }
    picked = dashboard._priority_directional_symbols(modeled, flow, limit=5)
    assert picked[0] == "M07"
    assert picked[1] == "M03"
    assert "OUTSIDE" not in picked
    assert len(picked) == 5
    assert set(picked) <= set(modeled)


def test_pead_directional_reconciliation_only_compares_the_same_symbol():
    payload = dashboard.reconcile_pead_directional_signals(
        [
            {"symbol": "AGREE", "side": "long", "evidence": {"pead_score": 1.4}},
            {"symbol": "CLASH", "side": "short", "evidence": {"pead_score": -1.2}},
            {"symbol": "GAP_ONLY", "side": "long", "evidence": {"pead_score": 0.9}},
        ],
        [
            {"symbol": "AGREE", "side": "LONG", "probability": 0.61, "state": "WATCH", "horizon": "5 Days"},
            {"symbol": "CLASH", "side": "LONG", "probability": 0.58, "state": "WATCH", "horizon": "5 Days"},
            {"symbol": "MODEL_ONLY", "side": "SHORT", "probability": 0.57, "state": "WATCH", "horizon": "5 Days"},
        ],
    )

    assert payload["counts"] == {
        "pead_flags": 3,
        "directional_forecasts": 3,
        "overlap": 2,
        "agreements": 1,
        "conflicts": 1,
        "pead_only": 1,
        "directional_only": 1,
    }
    assert [row["symbol"] for row in payload["rows"]] == ["CLASH", "AGREE"]
    assert payload["rows"][0]["relation"] == "conflict"
    assert "non-overlap is not disagreement" in payload["decision_rule"]


def test_analyze_symbol_attaches_shared_qlib_context_or_explicit_missing(monkeypatch, tmp_path):
    """Market ad-hoc path reuses the same scorer provenance as deep scan."""
    import numpy as np
    import pandas as pd
    from edge.daily_plays.qlib_scan_score import SCORE_KIND, score_cross_section_asof

    dates = pd.bdate_range("2024-01-02", periods=280)
    close = np.linspace(100, 120, len(dates))
    frame = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(len(dates), 1e6),
        },
        index=dates,
    )
    wide = tmp_path / "1d_wide"
    wide.mkdir()
    frame.to_parquet(wide / "AAA.parquet")

    monkeypatch.setattr(
        dashboard,
        "_market_data_dirs",
        lambda: (wide, tmp_path / "1d"),
    )
    monkeypatch.setattr(
        dashboard,
        "load_market_symbol_catalog",
        lambda **_: ["AAA", "BBB"],
    )

    # Second symbol for a real cross-section so ranks are not trivially 1-of-1.
    frame2 = frame.copy()
    frame2["Close"] = close[::-1]
    frame2.to_parquet(wide / "BBB.parquet")

    panel = score_cross_section_asof(symbols=["AAA", "BBB"], data_dirs=(wide,))
    payload = dashboard.analyze_symbol_adhoc("AAA", qlib_panel=panel)
    assert payload["qlib_quality"] == "ok"
    assert payload["qlib_score_kind"] == SCORE_KIND
    assert payload["qlib_source"] == panel["source"]
    assert str(payload["qlib_source"]).startswith("qlib_")
    assert payload["qlib_rank"] == panel["by_symbol"]["AAA"]["qlib_rank"]
    assert payload["qlib_asof"] == panel["by_symbol"]["AAA"]["asof"]
    assert payload["calibrated_probability"] is None

    missing = dashboard.analyze_symbol_adhoc("NOSUCH", qlib_panel=panel)
    assert "error" in missing
    assert missing["qlib"]["quality"] == "missing"
    assert missing["qlib"]["qlib_rank"] is None
    assert missing["qlib"]["qlib_score"] is None


def test_directional_dashboard_never_converts_ordinal_score_to_probability(monkeypatch):
    modeled = ["AAA"]
    captured: dict[str, object] = {}

    class FakeAdapter:
        last_warnings: list[str] = []

        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def __call__(self, *, symbols, **_):
            captured["symbols"] = symbols
            return [{
                "symbol": "AAA",
                "side": "long",
                "setup_ok": True,
                "model": {
                    "id": "ordinal-only",
                    "raw_score": 4.2,
                    "probability": None,
                    "confidence_kind": "ordinal_score",
                    "horizon_days": 5,
                    "state": "WATCH",
                    "reasons": ["score_not_calibrated"],
                },
            }]

    monkeypatch.setattr(dashboard, "load_directional_model_universe", lambda: modeled)
    monkeypatch.setattr(dashboard, "ChainFreeInternalModelsAdapter", FakeAdapter)

    diagnostics: dict = {}
    rows = dashboard.fetch_internal_directional_signals(candidate_limit=25, diagnostics=diagnostics)

    assert captured["symbols"] == ["AAA"]
    assert rows[0]["probability"] is None
    assert rows[0]["momentum"] == 4.2
    assert rows[0]["state"] == "WATCH"
    assert diagnostics["scored_symbols"] == 1
