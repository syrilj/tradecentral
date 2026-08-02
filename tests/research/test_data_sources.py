"""Tests for the shared FINRA short-volume loader.

The mandatory regression this file exists to enforce (plan Issue 3A / P1-3):
`load_finra_short_vol()` must raise, never return `None`, when no data
source resolves. Before this fix, `build_pead_factor_hybrid.py` carried its
own copy of this loader pointed at a path that has never existed
(`edge/data/finra_short_vol.csv`), the miss was swallowed by
`except Exception: pass`, and `short_pressure` silently collapsed to a
constant multiplier while `GATE_PEAD_HYBRID_RESULT.md` went on being
generated as though the feature were included. See
edge/docs/LOOKAHEAD_CORRECTION.md.

Every test here monkeypatches the module's path constants rather than
touching real files under edge/data/ — this repo's real
edge/data/finra_shortvol/ currently holds only the raw, ungaggregated FINRA
mirror (see test_error_message_mentions_unaggregated_raw_mirror_when_present),
so these tests must not assume a processed CSV exists on disk.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from edge.tools import data_sources


def _point_at_empty_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Redirect the loader's search paths into an empty temp directory."""
    finra_dir = tmp_path / "finra_shortvol"
    finra_dir.mkdir(parents=True, exist_ok=True)
    canonical = finra_dir / "short_vol.csv"
    legacy = tmp_path / "finra_short_vol.csv"
    monkeypatch.setattr(data_sources, "_FINRA_DIR", finra_dir)
    monkeypatch.setattr(data_sources, "_FINRA_CANONICAL_CSV", canonical)
    monkeypatch.setattr(data_sources, "_FINRA_LEGACY_CSV", legacy)
    return canonical, legacy


def _write_valid_csv(path: Path, *, short_ratio_value: float) -> None:
    pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "symbol": ["AAA", "AAA"],
        "short_ratio": [short_ratio_value, short_ratio_value + 0.02],
    }).to_csv(path, index=False)


def test_load_finra_short_vol_raises_when_no_path_resolves(tmp_path, monkeypatch) -> None:
    """THE mandatory regression test: no candidate on disk -> raise, not None.

    edge/docs/LOOKAHEAD_CORRECTION.md and the plan both call this out by
    name: 'load_finra_short_vol() must raise when no data path resolves. It
    currently returns None silently.' It must not, ever again.
    """
    _point_at_empty_dir(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError, match="FINRA short-volume data NOT FOUND"):
        data_sources.load_finra_short_vol()


def test_raises_even_when_finra_dir_itself_is_absent(tmp_path, monkeypatch) -> None:
    """The old bug's exact shape: the directory the fetcher writes to does
    not exist at all yet on a fresh checkout. Still a raise, not None."""
    finra_dir = tmp_path / "nonexistent" / "finra_shortvol"
    monkeypatch.setattr(data_sources, "_FINRA_DIR", finra_dir)
    monkeypatch.setattr(data_sources, "_FINRA_CANONICAL_CSV", finra_dir / "short_vol.csv")
    monkeypatch.setattr(data_sources, "_FINRA_LEGACY_CSV", tmp_path / "finra_short_vol.csv")
    with pytest.raises(FileNotFoundError, match="FINRA short-volume data NOT FOUND"):
        data_sources.load_finra_short_vol()


def test_loads_from_canonical_path(tmp_path, monkeypatch) -> None:
    canonical, _legacy = _point_at_empty_dir(monkeypatch, tmp_path)
    _write_valid_csv(canonical, short_ratio_value=0.40)

    result = data_sources.load_finra_short_vol()

    assert isinstance(result, pd.Series)
    assert result.index.names == ["date", "symbol"]
    assert result.loc[(pd.Timestamp("2024-01-02"), "AAA")] == pytest.approx(0.40)


def test_canonical_path_takes_precedence_over_legacy(tmp_path, monkeypatch) -> None:
    """Deterministic precedence when both exist: the new directory wins."""
    canonical, legacy = _point_at_empty_dir(monkeypatch, tmp_path)
    _write_valid_csv(canonical, short_ratio_value=0.11)
    _write_valid_csv(legacy, short_ratio_value=0.99)

    result = data_sources.load_finra_short_vol()

    assert result.loc[(pd.Timestamp("2024-01-02"), "AAA")] == pytest.approx(0.11)


def test_falls_back_to_legacy_path_when_canonical_is_absent(tmp_path, monkeypatch) -> None:
    canonical, legacy = _point_at_empty_dir(monkeypatch, tmp_path)
    assert not canonical.exists()
    _write_valid_csv(legacy, short_ratio_value=0.77)

    result = data_sources.load_finra_short_vol()

    assert result.loc[(pd.Timestamp("2024-01-02"), "AAA")] == pytest.approx(0.77)


def test_malformed_candidate_is_skipped_not_treated_as_success(tmp_path, monkeypatch) -> None:
    """A file that exists but lacks a required column must not be silently
    accepted as a hit, and must not silently end the search either — the
    next candidate still gets a chance."""
    canonical, legacy = _point_at_empty_dir(monkeypatch, tmp_path)
    pd.DataFrame({"date": ["2024-01-02"], "symbol": ["AAA"]}).to_csv(canonical, index=False)
    _write_valid_csv(legacy, short_ratio_value=0.55)

    result = data_sources.load_finra_short_vol()

    assert result.loc[(pd.Timestamp("2024-01-02"), "AAA")] == pytest.approx(0.55)


def test_error_message_names_every_attempted_path(tmp_path, monkeypatch) -> None:
    canonical, legacy = _point_at_empty_dir(monkeypatch, tmp_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        data_sources.load_finra_short_vol()

    message = str(excinfo.value)
    assert str(canonical) in message
    assert str(legacy) in message


def test_error_message_mentions_unaggregated_raw_mirror_when_present(tmp_path, monkeypatch) -> None:
    """This repo's actual edge/data/finra_shortvol/ holds only raw daily
    CNMSshvol*.txt.gz mirror files today, not a processed CSV — the raised
    message should say so rather than leaving an operator to guess why a
    directory full of real FINRA files still produced 'NOT FOUND'."""
    _point_at_empty_dir(monkeypatch, tmp_path)
    raw_dir = data_sources._FINRA_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "CNMSshvol20240102.txt.gz").write_bytes(b"")

    with pytest.raises(FileNotFoundError, match="raw daily FINRA mirror files"):
        data_sources.load_finra_short_vol()
