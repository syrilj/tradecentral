"""Which chart signals lead a reversal, and by how much -- measured out of sample.

Question (from the operator): volume-profile control (POC / value area), the
swing-anchored VWAP, the standardized MACD-HA and higher-timeframe location
together "tell you" a bottom or top. The swing VWAP only confirms after the
move. Is there a volume relationship that gets you in earlier, i.e. when to
add calls or puts?

Design
------
* Candidate bars: bottoms are searched only where swing structure is still
  down (``swing_dir == -1``) and price is at least 3 ATR under its 50-bar
  high; tops mirror that. This is "price is in a leg, is this where it turns".
* Outcome: a 2:1 triple barrier in ATR units -- +2 ATR in the trade direction
  before -1 ATR against, within ``horizon`` bars. A driftless walk lands near
  33%; every signal is judged as lift over the candidate set's own base rate.
* Market context: SPY's own MACD-HA / leg depth, and breadth (share of the
  universe beyond +/-100 on the MACD-HA on the same bar). Contemporaneous
  closes only, so still causal.
* Split by date: fit | validation | purge | test = first 48% | next 12% | gap |
  last 40%. Model *choice* and calibration use validation only; the test
  period is scored once. Every CI resamples whole dates -- all symbols on a
  day move together, so rows are not independent.
* Lag: for every swing-direction flip, how many bars and ATR after the true
  extreme it printed, against the first VWAP reclaim and the MACD-HA signal.

Run:  python -m edge.research.reversal_study --tf 1d
Writes ``runs/reversal_study/<tf>/summary.json`` and ``model.joblib``; the
live read in ``research.reversal_engine`` loads both.
"""

from __future__ import annotations

import argparse
import gc
import json
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from edge.research import reversal_signals as rs

ROOT = Path(__file__).resolve().parents[1]
DATA_1H = ROOT / "data" / "1h"
DATA_1D = ROOT / "data" / "1d_wide"
OUT_DIR = ROOT / "runs" / "reversal_study"
MARKET_SYMBOL = "SPY"


@dataclass(frozen=True)
class TfConfig:
    tf: str
    horizon: int
    win_atr: float
    loss_atr: float
    profile_sessions: int
    profile_bins: int
    leg_atr: float
    htf_freq: str
    thin: int


CONFIGS = {
    # 21 bars = three sessions. Adjacent 1h bars share 20 of 21 forward bars,
    # so keeping every third candidate loses little information.
    "1h": TfConfig("1h", horizon=21, win_atr=2.0, loss_atr=1.0, profile_sessions=20, profile_bins=40, leg_atr=3.0, htf_freq="D", thin=3),
    # 10 sessions; monthly-option horizon
    "1d": TfConfig("1d", horizon=10, win_atr=2.0, loss_atr=1.0, profile_sessions=60, profile_bins=30, leg_atr=3.0, htf_freq="W", thin=1),
}

# Directional signal name -> (bottom source, top source, label). Bottoms read
# the left column, tops the right; after `directional_frame` True always means
# "points toward the reversal being searched for".
BINARY_PAIRS = [
    ("macd_os_recent", "macd_ob_recent", "MACD-HA OS/OB signal in last 5 bars"),
    ("macd_below_100", "macd_above_100", "MACD-HA beyond -100/+100"),
    ("macd_turn", "macd_turn", "MACD-HA histogram turning against the leg"),
    ("macd_div", "macd_div", "Price back at the leg extreme, MACD-HA extreme well short of the leg's (divergence)"),
    ("svwap_reclaim_recent", "svwap_reject_recent", "Close back across the swing VWAP (structure not yet flipped)"),
    ("svwap_far", "svwap_far", "Price stretched > 2 ATR from swing VWAP"),
    ("val_reentry", "vah_reentry", "Poked outside value, closed back inside (failed auction)"),
    ("outside_value", "outside_value", "Closed outside the value area"),
    ("poc_cross", "poc_cross", "Crossed the POC in the reversal direction"),
    ("climax_at_extreme", "climax_at_extreme", "Extreme printed on >=2x slot volume"),
    ("rvol_fade", "rvol_fade", "Volume fading into the extreme"),
    ("clv_turn", "clv_turn", "Recent closes volume-weighted toward the reversal side"),
    ("htf_zone", "htf_zone", "HTF MACD-HA beyond +/-100 (prior HTF bar)"),
    ("htf_at_value_edge", "htf_at_value_edge", "HTF price within 1 ATR of its value-area edge"),
    ("htf_outside_value", "htf_outside_value", "HTF price outside its value area"),
    ("htf_with_trend", "htf_with_trend", "Reversal direction agrees with HTF 50-bar trend"),
    ("htf_range_edge", "htf_range_edge", "HTF price in the outer 20% of its 20-bar range"),
    ("mkt_zone", "mkt_zone", "SPY MACD-HA beyond +/-100 on the same bar"),
    ("breadth_extreme", "breadth_extreme", "25%+ of the universe beyond +/-100 on the same bar"),
    ("vol_expanded", "vol_expanded", "ATR 1.5x its 100-bar median (capitulation-type volatility)"),
]
BINARY = [name for name, _, _ in BINARY_PAIRS]

CHART_CONTINUOUS = [
    "macd_ha_c_dir", "macd_hist_dir", "macd_div_gap", "svwap_dist_dir", "svwap_slope_dir", "poc_dist_dir",
    "log_rvol", "log_extreme_rvol", "clv_dir", "leg_depth", "log_bars_since_anchor",
    "htf_macd_dir", "htf_range_pos_dir", "htf_poc_dist_dir",
]
CONTEXT_CONTINUOUS = [
    "stretch5", "stretch21", "log_vol_regime", "slot",
    "mkt_macd_dir", "mkt_leg_depth", "mkt_stretch5", "breadth_dir", "breadth_net_dir", "rel_strength_dir",
]
# The original chart-only feature set, kept as the ablation baseline.
CHART_BINARY = [b for b in BINARY if b not in ("mkt_zone", "breadth_extreme", "vol_expanded")]
FEATURES_CHART = CHART_BINARY + CHART_CONTINUOUS
FEATURES = BINARY + CHART_CONTINUOUS + CONTEXT_CONTINUOUS


def directional_frame(f: pd.DataFrame, side: int) -> pd.DataFrame:
    """Re-express features so that 'larger / True' always means 'toward the
    reversal in ``side``'. One model spec then serves bottoms and tops."""
    s = float(side)
    bull = side > 0
    d = pd.DataFrame(index=f.index)
    d["macd_os_recent"] = f["macd_os_recent" if bull else "macd_ob_recent"]
    d["macd_below_100"] = f["macd_below_100" if bull else "macd_above_100"]
    d["macd_turn"] = f["macd_hist_rising"] if bull else ~f["macd_hist_rising"]
    d["macd_div"] = f["bull_div" if bull else "bear_div"]
    d["svwap_reclaim_recent"] = f["svwap_reclaim_recent" if bull else "svwap_reject_recent"]
    d["svwap_far"] = (-s * f["svwap_dist_atr"]) > 2.0
    d["val_reentry"] = f["val_reentry" if bull else "vah_reentry"]
    d["outside_value"] = f["below_val" if bull else "above_vah"]
    d["poc_cross"] = f["poc_reclaim" if bull else "poc_lose"]
    d["climax_at_extreme"] = f["climax_at_low" if bull else "climax_at_high"]
    d["rvol_fade"] = f["rvol_fade"]
    d["clv_turn"] = (s * f["clv_vol_recent"]) > 0.25
    d["htf_zone"] = f["htf_macd_os_zone" if bull else "htf_macd_ob_zone"].astype(float) > 0.5
    d["htf_at_value_edge"] = f["htf_near_val" if bull else "htf_near_vah"].astype(float) > 0.5
    d["htf_outside_value"] = f["htf_below_val" if bull else "htf_above_vah"].astype(float) > 0.5
    trend_up = f["htf_trend_up"].astype(float) > 0.5
    d["htf_with_trend"] = trend_up if bull else ~trend_up
    rp = f["htf_range_pos"]
    d["htf_range_edge"] = (rp < 0.2) if bull else (rp > 0.8)
    d["mkt_zone"] = (-s * f["mkt_macd"]) > 100.0
    d["breadth_extreme"] = f["breadth_below" if bull else "breadth_above"] >= 0.25
    d["vol_expanded"] = f["vol_regime"] >= 1.5

    d["macd_ha_c_dir"] = (-s * f["macd_ha_c"] / 100.0).clip(-4, 4)
    d["macd_hist_dir"] = (s * f["macd_hist"] / 50.0).clip(-4, 4)
    d["macd_div_gap"] = f["macd_div_gap" if bull else "macd_div_gap_bear"].clip(-2, 4)
    d["svwap_dist_dir"] = (s * f["svwap_dist_atr"]).clip(-8, 8)
    d["svwap_slope_dir"] = (s * f["svwap_slope_atr"]).clip(-2, 2)
    d["poc_dist_dir"] = (-s * f["poc_dist_atr"]).clip(-10, 10)
    d["log_rvol"] = np.log(f["rvol"].clip(0.05, 20))
    d["log_extreme_rvol"] = np.log(f["low_bar_rvol" if bull else "high_bar_rvol"].clip(0.05, 20))
    d["clv_dir"] = s * f["clv_vol_recent"]
    d["leg_depth"] = ((-f["off_high_atr"]) if bull else f["off_low_atr"]).clip(0, 30)
    d["log_bars_since_anchor"] = np.log1p(f["bars_since_anchor"].clip(0, 2000))
    d["htf_macd_dir"] = (-s * f["htf_macd"] / 100.0).clip(-4, 4)
    d["htf_range_pos_dir"] = (0.5 - f["htf_range_pos"]) * s
    d["htf_poc_dist_dir"] = (-s * f["htf_poc_dist_atr"]).clip(-10, 10)

    d["stretch5"] = (-s * f["ret5_atr"]).clip(-10, 10)
    d["stretch21"] = (-s * f["ret21_atr"]).clip(-20, 20)
    d["log_vol_regime"] = np.log(f["vol_regime"].clip(0.2, 5))
    d["slot"] = f["slot"]
    d["mkt_macd_dir"] = (-s * f["mkt_macd"] / 100.0).clip(-4, 4)
    d["mkt_leg_depth"] = ((-f["mkt_off_high_atr"]) if bull else f["mkt_off_low_atr"]).clip(0, 30)
    d["mkt_stretch5"] = (-s * f["mkt_ret5_atr"]).clip(-10, 10)
    d["breadth_dir"] = f["breadth_below" if bull else "breadth_above"]
    d["breadth_net_dir"] = s * (f["breadth_below"] - f["breadth_above"])
    d["rel_strength_dir"] = (s * (f["ret10_pct"] - f["mkt_ret10_pct"]) * 100.0).clip(-50, 50)
    return d


# ---------------------------------------------------------------------------
# data


def load_bars(sym: str, cfg: TfConfig) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    try:
        if cfg.tf == "1h":
            bars = pd.read_parquet(DATA_1H / f"{sym}.parquet")
            htf = pd.read_parquet(DATA_1D / f"{sym}.parquet")
        else:
            bars = pd.read_parquet(DATA_1D / f"{sym}.parquet")
            htf = None
    except Exception:
        return None
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    if htf is None:
        htf = rs.weekly_bars(bars)
    else:
        htf = htf.dropna(subset=["open", "high", "low", "close"])
        htf = htf[~htf.index.duplicated(keep="last")].sort_index()
    return bars, htf


def _breadth_flags(sym: str, cfg: TfConfig) -> pd.DataFrame | None:
    warnings.filterwarnings("ignore")
    loaded = load_bars(sym, cfg)
    if loaded is None or len(loaded[0]) < 200:
        return None
    m = rs.st_macd_ha(loaded[0])
    return pd.DataFrame(
        {"below": (m["macd_ha_l"] < -100).astype(np.int16), "above": (m["macd_ha_h"] > 100).astype(np.int16), "n": np.int16(1)},
        index=loaded[0].index,
    ).loc[m["macd_ha_c"].notna()]


def market_context(bars_by_ts_frames: list[pd.DataFrame], market: pd.DataFrame) -> pd.DataFrame:
    """Breadth + SPY features on every timestamp. Breadth needs 50+ symbols
    reporting on a bar, otherwise it is left NaN rather than read off a handful."""
    tot = None
    for fr in bars_by_ts_frames:
        tot = fr if tot is None else tot.add(fr, fill_value=0)
    ctx = pd.DataFrame(index=tot.index)
    ok = tot["n"] >= 50
    ctx["breadth_below"] = np.where(ok, tot["below"] / tot["n"], np.nan)
    ctx["breadth_above"] = np.where(ok, tot["above"] / tot["n"], np.nan)
    mf = market_features(market)
    return ctx.join(mf, how="outer")


def market_features(market: pd.DataFrame) -> pd.DataFrame:
    market = market[list(rs.OHLCV)].astype(float)
    atr = rs.wilder_atr(market, 14)
    m = rs.st_macd_ha(market)
    c = market["close"]
    return pd.DataFrame(
        {
            "mkt_macd": m["macd_ha_c"],
            "mkt_off_high_atr": (c - market["high"].rolling(50, min_periods=1).max()) / atr,
            "mkt_off_low_atr": (c - market["low"].rolling(50, min_periods=1).min()) / atr,
            "mkt_ret5_atr": (c - c.shift(5)) / atr,
            "mkt_ret10_pct": c / c.shift(10) - 1.0,
        },
        index=market.index,
    )


def symbol_rows(sym: str, code: int, cfg: TfConfig, ctx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    warnings.filterwarnings("ignore")
    loaded = load_bars(sym, cfg)
    if loaded is None:
        return None
    bars, htf = loaded
    if len(bars) < 400 or len(htf) < 80:
        return None
    params = rs.FeatureParams(profile_sessions=cfg.profile_sessions, profile_bins=cfg.profile_bins)
    f = rs.build_features(bars, params)
    f = f.join(rs.align_htf(bars.index, rs.htf_context(htf), cfg.htf_freq))
    f = f.join(ctx.reindex(bars.index))
    atr = f["atr"]
    y_bull = rs.triple_barrier(bars, atr, cfg.horizon, cfg.win_atr, cfg.loss_atr, +1)
    y_bear = rs.triple_barrier(bars, atr, cfg.horizon, cfg.win_atr, cfg.loss_atr, -1)
    fwd = (bars["close"].shift(-cfg.horizon) - bars["close"]) / atr
    thin_mask = pd.Series(np.arange(len(bars)) % cfg.thin == 0, index=bars.index)

    frames = []
    for side, mask, y in (
        (+1, (f["swing_dir"] < 0) & (f["off_high_atr"] <= -cfg.leg_atr), y_bull),
        (-1, (f["swing_dir"] > 0) & (f["off_low_atr"] >= cfg.leg_atr), y_bear),
    ):
        keep = (
            mask & thin_mask & y.notna() & atr.notna() & f["svwap"].notna() & f["poc"].notna()
            & f["htf_macd"].notna() & f["mkt_macd"].notna()
        )
        if not keep.any():
            continue
        d = directional_frame(f.loc[keep], side)
        out = d[FEATURES].astype(np.float32)
        out["y"] = y[keep].astype(np.int8)
        out["fwd_atr_dir"] = (fwd[keep] * side).astype(np.float32)
        out["side"] = np.int8(side)
        out["sym"] = np.int16(code)
        out["day"] = (d.index.normalize().asi8 // 86_400_000_000_000).astype(np.int32)
        frames.append(out.reset_index(drop=True))
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # --- lag of the swing flip vs the reclaim / MACD signal that preceded it
    sw = rs.swing_anchored_vwap(bars)
    close = bars["close"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    high = bars["high"].to_numpy(float)
    atr_np = atr.to_numpy(float)
    flips = np.flatnonzero(sw["swing_flip"].to_numpy())
    reclaim, reject = f["svwap_reclaim"].to_numpy(), f["svwap_reject"].to_numpy()
    macd_os, macd_ob = f["macd_os"].to_numpy(), f["macd_ob"].to_numpy()
    bull_div, bear_div = f["bull_div"].to_numpy(), f["bear_div"].to_numpy()
    lag = []
    for j in range(1, len(flips)):
        t, prev = flips[j], flips[j - 1]
        side = int(sw["swing_dir"].iat[t])
        ext = int(sw["swing_low_pos"].iat[t] if side > 0 else sw["swing_high_pos"].iat[t])
        a = atr_np[ext]
        if not np.isfinite(a) or a <= 0 or ext <= prev:
            continue
        ext_px = low[ext] if side > 0 else high[ext]
        row = {"side": side, "flip_lag_bars": int(t - ext), "flip_move_atr": float(side * (close[t] - ext_px) / a)}
        for name, arr, start in (
            ("cue", reclaim if side > 0 else reject, ext),
            ("macd", macd_os if side > 0 else macd_ob, max(prev, ext - 10)),
            ("div", bull_div if side > 0 else bear_div, max(prev, ext - 10)),
        ):
            idx = np.flatnonzero(arr[start : t + 1]) + start
            row[f"{name}_lag_bars"] = float(idx[0] - ext) if len(idx) else np.nan
            row[f"{name}_move_atr"] = float(side * (close[idx[0]] - ext_px) / a) if len(idx) else np.nan
        lag.append(row)
    trades = structural_trades(bars, f, sw, cfg)
    return rows, pd.DataFrame(lag), trades


TRIGGERS = {
    # name: (bottom column, top column, description)
    "reclaim": ("svwap_reclaim", "svwap_reject", "First close back across the swing VWAP in the leg"),
    "macd_signal": ("macd_os", "macd_ob", "MACD-HA OS / OB triangle"),
    "divergence": ("bull_div", "bear_div", "First MACD-HA divergence at the leg extreme"),
    "value_reentry": ("val_reentry", "vah_reentry", "First close back inside value after trading outside it"),
    "reclaim_confirmed": ("_reclaim_conf_bull", "_reclaim_conf_bear", "VWAP reclaim with a divergence or OS/OB in the prior 10 bars"),
    "swing_flip": ("_flip_up", "_flip_dn", "Swing VWAP direction flip (the lagging confirmation)"),
    # same stop/target rule on ordinary leg bars: what drift + the rule alone earn
    "baseline": ("_base_bull", "_base_bear", "Every 7th bar of any qualifying leg (no signal) -- the benchmark"),
}


def structural_trades(bars: pd.DataFrame, f: pd.DataFrame, sw: pd.DataFrame, cfg: TfConfig) -> pd.DataFrame:
    """Trade each trigger the way a discretionary trader would: enter on the
    trigger bar's close, stop 0.1 ATR beyond the leg's extreme so far, target
    2R, give it 3x the barrier horizon. One trade per trigger per leg."""
    n = len(bars)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    close = bars["close"].to_numpy(float)
    atr = f["atr"].to_numpy(float)
    anchor = sw["svwap_anchor_pos"].to_numpy()
    dirn = sw["swing_dir"].to_numpy()
    flip = sw["swing_flip"].to_numpy()
    cols = f.copy()
    early_bull = (f["bull_div"] | f["macd_os"]).rolling(10, min_periods=1).max().astype(bool)
    early_bear = (f["bear_div"] | f["macd_ob"]).rolling(10, min_periods=1).max().astype(bool)
    cols["_reclaim_conf_bull"] = f["svwap_reclaim"] & early_bull
    cols["_reclaim_conf_bear"] = f["svwap_reject"] & early_bear
    cols["_flip_up"] = flip & (dirn > 0)
    cols["_flip_dn"] = flip & (dirn < 0)
    every7 = pd.Series(np.arange(n) % 7 == 0, index=f.index)
    cols["_base_bull"] = every7 & (f["swing_dir"] < 0) & (f["off_high_atr"] <= -cfg.leg_atr)
    cols["_base_bear"] = every7 & (f["swing_dir"] > 0) & (f["off_low_atr"] >= cfg.leg_atr)
    leg_low = pd.Series(low).groupby(anchor).cummin().to_numpy()
    leg_high = pd.Series(high).groupby(anchor).cummax().to_numpy()
    hold = cfg.horizon * 3
    out = []
    for trig, (bull_col, bear_col, _) in TRIGGERS.items():
        for side, col in ((1, bull_col), (-1, bear_col)):
            fired = np.flatnonzero(cols[col].to_numpy(bool))
            seen: set = set()
            for t in fired:
                if t + 1 >= n or anchor[t] < 0 or not np.isfinite(atr[t]) or atr[t] <= 0:
                    continue
                if trig == "swing_flip":
                    # the flip re-anchors at the extreme it confirmed
                    ext = low[int(sw["swing_low_pos"].iat[t])] if side > 0 else high[int(sw["swing_high_pos"].iat[t])]
                    key = t
                elif trig == "baseline":
                    ext = leg_low[t] if side > 0 else leg_high[t]
                    key = t
                else:
                    in_leg = dirn[t] < 0 if side > 0 else dirn[t] > 0
                    if not in_leg:
                        continue
                    ext = leg_low[t] if side > 0 else leg_high[t]
                    key = anchor[t]
                if key in seen:
                    continue
                seen.add(key)
                entry = close[t]
                stop = ext - 0.1 * atr[t] if side > 0 else ext + 0.1 * atr[t]
                risk = (entry - stop) * side
                if risk <= 0:
                    continue
                target = entry + 2.0 * risk * side
                end = min(n - 1, t + hold)
                if end <= t:
                    continue
                r_mult, win = None, 0
                for i in range(t + 1, end + 1):
                    hit_stop = low[i] <= stop if side > 0 else high[i] >= stop
                    hit_tgt = high[i] >= target if side > 0 else low[i] <= target
                    if hit_stop:
                        r_mult = -1.0
                        break
                    if hit_tgt:
                        r_mult, win = 2.0, 1
                        break
                if r_mult is None:
                    if t + hold >= n:
                        continue  # still open at the end of the data
                    r_mult = float(np.clip((close[end] - entry) * side / risk, -1.0, 2.0))
                h_end = min(n - 1, t + cfg.horizon)
                seg_hi = high[t + 1 : h_end + 1].max() if h_end > t else entry
                seg_lo = low[t + 1 : h_end + 1].min() if h_end > t else entry
                mfe = ((seg_hi - entry) if side > 0 else (entry - seg_lo)) / atr[t]
                out.append(
                    {
                        "trigger": trig, "side": side, "day": int(bars.index[t].normalize().value // 86_400_000_000_000),
                        "r": r_mult, "win": win, "risk_atr": float(risk / atr[t]), "mfe_atr": float(mfe),
                    }
                )
    return pd.DataFrame(out)


def paired_edge(t: pd.DataFrame, base: pd.DataFrame, reps: int = 400, seed: int = 3) -> dict:
    """avg R of a trigger minus avg R of the baseline, bootstrapping dates
    jointly so market-wide days move both sides together."""
    if t.empty or base.empty:
        return {"edge_r": None, "lo": None, "hi": None}
    all_days = np.union1d(t["day"].unique(), base["day"].unique())
    idx = pd.Index(all_days)
    k = len(idx)
    tc = idx.get_indexer(t["day"])
    bc = idx.get_indexer(base["day"])
    tr_sum = np.bincount(tc, weights=t["r"].to_numpy(float), minlength=k)
    tr_cnt = np.bincount(tc, minlength=k).astype(float)
    b_sum = np.bincount(bc, weights=base["r"].to_numpy(float), minlength=k)
    b_cnt = np.bincount(bc, minlength=k).astype(float)
    draws = np.random.default_rng(seed).integers(0, k, size=(reps, k))
    edges = tr_sum[draws].sum(1) / np.maximum(tr_cnt[draws].sum(1), 1) - b_sum[draws].sum(1) / np.maximum(b_cnt[draws].sum(1), 1)
    return {"edge_r": float(t["r"].mean() - base["r"].mean()), "lo": float(np.quantile(edges, 0.025)), "hi": float(np.quantile(edges, 0.975))}


def trade_table(trades: pd.DataFrame, split_day: int) -> dict:
    out: dict = {}
    for side, label in ((1, "bottom"), (-1, "top")):
        base_all = trades[(trades["trigger"] == "baseline") & (trades["side"] == side)]
        rows = []
        for trig, (_, _, desc) in TRIGGERS.items():
            t = trades[(trades["trigger"] == trig) & (trades["side"] == side)]
            if t.empty:
                continue
            entry = {"trigger": trig, "label": desc}
            for part, sub in (("all", t), ("early", t[t["day"] < split_day]), ("late", t[t["day"] >= split_day])):
                if sub.empty:
                    entry[part] = None
                    continue
                r = clustered_rate(sub["r"].to_numpy(), sub["day"].to_numpy())
                w = clustered_rate(sub["win"].to_numpy(), sub["day"].to_numpy())
                base = base_all if part == "all" else base_all[(base_all["day"] < split_day) == (part == "early")]
                entry[part] = {
                    "n": r["n"], "avg_r": r["rate"], "avg_r_lo": r["lo"], "avg_r_hi": r["hi"],
                    "win_rate": w["rate"], "risk_atr_median": float(sub["risk_atr"].median()),
                    "mfe_atr_median": float(sub["mfe_atr"].median()),
                    "vs_baseline": paired_edge(sub, base) if trig != "baseline" else None,
                }
            rows.append(entry)
        out[label] = rows
    return out


# ---------------------------------------------------------------------------
# statistics


def clustered_rate(y: np.ndarray, days: np.ndarray, reps: int = 400, seed: int = 7) -> dict:
    """Hit rate with a bootstrap CI that resamples whole dates."""
    if len(y) == 0:
        return {"n": 0, "rate": None, "lo": None, "hi": None, "dates": 0}
    codes, _ = pd.factorize(days)
    hits = np.bincount(codes, weights=y.astype(float))
    cnt = np.bincount(codes).astype(float)
    k = len(cnt)
    draws = np.random.default_rng(seed).integers(0, k, size=(reps, k))
    rates = hits[draws].sum(axis=1) / np.maximum(cnt[draws].sum(axis=1), 1)
    return {"n": int(len(y)), "dates": int(k), "rate": float(y.mean()), "lo": float(np.quantile(rates, 0.025)), "hi": float(np.quantile(rates, 0.975))}


def clustered_lift(y: np.ndarray, flag: np.ndarray, days: np.ndarray, reps: int = 400, seed: int = 11) -> dict:
    """Rate(flag) - rate(all), CI from a date-resampling bootstrap."""
    if len(y) == 0 or flag.sum() == 0:
        return {"lift": None, "lo": None, "hi": None}
    codes, _ = pd.factorize(days)
    k = codes.max() + 1
    h_all = np.bincount(codes, weights=y.astype(float), minlength=k)
    c_all = np.bincount(codes, minlength=k).astype(float)
    h_f = np.bincount(codes, weights=(y * flag).astype(float), minlength=k)
    c_f = np.bincount(codes, weights=flag.astype(float), minlength=k)
    draws = np.random.default_rng(seed).integers(0, k, size=(reps, k))
    lifts = h_f[draws].sum(1) / np.maximum(c_f[draws].sum(1), 1) - h_all[draws].sum(1) / np.maximum(c_all[draws].sum(1), 1)
    return {"lift": float(y[flag].mean() - y.mean()), "lo": float(np.quantile(lifts, 0.025)), "hi": float(np.quantile(lifts, 0.975))}


def auc(y: np.ndarray, p: np.ndarray) -> float:
    ranks = pd.Series(p).rank(method="average").to_numpy()
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def clustered_auc(y: np.ndarray, p: np.ndarray, days: np.ndarray, reps: int = 100, seed: int = 5) -> dict:
    codes, _ = pd.factorize(days)
    k = codes.max() + 1
    order = np.argsort(codes, kind="stable")
    bounds = np.searchsorted(codes[order], np.arange(k + 1))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, k, size=k)
        idx = np.concatenate([order[bounds[i] : bounds[i + 1]] for i in pick])
        vals.append(auc(y[idx], p[idx]))
    return {"auc": auc(y, p), "lo": float(np.nanquantile(vals, 0.025)), "hi": float(np.nanquantile(vals, 0.975))}


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    qs = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    if len(qs) < 2:
        return [{"p_lo": float(qs[0]), "p_hi": float(qs[0]), "n": int(len(p)), "pred": float(p.mean()), "obs": float(y.mean())}]
    idx = np.clip(np.searchsorted(qs, p, side="right") - 1, 0, len(qs) - 2)
    out = []
    for b in range(len(qs) - 1):
        m = idx == b
        if m.any():
            out.append({"p_lo": float(qs[b]), "p_hi": float(qs[b + 1]), "n": int(m.sum()), "pred": float(p[m].mean()), "obs": float(y[m].mean())})
    return out


class LogitModel:
    """Standardised L2 logistic regression."""

    def __init__(self, features: list[str]):
        self.features = features

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "LogitModel":
        from sklearn.linear_model import LogisticRegression

        A = X[self.features].to_numpy(np.float64)
        self.mu = np.nanmean(A, axis=0)
        self.sd = np.nanstd(A, axis=0)
        self.sd[~np.isfinite(self.sd) | (self.sd == 0)] = 1.0
        self.mu[~np.isfinite(self.mu)] = 0.0
        self.m = LogisticRegression(C=0.05, max_iter=500).fit(self._z(A), y)
        return self

    def _z(self, A: np.ndarray) -> np.ndarray:
        Z = (A - self.mu) / self.sd
        return np.nan_to_num(Z, nan=0.0)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(self._z(X[self.features].to_numpy(np.float64)))[:, 1]


class BoostModel:
    """Shallow gradient boosting; learns the confluences a linear model can't."""

    def __init__(self, features: list[str]):
        self.features = features

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "BoostModel":
        from sklearn.ensemble import HistGradientBoostingClassifier

        self.m = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=15, min_samples_leaf=400,
            l2_regularization=1.0, early_stopping=True, validation_fraction=0.15, random_state=0,
        ).fit(X[self.features].to_numpy(np.float32), y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(X[self.features].to_numpy(np.float32))[:, 1]


class Calibrated:
    """A fitted model plus an isotonic map learnt on the validation slice."""

    def __init__(self, model, iso, name: str):
        self.model, self.iso, self.name = model, iso, name
        self.features = model.features

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.iso.predict(self.model.predict(X))


def analyse(rows: pd.DataFrame, lag: pd.DataFrame, cfg: TfConfig, n_symbols: int) -> tuple[dict, dict]:
    from sklearn.isotonic import IsotonicRegression

    days = np.sort(rows["day"].unique())
    nd = len(days)
    fit_end = days[int(nd * 0.48)]
    val_end = days[int(nd * 0.60)]
    purge_days = 5 if cfg.tf == "1h" else cfg.horizon
    test_start = days[min(nd - 1, int(nd * 0.60) + purge_days)]

    def iso(d: int) -> str:
        return str(pd.Timestamp(int(d) * 86_400_000_000_000).date())

    out: dict = {
        "version": 2,
        "config": asdict(cfg),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": n_symbols,
        "fit_period": [iso(days[0]), iso(fit_end)],
        "validation_period": [iso(fit_end), iso(val_end)],
        "test_period": [iso(test_start), iso(days[-1])],
        "sides": {},
    }
    models: dict = {}
    for side, label in ((1, "bottom"), (-1, "top")):
        S = rows[rows["side"] == side]
        fit = S[S["day"] < fit_end]
        val = S[(S["day"] >= fit_end) & (S["day"] < val_end)]
        te = S[S["day"] >= test_start]
        yte, dte = te["y"].to_numpy(), te["day"].to_numpy()
        s: dict = {
            "base_fit": clustered_rate(fit["y"].to_numpy(), fit["day"].to_numpy()),
            "base_test": clustered_rate(yte, dte),
            "fwd_atr_test_mean": float(te["fwd_atr_dir"].mean()),
            "signals": [],
        }
        train = S[S["day"] < val_end]
        for name, _, desc in BINARY_PAIRS:
            ftr = train[name].to_numpy() > 0.5
            fte = te[name].to_numpy() > 0.5
            s["signals"].append(
                {
                    "key": name,
                    "label": desc,
                    "train": {**clustered_rate(train["y"].to_numpy()[ftr], train["day"].to_numpy()[ftr]), **clustered_lift(train["y"].to_numpy(), ftr, train["day"].to_numpy())},
                    "test": {**clustered_rate(yte[fte], dte[fte]), **clustered_lift(yte, fte, dte)},
                    "test_fwd_atr": float(te.loc[fte, "fwd_atr_dir"].mean()) if fte.any() else None,
                }
            )

        # pairs ranked on TRAIN, reported on TEST
        ytr = train["y"].to_numpy()
        flags_tr = {n: train[n].to_numpy() > 0.5 for n in BINARY}
        flags_te = {n: te[n].to_numpy() > 0.5 for n in BINARY}
        ranked = []
        for i, a in enumerate(BINARY):
            for b in BINARY[i + 1 :]:
                m = flags_tr[a] & flags_tr[b]
                if m.sum() >= 300:
                    ranked.append((float(ytr[m].mean()), a, b))
        ranked.sort(reverse=True)
        s["top_pairs"] = []
        for rate_tr, a, b in ranked[:12]:
            m = flags_te[a] & flags_te[b]
            s["top_pairs"].append({"keys": [a, b], "train_rate": rate_tr, "test": {**clustered_rate(yte[m], dte[m]), **clustered_lift(yte, m, dte)}})

        # --- model selection on validation, one score on test
        candidates = {
            "logit_chart": LogitModel(FEATURES_CHART),
            "logit_all": LogitModel(FEATURES),
            "boost_chart": BoostModel(FEATURES_CHART),
            "boost_all": BoostModel(FEATURES),
        }
        yfit, yval, dval = fit["y"].to_numpy(), val["y"].to_numpy(), val["day"].to_numpy()
        ablation = {}
        fitted = {}
        for name, mdl in candidates.items():
            mdl.fit(fit, yfit)
            fitted[name] = mdl
            p_val = mdl.predict(val)
            p_te = mdl.predict(te)
            ablation[name] = {"val_auc": auc(yval, p_val), "test_auc": clustered_auc(yte, p_te, dte, reps=60)}
            gc.collect()
        best = max(ablation, key=lambda k: ablation[k]["val_auc"])
        iso_map = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(fitted[best].predict(val), yval)
        model = Calibrated(fitted[best], iso_map, best)
        p_te = model.predict(te)
        # tiers rank on the raw score: isotonic steps tie whole deciles together
        raw_te = fitted[best].predict(te)
        rel = reliability(yte, p_te)
        cuts = {q: float(np.quantile(raw_te, q)) for q in (0.8, 0.9, 0.95)}
        s["model"] = {
            "chosen": best,
            "chosen_on": "validation AUC",
            "features": model.features,
            "ablation": ablation,
            "test_auc": clustered_auc(yte, p_te, dte),
            "tiers": {
                f"top_{int(round((1 - q) * 100))}pct": {**clustered_rate(yte[raw_te >= c], dte[raw_te >= c]), **clustered_lift(yte, raw_te >= c, dte), "score_threshold": c}
                for q, c in cuts.items()
            },
            "reliability": rel,
            "calibration_max_abs_err": float(max(abs(r["pred"] - r["obs"]) for r in rel if r["n"] >= 200)) if any(r["n"] >= 200 for r in rel) else None,
        }
        if best.startswith("logit"):
            coefs = fitted[best].m.coef_[0]
            s["model"]["drivers"] = sorted(
                [{"feature": f_, "weight": float(c)} for f_, c in zip(model.features, coefs)], key=lambda r: -abs(r["weight"])
            )[:12]
        else:
            from sklearn.inspection import permutation_importance

            sample = te.sample(min(len(te), 40_000), random_state=0)
            imp = permutation_importance(
                fitted[best].m, sample[model.features].to_numpy(np.float32), sample["y"].to_numpy(),
                scoring="roc_auc", n_repeats=3, random_state=0,
            )
            s["model"]["drivers"] = sorted(
                [{"feature": f_, "weight": float(w)} for f_, w in zip(model.features, imp.importances_mean)], key=lambda r: -abs(r["weight"])
            )[:12]
        auc_lo = s["model"]["test_auc"]["lo"]
        cal = s["model"]["calibration_max_abs_err"]
        s["model"]["passes"] = bool(auc_lo > 0.52 and cal is not None and cal < 0.06)
        models[label] = model

        lg = lag[lag["side"] == side] if len(lag) else lag
        if len(lg):
            s["lag"] = {"flips": int(len(lg)), "flip_lag_bars_median": float(lg["flip_lag_bars"].median()), "flip_move_atr_median": float(lg["flip_move_atr"].median())}
            for name in ("cue", "macd", "div"):
                has = lg[f"{name}_lag_bars"].notna()
                s["lag"][f"{name}_share"] = float(has.mean())
                s["lag"][f"{name}_lag_bars_median"] = float(lg.loc[has, f"{name}_lag_bars"].median()) if has.any() else None
                s["lag"][f"{name}_move_atr_median"] = float(lg.loc[has, f"{name}_move_atr"].median()) if has.any() else None
        out["sides"][label] = s
        del fit, val, te, train, S
        gc.collect()
    return out, models


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", choices=sorted(CONFIGS), default="1d")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()
    cfg = CONFIGS[args.tf]
    src = DATA_1H if cfg.tf == "1h" else DATA_1D
    syms = sorted(p.stem for p in src.glob("*.parquet"))
    if cfg.tf == "1h":
        syms = [s for s in syms if (DATA_1D / f"{s}.parquet").is_file()]
    if args.limit:
        keep = set(syms[: args.limit]) | {MARKET_SYMBOL}
        syms = [s for s in syms if s in keep]

    flags = [fr for fr in Parallel(n_jobs=args.jobs)(delayed(_breadth_flags)(s, cfg) for s in syms) if fr is not None]
    market = load_bars(MARKET_SYMBOL, cfg)
    if market is None:
        raise SystemExit(f"{MARKET_SYMBOL} bars missing for {cfg.tf}")
    ctx = market_context(flags, market[0])
    del flags
    gc.collect()

    res = Parallel(n_jobs=args.jobs)(delayed(symbol_rows)(s, i, cfg, ctx) for i, s in enumerate(syms))
    res = [r for r in res if r is not None]
    rows = pd.concat([r[0] for r in res if len(r[0])], ignore_index=True)
    lag = pd.concat([r[1] for r in res if len(r[1])], ignore_index=True)
    trades = pd.concat([r[2] for r in res if len(r[2])], ignore_index=True)
    del res
    gc.collect()
    summary, models = analyse(rows, lag, cfg, n_symbols=len(syms))
    days = np.sort(trades["day"].unique())
    summary["trades"] = trade_table(trades, int(days[len(days) // 2]))
    summary["trades_rule"] = "enter trigger close; stop 0.1 ATR beyond leg extreme; target 2R; exit at 3x horizon marked to close (clipped to [-1R, 2R]). avg_r CI resamples dates. Breakeven avg_r is 0 before costs/premium."
    out = OUT_DIR / cfg.tf
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    joblib.dump(models, out / "model.joblib", compress=3)
    print(json.dumps({"rows": int(len(rows)), "symbols": len(syms), "out": str(out)}))


if __name__ == "__main__":
    # Re-enter through the package so pickled model classes resolve to
    # `edge.research.reversal_study`, not `__main__`, when the engine loads them.
    from edge.research import reversal_study as _module

    _module.main()
