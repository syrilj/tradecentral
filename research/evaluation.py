"""Nested, date-grouped evaluation for the frozen simple daily models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .costs import UnderlyingCostModel
from .challengers import FixedMenuXGBoostChallenger, XGBOOST_CPU_MENU
from .features import feature_columns
from .models import RegularizedLogisticBaseline
from .panel_splits import NestedPanelWalkForwardFold
from .statistics import (
    bonferroni_deflated_sharpe_approximation,
    date_block_bootstrap_ci,
)


@dataclass(frozen=True)
class TrialSpec:
    name: str
    model: str
    config: Mapping[str, Any]
    features: tuple[str, ...]


def simple_trial_specs(horizon_days: int) -> tuple[TrialSpec, ...]:
    """Frozen simple search menu; changing it creates a new experiment hash."""
    horizon = int(horizon_days)
    return (
        TrialSpec(
            f"momentum_{horizon}d",
            "momentum",
            {"horizon_days": horizon, "score": f"momentum_{horizon}d"},
            (f"momentum_{horizon}d",),
        ),
        TrialSpec(
            f"volatility_scaled_momentum_{horizon}d",
            "volatility_scaled_momentum",
            {"horizon_days": horizon, "score": f"volatility_scaled_momentum_{horizon}d"},
            (f"volatility_scaled_momentum_{horizon}d",),
        ),
        TrialSpec(
            f"regularized_logistic_c0.1_{horizon}d",
            "regularized_logistic",
            {"horizon_days": horizon, "C": 0.1},
            feature_columns(),
        ),
        TrialSpec(
            f"regularized_logistic_c1.0_{horizon}d",
            "regularized_logistic",
            {"horizon_days": horizon, "C": 1.0},
            feature_columns(),
        ),
    )


def xgboost_trial_specs(horizon_days: int) -> tuple[TrialSpec, ...]:
    """Fixed CPU challenger menu; included only by explicit runner opt-in."""
    horizon = int(horizon_days)
    return tuple(
        TrialSpec(
            f"xgboost_{name}_{horizon}d",
            "cpu_xgboost",
            {"horizon_days": horizon, "menu_name": name, "config": dict(config)},
            feature_columns(),
        )
        for name, config in XGBOOST_CPU_MENU.items()
    )


def simple_hypothesis_trial_specs(horizon_days: int) -> tuple[TrialSpec, ...]:
    """Two fixed, theory-driven hypotheses; there is no parameter search."""
    horizon = int(horizon_days)
    if horizon == 5:
        return (
            TrialSpec(
                "shock_reversal_fixed_1.5_5d",
                "fixed_feature_score",
                {
                    "horizon_days": 5,
                    "score": "shock_reversal_score_5d",
                    "eligibility": "shock_reversal_eligible_5d",
                    "fixed_probability_threshold": 0.5,
                    "hypothesis": "volatility_normalized_one_day_shock_reversal",
                    "shock_abs_threshold": 1.5,
                },
                ("shock_reversal_score_5d", "shock_reversal_eligible_5d"),
            ),
        )
    if horizon == 20:
        return (
            TrialSpec(
                "sector_residual_momentum_fixed_30_70_20d",
                "fixed_feature_score",
                {
                    "horizon_days": 20,
                    "score": "sector_residual_score_20d",
                    "eligibility": "sector_residual_eligible_20d",
                    "fixed_probability_threshold": 0.5,
                    "hypothesis": "sector_residual_volatility_scaled_momentum",
                    "cross_sectional_percentile_lower": 0.30,
                    "cross_sectional_percentile_upper": 0.70,
                },
                ("sector_residual_score_20d", "sector_residual_eligible_20d"),
            ),
        )
    return ()


def trial_specs(
    horizon_days: int,
    *,
    include_xgboost: bool = False,
    include_simple_hypotheses: bool = False,
) -> tuple[TrialSpec, ...]:
    """Return the unchanged simple menu plus opt-in preregistered challengers."""
    simple = simple_trial_specs(horizon_days)
    xgboost = xgboost_trial_specs(horizon_days) if include_xgboost else ()
    hypotheses = simple_hypothesis_trial_specs(horizon_days) if include_simple_hypotheses else ()
    return simple + xgboost + hypotheses


def raw_scores(
    spec: TrialSpec,
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    label_column: str,
) -> tuple[pd.Series, Any | None]:
    """Fit only when required and return an up-direction score on test rows."""
    if spec.model in {"momentum", "volatility_scaled_momentum"}:
        key = str(spec.config["score"])
        return pd.to_numeric(test[key], errors="coerce").rename("raw_score"), None
    if spec.model == "fixed_feature_score":
        key = str(spec.config["score"])
        return pd.to_numeric(test[key], errors="coerce").rename("raw_score"), None
    if spec.model == "regularized_logistic":
        model = RegularizedLogisticBaseline(C=float(spec.config["C"]))
        model.fit(train.loc[:, spec.features], train[label_column])
        probability = model.predict_proba(test.loc[:, spec.features])
        # Platt calibration below expects a real-valued score.  Log-odds avoids
        # compressing already-probabilistic logistic output a second time.
        clipped = probability.clip(1e-6, 1 - 1e-6)
        return np.log(clipped.div(1.0 - clipped)).rename("raw_score"), model
    if spec.model == "cpu_xgboost":
        model = FixedMenuXGBoostChallenger(menu_name=str(spec.config["menu_name"]), feature_names=spec.features)
        model.fit(train.loc[:, spec.features], train[label_column])
        probability = model.predict_proba(test.loc[:, spec.features])
        clipped = probability.clip(1e-6, 1 - 1e-6)
        return np.log(clipped.div(1.0 - clipped)).rename("raw_score"), model
    raise ValueError(f"unsupported simple model: {spec.model}")


@dataclass(frozen=True)
class PlattMap:
    coefficient: float
    intercept: float

    def apply(self, scores: Iterable[float]) -> np.ndarray:
        values = np.asarray(list(scores), dtype=float)
        logits = self.coefficient * values + self.intercept
        return 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))


def fit_platt(scores: Iterable[float], labels: Iterable[int]) -> PlattMap:
    values = np.asarray(list(scores), dtype=float)
    target = np.asarray(list(labels), dtype=float)
    usable = np.isfinite(values) & np.isin(target, (0.0, 1.0))
    if usable.sum() < 20 or np.unique(target[usable]).size != 2:
        raise ValueError("Platt calibration requires at least 20 rows and both classes")
    estimator = LogisticRegression(C=1_000_000.0, solver="lbfgs", max_iter=1_000)
    estimator.fit(values[usable].reshape(-1, 1), target[usable].astype(int))
    return PlattMap(float(estimator.coef_[0, 0]), float(estimator.intercept_[0]))


def positions_from_probability(probability: Iterable[float], threshold: float) -> np.ndarray:
    if not 0.5 <= threshold < 1.0:
        raise ValueError("threshold must be in [0.5, 1)")
    values = np.asarray(list(probability), dtype=float)
    return np.where(values >= threshold, 1, np.where(values <= 1.0 - threshold, -1, 0)).astype(int)


def eligibility_for_spec(spec: TrialSpec, rows: pd.DataFrame) -> np.ndarray:
    """Return the preregistered eligibility mask, or all rows for ordinary models."""
    field = spec.config.get("eligibility")
    if field is None:
        return np.ones(len(rows), dtype=bool)
    if not isinstance(field, str) or field not in rows:
        raise ValueError(f"missing preregistered eligibility field: {field}")
    values = rows[field]
    if values.isna().any() or not values.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError(f"eligibility field must be complete boolean data: {field}")
    return values.to_numpy(dtype=bool)


def positions_for_spec(
    spec: TrialSpec,
    probability: Iterable[float],
    threshold: float,
    rows: pd.DataFrame,
    *,
    raw_score: Iterable[float] | None = None,
) -> np.ndarray:
    if spec.model == "fixed_feature_score":
        if raw_score is None:
            raise ValueError("fixed feature score requires raw scores for its preregistered direction")
        score = np.asarray(list(raw_score), dtype=float)
        if score.size != len(rows) or not np.isfinite(score).all():
            raise ValueError("fixed feature raw scores must be complete and finite")
        position = np.sign(score).astype(int)
    else:
        position = positions_from_probability(probability, threshold)
    position[~eligibility_for_spec(spec, rows)] = 0
    return position


def _net_returns(position: np.ndarray, forward_return: np.ndarray,
                 costs: UnderlyingCostModel) -> np.ndarray:
    active_cost = np.where(position != 0, costs.round_trip_cost_return, 0.0)
    return position.astype(float) * forward_return.astype(float) - active_cost


def select_threshold(
    probability: Iterable[float],
    forward_return: Iterable[float],
    dates: Iterable[object],
    *,
    costs: UnderlyingCostModel,
    thresholds: Iterable[float] = (0.50, 0.55, 0.60, 0.65),
    min_active_dates: int = 20,
) -> tuple[float, dict[str, float]]:
    """Choose a threshold on training-fold OOF predictions only."""
    probability_values = np.asarray(list(probability), dtype=float)
    forward_values = np.asarray(list(forward_return), dtype=float)
    date_values = pd.to_datetime(list(dates), errors="coerce")
    best: tuple[float, float, float, int] | None = None
    for threshold in thresholds:
        position = positions_from_probability(probability_values, float(threshold))
        net = _net_returns(position, forward_values, costs)
        active_dates = int(pd.DatetimeIndex(date_values[position != 0]).normalize().nunique())
        if active_dates < min_active_dates:
            continue
        daily = pd.DataFrame({"date": date_values, "net": net}).groupby("date", sort=True)["net"].mean()
        score = float(daily.mean())
        candidate = (score, float(threshold), float(np.mean(position != 0)), active_dates)
        # Equal expectancy chooses the more conservative threshold.
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        raise ValueError("no threshold has sufficient active training dates")
    return best[1], {"training_net_expectancy": best[0], "training_active_rate": best[2],
                     "training_active_dates": float(best[3])}


def select_threshold_for_spec(
    spec: TrialSpec,
    probability: Iterable[float],
    forward_return: Iterable[float],
    dates: Iterable[object],
    rows: pd.DataFrame,
    *,
    costs: UnderlyingCostModel,
    raw_score: Iterable[float] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Use a preregistered fixed rule or the ordinary train-only threshold search."""
    fixed = spec.config.get("fixed_probability_threshold")
    if fixed is None:
        return select_threshold(probability, forward_return, dates, costs=costs)
    threshold = float(fixed)
    probability_values = np.asarray(list(probability), dtype=float)
    forward_values = np.asarray(list(forward_return), dtype=float)
    date_values = pd.to_datetime(list(dates), errors="coerce")
    position = positions_for_spec(
        spec, probability_values, threshold, rows, raw_score=raw_score,
    )
    net = _net_returns(position, forward_values, costs)
    active_dates = int(pd.DatetimeIndex(date_values[position != 0]).normalize().nunique())
    if active_dates < 20:
        raise ValueError("fixed preregistered threshold has insufficient active training dates")
    daily = pd.DataFrame({"date": date_values, "net": net}).groupby(
        "date", sort=True,
    )["net"].mean()
    return threshold, {
        "threshold_policy": "fixed_preregistered",
        "direction_policy": "sign_of_preregistered_raw_score",
        "training_net_expectancy": float(daily.mean()),
        "training_active_rate": float(np.mean(position != 0)),
        "training_active_dates": float(active_dates),
    }


def _crossfit_inner(
    records: pd.DataFrame,
    fold: NestedPanelWalkForwardFold,
    spec: TrialSpec,
    *,
    label_column: str,
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for inner in fold.inner:
        train = records.iloc[inner.train_indices]
        validation = records.iloc[inner.validation_indices]
        score, _ = raw_scores(spec, train, validation, label_column=label_column)
        piece = validation.loc[:, [label_column]].copy()
        piece["raw_score"] = score
        pieces.append(piece)
    if not pieces:
        raise ValueError("nested fold has no inner OOF predictions")
    return pd.concat(pieces).sort_index()


def evaluate_trial_on_outer_fold(
    records: pd.DataFrame,
    fold: NestedPanelWalkForwardFold,
    spec: TrialSpec,
    *,
    horizon_days: int,
    costs: UnderlyingCostModel,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select calibration/threshold inside the outer training set, then score."""
    label_column = f"direction_{horizon_days}d"
    return_column = f"forward_return_{horizon_days}d"
    inner = _crossfit_inner(records, fold, spec, label_column=label_column)
    inner_full = records.loc[inner.index]
    calibrator = fit_platt(inner["raw_score"], inner[label_column])
    inner_probability = calibrator.apply(inner["raw_score"])
    threshold, threshold_metrics = select_threshold_for_spec(
        spec,
        inner_probability,
        inner_full[return_column],
        inner.index.get_level_values("timestamp"),
        inner_full,
        costs=costs,
        raw_score=inner["raw_score"],
    )
    outer_train = records.iloc[fold.outer.train_indices]
    outer_validation = records.iloc[fold.outer.validation_indices]
    score, _ = raw_scores(spec, outer_train, outer_validation, label_column=label_column)
    probability = calibrator.apply(score)
    position = positions_for_spec(
        spec, probability, threshold, outer_validation, raw_score=score,
    )
    result = outer_validation.loc[:, [label_column, return_column, "sector",
                                       "volatility_regime", "trend_regime", "bear_market"]].copy()
    result["trial"] = spec.name
    result["fold"] = fold.outer.fold
    result["raw_score"] = score
    result["probability"] = probability
    result["eligible"] = eligibility_for_spec(spec, outer_validation)
    result["position"] = position
    result["gross_return"] = position * result[return_column].to_numpy(dtype=float)
    result["net_return"] = _net_returns(position, result[return_column].to_numpy(dtype=float), costs)
    result["threshold"] = threshold
    metadata = {
        "trial": spec.name,
        "fold": fold.outer.fold,
        "calibration": asdict(calibrator),
        "threshold": threshold,
        **threshold_metrics,
    }
    return result, metadata


def expected_calibration_error(probability: Iterable[float], labels: Iterable[int],
                               *, bins: int = 10) -> float:
    p = np.asarray(list(probability), dtype=float)
    y = np.asarray(list(labels), dtype=float)
    usable = np.isfinite(p) & np.isin(y, (0.0, 1.0))
    if not usable.any():
        raise ValueError("calibration metrics require finite probability/labels")
    p, y = p[usable], y[usable]
    edges = np.linspace(0.0, 1.0, bins + 1)
    bucket = np.minimum(np.digitize(p, edges[1:-1], right=False), bins - 1)
    return float(sum(
        abs(float(y[bucket == idx].mean()) - float(p[bucket == idx].mean()))
        * float(np.mean(bucket == idx))
        for idx in range(bins) if np.any(bucket == idx)
    ))


def evidence_metrics(rows: pd.DataFrame, *, label_column: str,
                     trial_count: int, horizon_days: int) -> dict[str, Any]:
    if rows.empty:
        raise ValueError("cannot score empty OOF evidence")
    if horizon_days < 1:
        raise ValueError("horizon_days must be positive")
    dates = rows.index.get_level_values("timestamp")
    block_size = max(5, int(horizon_days))
    ci = date_block_bootstrap_ci(rows["net_return"], dates, block_size=block_size, seed=0)
    daily = rows.assign(trading_date=dates).groupby("trading_date", sort=True)["net_return"].mean()
    periods_per_year = max(1, 252 // int(horizon_days))
    dsr = bonferroni_deflated_sharpe_approximation(
        daily, trial_count=trial_count, periods_per_year=periods_per_year,
    )
    equity = (1.0 + daily).cumprod()
    drawdown = equity.div(equity.cummax()).sub(1.0)
    probability = pd.to_numeric(rows["probability"], errors="coerce")
    labels = pd.to_numeric(rows[label_column], errors="coerce")
    brier = float(np.mean(np.square(probability - labels)))
    return {
        "rows": int(len(rows)),
        "dates": int(pd.DatetimeIndex(dates).normalize().nunique()),
        "return_horizon_days": int(horizon_days),
        "bootstrap_block_dates": block_size,
        "sharpe_periods_per_year": periods_per_year,
        "active_rate": float(np.mean(rows["position"].to_numpy() != 0)),
        "net_expectancy": float(ci.estimate),
        "net_expectancy_ci95_lower": float(ci.lower),
        "net_expectancy_ci95_upper": float(ci.upper),
        "observed_sharpe": float(dsr.observed_sharpe),
        "deflated_sharpe_lower": float(dsr.lower_bound_sharpe),
        # This compounds overlapping fixed-horizon cohorts and is therefore a
        # stress diagnostic, not a deployable portfolio drawdown.  The <=8%
        # promotion gate is evaluated later on non-overlapping option shadow
        # positions with actual risk caps.
        "overlapping_cohort_drawdown_diagnostic": float(drawdown.min()),
        "brier_score": brier,
        "expected_calibration_error": expected_calibration_error(probability, labels),
        "direction_accuracy": float(np.mean((probability >= 0.5).astype(int) == labels.astype(int))),
    }


def paired_baseline_difference_metrics(
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    horizon_days: int,
) -> dict[str, Any]:
    """Date-block inference on candidate minus frozen-baseline net returns."""
    joined = candidate.loc[:, ["net_return"]].rename(
        columns={"net_return": "candidate"}
    ).join(
        baseline.loc[:, ["net_return"]].rename(columns={"net_return": "baseline"}),
        how="inner",
    )
    if joined.empty:
        raise ValueError("candidate and baseline have no paired OOF rows")
    difference = joined["candidate"] - joined["baseline"]
    dates = joined.index.get_level_values("timestamp")
    block_size = max(5, int(horizon_days))
    ci = date_block_bootstrap_ci(difference, dates, block_size=block_size, seed=0)
    return {
        "paired_rows": int(len(joined)),
        "paired_dates": int(pd.DatetimeIndex(dates).normalize().nunique()),
        "net_expectancy_difference": float(ci.estimate),
        "net_expectancy_difference_ci95_lower": float(ci.lower),
        "net_expectancy_difference_ci95_upper": float(ci.upper),
        "bootstrap_block_dates": block_size,
    }


def grouped_evidence(rows: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Compact performance slices by required symbol/sector/regime fields."""
    work = rows.reset_index()
    dimensions = {
        "symbol": ["symbol"],
        "sector": ["sector"],
        "volatility": ["volatility_regime"],
        "trend": ["trend_regime"],
        "bear_market": ["bear_market"],
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for name, columns in dimensions.items():
        grouped = work.groupby(columns, dropna=False, sort=True)["net_return"]
        table = grouped.agg(["count", "mean", "median"]).reset_index()
        table = table.rename(columns={"count": "n", "mean": "mean_net_return",
                                      "median": "median_net_return"})
        output[name] = table.to_dict("records")
    return output
