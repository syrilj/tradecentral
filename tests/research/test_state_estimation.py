"""Unit and integration tests for Causal Nadaraya-Watson envelopes, Kinematic Kalman filter, and Anchored VWAP."""
from __future__ import annotations

import math
import pytest
import numpy as np

from edge.research.state_estimation import (
    causal_nadaraya_watson_envelope,
    kinematic_kalman_filter,
    compute_anchored_vwap,
    compute_ou_half_life,
    gaussian_kernel,
    epanechnikov_kernel,
)


def test_kernels():
    u = np.array([0.0, 0.5, 1.0, 1.5])
    gk = gaussian_kernel(u)
    assert gk[0] > gk[1] > gk[2] > gk[3] > 0.0

    ek = epanechnikov_kernel(u)
    assert ek[0] == 0.75
    assert ek[1] == 0.75 * (1.0 - 0.25)
    assert ek[2] == 0.0
    assert ek[3] == 0.0


def test_ou_half_life():
    np.random.seed(42)
    # Synthetic mean-reverting series: x_t = 0.7 * x_{t-1} + noise
    x = [100.0]
    for _ in range(100):
        x.append(100.0 + 0.7 * (x[-1] - 100.0) + np.random.normal(0, 1.0))
    hl = compute_ou_half_life(np.array(x), window=30)
    assert len(hl) == len(x)
    assert np.all(hl > 0)
    assert np.median(hl) < 30.0  # Confirms mean-reverting detection


def test_causal_nadaraya_watson_envelope_non_repainting():
    prices = np.array([100.0, 101.0, 102.5, 101.8, 103.0, 104.2, 103.5, 105.0, 106.0, 105.5])
    
    # Run full series
    full_res = causal_nadaraya_watson_envelope(prices, base_bandwidth=5.0, alpha=2.0)
    
    # Run prefix of series up to bar 5
    prefix_prices = prices[:6]
    prefix_res = causal_nadaraya_watson_envelope(prefix_prices, base_bandwidth=5.0, alpha=2.0)
    
    # Because it is strictly causal, bar 5 in full_res must match bar 5 in prefix_res exactly (zero repainting)
    assert math.isclose(full_res.mean[5], prefix_res.mean[5], rel_tol=1e-7)
    assert math.isclose(full_res.upper[5], prefix_res.upper[5], rel_tol=1e-7)
    assert math.isclose(full_res.lower[5], prefix_res.lower[5], rel_tol=1e-7)
    assert math.isclose(full_res.sigma_local[5], prefix_res.sigma_local[5], rel_tol=1e-7)


def test_kinematic_kalman_filter():
    prices = np.linspace(100.0, 120.0, 50) + np.random.normal(0, 0.2, 50)
    res = kinematic_kalman_filter(
        prices,
        dt=1.0,
        base_sigma_q=1e-3,
        sigma_r=1.0,
        breakout_z=1.5,
        exhaustion_z=0.3,
    )

    assert len(res.latent_price) == len(prices)
    assert len(res.velocity) == len(prices)
    assert len(res.velocity_zscore) == len(prices)
    # Price is in an upward trend so average velocity should be positive
    assert np.mean(res.velocity[10:]) > 0.0
    assert np.all(res.innovation_variance > 0.0)
    assert np.all(res.process_noise_q > 0.0)


def test_compute_anchored_vwap():
    prices = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    volumes = np.array([1000, 2000, 1500, 3000, 2500, 4000])
    
    vwap_res = compute_anchored_vwap(prices, volumes, anchor_indices=[0, 3], anchor_names=["Open", "Event"])
    assert len(vwap_res) == 2
    
    # Open anchor should span full length
    assert len(vwap_res[0].vwap) == len(prices)
    assert not np.isnan(vwap_res[0].vwap[0])
    
    # Event anchor (bar 3) should have NaN before bar 3
    assert np.isnan(vwap_res[1].vwap[0])
    assert np.isnan(vwap_res[1].vwap[2])
    assert not np.isnan(vwap_res[1].vwap[3])
    assert vwap_res[1].vwap[3] == prices[3]
