from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

from edge.tools import build_finra_short_panel as bfsp
from edge.tools import data_sources


def _write_raw_file(raw_dir: Path, date_str: str, rows: list[tuple[str, str, str, str, str]]) -> Path:
    path = raw_dir / f"CNMSshvol{date_str}.txt.gz"
    lines = ["Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"]
    for date, symbol, short_vol, short_exempt, total_vol in rows:
        lines.append(f"{date}|{symbol}|{short_vol}|{short_exempt}|{total_vol}|Q,N")
    lines.append(str(len(rows)))
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


class TestParseFinraDailyFile:
    def test_parses_valid_rows_and_skips_trailer(self, tmp_path):
        path = _write_raw_file(
            tmp_path,
            "20180801",
            [("20180801", "AAA", "100", "0", "1000"), ("20180801", "BBB", "50", "0", "200")],
        )
        df = bfsp.parse_finra_daily_file(path)
        assert list(df["symbol"]) == ["AAA", "BBB"]
        assert list(df["date"]) == ["2018-08-01", "2018-08-01"]
        assert list(df["short_volume"]) == [100.0, 50.0]
        assert list(df["total_volume"]) == [1000.0, 200.0]

    def test_skips_zero_total_volume_row(self, tmp_path):
        path = _write_raw_file(tmp_path, "20180801", [("20180801", "ZZZ", "5", "0", "0")])
        df = bfsp.parse_finra_daily_file(path)
        assert df.empty

    def test_skips_malformed_row(self, tmp_path):
        path = tmp_path / "CNMSshvol20180801.txt.gz"
        with gzip.open(path, "wt") as fh:
            fh.write("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n")
            fh.write("20180801|AAA|not_a_number|0|1000|Q,N\n")
            fh.write("20180801|BBB|50|0|200|Q,N\n")
            fh.write("1\n")
        df = bfsp.parse_finra_daily_file(path)
        assert list(df["symbol"]) == ["BBB"]

    def test_unreadable_file_returns_empty_frame_not_none(self, tmp_path):
        path = tmp_path / "not_actually_gzip.txt.gz"
        path.write_text("garbage")
        df = bfsp.parse_finra_daily_file(path)
        assert df is not None
        assert df.empty
        assert list(df.columns) == ["date", "symbol", "short_volume", "total_volume"]


class TestBuildShortPanel:
    def test_aggregates_multiple_files_into_canonical_columns(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_raw_file(raw_dir, "20180801", [("20180801", "AAA", "100", "0", "1000")])
        _write_raw_file(raw_dir, "20180802", [("20180802", "AAA", "50", "0", "500")])
        out_csv = tmp_path / "short_vol.csv"

        summary = bfsp.build_short_panel(raw_dir, out_csv)

        panel = pd.read_csv(out_csv)
        assert list(panel.columns) == ["date", "symbol", "short_ratio"]
        assert summary["n_days"] == 2
        assert summary["n_rows"] == 2
        assert pytest.approx(panel.loc[panel["date"] == "2018-08-01", "short_ratio"].iloc[0]) == 0.1

    def test_multi_row_same_symbol_day_sums_before_ratio(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        path = raw_dir / "CNMSshvol20180801.txt.gz"
        with gzip.open(path, "wt") as fh:
            fh.write("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n")
            fh.write("20180801|AAA|100|0|1000|Q\n")
            fh.write("20180801|AAA|50|0|500|N\n")
            fh.write("2\n")
        out_csv = tmp_path / "short_vol.csv"

        bfsp.build_short_panel(raw_dir, out_csv)

        panel = pd.read_csv(out_csv)
        assert len(panel) == 1
        assert pytest.approx(panel["short_ratio"].iloc[0]) == 150.0 / 1500.0

    def test_incremental_only_parses_new_dates(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_raw_file(raw_dir, "20180801", [("20180801", "AAA", "100", "0", "1000")])
        out_csv = tmp_path / "short_vol.csv"
        bfsp.build_short_panel(raw_dir, out_csv)

        _write_raw_file(raw_dir, "20180802", [("20180802", "AAA", "20", "0", "200")])
        summary = bfsp.build_short_panel(raw_dir, out_csv, incremental=True)

        assert summary["n_files"] == 1  # only the new day was parsed
        panel = pd.read_csv(out_csv)
        assert sorted(panel["date"].unique()) == ["2018-08-01", "2018-08-02"]

    def test_out_of_range_ratio_counted(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        # ShortVolume > TotalVolume is malformed data but should not crash the build.
        _write_raw_file(raw_dir, "20180801", [("20180801", "AAA", "2000", "0", "1000")])
        out_csv = tmp_path / "short_vol.csv"

        summary = bfsp.build_short_panel(raw_dir, out_csv)

        assert summary["out_of_range_ratio_count"] == 1

    def test_empty_raw_dir_produces_empty_panel_not_crash(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        out_csv = tmp_path / "short_vol.csv"

        summary = bfsp.build_short_panel(raw_dir, out_csv)

        assert summary["n_rows"] == 0
        assert out_csv.exists()


class TestLoadFinraShortVolContract:
    def test_round_trips_through_load_finra_short_vol(self, tmp_path, monkeypatch):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        _write_raw_file(raw_dir, "20180801", [("20180801", "AAA", "100", "0", "1000")])
        out_csv = tmp_path / "finra_shortvol" / "short_vol.csv"
        bfsp.build_short_panel(raw_dir, out_csv)

        monkeypatch.setattr(data_sources, "_finra_csv_candidates", lambda: [out_csv])

        series = data_sources.load_finra_short_vol()
        assert series.loc[(pd.Timestamp("2018-08-01"), "AAA")] == pytest.approx(0.1)
