"""Insider tape: measured prints only, and a real 90-day window.

The dashboard contract (dashboard/src/api.ts InsidersIntelligencePayload)
reads summary.buy_count / sell_count / total_transactions / net_shares_90d
and quarterly_net[].net_volume / transaction_count. The builder used to
emit different names, invent $30 prices and 4x share holdings, book every
non-purchase as a sale, and call the first eight rows a 90-day window.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tools import financial_data

ASOF = date(2026, 11, 15)


def _row(**overrides):
    base = {
        "date": "2026-11-01",
        "insider_name": "Ada Lovelace",
        "relationship": "CEO",
        "transaction_type": "Purchase",
        "shares": 100,
        "price": 10.0,
        "value": 1000.0,
        "shares_held_after": 500,
    }
    base.update(overrides)
    return base


def test_missing_price_and_holding_stay_missing():
    row = financial_data.normalize_yfinance_insider_row(
        {
            "Insider": "Ada Lovelace",
            "Position": "CEO",
            "Text": "Purchase",
            "Shares": 100,
            "Start Date": "2026-08-01",
        }
    )
    assert row is not None
    assert row["transaction_type"] == "Purchase"
    assert row["shares"] == 100
    assert row["price"] is None
    assert row["value"] is None
    assert row["shares_held_after"] is None
    assert row["direct_indirect"] is None
    assert row["insider_name"] == "Ada Lovelace"
    assert "Officer/Director" not in row["insider_name"]


def test_zero_holding_is_kept_and_price_is_not_replaced():
    row = financial_data.normalize_yfinance_insider_row(
        {
            "Insider": "Ada Lovelace",
            "Text": "Sale",
            "Shares": 40,
            "Price": 0,
            "Value": 0,
            "Shares Held After": 0,
            "Start Date": "2026-08-02",
        }
    )
    assert row is not None
    assert row["price"] == 0
    assert row["value"] == 0
    assert row["shares_held_after"] == 0


def test_value_is_derived_only_from_a_measured_price():
    derived = financial_data.normalize_yfinance_insider_row(
        {
            "Insider": "Ada Lovelace",
            "Text": "Purchase",
            "Shares": 100,
            "Price": 12.5,
            "Start Date": "2026-08-01",
        }
    )
    assert derived is not None
    assert derived["value"] == 1250.0
    assert derived["price"] == 12.5

    from_value = financial_data.normalize_yfinance_insider_row(
        {
            "Insider": "Ada Lovelace",
            "Text": "Sale",
            "Shares": -80,
            "Value": 400,
            "Start Date": "2026-08-03",
        }
    )
    assert from_value is not None
    assert from_value["transaction_type"] == "Sale"
    assert from_value["shares"] == 80
    assert from_value["price"] == 5.0


def test_unknown_and_gift_are_not_option_exercises_or_sales():
    assert financial_data.classify_insider_transaction("Gift", 10) == "Other"
    assert financial_data.classify_insider_transaction("", 25) == "Other"
    assert financial_data.classify_insider_transaction("Sold", 10) == "Sale"
    assert financial_data.classify_insider_transaction("", -10) == "Sale"
    assert financial_data.classify_insider_transaction("Option exercise", 10) == "Option Exercise"
    assert financial_data.classify_insider_transaction("Purchase", 10) == "Purchase"


def test_summary_is_ninety_days_not_the_first_eight_rows():
    purchases = [_row(date=f"2026-11-{day:02d}", value=1_000.0, shares=10) for day in range(1, 11)]
    stale_sale = _row(
        date="2026-01-02",
        transaction_type="Sale",
        shares=5_000,
        value=500_000.0,
        insider_name="Grace Hopper",
    )
    exercise = _row(
        date="2026-11-10",
        transaction_type="Option Exercise",
        shares=200,
        value=20_000.0,
        insider_name="Alan Turing",
    )
    gift = _row(
        date="2026-11-04",
        transaction_type="Other",
        shares=15,
        value=150.0,
        insider_name="Alan Turing",
    )
    summary, quarterly = financial_data.summarize_insider_activity(
        [*purchases, stale_sale, exercise, gift],
        asof=ASOF,
    )

    assert summary["buy_count"] == 10
    assert summary["sell_count"] == 0
    assert summary["buy_volume_usd"] == 10_000.0
    assert summary["sell_volume_usd"] == 0.0
    assert summary["net_volume_usd"] == 10_000.0
    assert summary["net_shares_90d"] == 100
    # Ten purchases plus the exercise and the gift. The January sale is outside.
    assert summary["total_transactions"] == 12
    assert summary["option_transactions_count"] == 1
    assert summary["sentiment"] == "Bullish"

    by_quarter = {row["quarter"]: row for row in quarterly}
    assert by_quarter["2026 Q4"]["net_volume"] == 10_000.0
    assert by_quarter["2026 Q4"]["transaction_count"] == 10
    assert by_quarter["2026 Q1"]["net_volume"] == -500_000.0
    assert by_quarter["2026 Q1"]["transaction_count"] == 1
    assert "net_usd" not in by_quarter["2026 Q4"]
    assert "buy_transactions_count" not in summary


def test_blank_dollar_value_does_not_become_a_zero_total():
    summary, quarterly = financial_data.summarize_insider_activity(
        [_row(value=None, price=None)],
        asof=ASOF,
    )
    assert summary["buy_count"] == 1
    assert summary["buy_volume_usd"] is None
    assert summary["net_volume_usd"] is None
    assert summary["sentiment"] is None
    assert quarterly[0]["net_volume"] is None
    assert quarterly[0]["transaction_count"] == 1


def test_source_no_longer_invents_insider_dollars_or_holdings():
    source = Path(financial_data.__file__).read_text(encoding="utf-8")
    assert "or 30.0" not in source
    assert "else 35.0" not in source
    assert "sh * 4" not in source
