#!/usr/bin/env python3
"""Run or preflight the frozen daily directional bake-off."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from edge.research.directional_bakeoff import (  # noqa: E402
    BASE_MODEL_MENU,
    BakeoffProtocol,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_UNIVERSE_PATH,
    FEATURE_COLUMNS,
    ScoreCalibrator,
    _fit_calibration_indices,
    _folds,
    _make_model,
    build_decision_features,
    build_research_records,
    load_universe,
    run_bakeoff,
)
from edge.research.daily_data import load_daily_universe  # noqa: E402


def smoke_test(*, universe_path: Path, data_dir: Path) -> dict[str, object]:
    """Exercise causal features, split geometry, fitting, and calibration cheaply."""
    protocol = BakeoffProtocol(bootstrap_samples=100)
    symbols, sectors = load_universe(universe_path)
    selected = [symbol for symbol in symbols if symbol in {
        "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "JPM",
        "XOM", "JNJ", "WMT", "TLT", "COIN", "TSLA", "PLTR",
    }]
    bars = load_daily_universe(selected, asof=protocol.development_end, data_dir=data_dir)
    features = build_decision_features(bars, sectors)
    records = build_research_records(bars, features, horizon_days=5, protocol=protocol)
    folds = _folds(records, protocol, 5)
    fold = folds[0]
    fit_idx, calibration_idx = _fit_calibration_indices(
        records, fold.train_indices, horizon_days=5,
        calibration_dates=protocol.calibration_dates,
    )
    fit, calibration = records.iloc[fit_idx], records.iloc[calibration_idx]
    validation = records.iloc[fold.validation_indices]
    label = "direction_5d"
    model = _make_model("elastic_net", seed=protocol.random_state)
    model.fit(fit.loc[:, FEATURE_COLUMNS], fit[label].to_numpy(dtype=int))
    raw_cal = model.predict_proba(calibration.loc[:, FEATURE_COLUMNS])[:, 1]
    raw_val = model.predict_proba(validation.loc[:, FEATURE_COLUMNS])[:, 1]
    # The score calibrator independently verifies the calibration slice carries
    # both classes and can map an ordinal probability score deterministically.
    calibrator = ScoreCalibrator().fit(raw_cal, calibration[label].to_numpy(dtype=int))
    probability = calibrator.apply(raw_val)
    return {
        "status": "SMOKE_PASS",
        "symbols": len(selected),
        "feature_count": len(FEATURE_COLUMNS),
        "record_rows": len(records),
        "folds": len(folds),
        "first_validation_start": str(fold.validation_dates.min().date()),
        "first_validation_end": str(fold.validation_dates.max().date()),
        "probability_min": float(probability.min()),
        "probability_max": float(probability.max()),
        "fixed_base_models": list(BASE_MODEL_MENU),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        result = smoke_test(universe_path=args.universe, data_dir=args.data_dir)
    else:
        result = run_bakeoff(
            universe_path=args.universe,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
