"""Preregister and fit the frozen simple-model directional research programme."""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .costs import UnderlyingCostModel
from .daily_data import DEFAULT_DAILY_DATA_DIR, load_daily_universe
from .evaluation import (
    TrialSpec,
    evidence_metrics,
    evaluate_trial_on_outer_fold,
    fit_platt,
    grouped_evidence,
    paired_baseline_difference_metrics,
    raw_scores,
    select_threshold_for_spec,
    trial_specs,
)
from .experiment_ledger import ExperimentLedger
from .features import causal_daily_features, feature_columns
from .gates import (
    HorizonDevelopmentEvidence,
    evaluate_daily_directional_development_gate,
)
from .hashing import stable_hash
from .labels import FROZEN_HORIZONS, tradable_directional_labels
from .models import RegularizedLogisticBaseline
from .challengers import FixedMenuXGBoostChallenger
from .panel_splits import nested_panel_walk_forward_splits, trading_dates
from .provenance import load_upstream_provenance
from .regimes import classify_regimes
from .reporting import Figure, GateReportSpec, write_gate_doc
from .robustness import monte_carlo_robustness, oof_underlying_robustness_diagnostics
from .sector_residual import sector_residual_momentum_20d
from .simple_hypotheses import shock_reversal_features_5d


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = EDGE_ROOT / "config" / "universe_wide.json"
DEFAULT_OUTPUT_ROOT = EDGE_ROOT / "runs" / "research" / "directional_daily_v1"
IMPLEMENTATION_GENERATION = "fixed_direction_policy_v2"
HYPOTHESIS_FEATURE_COLUMNS = (
    "shock_reversal_score_5d",
    "shock_reversal_eligible_5d",
    "sector_residual_score_20d",
    "sector_residual_eligible_20d",
)


@dataclass(frozen=True)
class ResearchProtocol:
    development_start: str = "2018-01-02"
    validation_start: str = "2022-01-03"
    development_end: str = "2026-07-10"
    terminal_holdout_start: str = "2026-07-13"
    terminal_holdout_end: str = "2027-01-29"
    outer_validation_dates: int = 126
    inner_initial_train_dates: int = 504
    inner_validation_dates: int = 126
    outer_partial_final_validation: bool = True
    outer_partial_validation_min_dates: int = 60
    embargo_multiplier: int = 1
    round_trip_cost_bps: float = 10.0
    minimum_holdout_sessions: int = 120

    def __post_init__(self) -> None:
        ordered = [
            pd.Timestamp(self.development_start),
            pd.Timestamp(self.validation_start),
            pd.Timestamp(self.development_end),
            pd.Timestamp(self.terminal_holdout_start),
            pd.Timestamp(self.terminal_holdout_end),
        ]
        if ordered != sorted(ordered) or ordered[2] >= ordered[3]:
            raise ValueError("research protocol dates must be ordered and holdout must be terminal")
        if min(self.outer_validation_dates, self.inner_initial_train_dates,
               self.inner_validation_dates, self.embargo_multiplier,
               self.minimum_holdout_sessions, self.outer_partial_validation_min_dates) < 1:
            raise ValueError("research protocol counts must be positive")
        if self.outer_partial_validation_min_dates > self.outer_validation_dates:
            raise ValueError("outer partial validation minimum cannot exceed outer validation dates")
        if self.round_trip_cost_bps < 0:
            raise ValueError("round_trip_cost_bps must be non-negative")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return value
    raise TypeError(f"unsupported report value: {type(value).__name__}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def load_universe(path: str | Path = DEFAULT_UNIVERSE) -> tuple[list[str], dict[str, str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    symbols = [str(symbol).upper() for symbol in raw.get("symbols", [])]
    if not symbols:
        raise ValueError("research universe is empty")
    sectors: dict[str, str] = {}
    for sector, members in (raw.get("sectors") or {}).items():
        for symbol in members:
            sectors.setdefault(str(symbol).upper(), str(sector))
    return symbols, {symbol: sectors.get(symbol, "unclassified") for symbol in symbols}


def prepare_research_panel(
    *,
    symbols: Sequence[str],
    sectors: Mapping[str, str],
    asof: object,
    data_dir: str | Path = DEFAULT_DAILY_DATA_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load point-in-time bars and attach only causal features/regimes."""
    bars = load_daily_universe(symbols, asof=asof, data_dir=data_dir)
    close_features = causal_daily_features(bars)
    shock_features = shock_reversal_features_5d(bars)
    shifted_features: list[pd.DataFrame] = []
    labels: list[pd.DataFrame] = []
    regimes: list[pd.DataFrame] = []
    for symbol, frame in bars.groupby(level="symbol", sort=True):
        single = frame.droplevel("symbol")
        symbol_features = close_features.xs(symbol, level="symbol").join(
            shock_features.xs(symbol, level="symbol").loc[
                :, ["shock_reversal_score_5d", "shock_reversal_eligible_5d"]
            ],
        ).shift(1)
        symbol_features["shock_reversal_eligible_5d"] = (
            symbol_features["shock_reversal_eligible_5d"].eq(True)
        )
        symbol_features["feature_asof"] = single.index.to_series().shift(1)
        symbol_features["symbol"] = symbol
        shifted_features.append(
            symbol_features.reset_index().set_index(["timestamp", "symbol"])
        )
        label = tradable_directional_labels(single)
        label["symbol"] = symbol
        labels.append(label.reset_index().set_index(["timestamp", "symbol"]))
        regime = classify_regimes(single).shift(1)
        regime["symbol"] = symbol
        regimes.append(regime.reset_index().set_index(["timestamp", "symbol"]))
    panel = bars.join(pd.concat(shifted_features).sort_index()).join(
        pd.concat(labels).sort_index()
    ).join(
        pd.concat(regimes).sort_index()
    )
    panel["sector"] = panel.index.get_level_values("symbol").map(
        lambda symbol: sectors.get(str(symbol), "unclassified")
    )
    residual = sector_residual_momentum_20d(panel.reset_index()).set_index(
        ["timestamp", "symbol"],
    )
    panel = panel.join(residual.loc[:, [
        "sector_residual_score_20d", "sector_residual_eligible_20d",
    ]])
    return bars, panel.sort_index()


def research_feature_columns(*, include_simple_hypotheses: bool = False) -> tuple[str, ...]:
    """Frozen base features plus the explicitly opted-in simple hypotheses."""
    return feature_columns() + (
        HYPOTHESIS_FEATURE_COLUMNS if include_simple_hypotheses else ()
    )


def dataset_fingerprint(bars: pd.DataFrame) -> str:
    """Content identity of the point-in-time bars actually made available."""
    hashed = pd.util.hash_pandas_object(bars, index=True).to_numpy(dtype=np.uint64)
    digest = hashlib.sha256()
    digest.update(hashed.tobytes())
    digest.update("|".join(map(str, bars.columns)).encode("utf-8"))
    return digest.hexdigest()


def code_fingerprint() -> str:
    files = (
        "costs.py", "daily_data.py", "evaluation.py", "experiment_ledger.py",
        "features.py", "gates.py", "labels.py", "models.py", "challengers.py",
        "panel_splits.py", "regimes.py", "robustness.py", "runner.py",
        "sector_residual.py", "simple_hypotheses.py", "splits.py", "statistics.py",
    )
    material = {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in files
    }
    return stable_hash(material, namespace="edge-daily-research-code-v1")


def _development_records(
    panel: pd.DataFrame,
    protocol: ResearchProtocol,
    horizon_days: int,
    *,
    include_simple_hypotheses: bool = False,
) -> pd.DataFrame:
    start, end = pd.Timestamp(protocol.development_start), pd.Timestamp(protocol.development_end)
    dates = panel.index.get_level_values("timestamp")
    target_end_column = f"target_end_{horizon_days}d"
    label_column = f"direction_{horizon_days}d"
    return_column = f"forward_return_{horizon_days}d"
    model_features = research_feature_columns(
        include_simple_hypotheses=include_simple_hypotheses,
    )
    columns = [
        *model_features, label_column, return_column, target_end_column,
        "sector", "volatility_regime", "trend_regime", "bear_market",
    ]
    records = panel.loc[(dates >= start) & (dates <= end), columns].copy()
    target_end = pd.to_datetime(records[target_end_column], errors="coerce")
    records = records.loc[
        target_end.notna()
        & (target_end <= end)
        & records[label_column].notna()
        & records.loc[:, model_features].notna().all(axis=1)
    ].copy()
    records[label_column] = records[label_column].astype(int)
    if records.empty:
        raise ValueError(f"no resolved development rows for {horizon_days}d")
    return records.sort_index()


def _cost_model(protocol: ResearchProtocol) -> UnderlyingCostModel:
    # Split the frozen total evenly between one-way spread and slippage.  This
    # preserves the exact total while keeping both execution components explicit.
    one_way_total = protocol.round_trip_cost_bps / 2.0
    return UnderlyingCostModel(
        one_way_spread_bps=one_way_total / 2.0,
        one_way_slippage_bps=one_way_total / 2.0,
    )


def _folds(records: pd.DataFrame, protocol: ResearchProtocol, horizon_days: int):
    dates = trading_dates(records)
    validation_start = pd.Timestamp(protocol.validation_start)
    dates_before_validation = int(np.sum(dates < validation_start))
    embargo = horizon_days * protocol.embargo_multiplier
    initial = dates_before_validation - horizon_days - embargo
    if initial < protocol.inner_initial_train_dates:
        raise ValueError("validation boundary leaves insufficient initial training dates")
    return tuple(nested_panel_walk_forward_splits(
        records,
        label_horizon=horizon_days,
        outer_initial_train_dates=initial,
        outer_validation_dates=protocol.outer_validation_dates,
        inner_initial_train_dates=protocol.inner_initial_train_dates,
        inner_validation_dates=protocol.inner_validation_dates,
        outer_step_dates=protocol.outer_validation_dates,
        inner_step_dates=protocol.inner_validation_dates,
        embargo_dates=embargo,
        include_partial_final_outer=protocol.outer_partial_final_validation,
        min_partial_outer_validation_dates=protocol.outer_partial_validation_min_dates,
    ))


def _serialize_fitted_model(spec: TrialSpec, model: Any | None) -> dict[str, Any]:
    if spec.model in {"momentum", "volatility_scaled_momentum"}:
        return {"type": spec.model, "score_feature": spec.config["score"]}
    if spec.model == "fixed_feature_score":
        return {
            "type": spec.model,
            "score_feature": spec.config["score"],
            "eligibility_feature": spec.config["eligibility"],
            "fixed_probability_threshold": float(spec.config["fixed_probability_threshold"]),
            "hypothesis": spec.config["hypothesis"],
        }
    if spec.model == "cpu_xgboost":
        if not isinstance(model, FixedMenuXGBoostChallenger) or model.estimator_ is None:
            raise ValueError("fitted CPU XGBoost challenger is unavailable")
        booster = model.estimator_.get_booster()
        # JSON-format booster bytes are portable, deterministic for this fixed
        # seed/config, and remain safe to embed in the artifact JSON.
        booster_bytes = bytes(booster.save_raw(raw_format="json"))
        return {
            "type": spec.model,
            "menu_name": str(spec.config["menu_name"]),
            "config": dict(spec.config["config"]),
            "features": list(spec.features),
            "fitted_row_count": model.fitted_row_count_,
            "booster_format": "xgboost-json-base64",
            "booster_bytes_base64": base64.b64encode(booster_bytes).decode("ascii"),
            "booster_config": json.loads(booster.save_config()),
        }
    if not isinstance(model, RegularizedLogisticBaseline) or model.scaler_ is None or model.estimator_ is None:
        raise ValueError("fitted logistic model is unavailable")
    return {
        "type": spec.model,
        "C": float(spec.config["C"]),
        "features": list(spec.features),
        "scaler_mean": model.scaler_.mean_.tolist(),
        "scaler_scale": model.scaler_.scale_.tolist(),
        "coefficient": model.estimator_.coef_[0].tolist(),
        "intercept": float(model.estimator_.intercept_[0]),
    }


def run_preregistered_research(
    *,
    protocol: ResearchProtocol = ResearchProtocol(),
    universe_path: str | Path = DEFAULT_UNIVERSE,
    data_dir: str | Path = DEFAULT_DAILY_DATA_DIR,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    include_xgboost: bool = False,
    include_simple_hypotheses: bool = False,
) -> dict[str, Any]:
    """Run development-only nested evidence and seal, but do not open, holdout."""
    symbols, sectors = load_universe(universe_path)
    bars, panel = prepare_research_panel(
        symbols=symbols, sectors=sectors, asof=protocol.development_end,
        data_dir=data_dir,
    )
    data_id, code_id = dataset_fingerprint(bars), code_fingerprint()
    costs = _cost_model(protocol)
    root = Path(output_root)
    ledger = ExperimentLedger(root / "experiments.jsonl")
    upstream = load_upstream_provenance()
    specs_by_horizon = {
        horizon: trial_specs(
            horizon,
            include_xgboost=include_xgboost,
            include_simple_hypotheses=include_simple_hypotheses,
        )
        for horizon in FROZEN_HORIZONS
    }
    total_trial_count = sum(len(specs) for specs in specs_by_horizon.values())
    menu = {
        str(horizon): [
            {"name": spec.name, "model": spec.model, "config": dict(spec.config),
             "features": list(spec.features)}
            for spec in specs_by_horizon[horizon]
        ]
        for horizon in FROZEN_HORIZONS
    }
    experiment_config = {"protocol": asdict(protocol), "trial_menu": menu,
                         "implementation_generation": IMPLEMENTATION_GENERATION,
                         "recorded_trial_count": total_trial_count,
                         "instrument": "underlying", "option_profit_claim": False}
    if include_xgboost:
        experiment_config["include_cpu_xgboost"] = True
    if include_simple_hypotheses:
        experiment_config["include_fixed_simple_hypotheses"] = True
    experiment = ledger.preregister_experiment(
        features=research_feature_columns(
            include_simple_hypotheses=include_simple_hypotheses,
        ),
        model=(
            "nested_daily_directional_preregistered_menu_v2"
            if include_simple_hypotheses
            else "nested_cpu_xgboost_challenger_daily_directional_v1"
            if include_xgboost
            else "nested_simple_daily_directional_v1"
        ),
        config=experiment_config,
        upstream_provenance=upstream,
        dataset_fingerprint=data_id,
        boundaries={
            "train": {
                "start": protocol.development_start,
                "end": (pd.Timestamp(protocol.validation_start) - pd.Timedelta(days=1)).date().isoformat(),
            },
            "validation": {
                "start": protocol.validation_start,
                "end": protocol.development_end,
            },
            "terminal_holdout": {
                "start": protocol.terminal_holdout_start,
                "end": protocol.terminal_holdout_end,
            },
        },
        code_version=code_id,
    )
    run_dir = root / experiment.record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    horizons_report: dict[str, Any] = {}
    artifact_horizons: dict[str, Any] = {}
    development_gate_inputs: list[HorizonDevelopmentEvidence] = []
    for horizon in FROZEN_HORIZONS:
        records = _development_records(
            panel, protocol, horizon,
            include_simple_hypotheses=include_simple_hypotheses,
        )
        folds = _folds(records, protocol, horizon)
        if not folds:
            raise ValueError(f"no nested outer folds for {horizon}d")
        per_trial: dict[str, pd.DataFrame] = {}
        fold_metadata: dict[str, list[dict[str, Any]]] = {}
        trial_records: dict[str, Any] = {}
        specs = specs_by_horizon[horizon]
        for spec in specs:
            trial = ledger.preregister_trial(
                experiment.record_id,
                features=spec.features,
                model=spec.model,
                config={**dict(spec.config), "round_trip_cost_bps": protocol.round_trip_cost_bps},
            )
            trial_records[spec.name] = trial
            pieces: list[pd.DataFrame] = []
            metadata: list[dict[str, Any]] = []
            try:
                for fold in folds:
                    rows, details = evaluate_trial_on_outer_fold(
                        records, fold, spec, horizon_days=horizon, costs=costs,
                    )
                    pieces.append(rows)
                    metadata.append(details)
                evidence = pd.concat(pieces).sort_index()
                metrics = evidence_metrics(
                    evidence, label_column=f"direction_{horizon}d",
                    trial_count=total_trial_count,
                    horizon_days=horizon,
                )
                ledger.record_trial_result(trial.record_id, status="COMPLETED", metrics=metrics)
                per_trial[spec.name] = evidence
                fold_metadata[spec.name] = metadata
            except Exception as exc:
                ledger.record_trial_result(
                    trial.record_id, status="FAILED", errors=[f"{type(exc).__name__}:{exc}"],
                )
        if len(per_trial) != len(specs):
            raise RuntimeError(f"one or more preregistered trials failed for {horizon}d")
        metrics_by_trial = {
            name: evidence_metrics(
                rows, label_column=f"direction_{horizon}d",
                trial_count=total_trial_count,
                horizon_days=horizon,
            )
            for name, rows in per_trial.items()
        }
        selected_spec = max(
            specs,
            key=lambda spec: (
                metrics_by_trial[spec.name]["net_expectancy"],
                -metrics_by_trial[spec.name]["expected_calibration_error"],
                spec.name,
            ),
        )
        selected_rows = per_trial[selected_spec.name]
        baseline_rows = per_trial[specs[0].name]
        selected_metrics = metrics_by_trial[selected_spec.name]
        baseline_metrics = metrics_by_trial[specs[0].name]
        baseline_difference = paired_baseline_difference_metrics(
            selected_rows, baseline_rows, horizon_days=horizon,
        )
        robustness = oof_underlying_robustness_diagnostics(
            selected_rows,
            block_size=max(5, horizon),
        )
        monte_carlo = monte_carlo_robustness(
            selected_rows,
            n_simulations=2_000,
            holding_periods=(21, 63, 126, 252),
            seed=0,
        )
        development_gate_inputs.append(HorizonDevelopmentEvidence(
            horizon_days=horizon,
            candidate_net_returns=selected_rows["net_return"].to_numpy(dtype=float),
            momentum_net_returns=baseline_rows["net_return"].to_numpy(dtype=float),
            decision_dates=selected_rows.index.get_level_values("timestamp"),
            calibrated_probabilities=selected_rows["probability"].to_numpy(dtype=float),
            realized_outcomes=selected_rows[f"direction_{horizon}d"].astype(bool).tolist(),
            recorded_trial_count=total_trial_count,
        ))
        # A single final calibration and threshold is fitted from development
        # OOF predictions.  The terminal holdout remains unread.
        calibrator = fit_platt(
            selected_rows["raw_score"], selected_rows[f"direction_{horizon}d"],
        )
        calibrated = calibrator.apply(selected_rows["raw_score"])
        threshold, threshold_training = select_threshold_for_spec(
            selected_spec,
            calibrated,
            selected_rows[f"forward_return_{horizon}d"],
            selected_rows.index.get_level_values("timestamp"),
            records.loc[selected_rows.index],
            costs=costs,
            raw_score=selected_rows["raw_score"],
        )
        final_score, fitted_model = raw_scores(
            selected_spec, records, records.iloc[:1],
            label_column=f"direction_{horizon}d",
        )
        del final_score
        artifact_horizons[str(horizon)] = {
            "selected_trial_id": trial_records[selected_spec.name].record_id,
            "selected_trial": selected_spec.name,
            "model": _serialize_fitted_model(selected_spec, fitted_model),
            "calibration": {**asdict(calibrator), "version": stable_hash(
                {"experiment_id": experiment.record_id, "horizon": horizon,
                 "trial": selected_spec.name, "calibration": asdict(calibrator)},
                namespace="edge-daily-calibration-v1",
            )},
            "probability_target": "underlying_directional_return_next_open_to_horizon_close",
            "horizon_days": horizon,
            "threshold": threshold,
            "threshold_training": threshold_training,
            "development_metrics": selected_metrics,
            "frozen_baseline_trial": specs[0].name,
            "frozen_baseline_metrics": baseline_metrics,
            "paired_frozen_baseline_difference": baseline_difference,
            "development_robustness": robustness,
            "monte_carlo_robustness": monte_carlo,
            "beats_frozen_baseline_on_development": (
                selected_metrics["net_expectancy"] > baseline_metrics["net_expectancy"]
            ),
            "beats_frozen_baseline_with_positive_development_ci": (
                baseline_difference["net_expectancy_difference_ci95_lower"] > 0
            ),
        }
        horizons_report[str(horizon)] = {
            "fold_count": len(folds),
            "selected_trial": selected_spec.name,
            "selected_trial_id": trial_records[selected_spec.name].record_id,
            "metrics_by_trial": metrics_by_trial,
            "selected_slices": grouped_evidence(selected_rows),
            "selected_robustness": robustness,
            "fold_training_selection": fold_metadata,
        }
        for name, rows in per_trial.items():
            rows.to_parquet(run_dir / f"oof_{horizon}d_{name}.parquet")
    development_gate = evaluate_daily_directional_development_gate(
        development_gate_inputs,
    )
    development_gate_by_horizon = {
        str(row["horizon_days"]): row for row in development_gate["horizons"]
    }
    for horizon, gate in development_gate_by_horizon.items():
        artifact_horizons[horizon]["development_gate"] = gate
        artifact_horizons[horizon]["terminal_holdout_eligible"] = bool(gate["passed"])
        horizons_report[horizon]["development_gate"] = gate
    development_passed = bool(development_gate["passed"])
    sealed_fingerprint = stable_hash(
        {
            "experiment_id": experiment.record_id,
            "start": protocol.terminal_holdout_start,
            "end": protocol.terminal_holdout_end,
            "status": "UNSEEN_AND_NOT_LOADED",
        },
        namespace="edge-fresh-terminal-holdout-v1",
    )
    holdout = ledger.preregister_terminal_holdout(
        experiment.record_id, dataset_fingerprint=sealed_fingerprint,
    )
    artifact = {
        "schema_version": "edge-daily-directional-artifact-v1",
        "experiment_id": experiment.record_id,
        "status": "FROZEN_RESEARCH_CHALLENGER",
        "shadow_only": True,
        "broker_authorized": False,
        "underlying_gate": (
            "PENDING_UNTOUCHED_HOLDOUT" if development_passed
            else "FAIL_DEVELOPMENT"
        ),
        "development_gate": development_gate,
        "option_shadow_collection_authorized": False,
        "data_fingerprint": data_id,
        "code_version": code_id,
        "training_asof": protocol.development_end,
        "terminal_holdout": {
            "holdout_id": holdout.record_id,
            "start": protocol.terminal_holdout_start,
            "end": protocol.terminal_holdout_end,
            "minimum_sessions_before_evaluation": protocol.minimum_holdout_sessions,
            "status": "SEALED_UNEVALUATED",
        },
        "cost_model": {**asdict(costs), "round_trip_cost_bps": costs.round_trip_cost_bps},
        "target_definition": {
            "feature_information_cutoff": "prior_session_close",
            "entry": "next_session_open",
            "exit": "horizon_session_close",
            "return_basis": "underlying_next_open_to_horizon_close",
        },
        "horizons": artifact_horizons,
    }
    report = {
        "schema_version": "edge-daily-directional-research-report-v1",
        "experiment_id": experiment.record_id,
        "status": (
            "DEVELOPMENT_PASS_HOLDOUT_SEALED" if development_passed
            else "DEVELOPMENT_NO_GO_HOLDOUT_REMAINS_SEALED"
        ),
        "promotion_status": (
            "FAIL_SHADOW_ONLY_PENDING_FRESH_HOLDOUT" if development_passed
            else "FAIL_SHADOW_ONLY_DEVELOPMENT_GATE"
        ),
        "development_gate": development_gate,
        "symbols": len(symbols),
        "development_bar_dates": int(trading_dates(bars).size),
        "data_fingerprint": data_id,
        "code_version": code_id,
        "terminal_holdout_id": holdout.record_id,
        "terminal_holdout_opened": False,
        "horizons": horizons_report,
    }
    _write_json(run_dir / "artifact.json", artifact)
    _write_json(run_dir / "report.json", report)
    _write_json(root / "latest.json", {
        "experiment_id": experiment.record_id,
        "run_dir": str(run_dir),
        "artifact_path": str(run_dir / "artifact.json"),
        "report_path": str(run_dir / "report.json"),
        "status": report["status"],
    })
    return report


def _horizon_figures(horizon: int) -> tuple[Figure, ...]:
    """The four HARD checks from gates.py's decision tree, plus which trial
    was selected, for one frozen horizon -- sourced from
    `horizons.<h>.development_gate.*` in report.json (verified against a real
    run: edge/runs/research/directional_daily_v1/*/report.json)."""
    prefix = f"horizons.{horizon}.development_gate"
    return (
        Figure(f"h{horizon}_selected_trial", f"horizons.{horizon}.selected_trial", "str"),
        Figure(f"h{horizon}_status", f"{prefix}.status", "str"),
        Figure(
            f"h{horizon}_paired_ci_lower", f"{prefix}.metrics.candidate_minus_momentum_ci95_lower",
            "ratio4", "> 0", f"{prefix}.checks.candidate_minus_momentum_ci95_lower_positive",
        ),
        Figure(
            f"h{horizon}_expectancy_ci_lower", f"{prefix}.metrics.candidate_net_expectancy_ci95_lower",
            "ratio4", "> 0", f"{prefix}.checks.candidate_net_expectancy_ci95_lower_positive",
        ),
        Figure(
            f"h{horizon}_deflated_sharpe_lower", f"{prefix}.metrics.deflated_sharpe_lower",
            "ratio4", "> 0", f"{prefix}.checks.deflated_sharpe_lower_positive",
        ),
        Figure(
            f"h{horizon}_ece", f"{prefix}.metrics.expected_calibration_error",
            "ratio4", "≤ 0.05", f"{prefix}.checks.calibration_ece_within_limit",
        ),
    )


def _horizon_table_row(horizon: int) -> str:
    return (
        f"| **{horizon}d** | `{{h{horizon}_selected_trial}}` | "
        f"`{{h{horizon}_paired_ci_lower}}` (>0) {{h{horizon}_paired_ci_lower_badge}} | "
        f"`{{h{horizon}_expectancy_ci_lower}}` (>0) {{h{horizon}_expectancy_ci_lower_badge}} | "
        f"`{{h{horizon}_deflated_sharpe_lower}}` (>0) {{h{horizon}_deflated_sharpe_lower_badge}} | "
        f"`{{h{horizon}_ece}}` (≤0.05) {{h{horizon}_ece_badge}} | "
        f"{{h{horizon}_status}} |"
    )


def _build_directional_daily_gate_spec(horizons: Sequence[int]) -> GateReportSpec:
    """Generalizes build_pead_catalyst_model.py's doc-generation pattern
    (see edge.research.reporting's module docstring) to gate path #1: the
    daily-directional family, governed by evaluate_daily_directional_development_gate
    in gates.py and driven from here. Every figure below traces to a key in
    report.json (as written by `_write_json(run_dir / "report.json", report)`
    a few lines above `main()`) -- a metric absent from it raises rather than
    rendering, exactly the property GATE_XS3_RESULT.md and GATE_PEAD_RESULT.md
    did not have (edge/docs/STATUS.md:21, :113).
    """
    figures: list[Figure] = [
        Figure("status", "status", "str"),
        Figure("development_gate_status", "development_gate.status", "str"),
        Figure("passing_horizons", "development_gate.passing_horizons", "str"),
        Figure("failed_horizons", "development_gate.failed_horizons", "str"),
        Figure("required_horizons", "development_gate.required_horizons", "str"),
        Figure("failed_checks", "development_gate.failed_checks", "str"),
        Figure("symbols", "symbols", "int"),
        Figure("development_bar_dates", "development_bar_dates", "int"),
        Figure("experiment_id", "experiment_id", "str"),
        Figure("code_version", "code_version", "str"),
        Figure("data_fingerprint", "data_fingerprint", "str"),
        Figure("terminal_holdout_id", "terminal_holdout_id", "str"),
        Figure("terminal_holdout_opened", "terminal_holdout_opened", "bool"),
    ]
    for horizon in horizons:
        figures.extend(_horizon_figures(horizon))

    rows = "\n".join(_horizon_table_row(horizon) for horizon in horizons)

    def _daily_directional_badge(status: object) -> str:
        text = str(status).strip().upper()
        if text.startswith("DEVELOPMENT_PASS") or text == "PASS_DEVELOPMENT_ONLY":
            return "\U0001f7e2 **" + str(status) + "**"
        return "\U0001f534 **" + str(status) + "**"

    template = f"""# Daily-Directional Development Gate Result

**Rendered**: {{generated_at}}
**Artifact**: `{{artifact_path}}` (sha256 `{{artifact_hash}}`)
**Experiment**: `{{experiment_id}}`
**Verdict**: {{verdict_badge}}

---

## Protocol

`required_horizons` = `{{required_horizons}}`. `passing_horizons` = `{{passing_horizons}}`.
`failed_horizons` = `{{failed_horizons}}`. `failed_checks` (protocol-level) = `{{failed_checks}}`.

A protocol error, or zero horizons passing, fails the whole call regardless of
any individual horizon's own result -- see `edge/research/gates.py`'s module
docstring ("Decision tree"). Terminal holdout: `{{terminal_holdout_id}}`,
opened = `{{terminal_holdout_opened}}` (must be `no` on every path through this
gate, passing or failing -- this gate cannot open it).

---

## Per-Horizon Result

Each horizon needs ALL FOUR checks to pass (`gates.py`: "no partial credit").
Every cell below is pulled from `horizons.<h>.development_gate.*` in the
artifact -- see `edge/research/runner.py::_horizon_figures`.

| Horizon | Selected trial | Paired CI lower vs momentum | Candidate expectancy CI lower | Deflated Sharpe lower | ECE | Status |
|---|---|---|---|---|---|---|
{rows}

---

## Run Context

Universe: {{symbols}} symbols, {{development_bar_dates}} development bar-dates.
Code version `{{code_version}}`, data fingerprint `{{data_fingerprint}}`.

---

## Provenance

Rendered from `{{artifact_path}}` by `edge.research.reporting.write_gate_doc`,
called from `edge/research/runner.py::main()` immediately after that file is
written. A PASS here means "eligible for further shadow research," not
"cleared to look at holdout" -- see `gates.py`'s module docstring.
"""
    return GateReportSpec(
        gate_family="daily-directional",
        verdict_key_path="development_gate.status",
        figures=tuple(figures),
        template=template,
        verdict_badge_fn=_daily_directional_badge,
    )


DIRECTIONAL_DAILY_GATE_SPEC = _build_directional_daily_gate_spec(FROZEN_HORIZONS)


def render_directional_daily_result_doc(report_path: Path, *, doc_path: Path | None = None) -> str:
    """Render DIRECTIONAL_DAILY_RESULT.md from the report.json a run just
    wrote. Raises (edge.research.reporting.MetricNotFoundError) if any
    declared figure is absent from it."""
    target = doc_path or (EDGE_ROOT / "docs" / "DIRECTIONAL_DAILY_RESULT.md")
    content = write_gate_doc(artifact_path=report_path, spec=DIRECTIONAL_DAILY_GATE_SPEC, doc_path=target)
    print(f"wrote {target}")
    return content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frozen daily directional research")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DAILY_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--development-end", default=ResearchProtocol.development_end)
    parser.add_argument("--include-xgboost", action="store_true",
                        help="preregister the fixed CPU-only XGBoost challenger alongside the frozen simple menu")
    parser.add_argument(
        "--include-simple-hypotheses",
        action="store_true",
        help="preregister the two fixed causal shock/sector-residual hypotheses",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = ResearchProtocol(development_end=args.development_end)
    result = run_preregistered_research(
        protocol=protocol, universe_path=args.universe,
        data_dir=args.data_dir, output_root=args.output_root,
        include_xgboost=args.include_xgboost,
        include_simple_hypotheses=args.include_simple_hypotheses,
    )
    if args.json:
        print(json.dumps(_json_value(result), sort_keys=True, separators=(",", ":")))
    else:
        print(f"{result['status']}: {result['experiment_id']}")
        for horizon, row in result["horizons"].items():
            metrics = row["metrics_by_trial"][row["selected_trial"]]
            print(f"{horizon}d {row['selected_trial']}: net={metrics['net_expectancy']:.6f} "
                  f"CI95 lower={metrics['net_expectancy_ci95_lower']:.6f} "
                  f"DSR lower={metrics['deflated_sharpe_lower']:.3f}")
        print("Terminal holdout remains sealed; no live or options authorization.")

    # report.json's own on-disk location is deterministic from output_root and
    # the experiment id this same call just produced (run_dir = output_root /
    # experiment_id, per run_preregistered_research above) -- render gate path
    # #1's result doc from that file, not from `result` directly, so it goes
    # through the same artifact-on-disk discipline as the other two gate paths.
    report_path = Path(args.output_root) / result["experiment_id"] / "report.json"
    render_directional_daily_result_doc(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
