from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from edge.research.squeeze_validation import (
    SqueezeValidationConfig,
    _hit,
    _load_price,
    _score_train_oos,
)


def test_missing_forward_return_is_censored_not_counted_as_a_miss() -> None:
    assert _hit(25.0, None, 10.0) is None
    assert _hit(25.0, float("nan"), 10.0) is None
    assert _hit(float("nan"), 0.05, 10.0) is None


def test_hit_uses_direction_only_for_finite_threshold_crossings() -> None:
    assert _hit(25.0, 0.05, 10.0) is True
    assert _hit(25.0, -0.05, 10.0) is False
    assert _hit(-25.0, -0.05, 10.0) is True
    assert _hit(-25.0, 0.05, 10.0) is False
    assert _hit(5.0, 0.05, 10.0) is None


def _write_ohlcv(path: Path, dates: pd.DatetimeIndex) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100.0},
        index=pd.DatetimeIndex(dates, name="date"),
    )
    df.to_parquet(path)


def test_load_price_prefers_freshest_directory_regardless_of_order(tmp_path: Path) -> None:
    """Reproduces the real data/1d (stale, max 2026-08-05) vs data/1d_wide
    (fresh, max 2026-08-18) bug: the stale directory used to win outright
    just by being listed first, which is why fwd_5d came back all-null
    against a panel that spanned dates the stale directory never reached.
    """
    stale_dir = tmp_path / "stale"
    fresh_dir = tmp_path / "fresh"
    stale_dates = pd.bdate_range("2024-01-02", periods=5)
    fresh_dates = pd.bdate_range("2024-01-02", periods=40)
    _write_ohlcv(stale_dir / "SYM.parquet", stale_dates)
    _write_ohlcv(fresh_dir / "SYM.parquet", fresh_dates)

    # Stale directory listed first, exactly like DEFAULT_PRICE_DIRS = (data/1d, data/1d_wide).
    df_stale_first = _load_price("SYM", (stale_dir, fresh_dir))
    assert df_stale_first is not None
    assert df_stale_first.index.max() == fresh_dates[-1]
    assert len(df_stale_first) == len(fresh_dates)

    # Order must not matter -- freshness wins either way.
    df_fresh_first = _load_price("SYM", (fresh_dir, stale_dir))
    assert df_fresh_first is not None
    assert df_fresh_first.index.max() == fresh_dates[-1]


def test_load_price_falls_back_when_only_one_dir_has_the_symbol(tmp_path: Path) -> None:
    only_dir = tmp_path / "only"
    missing_dir = tmp_path / "missing"
    dates = pd.bdate_range("2024-01-02", periods=10)
    _write_ohlcv(only_dir / "SYM.parquet", dates)

    df = _load_price("SYM", (missing_dir, only_dir))
    assert df is not None
    assert len(df) == len(dates)


def test_load_price_skips_unreadable_file_and_uses_next_directory(tmp_path: Path) -> None:
    bad_dir = tmp_path / "bad"
    good_dir = tmp_path / "good"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "SYM.parquet").write_bytes(b"not a parquet file")
    dates = pd.bdate_range("2024-01-02", periods=7)
    _write_ohlcv(good_dir / "SYM.parquet", dates)

    df = _load_price("SYM", (bad_dir, good_dir))
    assert df is not None
    assert len(df) == len(dates)


def test_score_train_oos_surfaces_exception_instead_of_swallowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old `except Exception: train_oos = None` made a real failure in
    the train/OOS evaluator indistinguishable from "nothing to evaluate".
    Any exception raised while fitting the walk-forward block must now
    surface as a visible, structured error instead of vanishing.
    """
    panel = pd.DataFrame(
        {
            "error": [None, None],
            "theory_score": [12.0, -8.0],
            "fwd_1d": [0.01, -0.02],
            "asof": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        }
    )

    def boom(*args, **kwargs):
        raise ValueError("kaboom: geometry blew up")

    monkeypatch.setattr("edge.research.squeeze_flow_eval.evaluate_train_oos", boom)

    cfg = SqueezeValidationConfig()
    train_oos, summary_updates = _score_train_oos(panel, cfg)

    assert train_oos["status"] == "error"
    assert train_oos["oos_error"] == {"type": "ValueError", "message": "kaboom: geometry blew up"}
    assert train_oos["train"] is None
    assert train_oos["oos"] is None
    assert summary_updates["train"]["status"] == "error"
    assert summary_updates["oos"]["status"] == "error"
    assert summary_updates["train"]["oos_error"] == train_oos["oos_error"]
    assert summary_updates["oos"]["oos_error"] == train_oos["oos_error"]
