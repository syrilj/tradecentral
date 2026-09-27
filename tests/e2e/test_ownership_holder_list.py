"""Ownership builder: no 30-row cap, no famous-institution pad.

Drives tools.financial_data.get_ownership_payload — the same function the
/api/ownership handler uses — with mocked Yahoo frames shaped like
yfinance 0.2.66 (Holders._parse_major_holders_breakdown /
_parse_institution_ownership).
"""
from __future__ import annotations

import pandas as pd
import pytest

from tools import financial_data

PAD_HOLDER_NAMES = {
    "Vanguard Group Inc",
    "Blackrock Inc.",
    "State Street Corp",
    "Fidelity Management & Research (FMR LLC)",
    "Geode Capital Management, LLC",
    "T. Rowe Price Associates, Inc.",
    "Citadel Advisors LLC",
    "Millennium Management LLC",
    "Renaissance Technologies LLC",
    "Jane Street Group, LLC",
    "Two Sigma Investments, LP",
    "D.E. Shaw & Co., Inc.",
}


class _FakeTicker:
    def __init__(
        self,
        *,
        info=None,
        institutional_holders=None,
        mutualfund_holders=None,
        major_holders=None,
    ):
        self.info = info or {}
        self.institutional_holders = institutional_holders
        self.mutualfund_holders = mutualfund_holders
        self.major_holders = major_holders


@pytest.fixture(autouse=True)
def _clear_ownership_cache():
    financial_data._CACHE_OWNERSHIP.clear()
    yield
    financial_data._CACHE_OWNERSHIP.clear()


def _yf_major_holders(institutions_count: int) -> pd.DataFrame:
    """Exact 0.2.66 shape: DataFrame.from_dict(majorHoldersBreakdown, orient='index')."""
    data = {
        "insidersPercentHeld": 0.012,
        "institutionsPercentHeld": 0.624,
        "institutionsFloatPercentHeld": 0.641,
        "institutionsCount": institutions_count,
    }
    df = pd.DataFrame.from_dict(data, orient="index")
    df.columns.name = "Breakdown"
    df.rename(columns={df.columns[0]: "Value"}, inplace=True)
    return df


def _yf_inst_holders(n: int, names: list[str] | None = None) -> pd.DataFrame:
    """Exact 0.2.66 institutional_holders columns after yfinance rename.

    Live columns are Date Reported, Holder, pctHeld, Shares, Value, pctChange.
    pctHeld is a decimal (0.0823 == 8.23%); pctChange is a period delta and
    must not become pct_out.
    """
    holders = names if names is not None else [f"Named Filer {i:03d} LP" for i in range(1, n + 1)]
    if len(holders) != n:
        raise AssertionError("names length must match n")
    return pd.DataFrame(
        {
            "Date Reported": pd.to_datetime(["2026-06-30"] * n),
            "Holder": holders,
            "pctHeld": [0.0823 - i * 0.00005 for i in range(n)],
            "Shares": [1_000_000 + i for i in range(1, n + 1)],
            "Value": [35_000_000.0 + i for i in range(n)],
            "pctChange": [0.012 if i % 2 == 0 else -0.05 for i in range(n)],
        }
    )


def test_ownership_returns_all_234_real_rows_and_reported_count():
    # Live Ticker.info does not include institutionsCount — only major_holders index.
    ticker = _FakeTicker(
        info={
            "heldPercentInstitutions": 0.624,
            "heldPercentInsiders": 0.081,
            "sharesOutstanding": 400_000_000,
            "currentPrice": 35.0,
        },
        institutional_holders=_yf_inst_holders(234),
        major_holders=_yf_major_holders(234),
    )

    payload = financial_data.get_ownership_payload("INFQ", ticker=ticker)

    holders = payload["top_institutions"]
    assert len(holders) == 234
    assert payload["institutions_count"] == 234
    names = [row["holder"] for row in holders]
    assert names[0] == "Named Filer 001 LP"
    assert names[-1] == "Named Filer 234 LP"
    assert PAD_HOLDER_NAMES.isdisjoint(names)
    assert all(not name.startswith("Vanguard") for name in names)
    # pctHeld=0.0823 → 8.23; pctChange=0.012 must not win (that would be 1.2).
    assert holders[0]["pct_out"] == 8.23
    assert holders[0]["pct_out"] != 1.2
    assert holders[0]["change_pct"] == 1.2
    assert holders[1]["change_pct"] == -5.0
    expected_delta_0 = int(round(1_000_001 * 0.012 / 1.012))
    expected_delta_1 = int(round(1_000_002 * -0.05 / 0.95))
    assert holders[0]["change_shares"] == expected_delta_0
    assert holders[1]["change_shares"] == expected_delta_1
    assert holders[0]["change_pct"] != holders[0]["pct_out"]


def test_ownership_does_not_pad_short_or_empty_yahoo_tables():
    three = _yf_inst_holders(3, ["Alpha Capital LP", "Beta Trust Co", "Gamma Advisors LLC"])
    ticker = _FakeTicker(
        info={"heldPercentInstitutions": 0.71},
        institutional_holders=three,
        major_holders=_yf_major_holders(243),
    )
    payload = financial_data.get_ownership_payload("INFQ", ticker=ticker)
    names = [row["holder"] for row in payload["top_institutions"]]
    assert names == ["Alpha Capital LP", "Beta Trust Co", "Gamma Advisors LLC"]
    assert len(payload["top_institutions"]) == 3
    assert payload["institutions_count"] == 243
    assert PAD_HOLDER_NAMES.isdisjoint(names)
    assert payload["top_institutions"][0]["pct_out"] == 8.23
    # Odd row pctChange is -0.05; if that won, pct_out would be -5.0.
    second_held = (0.0823 - 0.00005) * 100
    assert payload["top_institutions"][1]["pct_out"] == financial_data._safe_round(second_held, 2)
    assert payload["top_institutions"][1]["pct_out"] != -5.0

    empty = _FakeTicker(
        info={},
        institutional_holders=pd.DataFrame(),
        major_holders=_yf_major_holders(243),
    )
    empty_payload = financial_data.get_ownership_payload("INFQ", ticker=empty)
    assert empty_payload["top_institutions"] == []
    assert empty_payload["institutions_count"] == 243
    assert empty_payload["top_funds"] == []


def test_ownership_no_pad_when_yfinance_raises():
    class _BoomTicker:
        @property
        def info(self):
            raise RuntimeError("Simulated Upstream YFinance Outage / Rate Limit")

        @property
        def institutional_holders(self):
            raise RuntimeError("Simulated Upstream YFinance Outage / Rate Limit")

        @property
        def mutualfund_holders(self):
            raise RuntimeError("Simulated Upstream YFinance Outage / Rate Limit")

        @property
        def major_holders(self):
            raise RuntimeError("Simulated Upstream YFinance Outage / Rate Limit")

    payload = financial_data.get_ownership_payload("INFQ", ticker=_BoomTicker())
    assert payload["symbol"] == "INFQ"
    assert payload["top_institutions"] == []
    assert payload["top_funds"] == []
    assert payload.get("institutions_count") is None
    names = [row.get("holder") for row in payload["top_institutions"]]
    assert PAD_HOLDER_NAMES.isdisjoint(names)


def test_ownership_missing_pct_held_falls_back_to_shares_over_outstanding():
    """Missing pctHeld → shares / outstanding. pctChange stays last-quarter change."""
    df = pd.DataFrame(
        {
            "Date Reported": pd.to_datetime(["2026-06-30"]),
            "Holder": ["No Pct Capital LP"],
            "Shares": [40_000_000],
            "Value": [520_000_000.0],
            "pctChange": [0.012],
        }
    )
    ticker = _FakeTicker(
        info={
            "heldPercentInstitutions": 0.624,
            "sharesOutstanding": 400_000_000,
            "currentPrice": 13.0,
        },
        institutional_holders=df,
        major_holders=_yf_major_holders(243),
    )
    payload = financial_data.get_ownership_payload("INFQ", ticker=ticker)
    row = payload["top_institutions"][0]
    assert row["holder"] == "No Pct Capital LP"
    assert row["shares"] == 40_000_000
    assert row["pct_out"] == 10.0
    assert row["pct_out"] != 1.2
    assert row["change_pct"] == 1.2
    assert row["change_shares"] == int(round(40_000_000 * 0.012 / 1.012))
    assert payload["institutions_count"] == 243


def test_ownership_share_change_column_and_funds_change_fields():
    inst = pd.DataFrame(
        {
            "Date Reported": pd.to_datetime(["2026-06-30"]),
            "Holder": ["Share Delta Advisors"],
            "pctHeld": [0.05],
            "Shares": [20_000_000],
            "Value": [260_000_000.0],
            "sharesChange": [1_500_000],
        }
    )
    funds = pd.DataFrame(
        {
            "Date Reported": pd.to_datetime(["2026-06-30"]),
            "Holder": ["iShares Russell 2000 ETF"],
            "pctHeld": [0.0137],
            "Shares": [3_077_954],
            "Value": [39_580_000.0],
            "pctChange": [0.08],
        }
    )
    ticker = _FakeTicker(
        info={"sharesOutstanding": 400_000_000, "currentPrice": 13.0},
        institutional_holders=inst,
        mutualfund_holders=funds,
        major_holders=_yf_major_holders(12),
    )
    payload = financial_data.get_ownership_payload("INFQ", ticker=ticker)
    inst_row = payload["top_institutions"][0]
    assert inst_row["pct_out"] == 5.0
    assert inst_row["change_shares"] == 1_500_000
    assert "change_pct" not in inst_row

    fund_row = payload["top_funds"][0]
    assert fund_row["holder"] == "iShares Russell 2000 ETF"
    assert fund_row["pct_out"] == 1.37
    assert fund_row["change_pct"] == 8.0
    assert fund_row["change_shares"] == int(round(3_077_954 * 0.08 / 1.08))


def test_parse_holder_rows_never_assigns_pct_change_to_pct_out():
    """Direct parse of the shipped function: pctChange is change, not outstanding."""
    df = _yf_inst_holders(3, ["Alpha Capital LP", "Beta Trust Co", "Gamma Advisors LLC"])
    rows = financial_data.parse_holder_rows(df, current_px=35.0, shares_outstanding=400_000_000)
    assert len(rows) == 3
    assert rows[0]["pct_out"] == 8.23
    assert rows[0]["change_pct"] == 1.2
    assert rows[1]["pct_out"] != -5.0
    assert rows[1]["change_pct"] == -5.0


def _nasdaq_holdings_json(n: int, names: list[str] | None = None) -> dict:
    holders = names if names is not None else [f"Named Filer {i:03d} LP" for i in range(1, n + 1)]
    if len(holders) != n:
        raise AssertionError("names length must match n")
    rows = []
    for i, name in enumerate(holders):
        if i % 3 == 0:
            change_pct, change_shares = "New", f"{1_000_000 + i:,}"
        elif i % 3 == 1:
            change_pct, change_shares = "-5.0%", f"-{500 + i:,}"
        else:
            change_pct, change_shares = "12.5%", f"{1_200 + i:,}"
        rows.append(
            {
                "ownerName": name,
                "date": "6/30/2026",
                "sharesHeld": f"{1_000_000 + i:,}",
                "sharesChange": change_shares,
                "sharesChangePCT": change_pct,
                "marketValue": f"${35_000 + i:,}",
            }
        )
    return {
        "data": {
            "ownershipSummary": {
                "SharesOutstandingPCT": {"label": "Institutional Ownership", "value": "42.11%"},
                "ShareoutstandingTotal": {"label": "Total Shares Outstanding (millions)", "value": "218"},
            },
            "holdingsTransactions": {
                "totalRecords": str(n),
                "institutionalHolders": f"{n} Institutional Holders",
                "table": {
                    "headers": {
                        "ownerName": "Owner Name",
                        "sharesHeld": "Shares Held",
                        "sharesChange": "Change (Shares)",
                        "sharesChangePCT": "Change (%)",
                        "marketValue": "Value (In 1,000s)",
                    },
                    "rows": rows,
                },
            },
        }
    }


def test_nasdaq_parse_returns_all_280_named_rows_with_quarter_change():
    blob = _nasdaq_holdings_json(280)
    parsed = financial_data.parse_nasdaq_holdings_payload(
        blob,
        current_px=13.0,
        shares_outstanding=218_000_000,
    )
    assert len(parsed["institutions"]) == 280
    assert parsed["institutions_count"] == 280
    first = parsed["institutions"][0]
    assert first["holder"] == "Named Filer 001 LP"
    assert first["shares"] == 1_000_000
    assert first["change_label"] == "New"
    assert first["change_shares"] == 1_000_000
    assert first["pct_out"] == financial_data._safe_round(1_000_000 / 218_000_000 * 100.0, 2)
    assert first["value"] == 35_000_000.0
    second = parsed["institutions"][1]
    assert second["change_pct"] == -5.0
    assert second["pct_out"] != -5.0
    assert parsed["institutions"][-1]["holder"] == "Named Filer 280 LP"


def test_ownership_prefers_nasdaq_full_list_over_yahoo_top_n():
    yahoo = _FakeTicker(
        info={"sharesOutstanding": 218_000_000, "currentPrice": 13.0, "heldPercentInstitutions": 0.4211},
        institutional_holders=_yf_inst_holders(10),
        major_holders=_yf_major_holders(285),
    )
    payload = financial_data.get_ownership_payload(
        "INFQ",
        ticker=yahoo,
        nasdaq_json=_nasdaq_holdings_json(280),
    )
    assert len(payload["top_institutions"]) == 280
    assert payload["institutions_count"] == 285
    assert payload["holders_source"] == "nasdaq_institutional_holdings"
    assert payload["top_institutions"][0]["holder"] == "Named Filer 001 LP"
    assert payload["top_institutions"][-1]["holder"] == "Named Filer 280 LP"
    # Last-quarter change travels with the Nasdaq row; pctChange must not become pct_out.
    assert payload["top_institutions"][1]["change_pct"] == -5.0
    assert payload["top_institutions"][1]["pct_out"] != -5.0


def test_yahoo_only_inject_still_skips_nasdaq_network():
    """Existing tests inject a ticker and must not require Nasdaq."""
    ticker = _FakeTicker(
        info={"heldPercentInstitutions": 0.624, "sharesOutstanding": 400_000_000, "currentPrice": 35.0},
        institutional_holders=_yf_inst_holders(234),
        major_holders=_yf_major_holders(234),
    )
    payload = financial_data.get_ownership_payload("INFQ", ticker=ticker)
    assert len(payload["top_institutions"]) == 234
    assert payload["holders_source"] == "yahoo"
