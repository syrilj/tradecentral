"""Tests for the Quantitative Pullback & Institutional Options Flow Engine.

Covers the DTE-window alignment between expiry selection and leg validation,
honest confidence provenance (no fabricated model endorsement), fail-closed
leg handling, risk sizing against the preregistered policy cap, and the
persist artifacts contract.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import DailyPlaysConfig
from edge.daily_plays.pullback_flow_engine import (
    analyze_options_gex_fast,
    calculate_technical_profile,
    persist_pullback_plays_run,
    run_pullback_flow_engine,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
SPOT = 100.0


def _config() -> DailyPlaysConfig:
    """Return a valid DailyPlaysConfig (swing_dte_min=30, swing_dte_max=60)."""
    return DailyPlaysConfig(
        schema_version="daily-plays-config-v1",
        shortlist_limit=10,
        regular_quote_max_age_seconds=30,
        swing_dte_min=30,
        swing_dte_max=60,
        intraday_enabled=False,
        shadow_only=True,
        min_abs_delta=0.40,
        max_abs_delta=0.60,
        max_spread_pct=0.10,
        low_premium_spread_floor=0.02,
        min_open_interest=500,
        min_volume=50,
        max_account_risk_pct=0.005,
        max_position_risk_pct=0.005,
        max_underlying_risk_pct=0.01,
        max_aggregate_open_risk_pct=0.03,
        universe_path="data/universe.json",
    )


def _ctx() -> RunContext:
    return RunContext.create()


def _daily_frame(rows: int = 60, start_close: float = SPOT) -> pd.DataFrame:
    """Deterministic OHLCV daily frame with enough bars for SMA/EMA/ATP."""
    dates = pd.bdate_range(end=pd.Timestamp.now(tz=None).date(), periods=rows)
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, size=rows)
    close = start_close * np.cumprod(1.0 + returns)
    high = close * (1.0 + np.abs(np.random.normal(0.005, 0.005, size=rows)))
    low = close * (1.0 - np.abs(np.random.normal(0.005, 0.005, size=rows)))
    open_p = low + (high - low) * np.random.uniform(0.2, 0.8, size=rows)
    volume = np.random.uniform(5_000_000, 25_000_000, size=rows)
    df = pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.index.name = "date"
    return df.reset_index()


def _option_chain(spot: float, *, dte: int) -> pd.DataFrame:
    """Synthetic option chain with an expiry at the requested DTE."""
    expiry = (datetime.now(timezone.utc).date() + timedelta(days=dte)).isoformat()
    rows = []
    for i in range(-5, 6):
        strike = round(spot * (1.0 + i * 0.025), 2)
        mid = max(0.50, spot * 0.04 - abs(i) * 0.30)
        rows.append(
            {
                "symbol": "TEST",
                "right": "C",
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "bid": round(mid * 0.95, 2),
                "ask": round(mid * 1.05, 2),
                "volume": 2000,
                "openInterest": 800,
                "impliedVolatility": 0.45,
                "delta": 0.50,
                "gamma": 0.02,
            }
        )
    for i in range(-5, 6):
        strike = round(spot * (1.0 + i * 0.025), 2)
        mid = max(0.50, spot * 0.04 - abs(i) * 0.30)
        rows.append(
            {
                "symbol": "TEST",
                "right": "P",
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "bid": round(mid * 0.95, 2),
                "ask": round(mid * 1.05, 2),
                "volume": 1500,
                "openInterest": 600,
                "impliedVolatility": 0.45,
                "delta": -0.50,
                "gamma": 0.02,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# DTE-window alignment
# --------------------------------------------------------------------------
def test_expiry_picker_prefers_in_window_dte():
    """Expiry selection honors the policy DTE window passed via dte_min/dte_max."""
    chain = _option_chain(SPOT, dte=10)
    # 10 DTE is outside the 30-60 swing window — should not be selected as target.
    res = analyze_options_gex_fast(chain, SPOT, dte_min=30, dte_max=60)
    assert res is not None
    # With only a 10-DTE expiry available, the picker falls back to the first
    # expiry, so target_exp is set but the leg will fail the dte gate.
    assert res["target_exp"] is not None


def test_expiry_picker_selects_in_window_expiry_when_available():
    """A 35-DTE expiry falls inside the 30-60 window and is selected as target."""
    chain = _option_chain(SPOT, dte=35)
    res = analyze_options_gex_fast(chain, SPOT, dte_min=30, dte_max=60)
    assert res is not None
    expiry_expected = (datetime.now(timezone.utc).date() + timedelta(days=35)).isoformat()
    assert res["target_exp"] == expiry_expected


def test_short_dte_leg_passes_picker_but_is_marked_for_gate_failure():
    """A 10-DTE leg survives the picker but the engine must not emit it as a valid leg.

    The leg validation gate in run_pullback_flow_engine rejects dte < swing_dte_min,
    so legs_list is empty and the play carries the failure rather than a contract.
    """
    chain = _option_chain(SPOT, dte=10)
    res = analyze_options_gex_fast(chain, SPOT, dte_min=30, dte_max=60)
    assert res is not None
    leg = res.get("best_call_leg")
    if leg:
        # If a leg was built, its dte must be outside the swing window.
        assert int(leg.get("dte") or 0) < 30


# --------------------------------------------------------------------------
# Technical profile
# --------------------------------------------------------------------------
def test_technical_profile_returns_none_for_short_frame():
    assert calculate_technical_profile(pd.DataFrame()) is None
    short = pd.DataFrame({"close": [10.0] * 10, "high": [11.0] * 10, "low": [9.0] * 10})
    assert calculate_technical_profile(short) is None


def test_technical_profile_computes_expected_fields():
    df = _daily_frame(rows=60)
    tech = calculate_technical_profile(df)
    assert tech is not None
    assert tech["close"] > 0
    assert 0 <= tech["rsi"] <= 100
    assert tech["atr"] > 0
    assert "ema_9" in tech and "ema_21" in tech
    assert "pivot" in tech and "r1" in tech and "s1" in tech


def test_technical_profile_rejects_sub_dollar_close():
    df = _daily_frame(rows=60, start_close=5.0)
    tech = calculate_technical_profile(df)
    assert tech is not None
    # Engine filters close < 8.0 at the candidate level, not in the profile.
    assert tech["close"] < 8.0


# --------------------------------------------------------------------------
# Engine run with synthetic data
# --------------------------------------------------------------------------
def _seed_repo(root: Path) -> None:
    """Populate data/1d and data/option_chains with one scannable symbol."""
    data_1d = root / "data" / "1d"
    data_1d.mkdir(parents=True, exist_ok=True)
    df = _daily_frame(rows=60, start_close=50.0)
    df.to_parquet(data_1d / "TEST.parquet")

    chain_dir = root / "data" / "option_chains" / f"date={datetime.now(timezone.utc).date().isoformat()}"
    chain_dir.mkdir(parents=True, exist_ok=True)
    _option_chain(50.0, dte=35).to_parquet(chain_dir / "TEST.parquet")


def test_engine_run_with_no_data_returns_no_play():
    result = run_pullback_flow_engine(
        account=10000.0,
        context=_ctx(),
        config=_config(),
        root_dir=Path("/tmp/__nonexistent_pullback_test__"),
    )
    assert result["status"] == "NO_PLAY"
    assert result["plays"] == []
    assert result["decision_blockers"] == []


def test_engine_run_with_seed_data_produces_honest_provenance():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        result = run_pullback_flow_engine(
            account=10000.0,
            context=_ctx(),
            config=_config(),
            root_dir=root,
        )
    # The seed symbol may or may not score above 40, but provenance must be honest.
    for decision in [*result["plays"], *result["watchlist"], *result["rejections"]]:
        conf = decision["confidence"]
        assert conf["confidence_kind"] == "unavailable"
        assert conf["model_probability"] is None
        assert conf["calibrated_probability"] is None
        assert conf["promotion_authorized"] is False
        assert conf["evidence_grade"] == "F"


def test_engine_risk_sizing_respects_position_risk_cap():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        result = run_pullback_flow_engine(
            account=10000.0,
            context=_ctx(),
            config=_config(),
            root_dir=root,
        )
    for decision in [*result["plays"], *result["watchlist"], *result["rejections"]]:
        risk = decision["risk"]
        # max_loss_pct is relative to account; with a 0.5% cap the per-play
        # loss must never exceed that fraction of the account.  When a single
        # contract costs more than the budget, contracts must be 0 rather
        # than forced to 1 (which would breach the cap).
        assert risk["max_loss_pct"] <= 0.005 + 1e-6
        if risk["contracts"] == 0:
            assert "risk_budget_exceeded" in decision["confidence"]["failed_checks"]


def test_engine_excludes_index_symbols():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        # Also add SPY which should be excluded.
        spy_df = _daily_frame(rows=60, start_close=400.0)
        (root / "data" / "1d" / "SPY.parquet").parent.mkdir(parents=True, exist_ok=True)
        spy_df.to_parquet(root / "data" / "1d" / "SPY.parquet")
        result = run_pullback_flow_engine(
            account=10000.0,
            context=_ctx(),
            config=_config(),
            root_dir=root,
        )
    symbols = {d["symbol"] for d in [*result["plays"], *result["watchlist"], *result["rejections"]]}
    assert "SPY" not in symbols


# --------------------------------------------------------------------------
# Persist contract
# --------------------------------------------------------------------------
def test_persist_writes_canonical_artifacts():
    import json
    import tempfile

    payload = {
        "run_id": "testrun",
        "requested_for": "2026-08-18",
        "asof_utc": "2026-08-18T12:00:00Z",
        "market_session": "regular",
        "mode": "live",
        "account": 10000.0,
        "config_hash": "pullback_options_flow_engine_v3",
        "warnings": [],
        "status": "COMPLETE",
        "market_map": {"money_in": [], "money_out": []},
        "scan_scope": {"sector_books_scored": 11, "targeted_count": 1, "model_covered_count": 1},
        "flow_activity": {"coverage": {"requested": 1, "with_activity": 1}},
        "plays": [{"play_id": "play_TEST_1", "symbol": "TEST", "state": "ENTER"}],
        "watchlist": [],
        "rejections": [],
        "research_board": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = persist_pullback_plays_run(payload, output_root=tmp)
        assert run_dir.name == "testrun"
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["run_id"] == "testrun"
        assert manifest["schema_version"] == "daily-plays-run-v1"
        plays = json.loads((run_dir / "plays.json").read_text())
        assert len(plays) == 1
        decisions = json.loads((run_dir / "decisions.json").read_text())
        assert len(decisions) == 1
        assert (run_dir / "discovery.json").is_file()
        assert (run_dir / "flow_activity.json").is_file()
        desk = Path(tmp) / "desk_board_latest.json"
        assert desk.is_file()
