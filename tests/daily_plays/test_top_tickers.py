"""Options-only Top Tickers from a mixed classified tape."""
from __future__ import annotations

from edge.daily_plays.options_intelligence import (
    build_options_top_tickers,
    classify_options_tape,
)


def _print(symbol: str, **over):
    row = {
        "underlying": symbol,
        "contract_type": "call",
        "premium": 50_000,
        "volume": 20,
        "open_interest": 400,
        "timestamp": "2026-07-31T14:45:00Z",
        "expiry": "2026-08-20",
        "strike": 115,
        "underlying_price": 100,
        "multiplier": 100,
    }
    row.update(over)
    return row


def test_category_winners_differ_and_put_only_is_not_call_leader():
    tape = classify_options_tape([
        # Unusual OTM leader: far OTM + near-dated (still ≥10% and ≤35 DTE).
        _print("OTMX", premium=60_000, volume=10, strike=140, timestamp="2026-07-31T14:40:00Z"),
        # Unusual volume leader: many contracts, milder OTM.
        _print("VOLX", premium=70_000, volume=400, strike=112, open_interest=50,
               timestamp="2026-07-31T14:41:00Z"),
        # Unusual premium leader: huge notional, moderate OTM/volume.
        _print("PREM", premium=900_000, volume=30, strike=112, open_interest=5_000,
               timestamp="2026-07-31T14:42:00Z"),
        # Sweep leader — dated so it is not Unusual.
        _print("SWPX", premium=400_000, volume=40, trade_class="sweep",
               expiry="2026-09-09", strike=101, timestamp="2026-07-31T13:00:00Z"),
        # Momentum leader — high relative volume, not unusual, not a sweep.
        _print("MOMX", premium=80_000, volume=500, open_interest=80,
               expiry="2026-09-09", strike=102, timestamp="2026-07-31T12:00:00Z"),
        # Call premium leader — unsigned calls only.
        _print("CALLY", premium=1_200_000, volume=40, expiry="2026-09-09", strike=103,
               timestamp="2026-07-31T11:00:00Z"),
        # Put-only name: cannot win Call Premium.
        _print("PUTTY", contract_type="put", premium=1_500_000, volume=50,
               expiry="2026-09-09", strike=99, timestamp="2026-07-31T10:00:00Z"),
    ])
    board = build_options_top_tickers(tape)
    winners = {
        name: rows[0]["symbol"]
        for name, rows in board["categories"].items()
        if rows
    }
    assert winners["unusual_otm"] == "OTMX"
    assert winners["unusual_volume"] == "VOLX"
    assert winners["unusual_premium"] == "PREM"
    assert winners["sweeps"] == "SWPX"
    assert winners["momentum"] == "MOMX"
    assert winners["call_premium"] == "CALLY"
    assert winners["put_premium"] == "PUTTY"
    assert winners["call_premium"] != winners["put_premium"]
    assert len(set(winners.values())) == len(winners)


def test_directional_share_uses_signed_premium_else_call_put():
    tape = classify_options_tape([
        _print("SIGNED", premium=300_000, volume=30, aggressor="BUY"),
        _print("SIGNED", contract_type="put", premium=100_000, volume=10,
               aggressor="BUY", strike=90),
        _print("MIX", premium=200_000, volume=20, expiry="2026-09-09", strike=101),
        _print("MIX", contract_type="put", premium=50_000, volume=10,
               expiry="2026-09-09", strike=99),
    ])
    board = build_options_top_tickers(tape)
    by_symbol = {row["symbol"]: row for row in board["tickers"]}

    signed = by_symbol["SIGNED"]
    assert signed["share_basis"] == "signed_premium"
    assert signed["bullish_share"] == 300_000 / 400_000
    assert signed["bearish_share"] == 100_000 / 400_000

    mixed = by_symbol["MIX"]
    assert mixed["share_basis"] == "call_put_premium"
    assert mixed["bullish_share"] == 200_000 / 250_000
    assert mixed["bearish_share"] == 50_000 / 250_000
