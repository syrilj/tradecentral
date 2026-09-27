"""Leak-resistant, dependency-light CART audit for the Decision workspace.

One as-of scorer turns bars available at a decision timestamp into features,
a probability, and an action with confidence and a trade-versus-abstain flag.
The historical backtest and the real-time call both use that scorer.  Loading
parquet stays outside it.

Signal features are known at session ``t`` close.  The simulated trade enters
at ``t+1`` open and exits at ``t+1`` close, with round-trip costs deducted.
Hyper-parameters and the confidence threshold are selected only from rows
strictly before the scored window.  The one-week audit remains a smoke test.
Live-capital readiness is a separate sealed window judged by the repository's
existing promotion checks.  A passing verdict still does not authorize an order.

scikit-learn is intentionally not required.  The repository's frozen Python
environment can have binary SciPy/sklearn mismatches, and a reliability screen
must remain measurable when that optional stack is unavailable.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

EDGE_DIR = Path(__file__).resolve().parents[1]
DATA_DIRS = (EDGE_DIR / "data" / "1d", EDGE_DIR / "data" / "1d_wide")
FEATURES = (
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "ret_10d",
    "gap_1d",
    "range_atr",
    "close_location",
    "dist_sma_10",
    "dist_sma_20",
    "volatility_5",
    "volatility_20",
    "volume_ratio_20",
    "rsi_14",
    "drawdown_20",
    "rebound_pressure",
)
DEFAULT_COST_BPS = 10.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.58
CANDIDATES = (
    {"max_depth": 2, "min_leaf": 100},
    {"max_depth": 3, "min_leaf": 100},
    {"max_depth": 3, "min_leaf": 180},
)
MAX_SYMBOLS = 120
WEEK_HISTORY_BARS = 320
CAPITAL_HISTORY_BARS = 252 * 6
OHLCV = ("open", "high", "low", "close", "volume")
# Gate B in docs/GATE_LIVE_STRATEGY.md.  η scales the shipped impact term in
# research.temporal.simulate_order_execution; the bps legs are round-trip.
COST_STRESS = (
    {
        "name": "1.0x",
        "commission_bps": 2.5,
        "half_spread_bps": 2.5,
        "slippage_bps": 2.5,
        "market_impact_multiplier": 0.5,
        "min_mean_net": 0.001,
    },
    {
        "name": "1.5x",
        "commission_bps": 3.75,
        "half_spread_bps": 3.75,
        "slippage_bps": 3.75,
        "market_impact_multiplier": 0.75,
        "min_mean_net": 0.0,
    },
    {
        "name": "2.0x",
        "commission_bps": 5.0,
        "half_spread_bps": 5.0,
        "slippage_bps": 5.0,
        "market_impact_multiplier": 1.0,
        "min_mean_net": 0.0,
    },
)
_CACHE_LOCK = threading.Lock()
_LAST_WEEK_CACHE: dict[str, Any] | None = None


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _latest_completed_week(dates: Iterable[pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp]:
    latest = pd.Timestamp(max(dates)).normalize()
    friday = latest - pd.Timedelta(days=(latest.weekday() - 4) % 7)
    monday = friday - pd.Timedelta(days=4)
    return monday, friday


def _load_symbol(path: Path) -> pd.DataFrame | None:
    try:
        frame = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume"])
    except Exception:
        return None
    if frame.empty:
        return None
    frame = frame[~frame.index.duplicated(keep="last")].sort_index().astype(float)
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    return frame.replace([np.inf, -np.inf], np.nan)


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame):
        return pd.DataFrame(columns=list(OHLCV))
    missing = [column for column in OHLCV if column not in frame.columns]
    if missing:
        return pd.DataFrame(columns=list(OHLCV))
    out = frame.loc[:, list(OHLCV)].copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.DatetimeIndex(pd.to_datetime(out.index))
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    out.index = out.index.normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.replace([np.inf, -np.inf], np.nan)
    return out.apply(pd.to_numeric, errors="coerce")


def _signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Causal features at each completed bar.  No next-session columns."""

    close = frame["close"]
    open_ = frame["open"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]
    prev_close = close.shift(1)
    hl = (high - low).abs().to_numpy()
    hpc = (high - prev_close).abs().to_numpy()
    lpc = (low - prev_close).abs().to_numpy()
    true_range = pd.Series(np.maximum(hl, np.maximum(hpc, lpc)), index=frame.index)
    atr14 = true_range.rolling(14, min_periods=10).mean().replace(0.0, np.nan)
    returns = close.pct_change(fill_method=None)
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(14, min_periods=10).mean()
    losses = (-delta.clip(upper=0)).rolling(14, min_periods=10).mean()
    rs = gains / losses.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    range_span = (high - low).replace(0.0, np.nan)
    sma10 = close.rolling(10, min_periods=8).mean()
    sma20 = close.rolling(20, min_periods=15).mean()
    rolling_high = high.rolling(20, min_periods=15).max()
    vol_median = volume.shift(1).rolling(20, min_periods=10).median().replace(0.0, np.nan)

    out = pd.DataFrame(index=frame.index)
    out["ret_1d"] = returns
    out["ret_3d"] = close.pct_change(3, fill_method=None)
    out["ret_5d"] = close.pct_change(5, fill_method=None)
    out["ret_10d"] = close.pct_change(10, fill_method=None)
    out["gap_1d"] = open_ / prev_close - 1.0
    out["range_atr"] = (high - low) / atr14
    out["close_location"] = ((close - low) / range_span).clip(0.0, 1.0)
    out["dist_sma_10"] = close / sma10 - 1.0
    out["dist_sma_20"] = close / sma20 - 1.0
    out["volatility_5"] = returns.rolling(5, min_periods=4).std()
    out["volatility_20"] = returns.rolling(20, min_periods=15).std()
    out["volume_ratio_20"] = volume / vol_median
    out["rsi_14"] = rsi / 100.0
    out["drawdown_20"] = close / rolling_high - 1.0
    # A large down move that closes off the low is the precise "ready to
    # bounce" shape the operator called out for SPCX.  It is evidence, not a
    # hard-coded buy rule; the tree may accept or reject it in each regime.
    out["rebound_pressure"] = (-out["ret_3d"]).clip(lower=0) * out["close_location"]
    return out


def _feature_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    signals = _signal_frame(frame)
    out = signals.copy()
    out["symbol"] = symbol
    out["signal_date"] = out.index
    out["target_date"] = pd.Series(frame.index, index=frame.index).shift(-1)
    out["entry_open"] = frame["open"].shift(-1)
    out["exit_close"] = frame["close"].shift(-1)
    out["entry_volume"] = frame["volume"].shift(-1)
    out["target_return"] = out["exit_close"] / out["entry_open"] - 1.0
    out["target_up"] = (out["target_return"] > 0.0).astype(int)
    return out.dropna(subset=[*FEATURES, "target_date", "target_return"])


def _selected_paths() -> dict[str, Path]:
    selected: dict[str, Path] = {}
    for base in DATA_DIRS:
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.parquet")):
            selected.setdefault(path.stem.upper(), path)
    return selected


def _audit_symbols(selected: Mapping[str, Path]) -> list[str]:
    # Keep the audit bounded and deterministic.  Prefer the core universe; it
    # includes SPCX and the liquid benchmark names used by the workstation.
    symbols = sorted(selected)[:MAX_SYMBOLS]
    # The core cache is refreshed in tiers.  Always include the liquid/focus
    # names whose daily bars are maintained through the latest session even
    # when an alphabetical cap would otherwise omit them.
    required = {
        "SPCX",
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "NVDA",
        "AAPL",
        "MSFT",
        "TSLA",
        "ARM",
        "COIN",
        "MSTR",
        "CRDO",
        "BTC",
    }
    return sorted(set(symbols) | (required & set(selected)))


def _load_bars() -> dict[str, pd.DataFrame]:
    selected = _selected_paths()
    bars: dict[str, pd.DataFrame] = {}
    for symbol in _audit_symbols(selected):
        frame = _load_symbol(selected[symbol])
        if frame is None or len(frame) < 45:
            continue
        bars[symbol] = frame
    if not bars:
        raise RuntimeError("No usable completed daily bars were found")
    return bars


def _history(frame: pd.DataFrame, history_bars: int | None) -> pd.DataFrame:
    clean = frame if set(OHLCV).issubset(frame.columns) else _normalize_bars(frame)
    if (
        clean.index.tz is not None
        or clean.index.has_duplicates
        or not clean.index.is_monotonic_increasing
    ):
        clean = _normalize_bars(clean)
    if history_bars is not None:
        clean = clean.tail(history_bars)
    return clean


def build_panel(
    bars_by_symbol: Mapping[str, pd.DataFrame], *, history_bars: int | None = WEEK_HISTORY_BARS
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol in sorted(bars_by_symbol):
        visible = _history(bars_by_symbol[symbol], history_bars)
        if len(visible) < 45:
            continue
        featured = _feature_frame(visible, str(symbol).upper())
        if not featured.empty:
            rows.append(featured)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(["target_date", "symbol"])


def _load_panel() -> pd.DataFrame:
    panel = build_panel(_load_bars(), history_bars=WEEK_HISTORY_BARS)
    if panel.empty:
        raise RuntimeError("No usable completed daily bars were found")
    return panel


@dataclass
class Node:
    probability_up: float
    samples: int
    feature: int | None = None
    threshold: float | None = None
    left: "Node | None" = None
    right: "Node | None" = None


class CausalTree:
    """Small deterministic CART classifier with Laplace-smoothed leaves."""

    def __init__(self, *, max_depth: int, min_leaf: int, max_thresholds: int = 12):
        self.max_depth = max_depth
        self.min_leaf = min_leaf
        self.max_thresholds = max_thresholds
        self.root: Node | None = None
        self.importance = np.zeros(len(FEATURES), dtype=float)

    @staticmethod
    def _gini(y: np.ndarray) -> float:
        if not len(y):
            return 0.0
        p = float(y.mean())
        return 2.0 * p * (1.0 - p)

    def fit(self, x: np.ndarray, y: np.ndarray) -> "CausalTree":
        self.importance[:] = 0.0
        self.root = self._grow(x, y.astype(int), 0)
        total = float(self.importance.sum())
        if total > 0:
            self.importance /= total
        return self

    def _grow(self, x: np.ndarray, y: np.ndarray, depth: int) -> Node:
        n_total = len(y)
        total_ones = int(y.sum())
        node = Node(probability_up=(float(total_ones) + 1.0) / (n_total + 2.0), samples=n_total)
        if depth >= self.max_depth or n_total < self.min_leaf * 2 or total_ones == 0 or total_ones == n_total:
            return node
        p = total_ones / n_total
        parent = 2.0 * p * (1.0 - p)
        best: tuple[float, int, float, np.ndarray] | None = None
        qs = np.linspace(0.04, 0.96, self.max_thresholds)
        for feature in range(x.shape[1]):
            values = x[:, feature]
            if values.max() <= values.min():
                continue
            if n_total > self.max_thresholds + 1:
                thresholds = np.unique(np.quantile(values, qs))
            else:
                unique = np.unique(values)
                thresholds = (unique[:-1] + unique[1:]) / 2.0
            for threshold in thresholds:
                left = values <= threshold
                n_left = int(left.sum())
                n_right = n_total - n_left
                if n_left < self.min_leaf or n_right < self.min_leaf:
                    continue
                n_ones_left = int(np.dot(left, y))
                n_ones_right = total_ones - n_ones_left
                impurity = (
                    2.0 * n_ones_left * (n_left - n_ones_left) / n_left
                    + 2.0 * n_ones_right * (n_right - n_ones_right) / n_right
                ) / n_total
                gain = parent - impurity
                if best is None or gain > best[0]:
                    best = (gain, feature, float(threshold), left)
        if best is None or best[0] <= 1e-7:
            return node
        gain, feature, threshold, left = best
        self.importance[feature] += gain * n_total
        node.feature = feature
        node.threshold = threshold
        node.left = self._grow(x[left], y[left], depth + 1)
        node.right = self._grow(x[~left], y[~left], depth + 1)
        return node

    def predict_probability(self, x: np.ndarray) -> np.ndarray:
        if self.root is None:
            raise RuntimeError("tree has not been fit")
        return np.asarray([self._walk(row)[0] for row in x], dtype=float)

    def explain(self, row: np.ndarray) -> list[str]:
        if self.root is None:
            return []
        return self._walk(row)[1]

    def _walk(self, row: np.ndarray) -> tuple[float, list[str]]:
        node = self.root
        path: list[str] = []
        while node.feature is not None and node.left is not None and node.right is not None:
            feature = node.feature
            threshold = float(node.threshold)
            go_left = row[feature] <= threshold
            path.append(f"{FEATURES[feature]} {('≤' if go_left else '>')} {threshold:.4f}")
            node = node.left if go_left else node.right
        path.append(f"leaf {node.samples} samples · raw P(up) {node.probability_up:.2f}")
        return node.probability_up, path


class IsotonicCalibrator:
    """Pool-adjacent-violators calibration, fitted only on OOF predictions."""

    def __init__(self):
        self.x = np.asarray([0.0, 1.0])
        self.y = np.asarray([0.0, 1.0])

    def fit(self, probabilities: np.ndarray, outcomes: np.ndarray) -> "IsotonicCalibrator":
        order = np.argsort(probabilities)
        xs = probabilities[order].astype(float)
        ys = outcomes[order].astype(float)
        blocks = [[float(y), 1, float(x), float(x)] for x, y in zip(xs, ys)]
        index = 0
        while index < len(blocks) - 1:
            if blocks[index][0] / blocks[index][1] <= blocks[index + 1][0] / blocks[index + 1][1]:
                index += 1
                continue
            a, b = blocks[index], blocks[index + 1]
            blocks[index : index + 2] = [[a[0] + b[0], a[1] + b[1], a[2], b[3]]]
            index = max(0, index - 1)
        self.x = np.asarray([(b[2] + b[3]) / 2.0 for b in blocks])
        self.y = np.asarray([b[0] / b[1] for b in blocks])
        if len(self.x) == 1:
            self.x = np.asarray([0.0, 1.0])
            self.y = np.asarray([self.y[0], self.y[0]])
        return self

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        return np.clip(np.interp(probabilities, self.x, self.y), 0.0, 1.0)


def _date_folds(frame: pd.DataFrame, count: int = 3) -> list[tuple[np.ndarray, np.ndarray]]:
    dates = np.asarray(sorted(pd.unique(frame["target_date"])))
    if len(dates) < 30:
        return []
    fold_size = max(5, len(dates) // (count + 2))
    folds = []
    for i in range(count):
        split = len(dates) - fold_size * (count - i)
        if split < fold_size * 2:
            continue
        train_dates = dates[:split]
        valid_dates = dates[split : split + fold_size]
        folds.append(
            (
                frame["target_date"].isin(train_dates).to_numpy(),
                frame["target_date"].isin(valid_dates).to_numpy(),
            )
        )
    return folds


def _balanced_accuracy(y: np.ndarray, pred: np.ndarray) -> float:
    scores = []
    for cls in (0, 1):
        mask = y == cls
        if mask.any():
            scores.append(float((pred[mask] == cls).mean()))
    return float(np.mean(scores)) if scores else 0.0


def _select_model(train: pd.DataFrame) -> tuple[dict[str, int], np.ndarray, np.ndarray, list[dict]]:
    candidates = [dict(params) for params in CANDIDATES]
    folds = _date_folds(train)
    x = train.loc[:, FEATURES].to_numpy(float)
    y = train["target_up"].to_numpy(int)
    ledger: list[dict] = []
    best = candidates[0]
    best_score = -1.0
    for params in candidates:
        fold_scores = []
        for train_mask, valid_mask in folds:
            tree = CausalTree(**params).fit(x[train_mask], y[train_mask])
            pred = (tree.predict_probability(x[valid_mask]) >= 0.5).astype(int)
            fold_scores.append(_balanced_accuracy(y[valid_mask], pred))
        score = float(np.mean(fold_scores)) if fold_scores else 0.0
        ledger.append(
            {**params, "cv_balanced_accuracy": round(score, 4), "folds": len(fold_scores)}
        )
        if score > best_score:
            best, best_score = params, score

    # Expanding-fold out-of-fold probabilities supply calibration without ever
    # touching the final week.
    oof_probability: list[float] = []
    oof_outcome: list[int] = []
    for train_mask, valid_mask in folds:
        tree = CausalTree(**best).fit(x[train_mask], y[train_mask])
        oof_probability.extend(tree.predict_probability(x[valid_mask]).tolist())
        oof_outcome.extend(y[valid_mask].tolist())
    return best, np.asarray(oof_probability), np.asarray(oof_outcome), ledger


def _metrics(
    frame: pd.DataFrame, probability: np.ndarray, *, threshold: float, cost_bps: float
) -> dict:
    y = frame["target_up"].to_numpy(int)
    predicted = (probability >= 0.5).astype(int)
    confidence = np.maximum(probability, 1.0 - probability)
    active = confidence >= threshold
    signed_return = np.where(predicted == 1, 1.0, -1.0) * frame["target_return"].to_numpy(float)
    net = signed_return - cost_bps / 10_000.0
    active_net = net[active]
    return {
        "observations": int(len(frame)),
        "trades": int(active.sum()),
        "coverage": round(float(active.mean()) if len(active) else 0.0, 4),
        "accuracy": (
            round(float((predicted[active] == y[active]).mean()), 4) if active.any() else None
        ),
        "balanced_accuracy": (
            round(_balanced_accuracy(y[active], predicted[active]), 4) if active.any() else None
        ),
        "mean_net_return_bps": (
            round(float(active_net.mean() * 10_000.0), 2) if active.any() else None
        ),
        "cumulative_net_return_pct": (
            round(float(active_net.sum() * 100.0), 3) if active.any() else None
        ),
        "brier_score": round(float(np.mean((probability - y) ** 2)), 4),
    }


@dataclass
class FittedDecision:
    """Model selected only on rows whose target date is before ``oos_start``."""

    tree: CausalTree
    calibrator: IsotonicCalibrator
    confidence_threshold: float
    parameters: dict[str, int]
    training_end: str
    oos_start: str
    cv_ledger: list[dict[str, Any]]
    threshold_ledger: list[dict[str, Any]]
    trial_count: int

    def fingerprint(self) -> dict[str, Any]:
        return {
            "parameters": dict(self.parameters),
            "confidence_threshold": self.confidence_threshold,
            "training_end": self.training_end,
            "oos_start": self.oos_start,
            "trial_count": self.trial_count,
            "tree": _node_signature(self.tree.root),
            "calibrator_x": [float(value) for value in self.calibrator.x],
            "calibrator_y": [float(value) for value in self.calibrator.y],
        }


def _node_signature(node: Node | None) -> list[Any]:
    if node is None:
        return []
    return [
        [
            node.feature,
            None if node.threshold is None else round(float(node.threshold), 10),
            round(float(node.probability_up), 10),
            int(node.samples),
        ],
        *_node_signature(node.left),
        *_node_signature(node.right),
    ]


def fit_decision_model(
    panel: pd.DataFrame, *, oos_start: Any, cost_bps: float = DEFAULT_COST_BPS
) -> FittedDecision:
    """Fit, calibrate, and choose the threshold using only pre-window rows."""

    window_start = pd.Timestamp(oos_start).normalize()
    train = panel.loc[pd.to_datetime(panel["target_date"]).dt.normalize() < window_start].copy()
    if train.empty:
        raise RuntimeError("no rows strictly before the out-of-sample window")
    best, oof_p, oof_y, ledger = _select_model(train)
    x_train = train.loc[:, FEATURES].to_numpy(float)
    y_train = train["target_up"].to_numpy(int)
    tree = CausalTree(**best).fit(x_train, y_train)
    calibrator = IsotonicCalibrator()
    threshold_ledger: list[dict] = []
    confidence_threshold = DEFAULT_CONFIDENCE_THRESHOLD
    searched_thresholds = 1
    if len(oof_p) >= 40:
        calibrator.fit(oof_p, oof_y)
        calibrated_oof = calibrator.predict(oof_p)
        oof_frames = [train.loc[valid_mask] for _, valid_mask in _date_folds(train)]
        oof_frame = pd.concat(oof_frames, ignore_index=True)
        # Determine maximum confidence reachable by the fitted tree on the pre-window training set
        p_train = calibrator.predict(tree.predict_probability(x_train))
        max_model_conf = (
            float(np.max(np.maximum(p_train, 1.0 - p_train))) if len(p_train) else 0.58
        )
        candidates = [
            c for c in (0.505, 0.51, 0.515, 0.52, 0.53, 0.54, 0.56, 0.58) if c <= max_model_conf
        ]
        if not candidates:
            candidates = [round(max(0.505, min(0.58, max_model_conf * 0.99)), 3)]

        for candidate in candidates:
            score = _metrics(oof_frame, calibrated_oof, threshold=candidate, cost_bps=cost_bps)
            threshold_ledger.append({"threshold": candidate, **score})
        searched_thresholds = len(threshold_ledger)
        eligible = [
            row
            for row in threshold_ledger
            if row["coverage"] >= 0.01
            and row["trades"] >= 20
            and (row["mean_net_return_bps"] or -1e9) > 0
        ]
        if not eligible:
            eligible = [
                row for row in threshold_ledger if row["coverage"] >= 0.01 and row["trades"] >= 20
            ]
        if eligible:
            chosen = max(
                eligible,
                key=lambda row: (
                    row["mean_net_return_bps"]
                    if row["mean_net_return_bps"] is not None
                    else -1e9,
                    row["balanced_accuracy"] if row["balanced_accuracy"] is not None else -1e9,
                ),
            )
            confidence_threshold = float(chosen["threshold"])
    training_end = pd.Timestamp(train["target_date"].max()).normalize()
    if training_end >= window_start:
        raise RuntimeError("training rows leaked into the out-of-sample window")
    return FittedDecision(
        tree=tree,
        calibrator=calibrator,
        confidence_threshold=confidence_threshold,
        parameters=dict(best),
        training_end=training_end.date().isoformat(),
        oos_start=window_start.date().isoformat(),
        cv_ledger=ledger,
        threshold_ledger=threshold_ledger,
        trial_count=len(CANDIDATES) * searched_thresholds,
    )


def _clock(clock: pd.Timestamp | None) -> pd.Timestamp:
    if clock is None:
        return pd.Timestamp.now(tz="America/New_York")
    stamp = pd.Timestamp(clock)
    if stamp.tzinfo is None:
        return stamp.tz_localize("America/New_York")
    return stamp.tz_convert("America/New_York")


def _session_is_complete(decision_ts: Any, clock: pd.Timestamp | None) -> bool:
    """A daily bar is complete only after that session's close, or on a prior date."""

    day = pd.Timestamp(decision_ts).normalize()
    now = _clock(clock)
    today = now.tz_localize(None).normalize()
    if day < today:
        return True
    if day > today:
        return False
    return now >= now.normalize() + pd.Timedelta(hours=16)


def _abstain_fields(reason: str) -> dict[str, Any]:
    return {
        "action": None,
        "confidence": None,
        "trade": False,
        "active": False,
        "abstain": True,
        "reason": reason,
        "probability_up": None,
        "decision_authorized": False,
        "order": None,
    }


def _calibrated_probability(model: FittedDecision, features: np.ndarray) -> float:
    raw = model.tree.predict_probability(np.asarray(features, dtype=float).reshape(1, -1))
    return float(model.calibrator.predict(raw)[0])


def _pack_decision(probability: float, threshold: float) -> dict[str, Any]:
    action = "buy" if probability >= 0.5 else "sell"
    confidence = float(max(probability, 1.0 - probability))
    trade = bool(confidence >= threshold)
    return {
        "action": action,
        "confidence": round(confidence, 4),
        "trade": trade,
        "active": trade,
        "abstain": not trade,
        "reason": None if trade else "below_confidence_threshold",
        "probability_up": float(probability),
        "decision_authorized": False,
        "order": None,
    }


def _feature_values(featured: pd.DataFrame, visible: pd.DataFrame, decision_ts: pd.Timestamp):
    if visible.empty or decision_ts not in visible.index:
        return None, "missing_bars"
    bar = visible.loc[decision_ts]
    if isinstance(bar, pd.DataFrame):
        bar = bar.iloc[-1]
    if not np.isfinite(pd.to_numeric(bar, errors="coerce").to_numpy(dtype=float)).all():
        return None, "nonfinite_bars"
    if featured.empty or decision_ts not in featured.index:
        return None, "insufficient_history"
    values = featured.loc[decision_ts, list(FEATURES)]
    if isinstance(values, pd.DataFrame):
        values = values.iloc[-1]
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all():
        return None, "nonfinite_features"
    return array, None


def score_dates(
    bars: pd.DataFrame,
    decision_timestamps: Iterable[Any],
    model: FittedDecision,
    *,
    session_complete: bool = True,
) -> list[dict[str, Any]]:
    """Score many timestamps.  Features stop at the latest requested timestamp."""

    dates = [pd.Timestamp(value).normalize() for value in decision_timestamps]
    if not dates:
        return []
    visible = _normalize_bars(bars)
    featured = _signal_frame(visible.loc[: max(dates)]) if not visible.empty else pd.DataFrame()
    scored: list[dict[str, Any]] = []
    for decision_ts in dates:
        base = {
            "decision_ts": decision_ts.date().isoformat(),
            "execution_lag_bars": 1,
            "execution": "enter next session open, exit next session close",
        }
        if not session_complete:
            scored.append({**base, **_abstain_fields("incomplete_session")})
            continue
        values, reason = _feature_values(featured, visible, decision_ts)
        if values is None:
            scored.append({**base, **_abstain_fields(reason or "missing_bars")})
            continue
        probability = _calibrated_probability(model, values)
        scored.append({**base, **_pack_decision(probability, model.confidence_threshold)})
    return scored


def score_asof(
    bars: pd.DataFrame,
    decision_ts: Any,
    model: FittedDecision,
    *,
    session_complete: bool | None = None,
    clock: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Score one decision timestamp.  Bars after it are not feature inputs."""

    if session_complete is None:
        session_complete = _session_is_complete(decision_ts, clock)
    return score_dates(bars, [decision_ts], model, session_complete=session_complete)[0]


def _visible_map(
    bars_by_symbol: Mapping[str, pd.DataFrame], history_bars: int | None
) -> dict[str, pd.DataFrame]:
    visible: dict[str, pd.DataFrame] = {}
    for symbol, frame in bars_by_symbol.items():
        history = _history(frame, history_bars)
        if len(history) >= 45:
            visible[str(symbol).upper()] = history
    return visible


def _week_bundle(cost_bps: float, universe: Mapping[str, pd.DataFrame] | None) -> dict[str, Any]:
    if universe is not None:
        return _compute_week(dict(universe), cost_bps)
    global _LAST_WEEK_CACHE
    fingerprint = _disk_fingerprint()
    with _CACHE_LOCK:
        cached = _LAST_WEEK_CACHE
        if (
            cached is not None
            and cached["fingerprint"] == fingerprint
            and cached["cost_bps"] == cost_bps
        ):
            return cached["bundle"]
        bundle = _compute_week(_load_bars(), cost_bps)
        _LAST_WEEK_CACHE = {"fingerprint": fingerprint, "cost_bps": cost_bps, "bundle": bundle}
        return bundle


def _disk_fingerprint() -> tuple:
    selected = _selected_paths()
    items = []
    for symbol in _audit_symbols(selected):
        stat = selected[symbol].stat()
        items.append((symbol, stat.st_mtime_ns, stat.st_size))
    return tuple(items)


def _compute_week(bars_by_symbol: Mapping[str, pd.DataFrame], cost_bps: float) -> dict[str, Any]:
    visible = _visible_map(bars_by_symbol, WEEK_HISTORY_BARS)
    panel = build_panel(visible, history_bars=None)
    if panel.empty:
        raise RuntimeError("No usable completed daily bars were found")
    holdout_start, holdout_end = _latest_completed_week(panel["target_date"])
    train = panel[pd.to_datetime(panel["target_date"]) < holdout_start].copy()
    holdout = panel[
        (pd.to_datetime(panel["target_date"]) >= holdout_start)
        & (pd.to_datetime(panel["target_date"]) <= holdout_end)
    ].copy()
    if train.empty or holdout.empty:
        raise RuntimeError("Insufficient pre-holdout or holdout rows")
    model = fit_decision_model(panel, oos_start=holdout_start, cost_bps=cost_bps)
    decisions: dict[tuple[str, pd.Timestamp], dict[str, Any]] = {}
    for symbol, group in holdout.groupby("symbol"):
        history = visible.get(str(symbol))
        if history is None:
            continue
        scored = score_dates(history, group["signal_date"], model, session_complete=True)
        for signal_date, decision in zip(group["signal_date"], scored):
            decisions[(str(symbol), pd.Timestamp(signal_date).normalize())] = decision

    probabilities: list[float] = []
    actions: list[str] = []
    confidences: list[float] = []
    actives: list[bool] = []
    for _, row in holdout.iterrows():
        decision = decisions.get((str(row["symbol"]), pd.Timestamp(row["signal_date"]).normalize()))
        if decision is None or decision["probability_up"] is None or decision["action"] is None:
            reason = None if decision is None else decision["reason"]
            raise RuntimeError(f"holdout row unscorable: {row['symbol']} {reason}")
        probabilities.append(float(decision["probability_up"]))
        actions.append(str(decision["action"]))
        confidences.append(float(decision["confidence"]))
        actives.append(bool(decision["trade"]))
    probability = np.asarray(probabilities, dtype=float)
    x_train = train.loc[:, FEATURES].to_numpy(float)
    y_train = train["target_up"].to_numpy(int)
    x_test = holdout.loc[:, FEATURES].to_numpy(float)
    baseline_probability = (
        CausalTree(max_depth=5, min_leaf=40).fit(x_train, y_train).predict_probability(x_test)
    )
    comparison = {
        "baseline": _metrics(holdout, baseline_probability, threshold=0.50, cost_bps=cost_bps),
        "improved": _metrics(
            holdout, probability, threshold=model.confidence_threshold, cost_bps=cost_bps
        ),
    }
    base_bal = comparison["baseline"]["balanced_accuracy"] or 0.0
    improved_bal = comparison["improved"]["balanced_accuracy"] or 0.0
    base_net = comparison["baseline"]["mean_net_return_bps"] or -1e9
    improved_net = comparison["improved"]["mean_net_return_bps"] or -1e9
    demonstrated = improved_bal > base_bal and improved_net > base_net
    risk_control_only = comparison["improved"]["trades"] == 0 and base_net < 0
    holdout = holdout.copy()
    holdout["probability_up"] = probability
    holdout["action"] = actions
    holdout["confidence"] = confidences
    holdout["active"] = actives
    holdout["correct"] = (holdout["action"] == "buy") == (holdout["target_return"] > 0)
    direction = np.where(holdout["action"] == "buy", 1.0, -1.0)
    holdout["net_return"] = direction * holdout["target_return"] - cost_bps / 10_000.0
    daily = []
    for date, group in holdout.groupby("target_date"):
        active = group[group["active"]]
        daily.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "observations": int(len(group)),
                "trades": int(len(active)),
                "accuracy": round(float(active["correct"].mean()), 4) if len(active) else None,
                "mean_net_return_bps": (
                    round(float(active["net_return"].mean() * 10_000), 2) if len(active) else None
                ),
            }
        )
    focus_rows = []
    focus = holdout[holdout["symbol"] == "SPCX"]
    for _, row in focus.iterrows():
        explanation = model.tree.explain(row.loc[list(FEATURES)].to_numpy(float))
        focus_rows.append(
            {
                "symbol": "SPCX",
                "signal_asof": pd.Timestamp(row["signal_date"]).date().isoformat(),
                "session_date": pd.Timestamp(row["target_date"]).date().isoformat(),
                "action": str(row["action"]),
                "confidence": float(row["confidence"]),
                "active": bool(row["active"]),
                "entry_open": round(float(row["entry_open"]), 4),
                "exit_close": round(float(row["exit_close"]), 4),
                "actual_return_pct": round(float(row["target_return"] * 100.0), 3),
                "correct": bool(row["correct"]),
                "net_return_bps": (
                    round(float(row["net_return"] * 10_000.0), 2) if row["active"] else None
                ),
                "tree_path": explanation,
                "rebound_pressure": round(float(row["rebound_pressure"]), 6),
                "rsi_14": round(float(row["rsi_14"] * 100.0), 2),
            }
        )
    importances = sorted(
        (
            {"feature": feature, "importance": round(float(value), 4)}
            for feature, value in zip(FEATURES, model.tree.importance)
            if value > 0
        ),
        key=lambda row: row["importance"],
        reverse=True,
    )
    payload = {
        "schema_version": "decision-tree-oos-v1",
        "status": "research_only",
        "verdict": (
            "IMPROVEMENT_DEMONSTRATED_ON_HOLDOUT"
            if demonstrated
            else (
                "RISK_CONTROL_IMPROVED_EDGE_NOT_DEMONSTRATED"
                if risk_control_only
                else "IMPROVEMENT_NOT_DEMONSTRATED_ON_HOLDOUT"
            )
        ),
        "window": {
            "holdout_start": holdout_start.date().isoformat(),
            "holdout_end": holdout_end.date().isoformat(),
            "training_end": (holdout_start - pd.Timedelta(days=1)).date().isoformat(),
            "sessions": int(holdout["target_date"].nunique()),
        },
        "protocol": {
            "signal": "completed session t OHLCV only",
            "execution": "enter t+1 open, exit t+1 close",
            "target": "next-session open-to-close direction",
            "round_trip_cost_bps": cost_bps,
            "selection": "expanding date folds ending before holdout",
            "holdout_used_for_training": False,
            "confidence_semantics": "OOF isotonic estimate; abstain below selected threshold",
            "warning": "One week is a smoke test, not evidence of live-trading readiness.",
        },
        "universe": {
            "symbols": int(holdout["symbol"].nunique()),
            "training_rows": int(len(train)),
            "holdout_rows": int(len(holdout)),
        },
        "model": {
            "kind": "causal_cart",
            "parameters": model.parameters,
            "confidence_threshold": model.confidence_threshold,
            "feature_count": len(FEATURES),
            "features": list(FEATURES),
            "top_importance": importances[:8],
            "cv_candidates": model.cv_ledger,
            "threshold_candidates": model.threshold_ledger,
        },
        "comparison": comparison,
        "daily": daily,
        "focus": {"symbol": "SPCX", "rows": focus_rows},
        "decision_authorized": False,
        "order": None,
    }
    return {"model": model, "bars": visible, "payload": payload}


def run_last_week_backtest(
    *, cost_bps: float = DEFAULT_COST_BPS, universe: Mapping[str, pd.DataFrame] | None = None
) -> dict[str, Any]:
    bundle = _week_bundle(cost_bps, universe)
    payload = deepcopy(bundle["payload"])
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def _latest_completed_session(
    bars: pd.DataFrame, clock: pd.Timestamp | None
) -> pd.Timestamp | None:
    visible = _normalize_bars(bars)
    if visible.empty:
        return None
    now = _clock(clock)
    today = now.tz_localize(None).normalize()
    if today in visible.index and _session_is_complete(today, now):
        return today
    prior = visible.index[visible.index < today]
    if len(prior) == 0:
        return None
    return pd.Timestamp(prior[-1])


def _public_score(symbol: str | None, decision_ts: Any, decision: dict[str, Any]) -> dict[str, Any]:
    stamped = dict(decision)
    stamped["symbol"] = symbol
    if decision_ts is not None and "decision_ts" not in stamped:
        stamped["decision_ts"] = pd.Timestamp(decision_ts).date().isoformat()
    stamped["decision_authorized"] = False
    stamped["order"] = None
    return stamped


def score_realtime_decision(
    symbol: str,
    decision_ts: Any = None,
    *,
    universe: Mapping[str, pd.DataFrame] | None = None,
    bars: pd.DataFrame | None = None,
    clock: pd.Timestamp | None = None,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    """Real-time entry point.  Same model and as-of rule as the backtest."""

    cleaned = str(symbol or "").upper().strip()
    if not cleaned or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for character in cleaned
    ):
        return _public_score(cleaned or None, decision_ts, _abstain_fields("invalid_symbol"))
    bundle = _week_bundle(cost_bps, universe)
    history = _normalize_bars(bars) if bars is not None else bundle["bars"].get(cleaned)
    if history is None or history.empty:
        return _public_score(cleaned, decision_ts, _abstain_fields("missing_bars"))
    if decision_ts is None:
        decision_ts = _latest_completed_session(history, clock)
        if decision_ts is None:
            return _public_score(cleaned, None, _abstain_fields("incomplete_session"))
    decision = score_asof(history, decision_ts, bundle["model"], clock=clock)
    return _public_score(cleaned, decision_ts, decision)


def _capital_window(dates: list[pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp, bool]:
    """Latest two-year span, always leaving a pre-window the fit is allowed to see."""

    ordered = sorted({pd.Timestamp(value).normalize() for value in dates})
    if len(ordered) < 40:
        day = ordered[-1] if ordered else pd.Timestamp("1970-01-01")
        return day, day, False
    latest = ordered[-1]
    earliest_oos = ordered[29] + pd.Timedelta(days=1)
    cutoff = max((latest - pd.DateOffset(years=2)).normalize(), earliest_oos)
    oos = [day for day in ordered if day >= cutoff]
    if len(oos) < 5:
        oos = ordered[-5:]
    pre = [day for day in ordered if day < oos[0]]
    years = {day.year for day in oos}
    supported = len(pre) >= 252 and len(years) >= 2 and len(oos) >= 60
    return oos[0], oos[-1], supported


def _not_ready(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "decision-live-capital-v1",
        "verdict": "not-ready",
        "decision_authorized": False,
        "order": None,
        "allow_live_order_submission": False,
        "all_checks_passed": False,
        "reasons": [reason],
        "checks": {},
        "window": {},
        "model": {},
    }


def _round_trip_cost_bps(trade: Mapping[str, Any], stress: Mapping[str, float]) -> float:
    from .temporal import MarketRecord, OrderIntent, simulate_order_execution

    signal = pd.Timestamp(trade["signal_date"]).normalize()
    session = pd.Timestamp(trade["session_date"]).normalize()
    if session <= signal:
        raise ValueError("execution lag must be at least one session")
    decision_ts = signal + pd.Timedelta(hours=16)
    event_ts = session + pd.Timedelta(hours=16)
    entry = float(trade["entry_open"])
    exit_ = float(trade["exit_close"])
    record = MarketRecord(
        symbol=str(trade["symbol"]),
        event_ts=event_ts,
        source_ts=event_ts,
        received_ts=event_ts,
        available_ts=event_ts,
        open=entry,
        high=max(entry, exit_),
        low=min(entry, exit_),
        close=exit_,
        volume=float(trade["volume"]),
        is_complete=True,
    )
    direction = 1.0 if trade["action"] == "buy" else -1.0
    kwargs = {
        "commission_bps": float(stress["commission_bps"]),
        "slippage_bps": float(stress["slippage_bps"]),
        "half_spread_bps": float(stress["half_spread_bps"]),
        "market_impact_multiplier": float(stress["market_impact_multiplier"]),
    }
    fills = []
    for weight in (direction, -direction):
        fill = simulate_order_execution(
            OrderIntent(
                symbol=str(trade["symbol"]),
                target_weight=weight,
                order_type="MARKET",
                signal_ts=signal,
                submission_ts=decision_ts,
            ),
            decision_ts,
            record,
            **kwargs,
        )
        if fill is None:
            raise ValueError("market order did not fill")
        fills.append(float(fill.realized_cost_bps))
    return fills[0] + fills[1]


def _daily_strategy_returns(
    session_dates: list[pd.Timestamp], nets_by_day: Mapping[pd.Timestamp, list[float]]
) -> list[float]:
    if session_dates:
        days = session_dates
    else:
        days = sorted(nets_by_day)
    returns = []
    for day in days:
        samples = nets_by_day.get(day, [])
        returns.append(float(np.mean(samples)) if samples else 0.0)
    return returns


def _fold_sharpes(dates: list[pd.Timestamp], daily: Mapping[pd.Timestamp, float]) -> list[float]:
    from .quant_core import sharpe as annualized_sharpe

    ordered = sorted(set(dates))
    if not ordered:
        return []
    cuts = [
        ordered[len(ordered) * index // 3 : len(ordered) * (index + 1) // 3] for index in range(3)
    ]
    sharpes: list[float] = []
    for fold_days in cuts:
        series = pd.Series([daily.get(day, 0.0) for day in fold_days], dtype=float)
        value = annualized_sharpe(series)
        sharpes.append(float("nan") if value is None else float(value))
    return sharpes


def judge_live_capital(
    trades: list[Mapping[str, Any]],
    *,
    session_dates: Iterable[Any] | None = None,
    trial_count: int = 15,
) -> dict[str, Any]:
    """Apply the repository live-capital checks.  Does not place or authorize an order."""

    from .live_edge import evaluate_walk_forward_gates, regime_stability_score
    from .quant_core import sharpe as annualized_sharpe
    from .statistics import bonferroni_deflated_sharpe_approximation, newey_west_tstat

    calendar = [
        pd.Timestamp(value).normalize()
        for value in list(session_dates if session_dates is not None else [])
    ]
    usable = []
    for trade in trades:
        prices = [
            trade.get("entry_open"),
            trade.get("exit_close"),
            trade.get("gross_return"),
            trade.get("volume"),
        ]
        if not all(isinstance(value, (int, float)) and np.isfinite(value) for value in prices):
            continue
        if trade.get("action") not in {"buy", "sell"}:
            continue
        usable.append(trade)
    lag_ok = all(
        pd.Timestamp(trade["session_date"]) > pd.Timestamp(trade["signal_date"]) for trade in usable
    )
    stress_nets: dict[str, np.ndarray] = {}
    cost_checks: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    if not lag_ok:
        reasons.append("execution lag is below one session")
    for stress in COST_STRESS:
        nets = []
        for trade in usable:
            gross = float(trade["gross_return"])
            signed = gross if trade["action"] == "buy" else -gross
            try:
                cost = _round_trip_cost_bps(trade, stress) / 10_000.0
            except (ValueError, TypeError):
                cost = float("inf")
            nets.append(signed - cost)
        array = np.asarray(nets, dtype=float)
        stress_nets[stress["name"]] = array
        finite = array[np.isfinite(array)]
        mean_net = float(finite.mean()) if finite.size else float("nan")
        by_day: dict[pd.Timestamp, list[float]] = {}
        for trade, net in zip(usable, array):
            if not np.isfinite(net):
                continue
            by_day.setdefault(pd.Timestamp(trade["session_date"]).normalize(), []).append(
                float(net)
            )
        daily_values = _daily_strategy_returns(calendar, by_day)
        sharpe_value = annualized_sharpe(pd.Series(daily_values, dtype=float))
        sharpe_number = float("nan") if sharpe_value is None else float(sharpe_value)
        expectancy_ok = bool(np.isfinite(mean_net) and mean_net > float(stress["min_mean_net"]))
        sharpe_ok = bool(np.isfinite(sharpe_number) and sharpe_number > 0.50)
        cumulative = float(finite.sum()) if finite.size else float("nan")
        cumulative_ok = (
            True if stress["name"] != "2.0x" else bool(np.isfinite(cumulative) and cumulative > 0.0)
        )
        passed = expectancy_ok and sharpe_ok and cumulative_ok
        cost_checks[stress["name"]] = {
            "passed": passed,
            "mean_net": mean_net,
            "min_mean_net": float(stress["min_mean_net"]),
            "sharpe": sharpe_number,
            "cumulative_net": cumulative,
        }
        if not passed:
            reasons.append(f"{stress['name']} cost stress failed")

    baseline_nets = stress_nets.get("1.0x", np.asarray([], dtype=float))
    wins = int(np.sum(baseline_nets[np.isfinite(baseline_nets)] > 0)) if baseline_nets.size else 0
    trade_count = int(np.isfinite(baseline_nets).sum()) if baseline_nets.size else 0
    try:
        from tools.shadow_reliability import wilson_low
    except ImportError:
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "tools" / "shadow_reliability.py"
        spec = importlib.util.spec_from_file_location("_edge_shadow_reliability", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        wilson_low = module.wilson_low
    wilson = float(wilson_low(wins, trade_count)) if trade_count else float("nan")
    by_day = {}
    for trade, net in zip(usable, baseline_nets):
        if np.isfinite(net):
            by_day.setdefault(pd.Timestamp(trade["session_date"]).normalize(), []).append(
                float(net)
            )
    daily_baseline = _daily_strategy_returns(calendar, by_day)
    newey = float(newey_west_tstat(daily_baseline))
    try:
        deflated = bonferroni_deflated_sharpe_approximation(
            daily_baseline, trial_count=max(1, trial_count)
        )
        deflated_lower = float(deflated.lower_bound_sharpe)
    except (ValueError, TypeError):
        deflated_lower = float("nan")
    daily_map = {
        day: (float(np.mean(samples)) if samples else 0.0) for day, samples in by_day.items()
    }
    fold_days = calendar or sorted(daily_map)
    fold_values = _fold_sharpes(fold_days, daily_map)
    gate = evaluate_walk_forward_gates(fold_values)
    regime_frame = pd.DataFrame(
        {
            "volatility_regime": [trade.get("volatility_regime") for trade in usable],
            "mean_return": baseline_nets if len(baseline_nets) == len(usable) else [],
            "n": 1,
        }
    )
    if len(regime_frame) == len(usable) and len(usable):
        grouped = (
            regime_frame.dropna(subset=["volatility_regime"])
            .groupby("volatility_regime", dropna=True)
            .agg(n=("n", "sum"), mean_return=("mean_return", "mean"))
            .reset_index()
        )
        regime = regime_stability_score(grouped)
    else:
        regime = {"stable": False, "reason": "no regime labels"}
    years = {}
    for trade, net in zip(usable, baseline_nets):
        if not np.isfinite(net):
            continue
        year = pd.Timestamp(trade["session_date"]).year
        years.setdefault(year, []).append(float(net))
    year_rows = []
    for year, samples in sorted(years.items()):
        year_rows.append({"year": year, "n": len(samples), "mean_return": float(np.mean(samples))})
    sampled_years = [row for row in year_rows if row["n"] >= 20]
    positive_years = sum(row["mean_return"] > 0 for row in sampled_years)
    years_stable = len(sampled_years) >= 2 and positive_years >= max(
        2, int(np.ceil(0.5 * len(sampled_years)))
    )
    checks = {
        "execution_lag": {"passed": lag_ok, "minimum_bars": 1},
        "trade_count": {"passed": trade_count >= 100, "trades": trade_count, "minimum": 100},
        "wilson_win_rate": {"passed": bool(np.isfinite(wilson) and wilson > 0.50), "lower": wilson},
        "newey_west_t": {
            "passed": bool(newey > 2.0),
            "t": newey,
            "minimum": 2.0,
            "daily_returns": daily_baseline,
        },
        "deflated_sharpe": {
            "passed": bool(np.isfinite(deflated_lower) and deflated_lower > 0.0),
            "lower": deflated_lower,
        },
        "regimes": {"passed": bool(regime.get("stable")), **regime},
        "calendar_years": {"passed": years_stable, "years": year_rows},
        "walk_forward": {**gate.as_dict(), "fold_sharpes": fold_values},
        "cost_stress": cost_checks,
    }
    for name in (
        "trade_count",
        "wilson_win_rate",
        "newey_west_t",
        "deflated_sharpe",
        "regimes",
        "calendar_years",
    ):
        if not checks[name]["passed"]:
            reasons.append(name.replace("_", " ") + " failed")
    if not checks["walk_forward"]["passed"]:
        reasons.extend(gate.reasons)
    cost_passed = all(row["passed"] for row in cost_checks.values()) if cost_checks else False
    checks["cost_stress"] = {**cost_checks, "passed": cost_passed}
    all_passed = (
        lag_ok
        and cost_passed
        and all(
            checks[name]["passed"]
            for name in (
                "trade_count",
                "wilson_win_rate",
                "newey_west_t",
                "deflated_sharpe",
                "regimes",
                "calendar_years",
                "walk_forward",
            )
        )
    )
    return _json_safe(
        {
            "schema_version": "decision-live-capital-v1",
            "verdict": "pass" if all_passed else "not-ready",
            "decision_authorized": False,
            "order": None,
            "allow_live_order_submission": False,
            "all_checks_passed": all_passed,
            "reasons": reasons,
            "checks": checks,
            "sample": {"trades": trade_count, "wins": wins},
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def evaluate_sealed_live_capital(
    *,
    universe: Mapping[str, pd.DataFrame] | None = None,
    history_bars: int = CAPITAL_HISTORY_BARS,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    """Score a sealed post-fit window and set the verdict from the live-capital checks."""

    from .regimes import classify_regimes

    bars = dict(universe) if universe is not None else _load_bars()
    visible = _visible_map(bars, history_bars)
    panel = build_panel(visible, history_bars=None)
    if panel.empty:
        return _not_ready("no completed bars")
    oos_start, oos_end, supported = _capital_window(list(pd.to_datetime(panel["target_date"])))
    try:
        model = fit_decision_model(panel, oos_start=oos_start, cost_bps=cost_bps)
    except RuntimeError as exc:
        return _not_ready(str(exc))
    window = panel[
        (pd.to_datetime(panel["target_date"]) >= oos_start)
        & (pd.to_datetime(panel["target_date"]) <= oos_end)
    ]
    trades: list[dict[str, Any]] = []
    observations = 0
    unscorable = 0
    below_threshold = 0
    for symbol, group in window.groupby("symbol"):
        history = visible.get(str(symbol))
        if history is None:
            continue
        regimes = classify_regimes(history["close"])
        scored = score_dates(history, group["signal_date"], model, session_complete=True)
        observations += len(scored)
        for (_, row), decision in zip(group.iterrows(), scored):
            if decision["action"] is None:
                unscorable += 1
                continue
            if not decision["trade"]:
                below_threshold += 1
                continue
            signal = pd.Timestamp(row["signal_date"]).normalize()
            label = None
            if signal in regimes.index and pd.notna(regimes.at[signal, "volatility_regime"]):
                label = str(regimes.at[signal, "volatility_regime"])
            trades.append(
                {
                    "symbol": str(symbol),
                    "signal_date": signal.date().isoformat(),
                    "session_date": pd.Timestamp(row["target_date"]).date().isoformat(),
                    "action": decision["action"],
                    "gross_return": float(row["target_return"]),
                    "entry_open": float(row["entry_open"]),
                    "exit_close": float(row["exit_close"]),
                    "volume": (
                        float(row["entry_volume"])
                        if np.isfinite(row["entry_volume"])
                        else float("nan")
                    ),
                    "volatility_regime": label,
                }
            )
    report = judge_live_capital(
        trades,
        session_dates=sorted(pd.to_datetime(window["target_date"]).unique()),
        trial_count=model.trial_count,
    )
    if not supported:
        report["all_checks_passed"] = False
        report["verdict"] = "not-ready"
        report["reasons"] = [
            *report["reasons"],
            "local history cannot support the live-capital sample",
        ]
    report["window"] = {
        "training_end": model.training_end,
        "oos_start": model.oos_start,
        "oos_end": oos_end.date().isoformat(),
        "supported": supported,
        "holdout_used_for_training": False,
        "execution_lag_bars": 1,
    }
    report["model"] = {
        "parameters": model.parameters,
        "confidence_threshold": model.confidence_threshold,
        "trial_count": model.trial_count,
        "fingerprint": model.fingerprint(),
    }
    report["sample"] = {
        **report.get("sample", {}),
        "observations": observations,
        "unscorable": unscorable,
        "below_threshold": below_threshold,
    }
    report["decision_authorized"] = False
    report["order"] = None
    return report


__all__ = [
    "run_last_week_backtest",
    "score_realtime_decision",
    "score_asof",
    "score_dates",
    "fit_decision_model",
    "build_panel",
    "evaluate_sealed_live_capital",
    "judge_live_capital",
    "CausalTree",
    "FEATURES",
    "FittedDecision",
]
