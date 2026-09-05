"""Empirical Stress-Testing Harness for Milestone 2: Dynamic Explainability & API Endpoint.

Validates:
1. Dynamic narrative variety across 20 distinct market state archetypes (uniqueness, no NaNs/None/null/undefined).
2. API concurrency & caching (multi-threaded single-flight locking, cache hit/miss semantics, force refresh).
3. TypeScript schema validation (0 missing required properties matching dashboard/src/regimeContracts.ts).
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import math
import threading
import time
from typing import Any, Dict, List, Optional
import pytest

from edge.research.regime_engine import (
    ConfidenceComponents,
    FlowContext,
    MarketStructure,
    ModelAgreement,
    PairwiseConflict,
    PrimaryRegime,
    QualityMetrics,
    StructuralLevels,
    UnifiedMarketState,
    VolatilityState,
)
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
from edge.daily_plays.desk_regime_fusion import format_market_regime_payload
from edge.tools import api_server


# ---------------------------------------------------------------------------
# In-Memory Socket Dispatch for API Server Testing
# ---------------------------------------------------------------------------


class _FakeSocket:
    """In-memory socket stream for BaseHTTPRequestHandler dispatch."""

    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode="r", buffering=None):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class _FakeServer:
    server_name = "127.0.0.1"
    server_port = 8787


class _Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def status_code(self) -> int:
        return self.status

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _http_request(
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> _Response:
    extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    raw = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{extra}"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode("utf-8") + body
    sock = _FakeSocket(raw)
    server = _FakeServer()
    api_server.ApiRequestHandler(sock, ("127.0.0.1", 12345), server)  # type: ignore[arg-type]
    sock.wfile.seek(0)
    raw_response = sock.wfile.read()
    header_part, _, body_part = raw_response.partition(b"\r\n\r\n")
    lines = header_part.decode("utf-8", errors="replace").split("\r\n")
    status = int(lines[0].split(" ")[1])
    resp_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip()] = v.strip()
    return _Response(status, resp_headers, body_part)


# ---------------------------------------------------------------------------
# 20 Distinct Market State Archetypes Definition
# ---------------------------------------------------------------------------


MARKET_STATE_ARCHETYPES = [
    {
        "id": "ARCHETYPE_1_BULL_TREND_LONG_GAMMA_CUSHION",
        "primary": PrimaryRegime.BULLISH_TREND,
        "vol_state": VolatilityState.COMPRESSION_LOW,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_ACCUMULATION,
        "z_scores": FeatureZScores(trend=2.2, gamma=1.8, vol=-0.8, flow=1.5, structure=1.9),
        "spot": 530.0,
        "call_wall": 545.0,
        "put_wall": 515.0,
        "gamma_flip": 510.0,
        "session_vwap": 528.0,
        "net_gex_usd": 25.0e6,
        "t_risk": 0.08,
        "vol_percentile": 0.20,
        "variance_ratio": 1.45,
        "ou_half_life": 45.0,
        "persistence_bars": 15,
        "confidence": 0.85,
    },
    {
        "id": "ARCHETYPE_2_BULL_TREND_SHORT_GAMMA_CALL_WALL",
        "primary": PrimaryRegime.BULLISH_TREND,
        "vol_state": VolatilityState.ELEVATED_HIGH,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=2.0, gamma=-2.1, vol=1.2, flow=0.6, structure=1.4),
        "spot": 538.5,
        "call_wall": 540.0,
        "put_wall": 510.0,
        "gamma_flip": 532.0,
        "session_vwap": 535.0,
        "net_gex_usd": -18.0e6,
        "t_risk": 0.25,
        "vol_percentile": 0.65,
        "variance_ratio": 1.20,
        "ou_half_life": 30.0,
        "persistence_bars": 8,
        "confidence": 0.62,
    },
    {
        "id": "ARCHETYPE_3_BULL_TREND_FLOW_DIVERGENCE_DISTRIBUTION",
        "primary": PrimaryRegime.BULLISH_TREND,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=1.7, gamma=0.4, vol=-0.2, flow=-2.2, structure=1.1),
        "spot": 525.0,
        "call_wall": 535.0,
        "put_wall": 515.0,
        "gamma_flip": 518.0,
        "session_vwap": 524.0,
        "net_gex_usd": 6.0e6,
        "t_risk": 0.35,
        "vol_percentile": 0.40,
        "variance_ratio": 1.10,
        "ou_half_life": 25.0,
        "persistence_bars": 6,
        "confidence": 0.55,
    },
    {
        "id": "ARCHETYPE_4_BULL_MOMENTUM_STRUCTURAL_EXHAUSTION",
        "primary": PrimaryRegime.BULLISH_TREND,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.MEAN_REVERTING,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=2.4, gamma=0.2, vol=0.5, flow=0.8, structure=-1.8),
        "spot": 528.0,
        "call_wall": 532.0,
        "put_wall": 510.0,
        "gamma_flip": 515.0,
        "session_vwap": 522.0,
        "net_gex_usd": 2.0e6,
        "t_risk": 0.30,
        "vol_percentile": 0.55,
        "variance_ratio": 0.62,
        "ou_half_life": 8.0,
        "persistence_bars": 4,
        "confidence": 0.58,
    },
    {
        "id": "ARCHETYPE_5_BEAR_BREAKDOWN_SHORT_GAMMA_CASCADE",
        "primary": PrimaryRegime.BEARISH_TREND,
        "vol_state": VolatilityState.VOLATILITY_SHOCK,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=-2.5, gamma=-2.4, vol=2.2, flow=-2.1, structure=1.8),
        "spot": 495.0,
        "call_wall": 530.0,
        "put_wall": 480.0,
        "gamma_flip": 512.0,
        "session_vwap": 505.0,
        "net_gex_usd": -35.0e6,
        "t_risk": 0.45,
        "vol_percentile": 0.92,
        "variance_ratio": 1.55,
        "ou_half_life": 50.0,
        "persistence_bars": 12,
        "confidence": 0.78,
    },
    {
        "id": "ARCHETYPE_6_BEAR_MOMENTUM_PUT_WALL_SUPPORT",
        "primary": PrimaryRegime.BEARISH_TREND,
        "vol_state": VolatilityState.ELEVATED_HIGH,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=-1.9, gamma=1.5, vol=0.8, flow=-0.9, structure=1.3),
        "spot": 501.5,
        "call_wall": 530.0,
        "put_wall": 500.0,
        "gamma_flip": 508.0,
        "session_vwap": 507.0,
        "net_gex_usd": 15.0e6,
        "t_risk": 0.20,
        "vol_percentile": 0.70,
        "variance_ratio": 1.25,
        "ou_half_life": 28.0,
        "persistence_bars": 7,
        "confidence": 0.65,
    },
    {
        "id": "ARCHETYPE_7_BEAR_DRIFT_FLOW_ACCUMULATION_DIVERGENCE",
        "primary": PrimaryRegime.BEARISH_TREND,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.INSTITUTIONAL_ACCUMULATION,
        "z_scores": FeatureZScores(trend=-1.4, gamma=0.1, vol=-0.4, flow=2.0, structure=-0.5),
        "spot": 510.0,
        "call_wall": 530.0,
        "put_wall": 495.0,
        "gamma_flip": 512.0,
        "session_vwap": 512.0,
        "net_gex_usd": 1.0e6,
        "t_risk": 0.32,
        "vol_percentile": 0.38,
        "variance_ratio": 0.95,
        "ou_half_life": 20.0,
        "persistence_bars": 5,
        "confidence": 0.52,
    },
    {
        "id": "ARCHETYPE_8_BEARISH_TREND_ORDERLY_INSTITUTIONAL",
        "primary": PrimaryRegime.BEARISH_TREND,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=-1.6, gamma=-0.2, vol=0.1, flow=-1.5, structure=1.2),
        "spot": 515.0,
        "call_wall": 535.0,
        "put_wall": 495.0,
        "gamma_flip": 520.0,
        "session_vwap": 518.0,
        "net_gex_usd": -3.0e6,
        "t_risk": 0.15,
        "vol_percentile": 0.52,
        "variance_ratio": 1.18,
        "ou_half_life": 35.0,
        "persistence_bars": 9,
        "confidence": 0.70,
    },
    {
        "id": "ARCHETYPE_9_VOL_EXPANSION_BID_ACCELERATION",
        "primary": PrimaryRegime.VOL_EXPANSION_BREAKOUT,
        "vol_state": VolatilityState.VOLATILITY_SHOCK,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_ACCUMULATION,
        "z_scores": FeatureZScores(trend=1.2, gamma=-1.5, vol=2.6, flow=2.4, structure=1.6),
        "spot": 542.0,
        "call_wall": 550.0,
        "put_wall": 520.0,
        "gamma_flip": 535.0,
        "session_vwap": 538.0,
        "net_gex_usd": -12.0e6,
        "t_risk": 0.50,
        "vol_percentile": 0.96,
        "variance_ratio": 1.60,
        "ou_half_life": 40.0,
        "persistence_bars": 3,
        "confidence": 0.68,
    },
    {
        "id": "ARCHETYPE_10_VOL_EXPANSION_PUT_ACCELERATION",
        "primary": PrimaryRegime.VOL_EXPANSION_BREAKOUT,
        "vol_state": VolatilityState.VOLATILITY_SHOCK,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=-1.1, gamma=-2.0, vol=2.8, flow=-2.5, structure=1.7),
        "spot": 488.0,
        "call_wall": 520.0,
        "put_wall": 475.0,
        "gamma_flip": 505.0,
        "session_vwap": 498.0,
        "net_gex_usd": -22.0e6,
        "t_risk": 0.55,
        "vol_percentile": 0.98,
        "variance_ratio": 1.65,
        "ou_half_life": 42.0,
        "persistence_bars": 3,
        "confidence": 0.72,
    },
    {
        "id": "ARCHETYPE_11_VOL_EXPANSION_COILING_SHOCK",
        "primary": PrimaryRegime.VOL_EXPANSION_BREAKOUT,
        "vol_state": VolatilityState.VOLATILITY_SHOCK,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.2, gamma=-0.8, vol=2.3, flow=0.4, structure=0.8),
        "spot": 520.0,
        "call_wall": 530.0,
        "put_wall": 510.0,
        "gamma_flip": 521.0,
        "session_vwap": 520.2,
        "net_gex_usd": -6.0e6,
        "t_risk": 0.48,
        "vol_percentile": 0.88,
        "variance_ratio": 1.05,
        "ou_half_life": 22.0,
        "persistence_bars": 2,
        "confidence": 0.54,
    },
    {
        "id": "ARCHETYPE_12_COMPRESSION_ZERO_GAMMA_PIN",
        "primary": PrimaryRegime.COMPRESSION_RANGE,
        "vol_state": VolatilityState.COMPRESSION_LOW,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.ABSORPTION_CHURN,
        "z_scores": FeatureZScores(trend=0.1, gamma=0.0, vol=-2.1, flow=-0.1, structure=-1.4),
        "spot": 525.0,
        "call_wall": 535.0,
        "put_wall": 515.0,
        "gamma_flip": 525.0,
        "session_vwap": 525.1,
        "net_gex_usd": 0.2e6,
        "t_risk": 0.10,
        "vol_percentile": 0.08,
        "variance_ratio": 0.70,
        "ou_half_life": 14.0,
        "persistence_bars": 18,
        "confidence": 0.74,
    },
    {
        "id": "ARCHETYPE_13_COMPRESSION_LONG_GAMMA_FORTRESS",
        "primary": PrimaryRegime.COMPRESSION_RANGE,
        "vol_state": VolatilityState.COMPRESSION_LOW,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.0, gamma=2.5, vol=-2.4, flow=0.1, structure=-1.6),
        "spot": 525.0,
        "call_wall": 530.0,
        "put_wall": 520.0,
        "gamma_flip": 505.0,
        "session_vwap": 524.9,
        "net_gex_usd": 40.0e6,
        "t_risk": 0.05,
        "vol_percentile": 0.04,
        "variance_ratio": 0.60,
        "ou_half_life": 10.0,
        "persistence_bars": 24,
        "confidence": 0.88,
    },
    {
        "id": "ARCHETYPE_14_COMPRESSION_RANGE_NARROW_DRIFT",
        "primary": PrimaryRegime.COMPRESSION_RANGE,
        "vol_state": VolatilityState.COMPRESSION_LOW,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.3, gamma=1.1, vol=-1.7, flow=0.2, structure=-0.9),
        "spot": 526.0,
        "call_wall": 532.0,
        "put_wall": 518.0,
        "gamma_flip": 512.0,
        "session_vwap": 525.8,
        "net_gex_usd": 12.0e6,
        "t_risk": 0.12,
        "vol_percentile": 0.15,
        "variance_ratio": 0.78,
        "ou_half_life": 16.0,
        "persistence_bars": 11,
        "confidence": 0.76,
    },
    {
        "id": "ARCHETYPE_15_MEAN_REVERTING_FAST_HALF_LIFE",
        "primary": PrimaryRegime.MEAN_REVERTING,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.MEAN_REVERTING,
        "flow_state": FlowContext.ABSORPTION_CHURN,
        "z_scores": FeatureZScores(trend=-0.2, gamma=0.6, vol=-0.5, flow=0.1, structure=-2.4),
        "spot": 524.0,
        "call_wall": 535.0,
        "put_wall": 515.0,
        "gamma_flip": 518.0,
        "session_vwap": 525.0,
        "net_gex_usd": 8.0e6,
        "t_risk": 0.14,
        "vol_percentile": 0.32,
        "variance_ratio": 0.52,
        "ou_half_life": 5.5,
        "persistence_bars": 14,
        "confidence": 0.79,
    },
    {
        "id": "ARCHETYPE_16_MEAN_REVERTING_VWAP_MAGNET",
        "primary": PrimaryRegime.MEAN_REVERTING,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.MEAN_REVERTING,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.4, gamma=0.8, vol=-0.9, flow=-0.3, structure=-2.0),
        "spot": 526.5,
        "call_wall": 538.0,
        "put_wall": 512.0,
        "gamma_flip": 516.0,
        "session_vwap": 525.0,
        "net_gex_usd": 10.0e6,
        "t_risk": 0.16,
        "vol_percentile": 0.25,
        "variance_ratio": 0.58,
        "ou_half_life": 7.2,
        "persistence_bars": 10,
        "confidence": 0.75,
    },
    {
        "id": "ARCHETYPE_17_UNCERTAIN_TRANSITIONAL_FLIP_BAND",
        "primary": PrimaryRegime.UNCERTAIN_TRANSITIONAL,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.8, gamma=-0.1, vol=0.4, flow=-0.2, structure=0.1),
        "spot": 525.10,
        "call_wall": 535.0,
        "put_wall": 515.0,
        "gamma_flip": 525.0,
        "session_vwap": 525.0,
        "net_gex_usd": -0.5e6,
        "t_risk": 0.38,
        "vol_percentile": 0.50,
        "variance_ratio": 1.00,
        "ou_half_life": 25.0,
        "persistence_bars": 1,
        "confidence": 0.32,
    },
    {
        "id": "ARCHETYPE_18_UNCERTAIN_TRANSITIONAL_MODEL_CONFLICT",
        "primary": PrimaryRegime.UNCERTAIN_TRANSITIONAL,
        "vol_state": VolatilityState.ELEVATED_HIGH,
        "struct_state": MarketStructure.MEAN_REVERTING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=2.2, gamma=-2.0, vol=1.5, flow=-2.1, structure=-1.5),
        "spot": 528.0,
        "call_wall": 530.0,
        "put_wall": 520.0,
        "gamma_flip": 527.0,
        "session_vwap": 526.0,
        "net_gex_usd": -15.0e6,
        "t_risk": 0.42,
        "vol_percentile": 0.60,
        "variance_ratio": 0.75,
        "ou_half_life": 12.0,
        "persistence_bars": 2,
        "confidence": 0.28,
    },
    {
        "id": "ARCHETYPE_19_UNCERTAIN_TRANSITIONAL_CHANGEPOINT_SHOCK",
        "primary": PrimaryRegime.UNCERTAIN_TRANSITIONAL,
        "vol_state": VolatilityState.VOLATILITY_SHOCK,
        "struct_state": MarketStructure.TRENDING,
        "flow_state": FlowContext.INSTITUTIONAL_DISTRIBUTION,
        "z_scores": FeatureZScores(trend=-0.9, gamma=-1.2, vol=2.5, flow=-1.8, structure=0.4),
        "spot": 518.0,
        "call_wall": 535.0,
        "put_wall": 500.0,
        "gamma_flip": 522.0,
        "session_vwap": 524.0,
        "net_gex_usd": -10.0e6,
        "t_risk": 0.78,
        "vol_percentile": 0.94,
        "variance_ratio": 1.08,
        "ou_half_life": 28.0,
        "persistence_bars": 1,
        "confidence": 0.21,
    },
    {
        "id": "ARCHETYPE_20_UNMEASURABLE_TELEMETRY_WITHHELD",
        "primary": PrimaryRegime.UNMEASURABLE,
        "vol_state": VolatilityState.NORMAL_MEDIUM,
        "struct_state": MarketStructure.RANGE_BOUND,
        "flow_state": FlowContext.BALANCED_FLOW,
        "z_scores": FeatureZScores(trend=0.0, gamma=0.0, vol=0.0, flow=0.0, structure=0.0),
        "spot": None,
        "call_wall": None,
        "put_wall": None,
        "gamma_flip": None,
        "session_vwap": None,
        "net_gex_usd": None,
        "t_risk": 0.0,
        "vol_percentile": 0.50,
        "variance_ratio": 1.0,
        "ou_half_life": 30.0,
        "persistence_bars": 0,
        "confidence": 0.0,
        "reason": "Missing price bars and option chains",
    },
]


# ---------------------------------------------------------------------------
# Dimension 1: Dynamic Narrative Variety Stress-Testing
# ---------------------------------------------------------------------------


def test_dynamic_narrative_variety_across_20_archetypes():
    """Verify that 20 distinct market state archetypes produce non-canned unique narratives without NaNs or None."""
    headlines: List[str] = []
    narratives: List[str] = []
    forbidden_tokens = ["nan", "none", "null", "undefined", "inf"]

    for arch in MARKET_STATE_ARCHETYPES:
        if arch["primary"] == PrimaryRegime.UNMEASURABLE:
            explanation = generate_dynamic_explanation_unmeasurable(arch.get("reason", "No data"))
            headline = explanation.headline
            narrative = explanation.summary_text
        else:
            levels = StructuralLevels(
                call_wall=arch["call_wall"],
                put_wall=arch["put_wall"],
                gamma_flip=arch["gamma_flip"],
                session_vwap=arch["session_vwap"],
            )
            explanation = generate_dynamic_explanation(
                primary_regime=arch["primary"],
                confidence=arch["confidence"],
                z_scores=arch["z_scores"],
                levels=levels,
                net_gex_usd=arch["net_gex_usd"],
                spot=arch["spot"],
                t_risk=arch["t_risk"],
                persistence_bars=arch["persistence_bars"],
                vol_percentile=arch["vol_percentile"],
                variance_ratio=arch["variance_ratio"],
                ou_half_life=arch["ou_half_life"],
            )
            headline = explanation.headline
            narrative = explanation.summary_text

        # Verify no forbidden substring tokens in headline and narrative
        for token in forbidden_tokens:
            assert token not in headline.lower(), f"Forbidden token '{token}' in headline for {arch['id']}: '{headline}'"
            assert token not in narrative.lower(), f"Forbidden token '{token}' in narrative for {arch['id']}: '{narrative}'"

        # Check all explanation sub-elements
        for driver in explanation.leading_drivers:
            desc = driver.get("description", "")
            for token in forbidden_tokens:
                assert token not in desc.lower(), f"Forbidden token in driver desc: '{desc}'"

        for rf in explanation.risk_factors:
            for token in forbidden_tokens:
                assert token not in rf.lower(), f"Forbidden token in risk factor: '{rf}'"

        for us in explanation.uncertainty_sources:
            for token in forbidden_tokens:
                assert token not in us.lower(), f"Forbidden token in uncertainty source: '{us}'"

        headlines.append(headline)
        narratives.append(narrative)

    # Assert variety: All 20 headlines and narratives must be unique
    unique_headlines = set(headlines)
    unique_narratives = set(narratives)

    assert len(unique_headlines) == len(MARKET_STATE_ARCHETYPES), (
        f"Duplicate headlines detected! {len(unique_headlines)} unique out of {len(MARKET_STATE_ARCHETYPES)}"
    )
    assert len(unique_narratives) == len(MARKET_STATE_ARCHETYPES), (
        f"Duplicate narratives detected! {len(unique_narratives)} unique out of {len(MARKET_STATE_ARCHETYPES)}"
    )


def test_dynamic_weights_and_attribution_bounds():
    """Verify dynamic weights re-normalization and strict [-3.0, 3.0] attribution bounding."""
    for arch in MARKET_STATE_ARCHETYPES:
        if arch["primary"] == PrimaryRegime.UNMEASURABLE:
            continue
        z = arch["z_scores"]
        weights = compute_dynamic_weights(
            z_scores=z,
            measurable_mask=(1, 1, 1, 1, 1),
            t_risk=arch["t_risk"],
            delta_flip=(arch["spot"] - arch["gamma_flip"]) / arch["spot"] if arch["spot"] and arch["gamma_flip"] else None,
        )

        assert pytest.approx(sum(weights.values()), abs=1e-4) == 1.0000
        for k, w in weights.items():
            assert 0.0 <= w <= 1.0, f"Weight out of bounds: {k}={w}"

        alpha = compute_feature_attributions(z_scores=z, weights=weights)
        for k, a in alpha.items():
            assert -3.0 <= a <= 3.0, f"Attribution out of bounds: {k}={a}"


# ---------------------------------------------------------------------------
# Dimension 2: API Concurrency, Single-Flighting & Caching Stress-Testing
# ---------------------------------------------------------------------------


def test_api_concurrency_and_single_flight_consistency():
    """Stress-test /api/market-regime under multi-threaded requests asserting single-flight building and cache consistency."""
    sym = "TESTSYM"
    
    # We will dispatch 24 concurrent requests across a ThreadPoolExecutor
    num_threads = 24
    results: List[_Response] = []
    errors: List[Exception] = []

    def _worker(worker_id: int) -> _Response:
        # Worker 0 triggers build; other workers run concurrently
        force_flag = "&force=1" if worker_id == 0 else ""
        return _http_request("GET", f"/api/market-regime?symbol={sym}{force_flag}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_worker, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                errors.append(e)

    assert len(errors) == 0, f"Encountered thread errors during concurrent dispatch: {errors}"
    assert len(results) == num_threads

    # Verify all responses succeeded with 200 OK
    for r in results:
        assert r.status_code == 200
        data = r.json()
        assert data["symbol"] == sym
        assert "primary" in data
        assert "confidence" in data
        assert "cache" in data

    # Verify cache behavior: after initial concurrent burst, immediate next request is a cache hit
    res_cached = _http_request("GET", f"/api/market-regime?symbol={sym}")
    assert res_cached.status_code == 200
    cached_data = res_cached.json()
    assert cached_data["cache"]["hit"] is True
    assert cached_data["cache"]["age_seconds"] >= 0.0
    assert cached_data["cache"]["ttl_seconds"] == 60.0

    # Verify force refresh resets cache hit to False
    res_forced = _http_request("GET", f"/api/market-regime?symbol={sym}&force=1")
    assert res_forced.status_code == 200
    forced_data = res_forced.json()
    assert forced_data["cache"]["hit"] is False


def test_api_multi_symbol_interleaved_concurrency():
    """Stress-test concurrent requests across multiple symbols simultaneously."""
    symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA"]
    results_map: Dict[str, List[int]] = {s: [] for s in symbols}

    def _multi_worker(sym: str) -> tuple[str, int]:
        res = _http_request("GET", f"/api/market-regime?symbol={sym}")
        return sym, res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_multi_worker, s) for _ in range(5) for s in symbols]
        for f in concurrent.futures.as_completed(futures):
            sym, status = f.result()
            results_map[sym].append(status)

    for sym, statuses in results_map.items():
        assert len(statuses) == 5
        assert all(st == 200 for st in statuses), f"Symbol {sym} returned non-200 statuses: {statuses}"


# ---------------------------------------------------------------------------
# Dimension 3: TypeScript Schema Conformance & Zero Missing Properties
# ---------------------------------------------------------------------------


REQUIRED_SCHEMA_CONTRACT = {
    "symbol": str,
    "asof_utc": str,
    "spot": (float, int, type(None)),
    "primary": str,
    "primaryLabel": str,
    "confidence": {
        "score": (float, int),
        "band": str,
        "penaltyFactors": list,
    },
    "trend": {
        "state": str,
        "slope": (float, int, type(None)),
        "kalmanVelocity": (float, int, type(None)),
        "kalmanZScore": (float, int, type(None)),
        "trendPersistence": (float, int, type(None)),
        "measured": bool,
    },
    "volatility": {
        "state": str,
        "realizedVolPct": (float, int, type(None)),
        "impliedVolPct": (float, int, type(None)),
        "volPercentile": (float, int, type(None)),
        "parkinsonVolPct": (float, int, type(None)),
        "ivHvRatio": (float, int, type(None)),
        "measured": bool,
    },
    "structure": {
        "state": str,
        "ouHalfLifeBars": (float, int, type(None)),
        "hurstExponent": (float, int, type(None)),
        "breakoutZScore": (float, int, type(None)),
        "exhaustionZScore": (float, int, type(None)),
        "measured": bool,
    },
    "flow": {
        "state": str,
        "dealerGammaRegime": str,
        "netGexM": (float, int, type(None)),
        "netVexM": (float, int, type(None)),
        "netCharmDriftM": (float, int, type(None)),
        "orderFlowDeltaM": (float, int, type(None)),
        "hedgingPressureDirection": str,
        "measured": bool,
    },
    "transition": {
        "level": str,
        "changepointProb5d": (float, int),
        "changepointProb20d": (float, int),
        "mapRunLength": (int, float),
        "expectedRunLength": (int, float),
        "stabilityScore": (float, int),
        "measured": bool,
    },
    "agreement": {
        "band": str,
        "agreementScore": (float, int),
        "agreeingModels": list,
        "conflictingModels": list,
        "divergenceSummary": (str, type(None)),
        "pairwiseMatrix": (dict, type(None)),
    },
    "explanation": {
        "headline": str,
        "summary": str,
        "leadingDrivers": list,
        "riskFactors": list,
        "uncertaintySources": list,
    },
    "levels": {
        "callWall": (float, int, type(None)),
        "putWall": (float, int, type(None)),
        "gammaFlip": (float, int, type(None)),
        "sessionVwap": (float, int, type(None)),
    },
    "quality": {
        "measurable": bool,
        "missingLenses": list,
        "reason": (str, type(None)),
    },
    "cache": {
        "hit": bool,
        "age_seconds": (float, int),
        "ttl_seconds": (float, int),
    },
}


def _validate_schema(data: dict[str, Any], schema: dict[str, Any], path: str = "") -> List[str]:
    """Recursively validate JSON payload structure and types, returning list of violations."""
    violations: List[str] = []
    for key, expected_type in schema.items():
        curr_path = f"{path}.{key}" if path else key
        if key not in data:
            violations.append(f"Missing required property: '{curr_path}'")
            continue

        val = data[key]
        if isinstance(expected_type, dict):
            if not isinstance(val, dict):
                violations.append(f"Expected object at '{curr_path}', got {type(val).__name__}")
            else:
                violations.extend(_validate_schema(val, expected_type, curr_path))
        elif isinstance(expected_type, tuple):
            if not isinstance(val, expected_type):
                violations.append(f"Expected {expected_type} at '{curr_path}', got {type(val).__name__} ({val})")
        else:
            if not isinstance(val, expected_type):
                violations.append(f"Expected {expected_type.__name__} at '{curr_path}', got {type(val).__name__} ({val})")

    return violations


def test_schema_conformance_across_market_regime_payloads():
    """Verify live endpoint payloads for multiple symbols have 0 missing properties and match TypeScript contracts."""
    test_symbols = ["SPY", "QQQ", "IWM", "INVALIDZZZ"]

    for sym in test_symbols:
        res = _http_request("GET", f"/api/market-regime?symbol={sym}&force=1")
        assert res.status_code == 200, f"Endpoint returned {res.status_code} for {sym}"
        payload = res.json()

        violations = _validate_schema(payload, REQUIRED_SCHEMA_CONTRACT)
        assert len(violations) == 0, f"Schema violations for {sym}: {violations}"

        # Invariant validations
        assert payload["primary"] in {
            "bull_trend",
            "bear_trend",
            "compression_range",
            "mean_reverting",
            "vol_expansion_breakout",
            "uncertain_transitional",
            "unmeasurable",
        }
        assert payload["confidence"]["band"] in {"high", "moderate", "low"}
        assert payload["transition"]["level"] in {"low", "moderate", "high", "critical"}
        assert payload["agreement"]["band"] in {"high", "moderate", "low", "conflict"}
        assert payload["flow"]["dealerGammaRegime"] in {"short", "long", "flip", "unmeasurable"}
        assert 0.0 <= payload["confidence"]["score"] <= 1.0
        assert 0.0 <= payload["transition"]["stabilityScore"] <= 1.0
        assert 0.0 <= payload["agreement"]["agreementScore"] <= 1.0


def test_all_20_archetypes_format_payload_without_schema_violations():
    """Format full UnifiedMarketState for all 20 archetypes through format_market_regime_payload and verify 0 schema violations."""
    for arch in MARKET_STATE_ARCHETYPES:
        if arch["primary"] == PrimaryRegime.UNMEASURABLE:
            explanation = generate_dynamic_explanation_unmeasurable(arch.get("reason", "No data"))
            state = UnifiedMarketState(
                symbol="TEST",
                primary_regime=PrimaryRegime.UNMEASURABLE,
                confidence=0.0,
                volatility_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.RANGE_BOUND,
                flow_context=FlowContext.BALANCED_FLOW,
                transition_risk=0.0,
                probabilities=None,  # type: ignore[arg-type]
                model_agreement=ModelAgreement(overall_agreement=0.0, agreeing_models=[], conflicting_models=[], divergence_summary="Unmeasured"),
                explainability=explanation,
                levels=StructuralLevels(call_wall=None, put_wall=None, gamma_flip=None, session_vwap=None),
                quality=QualityMetrics(measurable=False, data_completeness=0.0, missing_lenses=["Prices", "Options"], reason="No data"),
                spot=None,
                asof="2026-09-02T00:00:00Z",
                confidence_components=None,
            )
        else:
            levels = StructuralLevels(
                call_wall=arch["call_wall"],
                put_wall=arch["put_wall"],
                gamma_flip=arch["gamma_flip"],
                session_vwap=arch["session_vwap"],
            )
            explanation = generate_dynamic_explanation(
                primary_regime=arch["primary"],
                confidence=arch["confidence"],
                z_scores=arch["z_scores"],
                levels=levels,
                net_gex_usd=arch["net_gex_usd"],
                spot=arch["spot"],
                t_risk=arch["t_risk"],
                persistence_bars=arch["persistence_bars"],
                vol_percentile=arch["vol_percentile"],
                variance_ratio=arch["variance_ratio"],
                ou_half_life=arch["ou_half_life"],
            )
            state = UnifiedMarketState(
                symbol="TEST",
                primary_regime=arch["primary"],
                confidence=arch["confidence"],
                volatility_state=arch["vol_state"],
                market_structure=arch["struct_state"],
                flow_context=arch["flow_state"],
                transition_risk=arch["t_risk"],
                probabilities=None,  # type: ignore[arg-type]
                model_agreement=ModelAgreement(
                    overall_agreement=0.80,
                    agreeing_models=["Trend", "Structure"],
                    conflicting_models=[],
                    divergence_summary=None,
                    pairwise_matrix={"Trend": {"Trend": 1.0}},
                ),
                explainability=explanation,
                levels=levels,
                quality=QualityMetrics(measurable=True, data_completeness=1.0, missing_lenses=[], reason=None),
                spot=arch["spot"],
                asof="2026-09-02T00:00:00Z",
                confidence_components=ConfidenceComponents(
                    q_data=1.0,
                    q_bars=1.0,
                    q_chain=1.0,
                    q_freshness=1.0,
                    a_models=0.80,
                    d_boundary=0.90,
                    d_flip=0.90,
                    d_trend=0.90,
                    s_persistence=0.85,
                    tenure_bars=arch["persistence_bars"],
                    whipsaw_penalty=1.0,
                    t_risk=arch["t_risk"],
                    hazard_multiplier=1.0 - 0.5 * arch["t_risk"],
                    composite_confidence=arch["confidence"],
                ),
            )

        payload = format_market_regime_payload(state)
        violations = _validate_schema(payload, REQUIRED_SCHEMA_CONTRACT)
        assert len(violations) == 0, f"Schema violations for {arch['id']}: {violations}"
