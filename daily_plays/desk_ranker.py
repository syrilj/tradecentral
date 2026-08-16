"""Zero-fit desk ranker: regime-conditioned rev5 + mom12_1.

This is the implementation of ``docs/GATE_DESK_RANKER.md``. It does not train.
Scores are ordinal attention ranks, never calibrated probabilities, and never
ENTER authorization.

Skip-day label used by the bakeoff:
    close[t + 1 + HORIZON_DAYS] / close[t + 1] - 1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from edge.research.regimes import classify_regimes


SOURCE_ID = "desk_ranker_v1"
SCORE_KIND = "ordinal_desk_ranker"
HORIZON_DAYS = 5
ENTER_PERCENTILE = 0.80
EXIT_PERCENTILE = 0.65
MIN_HISTORY_BARS = 60
MOM_MIN_BARS = 260

# Frozen before the bakeoff. HIGH vol leans reversal; LOW vol leans momentum.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "HIGH": {"rev5": 0.65, "mom12_1": 0.35},
    "MEDIUM": {"rev5": 0.50, "mom12_1": 0.50},
    "LOW": {"rev5": 0.35, "mom12_1": 0.65},
}


def regime_weights(vol_regime: str | None) -> dict[str, float]:
    key = str(vol_regime or "").strip().upper()
    return dict(REGIME_WEIGHTS.get(key, REGIME_WEIGHTS["MEDIUM"]))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def literature_features(close: pd.Series) -> dict[str, float | None]:
    """Predicted-positive-IC forms from the factor probe (no fitting)."""
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if len(clean) < MIN_HISTORY_BARS:
        return {"rev5": None, "mom12_1": None}
    c = np.asarray(clean, dtype=float)
    rev5 = None
    if len(c) >= 6 and c[-6] != 0:
        rev5 = _finite(-(c[-1] / c[-6] - 1.0))
    mom12_1 = None
    if len(c) >= MOM_MIN_BARS and c[-253] != 0:
        mom12_1 = _finite(c[-22] / c[-253] - 1.0)
    return {"rev5": rev5, "mom12_1": mom12_1}


def _cross_section_rank_z(values: Mapping[str, float]) -> dict[str, float]:
    """Rank, then z-score the ranks. Matches GATE_DESK_RANKER and factor_probe."""
    if len(values) < 2:
        return {key: 0.0 for key in values}
    ranks = pd.Series(values, dtype=float).rank(method="average")
    mu = float(ranks.mean())
    sd = float(ranks.std(ddof=0))
    if not np.isfinite(sd) or sd <= 1e-12:
        return {key: 0.0 for key in values}
    return {key: float((ranks[key] - mu) / sd) for key in values}


@dataclass(frozen=True)
class RankerPanel:
    scores: dict[str, float]
    source: str
    vol_regime: str
    weights: dict[str, float]

    def __getitem__(self, symbol: str) -> float | str:
        if symbol == "source":
            return self.source
        return self.scores[symbol]


def score_feature_table(
    feature_table: Mapping[str, Mapping[str, Any]],
    *,
    vol_regime: str = "MEDIUM",
) -> RankerPanel:
    """Cross-sectional z-score blend. Missing factors drop their weight."""
    weights = regime_weights(vol_regime)
    z_by_factor: dict[str, dict[str, float]] = {}
    for factor in weights:
        raw = {
            symbol: float(feats[factor])
            for symbol, feats in feature_table.items()
            if _finite((feats or {}).get(factor)) is not None
        }
        z_by_factor[factor] = _cross_section_rank_z(raw)

    scores: dict[str, float] = {}
    for symbol in feature_table:
        num = 0.0
        den = 0.0
        for factor, weight in weights.items():
            if symbol in z_by_factor[factor]:
                num += weight * z_by_factor[factor][symbol]
                den += weight
        if den > 0:
            scores[symbol] = num / den
    return RankerPanel(
        scores=scores,
        source=SOURCE_ID,
        vol_regime=str(vol_regime or "MEDIUM").upper() or "MEDIUM",
        weights=weights,
    )


def skip_day_forward_return(
    close: pd.Series,
    decision_date: Any,
    *,
    horizon: int = HORIZON_DAYS,
) -> float | None:
    """Return from the first close after decision to the close ``horizon`` sessions later."""
    if horizon <= 0:
        return None
    series = pd.to_numeric(close, errors="coerce").dropna().sort_index()
    cut = pd.Timestamp(decision_date)
    future = series.loc[series.index > cut]
    if len(future) < horizon + 1:
        return None
    entry = float(future.iloc[0])
    exit_ = float(future.iloc[horizon])
    if entry == 0 or not np.isfinite(entry) or not np.isfinite(exit_):
        return None
    return exit_ / entry - 1.0


def hysteresis_holdings(
    scores: Mapping[str, float],
    *,
    held: set[str] | None = None,
    enter_percentile: float = ENTER_PERCENTILE,
    exit_percentile: float = EXIT_PERCENTILE,
) -> set[str]:
    """Long the top tail; keep a name until it falls through the exit floor."""
    if not scores:
        return set()
    if enter_percentile < exit_percentile:
        raise ValueError("enter_percentile must be >= exit_percentile")
    ranked = pd.Series({str(key): float(value) for key, value in scores.items()})
    ranked = ranked[np.isfinite(ranked)]
    if ranked.empty:
        return set()
    pct = ranked.rank(method="average", pct=True)
    previous = {str(symbol).upper() for symbol in (held or set())}
    keep: set[str] = set()
    for symbol, percentile in pct.items():
        name = str(symbol).upper()
        if percentile >= enter_percentile:
            keep.add(name)
        elif name in previous and percentile >= exit_percentile:
            keep.add(name)
    return keep


def classify_market_vol_regime(
    market_close: pd.Series,
    *,
    asof: Any | None = None,
) -> str:
    """Causal vol regime from a single market series (SPY or catalog average)."""
    series = pd.to_numeric(market_close, errors="coerce").dropna().sort_index()
    if asof is not None:
        series = series.loc[series.index <= pd.Timestamp(asof)]
    if len(series) < 40:
        return "MEDIUM"
    labels = classify_regimes(series)
    last = labels["volatility_regime"].dropna()
    if last.empty:
        return "MEDIUM"
    value = str(last.iloc[-1]).upper()
    return value if value in REGIME_WEIGHTS else "MEDIUM"
