"""Guard: `tools/financial_data.py` must not invent market or regulatory data.

An audit found this module fabricating, and serving to the dashboard as if
measured:

* congressional stock trades attributed to real, named, living members of
  Congress, with invented dates and dollar brackets, each stamped
  `source_url: https://disclosures-clerk.house.gov/`;
* SEC Form 4 insider filings attributed to real company officers;
* a fixed "Insider Purchases Strategy" backtest -- CAGR 28.4%, Sharpe 1.84,
  win rate 68.2% -- identical for every symbol, from no backtest at all;
* complete income statements, balance sheets and cash-flow statements;
* every valuation ratio, via `rng.uniform(...)` fallbacks;
* segment/geography revenue splits rendered under a "Source: SEC Form 10-K
  Notes" caption;
* real-format US patent numbers with invented titles and abstracts.

All of it was seeded from the ticker string, so it was stable across reloads
and therefore looked measured. Worse, it masked a real defect: the live
yfinance path raised `TypeError` on its first call and the enclosing
`except Exception` swallowed it at debug level, so *every* symbol had always
fallen through to the synthetic generator. Removing the fabrication is what
surfaced that bug.

These tests are cheap and blunt on purpose. The rule is not "use randomness
carefully" -- it is that a research surface reports what it measured, or
reports nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from edge.tools import financial_data

SOURCE = Path(financial_data.__file__).read_text(encoding="utf-8")


def test_module_has_no_random_number_generation():
    """No RNG at all. There is no legitimate use for one in this module."""
    offenders = [
        (i, line)
        for i, line in enumerate(SOURCE.splitlines(), 1)
        if re.search(r"\brng\s*\.|np\.random|random\.(random|uniform|choice|randint)", line)
        and not line.lstrip().startswith("#")
    ]
    assert offenders == [], f"randomness reintroduced: {offenders}"


def test_no_hardcoded_politician_names():
    """Named public officials must never appear in this module."""
    for name in (
        "Pelosi",
        "Tuberville",
        "McCaul",
        "Whitehouse",
        "Crenshaw",
        "Khanna",
    ):
        assert name not in SOURCE, f"real politician {name!r} hardcoded in payload source"


def test_no_invented_patent_numbers():
    """`US11985123B2`-shaped literals were invented and attributed to a real inventor."""
    assert re.search(r"US\d{7,8}[AB]\d", SOURCE) is None


def test_government_payload_reports_no_source_rather_than_inventing():
    payload = financial_data.get_government_payload("ZZTESTSYM")
    assert payload["available"] is False
    assert payload["congress"] == []
    assert payload["contracts"] == []
    assert payload["patents"] == []
    assert payload["lobbying"]["history"] == []
    assert payload["lobbying"]["filings"] == []
    assert payload["source"] == "unavailable"
    assert payload["reason"]


def test_revenue_breakdown_is_empty_without_a_segment_source():
    """Offline / unknown symbol -> honest empty result with the keys intact."""
    breakdown = financial_data._generate_revenue_breakdown("ZZTESTSYM", {}, 1_000_000.0)
    assert breakdown["by_segment"] == []
    assert breakdown["by_geography"] == []


def test_fallback_financials_are_empty_not_synthetic():
    payload = financial_data._generate_fallback_financials("ZZTESTSYM", "quarterly")
    assert payload["periods"] == []
    for section in ("income_statement", "balance_sheet", "cash_flow"):
        assert payload[section]["rows"] == [], section
    assert payload["ratios"] == {}
    assert payload["available"] is False
    assert payload["source"] == "unavailable"


def test_no_fixed_backtest_performance_constants():
    """The invented "Insider Purchases Strategy" numbers must not come back."""
    for literal in ("28.4", "42.6", "1.84", "68.2", "-14.2"):
        assert f": {literal}," not in SOURCE, f"fabricated performance constant {literal} present"


@pytest.mark.parametrize("symbol", ["ZZTESTSYM", "NONEXIST1"])
def test_unknown_symbols_never_produce_named_insider_filings(symbol):
    """An unknown ticker must not yield Form 4 rows naming anyone."""
    payload = financial_data.get_insiders_payload(symbol)
    assert payload["transactions"] == []
    assert payload["available"] is False
    assert "strategy" not in payload


def test_extract_row_signature_accepts_the_periods_argument():
    """Regression: the live yfinance path was dead for every symbol.

    `extract_row` took 3 positional parameters while all 16 call sites passed
    4, so the first call raised TypeError, the broad `except Exception` logged
    it at debug level, and the synthetic generator answered every request.
    Pin the call shape so the live path cannot silently die again.
    """
    assert "periods: list[str]," in SOURCE
    calls = re.findall(r"extract_row\(\s*\w+_df,", SOURCE)
    assert len(calls) >= 16, f"expected the full call set, found {len(calls)}"
