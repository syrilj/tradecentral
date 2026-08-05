"""
Unit tests for Workstream 5: Point-In-Time Historical Universe Engine.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

try:
    from edge.research.universe import InstrumentMaster, UniverseConfig, get_universe
except ImportError:
    from research.universe import InstrumentMaster, UniverseConfig, get_universe


def _make_dummy_master() -> list[InstrumentMaster]:
    return [
        InstrumentMaster(
            instrument_id="INST_AAPL_001",
            ticker="AAPL",
            exchange="NASDAQ",
            listing_date=pd.Timestamp("1980-12-12"),
            delisting_date=None,
            effective_from=pd.Timestamp("1980-12-12"),
            effective_to=pd.Timestamp("2099-12-31"),
            sector="Technology",
            industry="Consumer Electronics",
            share_class="Common",
            tradable=True,
        ),
        InstrumentMaster(
            instrument_id="INST_ENRON_001",
            ticker="ENE",
            exchange="NYSE",
            listing_date=pd.Timestamp("1985-01-01"),
            delisting_date=pd.Timestamp("2001-12-02"),
            effective_from=pd.Timestamp("1985-01-01"),
            effective_to=pd.Timestamp("2001-12-02"),
            sector="Energy",
            industry="Oil & Gas",
            share_class="Common",
            tradable=True,
        ),
        InstrumentMaster(
            instrument_id="INST_NEWCO_001",
            ticker="NWCO",
            exchange="NASDAQ",
            listing_date=pd.Timestamp("2026-06-01"),
            delisting_date=None,
            effective_from=pd.Timestamp("2026-06-01"),
            effective_to=pd.Timestamp("2099-12-31"),
            sector="Technology",
            industry="Software",
            share_class="Common",
            tradable=True,
        ),
    ]


def test_future_listing_is_excluded():
    master = _make_dummy_master()
    decision_ts = pd.Timestamp("2026-03-01")
    univ = get_universe(master, market_data={}, decision_ts=decision_ts)

    tickers = [i.ticker for i in univ]
    assert "AAPL" in tickers
    assert "NWCO" not in tickers  # Listed in June 2026; decision is March 2026


def test_delisted_stock_included_before_delisting_excluded_after():
    master = _make_dummy_master()

    # Before delisting: 2000-01-01 -> ENE present
    univ_2000 = get_universe(master, market_data={}, decision_ts=pd.Timestamp("2000-01-01"))
    assert "ENE" in [i.ticker for i in univ_2000]

    # After delisting: 2002-01-01 -> ENE excluded
    univ_2002 = get_universe(master, market_data={}, decision_ts=pd.Timestamp("2002-01-01"))
    assert "ENE" not in [i.ticker for i in univ_2002]


def test_trailing_liquidity_and_price_filters():
    master = _make_dummy_master()
    dates = pd.bdate_range("2026-01-01", periods=30)
    
    # AAPL has price 150, volume 1M -> ADV 150M -> PASS
    df_aapl = pd.DataFrame({"timestamps": dates, "close": 150.0, "volume": 1_000_000.0})
    
    # Low price stock (price 2.0 < min_price 5.0) -> FAIL
    master_penny = InstrumentMaster(
        instrument_id="INST_PENNY_001",
        ticker="PENNY",
        exchange="NASDAQ",
        listing_date=pd.Timestamp("2020-01-01"),
        delisting_date=None,
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2099-12-31"),
        sector="Technology",
        industry="Software",
        share_class="Common",
        tradable=True,
    )
    df_penny = pd.DataFrame({"timestamps": dates, "close": 2.0, "volume": 100_000.0})

    market_data = {"AAPL": df_aapl, "PENNY": df_penny}
    all_master = master + [master_penny]

    cfg = UniverseConfig(min_price=5.0, min_adv=1_000_000.0, lookback_days=20)
    univ = get_universe(all_master, market_data=market_data, decision_ts=dates[-1], config=cfg)

    tickers = [i.ticker for i in univ]
    assert "AAPL" in tickers
    assert "PENNY" not in tickers
