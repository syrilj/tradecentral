"""Layer 1 Raw Point-in-Time Feature Engine for Market Regimes.

Theoretical Foundations & Numerical Standards:
- Strictly causal (t <= T): zero lookahead, zero forward reference.
- Clean warm-up: NaNs during warm-up periods, never fake zeros or ungrounded defaults.
- Numerical stability: West's incremental variance, MAD scaling, safe square roots.
- Complete Greek derivatives: Delta, Gamma, Vega, Theta, Rho, Vanna, Charm, Speed, Zomma.
- Pure functions: deterministic, no side effects, no external I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_SQRT_2 = math.sqrt(2.0)
_DEFAULT_RATE = 0.045
_MIN_IV = 0.005
_MAX_IV = 5.0
_MIN_TIME_YEARS = 1.0 / (365.25 * 24.0 * 60.0)  # ~1 minute
_MAD_NORMAL_SCALE = 1.482602218505602


@dataclass(frozen=True)
class RegimeFeatureConfig:
    """Configuration parameters and window sizes for Layer 1 features."""

    volatility_window: int = 20
    annualization_factor: float = 252.0
    atr_window: int = 14
    vwap_slope_bars: int = 3
    baseline_sessions: int = 20
    min_slot_samples: int = 10
    fallback_bars: int = 20
    min_fallback_samples: int = 5
    flow_mad_window: int = 20
    risk_free_rate: float = _DEFAULT_RATE


@dataclass(frozen=True)
class OptionGreeks:
    """Complete 1st, 2nd, and 3rd order Black-Scholes Greeks."""

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    vanna: float
    charm: float
    speed: float
    zomma: float
    d1: float
    d2: float


# ---------------------------------------------------------------------------
# Core Time Series & Mathematical Primitives
# ---------------------------------------------------------------------------


def compute_log_returns(close: pd.Series | np.ndarray | Sequence[float]) -> pd.Series:
    """Compute strictly causal log returns r_t = ln(C_t / C_{t-1}).

    Returns NaN for t=0 or when prices are invalid / non-positive.
    """
    if isinstance(close, pd.Series):
        c = pd.to_numeric(close, errors="coerce").astype(float)
        idx = close.index
    else:
        arr = np.asarray(close, dtype=float)
        c = pd.Series(arr)
        idx = c.index

    valid = c > 0
    safe_c = c.where(valid, np.nan)
    log_c = np.log(safe_c)
    r = log_c.diff()
    r.index = idx
    return r


def compute_realized_volatilities(
    bars: pd.DataFrame,
    window: int = 20,
    annualization: float = 252.0,
) -> pd.DataFrame:
    """Compute rolling Close-to-Close, Parkinson, and Garman-Klass realized volatilities.

    Returns DataFrame with columns:
      - 'vol_close_to_close'
      - 'vol_parkinson'
      - 'vol_garman_klass'
    """
    if window < 2:
        raise ValueError("window must be >= 2")

    for col in ("open", "high", "low", "close"):
        if col not in bars.columns:
            raise KeyError(f"bars must contain '{col}' column")

    o = pd.to_numeric(bars["open"], errors="coerce").astype(float)
    h = pd.to_numeric(bars["high"], errors="coerce").astype(float)
    l = pd.to_numeric(bars["low"], errors="coerce").astype(float)
    c = pd.to_numeric(bars["close"], errors="coerce").astype(float)

    # 1. Close-to-Close (causal log returns)
    valid_c = (c > 0) & (c.shift(1) > 0)
    log_ret = pd.Series(np.nan, index=bars.index)
    log_ret[valid_c] = np.log(c[valid_c] / c.shift(1)[valid_c])
    var_cc = log_ret.rolling(window, min_periods=window).var(ddof=1)
    vol_cc = np.sqrt(np.maximum(0.0, var_cc * annualization))

    # 2. Parkinson (High-Low range estimator)
    # s^2_Park = (1 / (4 * ln 2)) * ln(H / L)^2
    valid_hl = (h > 0) & (l > 0) & (h >= l)
    log_hl = pd.Series(np.nan, index=bars.index)
    log_hl[valid_hl] = np.log(h[valid_hl] / l[valid_hl])
    var_park_bar = (log_hl**2) / (4.0 * math.log(2.0))
    var_park = var_park_bar.rolling(window, min_periods=window).mean()
    vol_park = np.sqrt(np.maximum(0.0, var_park * annualization))

    # 3. Garman-Klass (OHLC jump and range estimator)
    # s^2_GK = 0.5 * ln(H/L)^2 - (2*ln 2 - 1) * ln(C/O)^2
    valid_ohlc = valid_hl & (o > 0) & (c > 0)
    log_co = pd.Series(np.nan, index=bars.index)
    log_co[valid_ohlc] = np.log(c[valid_ohlc] / o[valid_ohlc])
    gk_bar = pd.Series(np.nan, index=bars.index)
    gk_bar[valid_ohlc] = 0.5 * (log_hl[valid_ohlc] ** 2) - (2.0 * math.log(2.0) - 1.0) * (
        log_co[valid_ohlc] ** 2
    )
    var_gk = gk_bar.rolling(window, min_periods=window).mean()
    vol_gk = np.sqrt(np.maximum(0.0, var_gk * annualization))

    return pd.DataFrame(
        {
            "vol_close_to_close": vol_cc,
            "vol_parkinson": vol_park,
            "vol_garman_klass": vol_gk,
        },
        index=bars.index,
    )


def compute_true_range(bars: pd.DataFrame) -> pd.Series:
    """Compute True Range TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)."""
    for col in ("high", "low", "close"):
        if col not in bars.columns:
            raise KeyError(f"bars must contain '{col}' column")

    h = pd.to_numeric(bars["high"], errors="coerce").astype(float)
    l = pd.to_numeric(bars["low"], errors="coerce").astype(float)
    c = pd.to_numeric(bars["close"], errors="coerce").astype(float)
    prev_c = c.shift(1)

    hl = h - l
    hc = (h - prev_c).abs()
    lc = (l - prev_c).abs()

    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    if len(tr) > 0:
        tr.iloc[0] = hl.iloc[0]
    return tr


def compute_wilders_atr(bars: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Compute Wilder's Average True Range using exact recursive formulation.

    Returns DataFrame with columns:
      - 'true_range'
      - 'atr'
      - 'natr' (Normalized ATR = ATR / Close)
    """
    if window < 1:
        raise ValueError("window must be >= 1")

    tr = compute_true_range(bars)
    c = pd.to_numeric(bars["close"], errors="coerce").astype(float)

    n = len(tr)
    atr = np.full(n, np.nan, dtype=float)
    tr_vals = tr.to_numpy(dtype=float)

    if n >= window:
        # Initial window SMA
        first_atr = float(np.nanmean(tr_vals[:window]))
        atr[window - 1] = first_atr
        curr_atr = first_atr
        for i in range(window, n):
            val = tr_vals[i]
            if np.isfinite(val):
                curr_atr = (curr_atr * (window - 1) + val) / window
                atr[i] = curr_atr
            else:
                atr[i] = curr_atr

    atr_s = pd.Series(atr, index=bars.index)
    natr = (atr_s / c).where(c > 0, np.nan)
    return pd.DataFrame({"true_range": tr, "atr": atr_s, "natr": natr}, index=bars.index)


# ---------------------------------------------------------------------------
# Session Anchoring & West's Incremental VWAP
# ---------------------------------------------------------------------------


def compute_session_vwap_west(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute session-reset VWAP and dispersion bands using West's incremental algorithm.

    Guarantees zero catastrophic cancellation and handles session boundaries.

    Returns DataFrame with columns:
      - 'vwap', 'vwap_sd', 'vwap_z', 'vwap_dist_bp',
      - 'upper_band_1', 'lower_band_1', 'upper_band_2', 'lower_band_2',
      - 'upper_band_3', 'lower_band_3'
    """
    for col in ("high", "low", "close", "volume"):
        if col not in bars.columns:
            raise KeyError(f"bars must contain '{col}' column")

    h = pd.to_numeric(bars["high"], errors="coerce").to_numpy(dtype=float)
    l = pd.to_numeric(bars["low"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(bars["close"], errors="coerce").to_numpy(dtype=float)
    v = pd.to_numeric(bars["volume"], errors="coerce").to_numpy(dtype=float)

    if isinstance(bars.index, pd.DatetimeIndex):
        sess = bars.index.normalize().to_numpy()
    else:
        sess = np.zeros(len(bars), dtype=int)

    n = len(bars)
    vwap = np.full(n, np.nan, dtype=float)
    sd = np.full(n, np.nan, dtype=float)

    tp = (h + l + c) / 3.0

    w_sum = 0.0
    mean = 0.0
    m2 = 0.0
    prev_sess = None

    for i in range(n):
        if prev_sess is None or sess[i] != prev_sess:
            w_sum, mean, m2 = 0.0, 0.0, 0.0
            prev_sess = sess[i]

        w = v[i]
        x = tp[i]
        if np.isfinite(w) and w > 0.0 and np.isfinite(x):
            w_sum += w
            delta = x - mean
            mean += (w / w_sum) * delta
            m2 += w * delta * (x - mean)

        if w_sum > 0.0:
            vwap[i] = mean
            var = max(0.0, m2 / w_sum)
            sd[i] = math.sqrt(var)

    vwap_s = pd.Series(vwap, index=bars.index)
    sd_s = pd.Series(sd, index=bars.index)
    close_s = pd.Series(c, index=bars.index)

    z = (close_s - vwap_s) / sd_s.replace(0.0, np.nan)
    dist_bp = (close_s / vwap_s - 1.0) * 1e4

    return pd.DataFrame(
        {
            "vwap": vwap_s,
            "vwap_sd": sd_s,
            "vwap_z": z,
            "vwap_dist_bp": dist_bp,
            "upper_band_1": vwap_s + sd_s,
            "lower_band_1": vwap_s - sd_s,
            "upper_band_2": vwap_s + 2.0 * sd_s,
            "lower_band_2": vwap_s - 2.0 * sd_s,
            "upper_band_3": vwap_s + 3.0 * sd_s,
            "lower_band_3": vwap_s - 3.0 * sd_s,
        },
        index=bars.index,
    )


# ---------------------------------------------------------------------------
# Slot-Relative Volume Baseline
# ---------------------------------------------------------------------------


def compute_slot_relative_volume(
    bars: pd.DataFrame,
    baseline_sessions: int = 20,
    min_slot_samples: int = 10,
    fallback_bars: int = 20,
    min_fallback_samples: int = 5,
) -> pd.DataFrame:
    """Compute slot-relative volume with strict shift(1) exclusion of current bar.

    Columns:
      - 'slot'
      - 'rvol_slot'
      - 'log_rvol_slot'
      - 'cum_rvol_session'
      - 'rvol_baseline'
      - 'rvol_baseline_kind'
    """
    if "volume" not in bars.columns:
        raise KeyError("bars must contain 'volume' column")

    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars index must be a DatetimeIndex for slot-relative volume")

    sess = pd.Series(bars.index.normalize(), index=bars.index)
    slots = sess.groupby(sess).cumcount()
    vol = pd.to_numeric(bars["volume"], errors="coerce").astype(float)

    # shift(1) grouped by slot steps back 1 session within that same slot
    slot_med = vol.groupby(slots).transform(
        lambda s: s.shift(1).rolling(baseline_sessions, min_periods=min_slot_samples).median()
    )
    fallback = vol.shift(1).rolling(fallback_bars, min_periods=min_fallback_samples).median()

    baseline = slot_med.where(slot_med.notna(), fallback)
    kind = pd.Series("unmeasured", index=bars.index, dtype="object")
    kind[fallback.notna()] = "trailing_median"
    kind[slot_med.notna()] = "slot_median"

    rvol = vol / baseline.replace(0.0, np.nan)
    log_rvol = np.log(rvol.where(rvol > 0, np.nan))

    cum_vol = vol.groupby(sess).cumsum()
    cum_base = cum_vol.groupby(slots).transform(
        lambda s: s.shift(1).rolling(baseline_sessions, min_periods=min_slot_samples).median()
    )
    cum_rvol = cum_vol / cum_base.replace(0.0, np.nan)

    return pd.DataFrame(
        {
            "slot": slots,
            "rvol_slot": rvol,
            "log_rvol_slot": log_rvol,
            "cum_rvol_session": cum_rvol,
            "rvol_baseline": baseline,
            "rvol_baseline_kind": kind,
        },
        index=bars.index,
    )


# ---------------------------------------------------------------------------
# Black-Scholes Greeks (1st, 2nd, 3rd Order) & Strike Exposure Engine
# ---------------------------------------------------------------------------


def calculate_option_greeks(
    *,
    spot: float,
    strike: float,
    years: float,
    iv: float,
    right: str,
    rate: float = _DEFAULT_RATE,
) -> Optional[OptionGreeks]:
    """Calculate 1st, 2nd, and 3rd order Black-Scholes Greeks."""
    if spot <= 0 or strike <= 0 or years <= 0 or not (_MIN_IV <= iv <= _MAX_IV):
        return None

    tau = max(years, _MIN_TIME_YEARS)
    root_t = math.sqrt(tau)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * tau) / (iv * root_t)
    d2 = d1 - iv * root_t

    phi_d1 = math.exp(-0.5 * d1 * d1) / _SQRT_2PI
    Phi_d1 = 0.5 * (1.0 + math.erf(d1 / _SQRT_2))
    Phi_d2 = 0.5 * (1.0 + math.erf(d2 / _SQRT_2))
    Phi_neg_d2 = 0.5 * (1.0 + math.erf(-d2 / _SQRT_2))

    is_call = right.strip().lower() in {"c", "call", "calls"}

    # 1. Delta
    delta = Phi_d1 if is_call else (Phi_d1 - 1.0)
    # 2. Gamma (identical for Call and Put)
    gamma = phi_d1 / (spot * iv * root_t)
    # 3. Vega (per 1.00 vol move)
    vega = spot * root_t * phi_d1
    # 4. Theta (per calendar day: dPrice / dt where dt = 1 / 365.25)
    df = math.exp(-rate * tau)
    if is_call:
        theta_ann = -(spot * phi_d1 * iv) / (2.0 * root_t) - rate * strike * df * Phi_d2
    else:
        theta_ann = -(spot * phi_d1 * iv) / (2.0 * root_t) + rate * strike * df * Phi_neg_d2
    theta = theta_ann / 365.25

    # 5. Rho (per 1% interest rate move)
    rho = (
        (strike * tau * df * Phi_d2 * 0.01)
        if is_call
        else (-strike * tau * df * Phi_neg_d2 * 0.01)
    )

    # 6. Vanna: dDelta / dSigma = dVega / dS
    vanna = -phi_d1 * d2 / iv

    # 7. Charm: dDelta / dt (per calendar day)
    charm_ann = phi_d1 * ((rate * d2) / (iv * root_t) - d2 / (2.0 * tau))
    charm = charm_ann / 365.25

    # 8. Speed: dGamma / dS
    speed = -(gamma / spot) * (d1 / (iv * root_t) + 1.0)

    # 9. Zomma: dGamma / dSigma
    zomma = gamma * ((d1 * d2 - 1.0) / iv)

    return OptionGreeks(
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        rho=rho,
        vanna=vanna,
        charm=charm,
        speed=speed,
        zomma=zomma,
        d1=d1,
        d2=d2,
    )


def compute_dollar_gex_profile(
    chain: pd.DataFrame,
    spot: float,
    rate: float = _DEFAULT_RATE,
    grid_points: int = 100,
    grid_range: float = 0.15,
) -> Dict[str, Any]:
    """Compute strike-level dollar GEX, VEX, CHEX, root flip level, and walls."""
    if chain.empty or spot <= 0:
        return {
            "spot": spot,
            "net_gex_usd": 0.0,
            "call_gex_usd": 0.0,
            "put_gex_usd": 0.0,
            "net_vex_usd": 0.0,
            "net_chex_usd": 0.0,
            "gamma_flip": None,
            "call_wall": None,
            "put_wall": None,
            "gex_profile": [],
        }

    # Extract required fields supporting multiple column name aliases
    strikes = pd.to_numeric(
        chain.get("strike", chain.get("strike_price", chain.get("k", 0.0))),
        errors="coerce",
    ).to_numpy(dtype=float)

    type_col = chain.get("option_type", chain.get("right", chain.get("type", "CALL")))
    types = type_col.astype(str).str.upper().to_numpy()

    ois = pd.to_numeric(
        chain.get("open_interest", chain.get("oi", 0.0)), errors="coerce"
    ).to_numpy(dtype=float)

    ivs = pd.to_numeric(
        chain.get("implied_volatility", chain.get("iv", 0.25)), errors="coerce"
    ).to_numpy(dtype=float)

    dtes = pd.to_numeric(
        chain.get("days_to_expiration", chain.get("dte", 30.0)), errors="coerce"
    ).to_numpy(dtype=float)

    call_gex = 0.0
    put_gex = 0.0
    call_vex = 0.0
    put_vex = 0.0
    call_chex = 0.0
    put_chex = 0.0

    strike_gex_map: Dict[float, float] = {}
    strike_call_map: Dict[float, float] = {}
    strike_put_map: Dict[float, float] = {}

    for k, opt_type, oi, iv, dte in zip(strikes, types, ois, ivs, dtes):
        if oi <= 0 or not np.isfinite(oi) or k <= 0:
            continue
        tau = max(dte if np.isfinite(dte) else 30.0, 0.5) / 365.25
        iv_val = iv if (np.isfinite(iv) and iv >= _MIN_IV) else 0.25

        g = calculate_option_greeks(
            spot=spot,
            strike=k,
            years=tau,
            iv=iv_val,
            right=opt_type,
            rate=rate,
        )
        if g is None:
            continue

        dgex = oi * 100.0 * g.gamma * (spot**2) * 0.01
        dvex = oi * 100.0 * g.vanna * spot * 0.01
        dchex = oi * 100.0 * g.charm * spot

        is_call = "C" in opt_type
        if is_call:
            call_gex += dgex
            call_vex += dvex
            call_chex += dchex
            strike_call_map[k] = strike_call_map.get(k, 0.0) + dgex
        else:
            put_gex += dgex
            put_vex += dvex
            put_chex += dchex
            strike_put_map[k] = strike_put_map.get(k, 0.0) + dgex

        signed_dgex = dgex if is_call else -dgex
        strike_gex_map[k] = strike_gex_map.get(k, 0.0) + signed_dgex

    # Directional Walls strictly on proper side of spot
    call_candidates = {k: v for k, v in strike_call_map.items() if k > spot and v > 0}
    call_wall = max(call_candidates, key=call_candidates.get) if call_candidates else None

    put_candidates = {k: v for k, v in strike_put_map.items() if k < spot and v > 0}
    put_wall = max(put_candidates, key=put_candidates.get) if put_candidates else None

    # Curve generation across grid and multi-root nearest flip finding
    s_min = spot * (1.0 - grid_range)
    s_max = spot * (1.0 + grid_range)
    s_grid = np.linspace(s_min, s_max, grid_points)

    profile = []
    root_crossings = []
    prev_s = None
    prev_net = None

    for s_eval in s_grid:
        net_eval = 0.0
        for k, opt_type, oi, iv, dte in zip(strikes, types, ois, ivs, dtes):
            if oi <= 0 or not np.isfinite(oi) or k <= 0:
                continue
            tau = max(dte if np.isfinite(dte) else 30.0, 0.5) / 365.25
            iv_val = iv if (np.isfinite(iv) and iv >= _MIN_IV) else 0.25

            g = calculate_option_greeks(
                spot=float(s_eval),
                strike=k,
                years=tau,
                iv=iv_val,
                right=opt_type,
                rate=rate,
            )
            if g is None:
                continue
            dg = oi * 100.0 * g.gamma * (float(s_eval) ** 2) * 0.01
            net_eval += dg if "C" in opt_type else -dg

        profile.append({"spot": round(float(s_eval), 2), "net_gex_usd": float(net_eval)})

        if prev_net is not None:
            if prev_net == 0.0:
                root_crossings.append(prev_s)
            elif (prev_net < 0 and net_eval > 0) or (prev_net > 0 and net_eval < 0):
                denom = abs(prev_net) + abs(net_eval)
                if denom > 1e-9:
                    root_s = prev_s + (abs(prev_net) / denom) * (s_eval - prev_s)
                    root_crossings.append(root_s)
        prev_s = float(s_eval)
        prev_net = net_eval

    # Gamma flip: root nearest to current spot
    gamma_flip = None
    if root_crossings:
        gamma_flip = min(root_crossings, key=lambda r: abs(r - spot))

    return {
        "spot": spot,
        "net_gex_usd": call_gex - put_gex,
        "call_gex_usd": call_gex,
        "put_gex_usd": put_gex,
        "net_vex_usd": call_vex - put_vex,
        "net_chex_usd": call_chex - put_chex,
        "gamma_flip": round(float(gamma_flip), 2) if gamma_flip is not None else None,
        "call_wall": round(float(call_wall), 2) if call_wall is not None else None,
        "put_wall": round(float(put_wall), 2) if put_wall is not None else None,
        "gex_profile": profile,
    }


# ---------------------------------------------------------------------------
# Signed Volume Flow Proxy & Robust Median/MAD Z-Scores
# ---------------------------------------------------------------------------


def compute_signed_flow_proxy(bars: pd.DataFrame, mad_window: int = 20) -> pd.DataFrame:
    """Compute Close Location Value (CLV), signed flow proxy, and robust MAD z-score."""
    for col in ("high", "low", "close", "volume"):
        if col not in bars.columns:
            raise KeyError(f"bars must contain '{col}' column")

    h = pd.to_numeric(bars["high"], errors="coerce").astype(float)
    l = pd.to_numeric(bars["low"], errors="coerce").astype(float)
    c = pd.to_numeric(bars["close"], errors="coerce").astype(float)
    v = pd.to_numeric(bars["volume"], errors="coerce").astype(float)

    rng = h - l
    valid_rng = rng > 0
    clv = pd.Series(0.0, index=bars.index)
    clv[valid_rng] = (2.0 * c[valid_rng] - h[valid_rng] - l[valid_rng]) / rng[valid_rng]

    signed_flow = clv * v

    if isinstance(bars.index, pd.DatetimeIndex):
        sess = pd.Series(bars.index.normalize(), index=bars.index)
        cum_flow = signed_flow.groupby(sess).cumsum()
    else:
        cum_flow = signed_flow.cumsum()

    # Robust rolling Median and MAD
    med = signed_flow.rolling(mad_window, min_periods=mad_window).median()
    dev = (signed_flow - med).abs()
    mad = dev.rolling(mad_window, min_periods=mad_window).median()

    denom = _MAD_NORMAL_SCALE * mad
    flow_z = (signed_flow - med) / denom.replace(0.0, np.nan)
    flow_z_clipped = flow_z.clip(lower=-5.0, upper=5.0)

    return pd.DataFrame(
        {
            "clv": clv,
            "signed_flow_proxy": signed_flow,
            "cum_signed_flow_session": cum_flow,
            "flow_mad_z": flow_z_clipped,
        },
        index=bars.index,
    )


# ---------------------------------------------------------------------------
# Master Layer 1 Raw Point-in-Time Feature Matrix Builder
# ---------------------------------------------------------------------------


def build_layer1_regime_features(
    bars: pd.DataFrame,
    option_chain: Optional[pd.DataFrame] = None,
    config: Optional[RegimeFeatureConfig] = None,
) -> pd.DataFrame:
    """Build unified strictly causal Layer 1 Raw Point-in-Time Feature Matrix."""
    cfg = config or RegimeFeatureConfig()

    # 1. Volatilities & Returns
    log_ret = compute_log_returns(bars["close"])
    vols = compute_realized_volatilities(
        bars, window=cfg.volatility_window, annualization=cfg.annualization_factor
    )
    atr_df = compute_wilders_atr(bars, window=cfg.atr_window)

    # 2. VWAP & Dispersion
    vwap_df = compute_session_vwap_west(bars)

    # 3. Relative Volume (if DatetimeIndex available)
    if isinstance(bars.index, pd.DatetimeIndex):
        rvol_df = compute_slot_relative_volume(
            bars,
            baseline_sessions=cfg.baseline_sessions,
            min_slot_samples=cfg.min_slot_samples,
            fallback_bars=cfg.fallback_bars,
            min_fallback_samples=cfg.min_fallback_samples,
        )
    else:
        rvol_df = pd.DataFrame(
            {
                "slot": 0,
                "rvol_slot": np.nan,
                "log_rvol_slot": np.nan,
                "cum_rvol_session": np.nan,
                "rvol_baseline": np.nan,
                "rvol_baseline_kind": "unmeasured",
            },
            index=bars.index,
        )

    # 4. Signed Flow Proxy
    flow_df = compute_signed_flow_proxy(bars, mad_window=cfg.flow_mad_window)

    # 5. Assemble master frame
    features = pd.concat(
        [
            pd.DataFrame({"log_return": log_ret}, index=bars.index),
            vols,
            atr_df,
            vwap_df,
            rvol_df,
            flow_df,
        ],
        axis=1,
    )

    return features


def assert_causal_leak_resistant(
    bars: pd.DataFrame,
    config: Optional[RegimeFeatureConfig] = None,
    cut: float = 0.7,
) -> None:
    """Executable point-in-time leakage verification: perturb tail, verify head is unchanged."""
    cfg = config or RegimeFeatureConfig()
    k = int(len(bars) * cut)
    if k < 2 or k >= len(bars):
        raise ValueError("cut must leave bars on both sides")

    baseline = build_layer1_regime_features(bars, config=cfg)

    # Perturb future data wildly
    tampered = bars.copy()
    for col in ("open", "high", "low", "close"):
        if col in tampered.columns:
            tampered.iloc[k:, tampered.columns.get_loc(col)] *= 2.5
    if "volume" in tampered.columns:
        tampered.iloc[k:, tampered.columns.get_loc("volume")] *= 10.0

    after = build_layer1_regime_features(tampered, config=cfg)

    base_head = baseline.iloc[:k]
    after_head = after.iloc[:k]

    for col in baseline.columns:
        if col == "rvol_baseline_kind":
            assert (
                base_head[col].to_numpy() == after_head[col].to_numpy()
            ).all(), f"Causality leak detected in string column '{col}'"
            continue
        b_vals = base_head[col].to_numpy(dtype=float)
        a_vals = after_head[col].to_numpy(dtype=float)
        both_nan = np.isnan(b_vals) & np.isnan(a_vals)
        matching = np.isclose(b_vals, a_vals, rtol=1e-12, atol=1e-12, equal_nan=True) | both_nan
        assert matching.all(), f"Causality leak detected in column '{col}' at indices {np.where(~matching)[0]}"
