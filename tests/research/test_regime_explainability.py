"""Unit and property tests for Dynamic Explainability Engine."""
from __future__ import annotations

import numpy as np
import pytest

from edge.research.regime_engine import PrimaryRegime, StructuralLevels
from edge.research.regime_explainability import (
    FeatureZScores,
    compute_dynamic_weights,
    compute_feature_attributions,
    generate_dynamic_explanation,
    generate_dynamic_explanation_unmeasurable,
    generate_dynamic_headline,
    generate_dynamic_narrative,
    rank_leading_drivers,
    surface_divergences_and_conflicts,
)


def test_feature_attribution_vector_properties():
    """Verify attribution vector alpha_k = w_k * z_k satisfies all mathematical invariants."""
    z_scores = FeatureZScores(trend=2.0, gamma=-1.5, vol=0.5, flow=1.0, structure=1.8)
    weights = compute_dynamic_weights(
        z_scores, measurable_mask=[1, 1, 1, 1, 1], t_risk=0.10
    )

    assert pytest.approx(sum(weights.values()), abs=1e-4) == 1.0000
    for k, w in weights.items():
        assert 0.0 <= w <= 1.0

    alpha = compute_feature_attributions(z_scores, weights)
    assert pytest.approx(alpha["trend"], abs=1e-4) == weights["trend"] * 2.0
    assert pytest.approx(alpha["gamma"], abs=1e-4) == weights["gamma"] * -1.5
    for k, a in alpha.items():
        assert -3.0 <= a <= 3.0


def test_feature_attribution_missing_options_lens():
    """Verify weights renormalize to 1.0 when options chain is missing (m_gamma = 0)."""
    z_scores = FeatureZScores(trend=1.5, gamma=0.0, vol=-0.5, flow=0.8, structure=1.2)
    weights = compute_dynamic_weights(
        z_scores, measurable_mask=[1, 0, 1, 1, 1], t_risk=0.05
    )

    assert weights["gamma"] == 0.0
    assert pytest.approx(sum(weights.values()), abs=1e-4) == 1.0000
    assert weights["trend"] > 0.25  # Absorbed portion of missing gamma weight


@pytest.mark.parametrize(
    "regime,expected_keyword",
    [
        (PrimaryRegime.BULLISH_TREND, "Bullish"),
        (PrimaryRegime.BEARISH_TREND, "Bearish"),
        (PrimaryRegime.COMPRESSION_RANGE, "Compression"),
        (PrimaryRegime.MEAN_REVERTING, "Mean-Reverting"),
        (PrimaryRegime.VOL_EXPANSION_BREAKOUT, "Expansion"),
        (PrimaryRegime.UNCERTAIN_TRANSITIONAL, "Uncertainty"),
        (PrimaryRegime.UNMEASURABLE, "Withheld"),
    ],
)
def test_dynamic_headline_generation(regime, expected_keyword):
    """Verify dynamic headline synthesis generates meaningful titles without NaN/null."""
    z_scores = FeatureZScores(trend=1.5, gamma=0.8, vol=0.2, flow=0.5, structure=1.0)
    attributions = {"trend": 0.4, "gamma": 0.2, "vol": 0.05, "flow": 0.1, "structure": 0.25}

    headline = generate_dynamic_headline(
        primary_regime=regime,
        z_scores=z_scores,
        attributions=attributions,
        call_wall=540.0,
        put_wall=510.0,
        gamma_flip=525.0,
        spot=528.0,
        vol_percentile=0.45,
        confidence=0.72,
    )

    assert expected_keyword.lower() in headline.lower()
    assert "null" not in headline.lower()
    assert "nan" not in headline.lower()


def test_conflict_surfacing_bull_trend_vs_short_gamma():
    """Verify Bull Trend (+2.0z) with Short Gamma (-1.8z) produces exact divergence narrative."""
    z_scores = FeatureZScores(trend=2.0, gamma=-1.8, vol=1.2, flow=0.5, structure=1.5)
    levels = StructuralLevels(call_wall=535.0, put_wall=505.0, gamma_flip=524.5, session_vwap=527.0)

    explanation = generate_dynamic_explanation(
        primary_regime=PrimaryRegime.BULLISH_TREND,
        confidence=0.68,
        z_scores=z_scores,
        levels=levels,
        net_gex_usd=-1.84e7,
        spot=528.0,
        t_risk=0.10,
        persistence_bars=14,
        vol_percentile=0.48,
    )

    assert "Short Gamma" in explanation.headline
    assert "Call Wall" in explanation.headline or "Call Wall" in explanation.summary_text
    assert any("Short Gamma" in u for u in explanation.uncertainty_sources)
    assert any("Short gamma" in r for r in explanation.risk_factors)


def test_conflict_surfacing_trend_vs_structure():
    """Verify high trend momentum inside mean-reverting structure surfaces structural divergence."""
    z_scores = FeatureZScores(trend=2.2, gamma=0.0, vol=0.3, flow=0.2, structure=-1.5)
    levels = StructuralLevels(call_wall=None, put_wall=None, gamma_flip=None, session_vwap=100.0)

    risk_factors, uncertainty_sources, _ = surface_divergences_and_conflicts(
        z_scores=z_scores,
        spot=100.0,
        variance_ratio=0.65,
        ou_half_life=6.0,
    )

    assert any("Structural Divergence" in u for u in uncertainty_sources)


def test_dynamic_explanation_unmeasurable_zero_spoofing():
    """Verify unmeasurable payload outputs honest withhold message with zero fabricated numbers."""
    explanation = generate_dynamic_explanation_unmeasurable("No price bars available")
    assert "Withheld" in explanation.headline
    assert len(explanation.leading_drivers) == 0
    assert "No price bars available" in explanation.summary_text


def test_dynamic_narrative_4_sentence_structure():
    """Verify generated narrative contains all 4 required structural elements."""
    z_scores = FeatureZScores(trend=1.8, gamma=0.5, vol=-0.2, flow=0.8, structure=1.2)
    attributions = {"trend": 0.45, "gamma": 0.12, "vol": -0.03, "flow": 0.12, "structure": 0.24}

    narrative = generate_dynamic_narrative(
        primary_regime=PrimaryRegime.BULLISH_TREND,
        confidence=0.80,
        attributions=attributions,
        z_scores=z_scores,
        call_wall=540.0,
        put_wall=510.0,
        spot=525.0,
        t_risk=0.10,
        persistence_bars=8,
    )

    # Sentence 1: Conviction & state
    assert "Bullish Trend" in narrative
    assert "Conviction" in narrative or "Confidence" in narrative
    # Sentence 2: Lead drivers
    assert "driven by" in narrative
    # Sentence 3: Headwinds / volatility
    assert "percentile" in narrative or "Call Wall" in narrative or "dealers" in narrative
    # Sentence 4: Stability & changepoint risk
    assert "Transition hazard" in narrative or "persistence" in narrative
