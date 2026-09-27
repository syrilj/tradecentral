"""Fail-closed contract for market-wide options flow.

Drives the shipped classifier, normalizer, market-flow loader, and unusual-flow
builder with injected prints. Does not mock those units or start past
classification.
"""
from __future__ import annotations

import time

import pytest

from edge.daily_plays.adapters.flow import (
    load_live_forward_flow,
    load_market_flow_activity,
    lse_circuit_is_open,
    normalize_flow_payload,
    reset_lse_circuit,
)
from edge.daily_plays.live_activity import build_unusual_options_flow
from edge.daily_plays.options_intelligence import classify_options_tape
import numpy as np
import pandas as pd


@pytest.fixture(autouse=True)
def _reset_lse_circuit():
    reset_lse_circuit()
    yield
    reset_lse_circuit()


def _bars(*, jump: float = 0.0, volume_multiple: float = 1.0, periods: int = 70) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=periods, freq="B")
    close = np.linspace(100.0, 104.0, len(dates))
    close[-1] *= 1.0 + jump
    volume = np.full(len(dates), 1_000_000.0)
    volume[-1] *= volume_multiple
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _print(**over):
    row = {
        "contract_type": "call",
        "premium": 80_000,
        "volume": 20,
        "open_interest": 400,
        "timestamp": "2026-07-31T14:45:00Z",
        "expiry": "2026-08-20",
        "strike": 115,
        "underlying_price": 100,
        "multiplier": 100,
        "symbol": "AAA",
    }
    row.update(over)
    return row


def test_missing_dte_oi_aggressor_strike_stay_missing_not_zero():
    tape = classify_options_tape(
        [
            {
                key: value
                for key, value in _print().items()
                if key not in {"expiry", "open_interest", "strike"}
            }
        ]
    )
    assert len(tape) == 1
    row = tape[0]
    assert row["dte"] is None
    assert row["open_interest"] is None
    assert row["strike"] is None
    assert row["otm_pct"] is None
    assert row["aggressor"] is None
    assert row["signed_premium"] is None
    assert row["is_unusual"] is False
    assert row["is_top_position"] is False
    assert row["dte"] != 0
    assert row["open_interest"] != 0
    assert row["otm_pct"] != 0


def test_unsigned_print_has_no_signed_premium_or_aggressor():
    row = classify_options_tape([_print()])[0]
    assert row["aggressor"] is None
    assert row["signed_premium"] is None
    assert row["bias"] is None
    assert row.get("aggressor_label") == "NO SIDE"
    assert row["edge_label"] == "CALL"


def test_vendor_sweep_stays_distinct_from_burst_heuristic():
    vendor = classify_options_tape([_print(trade_class="sweep")])[0]
    burst = classify_options_tape(
        [
            _print(id="b1", timestamp="2026-07-31T14:45:00Z", premium=80_000),
            _print(id="b2", timestamp="2026-07-31T14:45:02Z", premium=80_000),
        ]
    )
    assert vendor["trade_class"] == "sweep"
    assert vendor["trade_class_source"] == "vendor"
    assert vendor["is_sweep"] is True
    assert {row["trade_class_source"] for row in burst} == {"burst_heuristic"}
    assert all(row["trade_class"] == "sweep" for row in burst)
    assert vendor["trade_class_source"] != next(iter(burst))["trade_class_source"]


def test_put_whale_premium_mix_is_put_heavy_not_print_count_heavy():
    tape = classify_options_tape(
        [
            *(_print(id=f"c{i}", premium=20_000, timestamp=f"2026-07-31T14:4{i}:00Z") for i in range(5)),
            _print(
                id="put-whale",
                contract_type="put",
                premium=400_000,
                strike=90,
                timestamp="2026-07-31T14:49:00Z",
            ),
        ]
    )
    result = normalize_flow_payload(
        {
            "symbol": "AAA",
            "alerts": [
                *(_print(id=f"c{i}", premium=20_000, timestamp=f"2026-07-31T14:4{i}:00Z") for i in range(5)),
                _print(
                    id="put-whale",
                    contract_type="put",
                    premium=400_000,
                    strike=90,
                    timestamp="2026-07-31T14:49:00Z",
                ),
            ],
        }
    )
    assert result["evidence"]["put_flow_pct"] == pytest.approx(0.8, abs=1e-6)
    assert result["evidence"]["call_flow_pct"] == pytest.approx(0.2, abs=1e-6)
    assert result["evidence"]["call_print_count"] == 5
    assert result["evidence"]["put_print_count"] == 1
    assert result["direction"] == "neutral"
    assert result["evidence"]["direction_signed"] is False
    assert len(tape) == 6


def test_symbol_mismatched_provider_dump_is_discarded():
    result = load_live_forward_flow(
        "SPY",
        fetcher=lambda **_: [
            {"underlying": "NVDA", "contract_type": "call", "premium": 250_000, "ts": "2026-07-31T14:45:00Z"}
        ],
    )
    assert result == {"_evidence_warning": "flow_symbol_mismatch"}


def test_market_flow_timeout_and_credential_missing_are_empty_fail_closed(monkeypatch):
    reset_lse_circuit()
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    missing = load_market_flow_activity()
    assert missing["rows"] == []
    assert missing["warnings"] == ["flow_lse_credential_missing"]

    def slow(**_):
        time.sleep(0.05)
        return [{"underlying": "SPY", "premium": 100_000, "contract_type": "call"}]

    timed = load_market_flow_activity(fetcher=slow, timeout_seconds=0.01)
    assert timed["rows"] == []
    assert timed["warnings"] == ["flow_market_timeout"]
    reset_lse_circuit()


def test_unusual_flow_timeout_and_credential_missing_empty_tape(monkeypatch):
    reset_lse_circuit()
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    missing = build_unusual_options_flow(
        symbols=["AAA"],
        candle_loader={"AAA": _bars()}.__getitem__,
        row_limit=5,
        min_premium=25_000,
    )
    assert missing["feed_status"] == "credential_missing"
    assert missing["rows"] == []
    assert missing["tape"] == []
    assert missing["decision_authorized"] is False
    assert missing["asof"] in {None, ""}
    assert "flow_lse_credential_missing" in missing["warnings"]

    def boom(**_):
        raise TimeoutError("flow_provider_timeout")

    timed = build_unusual_options_flow(
        symbols=["AAA"],
        candle_loader={"AAA": _bars()}.__getitem__,
        flow_fetcher=boom,
        row_limit=5,
        min_premium=25_000,
    )
    assert timed["feed_status"] == "unavailable"
    assert timed["rows"] == []
    assert timed["tape"] == []
    assert timed["decision_authorized"] is False
    reset_lse_circuit()


def test_unusual_score_is_tape_premium_not_daily_bar_mix():
    quiet = _bars(jump=0.0, volume_multiple=1.0)
    loud = _bars(jump=0.12, volume_multiple=8.0)

    def flow_fetcher(**_):
        return [
            {
                "underlying": "AAA",
                "contract_type": "call",
                "premium": 200_000,
                "volume": 20,
                "ts": "2026-08-11T15:00:00Z",
            }
        ]

    quiet_result = build_unusual_options_flow(
        symbols=["AAA"],
        candle_loader={"AAA": quiet}.__getitem__,
        flow_fetcher=flow_fetcher,
        row_limit=5,
        min_premium=25_000,
    )
    loud_result = build_unusual_options_flow(
        symbols=["AAA"],
        candle_loader={"AAA": loud}.__getitem__,
        flow_fetcher=flow_fetcher,
        row_limit=5,
        min_premium=25_000,
    )
    assert quiet_result["rows"][0]["unusual_score"] == loud_result["rows"][0]["unusual_score"]
    assert loud_result["rows"][0]["local_activity_score"] > quiet_result["rows"][0]["local_activity_score"]
    assert "daily-bar" in " ".join(quiet_result["caveats"]).lower() or "local activity" in " ".join(
        quiet_result["caveats"]
    ).lower()


def test_market_flow_circuit_opens_after_three_timeouts():
    reset_lse_circuit()
    calls = {"n": 0}

    def always_timeout(**_):
        calls["n"] += 1
        time.sleep(0.04)
        return [{"underlying": "AAA", "premium": 100_000, "contract_type": "call"}]

    for _ in range(3):
        out = load_market_flow_activity(fetcher=always_timeout, timeout_seconds=0.01)
        assert out["warnings"] == ["flow_market_timeout"]
        assert out["rows"] == []
    assert lse_circuit_is_open() is True
    before = calls["n"]
    skipped = load_market_flow_activity(timeout_seconds=0.01)
    assert skipped["warnings"] == ["flow_lse_circuit_open"]
    assert skipped["rows"] == []
    assert calls["n"] == before
    reset_lse_circuit()


def test_asof_is_last_trade_time_not_generated_at():
    result = build_unusual_options_flow(
        symbols=["AAA"],
        candle_loader={"AAA": _bars()}.__getitem__,
        flow_fetcher=lambda **_: [
            {
                "underlying": "AAA",
                "contract_type": "put",
                "premium": 120_000,
                "ts": "2026-08-11T15:04:00Z",
            }
        ],
        row_limit=5,
        min_premium=25_000,
    )
    assert result["asof"] == "2026-08-11T15:04:00Z"
    assert result["generated_at"] != result["asof"]
    assert result["rows"][0]["decision_authorized"] is False
    assert all(row.get("decision_authorized") is False for row in result["tape"])


def test_heat_does_not_invent_dte_when_expiry_missing():
    missing = classify_options_tape([_print(expiry=None)])[0]
    dated = classify_options_tape([_print()])[0]
    assert missing["dte"] is None
    assert dated["dte"] == 20
    # Missing DTE must not be scored as if it were the 30-day default.
    assert missing["heat"] != dated["heat"] or missing["dte"] is None
