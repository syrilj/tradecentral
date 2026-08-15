"""Ship the InsiderFinance-style options tape classifier.

Tests inject fixture prints into ``classify_options_tape`` — the same
normalize + annotate + label path the live adapter uses. They do not mock
the classifier or re-implement its rules.
"""
from __future__ import annotations

from edge.daily_plays.options_intelligence import (
    classify_options_tape,
    filter_tape_preset,
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


def _one(**over):
    tape = classify_options_tape([_print(**over)])
    assert len(tape) == 1
    return tape[0]


def test_twenty_dte_fifteen_otm_is_unusual_and_call():
    row = _one()
    assert row["right"] == "call"
    assert row["dte"] == 20
    assert row["otm_pct"] == 0.15
    assert row["is_unusual"] is True
    assert "unusual" in row["presets"]


def test_forty_dte_or_five_otm_is_not_unusual():
    long_dated = _one(expiry="2026-09-09")  # 40 DTE from 2026-07-31
    near_atm = _one(strike=105)  # 5% OTM
    assert long_dated["dte"] == 40
    assert long_dated["is_unusual"] is False
    assert "unusual" not in long_dated["presets"]
    assert near_atm["otm_pct"] == 0.05
    assert near_atm["is_unusual"] is False


def test_vendor_sweep_including_split_and_vendor_block_survive():
    sweep = _one(trade_class="sweep")
    split = _one(trade_type="split")
    block = _one(trade_class="block")
    assert sweep["is_sweep"] is True
    assert sweep["trade_class"] == "sweep"
    assert sweep["trade_class_source"] == "vendor"
    assert "sweeps" in sweep["presets"]
    assert split["is_sweep"] is True
    assert split["trade_class"] == "sweep"
    assert split["trade_class_source"] == "vendor"
    assert block["is_block"] is True
    assert block["trade_class"] == "block"
    assert block["trade_class_source"] == "vendor"
    assert block["is_sweep"] is False


def test_size_above_open_interest_is_top_position():
    top = _one(volume=250, open_interest=100)
    not_top = _one(volume=20, open_interest=400)
    unknown = classify_options_tape([
        {key: value for key, value in _print(volume=50).items() if key != "open_interest"},
    ])[0]
    assert top["is_top_position"] is True
    assert not_top["is_top_position"] is False
    assert unknown["is_top_position"] is False


def test_heat_rises_when_size_or_premium_rises_other_inputs_fixed():
    base = _one(volume=10, premium=40_000, open_interest=500)
    bigger_size = _one(volume=80, premium=40_000, open_interest=500)
    bigger_premium = _one(volume=10, premium=400_000, open_interest=500)
    assert bigger_size["heat"] > base["heat"]
    assert bigger_premium["heat"] > base["heat"]


def test_presets_keep_only_matching_rows():
    unusual = _print(symbol="UNU", timestamp="2026-07-31T14:45:00Z")
    sweep = _print(
        symbol="SWP", trade_class="sweep", strike=101, expiry="2026-09-09",
        timestamp="2026-07-31T13:00:00Z",
    )
    momentum = _print(
        symbol="MOM", volume=300, open_interest=100, strike=102, expiry="2026-09-09",
        timestamp="2026-07-31T12:00:00Z",
    )
    moonshot = _print(
        symbol="MOON",
        premium=12_500,
        volume=100,
        strike=130,
        expiry="2026-09-09",
        open_interest=5_000,
        timestamp="2026-07-31T11:00:00Z",
    )
    other = _print(
        symbol="OTH",
        volume=5,
        open_interest=2_000,
        strike=103,
        expiry="2026-09-09",
        premium=10_000,
        timestamp="2026-07-31T10:00:00Z",
    )
    tape = classify_options_tape([unusual, sweep, momentum, moonshot, other])
    unusual_only = filter_tape_preset(tape, "unusual")
    sweeps_only = filter_tape_preset(tape, "sweeps")
    momentum_only = filter_tape_preset(tape, "momentum")
    moonshot_only = filter_tape_preset(tape, "moonshot")

    assert {row["symbol"] for row in unusual_only} == {"UNU"}
    assert {row["symbol"] for row in sweeps_only} == {"SWP"}
    assert {row["symbol"] for row in momentum_only} == {"MOM"}
    assert {row["symbol"] for row in moonshot_only} == {"MOON"}
    assert all(row["price"] is not None and row["price"] <= 2.50 for row in moonshot_only)
    assert all((row["otm_pct"] or 0) >= 0.20 for row in moonshot_only)
    assert all(row.get("bias") is None for row in tape)  # no invented buy/sell
