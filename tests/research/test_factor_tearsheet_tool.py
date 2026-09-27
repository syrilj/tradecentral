"""Tests for `edge.tools.factor_tearsheet`, the CLI driver over `factor_diagnostics.py`.

Five things this file exists to catch, mirroring the risks called out in the
tool's own module docstring and in `factor_diagnostics.py`'s:

  1. The dashboard-facing JSON (`envelope_dict` / `latest.json`) must survive
     `json.loads` with no `NaN` token anywhere in it.
  2. The `quantile == -1` spread row must be present in the envelope's
     `quantiles` list, and the top-level `monotonicity` scalar must be the
     value `monotonicity_score` computes *excluding* that row (not corrupted
     by the spread's out-of-order value -- see `factor_diagnostics.py`'s
     `monotonicity_score` docstring).
  3. A signal built through this tool's own `build_signal` (the exact path
     `main()` uses) on a synthetic panel with a real cross-sectional
     structure -- distinct, noise-free per-symbol drift -- must score
     monotonicity near +1.0 end-to-end, proving the CLI's data assembly does
     not introduce an off-by-one or an accidental shuffle.
  4. `--start`/`--end` at or after the sealed terminal holdout
     (2026-07-13) must raise, not silently clamp.
  5. A missing data directory must raise with the path named in the message.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from edge.tools.factor_tearsheet import (
    DEFAULT_END,
    TERMINAL_HOLDOUT_START,
    _list_symbols,
    _resolve_window,
    build_signal,
    envelope_dict,
)
from edge.research.factor_diagnostics import factor_tearsheet, monotonicity_score


def _write_symbol_parquet(
    data_dir, symbol: str, close: np.ndarray, index: pd.DatetimeIndex, *, phase: float,
) -> None:
    # A pure arithmetic/geometric ramp makes volume_z_20d exactly constant
    # under any fixed-length rolling window (the z-score of the endpoint of
    # an evenly-spaced window is a fixed number) -- a real zero-variance
    # column that `features.assert_no_degenerate_feature_columns` correctly
    # rejects. The sine wiggle breaks that degeneracy without disturbing the
    # deterministic drift-vs-return relationship this fixture exists to test
    # (see test_daily_features_models.py for the identical pattern).
    n = len(close)
    volume = 1_000_000.0 + np.arange(n) + 5_000.0 * np.sin(np.arange(n) / 3.0 + phase)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": volume,
        },
        index=index,
    )
    frame.index.name = "Date"
    frame.to_parquet(data_dir / f"{symbol}.parquet")


def _write_drift_universe(data_dir, *, n_symbols: int = 10, n_days: int = 160) -> list[str]:
    """Symbols with distinct, noise-free constant daily drift.

    Forward return and trailing momentum are both exact, deterministic
    functions of a symbol's drift, so they rank identically -- the cleanest
    possible fixture for "does the pipeline preserve a real monotone
    ranking end to end", the same shape of fixture
    `test_factor_diagnostics.py` uses for its own oracle-signal test.
    """
    index = pd.bdate_range("2024-01-02", periods=n_days)
    drifts = np.linspace(-0.003, 0.003, n_symbols)
    symbols = [f"SYM{i:02d}" for i in range(n_symbols)]
    for i, (symbol, drift) in enumerate(zip(symbols, drifts)):
        close = 100.0 * (1.0 + drift) ** np.arange(n_days)
        _write_symbol_parquet(data_dir, symbol, close, index, phase=float(i) * 0.5)
    return symbols


# ---------------------------------------------------------------------------
# 1 + 2: envelope JSON round-trips clean, spread row present, monotonicity
# excludes it.
# ---------------------------------------------------------------------------


def _synthetic_panel(n_dates: int = 250, n_syms: int = 25, seed: int = 5):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, 0.02, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close


def test_envelope_json_round_trips_with_no_nan() -> None:
    close = _synthetic_panel()
    # A leaky-by-design oracle score, same trick test_factor_diagnostics.py
    # uses, so the tearsheet actually has non-trivial (non-NaN-everywhere)
    # numbers to serialize, not just an all-empty degenerate result.
    scores = close.pct_change().shift(-1)
    tearsheet = factor_tearsheet(scores=scores, close=close, n_quantiles=5, horizons=(1, 2, 3, 5), execution_lag=1)

    envelope = envelope_dict(tearsheet, source="unit-test-source")
    dumped = json.dumps(envelope, allow_nan=False)  # raises on any NaN/Inf token
    reloaded = json.loads(dumped)

    assert reloaded["available"] is True
    assert reloaded["reason"] is None
    assert reloaded["source"] == "unit-test-source"
    assert reloaded["n_dates"] == len(close)
    assert reloaded["n_symbols"] == close.shape[1]
    assert isinstance(reloaded["generated_at"], str) and reloaded["generated_at"]

    for row in reloaded["ic_decay"] + reloaded["quantiles"] + reloaded["quantile_turnover"]:
        for value in row.values():
            assert value is None or isinstance(value, (int, float, str)), row
            if isinstance(value, float):
                assert np.isfinite(value)


def test_envelope_quantiles_include_spread_row_and_monotonicity_excludes_it() -> None:
    close = _synthetic_panel(n_dates=200, n_syms=20, seed=13)
    scores = close.pct_change().shift(-1)
    tearsheet = factor_tearsheet(scores=scores, close=close, n_quantiles=5, execution_lag=1)
    envelope = envelope_dict(tearsheet, source="x")

    quantile_values = sorted(row["quantile"] for row in envelope["quantiles"])
    assert quantile_values == [-1, 1, 2, 3, 4, 5]

    # Independently recompute monotonicity from the *real* buckets only
    # (quantile >= 1), exactly as factor_diagnostics.monotonicity_score does,
    # and check it matches the envelope's top-level scalar -- proving the
    # -1 spread row (an out-of-order, non-ordinal value) was not fed into it.
    real_rows = pd.DataFrame([row for row in envelope["quantiles"] if row["quantile"] >= 1])
    expected = monotonicity_score(real_rows)
    assert envelope["monotonicity"] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# 3: synthetic monotone signal, end-to-end through build_signal (the CLI's
# own data-assembly path).
# ---------------------------------------------------------------------------


def test_synthetic_monotone_signal_scores_near_one_through_cli_build_path(tmp_path) -> None:
    _write_drift_universe(tmp_path, n_symbols=10, n_days=160)
    end = pd.bdate_range("2024-01-02", periods=160)[-1]
    assert end < TERMINAL_HOLDOUT_START  # fixture must stay clear of the seal by construction

    scores, close, source = build_signal("momentum_20d", start=None, end=end, data_dir=tmp_path)
    assert "momentum_20d" in source
    assert scores.shape[1] == 10

    tearsheet = factor_tearsheet(scores=scores, close=close, n_quantiles=5, execution_lag=1)
    assert tearsheet.monotonicity == pytest.approx(1.0, abs=0.15)

    envelope = envelope_dict(tearsheet, source=source)
    json.dumps(envelope, allow_nan=False)  # must still be a clean payload


# ---------------------------------------------------------------------------
# 4: sealed-holdout boundary.
# ---------------------------------------------------------------------------


def test_end_at_or_after_holdout_raises() -> None:
    with pytest.raises(ValueError, match="sealed terminal holdout"):
        _resolve_window(None, str(TERMINAL_HOLDOUT_START.date()))
    with pytest.raises(ValueError, match="sealed terminal holdout"):
        _resolve_window(None, "2026-08-01")


def test_start_at_or_after_holdout_raises() -> None:
    with pytest.raises(ValueError, match="sealed terminal holdout"):
        _resolve_window(str(TERMINAL_HOLDOUT_START.date()), str(DEFAULT_END.date()))


def test_default_end_is_strictly_before_holdout() -> None:
    start, end = _resolve_window(None, None)
    assert start is None
    assert end < TERMINAL_HOLDOUT_START
    assert end == DEFAULT_END


# ---------------------------------------------------------------------------
# 5: missing data directory.
# ---------------------------------------------------------------------------


def test_missing_data_directory_raises_with_path_named(tmp_path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        _list_symbols(missing)

    with pytest.raises(FileNotFoundError, match=str(missing)):
        build_signal("momentum_20d", start=None, end=DEFAULT_END, data_dir=missing)
