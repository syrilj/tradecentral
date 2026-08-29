"""Reversal labeling and leak-resistant backtest for the absorption detector.

The detector (``daily_plays.absorption``) flags *where* heavy flow was
absorbed. This module answers the honest follow-up: *did a reversal actually
follow?* It is a research surface, not a trading authorization.

Two pieces:

1. ``label_reversals`` -- a causal, point-in-time label. A signal at index
   ``t`` is a hit if the price moves at least ``threshold`` in the *opposite*
   direction of the absorbed flow within ``horizon`` observations, using only
   bars ``> t``. The label is computed from the same bars the detector saw,
   so there is no lookahead into the label itself.

2. ``backtest_absorption`` -- walks the detector readouts, takes a
   hypothetical position in the reversal direction at each signal, holds for
   ``horizon`` bars, and reports both classification metrics (precision,
   recall, ROC-AUC, PR-AUC) and economic metrics (profit factor, Sharpe,
   max drawdown, win rate, expectancy). Returns are per-bar close-to-close
   and are *not* net of slippage/fees; that caveat is carried in the payload.

Everything is pure and in-memory; callers hand it bars and readouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from edge.daily_plays.absorption import (
    AbsorptionConfig,
    AbsorptionReadout,
    detect_absorption_series,
    observations_from_bars,
)


# ---------------------------------------------------------------------------
# Reversal labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReversalLabel:
    """Outcome of one signal at index ``t``."""

    index: int
    signal_kind: str
    direction: int
    entry_price: float
    exit_price: float
    forward_return: float
    hit: bool


def label_reversals(
    readouts: Sequence[AbsorptionReadout],
    prices: Sequence[float],
    *,
    horizon: int = 5,
    threshold: float = 0.005,
) -> list[ReversalLabel]:
    """Label each signal causally.

    ``prices`` is the same close series the detector consumed (ascending).
    A signal at index ``t`` is a hit if the price at ``t + horizon`` moved at
    least ``threshold`` in ``reversal_direction`` relative to the entry price
    at ``t``. Signals too close to the end of the series (no full horizon)
    are skipped, not guessed.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    n = len(prices)
    labels: list[ReversalLabel] = []
    for readout in readouts:
        if not readout.signal:
            continue
        t = readout.index
        exit_index = t + horizon
        if exit_index >= n:
            continue
        entry = float(prices[t])
        exit_price = float(prices[exit_index])
        if entry <= 0:
            continue
        forward_return = (exit_price - entry) / entry
        hit = forward_return * readout.reversal_direction >= threshold
        labels.append(
            ReversalLabel(
                index=t,
                signal_kind=readout.signal_kind or "unknown",
                direction=readout.reversal_direction,
                entry_price=entry,
                exit_price=exit_price,
                forward_return=forward_return,
                hit=hit,
            )
        )
    return labels


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic.

    Returns NaN when either class is absent (AUC is undefined). ``scores``
    must rank higher for positives; the detector's |absorption_score| is the
    natural ranking feature.
    """
    y = np.asarray(y_true, dtype=bool)
    s = np.asarray(scores, dtype=float)
    if y.size == 0 or not (y.any() and (~y).any()):
        return float("nan")
    pos = s[y]
    neg = s[~y]
    n_pos = pos.size
    n_neg = neg.size
    # Count pairs where a positive scores strictly above a negative; ties
    # contribute 0.5 (the standard AUC tie convention).
    auc = 0.0
    for p in pos:
        greater = np.count_nonzero(neg < p)
        ties = np.count_nonzero(neg == p)
        auc += greater + 0.5 * ties
    return float(auc / (n_pos * n_neg))


def _pr_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Area under the precision-recall curve (average precision).

    Computed from the sorted score thresholds; ties are handled by grouping
    equal scores. Returns NaN when there are no positives.
    """
    y = np.asarray(y_true, dtype=bool)
    s = np.asarray(scores, dtype=float)
    if y.size == 0 or not y.any():
        return float("nan")
    order = np.argsort(-s, kind="mergesort")
    y_sorted = y[order]
    s_sorted = s[order]
    n_pos = int(y.sum())
    total = y.size

    # Walk thresholds at each distinct score (descending). AP = sum over
    # thresholds of precision * (recall - prev_recall), with prev_recall = 0
    # before the first threshold.
    tp = 0
    fp = 0
    prev_recall = 0.0
    ap = 0.0
    i = 0
    while i < total:
        score = s_sorted[i]
        # Group all samples sharing this score.
        j = i
        while j < total and s_sorted[j] == score:
            if y_sorted[j]:
                tp += 1
            else:
                fp += 1
            j += 1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / n_pos
        ap += precision * (recall - prev_recall)
        prev_recall = recall
        i = j
    return float(ap)


def _sharpe(returns: Sequence[float], periods: int = 252) -> float:
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        return float("nan")
    std = arr.std(ddof=1)
    if std == 0:
        return float("nan")
    return float(arr.mean() / std * np.sqrt(periods))


def _max_drawdown(equity: Sequence[float]) -> float:
    arr = np.asarray(equity, dtype=float)
    if arr.size == 0:
        return float("nan")
    peak = np.maximum.accumulate(arr)
    drawdowns = arr / peak - 1.0
    return float(drawdowns.min())


def _profit_factor(returns: Sequence[float]) -> float:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return float("nan")
    gross_profit = float(arr[arr > 0].sum())
    gross_loss = float(-arr[arr < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else float("nan")
    return gross_profit / gross_loss


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest_absorption(
    bars: pd.DataFrame,
    *,
    cfg: AbsorptionConfig | None = None,
    horizon: int = 5,
    threshold: float = 0.005,
) -> dict[str, Any]:
    """Run the detector + reversal backtest over one symbol's OHLCV frame.

    Returns a payload with every key always present (repo convention), so a
    symbol with no signals still yields a valid, inspectable result.
    """
    cfg = cfg or AbsorptionConfig()
    observations = observations_from_bars(bars)
    readouts = detect_absorption_series(observations, cfg)
    prices = [float(close) for close in bars["close"].to_numpy()]

    labels = label_reversals(readouts, prices, horizon=horizon, threshold=threshold)

    n_signals = len(labels)
    n_hits = sum(1 for label in labels if label.hit)
    precision = (n_hits / n_signals) if n_signals else float("nan")
    recall = float("nan")  # recall needs a ground-truth reversal set; see caveats
    f1 = float("nan")

    # Ranking feature for AUC: |absorption_score| at the signal.
    scores = np.asarray(
        [abs(readouts[label.index].absorption_score) for label in labels], dtype=float
    )
    y_true = np.asarray([label.hit for label in labels], dtype=bool)
    roc_auc = _roc_auc(y_true, scores)
    pr_auc = _pr_auc(y_true, scores)

    # Economic metrics: a hypothetical position in the reversal direction,
    # held for ``horizon`` bars. Returns are per-bar close-to-close, not net
    # of slippage/fees.
    trade_returns = [label.forward_return * label.direction for label in labels]
    equity = np.cumprod(1.0 + np.asarray(trade_returns, dtype=float)).tolist() if trade_returns else []
    win_rate = (n_hits / n_signals) if n_signals else float("nan")
    expectancy = float(np.mean(trade_returns)) if trade_returns else float("nan")
    sharpe = _sharpe(trade_returns)
    max_dd = _max_drawdown(equity)
    profit_factor = _profit_factor(trade_returns)

    return {
        "symbol": str(bars.attrs.get("symbol") or "").upper() or None,
        "n_bars": len(bars),
        "n_signals": n_signals,
        "n_hits": n_hits,
        "precision": round(precision, 6) if precision == precision else None,
        "recall": None,
        "f1": None,
        "roc_auc": round(roc_auc, 6) if roc_auc == roc_auc else None,
        "pr_auc": round(pr_auc, 6) if pr_auc == pr_auc else None,
        "win_rate": round(win_rate, 6) if win_rate == win_rate else None,
        "expectancy": round(expectancy, 6) if expectancy == expectancy else None,
        "sharpe": round(sharpe, 4) if sharpe == sharpe else None,
        "max_drawdown": round(max_dd, 6) if max_dd == max_dd else None,
        "profit_factor": round(profit_factor, 4) if profit_factor == profit_factor else None,
        "horizon": horizon,
        "threshold": threshold,
        "labels": [
            {
                "index": label.index,
                "signal_kind": label.signal_kind,
                "direction": label.direction,
                "entry_price": round(label.entry_price, 4),
                "exit_price": round(label.exit_price, 4),
                "forward_return": round(label.forward_return, 6),
                "hit": label.hit,
            }
            for label in labels
        ],
        "caveats": [
            "Returns are per-bar close-to-close and are NOT net of slippage, "
            "fees, or spread; they are a research estimate, not a P&L.",
            "recall/f1 are null because a ground-truth reversal set is not "
            "defined here; precision and AUC are computed against the "
            "threshold-based reversal label only.",
            "signed flow is the CLV x volume proxy, not measured aggressor "
            "order flow -- this repo has no trades/quotes/L2 data.",
        ],
    }
