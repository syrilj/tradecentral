"""Test suite for Government Intelligence data engine and regulatory feeds."""
from __future__ import annotations

import pytest
from tools import government_data, financial_data


def test_government_payload_tracked_symbol_nem():
    """Verify NEM produces authentic, rich government intelligence."""
    payload = financial_data.get_government_payload("NEM")
    assert payload["symbol"] == "NEM"
    assert payload["available"] is True
    assert payload["source"] == "regulatory_disclosures_sec_usaspending_uspto_lda"

    # G1: Congressional Trades
    congress = payload["congress"]
    assert isinstance(congress, list)
    assert len(congress) >= 2
    for c in congress:
        assert c["politician_name"]
        assert c["party"] in ("Democrat", "Republican")
        assert c["chamber"] in ("House", "Senate")
        assert c["state"]
        assert c["transaction_date"]
        assert c["filing_date"]
        assert c["type"] in ("Purchase", "Sale")
        assert c["amount_range"]
        assert c["source_url"].startswith("http")

    # G2: Corporate Lobbying
    lobbying = payload["lobbying"]
    assert isinstance(lobbying, dict)
    assert lobbying["estimated_quarterly_spend"] is not None
    assert lobbying["estimated_quarterly_spend"] > 0
    assert lobbying["total_spend_annual"] is not None
    assert lobbying["total_spend_annual"] > 0
    assert len(lobbying["history"]) >= 2
    assert len(lobbying["filings"]) >= 2
    for f in lobbying["filings"]:
        assert f["amount"] > 0
        assert f["date"]
        assert f["issue"]
        assert f["description"]
        assert f["registrant"]

    # G3: Federal Government Contracts
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    assert len(contracts) >= 2
    for con in contracts:
        assert con["agency"]
        assert con["date"]
        assert con["amount"] > 0
        assert con["contract_type"]
        assert con["description"]

    # G4: U.S. Patents
    patents = payload["patents"]
    assert isinstance(patents, list)
    assert len(patents) >= 2
    for p in patents:
        assert p["patent_number"]
        assert p["title"]
        assert p["grant_date"]
        assert p["abstract"]
        assert p.get("inventor")


@pytest.mark.parametrize("symbol", ["LMT", "PLTR", "ASTS", "AAPL", "NVDA"])
def test_government_payload_tracked_symbols_have_disclosures(symbol):
    """Verify major tracked symbols return valid, non-empty government data."""
    payload = financial_data.get_government_payload(symbol)
    assert payload["symbol"] == symbol
    assert payload["available"] is True
    assert payload["source"] == "regulatory_disclosures_sec_usaspending_uspto_lda"
    assert len(payload["congress"]) > 0
    assert payload["lobbying"]["total_spend_annual"] is not None
    assert len(payload["contracts"]) > 0
    assert len(payload["patents"]) > 0


def test_government_payload_unknown_symbol_reports_unavailable():
    """Verify unknown or unconfigured test symbols fail cleanly with available=False."""
    payload = financial_data.get_government_payload("NONEXISTENT_XYZ_123")
    assert payload["symbol"] == "NONEXISTENT_XYZ_123"
    assert payload["available"] is False
    assert payload["source"] == "unavailable"
    assert payload["congress"] == []
    assert payload["contracts"] == []
    assert payload["patents"] == []
    assert payload["lobbying"]["history"] == []
    assert payload["lobbying"]["filings"] == []
    assert payload["reason"]
