"""Comprehensive Adversarial Stress Test Suite for Financial Intelligence Endpoints.

Tests:
1. Valid symbols (AAPL, MSFT, NVDA, TSLA, ASTS, SPY) across all 7 endpoints.
2. Invalid symbols, malformed symbols, unicode, emojis, SQLi, path traversal, empty strings (both URL-encoded and raw).
3. Edge cases in query parameters (period, window, symbols list, limit, force).
4. Schema and Typed Contract verification across all responses.
5. Simulated upstream exceptions (yfinance network failure, timeout, 429) verifying deterministic fallback.
6. Absolute guarantee of zero unhandled 500 server crashes.
"""
from __future__ import annotations

import json
import math
import urllib.parse
from typing import TYPE_CHECKING
from unittest.mock import patch
import pytest

from tools import financial_data

if TYPE_CHECKING:
    from tests.e2e.conftest import DirectApiClient


# List of endpoints requiring 'symbol' param
STOCK_INTELLIGENCE_ENDPOINTS = [
    "/api/financials",
    "/api/company-profile",
    "/api/insiders",
    "/api/government",
    "/api/ownership",
]

VALID_SYMBOLS = ["ASTS", "AAPL", "NVDA", "MSFT", "TSLA", "SPY"]


# --------------------------------------------------------------------------
# 1. Valid Symbols Contract & Field Integrity
# --------------------------------------------------------------------------
@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
@pytest.mark.parametrize("period", ["quarterly", "annual"])
def test_financials_valid_symbols_contract(api_client: DirectApiClient, symbol: str, period: str):
    res = api_client.get(f"/api/financials?symbol={symbol}&period={period}")
    assert res.status_code == 200, f"Failed for {symbol} ({period}): {res.text}"
    data = res.json()
    assert data["symbol"] == symbol
    assert data["period_type"] == period
    assert isinstance(data["periods"], list)
    # No assertion that periods is non-empty. When the provider returns no
    # fundamentals the payload is empty and says so; it used to be filled with
    # statements synthesised from the ticker string, and asserting non-empty
    # here is what required that fabrication to exist.
    if data.get("available") is False:
        assert data["periods"] == []
        assert data["income_statement"]["rows"] == []
        assert data["source"] == "unavailable"
        assert data["reason"]
    assert "income_statement" in data and isinstance(data["income_statement"]["rows"], list)
    assert "balance_sheet" in data and isinstance(data["balance_sheet"]["rows"], list)
    assert "cash_flow" in data and isinstance(data["cash_flow"]["rows"], list)
    assert "revenue_breakdown" in data
    assert "ratios" in data and isinstance(data["ratios"], dict)
    assert "source" in data
    assert "asof" in data

    # Check that rows contain valid types and no NaNs
    for section in ["income_statement", "balance_sheet", "cash_flow"]:
        for row in data[section]["rows"]:
            assert "label" in row
            assert "values" in row
            assert isinstance(row["values"], list)
            for v in row["values"]:
                if v is not None:
                    assert isinstance(v, (int, float))
                    assert math.isfinite(v)


@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
def test_company_profile_valid_symbols_contract(api_client: DirectApiClient, symbol: str):
    res = api_client.get(f"/api/company-profile?symbol={symbol}")
    assert res.status_code == 200, f"Failed for {symbol}: {res.text}"
    data = res.json()
    assert data["symbol"] == symbol
    assert "about" in data
    assert "name" in data["about"]
    assert "description" in data["about"]
    assert "officers" in data and isinstance(data["officers"], list)
    assert "compensation" in data and isinstance(data["compensation"]["rows"], list)
    assert "forecast" in data and isinstance(data["forecast"], dict)
    assert "smart_score" in data and isinstance(data["smart_score"], dict)
    # None when too few pillars were measured to compose a score. Pillars used
    # to fall back to rng.normal(), which made a partly-invented score
    # indistinguishable from a measured one.
    _score = data["smart_score"]["score"]
    assert _score is None or 1 <= _score <= 10
    assert "bull_bear" in data
    assert isinstance(data["bull_bear"]["bulls_say"], list)
    assert isinstance(data["bull_bear"]["bears_say"], list)
    assert "source" in data


@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
def test_insiders_valid_symbols_contract(api_client: DirectApiClient, symbol: str):
    res = api_client.get(f"/api/insiders?symbol={symbol}")
    assert res.status_code == 200, f"Failed for {symbol}: {res.text}"
    data = res.json()
    assert data["symbol"] == symbol
    assert "transactions" in data and isinstance(data["transactions"], list)
    # Not asserted non-empty: a symbol the provider has no Form 4 rows for
    # used to be padded with 16 invented filings attributed to real named
    # executives. Empty is the correct answer there.
    if not data["transactions"]:
        assert data.get("available") is False
        assert data["source"] == "unavailable"
    for tx in data["transactions"]:
        assert "date" in tx
        assert "insider_name" in tx
        assert "transaction_type" in tx
        assert "shares" in tx
        assert "value" in tx
    assert "quarterly_net" in data and isinstance(data["quarterly_net"], list)
    assert "summary" in data
    # `strategy` is absent unless a real backtest produced it. It used to be a
    # fixed block -- CAGR 28.4%, Sharpe 1.84, win rate 68.2% -- identical for
    # every symbol, from no backtest at all.
    if "strategy" in data:
        assert data["strategy"].get("cagr") is not None
        assert data["strategy"].get("sharpe") is not None


@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
def test_government_valid_symbols_contract(api_client: DirectApiClient, symbol: str):
    res = api_client.get(f"/api/government?symbol={symbol}")
    assert res.status_code == 200, f"Failed for {symbol}: {res.text}"
    data = res.json()
    assert data["symbol"] == symbol
    assert "congress" in data and isinstance(data["congress"], list)
    # Explicitly NOT asserted non-empty. This assertion is what kept the
    # fabricated congressional-trade generator alive: invented trades, dates
    # and dollar brackets attributed to real, named, living members of
    # Congress, each stamped with a real disclosures-clerk.house.gov URL.
    # No disclosure feed is wired up, so the honest answer is an empty list.
    assert data["congress"] == []
    assert data.get("available") is False
    assert data["source"] == "unavailable"
    assert data["reason"]
    assert "lobbying" in data and isinstance(data["lobbying"], dict)
    assert "history" in data["lobbying"]
    assert "contracts" in data and isinstance(data["contracts"], list)
    assert "patents" in data and isinstance(data["patents"], list)
    assert data["contracts"] == []
    assert data["patents"] == []


@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
def test_ownership_valid_symbols_contract(api_client: DirectApiClient, symbol: str):
    res = api_client.get(f"/api/ownership?symbol={symbol}")
    assert res.status_code == 200, f"Failed for {symbol}: {res.text}"
    data = res.json()
    assert data["symbol"] == symbol
    assert "breakdown" in data
    assert "institutional_pct" in data["breakdown"]
    assert "insider_pct" in data["breakdown"]
    assert "retail_float_pct" in data["breakdown"]
    assert "top_institutions" in data and isinstance(data["top_institutions"], list)
    assert "institutions_count" in data
    if data.get("institutions_count") is not None:
        assert isinstance(data["institutions_count"], int)
        assert data["institutions_count"] >= 0
    assert "top_funds" in data and isinstance(data["top_funds"], list)
    assert "short_interest" in data and isinstance(data["short_interest"], dict)
    assert "days_to_cover" in data["short_interest"]


@pytest.mark.parametrize("symbol", VALID_SYMBOLS)
def test_sentiment_valid_symbols_contract(api_client: DirectApiClient, symbol: str):
    res = api_client.get(f"/api/sentiment?symbol={symbol}")
    assert res.status_code == 200, f"Failed for {symbol}: {res.text}"
    data = res.json()
    assert "symbol" in data or "composite" in data or "sec_activity" in data or "anomalies" in data


def test_sentiment_no_symbol_contract(api_client: DirectApiClient):
    res = api_client.get("/api/sentiment")
    assert res.status_code == 200
    data = res.json()
    assert "generated_at" in data or "composite" in data or "cot" in data


@pytest.mark.parametrize("window", ["1m", "3m", "6m", "1y", "all"])
def test_compare_valid_symbols_contract(api_client: DirectApiClient, window: str):
    res = api_client.get(f"/api/compare?symbols=AAPL,MSFT,NVDA&window={window}")
    assert res.status_code == 200
    data = res.json()
    assert "series" in data
    assert "stats" in data
    assert "window" in data


# --------------------------------------------------------------------------
# 2. Adversarial Inputs: Missing, Empty, and Whitespace Symbols
# --------------------------------------------------------------------------
@pytest.mark.parametrize("endpoint", STOCK_INTELLIGENCE_ENDPOINTS)
def test_missing_symbol_parameter_returns_400(api_client: DirectApiClient, endpoint: str):
    """Missing symbol parameter must return 400 Bad Request, not 500."""
    res = api_client.get(endpoint)
    assert res.status_code == 400, f"Expected 400 for {endpoint}, got {res.status_code}: {res.text}"
    data = res.json()
    assert "error" in data


@pytest.mark.parametrize("endpoint", STOCK_INTELLIGENCE_ENDPOINTS)
@pytest.mark.parametrize("empty_val", ["", "%20%20%20"])
def test_empty_symbol_parameter_returns_400(api_client: DirectApiClient, endpoint: str, empty_val: str):
    """Empty or whitespace-only symbol parameter must return 400 Bad Request, not 500."""
    res = api_client.get(f"{endpoint}?symbol={empty_val}")
    assert res.status_code == 400, f"Expected 400 for {endpoint}?symbol={empty_val}, got {res.status_code}: {res.text}"
    data = res.json()
    assert "error" in data


# --------------------------------------------------------------------------
# 3. Adversarial Inputs: Invalid, Path Traversal, SQLi, XSS, Unicode, Length
# --------------------------------------------------------------------------
ADVERSARIAL_SYMBOLS = [
    "../../etc/passwd",
    "../../secret",
    "AAPL;DROP TABLE quotes;",
    "<script>alert(1)</script>",
    "INVALID$$$TICKER",
    "TOOLONGSYMBOLNAMEOVER10CHARS",
    "AAPL%00NULLBYTE",
    "🍎🚀💰",
    "SPY/VIX",
    "A*B*C",
    "SYM WITH SPACE",
]


@pytest.mark.parametrize("endpoint", STOCK_INTELLIGENCE_ENDPOINTS)
@pytest.mark.parametrize("bad_sym", ADVERSARIAL_SYMBOLS)
def test_adversarial_symbols_sanitization(api_client: DirectApiClient, endpoint: str, bad_sym: str):
    """Adversarial/malicious symbol inputs must be rejected with 400, never cause 500 or security compromise."""
    encoded_sym = urllib.parse.quote(bad_sym)
    res = api_client.get(f"{endpoint}?symbol={encoded_sym}")
    assert res.status_code == 400, f"Expected 400 for {endpoint}?symbol={encoded_sym}, got {res.status_code}"
    data = res.json()
    assert "error" in data


@pytest.mark.parametrize("bad_sym", ADVERSARIAL_SYMBOLS)
def test_compare_adversarial_symbols_sanitization(api_client: DirectApiClient, bad_sym: str):
    encoded_sym = urllib.parse.quote(bad_sym)
    res = api_client.get(f"/api/compare?symbols=AAPL,{encoded_sym}")
    assert res.status_code == 400
    data = res.json()
    assert "error" in data


@pytest.mark.parametrize("bad_sym", ADVERSARIAL_SYMBOLS)
def test_sentiment_adversarial_symbols_sanitization(api_client: DirectApiClient, bad_sym: str):
    encoded_sym = urllib.parse.quote(bad_sym)
    res = api_client.get(f"/api/sentiment?symbol={encoded_sym}")
    assert res.status_code == 400
    data = res.json()
    assert "error" in data


# --------------------------------------------------------------------------
# 4. Unknown/Synthetic But Syntactically Valid Symbols Fallback Behavior
# --------------------------------------------------------------------------
UNKNOWN_VALID_SYNTAX_SYMBOLS = ["NONEXIST1", "ZZZZ", "SYNTH99", "UNKNOWN"]


@pytest.mark.parametrize("endpoint", STOCK_INTELLIGENCE_ENDPOINTS)
@pytest.mark.parametrize("sym", UNKNOWN_VALID_SYNTAX_SYMBOLS)
def test_unknown_valid_syntax_symbol_deterministic_fallback(api_client: DirectApiClient, endpoint: str, sym: str):
    """Unknown symbols with valid syntax (e.g. NONEXIST1) must return 200 with deterministic fallback, never 500."""
    res = api_client.get(f"{endpoint}?symbol={sym}")
    assert res.status_code == 200, f"Failed for {endpoint}?symbol={sym}: {res.text}"
    data = res.json()
    assert data["symbol"] == sym
    # Must be valid JSON without crash
    assert json.dumps(data) is not None


# --------------------------------------------------------------------------
# 5. /api/compare Edge Cases
# --------------------------------------------------------------------------
def test_compare_empty_symbols_returns_400(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=")
    assert res.status_code == 400
    assert "error" in res.json()


def test_compare_whitespace_symbols_returns_400(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=%20,%20")
    assert res.status_code == 400
    assert "error" in res.json()


def test_compare_single_symbol_success(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=AAPL")
    assert res.status_code == 200
    data = res.json()
    assert "AAPL" in data["series"] or "AAPL" in data["stats"]


def test_compare_duplicate_symbols_deduplicated(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=AAPL,AAPL,AAPL")
    assert res.status_code == 200
    data = res.json()
    assert len(data["series"]) == 1
    assert "AAPL" in data["series"]


def test_compare_max_eight_symbols_cap(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=AAPL,MSFT,NVDA,TSLA,SPY,QQQ,GOOG,AMZN,META,NFLX")
    assert res.status_code == 200
    data = res.json()
    # Ensure capped at max 8 symbols
    assert len(data.get("series", {})) <= 8


def test_compare_invalid_window_defaults_safely(api_client: DirectApiClient):
    res = api_client.get("/api/compare?symbols=AAPL,MSFT&window=invalid_window_xyz")
    # API server defaults gracefully or handles without 500
    assert res.status_code in (200, 400, 404)


# --------------------------------------------------------------------------
# 6. Simulated Upstream Offline / Exception Handling (Zero 500 Rule)
# --------------------------------------------------------------------------
def test_financials_graceful_when_yfinance_raises():
    """Simulate yfinance throwing ConnectionError, RateLimit (429), or Timeout."""
    with patch("yfinance.Ticker", side_effect=RuntimeError("Simulated Upstream YFinance Outage / Rate Limit")):
        payload = financial_data.get_financials_payload("ASTS_OFFLINE_TEST", period="quarterly")
        assert payload is not None
        assert payload["symbol"] == "ASTS_OFFLINE_TEST"
        # An upstream outage must not be papered over with synthetic
        # statements. Same rule the ownership test below already applies.
        assert payload["income_statement"]["rows"] == []
        assert payload["balance_sheet"]["rows"] == []
        assert payload["cash_flow"]["rows"] == []
        assert payload["available"] is False
        assert payload["source"] == "unavailable"


def test_company_profile_graceful_when_yfinance_raises():
    with patch("yfinance.Ticker", side_effect=RuntimeError("Simulated YFinance Outage")):
        payload = financial_data.get_company_profile_payload("ASTS_OFFLINE_TEST")
        assert payload is not None
        assert payload["symbol"] == "ASTS_OFFLINE_TEST"
        assert "about" in payload
        assert "forecast" in payload
        assert "smart_score" in payload


def test_insiders_graceful_when_yfinance_raises():
    with patch("yfinance.Ticker", side_effect=RuntimeError("Simulated YFinance Outage")):
        payload = financial_data.get_insiders_payload("ASTS_OFFLINE_TEST")
        assert payload is not None
        assert payload["symbol"] == "ASTS_OFFLINE_TEST"
        # An outage must not invent Form 4 filings for real executives.
        assert payload["transactions"] == []
        assert payload["available"] is False
        assert "quarterly_net" in payload


def test_ownership_graceful_when_yfinance_raises():
    with patch("yfinance.Ticker", side_effect=RuntimeError("Simulated YFinance Outage")), patch(
        "tools.financial_data.fetch_nasdaq_holdings_json",
        return_value=None,
    ):
        payload = financial_data.get_ownership_payload("ASTS_OFFLINE_TEST")
        assert payload is not None
        assert payload["symbol"] == "ASTS_OFFLINE_TEST"
        # Named rows are real filings only — an outage must not invent a 30-name pad.
        assert payload["top_institutions"] == []
        assert payload.get("institutions_count") is None
        assert "breakdown" in payload


def test_government_payload_reports_unavailable_rather_than_inventing():
    """The payload was 'deterministic' because it was seeded from the ticker.

    Determinism was never the property worth testing here -- it only made the
    fabrication stable across reloads, and therefore more convincing. What
    matters is that nothing is invented.
    """
    payload = financial_data.get_government_payload("ASTS_OFFLINE_TEST")
    assert payload is not None
    assert payload["symbol"] == "ASTS_OFFLINE_TEST"
    assert payload["available"] is False
    assert payload["congress"] == []
    assert payload["contracts"] == []
    assert payload["patents"] == []
    assert payload["lobbying"]["history"] == []
    assert payload["source"] == "unavailable"
