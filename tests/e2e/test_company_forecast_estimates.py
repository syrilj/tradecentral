"""Street forecast builder: real ratings, real firm targets, no synthetic pad.

Drives tools.financial_data.get_company_profile_payload — the same function
/api/company-profile uses — with mocked Yahoo frames shaped like
yfinance 0.2.66 (recommendations_summary + upgrades_downgrades).
"""
from __future__ import annotations

import pandas as pd
import pytest

from tools import financial_data

PAD_RESEARCH_FIRMS = {
    "Goldman Sachs",
    "JPMorgan",
    "Morgan Stanley",
    "Needham & Company",
    "Evercore ISI",
    "KeyBanc Capital Markets",
    "Craig-Hallum",
    "Roth MKM",
}


class _FakeTicker:
    def __init__(
        self,
        *,
        info=None,
        recommendations_summary=None,
        recommendations=None,
        upgrades_downgrades=None,
        analyst_price_targets=None,
    ):
        self.info = info or {}
        self.recommendations_summary = recommendations_summary
        self.recommendations = recommendations
        self.upgrades_downgrades = upgrades_downgrades
        self.analyst_price_targets = analyst_price_targets or {}


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    financial_data._CACHE_PROFILE.clear()
    yield
    financial_data._CACHE_PROFILE.clear()


def _rec_summary(strong_buy: int, buy: int, hold: int, sell: int, strong_sell: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": ["0m", "-1m"],
            "strongBuy": [strong_buy, strong_buy],
            "buy": [buy, buy],
            "hold": [hold, hold],
            "sell": [sell, sell],
            "strongSell": [strong_sell, strong_sell],
        }
    )


def _upgrades(rows: list[dict]) -> pd.DataFrame:
    index = pd.to_datetime([row["date"] for row in rows])
    return pd.DataFrame(
        {
            "Firm": [row["firm"] for row in rows],
            "ToGrade": [row["to"] for row in rows],
            "FromGrade": [row.get("frm", "") for row in rows],
            "Action": [row.get("action", "main") for row in rows],
            "priceTargetAction": [row.get("pt_action", "") for row in rows],
            "currentPriceTarget": [row.get("target", 0.0) for row in rows],
            "priorPriceTarget": [row.get("prior", 0.0) for row in rows],
        },
        index=index,
    )


def test_forecast_uses_live_rating_counts_not_opinion_percentages():
    """ASTS-shaped: 11 opinions. Fabricated mix is 5/3/1/1/0. Live is 1/3/7/1/1."""
    ticker = _FakeTicker(
        info={
            "numberOfAnalystOpinions": 11,
            "recommendationMean": 2.69,
            "recommendationKey": "hold",
            "targetHighPrice": 108.0,
            "targetMedianPrice": 80.0,
            "targetLowPrice": 42.5,
            "targetMeanPrice": 78.48,
            "currentPrice": 70.98,
        },
        recommendations_summary=_rec_summary(1, 3, 7, 1, 1),
        upgrades_downgrades=_upgrades(
            [
                {
                    "date": "2026-08-11",
                    "firm": "UBS",
                    "to": "Neutral",
                    "frm": "Neutral",
                    "action": "main",
                    "pt_action": "Lowers",
                    "target": 78.0,
                    "prior": 80.0,
                },
                {
                    "date": "2026-08-11",
                    "firm": "Piper Sandler",
                    "to": "Overweight",
                    "frm": "Overweight",
                    "action": "main",
                    "pt_action": "Lowers",
                    "target": 98.0,
                    "prior": 100.0,
                },
                {
                    "date": "2026-07-29",
                    "firm": "Scotiabank",
                    "to": "Sector Perform",
                    "frm": "Sector Underperform",
                    "action": "up",
                    "pt_action": "Announces",
                    "target": 50.8,
                    "prior": 0.0,
                },
            ]
        ),
        analyst_price_targets={
            "current": 70.98,
            "high": 108.0,
            "low": 42.5,
            "mean": 78.48,
            "median": 80.0,
        },
    )

    payload = financial_data.get_company_profile_payload("ASTS", ticker=ticker)
    forecast = payload["forecast"]
    recs = forecast["recommendations"]

    assert recs["strong_buy"] == 1
    assert recs["buy"] == 3
    assert recs["hold"] == 7
    assert recs["sell"] == 1
    assert recs["strong_sell"] == 1
    assert recs["strong_buy"] != 5
    assert forecast["consensus_rating"] == "Hold"
    assert forecast["analyst_count"] == 13
    assert forecast["target_price_median"] == 80.0
    assert forecast["target_price_high"] == 108.0
    assert forecast["target_price_low"] == 42.5


def test_forecast_exposes_each_firm_target_and_whether_the_mark_hit_it():
    ticker = _FakeTicker(
        info={"currentPrice": 70.98, "recommendationKey": "hold"},
        recommendations_summary=_rec_summary(1, 3, 7, 1, 1),
        upgrades_downgrades=_upgrades(
            [
                {
                    "date": "2026-08-11",
                    "firm": "UBS",
                    "to": "Neutral",
                    "target": 78.0,
                    "prior": 80.0,
                    "pt_action": "Lowers",
                },
                {
                    "date": "2026-08-01",
                    "firm": "UBS",
                    "to": "Neutral",
                    "target": 80.0,
                    "prior": 85.0,
                    "pt_action": "Lowers",
                },
                {
                    "date": "2026-07-29",
                    "firm": "Scotiabank",
                    "to": "Sector Perform",
                    "action": "up",
                    "target": 50.8,
                    "pt_action": "Announces",
                },
                {
                    "date": "2026-07-17",
                    "firm": "Needham",
                    "to": "Hold",
                    "action": "reit",
                    "target": 0.0,
                },
            ]
        ),
    )

    forecast = financial_data.get_company_profile_payload("ASTS", ticker=ticker)["forecast"]
    estimates = forecast["estimates"]
    by_firm = {row["firm"]: row for row in estimates}

    assert set(by_firm) == {"UBS", "Scotiabank"}
    assert by_firm["UBS"]["target"] == 78.0
    assert by_firm["UBS"]["prior_target"] == 80.0
    assert by_firm["UBS"]["hit"] is False
    assert by_firm["Scotiabank"]["target"] == 50.8
    assert by_firm["Scotiabank"]["hit"] is True
    assert "Needham" not in by_firm
    assert forecast["estimates_hit"] == 1
    assert forecast["estimates_open"] == 1


def test_forecast_keeps_every_revision_and_never_pads_fake_firms():
    real_rows = [
        {
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "firm": f"Named Desk {i:03d}",
            "to": "Buy",
            "action": "main",
            "target": 10.0 + i,
        }
        for i in range(80)
    ]
    ticker = _FakeTicker(
        info={"currentPrice": 40.0, "numberOfAnalystOpinions": 80},
        recommendations_summary=_rec_summary(10, 20, 40, 8, 2),
        upgrades_downgrades=_upgrades(real_rows),
    )

    forecast = financial_data.get_company_profile_payload("INFQ", ticker=ticker)["forecast"]
    revisions = forecast["upgrades_downgrades"]
    firms = [row["firm"] for row in revisions]

    assert len(revisions) == 80
    assert firms[0] == "Named Desk 000"
    assert firms[-1] == "Named Desk 079"
    assert PAD_RESEARCH_FIRMS.isdisjoint(firms)
    assert all(row.get("target") == 10.0 + i for i, row in enumerate(revisions))


def test_forecast_blank_yahoo_cells_do_not_render_as_nan():
    ticker = _FakeTicker(
        info={"currentPrice": 20.0},
        upgrades_downgrades=pd.DataFrame(
            {
                "Firm": ["Desk A"],
                "ToGrade": [float("nan")],
                "FromGrade": [float("nan")],
                "Action": [float("nan")],
                "priceTargetAction": [float("nan")],
                "currentPriceTarget": [float("nan")],
                "priorPriceTarget": [float("nan")],
            },
            index=pd.to_datetime(["2026-08-01"]),
        ),
    )
    rev = financial_data.get_company_profile_payload("NANX", ticker=ticker)["forecast"][
        "upgrades_downgrades"
    ][0]
    assert "nan" not in str(rev["current"]).lower()
    assert "nan" not in str(rev["previous"]).lower()
    assert rev["target"] is None
    assert rev["target_action"] is None


def test_compensation_does_not_invent_officer_pay():
    ticker = _FakeTicker(
        info={
            "companyOfficers": [
                {"name": "Ada Lovelace", "title": "Chief Executive Officer", "totalPay": 4_200_000},
                {"name": "Alan Turing", "title": "Chief Scientist"},
            ]
        }
    )
    payload = financial_data.get_company_profile_payload("PAYX", ticker=ticker)
    comp = payload["compensation"]
    assert comp["highest_paid_name"] == "Ada Lovelace"
    assert comp["highest_paid_total"] == 4_200_000
    assert comp["median_employee_pay"] is None
    assert comp["ceo_pay_ratio"] is None
    assert comp["rows"][0]["total_compensation"] == 4_200_000
    assert comp["rows"][0]["salary"] is None
    assert comp["rows"][1]["total_compensation"] is None

    empty = financial_data.get_company_profile_payload("NOPAY", ticker=_FakeTicker(info={}))
    assert empty["compensation"]["rows"] == []
    assert empty["compensation"]["highest_paid_total"] is None
    assert empty["compensation"]["highest_paid_name"] is None


def test_forecast_missing_street_data_stays_explicitly_empty():
    ticker = _FakeTicker(info={})

    forecast = financial_data.get_company_profile_payload("ZZZX", ticker=ticker)["forecast"]

    assert forecast["consensus_rating"] is None
    assert forecast["recommendation_mean"] is None
    assert forecast["target_price_median"] is None
    assert forecast["target_price_high"] is None
    assert forecast["target_price_low"] is None
    assert forecast["upside_pct"] is None
    assert forecast["recommendations"] is None
    assert forecast["upgrades_downgrades"] == []
    assert forecast["estimates"] == []
    firms = [row.get("firm") for row in forecast.get("upgrades_downgrades") or []]
    assert PAD_RESEARCH_FIRMS.isdisjoint(set(firms))
