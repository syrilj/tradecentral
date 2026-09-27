"""Leakage-safe daily directional model bake-off (research generation v2).

The module deliberately keeps the model menu and feature set small and fixed.
It evaluates every model on expanding, purged walk-forward folds, calibrates on
the tail of each training fold, and records confidence percentile relative to
that calibration slice.  A high probability is therefore useful only when it
also ranks future observations well; calibration alone cannot win the gate.

The terminal holdout beginning 2026-07-13 is never loaded by this module.
Artifacts produced here are research-only until a separate prospective
promotion process supplies enough untouched evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from .daily_data import load_daily_universe
from .hashing import stable_hash
from .labels import FROZEN_HORIZONS, tradable_directional_labels
from .panel_splits import expanding_panel_walk_forward_splits, trading_dates
from .statistics import date_block_bootstrap_ci


EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE_PATH = EDGE_ROOT / "config" / "universe_directional_v2.json"
DEFAULT_DATA_DIR = EDGE_ROOT / "data" / "1d"
DEFAULT_OUTPUT_DIR = EDGE_ROOT / "runs" / "directional_bakeoff_v2"
MODEL_MENU = ("momentum", "elastic_net", "hist_gradient_boosting", "extra_trees", "xgboost", "soft_vote")
BASE_MODEL_MENU = tuple(name for name in MODEL_MENU if name not in {"momentum", "soft_vote"})
SELECTION_COVERAGES = (0.02, 0.05, 0.10, 0.20, 1.0)
PRIMARY_COVERAGE = 0.10


@dataclass(frozen=True)
class BakeoffProtocol:
    development_start: str = "2018-01-02"
    validation_start: str = "2022-01-03"
    selection_end: str = "2024-12-31"
    confirmation_start: str = "2025-01-02"
    development_end: str = "2026-07-10"
    terminal_holdout_start: str = "2026-07-13"
    terminal_holdout_end: str = "2027-01-29"
    validation_dates: int = 126
    calibration_dates: int = 252
    partial_validation_min_dates: int = 60
    round_trip_cost_bps: float = 10.0
    bootstrap_samples: int = 1_000
    random_state: int = 20260802

    def __post_init__(self) -> None:
        ordered = [
            pd.Timestamp(self.development_start),
            pd.Timestamp(self.validation_start),
            pd.Timestamp(self.selection_end),
            pd.Timestamp(self.confirmation_start),
            pd.Timestamp(self.development_end),
            pd.Timestamp(self.terminal_holdout_start),
            pd.Timestamp(self.terminal_holdout_end),
        ]
        if ordered != sorted(ordered) or ordered[4] >= ordered[5]:
            raise ValueError("bake-off dates must be ordered before the sealed holdout")
        if min(self.validation_dates, self.calibration_dates, self.partial_validation_min_dates) < 20:
            raise ValueError("walk-forward windows are too short")
        if self.round_trip_cost_bps < 0 or self.bootstrap_samples < 100:
            raise ValueError("invalid cost or bootstrap configuration")


RAW_FEATURES = (
    "return_1d", "return_2d", "return_5d", "return_10d", "return_20d",
    "return_63d", "return_126d", "return_252d", "volatility_5d",
    "volatility_20d", "volatility_63d", "downside_volatility_20d",
    "vol_scaled_return_20d", "atr_pct_14d", "rsi_14d", "range_position_20d",
    "range_position_63d", "gap_1d", "intraday_return_1d", "volume_z_20d",
    "dollar_volume_z_20d", "amihud_20d", "market_return_1d", "market_return_5d",
    "market_return_20d", "market_return_63d", "market_volatility_20d",
    "market_above_sma_200d", "gex_regime_proxy", "sector_relative_return_5d",
    "sector_relative_return_10d", "sector_relative_return_20d",
    "sector_relative_return_63d",
)
RANK_BASES = (
    "return_1d", "return_5d", "return_10d", "return_20d", "return_63d",
    "return_126d", "volatility_20d", "vol_scaled_return_20d",
    "range_position_20d", "volume_z_20d", "gap_1d",
    "sector_relative_return_10d", "sector_relative_return_20d",
    "sector_relative_return_63d",
)
FEATURE_COLUMNS = RAW_FEATURES + tuple(f"cross_sectional_rank_{name}" for name in RANK_BASES)


def load_universe(path: str | Path = DEFAULT_UNIVERSE_PATH) -> tuple[list[str], dict[str, str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    symbols = [str(value).strip().upper() for value in raw.get("symbols", []) if str(value).strip()]
    if not symbols:
        raise ValueError("directional bake-off universe is empty")
    sectors: dict[str, str] = {}
    for sector, members in (raw.get("sectors") or {}).items():
        for member in members if isinstance(members, list) else ():
            sectors.setdefault(str(member).strip().upper(), str(sector))
    return symbols, {symbol: sectors.get(symbol, "unclassified") for symbol in symbols}


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1.0 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / window, adjust=False).mean()
    return 100.0 - 100.0 / (1.0 + gain.div(loss.replace(0.0, np.nan)))


def _symbol_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    open_ = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change()
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1,
    ).max(axis=1)
    out = pd.DataFrame(index=frame.index)
    for horizon in (1, 2, 5, 10, 20, 63, 126, 252):
        out[f"return_{horizon}d"] = close.pct_change(horizon)
    for window in (5, 20, 63):
        out[f"volatility_{window}d"] = returns.rolling(window, min_periods=window).std(ddof=0)
    downside = returns.clip(upper=0.0)
    out["downside_volatility_20d"] = downside.rolling(20, min_periods=20).std(ddof=0)
    out["vol_scaled_return_20d"] = out["return_20d"].div(out["volatility_20d"].replace(0.0, np.nan))
    out["atr_pct_14d"] = true_range.ewm(alpha=1.0 / 14, adjust=False).mean().div(close)
    out["rsi_14d"] = _rsi(close).div(100.0)
    for window in (20, 63):
        lo = low.rolling(window, min_periods=window).min()
        hi = high.rolling(window, min_periods=window).max()
        out[f"range_position_{window}d"] = close.sub(lo).div(hi.sub(lo).replace(0.0, np.nan))
    out["gap_1d"] = open_.div(previous).sub(1.0)
    out["intraday_return_1d"] = close.div(open_).sub(1.0)
    volume_mean = volume.rolling(20, min_periods=20).mean()
    volume_std = volume.rolling(20, min_periods=20).std(ddof=0).replace(0.0, np.nan)
    out["volume_z_20d"] = volume.sub(volume_mean).div(volume_std)
    dollar_volume = np.log1p(close.mul(volume).clip(lower=0.0))
    out["dollar_volume_z_20d"] = dollar_volume.sub(
        dollar_volume.rolling(20, min_periods=20).mean()
    ).div(dollar_volume.rolling(20, min_periods=20).std(ddof=0).replace(0.0, np.nan))
    out["amihud_20d"] = returns.abs().div(close.mul(volume).replace(0.0, np.nan)).rolling(
        20, min_periods=20,
    ).mean()
    return out.replace([np.inf, -np.inf], np.nan)


def build_decision_features(bars: pd.DataFrame, sectors: Mapping[str, str]) -> pd.DataFrame:
    """Build features available at the prior close for each decision-day open."""
    if not isinstance(bars.index, pd.MultiIndex) or list(bars.index.names) != ["timestamp", "symbol"]:
        raise ValueError("bars must have a sorted (timestamp, symbol) MultiIndex")
    pieces: list[pd.DataFrame] = []
    for symbol, frame in bars.groupby(level="symbol", sort=True):
        values = _symbol_features(frame.droplevel("symbol"))
        values["symbol"] = str(symbol)
        pieces.append(values.reset_index().set_index(["timestamp", "symbol"]))
    features = pd.concat(pieces).sort_index()
    timestamps = features.index.get_level_values("timestamp")
    symbols = features.index.get_level_values("symbol")
    sector = pd.Series(symbols.map(lambda symbol: sectors.get(str(symbol), "unclassified")), index=features.index)

    benchmark_symbol = "SPY" if "SPY" in symbols else str(symbols[0])
    benchmark = features.xs(benchmark_symbol, level="symbol")
    market_map = {
        "market_return_1d": "return_1d", "market_return_5d": "return_5d",
        "market_return_20d": "return_20d", "market_return_63d": "return_63d",
        "market_volatility_20d": "volatility_20d",
    }
    for output, source in market_map.items():
        features[output] = timestamps.map(benchmark[source])
    benchmark_bars = bars.xs(benchmark_symbol, level="symbol")
    benchmark_above = benchmark_bars["close"].gt(
        benchmark_bars["close"].rolling(200, min_periods=200).mean(),
    ).astype(float)
    features["market_above_sma_200d"] = timestamps.map(benchmark_above)

    # GEX & Volatility-Regime proxy feature:
    mkt_vol = features["market_volatility_20d"]
    rp20 = features["range_position_20d"]
    features["gex_regime_proxy"] = np.where(
        (mkt_vol < 0.012) & (rp20 > 0.5), 1.0,
        np.where((mkt_vol > 0.020) | (rp20 < 0.2), -1.0, 0.0),
    )

    temp = features.loc[:, ["return_5d", "return_10d", "return_20d", "return_63d"]].copy()
    temp["timestamp_key"] = timestamps
    temp["sector_key"] = sector.to_numpy()
    for horizon in (5, 10, 20, 63):
        group_mean = temp.groupby(["timestamp_key", "sector_key"], sort=False)[f"return_{horizon}d"].transform("mean")
        features[f"sector_relative_return_{horizon}d"] = temp[f"return_{horizon}d"].sub(group_mean)
    for name in RANK_BASES:
        features[f"cross_sectional_rank_{name}"] = features[name].groupby(
            level="timestamp", sort=False,
        ).rank(pct=True).sub(0.5).mul(2.0)

    # Decision at session t uses the complete feature vector from session t-1.
    decision = features.loc[:, FEATURE_COLUMNS].groupby(level="symbol", sort=False).shift(1)
    return decision.replace([np.inf, -np.inf], np.nan).sort_index()


def build_research_records(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    *,
    horizon_days: int,
    protocol: BakeoffProtocol,
) -> pd.DataFrame:
    labels: list[pd.DataFrame] = []
    for symbol, frame in bars.groupby(level="symbol", sort=True):
        item = tradable_directional_labels(frame.droplevel("symbol"), horizons=FROZEN_HORIZONS)
        item["symbol"] = symbol
        labels.append(item.reset_index().set_index(["timestamp", "symbol"]))
    label_panel = pd.concat(labels).sort_index()
    label = f"direction_{horizon_days}d"
    forward = f"forward_return_{horizon_days}d"
    target_end = f"target_end_{horizon_days}d"
    records = features.join(label_panel.loc[:, [label, forward, target_end]])
    dates = records.index.get_level_values("timestamp")
    start, end = pd.Timestamp(protocol.development_start), pd.Timestamp(protocol.development_end)
    resolved = pd.to_datetime(records[target_end], errors="coerce")
    records = records.loc[
        (dates >= start) & (dates <= end) & resolved.notna() & (resolved <= end)
        & records[label].notna() & records.loc[:, FEATURE_COLUMNS].notna().all(axis=1)
    ].copy()
    records[label] = records[label].astype(int)
    if records.empty:
        raise ValueError(f"no complete development records for {horizon_days}d")
    return records.sort_index()


class BetaCalibrator:
    """Three-parameter beta calibration map fitted on a dedicated time slice."""

    def __init__(self) -> None:
        self.estimator = LogisticRegression(C=10.0, solver="lbfgs", max_iter=1_000, random_state=0)

    @staticmethod
    def _matrix(probability: Iterable[float]) -> np.ndarray:
        p = np.clip(np.asarray(list(probability), dtype=float), 1e-6, 1.0 - 1e-6)
        return np.column_stack([np.log(p), -np.log1p(-p)])

    def fit(self, probability: Iterable[float], labels: Iterable[int]) -> "BetaCalibrator":
        y = np.asarray(list(labels), dtype=int)
        if y.size < 100 or np.unique(y).size != 2:
            raise ValueError("beta calibration requires at least 100 rows and both classes")
        self.estimator.fit(self._matrix(probability), y)
        return self

    def apply(self, probability: Iterable[float]) -> np.ndarray:
        return self.estimator.predict_proba(self._matrix(probability))[:, 1]


class ScoreCalibrator:
    """Platt map for ordinal scores such as frozen momentum."""

    def __init__(self) -> None:
        self.estimator = LogisticRegression(C=10.0, solver="lbfgs", max_iter=1_000, random_state=0)

    def fit(self, scores: Iterable[float], labels: Iterable[int]) -> "ScoreCalibrator":
        x = np.asarray(list(scores), dtype=float).reshape(-1, 1)
        y = np.asarray(list(labels), dtype=int)
        if y.size < 100 or np.unique(y).size != 2:
            raise ValueError("score calibration requires at least 100 rows and both classes")
        self.estimator.fit(x, y)
        return self

    def apply(self, scores: Iterable[float]) -> np.ndarray:
        return self.estimator.predict_proba(np.asarray(list(scores), dtype=float).reshape(-1, 1))[:, 1]


def _make_model(name: str, *, seed: int) -> Any:
    if name == "elastic_net":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", RobustScaler(quantile_range=(10.0, 90.0))),
            ("model", LogisticRegression(
                penalty="elasticnet", solver="saga", C=0.05, l1_ratio=0.50,
                max_iter=5_000, tol=1e-3, random_state=seed,
            )),
        ])
    if name == "hist_gradient_boosting":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.02, max_iter=120, max_leaf_nodes=8,
                min_samples_leaf=150, l2_regularization=10.0,
                random_state=seed,
            )),
        ])
    if name == "extra_trees":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", ExtraTreesClassifier(
                n_estimators=300, max_depth=5, min_samples_leaf=120,
                max_features=0.50, class_weight="balanced_subsample",
                n_jobs=-1, random_state=seed,
            )),
        ])
    if name == "xgboost":
        try:
            from xgboost import XGBClassifier
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("xgboost is required for the fixed bake-off menu") from exc
        return XGBClassifier(
            n_estimators=180, max_depth=2, learning_rate=0.015,
            min_child_weight=60, subsample=0.75, colsample_bytree=0.60,
            reg_alpha=0.50, reg_lambda=15.0, objective="binary:logistic",
            eval_metric="logloss", tree_method="hist", device="cpu",
            n_jobs=-1, random_state=seed, verbosity=0,
        )
    raise ValueError(f"unknown bake-off model: {name}")


def _folds(records: pd.DataFrame, protocol: BakeoffProtocol, horizon_days: int):
    dates = trading_dates(records)
    validation_start = pd.Timestamp(protocol.validation_start)
    dates_before = int(np.sum(dates < validation_start))
    embargo = horizon_days
    initial = dates_before - horizon_days - embargo
    if initial <= protocol.calibration_dates + 504:
        raise ValueError("not enough history before validation")
    return tuple(expanding_panel_walk_forward_splits(
        records,
        label_horizon=horizon_days,
        initial_train_dates=initial,
        validation_dates=protocol.validation_dates,
        step_dates=protocol.validation_dates,
        embargo_dates=embargo,
        include_partial_final=True,
        min_partial_validation_dates=protocol.partial_validation_min_dates,
    ))


def _fit_calibration_indices(records: pd.DataFrame, train_indices: np.ndarray, *, horizon_days: int,
                             calibration_dates: int) -> tuple[np.ndarray, np.ndarray]:
    train = records.iloc[train_indices]
    dates = trading_dates(train)
    if dates.size <= calibration_dates + 504 + 2 * horizon_days:
        raise ValueError("outer training fold is too short for fit/calibration split")
    calibration = dates[-calibration_dates:]
    fit = dates[: -(calibration_dates + 2 * horizon_days)]
    row_dates = pd.DatetimeIndex(train.index.get_level_values("timestamp")).normalize()
    return train_indices[np.asarray(row_dates.isin(fit))], train_indices[np.asarray(row_dates.isin(calibration))]


def _confidence_percentile(calibration_probability: np.ndarray, validation_probability: np.ndarray) -> np.ndarray:
    reference = np.sort(np.maximum(calibration_probability, 1.0 - calibration_probability))
    values = np.maximum(validation_probability, 1.0 - validation_probability)
    return np.searchsorted(reference, values, side="right") / max(1, reference.size)


def _adaptive_ece(probability: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    frame = pd.DataFrame({"p": probability, "y": labels})
    frame["bin"] = pd.qcut(frame["p"], q=min(bins, frame["p"].nunique()), duplicates="drop")
    grouped = frame.groupby("bin", observed=True)
    return float(sum(len(group) / len(frame) * abs(group["p"].mean() - group["y"].mean()) for _, group in grouped))


def _calibration_slope(probability: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    p = np.clip(probability, 1e-6, 1.0 - 1e-6)
    logit = np.log(p / (1.0 - p)).reshape(-1, 1)
    estimator = LogisticRegression(C=1_000_000.0, solver="lbfgs", max_iter=1_000).fit(logit, labels)
    return float(estimator.intercept_[0]), float(estimator.coef_[0, 0])


def _date_mean_auc(rows: pd.DataFrame, label: str) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    for date, group in rows.groupby(level="timestamp", sort=True):
        if group[label].nunique() == 2:
            values[pd.Timestamp(date)] = float(roc_auc_score(group[label], group["probability"]))
    return pd.Series(values, dtype=float).sort_index()


def _ci(
    values: Iterable[float],
    dates: Iterable[object],
    *,
    block: int,
    samples: int,
    confidence: float = 0.95,
) -> dict[str, float | int]:
    values_list = list(values)
    dates_list = list(dates)
    usable_dates = pd.DatetimeIndex(pd.to_datetime(dates_list, errors="coerce"))
    usable_values = np.asarray(values_list, dtype=float)
    valid = np.isfinite(usable_values) & ~usable_dates.isna()
    n_dates = int(usable_dates[valid].normalize().nunique())
    if n_dates < 2:
        estimate = float(np.mean(usable_values[valid])) if valid.any() else float("nan")
        return {
            "estimate": estimate, "lower": float("nan"), "upper": float("nan"),
            "confidence": confidence, "n_dates": n_dates,
        }
    result = date_block_bootstrap_ci(
        usable_values[valid], usable_dates[valid], confidence=confidence,
        block_size=block, n_bootstrap=samples, seed=0,
    )
    return {
        "estimate": result.estimate, "lower": result.lower, "upper": result.upper,
        "confidence": result.confidence, "n_dates": result.n_dates,
    }


def metrics_for_oof(
    rows: pd.DataFrame,
    *,
    horizon_days: int,
    protocol: BakeoffProtocol,
    confidence: float = 0.95,
) -> dict[str, Any]:
    label = f"direction_{horizon_days}d"
    forward = f"forward_return_{horizon_days}d"
    p = rows["probability"].to_numpy(dtype=float)
    y = rows[label].to_numpy(dtype=int)
    null = rows["training_base_rate"].to_numpy(dtype=float)
    brier = float(brier_score_loss(y, p))
    null_brier = float(np.mean(np.square(null - y)))
    intercept, slope = _calibration_slope(p, y)
    date_auc = _date_mean_auc(rows, label)
    date_auc_ci = _ci(
        date_auc, date_auc.index, block=max(5, horizon_days),
        samples=protocol.bootstrap_samples, confidence=confidence,
    )
    result: dict[str, Any] = {
        "rows": int(len(rows)),
        "dates": int(pd.DatetimeIndex(rows.index.get_level_values("timestamp")).nunique()),
        "pooled_auc": float(roc_auc_score(y, p)),
        "date_mean_auc": float(date_auc.mean()),
        "date_mean_auc_ci": date_auc_ci,
        "balanced_accuracy": float(balanced_accuracy_score(y, p >= 0.5)),
        "brier_score": brier,
        "null_brier_score": null_brier,
        "brier_skill": float(1.0 - brier / null_brier),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "adaptive_ece": _adaptive_ece(p, y),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "coverage": {},
    }
    dates = rows.index.get_level_values("timestamp")
    costs = protocol.round_trip_cost_bps / 10_000.0
    for coverage in SELECTION_COVERAGES:
        active = rows["selection_percentile"].to_numpy(dtype=float) >= 1.0 - coverage
        selected = rows.loc[active]
        selected_p = selected["probability"].to_numpy(dtype=float)
        position = np.where(selected_p >= 0.5, 1, -1)
        correct = (position > 0) == selected[label].to_numpy(dtype=bool)
        net = position * selected[forward].to_numpy(dtype=float) - costs
        selected_dates = selected.index.get_level_values("timestamp")
        key = f"{int(round(coverage * 100))}pct"
        result["coverage"][key] = {
            "rows": int(len(selected)),
            "active_rate": float(active.mean()),
            "accuracy": float(correct.mean()) if len(selected) else float("nan"),
            "average_confidence": float(np.maximum(selected_p, 1.0 - selected_p).mean()) if len(selected) else float("nan"),
            "accuracy_ci": _ci(
                correct.astype(float), selected_dates, block=max(5, horizon_days),
                samples=protocol.bootstrap_samples, confidence=confidence,
            ),
            "net_expectancy_ci": _ci(
                net, selected_dates, block=max(5, horizon_days),
                samples=protocol.bootstrap_samples, confidence=confidence,
            ),
        }
    return result


def _momentum_score(records: pd.DataFrame, horizon_days: int) -> np.ndarray:
    feature = f"return_{horizon_days}d"
    if feature not in records:
        feature = "return_20d"
    return records[feature].to_numpy(dtype=float)


def evaluate_horizon(
    records: pd.DataFrame,
    *,
    horizon_days: int,
    protocol: BakeoffProtocol,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    label = f"direction_{horizon_days}d"
    folds = _folds(records, protocol, horizon_days)
    pieces: dict[str, list[pd.DataFrame]] = {name: [] for name in MODEL_MENU}
    fold_summaries: list[dict[str, Any]] = []
    for fold in folds:
        fit_idx, calibration_idx = _fit_calibration_indices(
            records, fold.train_indices, horizon_days=horizon_days,
            calibration_dates=protocol.calibration_dates,
        )
        fit = records.iloc[fit_idx]
        calibration = records.iloc[calibration_idx]
        validation = records.iloc[fold.validation_indices]
        y_fit = fit[label].to_numpy(dtype=int)
        y_cal = calibration[label].to_numpy(dtype=int)
        training_base = float(y_fit.mean())
        raw_cal: dict[str, np.ndarray] = {}
        raw_val: dict[str, np.ndarray] = {}

        momentum_calibrator = ScoreCalibrator().fit(_momentum_score(calibration, horizon_days), y_cal)
        raw_cal["momentum"] = momentum_calibrator.apply(_momentum_score(calibration, horizon_days))
        raw_val["momentum"] = momentum_calibrator.apply(_momentum_score(validation, horizon_days))

        for offset, name in enumerate(BASE_MODEL_MENU):
            model = _make_model(name, seed=protocol.random_state + fold.fold * 17 + offset)
            model.fit(fit.loc[:, FEATURE_COLUMNS], y_fit)
            raw_cal[name] = model.predict_proba(calibration.loc[:, FEATURE_COLUMNS])[:, 1]
            raw_val[name] = model.predict_proba(validation.loc[:, FEATURE_COLUMNS])[:, 1]
        raw_cal["soft_vote"] = np.mean([raw_cal[name] for name in BASE_MODEL_MENU], axis=0)
        raw_val["soft_vote"] = np.mean([raw_val[name] for name in BASE_MODEL_MENU], axis=0)

        for name in MODEL_MENU:
            if name == "momentum":
                p_cal, p_val = raw_cal[name], raw_val[name]
            else:
                calibrator = BetaCalibrator().fit(raw_cal[name], y_cal)
                p_cal, p_val = calibrator.apply(raw_cal[name]), calibrator.apply(raw_val[name])
            piece = validation.loc[:, [label, f"forward_return_{horizon_days}d"]].copy()
            piece["model"] = name
            piece["fold"] = fold.fold
            piece["probability"] = p_val
            piece["selection_percentile"] = _confidence_percentile(p_cal, p_val)
            piece["training_base_rate"] = training_base
            pieces[name].append(piece)
        fold_summaries.append({
            "fold": fold.fold,
            "fit_rows": int(len(fit)), "calibration_rows": int(len(calibration)),
            "validation_rows": int(len(validation)),
            "validation_start": str(fold.validation_dates.min().date()),
            "validation_end": str(fold.validation_dates.max().date()),
        })

    oof = {name: pd.concat(parts).sort_index() for name, parts in pieces.items()}
    return oof, fold_summaries


def _selected_daily_net(rows: pd.DataFrame, horizon_days: int, protocol: BakeoffProtocol) -> pd.Series:
    active = rows["selection_percentile"] >= 1.0 - PRIMARY_COVERAGE
    selected = rows.loc[active]
    probability = selected["probability"].to_numpy(dtype=float)
    position = np.where(probability >= 0.5, 1, -1)
    net = position * selected[f"forward_return_{horizon_days}d"].to_numpy(dtype=float) - protocol.round_trip_cost_bps / 10_000.0
    return pd.Series(net, index=pd.DatetimeIndex(selected.index.get_level_values("timestamp"))).groupby(level=0).mean()


def _model_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    primary = metrics["coverage"]["10pct"]
    all_rows = metrics["coverage"]["100pct"]
    checks = {
        "pooled_auc_above_random": metrics["pooled_auc"] > 0.50,
        "date_auc_lower_bound_above_random": metrics["date_mean_auc_ci"]["lower"] > 0.50,
        "positive_brier_skill": metrics["brier_skill"] > 0.0,
        "adaptive_ece_within_limit": metrics["adaptive_ece"] <= 0.05,
        "calibration_slope_stable": 0.75 <= metrics["calibration_slope"] <= 1.25,
        "selective_accuracy_improves": primary["accuracy"] >= all_rows["accuracy"] + 0.01,
        "selective_net_lower_bound_positive": primary["net_expectancy_ci"]["lower"] > 0.0,
        "beats_momentum_lower_bound_positive": metrics["net_difference_vs_momentum_ci"]["lower"] > 0.0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _selection_key(item: tuple[str, Mapping[str, Any]]) -> tuple[Any, ...]:
    name, metrics = item
    primary = metrics["coverage"]["10pct"]
    return (
        primary["accuracy_ci"]["lower"],
        primary["net_expectancy_ci"]["lower"],
        metrics["date_mean_auc_ci"]["lower"],
        metrics["brier_skill"], -MODEL_MENU.index(name),
    )


def _period(rows: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    dates = pd.DatetimeIndex(rows.index.get_level_values("timestamp")).normalize()
    mask = np.ones(len(rows), dtype=bool)
    if start is not None:
        mask &= dates >= pd.Timestamp(start)
    if end is not None:
        mask &= dates <= pd.Timestamp(end)
    selected = rows.loc[mask].copy()
    if selected.empty:
        raise ValueError(f"empty OOF evaluation period: {start} to {end}")
    return selected


def _attach_momentum_difference(
    metrics: dict[str, Any],
    candidate: pd.DataFrame,
    momentum: pd.DataFrame,
    *,
    horizon_days: int,
    protocol: BakeoffProtocol,
    confidence: float,
) -> None:
    candidate_daily = _selected_daily_net(candidate, horizon_days, protocol)
    momentum_daily = _selected_daily_net(momentum, horizon_days, protocol)
    joined = pd.concat(
        [candidate_daily.rename("candidate"), momentum_daily.rename("momentum")], axis=1,
    ).fillna(0.0)
    difference = joined["candidate"] - joined["momentum"]
    metrics["net_difference_vs_momentum_ci"] = _ci(
        difference, difference.index, block=max(5, horizon_days),
        samples=protocol.bootstrap_samples, confidence=confidence,
    )


def fit_final_bundle(
    records_by_horizon: Mapping[int, pd.DataFrame],
    selected_by_horizon: Mapping[int, str],
    *,
    protocol: BakeoffProtocol,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": "edge-directional-bakeoff-bundle-v2",
        "feature_columns": FEATURE_COLUMNS,
        "protocol": asdict(protocol),
        "horizons": {},
    }
    for horizon, records in records_by_horizon.items():
        name = selected_by_horizon[horizon]
        dates = trading_dates(records)
        calibration_dates = dates[-protocol.calibration_dates:]
        fit_dates = dates[: -(protocol.calibration_dates + 2 * horizon)]
        row_dates = pd.DatetimeIndex(records.index.get_level_values("timestamp")).normalize()
        fit = records.loc[row_dates.isin(fit_dates)]
        calibration = records.loc[row_dates.isin(calibration_dates)]
        label = f"direction_{horizon}d"
        y_fit = fit[label].to_numpy(dtype=int)
        y_cal = calibration[label].to_numpy(dtype=int)
        if name == "momentum":
            calibrator = ScoreCalibrator().fit(_momentum_score(calibration, horizon), y_cal)
            models: list[Any] = []
            p_cal = calibrator.apply(_momentum_score(calibration, horizon))
        else:
            member_names = list(BASE_MODEL_MENU) if name == "soft_vote" else [name]
            models = []
            raw = []
            for offset, member in enumerate(member_names):
                model = _make_model(member, seed=protocol.random_state + horizon * 31 + offset)
                model.fit(fit.loc[:, FEATURE_COLUMNS], y_fit)
                models.append(model)
                raw.append(model.predict_proba(calibration.loc[:, FEATURE_COLUMNS])[:, 1])
            raw_probability = np.mean(raw, axis=0)
            calibrator = BetaCalibrator().fit(raw_probability, y_cal)
            p_cal = calibrator.apply(raw_probability)
        threshold = float(np.quantile(np.maximum(p_cal, 1.0 - p_cal), 1.0 - PRIMARY_COVERAGE))
        bundle["horizons"][horizon] = {
            "model_name": name,
            "member_names": list(BASE_MODEL_MENU) if name == "soft_vote" else ([name] if name != "momentum" else []),
            "models": models,
            "calibrator": calibrator,
            "confidence_threshold": threshold,
            "training_base_rate": float(y_fit.mean()),
        }
    return bundle


def score_bundle(bundle: Mapping[str, Any], features: pd.DataFrame) -> list[dict[str, Any]]:
    """Score the newest complete row per symbol with a locally verified bundle."""
    expected = tuple(bundle.get("feature_columns") or ())
    if expected != FEATURE_COLUMNS:
        raise ValueError("directional bundle feature contract mismatch")
    rows: list[dict[str, Any]] = []
    latest = features.dropna(subset=list(FEATURE_COLUMNS)).groupby(level="symbol", sort=True).tail(1)
    for horizon, item in sorted(bundle["horizons"].items(), key=lambda pair: int(pair[0])):
        name = str(item["model_name"])
        if name == "momentum":
            raw = latest[f"return_{int(horizon)}d"].to_numpy(dtype=float)
            probability = item["calibrator"].apply(raw)
        else:
            raw_members = [model.predict_proba(latest.loc[:, FEATURE_COLUMNS])[:, 1] for model in item["models"]]
            probability = item["calibrator"].apply(np.mean(raw_members, axis=0))
        confidence = np.maximum(probability, 1.0 - probability)
        symbols = latest.index.get_level_values("symbol")
        timestamps = latest.index.get_level_values("timestamp")
        for idx, symbol in enumerate(symbols):
            rows.append({
                "symbol": str(symbol), "horizon_days": int(horizon),
                "side": "long" if probability[idx] >= 0.5 else "short",
                "probability_up": float(probability[idx]),
                "directional_confidence": float(confidence[idx]),
                "setup_ok": bool(confidence[idx] >= float(item["confidence_threshold"])),
                "confidence_threshold": float(item["confidence_threshold"]),
                "model_name": name, "data_asof_utc": pd.Timestamp(timestamps[idx]).isoformat(),
            })
    return rows


def run_bakeoff(
    *,
    protocol: BakeoffProtocol = BakeoffProtocol(),
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    symbols, sectors = load_universe(universe_path)
    bars = load_daily_universe(symbols, asof=protocol.development_end, data_dir=data_dir)
    features = build_decision_features(bars, sectors)
    records_by_horizon: dict[int, pd.DataFrame] = {}
    oof_all: list[pd.DataFrame] = []
    horizon_results: dict[str, Any] = {}
    selected: dict[int, str] = {}
    # One family-wise 5% error budget across the three horizon claims.  Model
    # choice does not consume this confirmation set: every winner is frozen
    # using only the earlier selection period.
    confirmation_confidence = 1.0 - 0.05 / len(FROZEN_HORIZONS)
    for horizon in FROZEN_HORIZONS:
        records = build_research_records(bars, features, horizon_days=horizon, protocol=protocol)
        records_by_horizon[horizon] = records
        oof, folds = evaluate_horizon(records, horizon_days=horizon, protocol=protocol)

        selection_oof = {
            name: _period(rows, protocol.validation_start, protocol.selection_end)
            for name, rows in oof.items()
        }
        selection_metrics: dict[str, Any] = {}
        for name, rows in selection_oof.items():
            metrics = metrics_for_oof(
                rows, horizon_days=horizon, protocol=protocol, confidence=0.95,
            )
            _attach_momentum_difference(
                metrics, rows, selection_oof["momentum"],
                horizon_days=horizon, protocol=protocol, confidence=0.95,
            )
            selection_metrics[name] = metrics
        winner, _ = max(selection_metrics.items(), key=_selection_key)
        selected[horizon] = winner

        confirmation_rows = _period(
            oof[winner], protocol.confirmation_start, protocol.development_end,
        )
        confirmation_momentum = _period(
            oof["momentum"], protocol.confirmation_start, protocol.development_end,
        )
        confirmation_metrics = metrics_for_oof(
            confirmation_rows, horizon_days=horizon, protocol=protocol,
            confidence=confirmation_confidence,
        )
        _attach_momentum_difference(
            confirmation_metrics, confirmation_rows, confirmation_momentum,
            horizon_days=horizon, protocol=protocol, confidence=confirmation_confidence,
        )
        confirmation_metrics["gate"] = _model_gate(confirmation_metrics)
        horizon_results[str(horizon)] = {
            "folds": folds,
            "selection_period": {
                "start": protocol.validation_start,
                "end": protocol.selection_end,
                "models": selection_metrics,
            },
            "selected_model": winner,
            "selection_rule": "maximize_10pct_accuracy_lower_bound_then_net_auc_brier",
            "confirmation_period": {
                "start": protocol.confirmation_start,
                "end": protocol.development_end,
                "familywise_confidence": confirmation_confidence,
                "selected_model_metrics": confirmation_metrics,
            },
            "selected_model_gate_passed": bool(confirmation_metrics["gate"]["passed"]),
        }
        for name, frame in oof.items():
            item = frame.copy()
            item["horizon_days"] = horizon
            item["model"] = name
            oof_all.append(item)

    bundle = fit_final_bundle(records_by_horizon, selected, protocol=protocol)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    bundle_path = out / "bundle.joblib"
    joblib.dump(bundle, bundle_path, compress=3)
    bundle_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    oof_path = out / "oof_predictions.parquet"
    pd.concat(oof_all).sort_index().to_parquet(oof_path)
    data_hash = hashlib.sha256(pd.util.hash_pandas_object(bars, index=True).to_numpy(dtype=np.uint64).tobytes()).hexdigest()
    quality_gate_passed = any(
        horizon_results[str(horizon)]["selected_model_gate_passed"] for horizon in FROZEN_HORIZONS
    )
    result = {
        "schema_version": "edge-directional-bakeoff-result-v2",
        "status": "DEVELOPMENT_PASS_RESEARCH_ONLY" if quality_gate_passed else "DEVELOPMENT_NO_GO",
        "deployment_eligible": False,
        "research_display_eligible": True,
        "quality_gate_passed_any_horizon": quality_gate_passed,
        "broker_authorized": False,
        "terminal_holdout": {
            "start": protocol.terminal_holdout_start,
            "end": protocol.terminal_holdout_end,
            "status": "SEALED_UNEVALUATED",
            "opened": False,
        },
        "recorded_trial_count": len(MODEL_MENU) * len(FROZEN_HORIZONS),
        "model_menu": list(MODEL_MENU),
        "feature_columns": list(FEATURE_COLUMNS),
        "protocol": asdict(protocol),
        "symbols": len(symbols),
        "data_fingerprint": data_hash,
        "experiment_id": stable_hash(
            {"protocol": asdict(protocol), "menu": MODEL_MENU, "features": FEATURE_COLUMNS, "data": data_hash},
            namespace="edge-directional-bakeoff-v2",
        ),
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha,
        "oof_path": str(oof_path),
        "horizons": horizon_results,
    }
    (out / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
