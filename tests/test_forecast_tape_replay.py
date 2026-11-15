"""The published financials payload must replay to the forecast it shipped.

score_report_forecast blends live revenue growth, earnings growth, forward
EPS, and the 52-week range into the price. Those inputs used to be scored
and then dropped, so replaying the response produced a different mark.
"""
from __future__ import annotations

from research.financials_ml_forecast import score_report_forecast
from tools import financial_data


def _report() -> dict:
    def row(key: str, label: str, values: list[float]) -> dict:
        return {"key": key, "label": label, "values": values}

    return {
        "symbol": "GROW",
        "period_type": "quarterly",
        "periods": ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"],
        "income_statement": {
            "rows": [
                row("total_revenue", "Total Revenue", [200e6, 170e6, 150e6, 130e6, 110e6]),
                row("gross_profit", "Gross Profit", [120e6, 98e6, 84e6, 70e6, 55e6]),
                row("operating_income", "Operating Income (EBIT)", [50e6, 38e6, 30e6, 22e6, 14e6]),
                row("net_income", "Net Income", [40e6, 30e6, 22e6, 16e6, 10e6]),
                row("diluted_eps", "Diluted EPS", [2.0, 1.5, 1.1, 0.8, 0.5]),
            ]
        },
        "balance_sheet": {
            "rows": [
                row("cash_equivalents", "Cash & Cash Equivalents", [80e6, 70e6, 60e6]),
                row("total_assets", "Total Assets", [300e6, 270e6, 240e6]),
                row("long_term_debt", "Long-Term Debt", [20e6, 22e6, 24e6]),
                row("stockholders_equity", "Total Stockholders' Equity", [220e6, 200e6, 180e6]),
            ]
        },
        "cash_flow": {
            "rows": [
                row("operating_cash_flow", "Cash from Operating Activities", [55e6, 42e6, 30e6]),
                row("free_cash_flow", "Free Cash Flow", [19e6, 14e6, 10e6]),
            ]
        },
        "ratios": {"current_price": 40.0, "market_cap": 800e6, "pe_trailing": 20.0},
    }


def test_published_tape_replays_the_forecast_that_used_it(monkeypatch):
    intel = {
        "last_price": 40.0,
        "current_price": 40.0,
        "forward_eps": 3.2,
        "revenue_growth": 0.55,
        "earnings_growth": 0.40,
        "range_position": 0.82,
        "ret_3m": 0.12,
        "trailing_eps": 2.0,
        "spot_source": "yfinance_delayed_last_price",
    }
    monkeypatch.setattr(financial_data, "resolve_forecast_intel", lambda _symbol: dict(intel))

    published = financial_data._with_model_forecast(_report())
    forecast = published["model_forecast"]
    replay = score_report_forecast(published)

    assert forecast["predicted_price"] == replay["predicted_price"]
    assert forecast["forecast_score"] == replay["forecast_score"]
    assert forecast["gearing_up_towards"] == replay["gearing_up_towards"]
    tape = published["tape"]
    assert tape["forward_eps"] == 3.2
    assert tape["revenue_growth"] == 0.55
    assert tape["earnings_growth"] == 0.40
    assert tape["range_position"] == 0.82
    assert "insider_net_volume_usd" not in tape
