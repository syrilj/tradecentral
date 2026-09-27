"""Fitness evaluation for strategy genomes on a precomputed market panel."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .genome import Genes, Genome
from .panel import (
    MarketPanel,
    cross_sectional_rank,
    rolling_max,
    rolling_mean,
    rolling_min,
    rolling_std,
)
from .protocol import EvolutionProtocol


@dataclass(frozen=True)
class FitnessConfig:
    """Weights for the multi-objective fitness score."""

    sharpe_weight: float = 1.0
    return_weight: float = 0.35
    drawdown_weight: float = 1.25
    win_rate_weight: float = 0.25
    complexity_weight: float = 0.40
    turnover_weight: float = 0.15
    min_sharpe_floor: float = -5.0

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class FitnessResult:
    fitness: float
    alive: bool
    death_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fitness": float(self.fitness),
            "alive": bool(self.alive),
            "death_reason": self.death_reason,
            "metrics": dict(self.metrics),
        }


def _signal_score(panel: MarketPanel, genes: Genes) -> np.ndarray:
    lookback = int(genes.lookback)
    vol_window = int(genes.vol_window)
    close = panel.close
    ret = panel.ret_1d
    family = genes.signal_family

    if family == "momentum":
        # Total return over lookback
        lagged = np.full_like(close, np.nan)
        lagged[lookback:] = close[lookback:] / close[:-lookback] - 1.0
        return lagged

    if family == "vol_scaled_momentum":
        mom = np.full_like(close, np.nan)
        mom[lookback:] = close[lookback:] / close[:-lookback] - 1.0
        vol = rolling_std(ret, vol_window)
        with np.errstate(invalid="ignore", divide="ignore"):
            return mom / np.where(vol > 1e-8, vol, np.nan)

    if family == "mean_reversion":
        mu = rolling_mean(close, lookback)
        sigma = rolling_std(close, lookback)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = (close - mu) / np.where(sigma > 1e-8, sigma, np.nan)
        # Positive score = expect reversion up (oversold)
        return -z

    if family == "breakout":
        hi = rolling_max(panel.high, lookback)
        lo = rolling_min(panel.low, lookback)
        with np.errstate(invalid="ignore", divide="ignore"):
            width = hi - lo
            pos = (close - lo) / np.where(width > 1e-8, width, np.nan)
        # Near highs → breakout long bias
        return pos

    raise ValueError(f"unknown family {family}")


def _liquidity_mask(panel: MarketPanel, min_rank: float) -> np.ndarray:
    """True where dollar-volume rank >= min_rank (0 = allow all)."""
    if min_rank <= 0:
        return np.isfinite(panel.close)
    ranks = cross_sectional_rank(panel.dollar_volume)
    return np.isfinite(panel.close) & np.isfinite(ranks) & (ranks >= float(min_rank))


def _apply_cs_score(
    scores: np.ndarray,
    eligible: np.ndarray,
    genes: Genes,
    panel: MarketPanel,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Filter / blend rule scores with panel.cs_score (Qlib-style ranks).

    * off — no change  
    * filter — require cs rank ≥ cs_min_rank (0–1, 1 = top of book)  
    * blend — convex mix of rule ranks and cs ranks, then optional rank floor  

    If cs_mode is not off but panel.cs_score is missing, genome is left unchanged
    and a metric flag is set (caller may still evaluate pure rule signal).
    """
    meta = {"cs_mode_applied": 0.0, "cs_eligible_frac": 1.0}
    mode = str(genes.cs_mode or "off")
    if mode == "off":
        return scores, eligible, meta
    if panel.cs_score is None:
        meta["cs_mode_applied"] = -1.0  # requested but unavailable
        return scores, eligible, meta

    cs = panel.cs_score
    cs_ranks = cross_sectional_rank(cs)  # higher rank = higher score
    # Normalize ranks to ~[0,1] per day where defined
    # cross_sectional_rank already returns percentile-like ranks in this codebase?
    # Check panel.cross_sectional_rank
    rule_ranks = cross_sectional_rank(scores)
    min_rank = float(genes.cs_min_rank)

    if mode == "filter":
        keep = eligible & np.isfinite(cs_ranks) & (cs_ranks >= min_rank)
        meta["cs_mode_applied"] = 1.0
        meta["cs_eligible_frac"] = float(np.mean(keep)) if keep.size else 0.0
        return scores, keep, meta

    if mode == "blend":
        blend = float(np.clip(genes.cs_blend, 0.0, 1.0))
        # Blend ranks so scale is comparable; missing → keep rule only that day/name
        mixed = np.where(
            np.isfinite(rule_ranks) & np.isfinite(cs_ranks),
            (1.0 - blend) * rule_ranks + blend * cs_ranks,
            rule_ranks,
        )
        keep = eligible
        if min_rank > 0:
            keep = keep & np.isfinite(cs_ranks) & (cs_ranks >= min_rank)
        meta["cs_mode_applied"] = 2.0
        meta["cs_eligible_frac"] = float(np.mean(keep)) if keep.size else 0.0
        return mixed, keep, meta

    return scores, eligible, meta


def _positions_from_scores(
    scores: np.ndarray,
    eligible: np.ndarray,
    genes: Genes,
) -> np.ndarray:
    """Build {-1,0,+1} position matrix from cross-sectional ranks."""
    t, s = scores.shape
    positions = np.zeros((t, s), dtype=float)
    top_k = int(genes.top_k)
    entry_z = float(genes.entry_z)
    mode = genes.long_short
    family = genes.signal_family

    masked = np.where(eligible, scores, np.nan)

    for i in range(t):
        row = masked[i]
        valid_idx = np.where(np.isfinite(row))[0]
        n = len(valid_idx)
        if n < max(2, top_k + 1):
            continue

        if family == "mean_reversion":
            # entry_z is z-threshold on score magnitude (already -z of price)
            # high score = oversold → long; low score = overbought → short
            long_mask = row >= entry_z
            short_mask = row <= -entry_z
        else:
            # Use rank tails scaled by entry_z as percentile gate:
            # entry_z 0.25→ loosely take top; 2.5 → very selective
            # map entry_z in [0.25, 2.5] → keep fraction in [0.25, 0.05]
            keep_frac = float(np.clip(0.30 - 0.10 * entry_z, 0.05, 0.30))
            k = max(top_k, int(np.ceil(keep_frac * n)))
            k = min(k, n // 2 if mode == "long_short" else n)
            order = np.argsort(row[valid_idx], kind="mergesort")
            high = valid_idx[order[-k:]]
            low = valid_idx[order[:k]]
            long_mask = np.zeros(s, dtype=bool)
            short_mask = np.zeros(s, dtype=bool)
            long_mask[high] = True
            short_mask[low] = True
            # Prefer explicit top_k if smaller than k from frac
            if top_k < k:
                long_mask[:] = False
                short_mask[:] = False
                long_mask[valid_idx[order[-top_k:]]] = True
                short_mask[valid_idx[order[:top_k]]] = True

        if mode in ("long_only", "long_short"):
            if family == "mean_reversion":
                # Take up to top_k longs among those above threshold
                cand = np.where(long_mask & eligible[i])[0]
                if len(cand) > top_k:
                    order = np.argsort(row[cand])[::-1][:top_k]
                    keep = cand[order]
                    positions[i, keep] = 1.0
                else:
                    positions[i, cand] = 1.0
            else:
                positions[i, long_mask] = 1.0

        if mode in ("short_only", "long_short"):
            if family == "mean_reversion":
                cand = np.where(short_mask & eligible[i])[0]
                if len(cand) > top_k:
                    order = np.argsort(row[cand])[:top_k]
                    keep = cand[order]
                    positions[i, keep] = -1.0
                else:
                    positions[i, cand] = -1.0
            elif mode == "short_only":
                positions[i, short_mask] = -1.0
            else:
                positions[i, short_mask] = -1.0

    # Clear anything not eligible
    positions = np.where(eligible, positions, 0.0)
    return positions


def _forward_returns(close: np.ndarray, horizon: int) -> np.ndarray:
    """Return from t+1 to t+1+horizon (signal at close t → next open approx).

    Using close[t+1+h] / close[t+1] - 1 avoids same-bar entry lookahead.
    """
    t, s = close.shape
    out = np.full((t, s), np.nan, dtype=float)
    # need t+1 and t+1+h
    last = t - (horizon + 1)
    if last <= 0:
        return out
    entry = close[1 : last + 1]
    exit_ = close[1 + horizon : last + 1 + horizon]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:last] = exit_ / entry - 1.0
    return out


def _portfolio_series(
    positions: np.ndarray,
    fwd: np.ndarray,
    cost_return: float,
) -> tuple[np.ndarray, dict[str, float]]:
    """Equal-weight active book; charge round-trip cost on position changes."""
    t, s = positions.shape
    # Hold signal positions for the horizon: rebalance every day with lag-1 entry
    # PnL attributed on the day the forward return is realized at signal time
    active = np.abs(positions) > 0
    n_active = active.sum(axis=1).astype(float)
    gross = np.zeros(t, dtype=float)
    for i in range(t):
        if n_active[i] < 1:
            continue
        legs = positions[i]
        rets = fwd[i]
        mask = (np.abs(legs) > 0) & np.isfinite(rets)
        if not mask.any():
            continue
        gross[i] = float(np.mean(legs[mask] * rets[mask]))

    # Turnover proxy: fraction of book that flips day-to-day
    turnover = np.zeros(t, dtype=float)
    if t > 1:
        delta = np.abs(positions[1:] - positions[:-1]).sum(axis=1) / max(s, 1)
        turnover[1:] = delta
    net = gross - cost_return * turnover

    trade_days = int((n_active > 0).sum())
    n_trades = int(active.sum())  # position-slots opened
    metrics = {
        "trade_days": float(trade_days),
        "n_position_slots": float(n_trades),
        "mean_active": float(np.nanmean(n_active)) if t else 0.0,
        "mean_turnover": float(np.nanmean(turnover)) if t else 0.0,
    }
    return net, metrics


def _max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + np.nan_to_num(returns, nan=0.0))
    peak = np.maximum.accumulate(equity)
    with np.errstate(invalid="ignore", divide="ignore"):
        dd = 1.0 - equity / np.where(peak > 0, peak, np.nan)
    if not np.isfinite(dd).any():
        return 0.0
    return float(np.nanmax(dd))


def evaluate_genes(
    panel: MarketPanel,
    genes: Genes,
    *,
    protocol: EvolutionProtocol | None = None,
    fitness_config: FitnessConfig | None = None,
) -> FitnessResult:
    """Score one gene set on the supplied panel window."""
    protocol = protocol or EvolutionProtocol()
    fitness_config = fitness_config or FitnessConfig()
    cost_return = float(protocol.round_trip_cost_bps) / 10_000.0

    if panel.n_dates < max(genes.lookback, genes.vol_window) + genes.horizon_days + 5:
        return FitnessResult(
            fitness=-1_000.0,
            alive=False,
            death_reason="insufficient_history",
            metrics={},
        )

    scores = _signal_score(panel, genes)
    eligible = _liquidity_mask(panel, genes.dollar_volume_min_rank)
    scores, eligible, cs_meta = _apply_cs_score(scores, eligible, genes, panel)
    if str(genes.cs_mode or "off") != "off" and panel.cs_score is None:
        return FitnessResult(
            fitness=-800.0,
            alive=False,
            death_reason="cs_score_unavailable",
            metrics={**cs_meta},
        )
    positions = _positions_from_scores(scores, eligible, genes)
    fwd = _forward_returns(panel.close, int(genes.horizon_days))
    net, book_metrics = _portfolio_series(positions, fwd, cost_return)

    valid = np.isfinite(net) & (np.abs(positions).sum(axis=1) > 0)
    if int(valid.sum()) < 10:
        return FitnessResult(
            fitness=-1_000.0,
            alive=False,
            death_reason="too_few_active_days",
            metrics=book_metrics,
        )

    series = net[valid]
    mean_r = float(np.mean(series))
    std_r = float(np.std(series, ddof=0))
    sharpe = float(mean_r / std_r * np.sqrt(252.0)) if std_r > 1e-12 else 0.0
    win_rate = float(np.mean(series > 0))
    max_dd = _max_drawdown(net)  # full path including flat days
    total_return = float(np.prod(1.0 + series) - 1.0)
    base = 1.0 + total_return
    if base > 0:
        ann_return = float(base ** (252.0 / max(len(series), 1)) - 1.0)
    else:
        ann_return = -1.0
    n_trades = int(book_metrics["n_position_slots"])
    turnover = float(book_metrics["mean_turnover"])

    metrics: dict[str, Any] = {
        **book_metrics,
        **cs_meta,
        "mean_net_return": mean_r,
        "ann_return": ann_return,
        "total_return": total_return,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "n_trades": float(n_trades),
        "active_days": float(int(valid.sum())),
        "horizon_days": float(genes.horizon_days),
        "complexity": float(genes.complexity()),
        "cost_bps": float(protocol.round_trip_cost_bps),
        "cs_mode": str(genes.cs_mode or "off"),
    }

    if n_trades < protocol.min_trades:
        return FitnessResult(
            fitness=-500.0 - (protocol.min_trades - n_trades),
            alive=False,
            death_reason="min_trades",
            metrics=metrics,
        )
    if max_dd > protocol.max_drawdown_hard:
        return FitnessResult(
            fitness=-400.0 - 100.0 * max_dd,
            alive=False,
            death_reason="max_drawdown",
            metrics=metrics,
        )
    if turnover > protocol.max_turnover:
        return FitnessResult(
            fitness=-300.0 - 10.0 * turnover,
            alive=False,
            death_reason="max_turnover",
            metrics=metrics,
        )

    fitness = (
        fitness_config.sharpe_weight * sharpe
        + fitness_config.return_weight * (ann_return * 10.0)
        + fitness_config.win_rate_weight * ((win_rate - 0.5) * 4.0)
        - fitness_config.drawdown_weight * (max_dd * 10.0)
        - fitness_config.complexity_weight * genes.complexity()
        - fitness_config.turnover_weight * (turnover * 5.0)
    )
    if not np.isfinite(fitness):
        return FitnessResult(
            fitness=-1_000.0,
            alive=False,
            death_reason="non_finite_fitness",
            metrics=metrics,
        )
    fitness = float(max(fitness_config.min_sharpe_floor * 10, fitness))
    return FitnessResult(fitness=fitness, alive=True, death_reason=None, metrics=metrics)


def evaluate_genome(
    panel: MarketPanel,
    genome: Genome,
    *,
    protocol: EvolutionProtocol | None = None,
    fitness_config: FitnessConfig | None = None,
) -> Genome:
    """Evaluate and mutate genome in place with fitness + metrics."""
    result = evaluate_genes(
        panel,
        genome.genes,
        protocol=protocol,
        fitness_config=fitness_config,
    )
    genome.fitness = result.fitness
    genome.alive = result.alive
    genome.death_reason = result.death_reason
    genome.metrics = result.metrics
    return genome
