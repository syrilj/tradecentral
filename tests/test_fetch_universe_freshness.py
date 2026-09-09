"""A rolling-window pull must still be able to refresh a saturated file.

`fetch_universe.py` asks Yahoo for `period="10y"`. That window rolls, so once a
symbol owns ten years of history every later pull returns the same row count,
just shifted forward. The old guard was `len(new) <= len(old) -> keep`, which
made row count the freshness test -- so the file froze permanently while the
script reported "OK <old span> (kept_existing)". SPY served a 2026-09-01 close
for a week; only young listings still short of the window ever updated.
"""
from __future__ import annotations

import pandas as pd
import pytest

from edge.tools.fetch_universe import maybe_write

COLS = ["open", "high", "low", "close", "volume"]


def _frame(start: str, periods: int, base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame(
        {c: [base + i for i in range(periods)] for c in COLS},
        index=idx,
    )


class TestRollingWindowRefresh:
    def test_same_row_count_but_newer_bars_is_written(self, tmp_path):
        """The exact SPY case: 2512 rows either way, window shifted forward."""
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 100), force=False)
        shifted = _frame("2016-01-06", 100)  # same length, 5 days newer

        assert maybe_write(path, shifted, force=False) == "merged"

        on_disk = pd.read_parquet(path)
        assert on_disk.index.max() == shifted.index.max()

    def test_the_merge_gains_the_dropped_bars_instead_of_replacing_history(self, tmp_path):
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 100), force=False)
        maybe_write(path, _frame("2016-01-06", 100), force=False)

        on_disk = pd.read_parquet(path)
        # 100 original + 5 new, not 100 replaced by 100.
        assert len(on_disk) == 105
        assert str(on_disk.index.min())[:10] == "2016-01-01"

    def test_a_short_pull_never_truncates_a_long_history(self, tmp_path):
        """The protection the old guard existed to give, kept.

        A five-bar pull landing inside an existing 500-bar history must leave
        all 500 on disk -- the merge keeps history that the pull did not cover.
        """
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 500), force=False)
        maybe_write(path, _frame("2016-03-01", 5), force=False)

        assert len(pd.read_parquet(path)) == 500

    def test_nothing_new_is_reported_as_kept_existing(self, tmp_path):
        path = tmp_path / "SPY.parquet"
        df = _frame("2016-01-01", 50)
        maybe_write(path, df, force=False)
        assert maybe_write(path, df, force=False) == "kept_existing"

    def test_overlapping_bars_take_the_new_value(self, tmp_path):
        """Yahoo restates adjusted closes; the fresh pull must win."""
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 10, base=100.0), force=False)
        maybe_write(path, _frame("2016-01-01", 10, base=200.0), force=False)

        assert float(pd.read_parquet(path)["close"].iloc[0]) == pytest.approx(200.0)

    def test_an_empty_pull_leaves_the_file_alone(self, tmp_path):
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 50), force=False)
        assert maybe_write(path, pd.DataFrame(columns=COLS), force=False) == "kept_existing"
        assert len(pd.read_parquet(path)) == 50

    def test_force_still_overwrites_outright(self, tmp_path):
        path = tmp_path / "SPY.parquet"
        maybe_write(path, _frame("2016-01-01", 500), force=False)
        assert maybe_write(path, _frame("2020-01-01", 3), force=True) == "wrote"
        assert len(pd.read_parquet(path)) == 3
