"""Reversal-timing features: the operator's chart stack, computed causally.

Three TradingView studies the operator reads for bottoms and tops, ported bar
for bar so the study measures what is actually on their chart:

* **Standardized MACD Heikin-Ashi** (EliCobra). MACD divided by an EMA of bar
  range, x100, then Heikin-Ashi-smoothed. ``OS`` fires when the HA body flips
  up with its low below -100; ``OB`` mirrors it above +100.
* **Dynamic Swing Anchored VWAP** (Zeiierman). The swing direction flips when
  the most recent ``prd``-bar extreme changes side; on the flip an EWMA VWAP
  is re-anchored at the opposite swing extreme and rolled forward. Only the
  default (non-adaptive) tracking speed is ported.
* **Volume profile** over the prior N sessions: POC, VAH, VAL. The triangular
  close-weighted volume split is the one ``research.volume_profile`` uses.

Every column at row ``t`` depends on bars ``<= t`` only. The swing VWAP's
re-anchoring *redraws* history on the chart, but the value it shows at the
current bar is computable at that bar, and that is the value stored here.
Profiles for a session use earlier sessions only, and higher-timeframe context
is shifted one completed HTF bar.

Pure computation, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from edge.research.volume_profile import value_area

OHLCV = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# primitives


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def wilder_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


# ---------------------------------------------------------------------------
# Standardized MACD Heikin-Ashi


@dataclass(frozen=True)
class StMacdParams:
    fast: int = 12
    slow: int = 26
    signal: int = 9
    threshold: float = 100.0


def st_macd_ha(df: pd.DataFrame, params: StMacdParams = StMacdParams()) -> pd.DataFrame:
    """Port of ``stmc`` + ``ha`` from the Pine source, close as source."""
    close = df["close"]
    rng = df["high"] - df["low"]
    denom = ema(rng, params.slow).replace(0.0, np.nan)
    x = (ema(close, params.fast) - ema(close, params.slow)) / denom * 100.0
    x_prev = x.shift(1)

    b_h = np.maximum(x, x_prev)
    b_l = np.minimum(x, x_prev)
    ha_c = ((x_prev + b_h + b_l + x) / 4.0).to_numpy()
    oc2 = ((x_prev + x) / 2.0).to_numpy()

    n = len(df)
    ha_o = np.full(n, np.nan)
    for t in range(n):
        if t == 0 or np.isnan(ha_o[t - 1]):
            ha_o[t] = oc2[t]
        else:
            ha_o[t] = (ha_o[t - 1] + ha_c[t - 1]) / 2.0
    ha_h = np.fmax(b_h.to_numpy(), np.fmax(ha_o, ha_c))
    ha_l = np.fmin(b_l.to_numpy(), np.fmin(ha_o, ha_c))

    ha_c_s = pd.Series(ha_c, index=df.index)
    ha_o_s = pd.Series(ha_o, index=df.index)
    signal = ema(ha_c_s, params.signal)
    hist = ha_c_s - signal

    up_body = ha_c_s > ha_o_s
    flip_up = up_body & ~up_body.shift(1, fill_value=True)
    flip_dn = ~up_body & up_body.shift(1, fill_value=False)
    thr = params.threshold
    return pd.DataFrame(
        {
            "macd_raw": x,
            "macd_ha_o": ha_o_s,
            "macd_ha_c": ha_c_s,
            "macd_ha_h": pd.Series(ha_h, index=df.index),
            "macd_ha_l": pd.Series(ha_l, index=df.index),
            "macd_signal": signal,
            "macd_hist": hist,
            "macd_os": flip_up & (pd.Series(ha_l, index=df.index) < -thr),
            "macd_ob": flip_dn & (pd.Series(ha_h, index=df.index) > thr),
            "macd_ha_up": up_body,
        },
        index=df.index,
    )


# ---------------------------------------------------------------------------
# Dynamic Swing Anchored VWAP


@dataclass(frozen=True)
class SwingVwapParams:
    period: int = 50
    apt: float = 20.0


def swing_anchored_vwap(df: pd.DataFrame, params: SwingVwapParams = SwingVwapParams()) -> pd.DataFrame:
    """Port of the Zeiierman study, default (non-adaptive) tracking speed.

    Returns, per bar: swing ``dir`` (+1 up / -1 down), the VWAP value the
    chart shows at that bar, the anchor bar position/price, and the latest
    swing high/low the direction is computed from.
    """
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    vol = np.nan_to_num(df["volume"].to_numpy(float), nan=0.0).clip(min=0.0)
    hlc3 = (high + low + close) / 3.0
    n = len(df)
    prd = params.period

    roll_hi = pd.Series(high).rolling(prd, min_periods=prd).max().to_numpy()
    roll_lo = pd.Series(low).rolling(prd, min_periods=prd).min().to_numpy()
    is_ph = high >= roll_hi  # NaN compares False during warm-up
    is_pl = low <= roll_lo
    pos = np.arange(n, dtype=float)
    ph_idx = pd.Series(np.where(is_ph, pos, np.nan)).ffill().fillna(0).to_numpy(int)
    pl_idx = pd.Series(np.where(is_pl, pos, np.nan)).ffill().fillna(0).to_numpy(int)
    ph_val = pd.Series(np.where(is_ph, high, np.nan)).ffill().to_numpy()
    pl_val = pd.Series(np.where(is_pl, low, np.nan)).ffill().to_numpy()
    direction = np.where(ph_idx > pl_idx, 1, -1)

    alpha = 1.0 - math.exp(-math.log(2.0) / max(1.0, params.apt))
    keep = 1.0 - alpha
    vwap = np.full(n, np.nan)
    anchor = np.full(n, -1, dtype=int)
    anchor_px = np.full(n, np.nan)
    flip = np.zeros(n, dtype=bool)
    p = v = 0.0
    started = False
    cur_anchor, cur_anchor_px = -1, np.nan
    for t in range(n):
        if t > 0 and direction[t] != direction[t - 1] and t >= prd:
            x = pl_idx[t] if direction[t] > 0 else ph_idx[t]
            y = pl_val[t] if direction[t] > 0 else ph_val[t]
            p = y * vol[x]
            v = vol[x]
            for i in range(x, t + 1):
                p = keep * p + alpha * hlc3[i] * vol[i]
                v = keep * v + alpha * vol[i]
            started = True
            flip[t] = True
            cur_anchor, cur_anchor_px = x, y
        elif started:
            p = keep * p + alpha * hlc3[t] * vol[t]
            v = keep * v + alpha * vol[t]
        if started and v > 0:
            vwap[t] = p / v
            anchor[t] = cur_anchor
            anchor_px[t] = cur_anchor_px

    return pd.DataFrame(
        {
            "swing_dir": direction,
            "swing_flip": flip,
            "svwap": vwap,
            "svwap_anchor_pos": anchor,
            "svwap_anchor_px": anchor_px,
            "swing_high": ph_val,
            "swing_low": pl_val,
            "swing_high_pos": ph_idx,
            "swing_low_pos": pl_idx,
        },
        index=df.index,
    )


# ---------------------------------------------------------------------------
# volume profile per session (prior sessions only)


def _triangular_shares(low: np.ndarray, high: np.ndarray, close: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Row-per-bar share of volume in each bin -- vectorised form of
    ``volume_profile._session_bin_shares`` (triangular kernel peaked at close)."""
    a = low[:, None]
    b = high[:, None]
    c = np.clip(close, low, high)[:, None]
    x = np.clip(edges[None, :], a, b)
    span = np.where(b > a, b - a, 1.0)
    left = np.where(c > a, (x - a) ** 2 / (span * np.where(c > a, c - a, 1.0)), 0.0)
    right = np.where(b > c, 1.0 - (b - x) ** 2 / (span * np.where(b > c, b - c, 1.0)), 1.0)
    cdf = np.where(x <= c, left, right)
    cdf[:, 0] = 0.0
    cdf[:, -1] = 1.0
    shares = np.clip(np.diff(cdf, axis=1), 0.0, None)
    # zero-range bars: everything into the bin that holds the price
    flat = (high <= low)
    if flat.any():
        idx = np.clip(np.searchsorted(edges, low[flat], side="right") - 1, 0, len(edges) - 2)
        shares[flat] = 0.0
        shares[np.flatnonzero(flat), idx] = 1.0
    tot = shares.sum(axis=1, keepdims=True)
    return np.divide(shares, tot, out=np.zeros_like(shares), where=tot > 0)


def profile_levels(window: pd.DataFrame, bins: int = 40) -> tuple[float, float, float] | None:
    """(poc, val, vah) of an OHLCV window, or None when it has no usable volume."""
    lo = float(window["low"].min())
    hi = float(window["high"].max())
    vol = np.nan_to_num(window["volume"].to_numpy(float), nan=0.0).clip(min=0.0)
    if not (np.isfinite(lo) and np.isfinite(hi)) or vol.sum() <= 0:
        return None
    if hi <= lo:
        return lo, lo, lo
    edges = np.linspace(lo, hi, bins + 1)
    shares = _triangular_shares(
        window["low"].to_numpy(float), window["high"].to_numpy(float), window["close"].to_numpy(float), edges
    )
    bin_vol = (shares * vol[:, None]).sum(axis=0)
    poc_i = int(np.argmax(bin_vol))
    poc = (edges[poc_i] + edges[poc_i + 1]) / 2.0
    records = [{"price_lo": edges[i], "price_hi": edges[i + 1], "volume": bin_vol[i]} for i in range(bins)]
    val, vah = value_area(records, coverage=0.70)
    return poc, val, vah


def session_profiles(df: pd.DataFrame, lookback_sessions: int = 20, bins: int = 40) -> pd.DataFrame:
    """POC/VAL/VAH for each bar, built from the ``lookback_sessions`` *prior*
    sessions (intraday) or prior bars (daily). Constant within a session."""
    intraday = _is_intraday(df.index)
    if intraday:
        day = df.index.normalize()
        days = pd.Index(day.unique())
        out = np.full((len(days), 3), np.nan)
        day_pos = pd.Series(np.arange(len(days)), index=days)
        codes = day_pos.reindex(day).to_numpy()
        starts = np.searchsorted(codes, np.arange(len(days)), side="left")
        for k in range(lookback_sessions, len(days)):
            window = df.iloc[starts[k - lookback_sessions] : starts[k]]
            lv = profile_levels(window, bins)
            if lv is not None:
                out[k] = lv
        per_bar = out[codes]
    else:
        per_bar = np.full((len(df), 3), np.nan)
        for t in range(lookback_sessions, len(df)):
            lv = profile_levels(df.iloc[t - lookback_sessions : t], bins)
            if lv is not None:
                per_bar[t] = lv
    return pd.DataFrame(per_bar, index=df.index, columns=["poc", "val", "vah"])


# ---------------------------------------------------------------------------
# relative volume


def _is_intraday(index: pd.Index) -> bool:
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 3:
        return False
    return bool(index.normalize().duplicated().any())


def relative_volume(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Volume over the median of the same time-of-day slot across the prior
    ``lookback`` sessions (intraday), or over the prior ``lookback``-bar median
    (daily). Slot-matching keeps the open/close volume smile out of the ratio."""
    vol = df["volume"].astype(float)
    if _is_intraday(df.index):
        slot = df.index.strftime("%H:%M")
        base = vol.groupby(slot).transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=max(5, lookback // 2)).median()
        )
    else:
        base = vol.shift(1).rolling(lookback, min_periods=max(5, lookback // 2)).median()
    return vol / base.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# feature frame


@dataclass(frozen=True)
class FeatureParams:
    atr_len: int = 14
    swing: SwingVwapParams = SwingVwapParams()
    macd: StMacdParams = StMacdParams()
    profile_sessions: int = 20
    profile_bins: int = 40
    rvol_lookback: int = 20
    climax_rvol: float = 2.0
    recent_bars: int = 5


def build_features(df: pd.DataFrame, params: FeatureParams = FeatureParams()) -> pd.DataFrame:
    """All signal-timeframe features, one row per bar, causal."""
    df = df[list(OHLCV)].astype(float)
    atr = wilder_atr(df, params.atr_len)
    macd = st_macd_ha(df, params.macd)
    sw = swing_anchored_vwap(df, params.swing)
    prof = session_profiles(df, params.profile_sessions, params.profile_bins)
    rvol = relative_volume(df, params.rvol_lookback)

    close, low, high = df["close"], df["low"], df["high"]
    k = params.recent_bars
    f = pd.DataFrame(index=df.index)
    f["close"] = close
    f["atr"] = atr
    f["rvol"] = rvol

    # --- MACD-HA
    f["macd_ha_c"] = macd["macd_ha_c"]
    f["macd_hist"] = macd["macd_hist"]
    f["macd_os"] = macd["macd_os"]
    f["macd_ob"] = macd["macd_ob"]
    f["macd_ha_up"] = macd["macd_ha_up"]
    f["macd_os_recent"] = macd["macd_os"].rolling(k, min_periods=1).max().astype(bool)
    f["macd_ob_recent"] = macd["macd_ob"].rolling(k, min_periods=1).max().astype(bool)
    f["macd_below_100"] = macd["macd_ha_l"] < -params.macd.threshold
    f["macd_above_100"] = macd["macd_ha_h"] > params.macd.threshold
    f["macd_hist_rising"] = macd["macd_hist"] > macd["macd_hist"].shift(1)

    # --- swing VWAP
    f["swing_dir"] = sw["swing_dir"]
    f["svwap"] = sw["svwap"]
    f["svwap_dist_atr"] = (close - sw["svwap"]) / atr
    above = close > sw["svwap"]
    f["svwap_above"] = above
    # reclaim = close crosses the downtrend's VWAP while structure is still down
    f["svwap_reclaim"] = (sw["swing_dir"] < 0) & above & ~above.shift(1, fill_value=True)
    f["svwap_reject"] = (sw["swing_dir"] > 0) & ~above & above.shift(1, fill_value=False)
    f["svwap_reclaim_recent"] = f["svwap_reclaim"].rolling(k, min_periods=1).max().astype(bool)
    f["svwap_reject_recent"] = f["svwap_reject"].rolling(k, min_periods=1).max().astype(bool)
    f["svwap_slope_atr"] = (sw["svwap"] - sw["svwap"].shift(k)) / (k * atr)
    pos = np.arange(len(df))
    f["bars_since_anchor"] = np.where(sw["svwap_anchor_pos"] >= 0, pos - sw["svwap_anchor_pos"], np.nan)
    f["off_high_atr"] = (close - high.rolling(params.swing.period, min_periods=1).max()) / atr
    f["off_low_atr"] = (close - low.rolling(params.swing.period, min_periods=1).min()) / atr

    # --- volume profile (control)
    f["poc"], f["val"], f["vah"] = prof["poc"], prof["val"], prof["vah"]
    f["poc_dist_atr"] = (close - prof["poc"]) / atr
    below_val_recent = (low < prof["val"]).rolling(k, min_periods=1).max().astype(bool)
    above_vah_recent = (high > prof["vah"]).rolling(k, min_periods=1).max().astype(bool)
    f["val_reentry"] = below_val_recent & (close > prof["val"])
    f["vah_reentry"] = above_vah_recent & (close < prof["vah"])
    f["below_val"] = close < prof["val"]
    f["above_vah"] = close > prof["vah"]
    above_poc = close > prof["poc"]
    f["poc_reclaim"] = above_poc & ~above_poc.shift(1, fill_value=True)
    f["poc_lose"] = ~above_poc & above_poc.shift(1, fill_value=False)

    # --- volume behaviour at the extreme
    low_k = low.rolling(k, min_periods=1).min()
    high_k = high.rolling(k, min_periods=1).max()
    rv = rvol.fillna(0.0)
    # rvol on the bar that printed the recent low / high
    low_bar_rvol = _value_at_rolling_arg(low.to_numpy(), rv.to_numpy(), k, np.argmin)
    high_bar_rvol = _value_at_rolling_arg(high.to_numpy(), rv.to_numpy(), k, np.argmax)
    f["low_bar_rvol"] = low_bar_rvol
    f["high_bar_rvol"] = high_bar_rvol
    f["climax_at_low"] = (low_bar_rvol >= params.climax_rvol) & (low_k <= low.rolling(params.swing.period, min_periods=1).min())
    f["climax_at_high"] = (high_bar_rvol >= params.climax_rvol) & (high_k >= high.rolling(params.swing.period, min_periods=1).max())
    leg_rvol = rv.rolling(params.swing.period // 2, min_periods=5).mean()
    recent_rvol = rv.rolling(k, min_periods=1).mean()
    f["rvol_fade"] = recent_rvol < 0.8 * leg_rvol.shift(k)
    # close position in bar range, volume-weighted over recent bars (candle
    # shape x volume; NOT order flow -- there is no trade/quote data here)
    clv = ((close - low) - (high - close)) / (high - low).replace(0.0, np.nan)
    f["clv_vol_recent"] = (clv.fillna(0.0) * rv).rolling(k, min_periods=1).sum() / rv.rolling(k, min_periods=1).sum().replace(0.0, np.nan)

    # --- divergence inside the current swing leg (leg = bars sharing an anchor)
    leg = sw["svwap_anchor_pos"]
    leg_low = low.groupby(leg).cummin()
    leg_high = high.groupby(leg).cummax()
    leg_macd_min = macd["macd_ha_l"].groupby(leg).cummin()
    leg_macd_max = macd["macd_ha_h"].groupby(leg).cummax()
    recent_macd_min = macd["macd_ha_l"].rolling(k, min_periods=1).min()
    recent_macd_max = macd["macd_ha_h"].rolling(k, min_periods=1).max()
    thr = params.macd.threshold
    # price is back at the leg's extreme, but momentum's recent extreme is
    # well short of the one the leg already printed
    f["bull_div"] = (leg >= 0) & (low_k <= leg_low + 0.25 * atr) & (leg_macd_min < -thr) & (recent_macd_min > leg_macd_min + 0.3 * thr)
    f["bear_div"] = (leg >= 0) & (high_k >= leg_high - 0.25 * atr) & (leg_macd_max > thr) & (recent_macd_max < leg_macd_max - 0.3 * thr)
    f["macd_div_gap"] = (recent_macd_min - leg_macd_min) / thr  # bull reading; bear side mirrors below
    f["macd_div_gap_bear"] = (leg_macd_max - recent_macd_max) / thr

    # --- stretch, volatility regime, clock
    f["ret5_atr"] = (close - close.shift(5)) / atr
    f["ret21_atr"] = (close - close.shift(21)) / atr
    f["ret10_pct"] = close / close.shift(10) - 1.0
    f["vol_regime"] = atr / atr.rolling(100, min_periods=30).median()
    if _is_intraday(df.index):
        f["slot"] = (df.index.hour + df.index.minute / 60.0 - 9.5) / 6.5
    else:
        f["slot"] = 0.0
    return f


def _value_at_rolling_arg(key: np.ndarray, val: np.ndarray, k: int, argf) -> np.ndarray:
    n = len(key)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    from numpy.lib.stride_tricks import sliding_window_view

    if n >= k:
        kw = sliding_window_view(np.nan_to_num(key, nan=np.inf if argf is np.argmin else -np.inf), k)
        vw = sliding_window_view(val, k)
        idx = argf(kw, axis=1)
        out[k - 1 :] = vw[np.arange(len(idx)), idx]
    return out


# ---------------------------------------------------------------------------
# higher timeframe context


def htf_context(htf: pd.DataFrame, params: StMacdParams = StMacdParams(), profile_bars: int = 60) -> pd.DataFrame:
    """Scale-free context on the higher timeframe (daily for 1h, weekly for
    daily). Row ``d`` holds what was known after HTF bar ``d`` closed; callers
    must align it to the *next* HTF period to stay causal."""
    htf = htf[list(OHLCV)].astype(float)
    atr = wilder_atr(htf, 14)
    macd = st_macd_ha(htf, params)
    close = htf["close"]
    lo20 = htf["low"].rolling(20, min_periods=10).min()
    hi20 = htf["high"].rolling(20, min_periods=10).max()
    levels = np.full((len(htf), 3), np.nan)
    for t in range(profile_bars, len(htf)):
        lv = profile_levels(htf.iloc[t - profile_bars + 1 : t + 1], bins=30)
        if lv is not None:
            levels[t] = lv
    poc = pd.Series(levels[:, 0], index=htf.index)
    val = pd.Series(levels[:, 1], index=htf.index)
    vah = pd.Series(levels[:, 2], index=htf.index)
    sma50 = close.rolling(50, min_periods=30).mean()
    return pd.DataFrame(
        {
            "htf_macd": macd["macd_ha_c"],
            "htf_macd_os_zone": macd["macd_ha_l"] < -params.threshold,
            "htf_macd_ob_zone": macd["macd_ha_h"] > params.threshold,
            "htf_macd_ha_up": macd["macd_ha_up"],
            "htf_range_pos": (close - lo20) / (hi20 - lo20).replace(0.0, np.nan),
            "htf_poc_dist_atr": (close - poc) / atr,
            "htf_near_val": ((close - val) / atr).abs() <= 1.0,
            "htf_near_vah": ((close - vah) / atr).abs() <= 1.0,
            "htf_below_val": close < val,
            "htf_above_vah": close > vah,
            "htf_trend_up": close > sma50,
        },
        index=htf.index,
    )


def align_htf(ltf_index: pd.DatetimeIndex, ctx: pd.DataFrame, htf_freq: str) -> pd.DataFrame:
    """Attach the last *completed* HTF row to each LTF bar.

    ``htf_freq='D'``: a 1h bar on day d sees the daily row for the last date
    strictly before d. ``'W'``: a daily bar sees the last weekly row whose
    week ended before the bar's week started.
    """
    ctx = ctx.sort_index()
    if htf_freq == "D":
        keys = ltf_index.normalize()
        pos = np.searchsorted(ctx.index.normalize().to_numpy(), keys.to_numpy(), side="left") - 1
    else:
        week_start = (ltf_index - pd.to_timedelta(ltf_index.dayofweek, unit="D")).normalize()
        pos = np.searchsorted(ctx.index.to_numpy(), week_start.to_numpy(), side="left") - 1
    out = ctx.iloc[np.clip(pos, 0, None)].astype(float)
    out.index = ltf_index
    out[pos < 0] = np.nan
    return out


def weekly_bars(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly OHLCV indexed by the week's last trading day."""
    daily = daily[list(OHLCV)].astype(float)
    g = daily.groupby(daily.index.to_period("W-FRI"))
    wk = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    )
    wk.index = g.apply(lambda s: s.index[-1])
    return wk


# ---------------------------------------------------------------------------
# forward labels (for the study only -- never used by the live read)


def triple_barrier(df: pd.DataFrame, atr: pd.Series, horizon: int, up_mult: float, dn_mult: float, side: int) -> pd.Series:
    """1 when the favourable barrier (``up_mult`` ATR in ``side`` direction) is
    touched before the adverse one (``dn_mult`` ATR) within ``horizon`` bars;
    0 otherwise (adverse first, both in one bar, or timeout); NaN when the
    horizon runs past the data."""
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(df)
    out = np.full(n, np.nan)
    for t in range(n - horizon):
        if not np.isfinite(a[t]) or a[t] <= 0:
            continue
        if side > 0:
            win_px, loss_px = close[t] + up_mult * a[t], close[t] - dn_mult * a[t]
            hit_win = high[t + 1 : t + 1 + horizon] >= win_px
            hit_loss = low[t + 1 : t + 1 + horizon] <= loss_px
        else:
            win_px, loss_px = close[t] - up_mult * a[t], close[t] + dn_mult * a[t]
            hit_win = low[t + 1 : t + 1 + horizon] <= win_px
            hit_loss = high[t + 1 : t + 1 + horizon] >= loss_px
        w = int(np.argmax(hit_win)) if hit_win.any() else horizon
        l = int(np.argmax(hit_loss)) if hit_loss.any() else horizon
        out[t] = 1.0 if w < l else 0.0
    return pd.Series(out, index=df.index)
