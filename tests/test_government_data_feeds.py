"""Test suite for Government Intelligence data engine and regulatory feeds.

This deployment wires no congressional-disclosure, lobbying, federal-contract
or patent feed: `government_data._save_disk_cache` has no callers, so nothing
ever writes the on-disk cache from a live source.

This file used to assert the opposite. It demanded that six seeded symbols
(NEM, LMT, PLTR, ASTS, AAPL, NVDA) return "authentic, rich government
intelligence" -- named politicians, parties, chambers, transaction and filing
dates, dollar brackets and http source_urls. The only thing that could satisfy
those assertions was the fabricated congressional-trade generator's leftover
cache file, which attributed invented securities trades to real, living members
of Congress and served them stamped `available: true`, `source:
regulatory_disclosures_sec_usaspending_uspto_lda`, with the current date as
asof. The test was therefore holding the fabrication in place: removing the
invented data made this suite fail.

What is worth pinning is the contract, in both directions: absent feeds report
absent, and a cache entry is only served when it carries real provenance.
"""
from __future__ import annotations

import pytest
from tools import government_data, financial_data


TRACKED_SYMBOLS = ["NEM", "LMT", "PLTR", "ASTS", "AAPL", "NVDA"]


@pytest.fixture(autouse=True)
def _clear_government_memo():
    """Drop both 15-minute in-process memos so each case sees its own cache stub.

    `financial_data.get_government_payload` memoises independently of
    `government_data.build_government_payload`, so clearing only one leaves the
    previous case's answer in front of this one.
    """
    government_data._MEM_CACHE.clear()
    financial_data._CACHE_GOVERNMENT.clear()
    yield
    government_data._MEM_CACHE.clear()
    financial_data._CACHE_GOVERNMENT.clear()


@pytest.mark.parametrize("symbol", TRACKED_SYMBOLS)
def test_government_payload_reports_absent_when_no_feed_is_configured(symbol):
    """With no disclosure feed wired, every symbol reports absent, not invented."""
    payload = financial_data.get_government_payload(symbol)
    assert payload["symbol"] == symbol
    assert payload["available"] is False
    assert payload["source"] == "unavailable"
    assert payload["reason"]
    assert payload["congress"] == []
    assert payload["contracts"] == []
    assert payload["patents"] == []
    assert payload["lobbying"]["history"] == []
    assert payload["lobbying"]["filings"] == []
    assert payload["lobbying"]["estimated_quarterly_spend"] is None
    assert payload["lobbying"]["total_spend_annual"] is None


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


def test_cache_entry_without_provenance_is_not_served(monkeypatch):
    """An unsourced cache entry must never be re-stamped as a regulatory disclosure.

    This is the exact shape the fabricated generator left behind: real content
    keys, no record of where any of it came from.
    """
    monkeypatch.setattr(
        government_data,
        "_load_disk_cache",
        lambda: {
            "AAPL": {
                "symbol": "AAPL",
                "congress": [{"politician_name": "Some Person", "party": "Democrat"}],
                "contracts": [{"agency": "DoD", "amount": 1}],
                "patents": [{"patent_number": "US1"}],
                "lobbying": {"total_spend_annual": 1, "history": [], "filings": []},
            }
        },
    )
    payload = financial_data.get_government_payload("AAPL")
    assert payload["available"] is False
    assert payload["source"] == "unavailable"
    assert payload["congress"] == []


def test_cache_entry_with_provenance_is_served(monkeypatch):
    """A entry stamped by a real fetcher is served, and keeps its source label."""
    monkeypatch.setattr(
        government_data,
        "_load_disk_cache",
        lambda: {
            "AAPL": {
                "symbol": "AAPL",
                "fetched_utc": "2026-09-01T00:00:00+00:00",
                "source_feed": "disclosures-clerk.house.gov",
                "congress": [
                    {
                        "politician_name": "Example Member",
                        "party": "Democrat",
                        "chamber": "House",
                        "state": "CA",
                        "transaction_date": "2026-08-01",
                        "filing_date": "2026-08-20",
                        "type": "Purchase",
                        "amount_range": "$1,001 - $15,000",
                        "source_url": "https://disclosures-clerk.house.gov/example",
                    }
                ],
                "contracts": [],
                "patents": [],
                "lobbying": {
                    "estimated_quarterly_spend": None,
                    "total_spend_annual": None,
                    "history": [],
                    "filings": [],
                },
            }
        },
    )
    payload = financial_data.get_government_payload("AAPL")
    assert payload["available"] is True
    assert payload["source"] == "regulatory_disclosures_sec_usaspending_uspto_lda"
    assert len(payload["congress"]) == 1
    assert payload["congress"][0]["source_url"].startswith("http")


def test_fetch_congress_trades_returns_empty_without_a_feed():
    """The reader has no live path: no fetcher writes the cache it reads."""
    assert government_data.fetch_congress_trades("AAPL") == []
