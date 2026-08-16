from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.daily_data import load_daily_universe, load_pit_membership
from edge.research.features import causal_daily_features, feature_columns
from edge.research.models import RegularizedLogisticBaseline, baseline_scores


def _write_daily(path, symbol: str, values: np.ndarray) -> None:
    index = pd.bdate_range("2025-01-02", periods=len(values))
    frame = pd.DataFrame({"open": values, "high": values + 1, "low": values - 1,
                          "close": values, "volume": 1_000 + np.arange(len(values))}, index=index)
    frame.to_parquet(path / f"{symbol}.parquet")


def _panel(n: int = 100) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=n)
    rows = []
    for symbol, phase in (("AAA", 0.0), ("BBB", .5)):
        close = 100 + np.arange(n) * .2 + np.sin(np.arange(n) / 3 + phase)
        # A pure arithmetic ramp makes volume_z_20d exactly constant under any
        # fixed-length rolling window (the z-score of the endpoint of an
        # evenly-spaced window is a fixed number) -- a real zero-variance
        # column, caught by features.assert_no_degenerate_feature_columns.
        # The wiggle mirrors the one `close` already uses above.
        volume = 1_000 + np.arange(n) + 5 * np.sin(np.arange(n) / 3 + phase)
        frame = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                              "volume": volume}, index=index)
        frame["symbol"] = symbol
        rows.append(frame.reset_index(names="timestamp").set_index(["timestamp", "symbol"]))
    return pd.concat(rows).sort_index()


def test_point_in_time_daily_universe_loader_excludes_later_parquet_rows(tmp_path):
    _write_daily(tmp_path, "AAA", np.arange(100.0, 140.0))
    _write_daily(tmp_path, "BBB", np.arange(200.0, 240.0))
    asof = pd.Timestamp("2025-02-14")
    panel = load_daily_universe(["BBB", "AAA"], asof=asof, data_dir=tmp_path)
    assert panel.index.names == ["timestamp", "symbol"]
    assert set(panel.index.get_level_values("symbol")) == {"AAA", "BBB"}
    assert panel.index.get_level_values("timestamp").max() <= asof
    before = panel.copy()
    future = pd.read_parquet(tmp_path / "AAA.parquet")
    future.loc[future.index > asof, "close"] *= 100
    future.to_parquet(tmp_path / "AAA.parquet")
    pd.testing.assert_frame_equal(before, load_daily_universe(["AAA", "BBB"], asof=asof, data_dir=tmp_path))


def test_pit_membership_parser_reads_dated_intervals(tmp_path):
    pit = tmp_path / "pit.txt"
    pit.write_text(
        "AAA\t2025-01-02\t2025-01-31\n"
        "AAA\t2025-03-03\t2025-03-31\n"
        "BBB\t2025-01-02\t2025-02-28\n"
        "malformed line without tabs\n"
        "CCC\t2025-01-02\n",
        encoding="utf-8",
    )
    memberships = load_pit_membership(pit)
    assert set(memberships) == {"AAA", "BBB"}
    aaa = memberships["AAA"]
    assert aaa.contains(pd.Timestamp("2025-01-15"))
    assert not aaa.contains(pd.Timestamp("2025-02-10"))  # gap between spans
    assert aaa.contains(pd.Timestamp("2025-03-20"))
    assert not aaa.contains(pd.Timestamp("2025-04-01"))
    assert memberships["BBB"].contains(pd.Timestamp("2025-02-01"))


def test_pit_membership_parser_rejects_inverted_spans(tmp_path):
    pit = tmp_path / "pit.txt"
    pit.write_text("AAA\t2025-02-01\t2025-01-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inverted span"):
        load_pit_membership(pit)


def test_daily_universe_drops_rows_outside_pit_membership(tmp_path):
    _write_daily(tmp_path, "AAA", np.arange(100.0, 140.0))
    _write_daily(tmp_path, "BBB", np.arange(200.0, 240.0))
    pit = tmp_path / "pit.txt"
    # AAA is a member only through 2025-02-07; BBB is never a member.
    pit.write_text("AAA\t2025-01-02\t2025-02-07\n", encoding="utf-8")
    asof = pd.Timestamp("2025-02-14")
    panel = load_daily_universe(["AAA", "BBB"], asof=asof, data_dir=tmp_path,
                                pit_instruments=pit)
    assert set(panel.index.get_level_values("symbol")) == {"AAA"}
    assert panel.index.get_level_values("timestamp").max() <= pd.Timestamp("2025-02-07")


def test_daily_universe_pit_required_raises_when_file_missing(tmp_path):
    _write_daily(tmp_path, "AAA", np.arange(100.0, 110.0))
    with pytest.raises(FileNotFoundError, match="PIT instruments file required"):
        load_daily_universe(["AAA"], asof=pd.Timestamp("2025-01-20"), data_dir=tmp_path,
                            pit_instruments=tmp_path / "missing.txt", pit_required=True)


def test_daily_universe_pit_optional_proceeds_unfiltered_when_file_missing(tmp_path):
    _write_daily(tmp_path, "AAA", np.arange(100.0, 110.0))
    panel = load_daily_universe(["AAA"], asof=pd.Timestamp("2025-01-20"), data_dir=tmp_path,
                                pit_instruments=tmp_path / "missing.txt")
    assert set(panel.index.get_level_values("symbol")) == {"AAA"}


def test_causal_features_are_unchanged_when_future_prices_mutate():
    bars = _panel()
    before = causal_daily_features(bars)
    mutated = bars.copy()
    cutoff = pd.Timestamp("2025-04-15")
    future = mutated.index.get_level_values("timestamp") > cutoff
    mutated.loc[future, "close"] *= 5
    after = causal_daily_features(mutated)
    pd.testing.assert_frame_equal(before.loc[(slice(None, cutoff), slice(None)), :],
                                  after.loc[(slice(None, cutoff), slice(None)), :])


def test_frozen_baselines_and_logistic_fit_only_training_rows():
    features = causal_daily_features(_panel()).dropna()
    baseline = baseline_scores(features, horizon_days=10)
    assert {"momentum_score", "volatility_scaled_momentum_score"}.issubset(baseline.columns)
    assert "probability" not in " ".join(baseline.columns)
    train = features.iloc[:80]
    labels = pd.Series(np.tile([0, 1], 40), index=train.index)
    model = RegularizedLogisticBaseline().fit(train, labels)
    assert tuple(model.scaler_.feature_names_in_) == feature_columns()
    assert np.allclose(model.scaler_.mean_, train.loc[:, feature_columns()].mean().to_numpy())
    first = model.predict_proba(features.iloc[80:])
    changed_test = features.copy()
    changed_test.iloc[81:, :] *= 999
    # The fitted transform/model is frozen; an unchanged row predicts exactly
    # the same despite arbitrary later data changes.
    pd.testing.assert_series_equal(first.iloc[:1], model.predict_proba(changed_test.iloc[80:]).iloc[:1])


def test_logistic_refuses_holdout_free_single_class_fit():
    features = causal_daily_features(_panel()).dropna().iloc[:20]
    with pytest.raises(ValueError, match="both direction classes"):
        RegularizedLogisticBaseline().fit(features, pd.Series(1, index=features.index))
