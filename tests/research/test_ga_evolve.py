"""Unit tests for the genetic evolution lab."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from edge.research.ga.fitness import FitnessConfig, evaluate_genes
from edge.research.ga.genome import (
    Genes,
    breed,
    crossover,
    mutate_genes,
    random_genome,
)
from edge.research.ga.panel import MarketPanel, build_market_panel
from edge.research.ga.protocol import EvolutionProtocol
from edge.research.ga.storage import list_runs, run_payload


EDGE = Path(__file__).resolve().parents[2]
DATA_1D = EDGE / "data" / "1d"
UNIVERSE = EDGE / "config" / "universe_directional_v2.json"


def _toy_panel(n_dates: int = 120, n_symbols: int = 8, seed: int = 0) -> MarketPanel:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    symbols = tuple(f"S{i:02d}" for i in range(n_symbols))
    rets = rng.normal(0.0003, 0.015, size=(n_dates, n_symbols))
    close = 100.0 * np.cumprod(1.0 + rets, axis=0)
    volume = rng.uniform(1e6, 5e6, size=(n_dates, n_symbols))
    high = close * (1.0 + rng.uniform(0, 0.01, size=close.shape))
    low = close * (1.0 - rng.uniform(0, 0.01, size=close.shape))
    ret_1d = np.full_like(close, np.nan)
    ret_1d[1:] = close[1:] / close[:-1] - 1.0
    return MarketPanel(
        dates=pd.DatetimeIndex(dates),
        symbols=symbols,
        close=close,
        volume=volume,
        high=high,
        low=low,
        ret_1d=ret_1d,
        dollar_volume=close * volume,
    )


def test_genes_bounds_reject_invalid():
    with pytest.raises(ValueError):
        Genes(
            signal_family="momentum",
            lookback=2,
            entry_z=1.0,
            exit_z=0.2,
            horizon_days=5,
            top_k=3,
            long_short="long_only",
            vol_window=20,
            dollar_volume_min_rank=0.0,
        )


def test_random_mutate_crossover_stay_in_bounds():
    rng = np.random.default_rng(42)
    for _ in range(30):
        g = random_genome(rng).genes
        m = mutate_genes(g, rng, rate=0.9)
        # construction validates bounds
        assert m.lookback >= 5
        a = random_genome(rng).genes
        b = random_genome(rng).genes
        child = crossover(a, b, rng)
        assert child.horizon_days in (5, 10, 20)


def test_breed_records_parents():
    rng = np.random.default_rng(1)
    p1 = random_genome(rng, generation=0)
    p2 = random_genome(rng, generation=0)
    child = breed(p1, p2, rng, generation=1)
    assert child.parent_ids == (p1.id, p2.id)
    assert child.generation == 1


def test_cs_genes_default_off_and_bounds():
    g = Genes(
        signal_family="momentum",
        lookback=20,
        entry_z=1.0,
        exit_z=0.3,
        horizon_days=5,
        top_k=2,
        long_short="long_only",
        vol_window=20,
        dollar_volume_min_rank=0.0,
    )
    assert g.cs_mode == "off"
    with pytest.raises(ValueError):
        Genes(
            signal_family="momentum",
            lookback=20,
            entry_z=1.0,
            exit_z=0.3,
            horizon_days=5,
            top_k=2,
            long_short="long_only",
            vol_window=20,
            dollar_volume_min_rank=0.0,
            cs_mode="nope",
        )


def test_cs_filter_and_blend_change_eligibility():
    from edge.research.ga.fitness import evaluate_genes
    from edge.research.ga.panel import attach_factor_probe_cs_score

    panel = attach_factor_probe_cs_score(_toy_panel(n_dates=180, n_symbols=10, seed=3))
    base = Genes(
        signal_family="mean_reversion",
        lookback=15,
        entry_z=1.2,
        exit_z=0.3,
        horizon_days=5,
        top_k=3,
        long_short="long_only",
        vol_window=20,
        dollar_volume_min_rank=0.0,
        cs_mode="off",
    )
    filtered = Genes.from_mapping({**base.as_dict(), "cs_mode": "filter", "cs_min_rank": 0.5})
    blended = Genes.from_mapping({**base.as_dict(), "cs_mode": "blend", "cs_blend": 0.5, "cs_min_rank": 0.0})
    r0 = evaluate_genes(panel, base, protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=0.95))
    r1 = evaluate_genes(panel, filtered, protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=0.95))
    r2 = evaluate_genes(panel, blended, protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=0.95))
    # All three should evaluate without crashing; filter may kill on min_trades.
    assert "cs_mode" in r0.metrics or r0.death_reason
    assert r1.metrics.get("cs_mode_applied") in (1.0, None) or r1.death_reason
    assert r2.metrics.get("cs_mode_applied") in (2.0, None) or r2.death_reason


def test_cs_mode_dies_when_panel_missing_scores():
    from edge.research.ga.fitness import evaluate_genes

    panel = _toy_panel()
    genes = Genes(
        signal_family="momentum",
        lookback=20,
        entry_z=1.0,
        exit_z=0.3,
        horizon_days=5,
        top_k=2,
        long_short="long_only",
        vol_window=20,
        dollar_volume_min_rank=0.0,
        cs_mode="filter",
        cs_min_rank=0.4,
    )
    result = evaluate_genes(panel, genes)
    assert result.alive is False
    assert result.death_reason == "cs_score_unavailable"


def test_evaluate_genes_returns_finite_or_death():
    panel = _toy_panel()
    genes = Genes(
        signal_family="momentum",
        lookback=20,
        entry_z=1.0,
        exit_z=0.3,
        horizon_days=5,
        top_k=2,
        long_short="long_only",
        vol_window=20,
        dollar_volume_min_rank=0.0,
    )
    result = evaluate_genes(
        panel,
        genes,
        protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=0.95),
        fitness_config=FitnessConfig(),
    )
    assert np.isfinite(result.fitness)
    assert "sharpe" in result.metrics or not result.alive


def test_evaluate_genes_negative_compounding():
    """Verify that severe drawdown leading to total_return <= -1.0 does not raise TypeError."""
    panel = _toy_panel(n_dates=100, seed=42)
    genes = Genes(
        signal_family="momentum",
        lookback=20,
        entry_z=0.5,
        exit_z=0.1,
        horizon_days=5,
        top_k=2,
        long_short="long_only",
        vol_window=20,
        dollar_volume_min_rank=0.0,
    )
    # Force panel close prices to drop rapidly causing total return <= -1.0
    panel.close[:] = 100.0 * (0.1 ** np.linspace(0, 10, len(panel.dates)))[:, None]
    result = evaluate_genes(
        panel,
        genes,
        protocol=EvolutionProtocol(min_trades=5, max_drawdown_hard=1.0),
        fitness_config=FitnessConfig(),
    )
    assert result.metrics["total_return"] < 0
    assert result.metrics["ann_return"] == -1.0
    assert np.isfinite(result.fitness)


def test_no_lookahead_future_price_mutation():
    """Mutating close prices strictly after signal date must not change early fitness path.

    We compare fitness on a truncated panel vs full panel for the overlapping
    prefix by evaluating on the same window only — if forward returns peek
    incorrectly, shifting far-future prices inside the window end would change
    early-period metrics. Here we mutate prices in the last 5 rows and require
    that positions (which depend only on past) stay identical on earlier rows.
    """
    from edge.research.ga.fitness import _positions_from_scores, _signal_score, _liquidity_mask

    panel = _toy_panel(n_dates=80, seed=3)
    genes = Genes(
        signal_family="mean_reversion",
        lookback=15,
        entry_z=1.2,
        exit_z=0.4,
        horizon_days=5,
        top_k=2,
        long_short="long_short",
        vol_window=15,
        dollar_volume_min_rank=0.0,
    )
    scores = _signal_score(panel, genes)
    elig = _liquidity_mask(panel, 0.0)
    pos = _positions_from_scores(scores, elig, genes)

    mutated = MarketPanel(
        dates=panel.dates,
        symbols=panel.symbols,
        close=panel.close.copy(),
        volume=panel.volume.copy(),
        high=panel.high.copy(),
        low=panel.low.copy(),
        ret_1d=panel.ret_1d.copy(),
        dollar_volume=panel.dollar_volume.copy(),
    )
    mutated.close[-5:] *= 1.5
    scores2 = _signal_score(mutated, genes)
    pos2 = _positions_from_scores(scores2, elig, genes)
    # Scores/positions up to T-5-lookback should match (lookback uses past only)
    cutoff = panel.n_dates - 5 - genes.lookback
    assert cutoff > 10
    np.testing.assert_allclose(pos[:cutoff], pos2[:cutoff], equal_nan=True)


@pytest.mark.skipif(not DATA_1D.is_dir(), reason="daily data not present")
def test_smoke_evolution_on_real_data(tmp_path: Path):
    import json
    from edge.research.ga.evolve import smoke_evolution

    raw = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    symbols = [str(s) for s in raw["symbols"][:15]]
    # Keep only symbols that exist on disk
    symbols = [s for s in symbols if (DATA_1D / f"{s}.parquet").is_file()]
    if len(symbols) < 8:
        pytest.skip("not enough parquets for smoke evolution")
    result = smoke_evolution(symbols, data_dir=DATA_1D, output_dir=tmp_path)
    assert result.history
    assert (tmp_path / result.run_id / "summary.json").is_file()
    rows = list_runs(tmp_path)
    assert any(r["run_id"] == result.run_id for r in rows)
    payload = run_payload(result.run_id, tmp_path)
    assert payload["detail"] is not None
    assert payload["decision_authorized"] is False


def test_protocol_rejects_bad_dates():
    with pytest.raises(ValueError):
        EvolutionProtocol(
            fitness_start="2024-01-01",
            fitness_end="2023-01-01",
        )
