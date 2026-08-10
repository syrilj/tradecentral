from __future__ import annotations

import pandas as pd

from edge.tools import fetch_smallcap_universe as fsu


NASDAQ_SAMPLE = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "AAAA|Alpha Test Co|Q|N|N|100|N|N\n"
    "BBBB|Beta ETF|Q|N|N|100|Y|N\n"
    "CCCC|Gamma Test Issue|Q|Y|N|100|N|N\n"
    "File Creation Time: 0801202608:00\n"
)


def test_parse_symbol_directory_excludes_etf_and_test_issue():
    symbols = fsu._parse_symbol_directory(NASDAQ_SAMPLE, symbol_col="Symbol", exchange_note="nasdaqlisted")
    assert symbols == ["AAAA"]


def test_normalize_renames_adj_close_and_lowercases():
    df = pd.DataFrame(
        {"Open": [1.0], "High": [1.1], "Low": [0.9], "Adj Close": [1.05], "Volume": [1000]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    out = fsu._normalize(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["close"].iloc[0] == 1.05


def test_normalize_trims_to_lookback_window():
    idx = pd.date_range("2026-01-01", periods=200, freq="B")
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100}, index=idx
    )
    out = fsu._normalize(df)
    assert len(out) == fsu.LOOKBACK_SESSIONS


def test_maybe_write_keeps_existing_when_new_pull_is_smaller(tmp_path):
    path = tmp_path / "AAAA.parquet"
    big = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1, 2]})
    small = big.iloc[:1]
    fsu.maybe_write(path, big, force=False)
    status = fsu.maybe_write(path, small, force=False)
    assert status == "kept_existing"
    assert len(pd.read_parquet(path)) == 2


def test_maybe_write_force_overwrites_with_smaller(tmp_path):
    path = tmp_path / "AAAA.parquet"
    big = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1, 2]})
    small = big.iloc[:1]
    fsu.maybe_write(path, big, force=False)
    status = fsu.maybe_write(path, small, force=True)
    assert status == "written"
    assert len(pd.read_parquet(path)) == 1
