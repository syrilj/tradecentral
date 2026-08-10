from __future__ import annotations

import csv

from edge.tools import fetch_float_data as ffd


def test_load_float_data_missing_file_returns_empty_dict(tmp_path):
    assert ffd.load_float_data(tmp_path / "nope.csv") == {}


def test_load_float_data_round_trips_known_and_unknown_float(tmp_path):
    csv_path = tmp_path / "float.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ffd.FIELDS)
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "float_shares": 5_000_000, "shares_outstanding": 6_000_000, "as_of_date": "2026-08-06"})
        writer.writerow({"symbol": "BBB", "float_shares": "", "shares_outstanding": "", "as_of_date": "2026-08-06"})

    result = ffd.load_float_data(csv_path)
    assert result["AAA"] == 5_000_000.0
    assert result["BBB"] is None


def test_candidates_under_ceiling_filters_by_last_close(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(ffd, "SMALLCAP_DIR", tmp_path)
    cheap = pd.DataFrame({"close": [1.0, 5.0]}, index=pd.date_range("2026-01-01", periods=2))
    expensive = pd.DataFrame({"close": [1.0, 500.0]}, index=pd.date_range("2026-01-01", periods=2))
    cheap.to_parquet(tmp_path / "CHEAP.parquet")
    expensive.to_parquet(tmp_path / "EXPENSIVE.parquet")

    result = ffd.candidates_under_ceiling()
    assert result == ["CHEAP"]
