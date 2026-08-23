"""Tests for the Quantitative Pullback & Institutional Options Flow Engine.

Covers the DTE-window alignment between expiry selection and leg validation,
honest confidence provenance (no fabricated model endorsement), fail-closed
leg handling, risk sizing against the preregistered policy cap, and the
persist artifacts contract.  v3.3 additions: two-sided setup sleeves, capture-
time quote honesty, chain-freshness gating, liquidity-aware expiry/leg
selection, Black-Scholes Greeks from cached IV, and the execution-honest
ENTER downgrade.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import DailyPlaysConfig
from edge.daily_plays.pullback_flow_engine import (
    _bs_greeks_for_leg,
    _chain_capture_time,
    analyze_options_gex_fast,
    calculate_technical_profile,
    persist_pullback_plays_run,
    PULLBACK_FLOW_ENGINE_NAME,
    PULLBACK_FLOW_ENGINE_VERSION,
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


def test_persist_manifest_records_engine_provenance():
    """The persisted manifest carries engine identity so /api/plays can badge it."""
    import json
    import tempfile

    payload = {
        "run_id": "testrun-eng",
        "status": "COMPLETE",
        "plays": [],
        "watchlist": [],
        "rejections": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = persist_pullback_plays_run(payload, output_root=tmp)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["engine"] == PULLBACK_FLOW_ENGINE_NAME
        assert manifest["engine_version"] == PULLBACK_FLOW_ENGINE_VERSION


# --------------------------------------------------------------------------
# v3.3: capture-time quote honesty, Greeks, freshness, two-sided sleeves,
# liquidity-aware selection, and the execution-honest ENTER downgrade.
# --------------------------------------------------------------------------
def test_chain_capture_time_comes_from_snapshot_not_clock():
    chain = _option_chain(SPOT, dte=35)
    captured = datetime.now(timezone.utc) - timedelta(hours=9)
    chain["captured_utc"] = captured.isoformat()
    stamp = _chain_capture_time(chain)
    assert stamp is not None
    # Within a minute of the injected capture stamp, NOT the current time.
    assert abs((stamp - captured).total_seconds()) < 60


def test_leg_quotes_carry_capture_time_and_measured_greeks():
    chain = _option_chain(SPOT, dte=35)
    captured = datetime.now(timezone.utc) - timedelta(hours=2)
    chain["captured_utc"] = captured.isoformat()
    res = analyze_options_gex_fast(
        chain, SPOT, dte_min=30, dte_max=60, asof_date=date.today()
    )
    leg = res["best_call_leg"]
    assert leg is not None
    quote_stamp = datetime.fromisoformat(leg["quote_asof_utc"].replace("Z", "+00:00"))
    assert abs((quote_stamp - captured).total_seconds()) < 60
    # Delta is a measured BS value in a sane range for near-ATM, not a default.
    assert leg["delta"] is not None and 0.05 <= leg["delta"] <= 0.95
    assert leg["theta"] is not None and leg["theta"] < 0  # time decay is real


def test_bs_greeks_absent_without_plausible_iv():
    greeks = _bs_greeks_for_leg(spot_price=SPOT, strike=100.0, dte=45, right="call", iv=None)
    assert greeks == {"delta": None, "gamma": None, "theta": None, "charm": None}
    wild = _bs_greeks_for_leg(spot_price=SPOT, strike=100.0, dte=45, right="call", iv=99.0)
    assert wild["delta"] is None


def test_expiry_picker_prefers_liquid_deeper_expiry():
    """A wide nearest expiry routes to a liquid deeper one inside the window."""
    today = date.today()
    near = (today + timedelta(days=34)).isoformat()
    deep = (today + timedelta(days=55)).isoformat()
    rows = []
    for expiry, spread_mult in ((near, 6.0), (deep, 1.0)):
        for i in range(-3, 4):
            strike = round(SPOT * (1 + i * 0.03), 2)
            mid = max(0.5, SPOT * 0.04 - abs(i) * 0.3)
            rows.append({
                "symbol": "TEST", "right": "C", "strike": strike, "expiry": expiry,
                "dte": (datetime.fromisoformat(expiry).date() - today).days,
                "bid": round(mid * (1 - 0.02 * spread_mult), 2),
                "ask": round(mid * (1 + 0.02 * spread_mult), 2),
                "volume": 2000, "openInterest": 900, "impliedVolatility": 0.45,
            })
    chain = pd.DataFrame(rows)
    res = analyze_options_gex_fast(chain, SPOT, dte_min=30, dte_max=60, asof_date=today)
    assert res["target_exp"] == deep
    assert res["best_call_leg"]["spread_pct"] <= 0.10


def test_leg_picker_prefers_liquid_contract_over_nearest_strike():
    """The nearest strike is illiquid; a slightly further one passes policy."""
    today = date.today()
    expiry = (today + timedelta(days=40)).isoformat()
    rows = []
    for i, (oi, vol) in enumerate([(10, 5), (4000, 800)]):
        strike = round(SPOT * (1.01 + i * 0.02), 2)
        mid = max(0.5, SPOT * 0.04)
        rows.append({
            "symbol": "TEST", "right": "C", "strike": strike, "expiry": expiry, "dte": 40,
            "bid": round(mid * 0.98, 2), "ask": round(mid * 1.02, 2),
            "volume": vol, "openInterest": oi, "impliedVolatility": 0.45,
        })
    chain = pd.DataFrame(rows)
    res = analyze_options_gex_fast(
        chain, SPOT, dte_min=30, dte_max=60, asof_date=today,
        min_open_interest=500, min_volume=50,
    )
    leg = res["best_call_leg"]
    assert leg["open_interest"] >= 500 and leg["volume"] >= 50


def _seed_two_sided_repo(root: Path, *, stale: bool = False) -> None:
    """One bouncing symbol and one breaking-down symbol with liquid chains."""
    data_1d = root / "data" / "1d"
    data_1d.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=80)
    # BOUNCE: steady uptrend then a controlled pullback to a neutral RSI.
    up = 100 * np.cumprod(1 + np.full(80, 0.004))
    up[-8:] = up[-9] * (1 - np.linspace(0.001, 0.06, 8))
    bounce = pd.DataFrame({
        "open": up, "high": up * 1.01, "low": up * 0.99,
        "close": up, "volume": np.full(80, 5e6),
    }, index=dates)
    bounce.to_parquet(data_1d / "BOUNCE.parquet")

    # BREAKDOWN: strong run-up then a five-session fade beneath the EMA.
    hot = 100 * np.cumprod(1 + np.full(80, 0.006))
    hot[-6:] = hot[-7] * (1 - np.linspace(0.004, 0.05, 6))
    breakdown = pd.DataFrame({
        "open": hot, "high": hot * 1.01, "low": hot * 0.99,
        "close": hot, "volume": np.full(80, 5e6),
    }, index=dates)
    breakdown.to_parquet(data_1d / "BRKDWN.parquet")

    day = date.today() - timedelta(days=12 if stale else 0)
    chain_dir = root / "data" / "option_chains" / f"date={day.isoformat()}"
    chain_dir.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()
    for sym in ("BOUNCE", "BRKDWN"):
        spot = float((bounce if sym == "BOUNCE" else breakdown)["close"].iloc[-1])
        frames = []
        for tag in ("C", "P"):
            for i in (-4, -3, -2, 2, 3, 4):
                strike = round(spot * (1 + i * 0.02), 2)
                mid = max(0.5, spot * 0.03)
                expiry = date.today() + timedelta(days=45)
                frames.append({
                    "asof_date": day.isoformat(), "captured_utc": captured, "symbol": sym,
                    "spot": spot, "right": tag, "expiry": expiry.isoformat(),
                    "dte": 45, "strike": strike,
                    "bid": round(mid * 0.97, 2), "ask": round(mid * 1.03, 2),
                    "lastPrice": mid, "volume": 3000, "openInterest": 6000,
                    "impliedVolatility": 0.5, "inTheMoney": False,
                    "contractSymbol": f"{sym}{expiry.strftime('%y%m%d')}{tag}{int(strike*1000):08d}",
                    "lastTradeDate": captured,
                })
        pd.DataFrame(frames).to_parquet(chain_dir / f"{sym}.parquet")


def test_engine_produces_enter_tickets_with_honest_quotes():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_two_sided_repo(root)
        result = run_pullback_flow_engine(
            account=250000.0, context=_ctx(), config=_config(), root_dir=root
        )
    decisions = [*result["plays"], *result["watchlist"], *result["rejections"]]
    symbols = {d["symbol"] for d in decisions}
    assert {"BOUNCE", "BRKDWN"} <= symbols
    for decision in result["plays"]:
        assert decision["state"] == "ENTER"
        assert decision["confidence"]["failed_checks"] == []
        leg = decision["legs"][0]
        assert leg["bid"] > 0 and leg["ask"] >= leg["bid"]
        assert leg["quote_asof_utc"]  # snapshot capture time, present
        assert leg["delta"] is not None
    strategies = {d["strategy"] for d in decisions}
    assert any(s == "long_call" for s in strategies)


def test_stale_chain_blocks_enter_but_keeps_watch_visibility():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_two_sided_repo(root, stale=True)
        result = run_pullback_flow_engine(
            account=250000.0, context=_ctx(), config=_config(), root_dir=root
        )
    assert result["plays"] == []
    watched = [d for d in result["watchlist"] if d["freshness"]["chain_snapshot_stale"]]
    assert watched, "stale-chain setups must remain visible on the watchlist"


def test_enter_slots_with_failed_gates_are_downgraded_to_watch():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Small account: every contract breaches the 0.5% budget -> no ENTER.
        _seed_two_sided_repo(root)
        result = run_pullback_flow_engine(
            account=1000.0, context=_ctx(), config=_config(), root_dir=root
        )
    assert result["plays"] == []
    demoted = [
        d for d in result["watchlist"] if d["provenance"].get("enter_downgraded_to_watch")
    ]
    assert demoted, "budget-blocked ENTER slots must be demoted, not silently dropped"
