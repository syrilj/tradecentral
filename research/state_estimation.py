"""State-Space Filtering & Non-Parametric Signal Processing for Market Microstructure.

Implements:
  1. Causal Nadaraya-Watson Kernel Regression Envelopes:
     - Strictly causal (one-sided, historical observations only up to t, non-repainting)
     - Gaussian and Epanechnikov kernel weighting
     - Dynamic bandwidth modulation by Dealer GEX and Ornstein-Uhlenbeck (OU) half-life
     - Kernel-weighted local volatility dispersion bands

  2. Kinematic Kalman Filter State-Space Formulation:
     - 2-State discrete linear Gaussian model: x_k = [p_k, v_k]^T (latent price & velocity)
     - Exact continuous-discrete kinematic covariance Q(dt, sigma_q^2)
     - Adaptive process noise scaling for leptokurtic return distributions & negative gamma jumps
     - Normalized velocity z-scores, momentum exhaustion, and kinematic acceleration triggers

  3. Microstructure-Anchored Volume-Weighted Average Price (Anchored VWAP):
     - Multi-anchor engine: Session Open, Macro Events, and Gamma Flip Crossings
     - Volume-weighted dispersion standard deviation bands
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Causal Nadaraya-Watson Kernel Regression & Envelopes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NadarayaWatsonEnvelopeResult:
    """Non-repainting causal kernel regression line and dynamic volatility envelopes."""
    mean: np.ndarray          # Causal conditional expectation m_h(t)
    upper: np.ndarray         # Upper envelope: m_h(t) + alpha * sigma_local(t)
    lower: np.ndarray         # Lower envelope: m_h(t) - alpha * sigma_local(t)
    sigma_local: np.ndarray   # Kernel-weighted local standard deviation
    bandwidth: np.ndarray     # Dynamic bandwidth h(t) applied at each bar
    ou_half_life: np.ndarray  # Trailing Ornstein-Uhlenbeck half-life estimates


def gaussian_kernel(u: np.ndarray) -> np.ndarray:
    """Gaussian continuous kernel: K(u) = (1 / sqrt(2*pi)) * exp(-0.5 * u^2)."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * np.exp(-0.5 * (u ** 2))


def epanechnikov_kernel(u: np.ndarray) -> np.ndarray:
    """Epanechnikov parabolic kernel: K(u) = 0.75 * (1 - u^2) * 1(|u| <= 1)."""
    valid = np.abs(u) <= 1.0
    res = np.zeros_like(u, dtype=float)
    res[valid] = 0.75 * (1.0 - (u[valid] ** 2))
    return res


def compute_ou_half_life(series: np.ndarray, window: int = 40) -> np.ndarray:
    """Estimate trailing Ornstein-Uhlenbeck mean-reversion half-life via AR(1) OLS on residuals.

    dEpsilon_t = - theta * Epsilon_{t-1} + sigma * dW_t
    Half-life t_{1/2} = ln(2) / theta
    """
    n = len(series)
    half_lives = np.full(n, np.nan, dtype=float)
    if n < window:
        return half_lives

    for i in range(window, n + 1):
        chunk = series[i - window : i]
        # Detrend with simple linear mean
        mu = np.mean(chunk)
        eps = chunk - mu
        x = eps[:-1]
        y = eps[1:]
        # OLS y = beta * x
        denom = np.dot(x, x)
        if denom > 1e-9:
            beta = np.dot(x, y) / denom
            if 0.0 < beta < 1.0:
                theta = -math.log(beta)
                if theta > 1e-4:
                    hl = math.log(2.0) / theta
                    half_lives[i - 1] = max(1.0, min(100.0, hl))
                else:
                    half_lives[i - 1] = 100.0
            elif beta <= 0.0:
                half_lives[i - 1] = 1.0  # Instant mean reversion
            else:
                half_lives[i - 1] = 100.0  # Pure trend / random walk

    # Forward fill valid half lives
    last_val = 20.0
    for i in range(n):
        if np.isnan(half_lives[i]):
            half_lives[i] = last_val
        else:
            last_val = half_lives[i]

    return half_lives


def causal_nadaraya_watson_envelope(
    prices: Sequence[float] | np.ndarray,
    *,
    base_bandwidth: float = 20.0,
    alpha: float = 2.0,
    kernel_fn: str = "gaussian",  # "gaussian" | "epanechnikov"
    gex_series: Sequence[float] | np.ndarray | None = None,
    use_dynamic_bandwidth: bool = True,
    lookback_cutoff: int = 150,
) -> NadarayaWatsonEnvelopeResult:
    """Compute strictly causal, non-repainting Nadaraya-Watson kernel regression envelopes.

    Strictly One-Sided: At bar t, only bars i in [max(0, t - lookback_cutoff), t] are evaluated.
    No future bars are ever referenced.

    Args:
        prices: 1D array of underlying prices.
        base_bandwidth: Baseline bandwidth parameter h0 (in bars).
        alpha: Volatility envelope multiplier (number of local standard deviations).
        kernel_fn: 'gaussian' or 'epanechnikov'.
        gex_series: Optional array of Net GEX values aligned with prices for dynamic modulation.
        use_dynamic_bandwidth: If True, modulates h by OU half-life and GEX regime.
        lookback_cutoff: Maximum historical bars to sum in kernel window for efficiency.

    Returns:
        NadarayaWatsonEnvelopeResult with mean, upper band, lower band, sigma_local, and bandwidth.
    """
    p = np.asarray(prices, dtype=float)
    n = len(p)
    if n == 0:
        empty = np.array([], dtype=float)
        return NadarayaWatsonEnvelopeResult(empty, empty, empty, empty, empty, empty)

    k_func: Callable[[np.ndarray], np.ndarray] = (
        epanechnikov_kernel if kernel_fn.lower() == "epanechnikov" else gaussian_kernel
    )

    ou_hl = compute_ou_half_life(p, window=min(30, max(5, n // 3))) if use_dynamic_bandwidth else np.full(n, 20.0)
    gex_arr = np.asarray(gex_series, dtype=float) if gex_series is not None and len(gex_series) == n else None

    # Compute dynamic bandwidth series h(t)
    h_arr = np.full(n, float(base_bandwidth), dtype=float)
    if use_dynamic_bandwidth:
        for t in range(n):
            h_t = base_bandwidth * (ou_hl[t] / 20.0)
            if gex_arr is not None:
                gex_val = gex_arr[t]
                # Positive GEX compresses h (tight mean-reversion); Negative GEX expands h (trend)
                gex_factor = 1.0 - 0.4 * math.tanh(gex_val / 200.0)
                h_t *= gex_factor
            h_arr[t] = max(3.0, min(80.0, h_t))

    mean_series = np.zeros(n, dtype=float)
    sigma_series = np.zeros(n, dtype=float)

    # Strictly causal calculation
    for t in range(n):
        start_i = max(0, t - lookback_cutoff)
        indices = np.arange(start_i, t + 1)
        sub_prices = p[indices]
        h_t = h_arr[t]

        # Kernel distance: u = (t - i) / h
        u = (t - indices) / h_t
        weights = k_func(u)
        sum_w = np.sum(weights)

        if sum_w > 1e-9:
            m_t = np.sum(weights * sub_prices) / sum_w
        else:
            m_t = p[t]
        mean_series[t] = m_t

        # Kernel-weighted local variance
        if t > 0 and sum_w > 1e-9:
            # Squared residuals against current causal trend
            sq_res = (sub_prices - m_t) ** 2
            var_t = np.sum(weights * sq_res) / sum_w
            sigma_series[t] = math.sqrt(max(1e-8, var_t))
        else:
            sigma_series[t] = 0.01 * p[t]

    upper_series = mean_series + alpha * sigma_series
    lower_series = mean_series - alpha * sigma_series

    return NadarayaWatsonEnvelopeResult(
        mean=mean_series,
        upper=upper_series,
        lower=lower_series,
        sigma_local=sigma_series,
        bandwidth=h_arr,
        ou_half_life=ou_hl,
    )


# ---------------------------------------------------------------------------
# 2-State Kinematic Kalman Filter with Adaptive Noise Scaling
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KinematicKalmanResult:
    """Output from the 2-state Kinematic Kalman Filter."""
    latent_price: np.ndarray       # Latent equilibrium price p_hat_k
    velocity: np.ndarray           # Instantaneous latent velocity v_hat_k = dp/dt
    velocity_zscore: np.ndarray    # Standardized velocity z-score: v_hat / sigma_v
    velocity_noise: np.ndarray     # Rolling standard deviation of velocity sigma_v
    innovations: np.ndarray        # Measurement innovations y_tilde_k = z_k - p_hat_{k|k-1}
    innovation_variance: np.ndarray# Innovation variance S_k
    kalman_gain_p: np.ndarray      # Kalman Gain component for price K_{k,0}
    kalman_gain_v: np.ndarray      # Kalman Gain component for velocity K_{k,1}
    process_noise_q: np.ndarray    # Adaptive process noise spectral density sigma_q^2(t)
    momentum_exhaustion: np.ndarray# Boolean mask: True where |v| <= epsilon and S_k stable
    kinematic_breakout: np.ndarray # Boolean mask: True where |v_z| > breakout_threshold


def kinematic_kalman_filter(
    prices: Sequence[float] | np.ndarray,
    *,
    dt: float = 1.0,
    base_sigma_q: float = 1e-3,
    sigma_r: float = 1.0,
    iv_series: Sequence[float] | np.ndarray | None = None,
    gex_series: Sequence[float] | np.ndarray | None = None,
    breakout_z: float = 2.0,
    exhaustion_z: float = 0.3,
    noise_window: int = 20,
) -> KinematicKalmanResult:
    """Run 2-State Kinematic Kalman Filter with adaptive process noise scaling.

    State Vector: x_k = [p_k, v_k]^T
    Transition Matrix: F = [[1, dt], [0, 1]]
    Observation Matrix: H = [[1, 0]]
    Process Noise Covariance Q = sigma_q^2 * [[dt^3 / 3, dt^2 / 2], [dt^2 / 2, dt]]
    Measurement Noise Variance R = sigma_r^2

    Adaptive Leptokurtic Scaling:
      sigma_q^2(t) = base_sigma_q^2 * (1 + 2.0 * IV(t) + 50.0 / (|GEX(t)| + 10.0))
      During negative gamma regimes or IV spikes, Q increases, raising Kalman Gain K_k
      so the filter rapidly tracks market discontinuities with zero phase lag.

    Args:
        prices: 1D array of observed prices.
        dt: Time delta between bars (default 1.0).
        base_sigma_q: Base process noise spectral density.
        sigma_r: Measurement noise standard deviation.
        iv_series: Optional aligned implied volatility series.
        gex_series: Optional aligned Net GEX series.
        breakout_z: Z-score threshold for kinematic acceleration / breakout.
        exhaustion_z: Z-score threshold for momentum exhaustion / mean reversion.
        noise_window: Rolling window to compute velocity standard deviation.

    Returns:
        KinematicKalmanResult with complete state estimates and indicators.
    """
    z = np.asarray(prices, dtype=float)
    n = len(z)
    if n == 0:
        empty = np.array([], dtype=float)
        empty_b = np.array([], dtype=bool)
        return KinematicKalmanResult(
            empty, empty, empty, empty, empty, empty, empty, empty, empty, empty_b, empty_b
        )

    # Preallocate output arrays
    p_hat = np.zeros(n, dtype=float)
    v_hat = np.zeros(n, dtype=float)
    innovations = np.zeros(n, dtype=float)
    inv_var = np.zeros(n, dtype=float)
    kg_p = np.zeros(n, dtype=float)
    kg_v = np.zeros(n, dtype=float)
    q_scale_series = np.zeros(n, dtype=float)

    # Matrices
    F = np.array([[1.0, dt], [0.0, 1.0]], dtype=float)
    H = np.array([[1.0, 0.0]], dtype=float)
    R = float(sigma_r ** 2)

    # Initial state estimate
    x = np.array([z[0], 0.0], dtype=float)
    P = np.array([[R, 0.0], [0.0, 1.0]], dtype=float)

    iv_arr = np.asarray(iv_series, dtype=float) if iv_series is not None and len(iv_series) == n else None
    gex_arr = np.asarray(gex_series, dtype=float) if gex_series is not None and len(gex_series) == n else None

    # Filter Loop
    for k in range(n):
        # 1. Compute Adaptive Q
        iv_val = iv_arr[k] if iv_arr is not None and not np.isnan(iv_arr[k]) else 0.20
        gex_val = gex_arr[k] if gex_arr is not None and not np.isnan(gex_arr[k]) else 0.0

        # Adaptive factor: increase Q in negative gamma (GEX < 0) and high IV
        gex_penalty = 50.0 / (abs(gex_val) + 5.0) if gex_val < 0 else 10.0 / (abs(gex_val) + 10.0)
        q_factor = 1.0 + (2.0 * iv_val) + gex_penalty
        cur_sigma_q_sq = (base_sigma_q ** 2) * q_factor
        q_scale_series[k] = cur_sigma_q_sq

        # Discrete Process Noise Matrix Q
        dt2 = dt * dt
        dt3 = dt2 * dt
        Q = cur_sigma_q_sq * np.array([[dt3 / 3.0, dt2 / 2.0], [dt2 / 2.0, dt]], dtype=float)

        if k == 0:
            p_hat[k] = x[0]
            v_hat[k] = x[1]
            innovations[k] = 0.0
            inv_var[k] = R
            kg_p[k] = 0.0
            kg_v[k] = 0.0
            continue

        # 2. Time Update (Predict)
        x_pred = F @ x
        P_pred = F @ P @ F.T + Q

        # 3. Measurement Update (Correct)
        z_k = z[k]
        y_tilde = z_k - (H @ x_pred)[0]
        S = (H @ P_pred @ H.T)[0, 0] + R
        S = max(1e-9, S)

        # Kalman Gain K = P_pred * H^T * S^-1
        K = (P_pred @ H.T) / S  # Shape (2, 1)

        x = x_pred + (K.flatten() * y_tilde)
        I_KH = np.eye(2) - K @ H
        P = I_KH @ P_pred @ I_KH.T + K * R @ K.T  # Joseph form for numerical stability

        p_hat[k] = x[0]
        v_hat[k] = x[1]
        innovations[k] = y_tilde
        inv_var[k] = S
        kg_p[k] = K[0, 0]
        kg_v[k] = K[1, 0]

    # Compute velocity standard deviation and z-score
    v_series = pd.Series(v_hat)
    rolling_sd = v_series.rolling(window=noise_window, min_periods=3).std(ddof=1).to_numpy()
    rolling_sd = np.where(np.isnan(rolling_sd) | (rolling_sd < 1e-6), 1e-3, rolling_sd)

    v_z = v_hat / rolling_sd

    # Momentum state detection
    exhaustion = (np.abs(v_z) <= exhaustion_z)
    breakout = (np.abs(v_z) >= breakout_z)

    return KinematicKalmanResult(
        latent_price=p_hat,
        velocity=v_hat,
        velocity_zscore=v_z,
        velocity_noise=rolling_sd,
        innovations=innovations,
        innovation_variance=inv_var,
        kalman_gain_p=kg_p,
        kalman_gain_v=kg_v,
        process_noise_q=q_scale_series,
        momentum_exhaustion=exhaustion,
        kinematic_breakout=breakout,
    )


# ---------------------------------------------------------------------------
# Microstructure-Anchored VWAP
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnchoredVWAPResult:
    """Series for a single event-anchored Volume-Weighted Average Price."""
    anchor_name: str
    anchor_index: int
    vwap: np.ndarray
    upper_1sd: np.ndarray
    lower_1sd: np.ndarray
    upper_2sd: np.ndarray
    lower_2sd: np.ndarray


def compute_anchored_vwap(
    prices: Sequence[float] | np.ndarray,
    volumes: Sequence[float] | np.ndarray,
    anchor_indices: Sequence[int] | np.ndarray,
    anchor_names: Sequence[str] | None = None,
) -> list[AnchoredVWAPResult]:
    """Compute multiple Microstructure-Anchored VWAP curves.

    Anchors can represent:
      - Session Open (09:30 EST)
      - Macro Economic Releases (08:30 CPI / 10:00 ISM)
      - Gamma Flip Crossings (where spot price crossed S*)

    Args:
        prices: 1D array of representative prices (typically (H+L+C)/3 or Close).
        volumes: 1D array of bar volumes.
        anchor_indices: List of integer bar indices where an anchor reset occurs.
        anchor_names: Optional descriptive names for each anchor.

    Returns:
        List of AnchoredVWAPResult objects, one per specified anchor.
    """
    p = np.asarray(prices, dtype=float)
    v = np.asarray(volumes, dtype=float)
    n = len(p)
    if n == 0 or len(v) != n:
        return []

    results: list[AnchoredVWAPResult] = []
    anchors = sorted(set(int(a) for a in anchor_indices if 0 <= a < n))
    if not anchors:
        anchors = [0]

    for idx, a_idx in enumerate(anchors):
        name = (
            anchor_names[idx]
            if anchor_names and idx < len(anchor_names)
            else f"Anchor_{idx + 1}_Bar_{a_idx}"
        )

        vwap_arr = np.full(n, np.nan, dtype=float)
        u1_arr = np.full(n, np.nan, dtype=float)
        l1_arr = np.full(n, np.nan, dtype=float)
        u2_arr = np.full(n, np.nan, dtype=float)
        l2_arr = np.full(n, np.nan, dtype=float)

        cum_pv = 0.0
        cum_v = 0.0
        cum_pv2 = 0.0

        for t in range(a_idx, n):
            vol = max(1e-4, v[t])
            px = p[t]
            cum_pv += px * vol
            cum_v += vol
            cum_pv2 += (px ** 2) * vol

            vwap_t = cum_pv / cum_v
            vwap_arr[t] = vwap_t

            # Weighted variance: E[X^2] - (E[X])^2
            mean_sq = cum_pv2 / cum_v
            var_t = max(0.0, mean_sq - (vwap_t ** 2))
            sd_t = math.sqrt(var_t)

            u1_arr[t] = vwap_t + 1.0 * sd_t
            l1_arr[t] = vwap_t - 1.0 * sd_t
            u2_arr[t] = vwap_t + 2.0 * sd_t
            l2_arr[t] = vwap_t - 2.0 * sd_t

        results.append(
            AnchoredVWAPResult(
                anchor_name=name,
                anchor_index=a_idx,
                vwap=vwap_arr,
                upper_1sd=u1_arr,
                lower_1sd=l1_arr,
                upper_2sd=u2_arr,
                lower_2sd=l2_arr,
            )
        )

    return results
